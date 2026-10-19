"""작업 결과 입력의 최신 Catalog 조회, 출처 검증과 Snapshot 독립성을 확인합니다."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_application import create_processing_test_app
from test_minimax_generation import CapturingImageClient, add_input_images, wait_for_submissions
from test_output_catalog import add_catalog_test_request


def test_job_picker_lists_current_images_without_prompt_or_unavailable_files(tmp_path: Path) -> None:
    """작은 작업 목록을 페이지 조회하고 이동된 이미지·보호된 작업도 입력 후보로 제공합니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    output_ids = add_input_images(server, [("original/a.png", (64, 96)), ("other/b.png", (96, 64)), ("unlinked.png", (64, 64))])
    request_identifier = add_catalog_test_request(server.database, "source-job")
    server.database.complete_request(request_identifier, ["original/a.png", "other/b.png", "missing.png", "movie.mp4"])
    video_request_identifier = add_catalog_test_request(server.database, "video-only")
    server.database.complete_request(video_request_identifier, ["video.mp4"])
    server.output_catalog.synchronize(server.config.managed_output_directory)
    server.database.set_job_deletion_protection("source-job", True)
    with TestClient(application) as client:
        assert client.get("/api/outputs/input-jobs").status_code == 401
        assert client.get("/api/jobs/source-job/input-images").status_code == 401
        client.post("/api/login", json={"password": "test"})
        response = client.post("/api/outputs/move", json={"source": "original/a.png", "destination_folder": "moved"})
        assert response.status_code == 200, response.text
        jobs = client.get("/api/outputs/input-jobs", params={"page_size": 1}).json()
        assert jobs["total"] == 1
        assert jobs["items"][0]["job_id"] == "source-job"
        assert jobs["items"][0]["image_count"] == 2
        assert set(jobs["items"][0]) == {"job_id", "workflow", "description", "created_at", "image_count"}
        assert client.get("/api/outputs/input-jobs?page=2&page_size=1").json()["items"] == []
        candidates = client.get("/api/jobs/source-job/input-images").json()
        assert [image["path"] for image in candidates["files"]] == ["moved/a.png", "other/b.png"]
        assert candidates["files"][0]["output_id"] == output_ids["original/a.png"]
        assert client.get("/api/jobs/unknown/input-images").status_code == 404
        assert client.get("/api/outputs/input-jobs?page_size=101").status_code == 422
        with sqlite3.connect(server.database.database_path) as connection:
            connection.execute("UPDATE output_files SET is_deleted=1 WHERE relative_path='other/b.png'")
        assert client.get("/api/outputs/input-jobs").json()["items"][0]["image_count"] == 1


def test_selected_job_images_use_current_paths_and_survive_source_deletion(tmp_path: Path) -> None:
    """확정한 일부 이미지만 Snapshot으로 접수하며 이후 원본 삭제·새 결과물 추가의 영향을 받지 않습니다."""

    comfy_client = CapturingImageClient(block_upload=True)
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    output_ids = add_input_images(server, [("original/b.png", (100, 60)), ("other/a.png", (65, 97)), ("later.png", (32, 32))])
    source_request_identifier = add_catalog_test_request(server.database, "source-job")
    server.database.complete_request(source_request_identifier, ["original/b.png", "other/a.png"])
    selected_identifiers = [output_ids["original/b.png"], output_ids["other/a.png"]]
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            inspection = client.post("/api/outputs/input-images/inspect", json={"output_ids": selected_identifiers, "input_job_id": "source-job"})
            assert inspection.status_code == 200
            assert client.post("/api/outputs/move", json={"source": "original/b.png", "destination_folder": "moved"}).status_code == 200
            server.database.complete_request(source_request_identifier, ["original/b.png", "other/a.png", "later.png"])
            response = client.post("/api/batches", json={
                "workflow": "minimax_h3", "body": {"prompt": "new prompt"}, "input_scope": "job",
                "input_job_id": "source-job", "output_ids": selected_identifiers,
                "settings": {"generation_mode": "FL2VA", "resolution_mode": "automatic"},
            })
            assert response.status_code == 200, response.text
            assert len(response.json()["request_ids"]) == 2
            assert comfy_client.upload_started.wait(3)
            assert server.database.delete_job("source-job")
            (server.config.managed_output_directory / "other/a.png").unlink()
            (server.config.managed_output_directory / "moved/b.png").unlink()
            comfy_client.release_upload.set()
            wait_for_submissions(comfy_client, 2)
            job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
            settings = job["inputs"]["settings"]
            assert settings["input_scope"] == "job"
            assert settings["input_job_id"] == "source-job"
            assert settings["input_output_ids"] == list(reversed(selected_identifiers))
            assert (settings["width"], settings["height"]) == (65, 97)
            assert [request["result"]["source_image"]["path"] for request in job["requests"]] == ["other/a.png", "moved/b.png"]
            assert all(request["result"]["source_image"]["job_id"] == "source-job" for request in job["requests"])
            assert all(metadata["home_server_request"]["source_image"]["job_id"] == "source-job" for workflow, metadata in comfy_client.submissions)
    finally:
        comfy_client.release_upload.set()


@pytest.mark.parametrize("invalid_selection", ["foreign", "deleted", "missing-file", "missing-job", "video", "duplicate", "empty", "too-many", "wrong-scope", "no-source"])
def test_job_input_rejects_invalid_selection_atomically(tmp_path: Path, invalid_selection: str) -> None:
    """출처·현재 파일·개수 검증 실패는 새 작업이나 부분 제출·임시 파일을 남기지 않습니다."""

    comfy_client = CapturingImageClient()
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    output_ids = add_input_images(server, [("input.png", (64, 96)), ("foreign.png", (64, 96))])
    source_request_identifier = add_catalog_test_request(server.database, "source-job")
    (server.config.managed_output_directory / "movie.mp4").write_bytes(b"video")
    server.database.complete_request(source_request_identifier, ["input.png", "movie.mp4"])
    with sqlite3.connect(server.database.database_path) as connection:
        video_identifier = connection.execute("SELECT output_id FROM output_files WHERE relative_path='movie.mp4'").fetchone()[0]
    payload = {"workflow": "minimax_h3", "body": {"prompt": "test"}, "input_scope": "job", "input_job_id": "source-job", "output_ids": [output_ids["input.png"]]}
    if invalid_selection == "foreign":
        payload["output_ids"].append(output_ids["foreign.png"])
    elif invalid_selection == "deleted":
        with sqlite3.connect(server.database.database_path) as connection:
            connection.execute("UPDATE output_files SET is_deleted=1 WHERE relative_path='input.png'")
    elif invalid_selection == "missing-file":
        (server.config.managed_output_directory / "input.png").unlink()
    elif invalid_selection == "missing-job":
        payload["input_job_id"] = "unknown"
    elif invalid_selection == "video":
        payload["output_ids"] = [video_identifier]
    elif invalid_selection == "duplicate":
        payload["output_ids"] *= 2
    elif invalid_selection == "empty":
        payload["output_ids"] = []
    elif invalid_selection == "too-many":
        payload["output_ids"] = list(range(1, 102))
    elif invalid_selection == "wrong-scope":
        payload["input_scope"] = "single"
    elif invalid_selection == "no-source":
        del payload["input_job_id"]
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        if invalid_selection in {"foreign", "deleted", "missing-file", "missing-job", "video", "duplicate"}:
            assert client.post("/api/outputs/input-images/inspect", json={"output_ids": payload["output_ids"], "input_job_id": payload["input_job_id"]}).status_code == 422
        response = client.post("/api/batches", json=payload)
        assert response.status_code == 422, response.text
        assert client.get("/api/jobs").json()["total"] == 1
        assert not list(server.upload_directory.iterdir())
        assert not comfy_client.submissions
