"""상시 asyncio Task의 진행 상태·장애 복구·정상 종료를 공통 관리합니다."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


LOGGER = logging.getLogger(__name__)
RESTART_DELAYS_SECONDS = (1, 2, 5, 10, 30)


def timestamp_now() -> str:
    """운영 상태 API에 사용할 UTC 시각을 반환합니다."""

    return datetime.now(timezone.utc).isoformat()


async def complete_thread_call(function: Callable, *arguments: Any, **keyword_arguments: Any) -> Any:
    """취소돼도 실제 Thread가 끝날 때까지 기다려 복구 Task와 IO가 겹치지 않게 합니다."""

    operation = asyncio.create_task(asyncio.to_thread(function, *arguments, **keyword_arguments))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        # asyncio Task 취소는 이미 실행 중인 Thread를 중단하지 않습니다.
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not operation.cancelled():
            operation.exception()
        raise


@dataclass
class ManagedBackgroundTask:
    """Task가 교체돼도 유지할 진행 상태와 재시작 정책을 보관합니다."""

    identifier: str
    label: str
    coroutine_factory: Callable[[], Awaitable[None]]
    timeout_seconds: float
    task: asyncio.Task | None = None
    enabled: bool = True
    state: str = "stopped"
    phase: str = "starting"
    idle: bool = False
    restart_count: int = 0
    consecutive_failures: int = 0
    started_at: str | None = None
    last_progress_at: str | None = None
    last_error: str | None = None
    last_progress_monotonic: float = field(default_factory=time.monotonic)
    started_monotonic: float = 0
    restart_after: float = 0
    cancellation_requested: bool = False

    def progress(self, phase: str, *, timeout_seconds: float = 180, idle: bool = False) -> None:
        """완료된 단계나 새 단계 진입을 기록하고 해당 단계의 정체 제한을 갱신합니다."""

        self.phase = phase
        self.idle = idle
        self.timeout_seconds = timeout_seconds
        self.last_progress_at = timestamp_now()
        self.last_progress_monotonic = time.monotonic()
        if not self.cancellation_requested:
            self.state = "idle" if idle else "running"

    def snapshot(self) -> dict[str, Any]:
        """Exception 객체나 업무 데이터 없이 운영에 필요한 상태만 반환합니다."""

        return {
            "identifier": self.identifier, "label": self.label, "state": self.state,
            "phase": self.phase, "restart_count": self.restart_count,
            "consecutive_failures": self.consecutive_failures, "started_at": self.started_at,
            "last_progress_at": self.last_progress_at, "last_error": self.last_error,
            "progress_age_seconds": round(time.monotonic() - self.last_progress_monotonic, 2),
            "restart_in_seconds": round(max(0, self.restart_after - time.monotonic()), 2),
            "alive": self.task is not None and not self.task.done(),
        }


class BackgroundTaskSupervisor:
    """하나의 감시 Task에서 등록된 Task의 종료·정체와 Backoff 재시작을 관리합니다."""

    def __init__(self, *, check_interval_seconds: float = 1, restart_delays: tuple[float, ...] = RESTART_DELAYS_SECONDS) -> None:
        """업무 Queue와 독립된 감시 Registry 및 종료 Gate를 준비합니다."""

        self.registrations: dict[str, ManagedBackgroundTask] = {}
        self.supervisor_task: asyncio.Task | None = None
        self.check_interval_seconds = check_interval_seconds
        self.restart_delays = restart_delays
        self.wakeup = asyncio.Event()
        self.stopping = False

    def register(self, identifier: str, label: str, coroutine_factory: Callable[[], Awaitable[None]],
                 *, timeout_seconds: float = 180) -> ManagedBackgroundTask:
        """서버 시작 전에 중복되지 않는 Task와 초기 정체 제한을 등록합니다."""

        if identifier in self.registrations:
            raise ValueError("이미 등록된 Background Task입니다: " + identifier)
        registration = ManagedBackgroundTask(identifier, label, coroutine_factory, timeout_seconds)
        self.registrations[identifier] = registration
        return registration

    def accepting(self, identifier: str) -> bool:
        """Worker 복구 대기 중에도 Queue는 받되 Supervisor 종료 시에는 접수를 막습니다."""

        registration = self.registrations[identifier]
        return (not self.stopping and registration.enabled and self.supervisor_task is not None
                and not self.supervisor_task.done())

    def start(self) -> None:
        """등록 Task와 공통 감시 Task를 각각 하나씩 시작합니다."""

        if self.supervisor_task is not None and not self.supervisor_task.done():
            return
        self.stopping = False
        for registration in self.registrations.values():
            registration.enabled = True
            self._start_registered_task(registration)
        self.supervisor_task = asyncio.create_task(self.run(), name="background-task-supervisor")

    async def _execute_registered_task(self, registration: ManagedBackgroundTask) -> None:
        """Factory 자체의 예외도 감시 대상 Task의 예외로 전달합니다."""

        await registration.coroutine_factory()

    def _wake_on_completion(self, finished_task: asyncio.Task) -> None:
        """Task 종료를 Polling 주기보다 빠르게 감시자에게 알립니다."""

        self.wakeup.set()

    def _start_registered_task(self, registration: ManagedBackgroundTask) -> None:
        """이전 Task가 완전히 종료된 경우에만 새 실행을 시작합니다."""

        if registration.task is not None and not registration.task.done():
            return
        if registration.started_at is not None:
            registration.restart_count += 1
        registration.started_at = timestamp_now()
        registration.started_monotonic = time.monotonic()
        registration.restart_after = 0
        registration.cancellation_requested = False
        registration.progress("starting", timeout_seconds=registration.timeout_seconds)
        registration.task = asyncio.create_task(self._execute_registered_task(registration), name=registration.identifier)
        registration.task.add_done_callback(self._wake_on_completion)
        LOGGER.info("Background Task 시작: identifier=%s restart_count=%s", registration.identifier, registration.restart_count)

    def _inspect_registered_task(self, registration: ManagedBackgroundTask) -> None:
        """종료를 Backoff로 복구하고 정체 시 이전 실행의 취소 완료까지 기다립니다."""

        if not registration.enabled:
            return
        current_time = time.monotonic()
        if registration.task is None:
            if current_time >= registration.restart_after:
                self._start_registered_task(registration)
            return
        if registration.task.done():
            exception = None if registration.task.cancelled() else registration.task.exception()
            if exception is not None:
                registration.last_error = f"{type(exception).__name__}: {exception}"
                LOGGER.error("Background Task 종료: identifier=%s", registration.identifier,
                             exc_info=(type(exception), exception, exception.__traceback__))
            elif not registration.cancellation_requested:
                registration.last_error = "예상하지 못한 Task 취소" if registration.task.cancelled() else "예상하지 못한 Task 종료"
                LOGGER.warning("Background Task 종료: identifier=%s reason=%s", registration.identifier, registration.last_error)
            if registration.last_progress_monotonic - registration.started_monotonic >= 60:
                registration.consecutive_failures = 0
            registration.consecutive_failures += 1
            delay_index = min(registration.consecutive_failures - 1, len(self.restart_delays) - 1)
            registration.restart_after = current_time + self.restart_delays[delay_index]
            registration.state = "recovering"
            registration.task = None
            LOGGER.warning("Background Task 복구 대기: identifier=%s delay_seconds=%s", registration.identifier, self.restart_delays[delay_index])
        elif not registration.idle and not registration.cancellation_requested:
            if current_time - registration.last_progress_monotonic > registration.timeout_seconds:
                registration.last_error = "단계 진행 제한 초과: " + registration.phase
                registration.state = "stalled"
                registration.cancellation_requested = True
                registration.task.cancel()
                LOGGER.error("Background Task 정체: identifier=%s phase=%s", registration.identifier, registration.phase)

    async def run(self) -> None:
        """감시 중 개별 상태 처리 오류가 나도 나머지 Task 감시를 계속합니다."""

        while not self.stopping:
            self.wakeup.clear()
            for registration in self.registrations.values():
                try:
                    self._inspect_registered_task(registration)
                except Exception:
                    LOGGER.exception("Background Task 감시 실패: identifier=%s", registration.identifier)
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.check_interval_seconds)
            except TimeoutError:
                pass

    async def stop_task(self, identifier: str) -> None:
        """개별 실행의 재시작을 먼저 차단한 뒤 실제 종료를 기다립니다."""

        registration = self.registrations[identifier]
        registration.enabled = False
        if registration.task is not None:
            if not registration.task.done() and not registration.cancellation_requested:
                registration.task.cancel()
            await asyncio.gather(registration.task, return_exceptions=True)
            registration.task = None
        registration.state = "stopped"

    async def stop(self) -> None:
        """정상 종료 Gate를 닫고 감시자와 등록 Task를 중복 재시작 없이 종료합니다."""

        self.stopping = True
        self.wakeup.set()
        if self.supervisor_task is not None:
            await asyncio.gather(self.supervisor_task, return_exceptions=True)
            self.supervisor_task = None
        await asyncio.gather(*(self.stop_task(identifier) for identifier in self.registrations))

    def snapshot(self) -> dict[str, Any]:
        """현재 감시자와 Task별 생존·복구 상태를 조회합니다."""

        return {"running": self.supervisor_task is not None and not self.supervisor_task.done() and not self.stopping,
                "tasks": [registration.snapshot() for registration in self.registrations.values()]}
