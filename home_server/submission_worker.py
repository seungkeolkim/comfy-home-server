"""ComfyUI 제출을 단일 Event loop Worker에서 작업 단위로 순차 처리합니다."""

import asyncio
import logging
from dataclasses import dataclass, field

from .background_tasks import complete_thread_call


LOGGER = logging.getLogger(__name__)
SUBMISSION_TASK_IDENTIFIER = "comfy-submission-worker"


@dataclass
class SubmissionAttempt:
    """Task가 종료돼도 현재 요청의 접수 단계와 복구에 필요한 확정 입력을 보존합니다."""

    request_identifier: str
    submission_started: bool = False
    prompt_identifier: str | None = None
    resolved_result: dict = field(default_factory=dict)


@dataclass
class SubmissionBatch:
    """대기 작업의 Metadata 참조와 전송 전 취소 표시만 보관합니다."""

    requests: list[dict]
    cancelled_request_identifiers: set[str] = field(default_factory=set)
    next_request_index: int = 0
    attempt: SubmissionAttempt | None = None


class SubmissionWorker:
    """이미지·Graph 대신 기존 요청 Metadata만 받아 한 작업의 접수를 끝낸 뒤 다음을 처리합니다."""

    def __init__(self, server) -> None:
        """작업 Metadata Queue와 실행 상태만 보관합니다."""

        self.server = server
        self.pending_batches: asyncio.Queue[SubmissionBatch] = asyncio.Queue()
        self.waiting_batches: dict[str, SubmissionBatch] = {}
        self.active_batch: SubmissionBatch | None = None
        self.accepting = False

    @property
    def active_requests(self) -> list[dict] | None:
        """기존 운영 조회에 현재 작업의 Metadata를 제공합니다."""

        return self.active_batch.requests if self.active_batch is not None else None

    @property
    def worker_task(self) -> asyncio.Task | None:
        """Supervisor가 교체한 현재 Worker Task를 반환합니다."""

        return self.server.background_tasks.registrations[SUBMISSION_TASK_IDENTIFIER].task

    @property
    def busy(self) -> bool:
        """대기 중이거나 실제 제출을 처리하는 작업이 있는지 반환합니다."""

        return self.active_requests is not None or not self.pending_batches.empty()

    def start(self) -> None:
        """Supervisor 시작에 앞서 Metadata Queue의 접수를 허용합니다."""

        self.accepting = True

    def ensure_accepting(self) -> None:
        """DB 저장 전에 Supervisor의 접수 가능 상태를 확인합니다."""

        if not self.accepting or not self.server.background_tasks.accepting(SUBMISSION_TASK_IDENTIFIER):
            raise RuntimeError("ComfyUI 제출 서비스가 중지 중입니다. 잠시 후 다시 시도해 주세요.")

    async def enqueue_saved(self, requests: list[dict]) -> None:
        """DB 저장 중 종료가 시작돼도 미제출 기록과 임시 입력을 방치하지 않습니다."""

        try:
            self.enqueue(requests)
        except RuntimeError:
            await self.finish_interrupted_batch(requests, "제출 서비스 종료로 접수되지 않았습니다. 자동 재제출하지 않습니다.")
            raise

    def progress(self, phase: str, *, timeout_seconds: float = 180, idle: bool = False) -> None:
        """요청 수와 무관하게 실제 단계 진행을 공통 Supervisor에 전달합니다."""

        self.server.background_tasks.registrations[SUBMISSION_TASK_IDENTIFIER].progress(
            phase, timeout_seconds=timeout_seconds, idle=idle,
        )

    async def enqueue_saved_batches(self, request_batches: list[list[dict]]) -> None:
        """연속된 작업을 같은 Event loop 차례에 접수하고 종료 경합 시 전체 미제출을 중단합니다."""

        try:
            self.ensure_accepting()
            for requests in request_batches:
                self.enqueue(requests)
        except RuntimeError:
            for requests in request_batches:
                await self.finish_interrupted_batch(requests, "제출 서비스 종료로 접수되지 않았습니다. 자동 재제출하지 않습니다.")
            raise

    def enqueue(self, requests: list[dict]) -> None:
        """Metadata 참조를 즉시 접수하며 같은 Event loop에서는 별도 Lock을 사용하지 않습니다."""

        if not requests:
            return
        self.ensure_accepting()
        batch = SubmissionBatch(requests)
        self.waiting_batches[requests[0]["job_id"]] = batch
        self.pending_batches.put_nowait(batch)
        LOGGER.info("작업 제출 대기: job_id=%s count=%s", requests[0]["job_id"], len(requests))

    def cancel_waiting_requests(self, job_identifier: str, request_identifier: str | None = None) -> list[str]:
        """아직 Worker가 가져가지 않은 요청을 동기적으로 표시해 즉시 취소 완료할 수 있게 합니다."""

        batch = self.waiting_batches.get(job_identifier)
        if batch is None:
            return []
        cancelled_identifiers = [request["request_id"] for request in batch.requests
                                 if request_identifier is None or request["request_id"] == request_identifier]
        batch.cancelled_request_identifiers.update(cancelled_identifiers)
        return cancelled_identifiers

    async def run(self) -> None:
        """재시작 시 현재 작업의 남은 요청부터 이어서 FIFO 제출을 계속합니다."""

        from .application import _submit_requests, cleanup_submission_uploads

        while True:
            if self.active_batch is None:
                self.progress("waiting_for_batch", idle=True)
                self.active_batch = await self.pending_batches.get()
            batch = self.active_batch
            requests = batch.requests
            self.waiting_batches.pop(requests[0]["job_id"], None)
            LOGGER.info("작업 제출 시작: job_id=%s count=%s next_index=%s", requests[0]["job_id"], len(requests), batch.next_request_index)
            self.progress("recovering_batch")
            if batch.attempt is not None:
                await self.recover_interrupted_attempt(batch)
            if batch.cancelled_request_identifiers:
                await complete_thread_call(self.server.database.cancel_unsubmitted_requests, list(batch.cancelled_request_identifiers))
            await _submit_requests(self.server, batch)
            self.progress("cleaning_inputs")
            try:
                await cleanup_submission_uploads(self.server, requests)
            except Exception:
                LOGGER.exception("제출 입력 정리 실패: job_id=%s", requests[0]["job_id"])
            LOGGER.info("작업 제출 종료: job_id=%s", requests[0]["job_id"])
            self.active_batch = None
            self.pending_batches.task_done()

    async def recover_interrupted_attempt(self, batch: SubmissionBatch) -> None:
        """미전송 요청은 다시 준비하고 응답 유실은 ComfyUI 기록을 대조해 중복 제출을 막습니다."""

        from .application import record_submission_failure

        attempt = batch.attempt
        if not attempt.submission_started:
            batch.attempt = None
            return
        self.progress("reconciling_submission", timeout_seconds=90)
        submission_state = await complete_thread_call(self.server.database.get_submission_state, attempt.request_identifier)
        if submission_state and submission_state["prompt_id"]:
            batch.next_request_index += 1
            batch.attempt = None
            return
        prompt_identifier = attempt.prompt_identifier
        if prompt_identifier is None:
            try:
                prompt_identifier = await self.server.comfy.find_request_prompt(attempt.request_identifier)
            except Exception:
                LOGGER.exception("ComfyUI 접수 대조 실패: request_id=%s", attempt.request_identifier)
            # 대조 중 취소돼도 이미 발견한 접수 ID는 다음 복구에서 재사용합니다.
            attempt.prompt_identifier = prompt_identifier
        if prompt_identifier is not None:
            try:
                await complete_thread_call(self.server.database.set_request_accepted, attempt.request_identifier,
                                           prompt_identifier, attempt.resolved_result)
                self.server.cancellation_wakeup.set()
                LOGGER.info("ComfyUI 접수 복구: request_id=%s prompt_id=%s", attempt.request_identifier, prompt_identifier)
            except Exception as exception:
                await record_submission_failure(self.server, attempt.request_identifier, exception, True, prompt_identifier)
        else:
            await complete_thread_call(self.server.database.stop_unsubmitted_requests, [attempt.request_identifier],
                                       "Worker 복구 후 ComfyUI 접수 여부가 미확인입니다. 중복 방지를 위해 자동 재제출하지 않습니다.")
        batch.next_request_index += 1
        batch.attempt = None

    def snapshot(self) -> dict:
        """입력 내용 없이 Queue 크기와 현재 제출 위치만 반환합니다."""

        batch = self.active_batch
        return {"accepting": self.accepting and self.server.background_tasks.accepting(SUBMISSION_TASK_IDENTIFIER),
                "queued_batches": self.pending_batches.qsize(),
                "active_job_identifier": batch.requests[0]["job_id"] if batch else None,
                "next_request_index": batch.next_request_index if batch else None,
                "active_request_identifier": batch.attempt.request_identifier if batch and batch.attempt else None}

    async def finish_interrupted_batch(self, requests: list[dict], message: str) -> None:
        """접수 ID가 없는 요청만 중단으로 기록하며 정리 오류가 Worker를 종료하지 못하게 합니다."""

        from .application import cleanup_submission_uploads

        try:
            await complete_thread_call(self.server.database.stop_unsubmitted_requests,
                                    [request["request_id"] for request in requests], message)
        except Exception:
            LOGGER.exception("미제출 요청 상태 기록 실패: job_id=%s", requests[0]["job_id"])
        try:
            await cleanup_submission_uploads(self.server, requests)
        except Exception:
            LOGGER.exception("제출 입력 정리 실패: job_id=%s", requests[0]["job_id"])

    async def stop(self) -> None:
        """Worker를 종료하고 대기 Metadata를 정리하되 이미 ComfyUI가 접수한 요청은 유지합니다."""

        self.accepting = False
        await self.server.background_tasks.stop_task(SUBMISSION_TASK_IDENTIFIER)
        if self.active_batch is not None:
            await self.finish_interrupted_batch(self.active_batch.requests, "서버 종료로 ComfyUI 제출이 중단됐습니다. 자동 재제출하지 않습니다.")
            self.active_batch = None
            self.pending_batches.task_done()
        while not self.pending_batches.empty():
            batch = self.pending_batches.get_nowait()
            requests = batch.requests
            self.waiting_batches.pop(requests[0]["job_id"], None)
            try:
                await self.finish_interrupted_batch(requests, "서버 종료로 대기 중 제출이 중단됐습니다. 자동 재제출하지 않습니다.")
            finally:
                self.pending_batches.task_done()
