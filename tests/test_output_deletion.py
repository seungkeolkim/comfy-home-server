"""단건 이미지 삭제의 Migration, FS 경계와 catalog 조회 일관성을 검증합니다."""

import sqlite3
from unittest.mock import Mock
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


@pytest.mark.parametrize("request_status", ["submitting", "pending", "running", "cancelling", "completed", "cancelled", "failed", "partial"])
@pytest.mark.parametrize("extension", [".png", ".mp4"])
def test_output_deletion_ignores_job_state_and_only_checks_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request_status: str, extension: str,
) -> None:
    """취소 후 일부 완료를 포함한 모든 작업 상태에서 이미지·영상 삭제는 보호 여부만 검사합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    monkeypatch.setattr(server.video_previews, "request_scan", Mock())
    invalidation = Mock(wraps=server.video_previews.invalidate_missing)
    monkeypatch.setattr(server.video_previews, "invalidate_missing", invalidation)
    source_path = f"generated{extension}"
    server.database.add_job("state-job", "anima" if extension == ".png" else "minimax_h3", "삭제 검증", [
        {"request_id": f"request-{request_index}", "status": "pending", "output_stem": "generated", "detail": {"body": {"prompt": "preserve"}, "settings": {"width": 64, "height": 64}}}
        for request_index in range(2)
    ])
    server.database.complete_request("request-0", [source_path])
    server.database.update_request("request-0", "completed" if request_status == "partial" else request_status)
    server.database.update_request("request-1", "cancelled" if request_status == "partial" else request_status)
    physical_path = server.config.managed_output_directory / source_path
    physical_path.write_bytes(b"generated output")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        original_job = client.get("/api/jobs/state-job").json()
        assert original_job["status"] == request_status
        listing = client.get("/api/outputs", params={"job_id": "state-job"}).json()
        output_identifier = listing["files"][0]["output_id"]
        neighbors_endpoint = f"/api/outputs/{output_identifier}/neighbors"
        candidates_endpoint = "/api/outputs/selection-candidates?job_id=state-job"
        assert client.get(candidates_endpoint).json()["deletable_output_ids"] == [output_identifier]
        assert client.get(neighbors_endpoint).json()["current"]["deletion_protected"] is False
        server.database.set_job_deletion_protection("state-job", True)
        assert client.get(candidates_endpoint).json()["deletable_output_ids"] == []
        assert client.get(neighbors_endpoint).json()["current"]["deletion_protected"] is True
        assert client.delete(f"/api/outputs/{output_identifier}").status_code == 409
        assert physical_path.exists()
        server.database.set_job_deletion_protection("state-job", False)
        assert client.delete(f"/api/outputs/{output_identifier}").status_code == 200
        assert not physical_path.exists()
        assert server.output_catalog.is_deleted(source_path)
        assert client.get("/api/jobs/state-job").json() == original_job
        assert client.get("/api/outputs?job_id=state-job").json()["files"] == []
        assert invalidation.call_count == (1 if extension == ".mp4" else 0)
        server.database.complete_request("request-0", [source_path])
        assert client.get("/api/outputs?job_id=state-job").json()["files"] == []


@pytest.mark.parametrize("extension", [".mp4", ".webm", ".mkv", ".mov"])
def test_video_deletion_invalidates_derived_cache_and_keeps_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str,
) -> None:
    """지원 영상 확장자는 Tombstone으로 삭제하고 파생 Cache 무효화 경로를 호출합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    monkeypatch.setattr(server.video_previews, "request_scan", Mock())
    invalidation = Mock(wraps=server.video_previews.invalidate_missing)
    monkeypatch.setattr(server.video_previews, "invalidate_missing", invalidation)
    request_identifier = add_catalog_test_request(server.database)
    relative_path = f"generated{extension}"
    physical_path = server.config.managed_output_directory / relative_path
    physical_path.write_bytes(b"video result")
    server.database.complete_request(request_identifier, [relative_path])
    original_history = read_history_json(server.database.database_path)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        output_identifier = client.get("/api/outputs").json()["files"][0]["output_id"]
        assert client.delete(f"/api/outputs/{output_identifier}").status_code == 200
        assert invalidation.call_count == 1
        assert not physical_path.exists()
        assert server.output_catalog.is_deleted(relative_path)
        assert client.get(f"/media/{relative_path}").status_code == 404
        assert client.get(f"/api/outputs/{output_identifier}/video-preview").status_code == 404
        assert read_history_json(server.database.database_path) == original_history


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 12
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
        listing = client.get("/api/outputs").json()
        assert listing["total"] == 1
        assert listing["files"][0]["deletion_protected"] is (failure_mode == "protected")
        assert not server.output_catalog.is_deleted("image.png")
        if failure_mode == "protected":
            server.database.set_job_deletion_protection("catalog-job", False)
            assert client.get("/api/outputs").json()["files"][0]["deletion_protected"] is False
            assert client.delete(f"/api/outputs/{output_id}").status_code == 200


@pytest.mark.parametrize("relative_path", ["unsupported.txt", "directory.png", "../outside.png"])
def test_single_deletion_rejects_unsupported_files_and_unsafe_paths(tmp_path: Path, relative_path: str) -> None:
    """인증과 catalog 식별자를 요구하며 미지원 파일·디렉터리·관리 폴더 밖 파일은 보존합니다."""

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


def test_output_deletion_candidates_span_pages_and_respect_filters_and_protection(tmp_path: Path) -> None:
    """전체 선택은 현재 필터의 모든 이미지 중 삭제·누락·보호된 파일을 제외하고 영상도 포함합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    request_id = add_catalog_test_request(server.database)
    protected_request_id = add_catalog_test_request(server.database, "protected-job")
    image_paths = [f"anima/image-{image_number:03d}.png" for image_number in range(65)]
    for relative_path in [*image_paths, "anima/movie.mp4", "protected.png"]:
        physical_path = server.config.managed_output_directory / relative_path
        physical_path.parent.mkdir(parents=True, exist_ok=True)
        physical_path.write_bytes(b"catalog dimensions avoid image header reads")
    Image.new("RGB", (32, 48)).save(server.config.managed_output_directory / "external.png")
    server.database.complete_request(request_id, [*image_paths, "anima/movie.mp4", "anima/missing.png"])
    server.database.complete_request(protected_request_id, ["protected.png"])
    server.database.set_job_deletion_protection("protected-job", True)
    original_history = read_history_json(server.database.database_path)
    candidate_endpoint = "/api/outputs/deletion-candidates"

    with TestClient(application) as client:
        assert client.get(candidate_endpoint).status_code == 401
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/outputs/sync").status_code == 200
        first_page = client.get("/api/outputs").json()
        second_page = client.get("/api/outputs", params={"page": 2}).json()
        listed_files = first_page["files"] + second_page["files"]
        path_to_identifier = {output_file["path"]: output_file["output_id"] for output_file in listed_files}
        expected_output_ids = {path_to_identifier[relative_path] for relative_path in [*image_paths, "anima/movie.mp4"]}
        assert len(first_page["files"]) == 64
        assert len(expected_output_ids) == 66
        assert set(client.get(candidate_endpoint).json()["output_ids"]) == expected_output_ids | {path_to_identifier["external.png"]}
        assert client.get(candidate_endpoint, params={"job_id": "protected-job"}).json() == {"output_ids": []}
        for query_parameters in ({"job_id": "catalog-job"}, {"request_id": request_id}):
            assert set(client.get(candidate_endpoint, params=query_parameters).json()["output_ids"]) == expected_output_ids
        protected_output = client.get("/api/outputs", params={"request_id": protected_request_id}).json()["files"][0]
        assert protected_output["deletion_protected"] is True

        deleted_output_id = path_to_identifier[image_paths[0]]
        assert client.delete(f"/api/outputs/{deleted_output_id}").status_code == 200
        expected_output_ids.remove(deleted_output_id)
        assert set(client.get(candidate_endpoint, params={"job_id": "catalog-job"}).json()["output_ids"]) == expected_output_ids

        # 전체 선택 이후 보호가 설정되어도 기존 단건 API가 삭제 직전에 다시 검사합니다.
        server.database.set_job_deletion_protection("catalog-job", True)
        assert client.get(candidate_endpoint, params={"job_id": "catalog-job"}).json() == {"output_ids": []}
        remaining_identifier = next(iter(expected_output_ids))
        assert client.delete(f"/api/outputs/{remaining_identifier}").status_code == 409
        protected_listing = client.get("/api/outputs", params={"job_id": "catalog-job"}).json()
        assert all(output_file["deletion_protected"] for output_file in protected_listing["files"])
        server.database.set_job_deletion_protection("catalog-job", False)
        assert set(client.get(candidate_endpoint, params={"request_id": request_id}).json()["output_ids"]) == expected_output_ids
        assert client.get(candidate_endpoint, params={"job_id": "missing"}).status_code == 404
        assert client.get(candidate_endpoint, params={"request_id": "missing"}).status_code == 404
        assert client.get(candidate_endpoint, params={"job_id": "catalog-job", "request_id": request_id}).status_code == 422
        assert read_history_json(server.database.database_path) == original_history
