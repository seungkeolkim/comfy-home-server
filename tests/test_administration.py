"""임시 DB에서 관리자 백업·복원 경합과 파일을 변경하지 않는 진단을 검증합니다."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.administration import AdministrationStore, diagnose_connections, storage_overview
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request


def create_administration_backup(client: TestClient, description: str = "정리 전") -> dict:
    """인증된 테스트 Client에서 설명이 있는 수동 백업을 생성합니다."""

    response = client.post("/api/administration/backups", json={"description": description})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("method,endpoint,payload", [
    ("GET", "/api/administration/backups", None),
    ("GET", "/api/administration/history", None),
    ("POST", "/api/administration/backups", {"description": ""}),
    ("POST", "/api/administration/diagnostics", None),
    ("POST", "/api/administration/storage", None),
    ("POST", "/api/administration/backups/unknown/restore", {"backup_confirmed": True}),
    ("DELETE", "/api/administration/backups/unknown", {"confirmed": True}),
])
def test_administration_requires_session(tmp_path: Path, method: str, endpoint: str, payload: dict | None) -> None:
    """관리자 버튼 위치와 무관하게 모든 관리 API에 기존 인증을 적용합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        assert client.request(method, endpoint, json=payload).status_code == 401


def test_backup_restore_keeps_administration_and_physical_files(tmp_path: Path) -> None:
    """DB만 되돌리고 설명·이력·실제 파일은 복원 이전 상태를 유지합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    server.database.save_preset("before", "복원할 Prompt", "anima", {"prompt": "before"})
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client, "  정리 전  ")
        assert backup["description"] == "정리 전"
        backup_path = server.administration.backup_directory / backup["file_name"]
        snapshot_bytes = backup_path.read_bytes()
        with closing(sqlite3.connect(backup_path)) as connection:
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='database_backups'").fetchone() is None
        server.database.save_preset("after", "사라질 Prompt", "anima", {"prompt": "after"})
        output_path = server.config.managed_output_directory / "after.png"
        output_path.write_bytes(b"keep generated file")
        input_directory = server.config.runtime_directory / "favorite_inputs"
        input_directory.mkdir()
        input_path = input_directory / "after.png"
        input_path.write_bytes(b"keep input file")
        description_response = client.patch(f"/api/administration/backups/{backup['backup_id']}/description", json={"description": "복원 기준"})
        assert description_response.status_code == 200
        assert backup_path.read_bytes() == snapshot_bytes
        restore_response = client.post(f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True})
        assert restore_response.status_code == 200, restore_response.text
        assert [preset["preset_id"] for preset in server.database.list_presets()] == ["before"]
        assert output_path.read_bytes() == b"keep generated file"
        assert input_path.read_bytes() == b"keep input file"
        assert backup_path.read_bytes() == snapshot_bytes
        listing = client.get("/api/administration/backups").json()
        assert listing["items"][0]["description"] == "복원 기준"
        assert listing["items"][0]["restorable"] is True
        assert len(list(server.administration.backup_directory.iterdir())) == 1
        history = client.get("/api/administration/history").json()["items"]
        assert [item["action"] for item in history] == ["restore", "description", "backup"]
        assert all(item["status"] == "completed" for item in history)
        assert client.get("/api/session").json() == {"authenticated": True}
        assert client.request("DELETE", f"/api/administration/backups/{backup['backup_id']}", json={"confirmed": True}).status_code == 200
        assert not backup_path.exists()
        assert client.get("/api/administration/backups").json()["items"] == []
        assert client.get("/api/administration/history").json()["items"][0]["action"] == "delete"


def test_schema_is_compared_again_at_restore_and_failures_are_recorded(tmp_path: Path) -> None:
    """목록 이후 백업 version이 달라져도 복원을 거절하며 기존 DB를 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client)
        assert client.get("/api/administration/backups").json()["items"][0]["restorable"] is True
        with closing(sqlite3.connect(server.administration.backup_directory / backup["file_name"])) as connection:
            connection.execute("PRAGMA user_version = 13")
        listing = client.get("/api/administration/backups").json()["items"][0]
        assert listing["schema_version"] == 13
        assert listing["restorable"] is False
        server.database.save_preset("keep", "보존", "anima", {"prompt": "keep"})
        response = client.post(f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True})
        assert response.status_code == 422
        assert server.database.list_presets()[0]["preset_id"] == "keep"
        assert client.get("/api/administration/history").json()["items"][0]["status"] == "failed"
        assert len(list(server.administration.backup_directory.iterdir())) == 1


def test_confirmation_and_single_line_description_are_required(tmp_path: Path) -> None:
    """미확인 복원·삭제와 잘못된 설명은 어떤 파일 변경도 만들지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/administration/backups", json={"description": "first\nsecond"}).status_code == 422
        assert client.post("/api/administration/backups", json={"description": "x" * 201}).status_code == 422
        backup = create_administration_backup(client)
        for payload in ({}, {"backup_confirmed": False}):
            assert client.post(f"/api/administration/backups/{backup['backup_id']}/restore", json=payload).status_code == 422
        assert client.request("DELETE", f"/api/administration/backups/{backup['backup_id']}", json={"confirmed": False}).status_code == 422
        assert len(client.get("/api/administration/backups").json()["items"]) == 1


def test_restore_refuses_active_work_and_stops_historical_work(tmp_path: Path) -> None:
    """진행 중 작업은 복원을 막고 백업 당시의 활성 상태는 자동 재실행 없이 중단합니다."""

    comfy_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client)
        restore_url = f"/api/administration/backups/{backup['backup_id']}/restore"
        assert client.post(restore_url, json={"backup_confirmed": True}).status_code == 409
        server.database.update_request(request_id, "failed", "test finished")
        assert client.post(restore_url, json={"backup_confirmed": True}).status_code == 200
        assert server.database.list_active_requests() == []
        with server.database._connect() as connection:
            row = connection.execute("SELECT status,error_message FROM job_requests WHERE request_id=?", (request_id,)).fetchone()
        assert row["status"] == "stopped"
        assert "DB 복원" in row["error_message"]
        assert comfy_client.submissions == []


def test_existing_missing_and_corrupt_backups_remain_manageable(tmp_path: Path) -> None:
    """기존 백업을 발견하고 손상·누락 파일은 목록에서 복원 불가로 표시합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    store = application.state.home_server.administration
    broken_path = store.backup_directory / "broken.sqlite3"
    broken_path.write_bytes(b"not a database")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = client.get("/api/administration/backups").json()["items"][0]
        assert backup["source"] == "existing"
        assert backup["restorable"] is False
        broken_path.unlink()
        assert client.get("/api/administration/backups").json()["items"][0]["size_bytes"] is None
        assert client.request("DELETE", f"/api/administration/backups/{backup['backup_id']}", json={"confirmed": True}).status_code == 200


def test_backup_paths_cannot_escape_managed_directory(tmp_path: Path) -> None:
    """관리용 DB의 경로가 변조되어도 외부 파일 삭제와 복원을 거절합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    store = application.state.home_server.administration
    outside_path = tmp_path / "runtime" / "outside.sqlite3"
    outside_path.write_bytes(b"keep outside")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client)
        with store.connect() as connection:
            connection.execute("UPDATE database_backups SET file_name='../outside.sqlite3' WHERE backup_id=?", (backup["backup_id"],))
        assert client.request("DELETE", f"/api/administration/backups/{backup['backup_id']}", json={"confirmed": True}).status_code == 422
        assert outside_path.read_bytes() == b"keep outside"


def test_diagnostics_and_storage_do_not_modify_db_or_files(tmp_path: Path) -> None:
    """복원 이후의 누락·미등록·즐겨찾기 연결 문제를 수정하지 않고 정확히 구분합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    server.database.complete_request(request_id, ["missing.png", "deleted.png"])
    output_directory = server.config.managed_output_directory
    (output_directory / "unregistered.png").write_bytes(b"unregistered")
    (output_directory / "deleted.png").write_bytes(b"keep deleted file")
    input_directory = server.config.runtime_directory / "favorite_inputs"
    input_directory.mkdir()
    (input_directory / "orphan.png").write_bytes(b"keep orphan")
    verification_directory = server.config.runtime_directory / "verification"
    verification_directory.mkdir()
    (verification_directory / "report.txt").write_bytes(b"other runtime")
    with server.database._connect() as connection:
        connection.execute("UPDATE output_files SET is_deleted=1 WHERE relative_path='deleted.png'")
        connection.execute(
            "INSERT INTO request_favorites (favorite_id,source_request_id,workflow,description,snapshot_json,input_asset_name,created_at) "
            "VALUES ('favorite','request','minimax_h3','','{}','missing.png','2026-10-26')",
        )
    original_database = server.database.database_path.read_bytes()
    diagnosis = diagnose_connections(server)
    expected_paths = {
        "missing_outputs": ["missing.png"], "unregistered_outputs": ["unregistered.png"],
        "deleted_outputs_present": ["deleted.png"], "missing_favorite_inputs": ["missing.png"],
        "unreferenced_favorite_inputs": ["orphan.png"],
    }
    for finding_name, paths in expected_paths.items():
        assert diagnosis["findings"][finding_name] == {"total": 1, "paths": paths}
    storage = storage_overview(server)
    output_usage = next(item for item in storage["items"] if item["name"] == "결과물")
    assert output_usage["size_bytes"] == len(b"unregistered") + len(b"keep deleted file")
    assert output_usage["file_count"] == 2
    assert output_usage["disk_free_bytes"] > 0
    other_usage = next(item for item in storage["items"] if item["name"] == "기타 runtime")
    assert other_usage["file_count"] == 1
    assert other_usage["size_bytes"] == len(b"other runtime")
    assert server.database.database_path.read_bytes() == original_database
    assert (input_directory / "orphan.png").read_bytes() == b"keep orphan"
    assert list(server.administration.backup_directory.iterdir()) == []


def test_restore_waits_for_requests_and_rejects_new_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """진행 중 HTTP 쓰기를 기다리고 실제 복원 중 새 변경 요청을 거절합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    store = application.state.home_server.administration
    restore_started = threading.Event()
    release_restore = threading.Event()
    original_restore = store.restore_backup

    def blocked_restore(backup_id: str, ensure_idle) -> dict:
        """Gate가 닫힌 구간을 다른 HTTP 요청과 경합시킵니다."""

        restore_started.set()
        assert release_restore.wait(5)
        return original_restore(backup_id, ensure_idle)

    monkeypatch.setattr(store, "restore_backup", blocked_restore)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client)
        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.post, f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True})
            assert restore_started.wait(5)
            try:
                assert client.post("/api/administration/backups", json={"description": "must not run"}).status_code == 503
                assert client.get("/api/jobs").status_code == 503
                assert client.get("/api/session").status_code == 200
                assert client.post(f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True}).status_code == 409
            finally:
                release_restore.set()
            assert response_future.result(timeout=5).status_code == 200
        assert client.get("/api/administration/backups").status_code == 200


def test_management_history_survives_restart_and_marks_unfinished_operations(tmp_path: Path) -> None:
    """재시작 전 끝나지 않은 관리자 작업을 성공으로 추정하지 않고 중단으로 기록합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    store = application.state.home_server.administration
    store.start_operation("backup", None, None, "interrupted operation")
    restarted_store = AdministrationStore(store.operational_database_path)
    history = restarted_store.list_history(1)
    assert history["items"][0]["status"] == "interrupted"
    assert history["items"][0]["finished_at"] is not None


def test_restore_drains_existing_http_change_before_loading_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """복원 시작 전에 접수된 설명 쓰기가 끝난 뒤 복원을 진행하고 관리 설명은 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    update_started = threading.Event()
    release_update = threading.Event()
    original_update = server.administration.update_description

    def delayed_description_update(backup_id: str, description: str) -> dict:
        """먼저 시작한 HTTP 요청의 완료 시점을 제어합니다."""

        update_started.set()
        assert release_update.wait(5)
        return original_update(backup_id, description)

    monkeypatch.setattr(server.administration, "update_description", delayed_description_update)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = create_administration_backup(client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            update_future = executor.submit(client.patch, f"/api/administration/backups/{backup['backup_id']}/description", json={"description": "보존할 새 설명"})
            assert update_started.wait(5)
            restore_future = executor.submit(client.post, f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True})
            deadline = time.monotonic() + 5
            while not server.administration_maintenance.restoring and time.monotonic() < deadline:
                time.sleep(0.01)
            try:
                assert server.administration_maintenance.restoring is True
                assert restore_future.done() is False
            finally:
                release_update.set()
            assert update_future.result(timeout=5).status_code == 200
            assert restore_future.result(timeout=5).status_code == 200
        assert server.administration.get_backup(backup["backup_id"])["description"] == "보존할 새 설명"


def test_restore_preparation_failure_keeps_operational_db(tmp_path: Path) -> None:
    """Version은 같지만 읽을 수 없는 구조의 백업은 운영 DB를 덮어쓰기 전에 거절합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    invalid_path = server.administration.backup_directory / "incomplete.sqlite3"
    with closing(sqlite3.connect(invalid_path)) as connection:
        connection.execute("PRAGMA user_version = 14")
    server.database.save_preset("keep", "보존", "anima", {"prompt": "keep"})
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        backup = client.get("/api/administration/backups").json()["items"][0]
        assert backup["restorable"] is True
        response = client.post(f"/api/administration/backups/{backup['backup_id']}/restore", json={"backup_confirmed": True})
        assert response.status_code == 409
        assert server.database.list_presets()[0]["preset_id"] == "keep"
        assert client.get("/api/administration/history").json()["items"][0]["status"] == "failed"
