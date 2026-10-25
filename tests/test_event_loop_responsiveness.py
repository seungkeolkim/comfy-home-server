"""동기 처리 지연이 Event Loop의 조회·취소 응답을 막지 않는지 검증합니다."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from logging.handlers import RotatingFileHandler

from test_application import FakeComfyClient, create_processing_test_app


def prepare_responsiveness_jobs(database) -> None:
    """조회할 완료 작업과 취소할 100개 미접수 요청을 독립된 DB에 준비합니다."""

    database.add_job("completed", "anima", "", [{
        "request_id": "completed-request", "status": "completed", "output_stem": "output",
        "detail": {"body": {"prompt": "original"}, "selected_tags": [{"content": "saved candidate"}],
                   "resolved": {"prompt": "final", "selected_path": [{"name": "chosen"}]}},
    }])
    database.add_job("cancel-target", "anima", "", [{
        "request_id": f"cancel-request-{request_index}", "status": "pending", "output_stem": "output", "detail": {},
    } for request_index in range(100)])
    database.save_preset("saved", "saved", "anima", {"prompt": "original"})


def verify_session_and_cancellation(client: TestClient) -> None:
    """느린 처리 중에도 Session과 작업 취소 접수가 1초 이내에 완료되는지 확인합니다."""

    started = time.monotonic()
    assert client.get("/api/session").status_code == 200
    cancellation = client.post("/api/jobs/cancel-target/cancel")
    assert cancellation.status_code == 200
    assert cancellation.json() == {"status": "cancelling", "requested_count": 100}
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("endpoint", [
    "/api/jobs?summary=true", "/api/jobs", "/api/jobs/completed", "/api/jobs/completed/inputs",
    "/api/jobs/deletion-candidates", "/api/jobs/selection-candidates", "/api/job-folders",
    "/api/jobs/activity", "/api/tags", "/api/presets",
    "/api/presets/saved/versions", "/api/loras", "/api/loras/presets", "/api/outputs",
])
def test_slow_json_serialization_keeps_session_and_cancellation_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    """각 조회 API의 최종 JSON 생성이 Worker에서 끝나며 다른 요청을 막지 않습니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    prepare_responsiveness_jobs(app.state.home_server.database)
    serialization_started = threading.Event()
    release_serialization = threading.Event()
    serialization_on_event_loop = []
    original_render = JSONResponse.render

    def blocked_render(response, content) -> bytes:
        """첫 조회 응답만 멈추고 작은 Session·취소 응답은 그대로 생성합니다."""

        is_control_response = isinstance(content, dict) and (
            "authenticated" in content or content.get("status") == "cancelling"
        )
        if not is_control_response and not serialization_started.is_set():
            try:
                asyncio.get_running_loop()
                serialization_on_event_loop.append(True)
            except RuntimeError:
                serialization_on_event_loop.append(False)
            serialization_started.set()
            release_serialization.wait(3)
        return original_render(response, content)

    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        monkeypatch.setattr(JSONResponse, "render", blocked_render)
        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.get, endpoint)
            assert serialization_started.wait(2)
            try:
                verify_session_and_cancellation(client)
                assert not response_future.done()
                assert serialization_on_event_loop == [False]
            finally:
                release_serialization.set()
            assert response_future.result().status_code == 200


@pytest.mark.parametrize("method_name,endpoint", [
    ("list_tag_entries", "/api/tags"), ("list_presets", "/api/presets"),
    ("export_tag_definitions", "/api/tags/export"),
    ("list_preset_versions", "/api/presets/saved/versions"), ("list_lora_profiles", "/api/loras"),
    ("list_lora_presets", "/api/loras/presets"), ("get_job", "/api/jobs/completed"),
])
def test_slow_database_read_keeps_session_and_cancellation_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method_name: str, endpoint: str,
) -> None:
    """DB의 느린 조회가 서버 Event Loop나 취소 접수 처리를 점유하지 않습니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    database = app.state.home_server.database
    prepare_responsiveness_jobs(database)
    read_started = threading.Event()
    release_read = threading.Event()
    original_read = getattr(database, method_name)

    def blocked_database_read(*arguments, **keyword_arguments):
        """SQL 실행 직전의 I/O 지연을 별도 Worker에서 재현합니다."""

        read_started.set()
        release_read.wait(3)
        return original_read(*arguments, **keyword_arguments)

    monkeypatch.setattr(database, method_name, blocked_database_read)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        with ThreadPoolExecutor(max_workers=1) as executor:
            read_future = executor.submit(client.get, endpoint)
            assert read_started.wait(2)
            try:
                verify_session_and_cancellation(client)
                assert not read_future.done()
            finally:
                release_read.set()
            assert read_future.result().status_code == 200


@pytest.mark.parametrize("endpoint", ["/api/prompts/preview", "/api/batches"])
def test_slow_tag_validation_does_not_block_other_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    """미리보기·제출의 태그 검증이 지연되어도 조회와 취소는 처리됩니다."""

    from home_server.application import selected_tag_definitions

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    prepare_responsiveness_jobs(app.state.home_server.database)
    validation_started = threading.Event()
    release_validation = threading.Event()

    def blocked_tag_validation(*arguments, **keyword_arguments):
        """태그 후보 조회·그래프 검증이 지연되는 상황을 재현합니다."""

        validation_started.set()
        release_validation.wait(3)
        return selected_tag_definitions(*arguments, **keyword_arguments)

    monkeypatch.setattr("home_server.application.selected_tag_definitions", blocked_tag_validation)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        with ThreadPoolExecutor(max_workers=1) as executor:
            validation_future = executor.submit(client.post, endpoint, json={
                "workflow": "anima", "body": {"prompt": "portrait"}, "count": 1,
            })
            assert validation_started.wait(2)
            try:
                verify_session_and_cancellation(client)
                assert not validation_future.done()
            finally:
                release_validation.set()
            assert validation_future.result().status_code == 200


def test_slow_log_file_does_not_delay_cancellation_or_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """취소 로그의 파일 쓰기가 막혀도 API 응답은 기다리지 않습니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    prepare_responsiveness_jobs(app.state.home_server.database)
    logging_started = threading.Event()
    release_logging = threading.Event()
    original_emit = RotatingFileHandler.emit

    def blocked_log_write(handler, record) -> None:
        """취소 접수 로그에 한해서 파일 쓰기를 멈춥니다."""

        if record.getMessage().startswith("작업 취소 접수"):
            logging_started.set()
            release_logging.wait(3)
        original_emit(handler, record)

    monkeypatch.setattr(RotatingFileHandler, "emit", blocked_log_write)
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        try:
            verify_session_and_cancellation(client)
            assert logging_started.wait(2)
            assert not release_logging.is_set()
            assert client.get("/api/session").status_code == 200
        finally:
            release_logging.set()
    log_text = (tmp_path / "runtime/logs/home_server.log").read_text(encoding="utf-8")
    assert "작업 취소 접수" in log_text
    assert "서버 종료" in log_text
