"""파일별 stat 없이 실제 이미지 해상도를 잠시 재사용합니다."""

from collections import OrderedDict
from pathlib import Path
from threading import Lock
import time
from typing import Callable


class ImageDimensionCache:
    """경로별 해상도를 제한된 수와 TTL로 보관합니다."""

    def __init__(
        self, maximum_entries: int = 2048, refresh_seconds: float = 60,
        monotonic_time: Callable[[], float] = time.monotonic,
    ) -> None:
        """최대 항목 수, 같은 경로의 갱신 간격과 측정용 clock을 설정합니다."""

        self.maximum_entries = maximum_entries
        self.refresh_seconds = refresh_seconds
        self.monotonic_time = monotonic_time
        self.cached_dimensions: OrderedDict[Path, tuple[float, tuple[int, int]]] = OrderedDict()
        self.cache_lock = Lock()

    def get_dimensions(
        self, image_path: Path, read_dimensions: Callable[[Path], tuple[int, int] | None],
    ) -> tuple[int, int] | None:
        """TTL 안의 해상도는 재사용하고 만료된 값은 이미지 header에서 다시 읽습니다."""

        with self.cache_lock:
            cached_entry = self.cached_dimensions.get(image_path)
            if cached_entry is not None:
                expires_at, dimensions = cached_entry
                if self.monotonic_time() < expires_at:
                    self.cached_dimensions.move_to_end(image_path)
                    return dimensions
                del self.cached_dimensions[image_path]
        # 파일 읽기는 Lock 밖에서 수행해 다른 경로의 Cache hit을 막지 않습니다.
        dimensions = read_dimensions(image_path)
        if dimensions is None:
            return None
        with self.cache_lock:
            self.cached_dimensions[image_path] = (
                self.monotonic_time() + self.refresh_seconds, dimensions,
            )
            self.cached_dimensions.move_to_end(image_path)
            while len(self.cached_dimensions) > self.maximum_entries:
                self.cached_dimensions.popitem(last=False)
        return dimensions

    def invalidate(self, image_path: Path) -> None:
        """앱에서 파일을 이동할 때 해당 경로의 기존 해상도를 제거합니다."""

        with self.cache_lock:
            self.cached_dimensions.pop(image_path, None)

    def clear(self) -> None:
        """보관한 해상도를 모두 제거합니다."""

        with self.cache_lock:
            self.cached_dimensions.clear()
