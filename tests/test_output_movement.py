"""작업·선택 결과물 이동의 파일 경계, 부분 실패와 DB 경로 보존을 검증합니다."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


def test_job_movement_includes_all_pages_current_paths_and_protected_outputs(tmp_path: Path) -> None:
    """종료 작업의 이미지·영상·이동 파일을 모두 옮기고 원래 JSON과 보호 상태를 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    image_paths = [f"anima/image-{image_number:03d}.png" for image_number in range(65)]
    for relative_path in image_paths:
        image_path = server.config.managed_output_directory / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 48)).save(image_path)
    (server.config.managed_output_directory / "anima/movie.mp4").write_bytes(b"video")
    server.database.complete_request(request_id, [*image_paths, "anima/movie.mp4", "anima/missing.png"])
    server.database.set_job_deletion_protection("catalog-job", True)
    original_history = read_history_json(server.database.database_path)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        client.post("/api/outputs/sync")
        selection = client.get("/api/outputs/selection-candidates", params={"job_id": "catalog-job"}).json()
        assert len(selection["output_ids"]) == 66
        assert selection["deletable_output_ids"] == []
        assert client.post("/api/outputs/move", json={
            "source": image_paths[0], "destination_folder": "already-moved",
        }).status_code == 200
        old_preview_path = "already-moved/image-000.png"
        assert client.get(f"/api/outputs/preview/{old_preview_path}").status_code == 200
        movement_response = client.post("/api/jobs/catalog-job/outputs/move", json={"destination_folder": "archive"})
        assert movement_response.status_code == 200
        movement = movement_response.json()
        assert movement["moved_count"] == 66
        assert movement["skipped_count"] == 0
        assert movement["failures"] == []
        assert len(client.get("/api/outputs", params={"job_id": "catalog-job"}).json()["files"]) == 64
        listing = client.get("/api/outputs", params={"request_id": request_id, "page_size": 100}).json()
        assert listing["total"] == 66
        assert all(output_file["path"].startswith("archive/") and output_file["deletion_protected"] for output_file in listing["files"])
        assert (server.config.managed_output_directory / "archive/image-000.png").is_file()
        assert not (server.config.managed_output_directory / old_preview_path).exists()
        assert client.get(f"/api/outputs/preview/{old_preview_path}").status_code == 404
        assert not any(cache_key[0].name == "image-000.png" for cache_key in server.thumbnail_cache._cached_thumbnails)
        assert read_history_json(server.database.database_path) == original_history
        repeated = client.post("/api/jobs/catalog-job/outputs/move", json={"destination_folder": "archive"}).json()
        assert repeated["moved_count"] == 0
        assert repeated["skipped_count"] == 66
        assert repeated["failures"] == []
    with sqlite3.connect(server.database.database_path) as connection:
        assert connection.execute(
            "SELECT original_relative_path,relative_path,request_id,job_id FROM output_files "
            "WHERE original_relative_path=?", (image_paths[0],),
        ).fetchone() == (image_paths[0], "archive/image-000.png", request_id, "catalog-job")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bulk_movement_reports_partial_failures_without_overwriting_files(tmp_path: Path) -> None:
    """중복 ID·동일 폴더는 한 번 처리하고 충돌·누락·삭제된 파일의 실패만 별도 반환합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    recorded_paths = ["anima/good.png", "anima/collision.png", "anima/missing.png", "anima/deleted.png", "sorted/same.png"]
    for relative_path in ["anima/good.png", "anima/collision.png", "sorted/same.png", "sorted/collision.png"]:
        output_path = server.config.managed_output_directory / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(relative_path.encode())
    server.database.complete_request(request_id, recorded_paths)
    with sqlite3.connect(server.database.database_path) as connection:
        connection.execute("UPDATE output_files SET is_deleted=1,is_available=0 WHERE relative_path='anima/deleted.png'")
        output_ids = dict(connection.execute("SELECT relative_path,output_id FROM output_files"))
    selected_ids = [output_ids[relative_path] for relative_path in recorded_paths]
    with TestClient(application) as client:
        assert client.post("/api/outputs/move-batch", json={"output_ids": selected_ids, "destination_folder": "sorted"}).status_code == 401
        client.post("/api/login", json={"password": "test"})
        movement = client.post("/api/outputs/move-batch", json={
            "output_ids": [*selected_ids, selected_ids[0], 999999], "destination_folder": "sorted",
        }).json()
        assert movement["moved_output_ids"] == [output_ids["anima/good.png"]]
        assert movement["skipped_output_ids"] == [output_ids["sorted/same.png"]]
        assert len(movement["failures"]) == 4
        assert {failure["output_id"] for failure in movement["failures"]} == {
            output_ids["anima/collision.png"], output_ids["anima/missing.png"], output_ids["anima/deleted.png"], 999999,
        }
        assert (server.config.managed_output_directory / "sorted/collision.png").read_bytes() == b"sorted/collision.png"
        assert (server.config.managed_output_directory / "anima/collision.png").read_bytes() == b"anima/collision.png"
        assert (server.config.managed_output_directory / "sorted/good.png").read_bytes() == b"anima/good.png"
        assert server.output_catalog.is_deleted("anima/deleted.png")


@pytest.mark.parametrize("failure_mode", ["database", "filesystem"])
def test_movement_failure_preserves_original_path_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str) -> None:
    """DB 변경 또는 실제 이동에 실패하면 원래 파일과 catalog 경로를 유지합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    image_path = server.config.managed_output_directory / "image.png"
    image_path.write_bytes(b"preserved image")
    server.database.complete_request(request_id, ["image.png"])
    output_id = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
    if failure_mode == "database":
        with sqlite3.connect(server.database.database_path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_movement BEFORE UPDATE OF relative_path ON output_files "
                "BEGIN SELECT RAISE(ABORT, 'database failure'); END"
            )
    else:
        def reject_physical_movement(*arguments, **keyword_arguments) -> None:
            """파일이 열려 있어 OS가 이동을 거부하는 상황을 재현합니다."""

            raise PermissionError("image is open")

        monkeypatch.setattr("home_server.application.shutil.move", reject_physical_movement)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        result = client.post("/api/outputs/move-batch", json={"output_ids": [output_id], "destination_folder": "sorted"}).json()
        assert result["moved_count"] == 0
        assert len(result["failures"]) == 1
        assert image_path.read_bytes() == b"preserved image"
        assert server.output_catalog.get_output_path_for_move(output_id) == "image.png"
        assert not (server.config.managed_output_directory / "sorted/image.png").exists()


def test_movement_validates_job_status_destination_ids_and_stale_paths(tmp_path: Path) -> None:
    """진행 중 작업·잘못된 목적지·ID·경합으로 바뀐 경로는 파일 이동 전에 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    image_path = server.config.managed_output_directory / "image.png"
    image_path.write_bytes(b"image")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/jobs/missing/outputs/move", json={"destination_folder": "sorted"}).status_code == 404
        assert client.post("/api/jobs/catalog-job/outputs/move", json={"destination_folder": "sorted"}).status_code == 409
        server.database.complete_request(request_id, ["image.png"])
        output_id = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
        assert client.post("/api/outputs/move-batch", json={"output_ids": [], "destination_folder": "sorted"}).status_code == 422
        assert client.post("/api/outputs/move-batch", json={"output_ids": [-1], "destination_folder": "sorted"}).status_code == 422
        assert client.post("/api/outputs/move-batch", json={"output_ids": [output_id], "destination_folder": "../outside"}).status_code == 422

        def reject_unexpected_movement() -> None:
            """현재 경로의 ID가 다르면 FS callback을 호출하지 않아야 합니다."""

            raise AssertionError("stale path must not move a file")

        with pytest.raises(ValueError, match="경로가 변경"):
            server.output_catalog.move_file("image.png", "sorted/image.png", reject_unexpected_movement, expected_output_id=output_id + 1)
        assert image_path.is_file()
        assert server.output_catalog.get_output_path_for_move(output_id) == "image.png"
