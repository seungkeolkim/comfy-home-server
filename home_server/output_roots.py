"""일반 출력의 기존 경로를 유지하며 스타일 출력 루트를 별도로 해석합니다."""

from pathlib import Path

from .output_directories import resolve_output_directory, validate_directory_name


STYLE_OUTPUT_ROOT_NAME = "from_comfy_home_style"
STYLE_OUTPUT_PREFIX = STYLE_OUTPUT_ROOT_NAME + "/"


def resolve_managed_file(general_root: Path, style_root: Path, relative_path: str, must_exist: bool = False) -> Path:
    """등록된 두 루트 안의 파일만 허용하고 경로·링크 우회를 거부합니다."""

    normalized_path = relative_path.replace("\\", "/")
    selected_root = general_root
    if normalized_path.startswith(STYLE_OUTPUT_PREFIX):
        selected_root = style_root
        normalized_path = normalized_path[len(STYLE_OUTPUT_PREFIX):]
    if selected_root.is_symlink() or selected_root.is_junction():
        raise ValueError("출력 루트는 링크 폴더로 지정할 수 없습니다.")
    components = normalized_path.split("/")
    for component in components:
        validate_directory_name(component)
    parent_path = "/".join(components[:-1])
    parent_directory = resolve_output_directory(selected_root, parent_path, must_exist=False)
    file_path = parent_directory / components[-1]
    if file_path.is_symlink() or file_path.is_junction():
        raise ValueError("링크 파일은 관리 출력으로 사용할 수 없습니다.")
    resolved_path = file_path.resolve()
    if selected_root.resolve() not in resolved_path.parents:
        raise ValueError("등록한 출력 루트 밖의 파일입니다.")
    if must_exist and not resolved_path.is_file():
        raise FileNotFoundError(relative_path)
    return resolved_path


def is_style_output(relative_path: str) -> bool:
    """파일을 옮기거나 Job이 삭제돼도 스타일 출력의 소속을 구분합니다."""

    return relative_path.replace("\\", "/").startswith(STYLE_OUTPUT_PREFIX)
