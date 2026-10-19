"""영상별 영속 미리보기와 독립된 Thumbnail LRU, 공유 변환 Queue를 관리합니다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .configuration import AppConfig
from .output_catalog import OutputCatalog
from .video_encoding import VideoEncodingError, VideoEncodingStopped, encode_video_preview, extract_video_thumbnail


LOGGER = logging.getLogger(__name__)


def canonical_filesystem_path(path: Path) -> Path:
    """Windows 확장 경로 접두어를 정규화하여 같은 Root의 경계를 일관되게 비교합니다."""

    resolved_path = str(path.resolve())
    if os.name == "nt":
        if resolved_path.startswith("\\\\?\\UNC\\"):
            resolved_path = "\\\\" + resolved_path[8:]
        elif resolved_path.startswith("\\\\?\\"):
            resolved_path = resolved_path[4:]
    return Path(resolved_path)


class VideoPreviewQueueFull(Exception):
    """대기 Queue가 가득 차 새 사용자 요청을 접수하지 못했음을 나타냅니다."""


@dataclass(frozen=True)
class VideoSource:
    """이동과 독립된 원본 버전 및 현재 경로를 보관합니다."""

    output_id: int
    relative_path: str
    path: Path
    modified_at_ns: int
    file_size: int

    @property
    def identifier(self) -> str:
        """인코딩 설정을 제외한 원본 버전의 안전한 저장 식별자를 반환합니다."""

        identity = f"{self.output_id}:{self.modified_at_ns}:{self.file_size}"
        return hashlib.sha256(identity.encode()).hexdigest()

    def metadata(self) -> dict:
        """절대 경로를 제외한 원본 Metadata를 반환합니다."""

        return {"output_id": self.output_id, "relative_path": self.relative_path,
                "modified_at_ns": self.modified_at_ns, "file_size": self.file_size}


@dataclass
class VideoPreviewTask:
    """진행 중 작업만 메모리에 유지하고 완료/실패 기록은 디스크로 넘깁니다."""

    source: VideoSource
    priority: int
    attempts: int = 0
    state: str = "queued"
    enqueued_at: float = field(default_factory=time.monotonic)
    retry_at: float = 0
    error: str | None = None
    process: subprocess.Popen | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)


class VideoPreviewCache:
    """한 서버 프로세스의 Worker·Scheduler·기동 Producer와 파생 파일 수명을 관리합니다."""

    def __init__(self, configuration: AppConfig, catalog: OutputCatalog) -> None:
        """IO 없는 실행 구조를 준비하며 Lifespan에서 실제 Worker를 시작합니다."""

        self.configuration = configuration
        self.catalog = catalog
        self.root = configuration.runtime_directory / "cache" / "media"
        self._condition = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._tasks: dict[str, VideoPreviewTask] = {}
        self._unsaved_failures: dict[str, dict] = {}
        self._workers: list[threading.Thread] = []
        self._scheduler: threading.Thread | None = None
        self._producer: threading.Thread | None = None
        self._rescan_priority: int | None = None
        self._cleanup_requested = False
        self._thumbnail_slots = threading.BoundedSemaphore(2)
        self._thumbnail_futures: dict[str, Future] = {}
        self._thumbnail_order: OrderedDict[str, Path] = OrderedDict()
        self._stream_readers: dict[str, int] = {}
        self.available = False

    def source(self, output_id: int) -> VideoSource:
        """DB의 최신 경로와 현재 stat으로 원본 버전을 확인하고 링크 경로를 거부합니다."""

        recorded = self.catalog.get_video_source(output_id)
        relative_path = recorded["relative_path"]
        managed_root = canonical_filesystem_path(self.configuration.managed_output_directory)
        source_path = managed_root / relative_path
        if managed_root not in canonical_filesystem_path(source_path).parents:
            raise ValueError("관리 폴더 밖 영상에 접근할 수 없습니다.")
        for component_path in (source_path, *source_path.parents):
            if component_path == managed_root:
                break
            if component_path.is_symlink() or component_path.is_junction():
                raise ValueError("링크 경로 영상은 미리보기를 지원하지 않습니다.")
        source_stat = source_path.stat()
        if not source_path.is_file():
            raise FileNotFoundError("영상 파일이 없습니다.")
        return VideoSource(output_id, relative_path, source_path, source_stat.st_mtime_ns, source_stat.st_size)

    def directory(self, area: str, identifier: str, create: bool = False) -> Path:
        """고정 저장 영역과 Hex 식별자만 허용하고 Root 밖으로 연결된 폴더를 거부합니다."""

        if area not in {"previews", "thumbnails"} or len(identifier) != 64 or any(character not in "0123456789abcdef" for character in identifier):
            raise ValueError("잘못된 Cache 식별자입니다.")
        directory = self.root / area / identifier
        for checked_path in (self.root, self.root.parent, self.root / area, directory):
            if checked_path.is_symlink() or checked_path.is_junction():
                raise ValueError("Cache 폴더의 링크 경로는 허용하지 않습니다.")
        runtime_root = canonical_filesystem_path(self.configuration.runtime_directory)
        resolved_directory = canonical_filesystem_path(directory)
        if runtime_root not in resolved_directory.parents:
            raise ValueError("Cache Root 밖의 경로입니다.")
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _read_metadata(self, directory: Path) -> dict:
        """완료/실패 Metadata가 없거나 불완전하면 빈 상태로 취급합니다."""

        metadata_path = directory / "source.json"
        if metadata_path.is_symlink() or metadata_path.is_junction():
            raise ValueError("Cache Metadata 링크는 허용하지 않습니다.")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return metadata if isinstance(metadata, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _write_metadata(self, directory: Path, metadata: dict) -> None:
        """같은 폴더의 임시 JSON을 원자적으로 교체하고 중간 쓰기를 노출하지 않습니다."""

        temporary_path = directory / f"metadata-{uuid.uuid4().hex}.partial"
        try:
            temporary_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            temporary_path.replace(directory / "source.json")
        finally:
            temporary_path.unlink(missing_ok=True)

    def complete_file(self, source: VideoSource) -> Path | None:
        """기존 완료 파일은 현재 인코딩 설정과 비교하거나 다시 Probe하지 않습니다."""

        directory = self.directory("previews", source.identifier)
        metadata = self._read_metadata(directory)
        output_path = directory / "preview.mp4"
        if output_path.is_symlink() or output_path.is_junction():
            raise ValueError("미리보기 링크 파일은 허용하지 않습니다.")
        if metadata.get("complete") is True and output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        return None

    def start(self) -> None:
        """의존성을 확인한 뒤 전용 Worker·Scheduler와 한 번 실행하는 Producer를 시작합니다."""

        if self.available:
            return
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            LOGGER.warning("영상 미리보기 비활성: FFmpeg/ffprobe 설치가 필요합니다.")
            return
        self._stop.clear()
        self.available = True
        for worker_index in range(self.configuration.video_preview_worker_count):
            worker = threading.Thread(target=self._worker_loop, name=f"video-preview-worker-{worker_index}", daemon=True)
            self._workers.append(worker)
            worker.start()
        self._scheduler = threading.Thread(target=self._scheduler_loop, name="video-preview-scheduler", daemon=True)
        self._scheduler.start()
        self._producer = threading.Thread(target=self._startup_fill, name="video-preview-startup", daemon=True)
        self._producer.start()

    def stop(self) -> None:
        """접수와 재탐색을 중단하고 제한 시간 후 남은 프로세스와 Worker를 회수합니다."""

        self.available = False
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        deadline = time.monotonic() + self.configuration.video_preview_shutdown_timeout_seconds
        for thread in (self._producer, self._scheduler, *self._workers):
            if thread is not None:
                thread.join(timeout=max(0, deadline - time.monotonic()))
        with self._condition:
            for task in self._tasks.values():
                task.stop_event.set()
                if task.process is not None and task.process.poll() is None:
                    task.process.kill()
            self._condition.notify_all()
        termination_deadline = time.monotonic() + 16
        for thread in (self._producer, self._scheduler, *self._workers):
            if thread is not None:
                thread.join(timeout=max(0, termination_deadline - time.monotonic()))
        self._workers.clear()

    def enqueue(self, output_id: int, priority: int = 0, retry: bool = False) -> dict:
        """완료본·기존 Task·실패 제한을 재사용하고 빈 Queue에만 새 작업을 접수합니다."""

        source = self.source(output_id)
        if self.complete_file(source) is not None:
            return self.describe(source)
        if not self.available or self._stop.is_set():
            raise VideoEncodingError("FFmpeg 미리보기 서비스를 사용할 수 없습니다.")
        directory = self.directory("previews", source.identifier, create=True)
        with self._condition:
            if self.complete_file(source) is not None:
                return self.describe(source)
            metadata = self._read_metadata(directory)
            task = self._tasks.get(source.identifier)
            if task is not None:
                task.priority = min(task.priority, priority)
                self._condition.notify_all()
                return self._task_description(task)
            if (metadata.get("failed") or source.identifier in self._unsaved_failures) and not retry:
                return self.describe(source)
            waiting_count = sum(task.state != "converting" for task in self._tasks.values())
            if waiting_count >= self.configuration.video_preview_queue_max_entries:
                raise VideoPreviewQueueFull()
            task = VideoPreviewTask(source, priority, attempts=0 if retry else metadata.get("attempts", 0))
            retry_at = 0 if retry else metadata.get("retry_at", 0)
            if retry_at > time.time():
                task.state = "retry_wait"
                task.retry_at = retry_at
            if retry:
                self._write_metadata(directory, source.metadata())
                self._unsaved_failures.pop(source.identifier, None)
            self._tasks[source.identifier] = task
            self._condition.notify_all()
            LOGGER.info("VIDEO_PREVIEW event=queued output_id=%s priority=%s", output_id, priority)
            return self._task_description(task)

    def describe(self, source: VideoSource) -> dict:
        """현재 상태만 반환하고 단순 조회로 실패 횟수나 재시도를 변경하지 않습니다."""

        with self._condition:
            task = self._tasks.get(source.identifier)
            if task is not None:
                return self._task_description(task)
            if source.identifier in self._unsaved_failures:
                return {"state": "failed", "identifier": source.identifier, "stream_ready": False,
                        **self._unsaved_failures[source.identifier]}
        directory = self.directory("previews", source.identifier)
        metadata = self._read_metadata(directory)
        state = "ready" if self.complete_file(source) is not None else "failed" if metadata.get("failed") else "missing"
        return {"state": state, "identifier": source.identifier, "stream_ready": state == "ready",
                "attempts": metadata.get("attempts", 0), "error": metadata.get("error")}

    def _task_description(self, task: VideoPreviewTask) -> dict:
        """공유 Task의 상태와 선두 출력 여부를 짧게 조회합니다."""

        partial_path = self.directory("previews", task.source.identifier) / "preview.partial.mp4"
        try:
            stream_ready = task.state == "converting" and partial_path.stat().st_size > 1024
        except FileNotFoundError:
            stream_ready = False
        return {"state": task.state, "identifier": task.source.identifier, "stream_ready": stream_ready,
                "attempts": task.attempts, "retry_at": task.retry_at, "error": task.error}

    def request_scan(self, priority: int = 1, cleanup: bool = False) -> None:
        """포화된 자동 접수와 수동 동기화 신호를 합쳐 메모리 증가 없이 재탐색을 예약합니다."""

        if not self.available:
            return
        with self._condition:
            self._rescan_priority = min(priority, self._rescan_priority) if self._rescan_priority is not None else priority
            self._cleanup_requested = self._cleanup_requested or cleanup
            self._condition.notify_all()

    def completed_request(self, request_id: str) -> None:
        """DB Commit 뒤 신규 완료 요청의 영상만 접수하고 포화 시 재탐색으로 회수합니다."""

        if not self.configuration.video_preview_on_completion_enabled or not self.available:
            return
        for output in self.catalog.iter_video_sources(request_id):
            try:
                self.enqueue(output["output_id"], priority=1)
            except VideoPreviewQueueFull:
                self.request_scan()
                return
            except (OSError, ValueError, VideoEncodingError):
                LOGGER.warning("VIDEO_PREVIEW event=completion_enqueue_failed output_id=%s", output["output_id"])

    def _discover(self, priority: int, wait_for_capacity: bool) -> None:
        """전체 미변환 영상을 페이지 탐색하며 Queue 포화 뒤에도 누락 없이 이어갑니다."""

        for output in self.catalog.iter_video_sources():
            while not self._stop.is_set():
                try:
                    self.enqueue(output["output_id"], priority)
                    break
                except VideoPreviewQueueFull:
                    if not wait_for_capacity:
                        self.request_scan(priority)
                        return
                    with self._condition:
                        self._condition.wait(timeout=0.5)
                except (OSError, ValueError, VideoEncodingError):
                    break
            if self._stop.is_set():
                return

    def _startup_fill(self) -> None:
        """한 번 정리하고 전체 누락분 접수를 마친 뒤 Producer thread를 종료합니다."""

        try:
            self.cleanup()
            if self.configuration.video_preview_warmup_enabled:
                self._discover(priority=2, wait_for_capacity=True)
        except Exception:
            LOGGER.exception("VIDEO_PREVIEW event=startup_failed")
        finally:
            LOGGER.info("VIDEO_PREVIEW event=startup_producer_finished")

    def _scheduler_loop(self) -> None:
        """지연 재시도와 포화 후 재탐색만 관리하고 변환 Worker를 대기 시간에 점유하지 않습니다."""

        while not self._stop.is_set():
            with self._condition:
                due_times = []
                for task in self._tasks.values():
                    if task.state == "retry_wait":
                        if task.retry_at <= time.time():
                            task.state = "queued"
                            task.enqueued_at = time.monotonic()
                        else:
                            due_times.append(task.retry_at)
                self._condition.notify_all()
                priority, cleanup = self._rescan_priority, self._cleanup_requested
                self._rescan_priority = None
                self._cleanup_requested = False
            if cleanup:
                self.cleanup()
            if priority is not None:
                self._discover(priority, wait_for_capacity=False)
            with self._condition:
                delay = max(0.05, min(due_times) - time.time()) if due_times else 1
                self._condition.wait(timeout=min(delay, 1))

    def _worker_loop(self) -> None:
        """Queue 우선순위와 Aging으로 한 건씩 처리하고 빈 Queue에서는 대기합니다."""

        while not self._stop.is_set():
            with self._condition:
                queued_tasks = [task for task in self._tasks.values() if task.state == "queued"]
                if not queued_tasks:
                    self._condition.wait(timeout=1)
                    continue
                task = min(queued_tasks, key=lambda candidate: candidate.enqueued_at + candidate.priority * 30)
                task.state = "converting"
                self._condition.notify_all()
            LOGGER.info("VIDEO_PREVIEW event=started output_id=%s queue_wait_ms=%.2f",
                        task.source.output_id, (time.monotonic() - task.enqueued_at) * 1000)
            try:
                self._convert(task)
            except VideoEncodingStopped:
                self._finish_task(task, "stopped")
            except Exception as exception:
                try:
                    self._record_failure(task, exception)
                except Exception:
                    LOGGER.exception("VIDEO_PREVIEW event=failure_handling_failed output_id=%s", task.source.output_id)
                    self._finish_task(task, "failed")

    def _finish_task(self, task: VideoPreviewTask, state: str) -> None:
        """기존 Reader에 완료 상태를 전달하고 Queue 메모리를 해제합니다."""

        with self._condition:
            task.state = state
            self._tasks.pop(task.source.identifier, None)
            self._condition.notify_all()

    def _convert(self, task: VideoPreviewTask) -> None:
        """원본을 재확인하여 설정 Snapshot대로 변환하고 성공한 파일만 확정합니다."""

        source = self.source(task.source.output_id)
        if source.identifier != task.source.identifier:
            raise VideoEncodingStopped()
        directory = self.directory("previews", source.identifier, create=True)
        partial_path = directory / "preview.partial.mp4"
        started_at = time.monotonic()
        task.attempts += 1

        def record_process(process: subprocess.Popen) -> None:
            """종료와 원본 무효화를 위해 현재 FFmpeg를 Manager에 등록합니다."""

            with self._condition:
                task.process = process

        try:
            information = encode_video_preview(source.path, partial_path, self.configuration, task.stop_event, record_process)
            current_source = self.source(source.output_id)
            if task.stop_event.is_set() or current_source.identifier != source.identifier:
                raise VideoEncodingStopped()
            if not partial_path.is_file() or partial_path.stat().st_size == 0:
                raise VideoEncodingError("변환된 미리보기 데이터가 없습니다.")
            snapshot = {name: value for name, value in asdict(self.configuration).items()
                        if name in {"video_preview_max_dimension", "video_preview_frame_rate", "video_preview_video_bitrate_kbps", "video_preview_audio_bitrate_kbps"}}
            # Windows에서 Reader가 임시 파일을 열고 있는 동안 rename하지 않도록 짧게 직렬화합니다.
            with self._condition:
                output_size = partial_path.stat().st_size
                partial_path.replace(directory / "preview.mp4")
                self._write_metadata(directory, {**current_source.metadata(), **information,
                                                "complete": True, "attempts": task.attempts, "settings": snapshot})
                self._finish_task(task, "ready")
            LOGGER.info("VIDEO_PREVIEW event=complete output_id=%s elapsed_ms=%.2f bytes=%s",
                        source.output_id, (time.monotonic() - started_at) * 1000, output_size)
        finally:
            task.process = None
            partial_path.unlink(missing_ok=True)

    def _record_failure(self, task: VideoPreviewTask, exception: Exception) -> None:
        """상한 있는 실패 정보만 영속화하고 일시 오류는 Scheduler에 지연 재등록합니다."""

        if task.stop_event.is_set() or self._stop.is_set():
            self._finish_task(task, "stopped")
            return
        if isinstance(exception, FileNotFoundError):
            self._finish_task(task, "stopped")
            self.request_scan(cleanup=True)
            return
        retryable = isinstance(exception, VideoEncodingError) and exception.retryable
        task.error = str(exception) if isinstance(exception, VideoEncodingError) else "미리보기 변환 중 오류가 발생했습니다."
        may_retry = retryable and task.attempts < self.configuration.video_preview_retry_max_attempts
        delay = min(self.configuration.video_preview_retry_initial_delay_seconds * 2 ** max(0, task.attempts - 1),
                    self.configuration.video_preview_retry_max_delay_seconds)
        task.retry_at = time.time() + delay if may_retry else 0
        metadata = {**task.source.metadata(), "attempts": task.attempts, "error": task.error,
                    "retry_at": task.retry_at, "failed": not may_retry}
        try:
            self._write_metadata(self.directory("previews", task.source.identifier, create=True), metadata)
        except OSError:
            may_retry = False
            with self._condition:
                self._unsaved_failures[task.source.identifier] = {"attempts": task.attempts, "error": task.error}
            LOGGER.exception("VIDEO_PREVIEW event=failure_metadata_write_failed output_id=%s", task.source.output_id)
        with self._condition:
            task.state = "retry_wait" if may_retry else "failed"
            if not may_retry:
                self._tasks.pop(task.source.identifier, None)
            self._condition.notify_all()
        LOGGER.warning("VIDEO_PREVIEW event=failed output_id=%s attempts=%s retry=%s error_type=%s",
                       task.source.output_id, task.attempts, may_retry, type(exception).__name__)

    def thumbnail(self, output_id: int) -> tuple[bytes, str]:
        """정지 WebP만 별도 LRU에서 제공하고 동시 Cache Miss의 추출을 공유합니다."""

        source = self.source(output_id)
        if not self.available:
            raise VideoEncodingError("FFmpeg 미리보기 서비스를 사용할 수 없습니다.")
        directory = self.directory("thumbnails", source.identifier)
        poster_path = directory / "poster.webp"
        with self._condition:
            future = self._thumbnail_futures.get(source.identifier)
            owns_generation = future is None
            if owns_generation:
                future = Future()
                self._thumbnail_futures[source.identifier] = future
        if not owns_generation:
            return future.result(timeout=60), source.identifier
        try:
            self.directory("thumbnails", source.identifier, create=True)
            with self._thumbnail_slots:
                if poster_path.is_symlink() or poster_path.is_junction():
                    raise ValueError("Thumbnail 링크는 허용하지 않습니다.")
                if not poster_path.is_file():
                    partial_path = directory / "poster.partial.webp"
                    try:
                        extract_video_thumbnail(source.path, partial_path, self._stop)
                        current_source = self.source(output_id)
                        if current_source.identifier != source.identifier:
                            raise FileNotFoundError("원본 영상이 변경되었습니다.")
                        self._write_metadata(directory, current_source.metadata())
                        partial_path.replace(poster_path)
                    finally:
                        partial_path.unlink(missing_ok=True)
                thumbnail_bytes = poster_path.read_bytes()
                os.utime(poster_path, None)
                with self._condition:
                    self._thumbnail_order[source.identifier] = directory
                    self._thumbnail_order.move_to_end(source.identifier)
                future.set_result(thumbnail_bytes)
                return thumbnail_bytes, source.identifier
        except Exception as exception:
            future.set_exception(exception)
            raise
        finally:
            with self._condition:
                self._thumbnail_futures.pop(source.identifier, None)
            self._trim_thumbnails()

    def _remove_directory(self, area: str, identifier: str) -> None:
        """검증된 Cache Root 내부의 해당 디렉터리만 제거하고 원본에는 접근하지 않습니다."""

        directory = self.directory(area, identifier)
        if directory.exists():
            shutil.rmtree(directory)

    def _trim_thumbnails(self) -> None:
        """이미지와 동일한 개수 상한을 Thumbnail에만 적용하고 영상 저장 영역은 유지합니다."""

        with self._condition:
            for identifier in list(self._thumbnail_order):
                if len(self._thumbnail_order) <= self.configuration.thumbnail_cache_max_entries:
                    break
                if identifier in self._thumbnail_futures:
                    continue
                self._remove_directory("thumbnails", identifier)
                self._thumbnail_order.pop(identifier, None)

    def cleanup(self) -> None:
        """삭제/교체 원본의 파생 파일과 이전 임시 파일을 정리하며 현재 출력 설정은 비교하지 않습니다."""

        for area in ("previews", "thumbnails"):
            area_path = self.root / area
            if not area_path.exists():
                continue
            for candidate in area_path.iterdir():
                if self._stop.is_set():
                    return
                try:
                    directory = self.directory(area, candidate.name)
                    with self._condition:
                        if candidate.name in self._tasks or candidate.name in self._thumbnail_futures or self._stream_readers.get(candidate.name):
                            continue
                        metadata = self._read_metadata(directory)
                        output_id = metadata.get("output_id")
                        invalid = output_id is None
                        if output_id is not None:
                            try:
                                invalid = self.source(output_id).identifier != candidate.name
                            except FileNotFoundError:
                                # Root 자체가 없으면 마운트 문제와 원본 삭제를 구분할 수 없습니다.
                                invalid = self.configuration.managed_output_directory.is_dir()
                        if invalid:
                            self._remove_directory(area, candidate.name)
                            self._thumbnail_order.pop(candidate.name, None)
                            continue
                        for temporary_path in directory.iterdir():
                            if ".partial" in temporary_path.name and temporary_path.is_file() and not temporary_path.is_symlink():
                                temporary_path.unlink()
                        if area == "thumbnails" and (directory / "poster.webp").is_file():
                            self._thumbnail_order[candidate.name] = directory
                except (OSError, ValueError, TypeError):
                    LOGGER.warning("VIDEO_PREVIEW event=cleanup_deferred entry=%s", candidate.name)
        with self._condition:
            self._thumbnail_order = OrderedDict(sorted(self._thumbnail_order.items(), key=thumbnail_last_access))
        self._trim_thumbnails()

    def invalidate_missing(self) -> None:
        """원본 삭제 후 실행 중 Task를 중단하고 파생 파일 정리를 예약합니다."""

        with self._condition:
            for task in list(self._tasks.values()):
                try:
                    if self.source(task.source.output_id).identifier == task.source.identifier:
                        continue
                except (OSError, ValueError):
                    pass
                task.stop_event.set()
                if task.state != "converting":
                    self._tasks.pop(task.source.identifier, None)
            self._cleanup_requested = True
            self._condition.notify_all()

    def stream_chunk(self, source: VideoSource, position: int) -> tuple[bytes, bool]:
        """독립된 읽기 위치에서 변환 중이거나 완성된 파일을 읽습니다."""

        if self.source(source.output_id).identifier != source.identifier:
            return b"", True
        with self._condition:
            directory = self.directory("previews", source.identifier)
            task = self._tasks.get(source.identifier)
            is_complete = self.complete_file(source) is not None
            output_path = directory / ("preview.mp4" if is_complete else "preview.partial.mp4")
            if output_path.exists():
                with output_path.open("rb") as output_file:
                    output_file.seek(position)
                    chunk = output_file.read(64 * 1024)
            else:
                chunk = b""
            finished = is_complete or task is None or task.state not in {"converting", "queued"}
            return chunk, finished

    async def stream(self, source: VideoSource):
        """재생 연결이 끊겨도 변환을 유지하며 느린 Reader마다 파일에서 필요한 구간만 읽습니다."""

        position = 0
        started_at = time.monotonic()
        with self._condition:
            self._stream_readers[source.identifier] = self._stream_readers.get(source.identifier, 0) + 1
        try:
            while not self._stop.is_set():
                try:
                    chunk, finished = await asyncio.to_thread(self.stream_chunk, source, position)
                except (OSError, ValueError):
                    break
                if chunk:
                    if position == 0:
                        LOGGER.info("VIDEO_PREVIEW event=first_stream_chunk output_id=%s elapsed_ms=%.2f",
                                    source.output_id, (time.monotonic() - started_at) * 1000)
                    position += len(chunk)
                    yield chunk
                elif finished:
                    break
                else:
                    await asyncio.sleep(0.1)
        finally:
            LOGGER.info("VIDEO_PREVIEW event=stream_closed output_id=%s bytes=%s elapsed_ms=%.2f",
                        source.output_id, position, (time.monotonic() - started_at) * 1000)
            with self._condition:
                reader_count = self._stream_readers.get(source.identifier, 1) - 1
                if reader_count:
                    self._stream_readers[source.identifier] = reader_count
                else:
                    self._stream_readers.pop(source.identifier, None)
                self._condition.notify_all()


def thumbnail_last_access(entry: tuple[str, Path]) -> float:
    """기동 시 Thumbnail의 최근 파일 접근 시각을 LRU 순서로 복원합니다."""

    try:
        return (entry[1] / "poster.webp").stat().st_mtime
    except OSError:
        return 0
