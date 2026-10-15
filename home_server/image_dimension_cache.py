"""파일별 stat 없이 실제 이미지 해상도를 LRU Cache로 재사용합니다."""

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Callable


class ImageDimensionCache:
    """경로별 해상도를 시간 만료 없이 제한된 수만 보관합니다."""

    def __init__(self, maximum_entries: int = 30_000) -> None:
        """최대 항목 수와 경로별 해상도 저장소를 준비합니다."""

        self.maximum_entries = maximum_entries
        self.cached_dimensions: OrderedDict[Path, tuple[int, int]] = OrderedDict()
        self.cache_lock = Lock()

    def get_dimensions(
        self, image_path: Path, read_dimensions: Callable[[Path], tuple[int, int] | None],
    ) -> tuple[int, int] | None:
        """보관한 해상도는 재사용하고 Cache에 없는 경로만 이미지 header를 읽습니다."""

        with self.cache_lock:
            cached_dimensions = self.cached_dimensions.get(image_path)
            if cached_dimensions is not None:
                self.cached_dimensions.move_to_end(image_path)
                return cached_dimensions
        # 파일 읽기는 Lock 밖에서 수행해 다른 경로의 Cache hit을 막지 않습니다.
        dimensions = read_dimensions(image_path)
        if dimensions is None:
            return None
        with self.cache_lock:
            self.cached_dimensions[image_path] = dimensions
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
