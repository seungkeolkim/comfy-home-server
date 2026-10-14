"""결과물 조회 단계의 누적 시간과 느린 파일 작업을 요청별로 기록합니다."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


LOGGER = logging.getLogger(__name__)


@dataclass
class OutputOperationTiming:
    """같은 작업의 호출 수와 누적·최대 시간을 보관합니다."""

    calls: int = 0
    elapsed_seconds: float = 0
    maximum_seconds: float = 0
    maximum_path: str = ""
    slow_calls: int = 0


class OutputTimingRecorder:
    """한 결과물 요청의 HTTP 처리와 파일·DB 작업 시간을 집계합니다."""

    def __init__(self, request_path: str) -> None:
        """요청 ID와 monotonic 시작 시간을 준비합니다."""

        self.identifier = uuid.uuid4().hex
        self.started_at = time.perf_counter()
        self.operations: dict[str, OutputOperationTiming] = {}
        LOGGER.info("OUTPUT_TIMING id=%s event=start path=%s", self.identifier, request_path)

    def record(self, stage: str, started_at: float, path: str = "", *, emit: bool = False) -> None:
        """작업 시간을 누적하고 지정한 단계는 즉시 로그로 남깁니다."""

        elapsed_seconds = time.perf_counter() - started_at
        operation = self.operations.setdefault(stage, OutputOperationTiming())
        operation.calls += 1
        operation.elapsed_seconds += elapsed_seconds
        if elapsed_seconds > operation.maximum_seconds:
            operation.maximum_seconds = elapsed_seconds
            operation.maximum_path = path
        if elapsed_seconds >= 0.01:
            operation.slow_calls += 1
        if emit:
            LOGGER.info(
                "OUTPUT_TIMING id=%s event=step stage=%s elapsed_ms=%.3f path=%s",
                self.identifier, stage, elapsed_seconds * 1000, path or "-",
            )

    def progress(self, *, scanned: int, matched: int, skipped: int) -> None:
        """전체 탐색의 진행량과 요청 시작 후 경과 시간을 기록합니다."""

        LOGGER.info(
            "OUTPUT_TIMING id=%s event=scan_progress scanned=%s matched=%s skipped=%s elapsed_ms=%.3f",
            self.identifier, scanned, matched, skipped, (time.perf_counter() - self.started_at) * 1000,
        )

    def finish(self, status_code: int) -> None:
        """모든 단계 집계와 전체 HTTP 응답 준비 시간을 기록합니다."""

        elapsed_seconds = time.perf_counter() - self.started_at
        for stage, operation in self.operations.items():
            LOGGER.info(
                "OUTPUT_TIMING id=%s event=summary stage=%s calls=%s total_ms=%.3f "
                "max_ms=%.3f slow_calls=%s max_path=%s",
                self.identifier, stage, operation.calls, operation.elapsed_seconds * 1000,
                operation.maximum_seconds * 1000, operation.slow_calls, operation.maximum_path or "-",
            )
        LOGGER.info(
            "OUTPUT_TIMING id=%s event=complete status=%s total_ms=%.3f",
            self.identifier, status_code, elapsed_seconds * 1000,
        )


@contextmanager
def measure_output_step(
    recorder: OutputTimingRecorder | None, stage: str, path: str = "", *, emit: bool = False,
) -> Iterator[None]:
    """측정이 지정된 요청에서만 단계 시간을 기록하고 예외도 그대로 전달합니다."""

    started_at = time.perf_counter() if recorder is not None else 0
    try:
        yield
    finally:
        if recorder is not None:
            recorder.record(stage, started_at, path, emit=emit)
