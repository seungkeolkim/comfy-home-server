"""태그 Import의 두 정책, 변경 전 DB 백업, 오류 시 전체 rollback을 검증합니다."""

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.database import Database
from test_application import FakeComfyClient, create_processing_test_app


def read_database_snapshot(database_path: Path) -> dict:
    """모든 테이블과 schema 버전을 비교할 수 있는 독립 Snapshot을 읽습니다."""

    with closing(sqlite3.connect(database_path)) as connection:
        snapshot = {"schema_version": connection.execute("PRAGMA user_version").fetchone()[0]}
        table_names = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (table_name,) in table_names:
            snapshot[table_name] = sorted(connection.execute(f'SELECT * FROM "{table_name}"').fetchall(), key=repr)
    return snapshot


def prepare_tag_import_database(database: Database) -> None:
    """기존 태그와 독립적으로 보존할 Prompt·작업·즐겨찾기 데이터를 만듭니다."""

    database.save_tag_group("existing-group", "기존 조명", "LIGHTING", False)
    database.save_tag_group("untouched-group", "유지할 그룹", "OTHER", True)
    database.save_tag_entry("existing-tag", {
        "group_id": "existing-group", "name": "같은 이름", "content": "soft light", "weight": 5.0,
    })
    database.save_preset("saved-prompt", "기존 Prompt", "anima", {"prompt": "[LIGHTING]"})
    database.add_job("completed-job", "anima", "기존 작업", [{
        "request_id": "completed-request", "status": "completed", "output_stem": "old",
        "detail": {"selected_tags": [{"tag_id": "existing-tag", "content": "snapshot light"}]},
    }])
    with closing(sqlite3.connect(database.database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO request_favorites (favorite_id, source_request_id, source_job_id, workflow, description, "
            "snapshot_json, created_at) VALUES ('favorite', 'completed-request', 'completed-job', 'anima', '', ?, 'saved')",
            (json.dumps({"selected_tags": [{"tag_id": "existing-tag", "content": "favorite light"}]}),),
        )


def create_tag_import_document() -> dict:
    """기존 항목·동일 이름의 새 본문·공유 참조 그룹·빈 그룹을 가진 JSON을 만듭니다."""

    return {
        "format": "comfy-home-server.tags", "schema_version": 1,
        "groups": [
            {"name": "기존 조명", "tag_key": "LIGHTING", "tags": [
                {"name": "같은 이름", "content": "soft light", "weight": 1.0},
                {"name": "같은 이름", "content": "  warm light\n[DETAIL]  ", "weight": 2.5},
            ]},
            {"name": "다른 조명", "tag_key": "LIGHTING", "tags": [
                {"name": "태그", "content": "morning light"},
            ]},
            {"name": "빈 그룹", "tag_key": "EMPTY", "tags": []},
        ],
    }


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_tag_import_backs_up_database_and_applies_selected_policy(tmp_path: Path, mode: str) -> None:
    """정책별 결과와 변경 직전 전체 백업을 확인하고 다른 테이블은 그대로 보존합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    snapshot_before_import = read_database_snapshot(database.database_path)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": mode, "data": create_tag_import_document()})
        assert response.status_code == 200, response.text
        import_result = response.json()
        backup_path = database.database_path.parent / "backups" / import_result["backup_filename"]
        assert read_database_snapshot(backup_path) == snapshot_before_import
        with closing(sqlite3.connect(backup_path)) as backup_connection:
            assert backup_connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert backup_connection.execute("PRAGMA foreign_key_check").fetchall() == []

        exported_groups = client.get("/api/tags/export").json()["groups"]
        imported_group = next(group for group in exported_groups if group["name"] == "기존 조명")
        assert imported_group["tags"][1]["content"] == "  warm light\n[DETAIL]  "
        assert imported_group["tags"][1]["weight"] == 2.5
        if mode == "append":
            assert import_result["created_group_count"] == 2
            assert import_result["created_tag_count"] == 2
            assert import_result["skipped_tag_count"] == 1
            assert imported_group["tags"][0]["weight"] == 5.0
            assert database.get_tag_group("existing-group")["default_expanded"] is False
            assert database.get_tag_entry("existing-tag")["weight"] == 5.0
            assert len(exported_groups) == 4
            repeated_response = client.post("/api/tags/import", json={"mode": mode, "data": create_tag_import_document()})
            assert repeated_response.status_code == 200
            assert repeated_response.json()["created_group_count"] == 0
            assert repeated_response.json()["created_tag_count"] == 0
            assert repeated_response.json()["skipped_tag_count"] == 3
            assert client.get("/api/tags/export").json()["groups"] == exported_groups
        else:
            assert import_result["created_group_count"] == 3
            assert import_result["created_tag_count"] == 3
            assert import_result["skipped_tag_count"] == 0
            assert imported_group["tags"][0]["weight"] == 1.0
            assert database.get_tag_group("existing-group") is None
            assert database.get_tag_group("untouched-group") is None
            assert database.get_tag_entry("existing-tag") is None
            assert len(exported_groups) == 3

    snapshot_after_import = read_database_snapshot(database.database_path)
    for table_name, original_rows in snapshot_before_import.items():
        if table_name not in {"tag_groups", "tag_entries"}:
            assert snapshot_after_import[table_name] == original_rows


def test_replace_round_trip_preserves_duplicate_groups_and_original_text(tmp_path: Path) -> None:
    """같은 이름의 그룹·태그를 합치지 않고 export→replace→export 순서와 원문을 보존합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    for group_identifier in ("first", "second"):
        database.save_tag_group(group_identifier, "같은 그룹", "LIGHTING", False)
    for tag_identifier, content, weight in (("first-tag", '한글\n"따옴표" \\ [LIGHTING]', 5), ("second-tag", "본문", 0.25)):
        database.save_tag_entry(tag_identifier, {
            "group_id": "first", "name": "같은 이름", "content": content, "weight": weight,
        })
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        exported_document = client.get("/api/tags/export").json()
        response = client.post("/api/tags/import", json={"mode": "replace", "data": exported_document})
        assert response.status_code == 200, response.text
        assert client.get("/api/tags/export").json()["groups"] == exported_document["groups"]


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_tag_import_does_not_write_when_backup_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """백업 실패 시에는 삭제·추가를 시작하지 않고 기존 DB를 보존합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    original_snapshot = read_database_snapshot(database.database_path)

    def fail_database_backup(*arguments) -> None:
        """디스크 쓰기 실패를 재현하여 Import의 사전 백업 조건을 확인합니다."""

        raise OSError("backup disk unavailable")

    monkeypatch.setattr(database, "_create_verified_database_backup", fail_database_backup)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": mode, "data": create_tag_import_document()})
        assert response.status_code == 500
        assert "반영되지 않았습니다" in response.json()["detail"]
    assert read_database_snapshot(database.database_path) == original_snapshot


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_tag_import_rolls_back_all_writes_when_an_insert_fails(tmp_path: Path, mode: str) -> None:
    """중간 INSERT 실패 시 앞선 삭제·추가도 취소하고 정상 백업은 유지합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    with closing(sqlite3.connect(database.database_path)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER fail_import BEFORE INSERT ON tag_entries WHEN NEW.name='실패' "
            "BEGIN SELECT RAISE(ABORT, 'forced import failure'); END"
        )
    original_snapshot = read_database_snapshot(database.database_path)
    imported_document = create_tag_import_document()
    imported_document["groups"][-1]["tags"] = [{"name": "실패", "content": "rejected", "weight": 1.0}]
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": mode, "data": imported_document})
        assert response.status_code == 500
    assert read_database_snapshot(database.database_path) == original_snapshot
    backup_paths = list((database.database_path.parent / "backups").glob("*tag_import_*.sqlite3"))
    assert len(backup_paths) == 1
    assert read_database_snapshot(backup_paths[0]) == original_snapshot


@pytest.mark.parametrize("invalid_field,invalid_value", [
    ("format", "unknown"), ("schema_version", 2), ("schema_version", True),
    ("tag_key", "[LIGHTING]"), ("name", " "), ("content", " "), ("content", "a" * 8001),
    ("weight", 0), ("weight", -1), ("weight", "1.0"), ("weight", True), ("group_id", "internal-id"),
])
def test_invalid_tag_import_is_rejected_before_backup(tmp_path: Path, invalid_field: str, invalid_value) -> None:
    """형식·버전·본문·weight·내부 ID 오류는 백업이나 DB 변경 전에 거부합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    imported_document = create_tag_import_document()
    if invalid_field in {"format", "schema_version"}:
        imported_document[invalid_field] = invalid_value
    elif invalid_field == "tag_key":
        imported_document["groups"][0][invalid_field] = invalid_value
    else:
        imported_document["groups"][0]["tags"][0][invalid_field] = invalid_value
    original_snapshot = read_database_snapshot(database.database_path)
    with TestClient(app) as client:
        assert client.post("/api/tags/import", json={"mode": "replace", "data": imported_document}).status_code == 401
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        assert client.post("/api/tags/import", json={"mode": "replace", "data": imported_document}).status_code == 422
    assert read_database_snapshot(database.database_path) == original_snapshot
    assert not list((database.database_path.parent / "backups").glob("*tag_import_*.sqlite3"))


@pytest.mark.parametrize("ambiguity_source", ["database", "document"])
def test_append_rejects_ambiguous_groups_without_partial_writes(tmp_path: Path, ambiguity_source: str) -> None:
    """이름과 참조가 같은 그룹이 여러 개면 합치지 않고 기존 상태를 보존합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    imported_document = create_tag_import_document()
    if ambiguity_source == "database":
        database.save_tag_group("duplicate-group", "기존 조명", "LIGHTING", True)
    else:
        imported_document["groups"].append(imported_document["groups"][0])
    original_snapshot = read_database_snapshot(database.database_path)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": "append", "data": imported_document})
        assert response.status_code == 409
        assert "Append 대상을 정할 수 없습니다" in response.json()["detail"]
    assert read_database_snapshot(database.database_path) == original_snapshot


def test_empty_replace_removes_only_tag_definitions(tmp_path: Path) -> None:
    """빈 목록으로 전체 교체하더라도 태그 외 데이터와 변경 전 백업을 보존합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    original_snapshot = read_database_snapshot(database.database_path)
    imported_document = create_tag_import_document()
    imported_document["groups"] = []
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": "replace", "data": imported_document})
        assert response.status_code == 200
        assert client.get("/api/tags/export").json()["groups"] == []
    snapshot_after_import = read_database_snapshot(database.database_path)
    for table_name, original_rows in original_snapshot.items():
        if table_name not in {"tag_groups", "tag_entries"}:
            assert snapshot_after_import[table_name] == original_rows


def test_tag_import_releases_backup_file_immediately(tmp_path: Path) -> None:
    """Import 응답 직후 Windows에서도 백업 파일을 이동할 수 있도록 연결을 닫습니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/tags/import", json={"mode": "append", "data": create_tag_import_document()})
        assert response.status_code == 200
        backup_path = database.database_path.parent / "backups" / response.json()["backup_filename"]
        moved_backup_path = backup_path.with_suffix(".verified.sqlite3")
        backup_path.rename(moved_backup_path)
        assert moved_backup_path.is_file()
        moved_backup_path.rename(backup_path)


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_tag_import_backup_keeps_session_and_tag_reads_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """백업 중에도 Event Loop와 기존 태그 읽기가 응답하고 미완료 변경은 보이지 않습니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_tag_import_database(database)
    backup_started = threading.Event()
    release_backup = threading.Event()
    original_backup = database._create_verified_database_backup

    def delay_database_backup(*arguments) -> Path:
        """쓰기 예약 이후 백업을 잠시 멈춰 다른 요청의 응답을 확인합니다."""

        backup_started.set()
        assert release_backup.wait(5)
        return original_backup(*arguments)

    monkeypatch.setattr(database, "_create_verified_database_backup", delay_database_backup)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        original_tags = client.get("/api/tags").json()
        with ThreadPoolExecutor(max_workers=1) as executor:
            import_future = executor.submit(client.post, "/api/tags/import", json={"mode": mode, "data": create_tag_import_document()})
            try:
                assert backup_started.wait(2)
                started = time.monotonic()
                assert client.get("/api/session").status_code == 200
                assert client.get("/api/tags").json() == original_tags
                assert time.monotonic() - started < 1
                assert not import_future.done()
            finally:
                release_backup.set()
            assert import_future.result().status_code == 200
