"""결과물 루트 안의 폴더만 탐색하고 생성합니다."""

import os
import re
import stat
from pathlib import Path


def validate_directory_name(directory_name: str) -> None:
    """Windows와 Docker에서 동일하게 사용할 수 있는 단일 폴더 이름을 검사합니다."""

    if (
        not directory_name or directory_name in {".", ".."}
        or directory_name.endswith((".", " "))
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', directory_name)
        or re.fullmatch(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", directory_name, re.IGNORECASE)
    ):
        raise ValueError("올바른 폴더 이름 한 개를 입력해 주세요. 경로·예약 이름·끝의 점이나 공백은 사용할 수 없습니다.")


def resolve_output_directory(output_root: Path, relative_path: str, must_exist: bool = True) -> Path:
    """빈 문자열은 루트로 해석하고 절대 경로·상위 경로·symlink·junction은 거부합니다."""

    directory_path = output_root
    if relative_path:
        directory_names = relative_path.replace("\\", "/").split("/")
        for directory_name in directory_names:
            validate_directory_name(directory_name)
        for directory_name in directory_names:
            directory_path = directory_path / directory_name
            try:
                directory_stat = directory_path.lstat()
            except FileNotFoundError:
                if must_exist:
                    raise FileNotFoundError("폴더를 찾을 수 없습니다.") from None
                continue
            # resolve만으로 내부 alias까지 허용하지 않도록 링크 자체도 검사합니다.
            if stat.S_ISLNK(directory_stat.st_mode) or (
                getattr(directory_stat, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError("symlink 또는 junction 폴더에는 접근할 수 없습니다.")
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise ValueError("폴더가 아닌 경로입니다.")
    resolved_directory = directory_path.resolve()
    if resolved_directory != output_root and output_root not in resolved_directory.parents:
        raise ValueError("결과물 루트 밖의 폴더에는 접근할 수 없습니다.")
    if must_exist and not resolved_directory.is_dir():
        raise FileNotFoundError("폴더를 찾을 수 없습니다.")
    return resolved_directory


def list_output_directories(output_root: Path, relative_path: str) -> dict:
    """현재 폴더의 바로 아래 폴더만 읽으며 이미지나 하위 트리는 읽지 않습니다."""

    directory_path = resolve_output_directory(output_root, relative_path)
    normalized_path = directory_path.relative_to(output_root).as_posix()
    if normalized_path == ".":
        normalized_path = ""
    directories = []
    with os.scandir(directory_path) as directory_entries:
        for directory_entry in directory_entries:
            if not directory_entry.is_dir(follow_symlinks=False):
                continue
            child_relative_path = (directory_path / directory_entry.name).relative_to(output_root).as_posix()
            try:
                resolve_output_directory(output_root, child_relative_path)
            except (ValueError, FileNotFoundError):
                continue
            directories.append({"name": directory_entry.name, "path": child_relative_path})
    directories.sort(key=lambda directory: (directory["name"].casefold(), directory["name"]))
    parent_path = normalized_path.rpartition("/")[0] if normalized_path else None
    return {"path": normalized_path, "parent_path": parent_path, "directories": directories}


def create_output_directory(output_root: Path, parent_path: str, directory_name: str) -> dict:
    """존재하는 부모에 폴더 하나를 원자적으로 만들고 상대 경로를 반환합니다."""

    validate_directory_name(directory_name)
    parent_directory = resolve_output_directory(output_root, parent_path)
    created_directory = parent_directory / directory_name
    created_directory.mkdir()
    return {"name": directory_name, "path": created_directory.relative_to(output_root).as_posix()}
