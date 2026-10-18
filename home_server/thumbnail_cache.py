"""압축된 썸네일의 개수 제한 LRU Cache와 기동 시 백그라운드 생성을 제공합니다."""

from __future__ import annotations

import heapq
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, TimeoutError
from io import BytesIO
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageOps, UnidentifiedImageError

from .output_timing import OutputTimingRecorder, measure_output_step


PREVIEW_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PREVIEW_SIZE = 384
MAX_PREVIEW_PIXELS = 80_000_000
LOGGER = logging.getLogger(__name__)
ThumbnailKey = tuple[Path, int, int]


class ThumbnailTooLargeError(ValueError):
    """원본의 픽셀 수가 썸네일 생성 제한을 초과했음을 나타냅니다."""


class ThumbnailWarmupStopped(Exception):
    """서버 종료로 백그라운드 Cache 채우기를 중단합니다."""


def create_thumbnail_bytes(image_path: Path) -> bytes:
    """원본을 작은 WebP bytes로 변환하고 모든 Bitmap과 Buffer를 닫습니다."""

    with Image.open(image_path) as source_image:
        if source_image.width * source_image.height > MAX_PREVIEW_PIXELS:
            raise ThumbnailTooLargeError("미리보기 크기 제한을 초과했습니다.")
        with ImageOps.exif_transpose(source_image) as oriented_image:
            image_mode = "RGBA" if "A" in oriented_image.getbands() or "transparency" in oriented_image.info else "RGB"
            with oriented_image.convert(image_mode) as thumbnail_image:
                thumbnail_image.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
                with BytesIO() as output_buffer:
                    thumbnail_image.save(output_buffer, format="WEBP", quality=75)
                    return output_buffer.getvalue()


class ThumbnailCache:
    """WebP bytes만 LRU로 보관하고 중복 생성·동시 Bitmap 메모리를 제어합니다."""

    def __init__(self, maximum_entries: int) -> None:
        """Cache의 개수 제한과 두 개의 동시 생성 Slot을 준비합니다."""

        if type(maximum_entries) is not int or maximum_entries < 1:
            raise ValueError("thumbnail_cache_max_entries는 1 이상의 정수여야 합니다.")
        self.maximum_entries = maximum_entries
        self._cached_thumbnails: OrderedDict[ThumbnailKey, bytes] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._in_progress: dict[ThumbnailKey, Future[bytes]] = {}
        self._generation_slots = threading.BoundedSemaphore(2)
        self._warmup_stop = threading.Event()
        self._warmup_thread: threading.Thread | None = None

    def get_or_create(
        self, image_path: Path, modified_at_ns: int, file_size: int, *, background: bool = False,
        output_timing: OutputTimingRecorder | None = None,
    ) -> bytes:
        """현재 파일 버전의 bytes를 재사용하고 같은 버전의 생성은 한 번만 수행합니다."""

        thumbnail_key = (image_path, modified_at_ns, file_size)
        with measure_output_step(output_timing, "thumbnail_cache_lock_lookup", emit=True), self._cache_lock:
            cached_thumbnail = self._cached_thumbnails.get(thumbnail_key)
            if cached_thumbnail is not None:
                if output_timing is not None:
                    LOGGER.info("OUTPUT_TIMING id=%s event=thumbnail_cache state=hit", output_timing.identifier)
                if not background:
                    self._cached_thumbnails.move_to_end(thumbnail_key)
                return cached_thumbnail
            pending_thumbnail = self._in_progress.get(thumbnail_key)
            owns_generation = pending_thumbnail is None
            if pending_thumbnail is None:
                pending_thumbnail = Future()
                self._in_progress[thumbnail_key] = pending_thumbnail

        if output_timing is not None:
            LOGGER.info(
                "OUTPUT_TIMING id=%s event=thumbnail_cache state=%s",
                output_timing.identifier, "miss" if owns_generation else "waiting",
            )
        if not owns_generation:
            pending_started_at = time.perf_counter()
            while True:
                if background and self._warmup_stop.is_set():
                    raise ThumbnailWarmupStopped()
                try:
                    thumbnail_bytes = pending_thumbnail.result(timeout=0.1)
                    if output_timing is not None:
                        output_timing.record("thumbnail_pending_wait", pending_started_at, emit=True)
                    return thumbnail_bytes
                except TimeoutError:
                    if pending_thumbnail.done():
                        return pending_thumbnail.result()
                    continue

        acquired_slot = False
        generation_slot_started_at = time.perf_counter()
        try:
            while not acquired_slot:
                if background and self._warmup_stop.is_set():
                    raise ThumbnailWarmupStopped()
                acquired_slot = self._generation_slots.acquire(timeout=0.1)
            if output_timing is not None:
                output_timing.record("thumbnail_generation_slot", generation_slot_started_at, emit=True)
            if background and self._warmup_stop.is_set():
                raise ThumbnailWarmupStopped()
            with measure_output_step(output_timing, "thumbnail_generation", emit=True):
                thumbnail_bytes = create_thumbnail_bytes(image_path)
            with self._cache_lock:
                # 백그라운드 채우기로 사용자가 최근 조회한 썸네일을 밀어내지 않습니다.
                if not background or len(self._cached_thumbnails) < self.maximum_entries:
                    self._cached_thumbnails[thumbnail_key] = thumbnail_bytes
                    if background:
                        self._cached_thumbnails.move_to_end(thumbnail_key, last=False)
                    while len(self._cached_thumbnails) > self.maximum_entries:
                        self._cached_thumbnails.popitem(last=False)
            pending_thumbnail.set_result(thumbnail_bytes)
            return thumbnail_bytes
        except BaseException as exception:
            pending_thumbnail.set_exception(exception)
            raise
        finally:
            if acquired_slot:
                self._generation_slots.release()
            with self._cache_lock:
                self._in_progress.pop(thumbnail_key, None)

    def invalidate(self, image_path: Path) -> None:
        """삭제한 이미지의 모든 파일 버전에서 압축된 썸네일을 제거합니다."""

        with self._cache_lock:
            matching_keys = []
            for thumbnail_key in self._cached_thumbnails:
                if thumbnail_key[0] == image_path:
                    matching_keys.append(thumbnail_key)
            for thumbnail_key in matching_keys:
                del self._cached_thumbnails[thumbnail_key]

    def start_warmup(self, managed_output_directory: Path) -> None:
        """서비스 기동을 기다리게 하지 않고 별도 Thread에서 한 번 Cache를 채웁니다."""

        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            return
        self._warmup_stop.clear()
        self._warmup_thread = threading.Thread(
            target=self._fill_in_background,
            args=(managed_output_directory,),
            name="thumbnail-cache-warmup",
            daemon=True,
        )
        self._warmup_thread.start()

    def stop_warmup(self) -> None:
        """파일 단위로 중단을 요청하고 실행 중인 한 건의 변환이 끝날 때까지 기다립니다."""

        self._warmup_stop.set()
        if self._warmup_thread is not None:
            self._warmup_thread.join()
            self._warmup_thread = None

    def _existing_images(self, managed_output_directory: Path) -> Iterator[tuple[int, str, Path, int]]:
        """관리 폴더 안의 이미지 파일 정보만 읽고 이미지 내용은 아직 열지 않습니다."""

        for image_path in managed_output_directory.rglob("*"):
            if self._warmup_stop.is_set():
                return
            if image_path.suffix.lower() not in PREVIEW_IMAGE_EXTENSIONS:
                continue
            try:
                resolved_path = image_path.resolve()
                if managed_output_directory not in resolved_path.parents or not resolved_path.is_file():
                    continue
                file_stat = resolved_path.stat()
                relative_path = image_path.relative_to(managed_output_directory).as_posix()
            except (OSError, ValueError):
                continue
            yield (file_stat.st_mtime_ns, relative_path, resolved_path, file_stat.st_size)

    def _fill_in_background(self, managed_output_directory: Path) -> None:
        """각 파일을 읽기 전에 현재 버전의 Cache를 확인하고 없는 최신 이미지만 채웁니다."""

        completed_count = 0
        skipped_count = 0
        reused_count = 0
        LOGGER.info("썸네일 Cache 채우기 시작: maximum_entries=%s", self.maximum_entries)
        try:
            selected_images = heapq.nlargest(
                self.maximum_entries, self._existing_images(managed_output_directory),
                key=lambda image: (image[0], image[1]),
            )
            for modified_at_ns, relative_path, image_path, file_size in selected_images:
                if self._warmup_stop.is_set():
                    break
                try:
                    image_path = image_path.resolve()
                    if managed_output_directory not in image_path.parents or not image_path.is_file():
                        skipped_count += 1
                        continue
                    # 목록 확인 후 변경되거나 사용자 조회로 채워진 최신 파일 버전을 확인합니다.
                    current_file_stat = image_path.stat()
                    modified_at_ns = current_file_stat.st_mtime_ns
                    file_size = current_file_stat.st_size
                except OSError:
                    skipped_count += 1
                    continue
                with self._cache_lock:
                    if len(self._cached_thumbnails) >= self.maximum_entries:
                        break
                    if (image_path, modified_at_ns, file_size) in self._cached_thumbnails:
                        reused_count += 1
                        continue
                try:
                    self.get_or_create(image_path, modified_at_ns, file_size, background=True)
                    completed_count += 1
                except ThumbnailWarmupStopped:
                    break
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                    skipped_count += 1
                # 한 건 사이에서 대기하여 요청 처리와 디스크 접근에 여유를 줍니다.
                if self._warmup_stop.wait(0.05):
                    break
        except OSError as exception:
            LOGGER.warning("썸네일 Cache 폴더 탐색 실패: error_type=%s", type(exception).__name__)
        finally:
            LOGGER.info(
                "썸네일 Cache 채우기 종료: completed=%s reused=%s skipped=%s stopped=%s",
                completed_count, reused_count, skipped_count, self._warmup_stop.is_set(),
            )
