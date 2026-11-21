"""단일 제출 Worker의 작업 순서와 대기 중 참조 유실·취소·종료를 검증합니다."""

import asyncio
import threading
import time
import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.comfy_client import ComfyHttpError
from home_server.workflows import WORKFLOW_FILES
from test_application import FakeComfyClient, create_processing_test_app
from test_minimax_generation import add_input_images
from test_request_favorites import prepare_favorite_job
from test_style_generation import StyleComfyClient, prepare_style_generation


class GatedSubmissionClient(FakeComfyClient):
    """첫 ComfyUI 접수를 막아 뒤 작업의 내부 접수와 실제 제출을 분리합니다."""

    def __init__(self) -> None:
        """네트워크 Gate·LoRA 목록·개별 취소 기록을 준비합니다."""

        super().__init__()
        self.first_submission_started = threading.Event()
        self.release_first_submission = threading.Event()
        self.available_loras = ["example.safetensors"]
        self.cancelled_prompt_identifiers = []
        self.rejected_job_identifier = None
        self.rejection_exception = None

    async def list_loras(self) -> list[str]:
        """접수 이후 파일 삭제를 재현할 수 있는 목록을 제공합니다."""

        return self.available_loras

    async def submit(self, workflow: dict, metadata: dict) -> str:
        """매 요청에서 실행을 양보하고 첫 접수만 외부 Gate를 기다립니다."""

        if not self.first_submission_started.is_set():
            self.first_submission_started.set()
            if not await asyncio.to_thread(self.release_first_submission.wait, 15):
                raise TimeoutError("테스트 제출 Gate가 열리지 않았습니다.")
        await asyncio.sleep(0)
        if metadata["home_server_request"]["job_id"] == self.rejected_job_identifier:
            raise self.rejection_exception
        return await super().submit(workflow, metadata)

    async def cancel_prompt(self, prompt_id: str) -> bool:
        """삭제된 요청에 뒤늦게 접수된 Prompt만 개별 취소합니다."""

        self.cancelled_prompt_identifiers.append(prompt_id)
        return await super().cancel_prompt(prompt_id)


def submit_anima_batch(client: TestClient, count: int = 1, **extra_fields) -> dict:
    """GPU를 사용하지 않는 일반 작업을 내부 Worker에 접수합니다."""

    response = client.post("/api/batches", json={
        "workflow": "anima", "body": {"prompt": "safe garden"}, "count": count, **extra_fields,
    })
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_admission(client: TestClient, job_identifier: str) -> dict:
    """GPU 완료가 아닌 Worker의 접수·실패 처리가 끝날 때까지만 기다립니다."""

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_identifier}")
        assert response.status_code == 200, response.text
        job = response.json()
        if all(request["status"] not in {"submitting", "cancelling"} for request in job["requests"]):
            return job
        time.sleep(0.01)
    raise AssertionError(f"Worker가 작업 제출을 끝내지 못했습니다: {job_identifier}")


def test_two_hundred_request_batches_are_admitted_quickly_and_never_interleave(tmp_path: Path) -> None:
    """앞 작업 전송이 막혀도 뒤 100개 접수는 끝나고 실제 Prompt는 작업별로 연속 제출됩니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client, 100)
            assert fake_client.first_submission_started.wait(3)
            started_at = time.monotonic()
            second_batch = submit_anima_batch(client, 100)
            assert time.monotonic() - started_at < 2
            assert fake_client.submissions == []
            assert application.state.home_server.submission_worker.busy
            fake_client.release_first_submission.set()
            wait_for_admission(client, second_batch["job_id"])
            submitted_jobs = [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions]
            assert submitted_jobs == [first_batch["job_id"]] * 100 + [second_batch["job_id"]] * 100
    finally:
        fake_client.release_first_submission.set()


def test_queued_input_snapshot_missing_fails_only_that_request_and_continues(tmp_path: Path) -> None:
    """대기 중 입력 Snapshot 한 개가 삭제돼도 같은 작업의 정상 입력과 다음 작업을 처리합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    output_identifiers = add_input_images(server, [("first.png", (64, 96)), ("second.png", (64, 96))])
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            response = client.post("/api/batches", json={
                "workflow": "minimax_h3", "body": {"prompt": "safe garden"},
                "input_scope": "folder", "input_directory": "",
                "output_ids": list(output_identifiers.values()), "settings": {"generation_mode": "FL2VA"},
            })
            assert response.status_code == 200, response.text
            image_batch = response.json()
            missing_request = server.database.get_request(image_batch["request_ids"][0])
            next(server.upload_directory.glob(missing_request["upload_id"] + ".*")).unlink()
            final_batch = submit_anima_batch(client)
            fake_client.release_first_submission.set()
            image_job = wait_for_admission(client, image_batch["job_id"])
            wait_for_admission(client, final_batch["job_id"])
            assert image_job["status_counts"] == {"failed": 1, "pending": 1}
            assert "입력 이미지" in image_job["requests"][0]["error_message"]
            submitted_jobs = [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions]
            assert submitted_jobs == [first_batch["job_id"], image_batch["job_id"], final_batch["job_id"]]
            assert not list(server.upload_directory.iterdir())
    finally:
        fake_client.release_first_submission.set()


def test_deleted_original_inputs_still_use_accepted_snapshots(tmp_path: Path) -> None:
    """Worker 대기 중 원본 파일이 지워져도 이미 복사한 입력 Snapshot으로 생성합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    output_identifiers = add_input_images(server, [("original.png", (64, 96))])
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            response = client.post("/api/batches", json={
                "workflow": "minimax_h3", "body": {"prompt": "safe garden"},
                "input_scope": "folder", "input_directory": "",
                "output_ids": list(output_identifiers.values()), "settings": {"generation_mode": "FL2VA"},
            })
            assert response.status_code == 200, response.text
            (server.config.managed_output_directory / "original.png").unlink()
            fake_client.release_first_submission.set()
            assert wait_for_admission(client, response.json()["job_id"])["status_counts"] == {"pending": 1}
    finally:
        fake_client.release_first_submission.set()


def test_shared_upload_is_not_cleaned_before_later_queued_job_uses_it(tmp_path: Path) -> None:
    """같은 임시 입력을 참조한 뒤 작업이 남아 있으면 앞 작업의 정리가 해당 파일을 보존합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    upload_identifier = uuid.uuid4().hex
    upload_path = server.upload_directory / (upload_identifier + ".png")
    Image.new("RGB", (64, 96)).save(upload_path)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            payload = {"workflow": "minimax_h3", "body": {"prompt": "safe garden"},
                       "upload_ids": [upload_identifier], "settings": {"generation_mode": "FL2VA"}}
            first_input_batch = client.post("/api/batches", json=payload)
            second_input_batch = client.post("/api/batches", json=payload)
            assert first_input_batch.status_code == second_input_batch.status_code == 200
            fake_client.release_first_submission.set()
            assert wait_for_admission(client, first_input_batch.json()["job_id"])["status_counts"] == {"pending": 1}
            assert wait_for_admission(client, second_input_batch.json()["job_id"])["status_counts"] == {"pending": 1}
            client.portal.call(server.submission_worker.pending_batches.join)
            assert not upload_path.exists()
            assert len(fake_client.submissions) == 3
    finally:
        fake_client.release_first_submission.set()


def test_cancelled_queued_job_can_be_deleted_before_previous_submission_finishes(tmp_path: Path) -> None:
    """대기 취소는 앞 작업의 네트워크를 기다리지 않고 완료되며 삭제된 Metadata도 안전하게 건너뜁니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            deleted_batch = submit_anima_batch(client, 3)
            assert client.post(f"/api/jobs/{deleted_batch['job_id']}/cancel").status_code == 200
            assert client.get(f"/api/jobs/{deleted_batch['job_id']}").json()["status_counts"] == {"cancelled": 3}
            assert client.delete(f"/api/jobs/{deleted_batch['job_id']}").status_code == 200
            final_batch = submit_anima_batch(client)
            fake_client.release_first_submission.set()
            wait_for_admission(client, final_batch["job_id"])
            assert [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions] == [first_batch["job_id"], final_batch["job_id"]]
    finally:
        fake_client.release_first_submission.set()


def test_queued_single_request_cancellation_preserves_remaining_requests(tmp_path: Path) -> None:
    """대기 작업의 한 요청만 즉시 취소하고 나머지는 같은 작업 순서를 유지합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            second_batch = submit_anima_batch(client, 3)
            cancelled_identifier = second_batch["request_ids"][1]
            assert client.post(f"/api/requests/{cancelled_identifier}/cancel").status_code == 200
            assert application.state.home_server.database.get_request(cancelled_identifier)["status"] == "cancelled"
            fake_client.release_first_submission.set()
            second_job = wait_for_admission(client, second_batch["job_id"])
            assert second_job["status_counts"] == {"pending": 2, "cancelled": 1}
            assert cancelled_identifier not in [metadata["home_server_request"]["request_id"] for _, metadata in fake_client.submissions]
    finally:
        fake_client.release_first_submission.set()


def test_removed_lora_after_enqueue_is_failed_before_comfy_submission(tmp_path: Path) -> None:
    """접수 후 사라진 LoRA는 명시적 실패로 남기고 뒤의 정상 작업은 진행합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            missing_lora_batch = submit_anima_batch(client, 2, loras=[{"name": "example.safetensors", "strength": 0.5}])
            fake_client.available_loras = []
            final_batch = submit_anima_batch(client)
            fake_client.release_first_submission.set()
            missing_lora_job = wait_for_admission(client, missing_lora_batch["job_id"])
            wait_for_admission(client, final_batch["job_id"])
            assert missing_lora_job["status_counts"] == {"failed": 2}
            assert all("LoRA 파일" in request["error_message"] for request in missing_lora_job["requests"])
            assert len(fake_client.submissions) == 2
    finally:
        fake_client.release_first_submission.set()


def test_missing_workflow_file_after_enqueue_does_not_use_stale_batch_cache(tmp_path: Path) -> None:
    """대기 중 Workflow JSON이 사라지면 이전 작업의 Cache를 빌려 생성하지 않고 실패합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    workflow_directory = tmp_path / "workflows"
    shutil.copytree(server.config.workflow_directory, workflow_directory)
    server.config = replace(server.config, workflow_directory=workflow_directory)
    workflow_prefix = workflow_directory / WORKFLOW_FILES["anima"]
    workflow_file = workflow_prefix.with_name(workflow_prefix.name + "_api.json")
    original_workflow = workflow_file.read_bytes()
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            missing_workflow_batch = submit_anima_batch(client, 2)
            workflow_file.unlink()
            fake_client.release_first_submission.set()
            assert wait_for_admission(client, missing_workflow_batch["job_id"])["status_counts"] == {"failed": 2}
            workflow_file.write_bytes(original_workflow)
            final_batch = submit_anima_batch(client)
            wait_for_admission(client, final_batch["job_id"])
            assert len(fake_client.submissions) == 2
    finally:
        fake_client.release_first_submission.set()


def test_favorite_restore_shares_worker_and_survives_favorite_removal(tmp_path: Path) -> None:
    """즐겨찾기 복원도 공통 Worker를 기다리고 접수 후 즐겨찾기 해제와 독립적으로 실행됩니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    output_identifier = prepare_favorite_job(application.state.home_server)[0]
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            favorite_identifier = client.put(f"/api/outputs/{output_identifier}/favorite").json()["favorite_id"]
            first_batch = submit_anima_batch(client, 2)
            assert fake_client.first_submission_started.wait(3)
            response = client.post(f"/api/favorites/{favorite_identifier}/batches", json={
                "workflow": "anima", "body": {"prompt": "saved garden"}, "settings": {},
            })
            assert response.status_code == 200, response.text
            assert fake_client.submissions == []
            assert client.delete(f"/api/favorites/{favorite_identifier}").status_code == 200
            fake_client.release_first_submission.set()
            favorite_job = wait_for_admission(client, response.json()["job_id"])
            assert favorite_job["status_counts"] == {"pending": 1}
            assert [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions] == [first_batch["job_id"], first_batch["job_id"], response.json()["job_id"]]
    finally:
        fake_client.release_first_submission.set()


def test_style_generation_uses_same_worker_and_missing_render_is_explicit(tmp_path: Path) -> None:
    """스타일 제출이 일반 작업 사이에 끼어들지 않고 유실된 Render만 명시적으로 실패합니다."""

    class GatedStyleClient(StyleComfyClient):
        """스타일 Preflight는 유지하며 Prompt 제출 Gate를 공유합니다."""

        def __init__(self) -> None:
            """Graph 준비용 Fake와 직렬 제출 관찰용 Gate를 준비합니다."""

            super().__init__()
            self.submission_gate = GatedSubmissionClient()

        async def submit(self, workflow: dict, metadata: dict) -> str:
            """첫 접수만 기다린 뒤 원래 스타일 PNG 생성 Fake를 실행합니다."""

            if not self.submission_gate.first_submission_started.is_set():
                self.submission_gate.first_submission_started.set()
                await asyncio.to_thread(self.submission_gate.release_first_submission.wait, 15)
            return await super().submit(workflow, metadata)

    fake_client = GatedStyleClient()
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    server = application.state.home_server
    try:
        first_batch = submit_anima_batch(client)
        assert fake_client.submission_gate.first_submission_started.wait(3)
        endpoint = f"/api/style-projects/{project['identifier']}"
        plan_response = client.post(endpoint + "/generation-plans", json=plan_input)
        assert plan_response.status_code == 201, plan_response.text
        plan = plan_response.json()
        response = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": "queued-style-generation-operation"})
        assert response.status_code == 200, response.text
        style_job_identifier = response.json()["jobIdentifier"]
        assert fake_client.submissions == []
        with closing(server.database._connect()) as connection, connection:
            missing_render = connection.execute("SELECT render_id,request_id FROM style_candidate_renders WHERE request_id=?", (response.json()["requestIdentifiers"][0],)).fetchone()
            connection.execute("DELETE FROM style_candidate_renders WHERE render_id=?", (missing_render["render_id"],))
        final_batch = submit_anima_batch(client)
        fake_client.submission_gate.release_first_submission.set()
        style_job = wait_for_admission(client, style_job_identifier)
        wait_for_admission(client, final_batch["job_id"])
        failed_request = next(request for request in style_job["requests"] if request["request_id"] == missing_render["request_id"])
        assert failed_request["status"] == "failed"
        assert "스타일" in failed_request["error_message"]
        submitted_jobs = [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions]
        assert submitted_jobs == [first_batch["job_id"]] + [style_job_identifier] * (len(style_job["requests"]) - 1) + [final_batch["job_id"]]
    finally:
        fake_client.submission_gate.release_first_submission.set()
        client.__exit__(None, None, None)


@pytest.mark.parametrize("error_kind", ["missing-model", "unconfirmed-response"])
def test_comfy_rejection_or_unconfirmed_response_does_not_stop_worker(tmp_path: Path, error_kind: str) -> None:
    """명확한 참조 오류는 실패로, 접수 여부가 모호한 통신 오류는 중단으로 남기고 이어갑니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            rejected_batch = submit_anima_batch(client, 2)
            fake_client.rejected_job_identifier = rejected_batch["job_id"]
            fake_client.rejection_exception = ComfyHttpError(400, "Model file was deleted") if error_kind == "missing-model" else TimeoutError("response lost")
            final_batch = submit_anima_batch(client)
            fake_client.release_first_submission.set()
            rejected_job = wait_for_admission(client, rejected_batch["job_id"])
            wait_for_admission(client, final_batch["job_id"])
            expected_status = "failed" if error_kind == "missing-model" else "stopped"
            assert rejected_job["status_counts"] == {expected_status: 2}
            assert len(fake_client.submissions) == 2
            assert not application.state.home_server.submission_worker.worker_task.done()
    finally:
        fake_client.release_first_submission.set()


@pytest.mark.parametrize("manual_change", ["deleted", "stopped", "cancelled"])
def test_changed_inflight_request_cancels_late_comfy_acceptance_and_continues(tmp_path: Path, manual_change: str) -> None:
    """수동 삭제·종료와 접수 응답이 경합해도 고아 Prompt를 취소하고 종료 상태를 되살리지 않습니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            deleted_batch = submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            if manual_change == "deleted":
                with closing(server.database._connect()) as connection, connection:
                    connection.execute("DELETE FROM job_requests WHERE job_id=?", (deleted_batch["job_id"],))
                assert server.database.delete_job(deleted_batch["job_id"])
            else:
                server.database.update_request(deleted_batch["request_ids"][0], manual_change, "manual change")
            final_batch = submit_anima_batch(client)
            fake_client.release_first_submission.set()
            wait_for_admission(client, final_batch["job_id"])
            assert fake_client.cancelled_prompt_identifiers == ["prompt-1"]
            assert fake_client.history_records["prompt-1"]["status"]["status_str"] == "interrupted"
            if manual_change == "deleted":
                assert server.database.get_job(deleted_batch["job_id"]) is None
            else:
                changed_request = server.database.get_request(deleted_batch["request_ids"][0])
                assert changed_request["status"] == manual_change
                assert changed_request["error_message"] == "manual change"
    finally:
        fake_client.release_first_submission.set()


def test_cleanup_failure_does_not_terminate_shared_worker(tmp_path: Path) -> None:
    """파일 정리 권한 오류가 발생해도 이미 접수한 상태를 유지하고 다음 작업을 진행합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            first_batch = submit_anima_batch(client)
            assert fake_client.first_submission_started.wait(3)
            final_batch = submit_anima_batch(client)
            with patch("home_server.application.clear_batch_uploads", side_effect=PermissionError("locked input")):
                fake_client.release_first_submission.set()
                wait_for_admission(client, final_batch["job_id"])
                assert [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions] == [first_batch["job_id"], final_batch["job_id"]]
                assert not application.state.home_server.submission_worker.worker_task.done()
    finally:
        fake_client.release_first_submission.set()


def test_shutdown_marks_active_and_waiting_submissions_stopped_without_replay(tmp_path: Path) -> None:
    """서버 종료 시 접수 응답 없는 요청은 중단으로 남기고 재시작 때 자동 제출하지 않습니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        first_batch = submit_anima_batch(client, 2)
        assert fake_client.first_submission_started.wait(3)
        second_batch = submit_anima_batch(client, 2)
        client.portal.call(application.state.home_server.submission_worker.stop)
        fake_client.release_first_submission.set()
        assert client.get(f"/api/jobs/{first_batch['job_id']}").json()["status_counts"] == {"stopped": 2}
        assert client.get(f"/api/jobs/{second_batch['job_id']}").json()["status_counts"] == {"stopped": 2}
        assert not application.state.home_server.submission_worker.busy
    restarted_client = FakeComfyClient()
    restarted_application = create_processing_test_app(tmp_path, restarted_client)
    with TestClient(restarted_application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.get(f"/api/jobs/{first_batch['job_id']}").json()["status_counts"] == {"stopped": 2}
        assert restarted_client.submissions == []


def test_restart_preserves_requests_already_accepted_by_comfy(tmp_path: Path) -> None:
    """ComfyUI가 처리 중인 Prompt ID와 대기 상태는 CHS 재시작 뒤에도 유지합니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        batch = submit_anima_batch(client, 2)
        accepted_job = wait_for_admission(client, batch["job_id"])
        accepted_prompt_identifiers = [request["prompt_id"] for request in accepted_job["requests"]]
        assert accepted_job["status_counts"] == {"pending": 2}
    restarted_application = create_processing_test_app(tmp_path, fake_client)
    with TestClient(restarted_application) as client:
        client.post("/api/login", json={"password": "test"})
        restarted_job = client.get(f"/api/jobs/{batch['job_id']}").json()
        assert restarted_job["status_counts"] == {"pending": 2}
        assert [request["prompt_id"] for request in restarted_job["requests"]] == accepted_prompt_identifiers
        assert len(fake_client.submissions) == 2
