"""ComfyUI 제출을 단일 Event loop Worker에서 작업 단위로 순차 처리합니다."""

import asyncio
import logging
from dataclasses import dataclass, field


LOGGER = logging.getLogger(__name__)


@dataclass
class SubmissionBatch:
    """대기 작업의 Metadata 참조와 전송 전 취소 표시만 보관합니다."""

    requests: list[dict]
    cancelled_request_identifiers: set[str] = field(default_factory=set)


class SubmissionWorker:
    """이미지·Graph 대신 기존 요청 Metadata만 받아 한 작업의 접수를 끝낸 뒤 다음을 처리합니다."""

    def __init__(self, server) -> None:
        """작업 Metadata Queue와 실행 상태만 보관합니다."""

        self.server = server
        self.pending_batches: asyncio.Queue[SubmissionBatch] = asyncio.Queue()
        self.waiting_batches: dict[str, SubmissionBatch] = {}
        self.active_requests: list[dict] | None = None
        self.worker_task: asyncio.Task | None = None
        self.accepting = False

    @property
    def busy(self) -> bool:
        """대기 중이거나 실제 제출을 처리하는 작업이 있는지 반환합니다."""

        return self.active_requests is not None or not self.pending_batches.empty()

    def start(self) -> None:
        """애플리케이션 Event loop에 단일 제출 Worker를 시작합니다."""

        if self.worker_task is not None and not self.worker_task.done():
            return
        self.accepting = True
        self.worker_task = asyncio.create_task(self.run(), name="comfy-submission-worker")

    def enqueue(self, requests: list[dict]) -> None:
        """Metadata 참조를 즉시 접수하며 같은 Event loop에서는 별도 Lock을 사용하지 않습니다."""

        if not requests:
            return
        if not self.accepting or self.worker_task is None or self.worker_task.done():
            raise RuntimeError("ComfyUI 제출 Worker가 중지 중입니다. 잠시 후 다시 시도해 주세요.")
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
        """각 작업의 전체 제출을 기다리며 개별 작업 오류 후에도 다음 작업을 처리합니다."""

        from .application import _submit_requests

        while True:
            batch = await self.pending_batches.get()
            requests = batch.requests
            self.waiting_batches.pop(requests[0]["job_id"], None)
            self.active_requests = requests
            try:
                LOGGER.info("작업 제출 시작: job_id=%s count=%s", requests[0]["job_id"], len(requests))
                if batch.cancelled_request_identifiers:
                    await asyncio.to_thread(self.server.database.cancel_unsubmitted_requests, list(batch.cancelled_request_identifiers))
                await _submit_requests(self.server, requests)
            except asyncio.CancelledError:
                await self.finish_interrupted_batch(requests, "서버 종료로 ComfyUI 제출이 중단됐습니다. 자동 재제출하지 않습니다.")
                raise
            except Exception:
                LOGGER.exception("작업 제출 Worker 오류: job_id=%s", requests[0]["job_id"])
                await self.finish_interrupted_batch(requests, "작업 제출 처리 중 오류가 발생했습니다. ComfyUI 접수 여부를 확인해 주세요.")
            finally:
                LOGGER.info("작업 제출 종료: job_id=%s", requests[0]["job_id"])
                self.active_requests = None
                self.pending_batches.task_done()

    async def finish_interrupted_batch(self, requests: list[dict], message: str) -> None:
        """접수 ID가 없는 요청만 중단으로 기록하며 정리 오류가 Worker를 종료하지 못하게 합니다."""

        from .application import cleanup_submission_uploads

        try:
            await asyncio.to_thread(self.server.database.stop_unsubmitted_requests,
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
        if self.worker_task is not None:
            self.worker_task.cancel()
            await asyncio.gather(self.worker_task, return_exceptions=True)
            self.worker_task = None
        while not self.pending_batches.empty():
            batch = self.pending_batches.get_nowait()
            requests = batch.requests
            self.waiting_batches.pop(requests[0]["job_id"], None)
            try:
                await self.finish_interrupted_batch(requests, "서버 종료로 대기 중 제출이 중단됐습니다. 자동 재제출하지 않습니다.")
            finally:
                self.pending_batches.task_done()
