"""제출된 작업 설명 수정의 입력 검증·권한·조회 일관성과 생성 기록 보존을 검증합니다."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


@pytest.mark.parametrize("request_status", ["running", "completed", "cancelled", "partial"])
@pytest.mark.parametrize("protected", [False, True])
def test_job_description_updates_only_display_text_in_any_job_state(tmp_path: Path, request_status: str, protected: bool) -> None:
    """삭제 보호·진행 상태와 무관하게 설명만 갱신하고 요청·입력·파일·생성 시각을 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    server.database.add_job("catalog-job", "anima", "original description", [
        {"request_id": f"source-{request_index}", "status": "pending", "output_stem": "generated",
         "detail": {"body": {"prompt": "preserve"}, "settings": {"width": 64, "height": 64}}}
        for request_index in range(2)
    ])
    request_identifier = "source-0"
    server.database.complete_request(request_identifier, ["existing.png"])
    server.database.update_request(request_identifier, "completed" if request_status == "partial" else request_status)
    server.database.update_request("source-1", "cancelled" if request_status == "partial" else request_status)
    output_path = server.config.managed_output_directory / "existing.png"
    output_path.write_bytes(b"preserve original image")
    server.database.set_job_deletion_protection("catalog-job", protected)
    original_history = read_history_json(server.database.database_path)
    with sqlite3.connect(server.database.database_path) as connection:
        original_requests = connection.execute("SELECT * FROM job_requests").fetchall()
        original_outputs = connection.execute("SELECT * FROM output_files").fetchall()
        original_created_at = connection.execute("SELECT created_at FROM jobs").fetchone()[0]
    endpoint = "/api/jobs/catalog-job/description"
    with TestClient(application) as client:
        assert client.patch(endpoint, json={"description": "new"}).status_code == 401
        client.post("/api/login", json={"password": "test"})
        assert client.get("/api/jobs/catalog-job").json()["status"] == request_status
        response = client.patch(endpoint, json={"description": "  바꾼 설명 <escaped>  "})
        assert response.status_code == 200
        assert response.json() == {"job_id": "catalog-job", "description": "바꾼 설명 <escaped>"}
        for url in ("/api/jobs/catalog-job", "/api/jobs/catalog-job/inputs", "/api/jobs?page=1"):
            payload = client.get(url).json()
            job = payload["items"][0] if "items" in payload else payload
            assert job["description"] == "바꾼 설명 <escaped>"
        assert client.get("/api/outputs/input-jobs").json()["items"][0]["description"] == "바꾼 설명 <escaped>"
        assert client.get("/api/jobs/catalog-job/input-images").json()["job"]["description"] == "바꾼 설명 <escaped>"
        assert client.patch(endpoint, json={"description": "바꾼 설명 <escaped>"}).status_code == 200
        assert client.patch(endpoint, json={"description": "  "}).json()["description"] == ""
        assert client.get("/api/jobs/catalog-job").json()["deletion_protected"] is protected
    assert read_history_json(server.database.database_path) == original_history
    assert output_path.read_bytes() == b"preserve original image"
    with sqlite3.connect(server.database.database_path) as connection:
        assert connection.execute("SELECT * FROM job_requests").fetchall() == original_requests
        assert connection.execute("SELECT * FROM output_files").fetchall() == original_outputs
        assert connection.execute("SELECT created_at FROM jobs").fetchone()[0] == original_created_at


def test_job_description_validates_single_line_length_and_missing_jobs(tmp_path: Path) -> None:
    """생성과 동일하게 200자·한 줄을 적용하고 잘못된 수정과 없는 작업을 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    add_catalog_test_request(server.database)
    endpoint = "/api/jobs/catalog-job/description"
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        for invalid_payload in ({}, {"description": None}, {"description": "a\nb"}, {"description": "a\rb"}, {"description": "가" * 201}):
            assert client.patch(endpoint, json=invalid_payload).status_code == 422
        assert client.patch(endpoint, json={"description": "가" * 200}).status_code == 200
        assert client.patch("/api/jobs/unknown/description", json={"description": "new"}).status_code == 404
