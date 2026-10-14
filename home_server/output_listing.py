"""파일 종류 정보를 재사용할 수 있는 결과물 디렉터리 항목을 제공합니다."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator


OUTPUT_FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{6})_(?P<time>\d{6})_(?P<seed>\d+)(?:_[A-Za-z0-9-]+)*"
)


def output_filename_metadata(output_path: Path) -> tuple[float | None, int | None]:
    """Saver 파일명의 yyMMdd_HHmmss와 seed를 읽고 잘못된 형식은 미상으로 반환합니다."""

    filename_match = OUTPUT_FILENAME_PATTERN.fullmatch(output_path.stem)
    if filename_match is None:
        return None, None
    date_text = filename_match.group("date")
    time_text = filename_match.group("time")
    try:
        generated_datetime = datetime(
            year=2000 + int(date_text[:2]), month=int(date_text[2:4]), day=int(date_text[4:6]),
            hour=int(time_text[:2]), minute=int(time_text[2:4]), second=int(time_text[4:6]),
        )
        generated_at = generated_datetime.timestamp()
    except (ValueError, OverflowError, OSError):
        return None, None
    return generated_at, int(filename_match.group("seed"))


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
