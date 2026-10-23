"""요청 시작 시각의 Migration·감시·집계와 서버 UTC 시각 응답을 검증합니다."""

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.application import _refresh_requests, comfy_execution_started_at
from home_server.database import Database
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request


def test_schema_twelve_migration_keeps_unknown_start_times_and_backups(tmp_path: Path) -> None:
    """기존 시작 시각을 추측하지 않고 백업·원본 JSON·완료 시각을 보존합니다."""

    database_path = tmp_path / "jobs.sqlite3"
    database = Database(database_path)
    request_identifier = add_catalog_test_request(database)
    database.complete_request(request_identifier, ["preserved.png"])
    original_request = database.get_request(request_identifier)
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE job_requests DROP COLUMN started_at")
        connection.execute("PRAGMA user_version=12")
    migrated_database = Database(database_path)
    migrated_request = migrated_database.get_request(request_identifier)
    assert migrated_request["started_at"] is None
    assert migrated_request["updated_at"] == original_request["updated_at"]
    assert migrated_request["result"] == original_request["result"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
        assert "finished_at" not in {row[1] for row in connection.execute("PRAGMA table_info(job_requests)")}
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    backup_path = next((tmp_path / "backups").glob("*_before_request_started_at_*.sqlite3"))
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 12
        assert "started_at" not in {row[1] for row in connection.execute("PRAGMA table_info(job_requests)")}
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*_before_request_started_at_*.sqlite3"))) == 1


@pytest.mark.parametrize("terminal_status, expected_status", [
    ("success", "completed"), ("error", "failed"), ("interrupted", "cancelled"),
])
@pytest.mark.parametrize("observe_running", [False, True])
def test_request_monitor_records_actual_history_start_without_extra_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal_status: str, expected_status: str, observe_running: bool,
) -> None:
    """실행 Polling을 놓친 요청도 기존 History의 시작 시각으로 확정하며 반복 조회는 보존합니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    database = server.database
    request_identifier = add_catalog_test_request(database)
    database.set_request_accepted(request_identifier, "prompt-1", {})
    fake_comfy.submissions.append(({}, {}))
    history_calls = []
    original_history = fake_comfy.history

    async def track_history(prompt_identifier: str) -> dict:
        """기존 완료 조회 외에 시작 시각을 얻기 위한 추가 HTTP 호출이 없는지 확인합니다."""

        history_calls.append(prompt_identifier)
        return await original_history(prompt_identifier)

    monkeypatch.setattr(fake_comfy, "history", track_history)
    monkeypatch.setattr("home_server.application.current_timestamp", lambda: "2026-10-23T03:00:01+00:00")
    monkeypatch.setattr("home_server.database.current_timestamp", lambda: "2026-10-23T03:00:01+00:00")
    asyncio.run(_refresh_requests(server))
    assert database.get_request(request_identifier)["started_at"] is None
    if observe_running:
        fake_comfy.running_prompt_ids.add("prompt-1")
        asyncio.run(_refresh_requests(server))
        running_request = database.get_request(request_identifier)
        assert running_request["started_at"] == "2026-10-23T03:00:01+00:00"
        monkeypatch.setattr("home_server.application.current_timestamp", lambda: "2026-10-23T03:03:00+00:00")
        monkeypatch.setattr("home_server.database.current_timestamp", lambda: "2026-10-23T03:03:00+00:00")
        asyncio.run(_refresh_requests(server))
        assert database.get_request(request_identifier)["started_at"] == running_request["started_at"]
        assert database.get_request(request_identifier)["updated_at"] == running_request["updated_at"]
    assert history_calls == []
    actual_start = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    fake_comfy.history_records["prompt-1"] = {
        "status": {"status_str": terminal_status, "messages": [
            ["execution_start", {"timestamp": int(actual_start.timestamp() * 1000)}],
        ]}, "outputs": {},
    }
    monkeypatch.setattr("home_server.database.current_timestamp", lambda: "2026-10-23T03:06:06+00:00")
    asyncio.run(_refresh_requests(server))
    final_request = database.get_request(request_identifier)
    assert final_request["status"] == expected_status
    assert final_request["started_at"] == "2026-10-23T03:00:00+00:00"
    assert final_request["updated_at"] == "2026-10-23T03:06:06+00:00"
    assert history_calls == ["prompt-1"]
    asyncio.run(_refresh_requests(server))
    assert database.get_request(request_identifier) == final_request
    assert history_calls == ["prompt-1"]


def test_cancelling_running_request_keeps_status_and_records_first_start(tmp_path: Path) -> None:
    """취소 요청과 첫 실행 관찰이 겹쳐도 취소 상태를 되돌리지 않고 시작 시각을 보존합니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    request_identifier = add_catalog_test_request(server.database)
    server.database.set_request_accepted(request_identifier, "prompt-1", {})
    server.database.mark_request_cancelling(request_identifier)
    fake_comfy.submissions.append(({}, {}))
    fake_comfy.running_prompt_ids.add("prompt-1")
    asyncio.run(_refresh_requests(server))
    running_request = server.database.get_request(request_identifier)
    assert running_request["status"] == "cancelling"
    assert running_request["started_at"] is not None
    server.database.apply_request_states([{"request_id": request_identifier, "status": "cancelled"}])
    assert server.database.get_request(request_identifier)["started_at"] == running_request["started_at"]


def test_cancelled_pending_request_has_no_invented_start_time(tmp_path: Path) -> None:
    """대기 중 취소되어 실행 History가 없는 요청은 시작 시각을 비워 둡니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    request_identifier = add_catalog_test_request(server.database)
    server.database.set_request_accepted(request_identifier, "prompt-1", {})
    server.database.mark_request_cancelling(request_identifier)
    fake_comfy.history_records["prompt-1"] = {"status": {"status_str": "interrupted"}, "outputs": {}}
    asyncio.run(_refresh_requests(server))
    cancelled_request = server.database.get_request(request_identifier)
    assert cancelled_request["status"] == "cancelled"
    assert cancelled_request["started_at"] is None
    assert server.database.list_job_summaries()["items"][0]["started_at"] is None


def test_job_start_aggregation_and_api_server_time_use_timezone_aware_utc(tmp_path: Path) -> None:
    """상위 시작은 하위 최솟값이며 요약·상세는 같은 시작 시각과 서버 시각을 제공합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    database = application.state.home_server.database
    database.add_job("aggregate-job", "anima", "", [
        {"request_id": f"request-{request_index}", "status": "pending", "output_stem": "output", "detail": {}}
        for request_index in range(3)
    ])
    database.apply_request_states([
        {"request_id": "request-0", "status": "running", "started_at": "2026-10-23T03:00:00+00:00"},
        {"request_id": "request-1", "status": "running", "started_at": "2026-10-23T02:59:00+00:00"},
    ])
    assert database.get_request("request-2")["started_at"] is None
    assert database.list_jobs()["items"][0]["started_at"] == "2026-10-23T02:59:00+00:00"
    assert database.list_job_summaries()["items"][0]["started_at"] == "2026-10-23T02:59:00+00:00"
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        for endpoint in ("/api/jobs?summary=true", "/api/jobs", "/api/jobs/aggregate-job"):
            response = client.get(endpoint)
            assert response.status_code == 200
            body = response.json()
            assert datetime.fromisoformat(body["server_time"]).utcoffset().total_seconds() == 0
            job = body["items"][0] if "items" in body else body
            assert job["started_at"] == "2026-10-23T02:59:00+00:00"


@pytest.mark.parametrize("timestamp_value", [None, "unknown", True, float("inf"), 10**30])
def test_invalid_comfy_start_timestamp_is_ignored(timestamp_value) -> None:
    """유효하지 않은 시작 Timestamp가 기존 상태 감시와 종료 처리를 중단하지 않습니다."""

    assert comfy_execution_started_at({"messages": [["execution_start", {"timestamp": timestamp_value}]]}) is None
