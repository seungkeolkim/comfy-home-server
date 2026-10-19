"""DirEntry 탐색의 중첩 폴더와 Symlink 경계 동작을 검증합니다."""

import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.output_listing import iterate_output_directory_entries, output_filename_metadata
from test_application import FakeComfyClient, create_processing_test_app


@pytest.mark.parametrize("filename", [
    "261006_153012_123456.png",
    "261006_153012_123456_1.png",
    "261006_153012_123456_00001_audio.webm",
])
def test_output_filename_metadata_reads_saver_timestamp_and_seed(filename: str) -> None:
    """이미지 중복 suffix와 영상 counter가 있어도 실제 timestamp와 seed를 읽습니다."""

    generated_at, generation_seed = output_filename_metadata(Path(filename))
    assert generated_at == datetime(2026, 10, 6, 15, 30, 12).timestamp()
    assert generation_seed == 123456


@pytest.mark.parametrize("filename", ["image.png", "261332_153012_1.png", "261006_256099_1.png"])
def test_output_filename_metadata_keeps_unknown_names_without_stat(filename: str) -> None:
    """규칙 밖 파일과 잘못된 날짜는 삭제하거나 stat하지 않고 미상으로 표시합니다."""

    assert output_filename_metadata(Path(filename)) == (None, None)


def test_output_listing_sorts_by_filename_without_path_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """수정 시각과 무관하게 파일명으로 정렬하고 크기 metadata 및 stat 호출을 제거합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    def skip_independent_video_workers():
        """목록의 전역 stat 금지 검증에서 독립 영상 백그라운드 IO를 분리합니다."""

    monkeypatch.setattr(application.state.home_server.video_previews, "start", skip_independent_video_workers)
    managed_directory = application.state.home_server.config.managed_output_directory
    output_names = [
        "261015_010001_3.png", "261015_010001_20.png", "261015_010002_1.png", "unknown.png",
    ]
    for output_index, output_name in enumerate(output_names):
        output_path = managed_directory / output_name
        output_path.write_bytes(b"listed image")
        os.utime(output_path, (output_index + 1, output_index + 1))

    def reject_path_stat(*arguments, **keyword_arguments):
        """목록 요청에서 Path.stat을 사용하면 즉시 실패합니다."""

        raise AssertionError("output listing must not call Path.stat")

    def known_image_dimensions(image_path: Path) -> tuple[int, int]:
        """이 테스트에서는 이미지 읽기를 정렬 검증과 분리합니다."""

        return 32, 48

    monkeypatch.setattr("home_server.application.cached_image_dimensions", known_image_dimensions)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/outputs/sync").status_code == 200
        with monkeypatch.context() as request_patch:
            request_patch.setattr(Path, "stat", reject_path_stat)
            response = client.get("/api/outputs")
        assert response.status_code == 200
        output_files = response.json()["files"]
        assert [output_file["name"] for output_file in output_files] == [
            "261015_010002_1.png", "261015_010001_20.png", "261015_010001_3.png", "unknown.png",
        ]
        assert all("size" not in output_file and "modified_at" not in output_file for output_file in output_files)
        assert output_files[-1]["generated_at"] is None
        assert output_files[-1]["width"] == 32


def test_dimension_cache_limit_and_explicit_invalidation(tmp_path: Path) -> None:
    """해상도 Cache가 최대 항목 수와 이동에 필요한 경로별 무효화를 지킵니다."""

    from home_server.image_dimension_cache import ImageDimensionCache

    dimension_cache = ImageDimensionCache(maximum_entries=2)
    dimension_reads = []

    def read_test_dimensions(image_path: Path) -> tuple[int, int]:
        """실제 파일 대신 어떤 경로를 다시 읽었는지 기록합니다."""

        dimension_reads.append(image_path)
        return 32, 48

    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    third_path = tmp_path / "third.png"
    dimension_cache.get_dimensions(first_path, read_test_dimensions)
    dimension_cache.get_dimensions(second_path, read_test_dimensions)
    dimension_cache.get_dimensions(first_path, read_test_dimensions)
    dimension_cache.get_dimensions(third_path, read_test_dimensions)
    assert list(dimension_cache.cached_dimensions) == [first_path, third_path]
    dimension_cache.invalidate(first_path)
    dimension_cache.get_dimensions(first_path, read_test_dimensions)
    assert dimension_reads == [first_path, second_path, third_path, first_path]


def test_output_entries_include_nested_files_and_directories(tmp_path: Path) -> None:
    """확장자가 있는 폴더도 파일과 구분하고 중첩 파일을 빠짐없이 탐색합니다."""

    nested_directory = tmp_path / "folder.png" / "nested"
    nested_directory.mkdir(parents=True)
    (nested_directory / "image.png").write_bytes(b"image")
    (tmp_path / "notes.txt").write_text("notes", encoding="utf-8")

    entries_by_path = {}
    for directory_entry in iterate_output_directory_entries(tmp_path):
        relative_path = Path(directory_entry.path).relative_to(tmp_path).as_posix()
        entries_by_path[relative_path] = directory_entry

    assert set(entries_by_path) == {"folder.png", "folder.png/nested", "folder.png/nested/image.png", "notes.txt"}
    assert not entries_by_path["folder.png"].is_file()
    assert entries_by_path["folder.png/nested/image.png"].is_file()


def test_output_listing_excludes_file_and_directory_symlinks(tmp_path: Path) -> None:
    """내부·외부·깨진 파일 Symlink와 Directory symlink 아래 결과물을 제외합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    managed_directory = application.state.home_server.config.managed_output_directory
    nested_directory = managed_directory / "nested"
    nested_directory.mkdir(parents=True)
    image_path = nested_directory / "image.png"
    image_path.write_bytes(b"listed image")
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(b"outside image")
    try:
        (managed_directory / "internal.png").symlink_to(image_path)
        (managed_directory / "outside.png").symlink_to(outside_image)
        (managed_directory / "broken.png").symlink_to(tmp_path / "missing.png")
        (managed_directory / "directory-link").symlink_to(nested_directory, target_is_directory=True)
    except OSError:
        pytest.skip("현재 환경에서 Symlink 생성 권한을 제공하지 않습니다.")

    with TestClient(application) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        assert client.post("/api/outputs/sync").status_code == 200
        response = client.get("/api/outputs")
        assert response.status_code == 200
        assert {output_file["path"] for output_file in response.json()["files"]} == {
            "nested/image.png",
        }
