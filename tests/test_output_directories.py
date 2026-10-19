"""결과물 폴더 탐색·생성과 루트 이동의 경계 및 이력 보존을 검증합니다."""

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


def test_directory_navigation_creation_and_all_movement_modes_preserve_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 폴더를 조회·생성하고 세 이동 방식과 루트 복귀 시 catalog 원본 이력을 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    output_root = server.config.managed_output_directory
    request_id = add_catalog_test_request(server.database)
    (output_root / "image.png").write_bytes(b"image")
    (output_root / "empty").mkdir()
    server.database.complete_request(request_id, ["image.png"])
    original_history = read_history_json(server.database.database_path)
    output_id = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
    with TestClient(application) as client:
        assert client.get("/api/outputs/directories").status_code == 401
        assert client.post("/api/outputs/directories", json={"parent_path": "", "name": "forbidden"}).status_code == 401
        assert not (output_root / "forbidden").exists()
        client.post("/api/login", json={"password": "test"})

        def reject_catalog_scan(*arguments, **keyword_arguments) -> None:
            """폴더 조작이 전체 동기화를 호출하면 실패시킵니다."""

            raise AssertionError("folder operations must not synchronize the catalog")

        monkeypatch.setattr(server.output_catalog, "synchronize", reject_catalog_scan)
        listing = client.get("/api/outputs/directories").json()
        assert listing == {"path": "", "parent_path": None, "directories": [{"name": "empty", "path": "empty"}]}
        assert client.get("/api/outputs/directories", params={"path": "empty"}).json() == {
            "path": "empty", "parent_path": "", "directories": [],
        }
        created = client.post("/api/outputs/directories", json={"parent_path": "empty", "name": "새 폴더"})
        assert created.status_code == 201
        assert created.json() == {"name": "새 폴더", "path": "empty/새 폴더"}
        assert client.post("/api/outputs/directories", json={"parent_path": "", "name": "archive"}).status_code == 201
        assert client.get("/api/outputs/directories", params={"path": "empty/새 폴더"}).json()["parent_path"] == "empty"
        assert server.output_catalog.list_files(1, 64)["total"] == 1
        assert read_history_json(server.database.database_path) == original_history
        for movement_endpoint, destination, movement_fields in [
            ("/api/outputs/move", "empty/새 폴더", {"source": "image.png"}),
            ("/api/outputs/move", "", {"source": "empty/새 폴더/image.png"}),
            ("/api/outputs/move-batch", "archive", {"output_ids": [output_id]}),
            ("/api/outputs/move-batch", "", {"output_ids": [output_id]}),
            ("/api/jobs/catalog-job/outputs/move", "empty/새 폴더", {}),
            ("/api/jobs/catalog-job/outputs/move", "", {}),
        ]:
            response = client.post(movement_endpoint, json={**movement_fields, "destination_folder": destination})
            assert response.status_code == 200, response.text
            assert (output_root / destination / "image.png").read_bytes() == b"image"
        same_folder = client.post("/api/outputs/move-batch", json={"output_ids": [output_id], "destination_folder": ""}).json()
        assert same_folder["skipped_count"] == 1
        assert read_history_json(server.database.database_path) == original_history
    with sqlite3.connect(server.database.database_path) as connection:
        assert connection.execute("SELECT original_relative_path,relative_path FROM output_files").fetchall() == [("image.png", "image.png")]


@pytest.mark.parametrize("directory_name", [
    "", ".", "..", "../escape", "a/b", "a\\b", "/absolute", "C:\\absolute", "a:b", "bad<name", "bad>name",
    'bad"name', "bad|name", "bad?name", "bad*name", "control\x00", "control\n", "control\x7f", " ", "trailing.", "trailing ",
    "CON", "con.txt", "PRN", "AUX", "NUL", "COM1", "lpt9.txt", "COM¹",
])
def test_directory_creation_rejects_invalid_names(tmp_path: Path, directory_name: str) -> None:
    """플랫폼에 상관없이 경로·제어 문자·Windows 예약 이름을 일관되게 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        response = client.post("/api/outputs/directories", json={"parent_path": "", "name": directory_name})
        assert response.status_code == 422


@pytest.mark.parametrize("relative_path", ["..", "../outside", "/", "/absolute", "C:/absolute", "C:relative", "//server/share", "a/../b", "./a", "a//b"])
def test_directory_endpoints_and_move_destinations_reject_invalid_paths(tmp_path: Path, relative_path: str) -> None:
    """UI를 우회한 요청도 모든 폴더 목적지에서 절대·상위 경로를 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.get("/api/outputs/directories", params={"path": relative_path}).status_code == 422
        assert client.post("/api/outputs/directories", json={"parent_path": relative_path, "name": "new"}).status_code == 422
        assert client.post("/api/outputs/move-batch", json={"output_ids": [1], "destination_folder": relative_path}).status_code == 422


def test_directory_errors_collisions_and_creation_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """누락·파일 충돌·권한 오류와 중복 생성 경합에서 덮어쓰기 없이 오류를 반환합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    output_root = application.state.home_server.config.managed_output_directory
    (output_root / "existing").mkdir()
    (output_root / "file.png").write_bytes(b"unchanged")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.get("/api/outputs/directories", params={"path": "missing"}).status_code == 404
        assert client.get("/api/outputs/directories", params={"path": "file.png"}).status_code == 422
        assert client.post("/api/outputs/directories", json={"parent_path": "missing", "name": "new"}).status_code == 404
        assert client.post("/api/outputs/directories", json={"parent_path": "file.png", "name": "new"}).status_code == 422
        for existing_name in ["existing", "file.png"]:
            assert client.post("/api/outputs/directories", json={"parent_path": "", "name": existing_name}).status_code == 409
        original_mkdir = Path.mkdir

        def create_competing_directory(directory_path: Path, *arguments, **keyword_arguments) -> None:
            """생성 직전에 다른 요청이 같은 이름의 폴더를 만든 상황을 재현합니다."""

            if directory_path == output_root / "race":
                original_mkdir(directory_path)
            if directory_path == output_root / "denied":
                raise PermissionError("private server path")
            original_mkdir(directory_path, *arguments, **keyword_arguments)

        monkeypatch.setattr(Path, "mkdir", create_competing_directory)
        assert client.post("/api/outputs/directories", json={"parent_path": "", "name": "race"}).status_code == 409
        denied = client.post("/api/outputs/directories", json={"parent_path": "", "name": "denied"})
        assert denied.status_code == 403
        assert "private server path" not in denied.text

        def reject_directory_listing(directory_path: Path):
            """폴더 조회 권한이 없는 상황을 재현합니다."""

            raise PermissionError("private server path")

        monkeypatch.setattr("home_server.output_directories.os.scandir", reject_directory_listing)
        assert client.get("/api/outputs/directories").status_code == 403
        assert (output_root / "file.png").read_bytes() == b"unchanged"


def test_directory_links_are_hidden_and_rejected_for_browsing_creation_and_moves(tmp_path: Path) -> None:
    """루트 외부와 내부로 향하는 symlink 또는 Windows junction을 모두 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    output_root = server.config.managed_output_directory
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    (output_root / "real").mkdir()
    (output_root / "image.png").write_bytes(b"image")
    for directory_name, target_directory in [("outside-link", outside_directory), ("inside-link", output_root / "real")]:
        link_path = output_root / directory_name
        try:
            link_path.symlink_to(target_directory, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link_path), str(target_directory)], check=True, capture_output=True)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.get("/api/outputs/directories").json()["directories"] == [{"name": "real", "path": "real"}]
        for directory_name in ["outside-link", "inside-link"]:
            assert client.get("/api/outputs/directories", params={"path": directory_name}).status_code == 422
            assert client.post("/api/outputs/directories", json={"parent_path": directory_name, "name": "new"}).status_code == 422
            assert client.post("/api/outputs/move", json={"source": "image.png", "destination_folder": directory_name}).status_code == 422
            assert client.post("/api/outputs/move-batch", json={"output_ids": [1], "destination_folder": f"{directory_name}/new"}).status_code == 422
        assert not (outside_directory / "new").exists()
