"""공통 Supervisor의 장애 격리·Backoff·정체 복구와 Thread 종료 경계를 검증합니다."""

import asyncio
import threading
import time
from collections.abc import Callable

from home_server.background_tasks import BackgroundTaskSupervisor, complete_thread_call


async def wait_until_condition(condition: Callable[[], bool], timeout_seconds: float = 3) -> None:
    """상태 변화까지 Event loop를 양보하고 제한 시간 초과를 실패로 처리합니다."""

    deadline = time.monotonic() + timeout_seconds
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError("기대 상태로 전환되지 않았습니다.")
        await asyncio.sleep(0.005)


def test_crashed_task_uses_backoff_and_keeps_other_task_running() -> None:
    """실패한 Task만 간격을 두고 복구하며 정상 Task의 실행은 유지합니다."""

    async def verify_recovery() -> None:
        """두 번의 실제 예외와 한 번의 예상하지 못한 정상 반환을 재현합니다."""

        supervisor = BackgroundTaskSupervisor(check_interval_seconds=0.005, restart_delays=(0.02, 0.04, 0.06))
        invocation_times = []
        healthy_invocations = []

        async def failing_task() -> None:
            """재시작 세 번 뒤에는 정상 대기 상태를 유지합니다."""

            invocation_times.append(time.monotonic())
            if len(invocation_times) <= 2:
                raise RuntimeError("injected failure")
            if len(invocation_times) == 3:
                return
            await asyncio.Event().wait()

        async def healthy_task() -> None:
            """다른 Task의 장애로 재시작되지 않아야 하는 실행입니다."""

            healthy_invocations.append(time.monotonic())
            await asyncio.Event().wait()

        failing_registration = supervisor.register("failing", "실패 테스트", failing_task)
        healthy_registration = supervisor.register("healthy", "정상 테스트", healthy_task)
        supervisor.start()
        try:
            await wait_until_condition(lambda: len(invocation_times) == 4)
            assert failing_registration.restart_count == 3
            assert len(healthy_invocations) == 1
            assert healthy_registration.restart_count == 0
            assert invocation_times[1] - invocation_times[0] >= 0.019
            assert invocation_times[2] - invocation_times[1] >= 0.039
            assert invocation_times[3] - invocation_times[2] >= 0.059
            assert failing_registration.last_error == "예상하지 못한 Task 종료"
        finally:
            await supervisor.stop()
        assert not supervisor.snapshot()["running"]
        assert all(registration.task is None for registration in supervisor.registrations.values())

    asyncio.run(verify_recovery())


def test_stalled_task_is_replaced_only_after_old_execution_finishes() -> None:
    """정체된 실행을 취소하고 종료된 뒤에만 교체하여 동시 실행을 방지합니다."""

    async def verify_stall_recovery() -> None:
        """첫 실행은 멈추고 두 번째는 Idle 상태로 살아 있는지 확인합니다."""

        supervisor = BackgroundTaskSupervisor(check_interval_seconds=0.005, restart_delays=(0.01,))
        invocation_count = 0
        concurrent_count = 0
        maximum_concurrent_count = 0

        async def monitored_task() -> None:
            """진행 없는 실행과 정상적인 빈 Queue 대기를 구별합니다."""

            nonlocal invocation_count, concurrent_count, maximum_concurrent_count
            invocation_count += 1
            concurrent_count += 1
            maximum_concurrent_count = max(maximum_concurrent_count, concurrent_count)
            registration.progress("waiting", timeout_seconds=0.02, idle=invocation_count > 1)
            try:
                await asyncio.Event().wait()
            finally:
                concurrent_count -= 1

        registration = supervisor.register("monitored", "정체 테스트", monitored_task)
        supervisor.start()
        try:
            await wait_until_condition(lambda: invocation_count == 2)
            await asyncio.sleep(0.08)
            assert invocation_count == 2
            assert maximum_concurrent_count == 1
            assert registration.state == "idle"
            assert registration.last_error == "단계 진행 제한 초과: waiting"
        finally:
            await supervisor.stop()
        assert invocation_count == 2

    asyncio.run(verify_stall_recovery())


def test_running_thread_io_must_finish_before_replacement_starts() -> None:
    """Task 취소 후에도 남아 있는 DB Thread와 복구 실행이 겹치지 않습니다."""

    async def verify_thread_boundary() -> None:
        """Worker가 취소돼도 외부 Gate를 해제하기 전에는 다음 실행이 시작되지 않습니다."""

        supervisor = BackgroundTaskSupervisor(check_interval_seconds=0.005, restart_delays=(0.01,))
        thread_started = threading.Event()
        release_thread = threading.Event()
        invocation_count = 0

        def blocked_database_write() -> None:
            """실제 DB 쓰기처럼 Task 취소로 중단되지 않는 Thread를 재현합니다."""

            thread_started.set()
            release_thread.wait(3)

        async def monitored_task() -> None:
            """첫 실행만 Thread IO를 사용하고 재시작 뒤에는 대기합니다."""

            nonlocal invocation_count
            invocation_count += 1
            if invocation_count == 1:
                registration.progress("database_write", timeout_seconds=0.02)
                await complete_thread_call(blocked_database_write)
            registration.progress("waiting", idle=True)
            await asyncio.Event().wait()

        registration = supervisor.register("monitored", "Thread 테스트", monitored_task)
        supervisor.start()
        try:
            await wait_until_condition(thread_started.is_set)
            await wait_until_condition(lambda: registration.state == "stalled")
            await asyncio.sleep(0.04)
            assert invocation_count == 1
            assert not registration.task.done()
            release_thread.set()
            await wait_until_condition(lambda: invocation_count == 2)
        finally:
            release_thread.set()
            await supervisor.stop()

    asyncio.run(verify_thread_boundary())
