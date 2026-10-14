"""DirEntry 탐색의 중첩 폴더와 Symlink 경계 동작을 검증합니다."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.output_listing import iterate_output_directory_entries
from test_application import FakeComfyClient, create_processing_test_app


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
        response = client.get("/api/outputs")
        assert response.status_code == 200
        assert {output_file["path"] for output_file in response.json()["files"]} == {
            "nested/image.png",
        }
