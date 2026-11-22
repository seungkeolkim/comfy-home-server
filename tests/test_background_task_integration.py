"""실제 앱의 네 Task 복구와 제출 Cursor·접수 유실·인증 경계를 검증합니다."""

import asyncio
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from home_server.comfy_client import ComfyClient
from test_application import FakeComfyClient, create_processing_test_app
from test_submission_worker import submit_anima_batch, wait_for_admission
import home_server.application as application_module


class InterruptedSubmissionClient(FakeComfyClient):
    """요청 준비·전송·접수 응답 대기의 원하는 위치에서 Worker 종료를 재현합니다."""

    def __init__(self, interruption_phase: str) -> None:
        """테스트 Thread가 확인할 Gate와 접수 조회 이력을 준비합니다."""

        super().__init__()
        self.interruption_phase = interruption_phase
        self.interruption_started = threading.Event()
        self.release_interruption = threading.Event()
        self.lookup_count = 0

    async def wait_at_interruption(self) -> None:
        """Task 취소로 정상 종료할 수 있는 비동기 네트워크 대기를 만듭니다."""

        self.interruption_started.set()
        while not self.release_interruption.is_set():
            await asyncio.sleep(0.005)

    async def populate_wildcards(self, prompt: str, seed: int) -> str:
        """전송 전 종료는 같은 요청을 안전하게 다시 준비하도록 만듭니다."""

        if self.interruption_phase == "preparing" and not self.interruption_started.is_set():
            await self.wait_at_interruption()
        return await super().populate_wildcards(prompt, seed)

    async def submit(self, workflow: dict, metadata: dict) -> str:
        """접수된 뒤 응답 유실 또는 접수 전 전송 중단을 구분해 재현합니다."""

        if self.interruption_phase != "preparing" and not self.interruption_started.is_set():
            if self.interruption_phase == "accepted":
                prompt_identifier = await super().submit(workflow, metadata)
                await self.wait_at_interruption()
                return prompt_identifier
            await self.wait_at_interruption()
        return await super().submit(workflow, metadata)

    async def find_request_prompt(self, request_identifier: str) -> str | None:
        """실제 ComfyUI 대신 접수 이력의 Metadata를 대조합니다."""

        self.lookup_count += 1
        for submission_index, (_, metadata) in enumerate(self.submissions, start=1):
            if metadata["home_server_request"]["request_id"] == request_identifier:
                return f"prompt-{submission_index}"
        return None


def wait_for_restarted_task(client: TestClient, identifier: str) -> dict:
    """운영 상태 API에서 교체된 실행과 인증된 응답을 확인합니다."""

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/api/background-tasks")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        registration = next(item for item in response.json()["tasks"] if item["identifier"] == identifier)
        if registration["restart_count"] >= 1 and registration["alive"]:
            return registration
        time.sleep(0.01)
    raise AssertionError("Task가 복구되지 않았습니다: " + identifier)


@pytest.mark.parametrize("identifier", ["comfy-submission-worker", "request-monitor", "cancellation-monitor", "resource-monitor"])
def test_all_four_application_tasks_recover_independently(tmp_path: Path, identifier: str) -> None:
    """네 종류의 Task를 각각 강제 종료해 공통 복구·장애 격리·정상 종료를 검증합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    server.background_tasks.restart_delays = (0.02,)
    server.background_tasks.check_interval_seconds = 0.005
    with TestClient(application) as client:
        assert client.get("/api/background-tasks").status_code == 401
        client.post("/api/login", json={"password": "test"})
        client.portal.call(server.background_tasks.registrations[identifier].task.cancel)
        recovered = wait_for_restarted_task(client, identifier)
        assert recovered["last_error"] == "예상하지 못한 Task 취소"
        for other_identifier, registration in server.background_tasks.registrations.items():
            if other_identifier != identifier:
                assert registration.restart_count == 0
        assert len(client.get("/api/background-tasks").json()["tasks"]) == 4
    assert not server.background_tasks.snapshot()["running"]
    assert all(not registration.enabled and registration.task is None for registration in server.background_tasks.registrations.values())


@pytest.mark.parametrize("interruption_phase", ["preparing", "accepted", "unknown"])
def test_submission_recovery_preserves_fifo_and_never_replays_unconfirmed_request(tmp_path: Path, interruption_phase: str) -> None:
    """진행 중 작업의 남은 요청을 먼저 처리하고 접수 유실은 대조 또는 중단으로 복구합니다."""

    fake_client = InterruptedSubmissionClient(interruption_phase)
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    server.background_tasks.restart_delays = (0.15,)
    server.background_tasks.check_interval_seconds = 0.005
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client, 3)
            assert fake_client.interruption_started.wait(3)
            client.portal.call(server.submission_worker.worker_task.cancel)
            second_batch = submit_anima_batch(client, 2)
            wait_for_restarted_task(client, "comfy-submission-worker")
            first_job = wait_for_admission(client, first_batch["job_id"])
            wait_for_admission(client, second_batch["job_id"])
            expected_first_count = 2 if interruption_phase == "unknown" else 3
            submitted_jobs = [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions]
            assert submitted_jobs == [first_batch["job_id"]] * expected_first_count + [second_batch["job_id"]] * 2
            submitted_requests = [metadata["home_server_request"]["request_id"] for _, metadata in fake_client.submissions]
            assert len(submitted_requests) == len(set(submitted_requests))
            if interruption_phase == "unknown":
                assert first_job["requests"][0]["status"] == "stopped"
                assert "미확인" in first_job["requests"][0]["error_message"]
            else:
                assert first_job["status_counts"] == {"pending": 3}
            assert fake_client.lookup_count == (0 if interruption_phase == "preparing" else 1)
            client.portal.call(server.submission_worker.pending_batches.join)
    finally:
        fake_client.release_interruption.set()


def test_stopped_supervisor_rejects_submission_before_persisting_job(tmp_path: Path) -> None:
    """접수 불가능 상태에서는 503을 반환하고 제출 중 Job을 새로 만들지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        client.portal.call(application.state.home_server.background_tasks.stop)
        response = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "safe garden"}})
        assert response.status_code == 503
        assert client.get("/api/jobs").json()["items"] == []


def test_stalled_submission_is_recovered_without_manual_restart(tmp_path: Path) -> None:
    """실제 제출 단계의 제한 초과를 공통 감시자가 발견하고 접수 ID를 복구합니다."""

    fake_client = InterruptedSubmissionClient("accepted")
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    server.background_tasks.restart_delays = (0.02,)
    server.background_tasks.check_interval_seconds = 0.005
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        batch = submit_anima_batch(client, 2)
        assert fake_client.interruption_started.wait(3)
        registration = server.background_tasks.registrations["comfy-submission-worker"]
        client.portal.call(setattr, registration, "last_progress_monotonic", time.monotonic() - 400)
        recovered = wait_for_restarted_task(client, "comfy-submission-worker")
        assert "제한 초과" in recovered["last_error"]
        assert wait_for_admission(client, batch["job_id"])["status_counts"] == {"pending": 2}
        assert len(fake_client.submissions) == 2


def test_terminal_request_is_preserved_and_late_discovered_prompt_is_cancelled(tmp_path: Path) -> None:
    """복구 전에 수동 중단된 요청은 되살리지 않고 발견한 Prompt만 개별 취소합니다."""

    fake_client = InterruptedSubmissionClient("accepted")
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    server.background_tasks.restart_delays = (0.02,)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        batch = submit_anima_batch(client, 2)
        assert fake_client.interruption_started.wait(3)
        server.database.update_request(batch["request_ids"][0], "stopped", "manual stop")
        client.portal.call(server.submission_worker.worker_task.cancel)
        wait_for_restarted_task(client, "comfy-submission-worker")
        job = wait_for_admission(client, batch["job_id"])
        assert job["requests"][0]["status"] == "stopped"
        assert job["requests"][0]["error_message"] == "manual stop"
        assert fake_client.history_records["prompt-1"]["status"]["status_str"] == "interrupted"
        assert job["requests"][1]["prompt_id"] == "prompt-2"


def test_shutdown_between_database_save_and_enqueue_does_not_leave_submitting_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DB 저장 이후 접수 Gate가 닫히는 경합에서도 새 요청을 중단으로 확정합니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    original_store_batch = application_module.store_batch_requests

    def save_and_stop_accepting(*arguments):
        """DB Commit 직후 접수 서비스 종료를 재현합니다."""

        stored_batch = original_store_batch(*arguments)
        server.submission_worker.accepting = False
        return stored_batch

    monkeypatch.setattr(application_module, "store_batch_requests", save_and_stop_accepting)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        response = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "safe garden"}})
        assert response.status_code == 503
        jobs = client.get("/api/jobs").json()["items"]
        assert len(jobs) == 1
        assert jobs[0]["status_counts"] == {"stopped": 1}
        assert fake_client.submissions == []


def test_cancel_during_acceptance_write_waits_for_commit_before_resuming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """접수 DB 쓰기 Thread가 살아 있으면 복구를 기다리고 Commit된 Prompt를 재제출하지 않습니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    server.background_tasks.restart_delays = (0.02,)
    server.background_tasks.check_interval_seconds = 0.005
    write_started = threading.Event()
    release_write = threading.Event()
    original_write = server.database.set_request_accepted

    def delayed_acceptance_write(*arguments) -> None:
        """첫 접수의 Commit을 외부에서 잠시 지연합니다."""

        if not write_started.is_set():
            write_started.set()
            release_write.wait(5)
        original_write(*arguments)

    monkeypatch.setattr(server.database, "set_request_accepted", delayed_acceptance_write)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client, 2)
            assert write_started.wait(3)
            client.portal.call(server.submission_worker.worker_task.cancel)
            second_batch = submit_anima_batch(client)
            time.sleep(0.05)
            assert len(fake_client.submissions) == 1
            assert server.background_tasks.registrations["comfy-submission-worker"].restart_count == 0
            release_write.set()
            wait_for_restarted_task(client, "comfy-submission-worker")
            assert wait_for_admission(client, first_batch["job_id"])["status_counts"] == {"pending": 2}
            wait_for_admission(client, second_batch["job_id"])
            assert len(fake_client.submissions) == 3
    finally:
        release_write.set()


@pytest.mark.parametrize("source", ["queue", "history", "missing", "duplicate"])
def test_comfy_request_lookup_uses_embedded_metadata(source: str) -> None:
    """동일 요청 식별자를 가진 접수만 찾고 다중 접수는 임의 선택하지 않습니다."""

    async def verify_lookup() -> None:
        """실제 HTTP Client의 Queue·History Metadata 해석을 검증합니다."""

        prompt_record = [1, "known-prompt", {}, {"extra_pnginfo": {"home_server_request": {"request_id": "request-one"}}}]

        def respond_to_lookup(request: httpx.Request) -> httpx.Response:
            """GPU를 사용하지 않고 공식 ComfyUI 응답 구조를 제공합니다."""

            if request.url.path == "/queue":
                queued_records = [prompt_record] if source in {"queue", "duplicate"} else []
                return httpx.Response(200, json={"queue_running": [], "queue_pending": queued_records})
            assert request.url.path == "/history"
            assert request.url.params["max_items"] == "200"
            completed_record = prompt_record if source == "history" else [1, "other-prompt", {}, prompt_record[3]]
            return httpx.Response(200, json={"item": {"prompt": completed_record}} if source in {"history", "duplicate"} else {})

        comfy_client = ComfyClient("http://comfy.test")
        await comfy_client.close()
        comfy_client.client = httpx.AsyncClient(base_url=comfy_client.endpoint, transport=httpx.MockTransport(respond_to_lookup))
        try:
            if source == "duplicate":
                with pytest.raises(RuntimeError, match="여러"):
                    await comfy_client.find_request_prompt("request-one")
            else:
                assert await comfy_client.find_request_prompt("request-one") == (None if source == "missing" else "known-prompt")
        finally:
            await comfy_client.close()

    asyncio.run(verify_lookup())
