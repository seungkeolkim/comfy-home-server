"""단건 이미지 삭제의 Migration, FS 경계와 catalog 조회 일관성을 검증합니다."""

import sqlite3
from collections.abc import Iterator
from os import DirEntry
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.database import Database
from home_server.output_catalog import OutputCatalog
from home_server.output_listing import iterate_output_directory_entries
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


def test_schema_ten_migration_preserves_catalog_and_json(tmp_path: Path) -> None:
    """Version 10을 백업한 뒤 누락 파일과 기존 metadata를 그대로 유지합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    request_id = add_catalog_test_request(database)
    database.complete_request(request_id, ["anima/present.png", "anima/missing.png"])
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE output_files SET is_available=0 WHERE relative_path='anima/missing.png'")
        connection.execute("DROP INDEX output_files_deleted_original")
        connection.execute("ALTER TABLE output_files DROP COLUMN is_deleted")
        connection.execute("PRAGMA user_version=10")
        original_catalog = connection.execute("SELECT * FROM output_files ORDER BY output_id").fetchall()
    original_history = read_history_json(database_path)

    Database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        migrated_catalog = connection.execute("SELECT * FROM output_files ORDER BY output_id").fetchall()
        assert [catalog_row[:-1] for catalog_row in migrated_catalog] == original_catalog
        assert [catalog_row[-1] for catalog_row in migrated_catalog] == [0, 0]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert read_history_json(database_path) == original_history
    backup_paths = list((tmp_path / "backups").glob("*before_output_deletion*.sqlite3"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
        assert connection.execute("SELECT * FROM output_files ORDER BY output_id").fetchall() == original_catalog
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


@pytest.mark.parametrize("move_image", [False, True])
def test_single_image_deletion_preserves_history_and_stays_deleted(tmp_path: Path, move_image: bool) -> None:
    """현재 파일만 삭제하고 반복 요청·재시작·동기화·완료 재반영에서도 삭제를 유지합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    relative_path = "anima/261018_090102_1.png"
    remaining_path = "anima/261018_090103_2.png"
    for image_relative_path in (relative_path, remaining_path):
        image_path = server.config.managed_output_directory / image_relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 48)).save(image_path)
    server.database.complete_request(request_id, [relative_path, remaining_path])
    original_history = read_history_json(server.database.database_path)

    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        original_output = next(
            output_file for output_file in client.get("/api/outputs").json()["files"]
            if output_file["path"] == relative_path
        )
        if move_image:
            movement = client.post("/api/outputs/move", json={"source": relative_path, "destination_folder": "sorted"})
            assert movement.status_code == 200
            relative_path = movement.json()["path"]
        image_path = server.config.managed_output_directory / relative_path
        preview_url = f"/api/outputs/preview/{relative_path}"
        assert client.get(preview_url).status_code == 200
        assert any(cache_key[0] == image_path for cache_key in server.thumbnail_cache._cached_thumbnails)
        deletion_endpoint = f"/api/outputs/{original_output['output_id']}"
        deletion = client.delete(deletion_endpoint)
        assert deletion.status_code == 200
        assert deletion.json() == {"deleted": True, "path": relative_path, "deleted_files": 1}
        assert not image_path.exists()
        assert not any(cache_key[0] == image_path for cache_key in server.thumbnail_cache._cached_thumbnails)
        assert read_history_json(server.database.database_path) == original_history
        for query_parameters in ({}, {"job_id": "catalog-job"}, {"request_id": request_id}):
            listing = client.get("/api/outputs", params=query_parameters).json()
            assert listing["total"] == 1
            assert listing["files"][0]["path"] == remaining_path
        assert client.get(f"/media/{relative_path}").status_code == 404
        assert client.get(preview_url).status_code == 404
        assert client.get("/api/jobs/catalog-job").status_code == 200
        assert client.delete(deletion_endpoint).json()["deleted_files"] == 0

        # 같은 경로가 다시 생겨도 명시적으로 삭제한 결과물을 재등록하거나 다시 지우지 않습니다.
        Image.new("RGB", (48, 32)).save(image_path)
        assert client.delete(deletion_endpoint).json()["deleted_files"] == 0
        assert image_path.exists()
        assert client.post("/api/outputs/sync").json()["available"] == 1
        server.database.complete_request(request_id, [original_output["path"], remaining_path])
        assert client.get("/api/outputs").json()["total"] == 1
        Database(server.database.database_path)
        assert server.output_catalog.synchronize(server.config.managed_output_directory)["available"] == 1
        assert client.get(f"/media/{relative_path}").status_code == 404
        assert client.get(preview_url).status_code == 404
        assert client.post("/api/outputs/move", json={
            "source": relative_path, "destination_folder": "must-not-move",
        }).status_code == 409
        assert image_path.exists()
        assert client.get("/api/outputs").json()["total"] == 1
    with sqlite3.connect(server.database.database_path) as connection:
        assert connection.execute(
            "SELECT is_deleted,is_available,original_relative_path,request_id FROM output_files WHERE output_id=?",
            (original_output["output_id"],),
        ).fetchone() == (1, 0, original_output["path"], request_id)


def test_missing_image_can_be_marked_deleted(tmp_path: Path) -> None:
    """외부에서 이미 사라진 이미지도 삭제 상태로 구분하고 동기화로 복원하지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    server.database.complete_request(request_id, ["anima/missing.png"])
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        with sqlite3.connect(server.database.database_path) as connection:
            output_id = connection.execute("SELECT output_id FROM output_files").fetchone()[0]
        deletion = client.delete(f"/api/outputs/{output_id}")
        assert deletion.status_code == 200
        assert deletion.json()["deleted_files"] == 0
        assert server.output_catalog.is_deleted("anima/missing.png")


@pytest.mark.parametrize("failure_mode", ["protected", "filesystem", "database"])
def test_failed_image_deletion_preserves_file_and_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str,
) -> None:
    """삭제 보호·FS 실패·DB 변경 실패가 파일이나 삭제 플래그를 손상하지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    image_path = server.config.managed_output_directory / "image.png"
    Image.new("RGB", (32, 48)).save(image_path)
    server.database.complete_request(request_id, ["image.png"])
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        output_id = client.get("/api/outputs").json()["files"][0]["output_id"]
        if failure_mode == "protected":
            server.database.set_job_deletion_protection("catalog-job", True)
        elif failure_mode == "filesystem":
            original_unlink = Path.unlink

            def reject_image_removal(selected_path: Path, *arguments, **keyword_arguments) -> None:
                """대상 이미지만 파일 잠금 상황으로 처리합니다."""

                if selected_path == image_path:
                    raise PermissionError("image is open")
                original_unlink(selected_path, *arguments, **keyword_arguments)

            monkeypatch.setattr(Path, "unlink", reject_image_removal)
        else:
            with sqlite3.connect(server.database.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_deletion BEFORE UPDATE OF is_deleted ON output_files "
                    "BEGIN SELECT RAISE(ABORT, 'database failure'); END"
                )
        assert client.delete(f"/api/outputs/{output_id}").status_code == 409
        assert image_path.is_file()
        assert client.get("/api/outputs").json()["total"] == 1
        assert not server.output_catalog.is_deleted("image.png")
        if failure_mode == "protected":
            server.database.set_job_deletion_protection("catalog-job", False)
            assert client.delete(f"/api/outputs/{output_id}").status_code == 200


@pytest.mark.parametrize("relative_path", ["video.mp4", "directory.png", "../outside.png"])
def test_single_deletion_rejects_non_images_and_unsafe_paths(tmp_path: Path, relative_path: str) -> None:
    """인증과 catalog 식별자를 요구하며 영상·디렉터리·관리 폴더 밖 파일은 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    selected_path = server.config.managed_output_directory / relative_path
    if relative_path == "directory.png":
        selected_path.mkdir()
    else:
        selected_path.write_bytes(b"preserve this file")
    # 손상된 이전 catalog 경로에도 실제 파일 경계 검증을 적용합니다.
    with sqlite3.connect(server.database.database_path) as connection:
        output_id = connection.execute(
            "INSERT INTO output_files (original_relative_path,relative_path) VALUES (?,?)",
            (relative_path, relative_path),
        ).lastrowid
    with TestClient(application) as client:
        assert client.delete(f"/api/outputs/{output_id}").status_code == 401
        client.post("/api/login", json={"password": "test"})
        assert client.delete("/api/outputs/999999").status_code == 404
        assert client.delete(f"/api/outputs/{output_id}").status_code in {409, 422}
        assert selected_path.exists()
        assert not server.output_catalog.is_deleted(relative_path)


def test_deletion_holds_database_lock_while_removing_image(tmp_path: Path) -> None:
    """이미지 삭제 중 다른 연결이 삭제 보호나 catalog 경로를 변경할 수 없습니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    request_id = add_catalog_test_request(database)
    database.complete_request(request_id, ["image.png"])
    catalog = OutputCatalog(database.database_path)
    output_id = catalog.list_files(1, 24)["files"][0]["output_id"]

    def remove_image_under_lock(relative_path: str) -> bool:
        """독립된 연결에서 두 가지 변경이 모두 잠금으로 차단되는지 확인합니다."""

        assert relative_path == "image.png"
        with sqlite3.connect(database.database_path, timeout=0) as connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("UPDATE jobs SET deletion_protected=1")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                connection.execute("UPDATE output_files SET relative_path='moved.png'")
        return True

    assert catalog.delete_file(output_id, remove_image_under_lock)["deleted_files"] == 1


def test_synchronization_does_not_restore_image_deleted_during_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동기화가 삭제 직전의 FS 목록을 가지고 있어도 삭제 표시와 비가용 상태를 유지합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    request_id = add_catalog_test_request(database)
    database.complete_request(request_id, ["image.png"])
    managed_directory = tmp_path / "managed"
    managed_directory.mkdir()
    image_path = managed_directory / "image.png"
    image_path.write_bytes(b"image contents")
    catalog = OutputCatalog(database.database_path)
    output_id = catalog.list_files(1, 24)["files"][0]["output_id"]

    def remove_scanned_image(relative_path: str) -> bool:
        """FS 목록에 먼저 담긴 이미지를 동기화의 DB 갱신 전에 삭제합니다."""

        assert relative_path == "image.png"
        image_path.unlink()
        return True

    def scan_then_delete(directory_path: Path) -> Iterator[DirEntry[str]]:
        """실제 DirEntry를 읽은 뒤 삭제 요청과의 실행 순서를 재현합니다."""

        yield from iterate_output_directory_entries(directory_path)
        catalog.delete_file(output_id, remove_scanned_image)

    monkeypatch.setattr("home_server.output_catalog.iterate_output_directory_entries", scan_then_delete)
    assert catalog.synchronize(managed_directory)["available"] == 0
    assert catalog.list_files(1, 24)["total"] == 0
    with sqlite3.connect(database.database_path) as connection:
        assert connection.execute("SELECT is_deleted,is_available FROM output_files").fetchone() == (1, 0)
