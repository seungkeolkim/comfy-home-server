"""결과물 column 백필, index 조회, 생성·이동·삭제의 목록 일관성을 검증합니다."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.database import Database
from home_server.output_catalog import OUTPUT_SORT_ORDER, OutputCatalog
from test_application import FakeComfyClient, create_processing_test_app


def add_catalog_test_request(database: Database, job_id: str = "catalog-job") -> str:
    """공통 입력과 확정 설정이 다른 요청을 만들어 metadata 우선순위를 확인합니다."""

    request_id = f"{job_id}-request"
    database.add_job(job_id, "anima", "metadata 검증", [{
        "request_id": request_id,
        "status": "pending",
        "output_stem": "anima/example",
        "detail": {
            "settings": {"width": 640, "height": 480},
            "body": {"prompt": "보존할 입력"},
            "resolved": {
                "settings": {"width": 768, "height": 512},
                "prompt": "보존할 확정 Prompt",
                "extra_metadata": {"preserve": True},
            },
        },
    }])
    return request_id


def read_history_json(database_path: Path) -> dict[str, list[tuple]]:
    """원래 JSON 문자열을 decode하지 않고 그대로 비교할 수 있게 읽습니다."""

    with sqlite3.connect(database_path) as connection:
        return {
            "inputs": connection.execute("SELECT * FROM job_inputs ORDER BY job_id").fetchall(),
            "results": connection.execute("SELECT * FROM request_results ORDER BY request_id").fetchall(),
        }


def test_schema_nine_backfill_preserves_json_and_hides_missing_files(tmp_path: Path) -> None:
    """백필은 원래 JSON을 변경하지 않고 요청 해상도·파일명 시각·seed를 추가 저장합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    request_id = add_catalog_test_request(database)
    existing_path = "anima/261015_090102_18446744073709551615.png"
    missing_path = "anima/261015_090103_1.png"
    database.complete_request(request_id, [existing_path, missing_path, "../outside.png"])
    original_json = read_history_json(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE output_files")
        connection.execute("PRAGMA user_version = 9")

    Database(database_path)
    assert read_history_json(database_path) == original_json
    managed_directory = tmp_path / "managed"
    (managed_directory / "anima").mkdir(parents=True)
    (managed_directory / existing_path).write_bytes(b"file contents are not read during backfill")
    catalog = OutputCatalog(database_path)
    assert catalog.synchronize(managed_directory) == {
        "available": 1, "added": 0, "availability_changes": 1,
    }
    listing = catalog.list_files(1, 24)
    assert listing["total"] == 1
    assert listing["files"][0]["width"] == 768
    assert listing["files"][0]["height"] == 512
    assert listing["files"][0]["seed"] == 18446744073709551615
    assert listing["files"][0]["generated_at"] == datetime(2026, 10, 15, 9, 1, 2).timestamp()
    assert listing["files"][0]["dimensions_source"] == "settings"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM output_files").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    backup_paths = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
    assert read_history_json(backup_paths[0]) == original_json
    Database(database_path)
    assert read_history_json(database_path) == original_json
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


@pytest.mark.parametrize("completion_method", ["individual", "monitor"])
def test_completion_registers_outputs_and_retains_resolved_json(tmp_path: Path, completion_method: str) -> None:
    """개별 완료와 감시 완료 모두 같은 transaction에서 목록 column을 채웁니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    request_id = add_catalog_test_request(database)
    output_path = "anima/261015_090102_13.png"
    if completion_method == "individual":
        database.complete_request(request_id, [output_path])
    else:
        updates = [{"request_id": request_id, "status": "completed", "output_paths": [output_path]}]
        assert database.apply_request_states(updates) == updates
        assert database.apply_request_states(updates) == []
    listing = OutputCatalog(database.database_path).list_files(1, 24, request_id=request_id)
    assert listing["total"] == 1
    assert listing["files"][0]["path"] == output_path
    assert listing["files"][0]["width"] == 768
    assert database.get_request(request_id)["result"]["extra_metadata"] == {"preserve": True}
    assert database.get_request(request_id)["result"]["output_paths"] == [output_path]


def test_catalog_queries_use_indexes_without_json_or_filesystem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """전체·작업·요청 조회는 index 순서대로 페이지를 읽고 JSON·FS를 호출하지 않습니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    request_id = add_catalog_test_request(database)
    output_paths = [f"anima/261015_090102_{seed}.png" for seed in (3, 20, 18446744073709551615)]
    database.complete_request(request_id, output_paths)
    catalog = OutputCatalog(database.database_path)

    def reject_extra_lookup(*arguments, **keyword_arguments):
        """일반 목록에서 JSON decode나 FS lookup을 시도하면 실패합니다."""

        raise AssertionError("indexed listing must not read JSON or filesystem metadata")

    with monkeypatch.context() as listing_patch:
        listing_patch.setattr(json, "loads", reject_extra_lookup)
        listing_patch.setattr(Path, "stat", reject_extra_lookup)
        listing_patch.setattr("home_server.output_catalog.iterate_output_directory_entries", reject_extra_lookup)
        for filters in ({}, {"job_id": "catalog-job"}, {"request_id": request_id}):
            listing = catalog.list_files(1, 2, **filters)
            assert listing["total"] == 3
            assert [output_file["seed"] for output_file in listing["files"]] == [18446744073709551615, 20]
            assert catalog.list_files(2, 2, **filters)["files"][0]["seed"] == 3

    with sqlite3.connect(database.database_path) as connection:
        for filter_sql, query_parameters, expected_index in (
            ("", (), "output_files_listing"),
            ("AND job_id=?", ("catalog-job",), "output_files_job_listing"),
            ("AND request_id=?", (request_id,), "output_files_request_listing"),
        ):
            query_plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT relative_path FROM output_files "
                f"WHERE is_available=1 {filter_sql} ORDER BY {OUTPUT_SORT_ORDER} LIMIT 24",
                query_parameters,
            ).fetchall()
            plan_text = " ".join(plan_row[3] for plan_row in query_plan)
            assert expected_index in plan_text
            assert "TEMP B-TREE" not in plan_text
    with pytest.raises(LookupError):
        catalog.list_files(1, 24, job_id="missing-job")
    with pytest.raises(LookupError):
        catalog.list_files(1, 24, request_id="missing-request")


def test_folder_prefix_preserves_case_and_literal_wildcard_characters(tmp_path: Path) -> None:
    """폴더 prefix를 기존 startswith와 동일하게 비교하고 SQL wildcard로 확장하지 않습니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    request_id = add_catalog_test_request(database)
    database.complete_request(request_id, [
        "anima/test_100%/261015_090102_1.png",
        "anima/testX100Y/261015_090102_2.png",
        "anima/Test_100%/261015_090102_3.png",
    ])
    catalog = OutputCatalog(database.database_path)
    listing = catalog.list_files(1, 24, prefix="anima/test_100%/")
    assert listing["total"] == 1
    assert listing["files"][0]["seed"] == 1


@pytest.mark.parametrize("delete_outputs", [False, True])
def test_output_move_and_history_deletion_keep_metadata(tmp_path: Path, delete_outputs: bool) -> None:
    """이동 파일은 원래 JSON과 metadata를 유지하고 파일 포함 삭제에서도 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    original_paths = ["anima/261015_090102_1.png", "anima/261015_090102_2.png"]
    for relative_path in original_paths:
        output_path = server.config.managed_output_directory / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"no image header lookup needed")
    server.database.complete_request(request_id, original_paths)
    original_json = read_history_json(server.database.database_path)
    with TestClient(application) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        move_response = client.post("/api/outputs/move", json={
            "source": original_paths[0], "destination_folder": "sorted",
        })
        assert move_response.status_code == 200
        moved_path = move_response.json()["path"]
        assert read_history_json(server.database.database_path) == original_json
        listing = client.get("/api/outputs", params={"job_id": "catalog-job"}).json()
        assert {output_file["path"] for output_file in listing["files"]} == {moved_path, original_paths[1]}
        assert all(output_file["dimensions_source"] == "settings" for output_file in listing["files"])
        deletion = client.delete("/api/jobs/catalog-job", params={"delete_outputs": delete_outputs})
        assert deletion.status_code == 200
        assert deletion.json()["deleted_files"] == int(delete_outputs)
        assert deletion.json()["missing_files"] == int(delete_outputs)
        remaining_files = client.get("/api/outputs").json()["files"]
        assert len(remaining_files) == (1 if delete_outputs else 2)
        assert all(output_file["job_id"] is None and output_file["width"] == 768 for output_file in remaining_files)
        assert (server.config.managed_output_directory / moved_path).is_file()
    with sqlite3.connect(server.database.database_path) as connection:
        assert connection.execute(
            "SELECT original_relative_path,request_id FROM output_files WHERE relative_path=?", (moved_path,),
        ).fetchone() == (original_paths[0], None)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_external_files_require_sync_and_actual_dimensions_are_not_stored(tmp_path: Path) -> None:
    """외부 변경은 명시적으로 반영하고 header fallback을 DB 실제 해상도로 백필하지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    external_path = server.config.managed_output_directory / "external.png"
    Image.new("RGB", (32, 48)).save(external_path)
    with TestClient(application) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        assert client.get("/api/outputs").json()["total"] == 0
        assert client.post("/api/outputs/sync").json()["added"] == 1
        external_file = client.get("/api/outputs").json()["files"][0]
        assert external_file["dimensions_source"] == "file"
        assert (external_file["width"], external_file["height"]) == (32, 48)
        with sqlite3.connect(server.database.database_path) as connection:
            assert connection.execute("SELECT requested_width,requested_height FROM output_files").fetchone() == (None, None)
        external_path.unlink()
        assert client.get("/api/outputs").json()["total"] == 1
        assert client.post("/api/outputs/sync").json()["availability_changes"] == 1
        assert client.get("/api/outputs").json()["total"] == 0
