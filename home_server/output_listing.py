"""파일 종류 정보를 재사용할 수 있는 결과물 디렉터리 항목을 제공합니다."""

import os
from pathlib import Path
from typing import Iterator


def iterate_output_directory_entries(managed_output_directory: Path) -> Iterator[os.DirEntry[str]]:
    """Directory symlink를 따라가지 않고 폴더·파일의 DirEntry를 재귀적으로 반환합니다."""

    pending_directories = [managed_output_directory]
    while pending_directories:
        current_directory = pending_directories.pop()
        try:
            with os.scandir(current_directory) as directory_entries:
                for directory_entry in directory_entries:
                    yield directory_entry
                    try:
                        if directory_entry.is_dir(follow_symlinks=False):
                            pending_directories.append(Path(directory_entry.path))
                    except OSError:
                        # 탐색 도중 삭제·이동되거나 접근할 수 없어진 항목은 건너뜁니다.
                        continue
        except OSError:
            continue
