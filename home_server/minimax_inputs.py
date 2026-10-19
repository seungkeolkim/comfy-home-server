"""MiniMax의 서버 이미지 선택, 실제 해상도 확인과 요청별 입력 Snapshot을 처리합니다."""

import stat
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from .output_catalog import OutputCatalog
from .output_directories import resolve_output_directory, validate_directory_name


MAX_INPUT_BYTES = 50 * 1024 * 1024


def resolve_input_image(output_root: Path, relative_path: str) -> Path:
    """폴더 경계와 파일 자체의 링크 여부를 확인하여 루트 안의 일반 파일만 허용합니다."""

    normalized_path = relative_path.replace("\\", "/")
    parent_path, _, image_name = normalized_path.rpartition("/")
    validate_directory_name(image_name)
    parent_directory = resolve_output_directory(output_root, parent_path)
    image_path = parent_directory / image_name
    image_stat = image_path.lstat()
    if not stat.S_ISREG(image_stat.st_mode) or getattr(image_stat, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("일반 이미지 파일만 입력으로 사용할 수 있습니다.")
    return image_path


def read_input_dimensions(image_path: Path) -> tuple[int, int]:
    """요청 해상도 Cache를 사용하지 않고 EXIF 표시 방향을 반영한 실제 크기를 읽습니다."""

    with Image.open(image_path) as source_image:
        width, height = source_image.size
        if source_image.getexif().get(274) in {5, 6, 7, 8}:
            width, height = height, width
    return width, height


def inspect_input_images(output_root: Path, catalog: OutputCatalog, output_ids: list[int]) -> list[dict[str, Any]]:
    """선택한 최대 100장의 실제 크기를 확인하며 불완전한 입력은 조용히 제외하지 않습니다."""

    inspected_images = catalog.get_input_images(output_ids)
    for image_record in inspected_images:
        try:
            image_path = resolve_input_image(output_root, image_record["path"])
            width, height = read_input_dimensions(image_path)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exception:
            raise ValueError(f"입력 이미지를 확인할 수 없습니다: {image_record['name']}. 다시 선택해 주세요.") from exception
        image_record.update({"width": width, "height": height})
    return inspected_images


def snapshot_input_images(
    output_root: Path, catalog: OutputCatalog, upload_directory: Path, output_ids: list[int],
    input_scope: str | None, input_directory: str | None,
) -> list[dict[str, Any]]:
    """제출 대상의 최신 경로를 확인하고 원본과 독립된 임시 파일을 만들며 실패하면 전부 회수합니다."""

    if input_scope not in {"single", "folder"} or (input_scope == "single" and len(output_ids) != 1):
        raise ValueError("단건은 이미지 한 장, 폴더 작업은 이미지 1~100장을 선택해 주세요.")
    image_records = catalog.get_input_images(output_ids)
    if input_scope == "folder":
        if input_directory is None:
            raise ValueError("입력 폴더를 선택해 주세요.")
        source_directory = resolve_output_directory(output_root, input_directory)
        for image_record in image_records:
            if resolve_input_image(output_root, image_record["path"]).parent != source_directory:
                raise ValueError("선택한 폴더의 직하위 이미지만 함께 제출할 수 있습니다. 다시 선택해 주세요.")
    created_snapshots = []
    try:
        for image_record in image_records:
            image_path = resolve_input_image(output_root, image_record["path"])
            upload_id = uuid.uuid4().hex
            snapshot_path = upload_directory / f"{upload_id}{image_path.suffix.lower()}"
            with snapshot_path.open("xb") as snapshot_file:
                created_snapshots.append({**image_record, "upload_id": upload_id, "snapshot_path": snapshot_path})
                with image_path.open("rb") as source_file:
                    copied_bytes = 0
                    while source_chunk := source_file.read(1024 * 1024):
                        copied_bytes += len(source_chunk)
                        if copied_bytes > MAX_INPUT_BYTES:
                            raise ValueError("입력 이미지 한 장은 50 MB 이하여야 합니다.")
                        snapshot_file.write(source_chunk)
            width, height = read_input_dimensions(snapshot_path)
            created_snapshots[-1].update({"width": width, "height": height})
    except Exception:
        remove_input_snapshots(created_snapshots)
        raise
    return created_snapshots


def remove_input_snapshots(image_records: list[dict[str, Any]]) -> None:
    """현재 접수 과정이 만든 임시 파일만 제거합니다."""

    for image_record in image_records:
        image_record["snapshot_path"].unlink(missing_ok=True)


def prepare_input_canvas(snapshot_path: Path, width: int, height: int) -> Path:
    """원본 비율과 EXIF 방향을 유지한 RGB 이미지를 공통 Canvas에 검은 Pad로 맞춥니다."""

    prepared_path = snapshot_path.with_suffix(".prepared.png")
    with Image.open(snapshot_path) as source_image:
        oriented_image = ImageOps.exif_transpose(source_image)
        rgba_image = oriented_image.convert("RGBA")
        background_image = Image.new("RGBA", rgba_image.size, (0, 0, 0, 255))
        background_image.alpha_composite(rgba_image)
        canvas_image = ImageOps.pad(background_image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS, color="black")
        canvas_image.save(prepared_path, format="PNG")
    return prepared_path
