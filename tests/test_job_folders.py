"""작업 분류의 깊이·소속·삭제·조회 범위와 기존 데이터 보존을 검증합니다."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.database import Database
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


def test_folder_tree_rejects_cycles_duplicates_and_subtree_depth(tmp_path: Path) -> None:
    """이름·부모 변경과 이동에서 중복·순환·하위 포함 3단계 제한을 적용합니다."""

    database = Database(tmp_path / "jobs.sqlite3")
    folders = database.job_folders
    parent_id = folders.save_folder("인물", None)
    child_id = folders.save_folder("표정", parent_id)
    leaf_id = folders.save_folder("최종", child_id)
    sibling_id = folders.save_folder("배경", None)
    for name in ("", "  ", "a/b", "a\\b", "a\nb", "a\x00b", "가" * 81):
        with pytest.raises(ValueError):
            folders.save_folder(name, None)
    with pytest.raises(ValueError, match="같은 이름"):
        folders.save_folder(" 인물 ", None)
    folders.save_folder("인물", sibling_id)
    for parent_identifier in (parent_id, child_id, leaf_id):
        with pytest.raises(ValueError, match="자기 자신"):
            folders.save_folder("인물", parent_identifier, parent_id)
    with pytest.raises(ValueError, match="3단계"):
        folders.save_folder("초과", leaf_id)
    with pytest.raises(ValueError, match="3단계"):
        folders.save_folder("인물", sibling_id, parent_id)
    with pytest.raises(LookupError):
        folders.save_folder("없음", "missing")
    folders.save_folder("최종 변경", sibling_id, leaf_id)
    updated_folder = next(folder for folder in folders.list_folders()["items"] if folder["folder_id"] == leaf_id)
    assert updated_folder["path"] == "배경 / 최종 변경"
    assert updated_folder["depth"] == 2


def test_folder_deletion_unassigns_all_jobs_and_preserves_history_and_files(tmp_path: Path) -> None:
    """진행 중·보호 작업도 소속만 이동하며 분류 삭제는 원본 데이터에 영향을 주지 않습니다."""

    database = Database(tmp_path / "jobs.sqlite3")
    parent_id = database.job_folders.save_folder("부모", None)
    child_id = database.job_folders.save_folder("자식", parent_id)
    other_id = database.job_folders.save_folder("별도", None)
    for job_id in ("first", "second", "outside"):
        add_catalog_test_request(database, job_id)
    database.set_job_deletion_protection("first", True)
    database.job_folders.move_jobs(["first"], parent_id)
    database.job_folders.move_jobs(["second"], child_id)
    database.job_folders.move_jobs(["outside"], other_id)
    database.complete_request("second-request", ["preserved.png"])
    output_path = tmp_path / "preserved.png"
    output_path.write_bytes(b"original output")
    original_json = read_history_json(database.database_path)
    with sqlite3.connect(database.database_path) as connection:
        original_jobs = connection.execute("SELECT * FROM jobs").fetchall()
        original_requests = connection.execute("SELECT * FROM job_requests").fetchall()
        original_outputs = connection.execute("SELECT * FROM output_files").fetchall()
    assert database.job_folders.list_folders()["unassigned_count"] == 0
    parent_folder = next(folder for folder in database.job_folders.list_folders()["items"] if folder["folder_id"] == parent_id)
    assert parent_folder["job_count"] == 2
    assert parent_folder["descendant_folder_count"] == 1
    assert database.get_job("first")["folder_id"] == parent_id
    assert Database(database.database_path).get_job("second")["folder_id"] == child_id
    assert database.job_folders.delete_folder(parent_id) == {"deleted_folder_count": 2, "moved_job_count": 2}
    assert database.job_folders.list_folders()["unassigned_count"] == 2
    assert database.get_job("first")["folder_id"] is None
    assert database.get_job_inputs("outside")["folder_id"] == other_id
    assert read_history_json(database.database_path) == original_json
    assert output_path.read_bytes() == b"original output"
    with sqlite3.connect(database.database_path) as connection:
        assert connection.execute("SELECT * FROM jobs").fetchall() == original_jobs
        assert connection.execute("SELECT * FROM job_requests").fetchall() == original_requests
        assert connection.execute("SELECT * FROM output_files").fetchall() == original_outputs
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("summary", [False, True])
def test_folder_search_and_selection_share_scope(tmp_path: Path, summary: bool) -> None:
    """상위 포함 조회·문자 그대로 검색·페이지 수·전체 선택 범위가 일치합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    database = application.state.home_server.database
    parent_id = database.job_folders.save_folder("실험", None)
    child_id = database.job_folders.save_folder("후보", parent_id)
    for job_index in range(14):
        job_id = f"job-{job_index}"
        add_catalog_test_request(database, job_id)
        database.update_job_description(job_id, "100%_비교" if job_index < 12 else "다른 실험")
        if job_index < 12:
            database.job_folders.move_jobs([job_id], child_id if job_index % 2 else parent_id)
        if job_index:
            database.update_request(f"{job_id}-request", "completed")
    database.set_job_deletion_protection("job-1", True)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        parameters = {"folder_id": parent_id, "search": "%_", "summary": summary}
        listing = client.get("/api/jobs", params=parameters).json()
        assert listing["total"] == 12
        assert listing["total_pages"] == 2
        assert len(listing["items"]) == 10
        assert client.get("/api/jobs", params={**parameters, "page": 2}).json()["total"] == 12
        assert client.get("/api/jobs", params={**parameters, "job_id": "job-13"}).json()["total"] == 0
        assert client.get("/api/jobs", params={"folder_id": "unassigned"}).json()["total"] == 2
        assert client.get("/api/jobs", params={"folder_id": "missing"}).status_code == 404
        candidates = client.get("/api/jobs/selection-candidates", params=parameters).json()
        assert len(candidates["job_ids"]) == 12
        assert len(candidates["deletable_job_ids"]) == 10
        assert "job-0" not in candidates["deletable_job_ids"]
        assert "job-1" not in candidates["deletable_job_ids"]
        assert client.get("/api/jobs/deletion-candidates", params=parameters).json()["job_ids"] == candidates["deletable_job_ids"]


def test_folder_api_requires_auth_and_moves_atomically(tmp_path: Path) -> None:
    """API 검증 실패나 삭제된 작업·분류가 있으면 일부 소속만 변경하지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    database = application.state.home_server.database
    add_catalog_test_request(database, "existing")
    with TestClient(application) as client:
        assert client.get("/api/job-folders").status_code == 401
        assert client.post("/api/job-folders", json={"name": "test"}).status_code == 401
        assert client.post("/api/jobs/folder", json={"job_ids": ["existing"]}).status_code == 401
        client.post("/api/login", json={"password": "test"})
        folder_id = client.post("/api/job-folders", json={"name": "테스트"}).json()["folder_id"]
        assert client.post("/api/jobs/folder", json={"job_ids": ["existing", "missing"], "folder_id": folder_id}).status_code == 404
        assert database.get_job("existing")["folder_id"] is None
        assert client.post("/api/jobs/folder", json={"job_ids": ["existing"], "folder_id": "missing"}).status_code == 422
        assert client.post("/api/jobs/folder", json={"job_ids": []}).status_code == 422
        assert client.post("/api/jobs/folder", json={"job_ids": ["existing", "existing"], "folder_id": folder_id}).json()["moved_job_count"] == 1
        assert client.put(f"/api/job-folders/{folder_id}", json={"name": "이름 변경"}).status_code == 200
        assert client.delete(f"/api/job-folders/{folder_id}").json()["moved_job_count"] == 1
        assert client.delete(f"/api/job-folders/{folder_id}").status_code == 404
        assert client.post("/api/job-folders", json={"name": "  "}).status_code == 422


def test_schema_eleven_upgrade_and_group_only_rollback_preserve_new_history(tmp_path: Path) -> None:
    """Migration 백업과 분류 테이블만 제거하는 Rollback이 작업 이력을 보존합니다."""

    database_path = tmp_path / "jobs.sqlite3"
    database = Database(database_path)
    add_catalog_test_request(database, "before")
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE job_folder_assignments")
        connection.execute("DROP TABLE job_folders")
        connection.execute("PRAGMA user_version=11")
    migrated_database = Database(database_path)
    backup_path = next((tmp_path / "backups").glob("*_before_job_folders_*.sqlite3"))
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    folder_id = migrated_database.job_folders.save_folder("시험", None)
    migrated_database.add_job("after", "anima", "새 이력", [], folder_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE job_folder_assignments")
        connection.execute("DROP TABLE job_folders")
        connection.execute("PRAGMA user_version=11")
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_submission_folder_is_committed_with_job_or_rolled_back(tmp_path: Path) -> None:
    """제출 시 사라진 분류를 지정하면 작업 일부가 남지 않으며 미지정이 기본입니다."""

    database = Database(tmp_path / "jobs.sqlite3")
    folder_id = database.job_folders.save_folder("제출", None)
    database.add_job("assigned", "anima", "새 설명", [], folder_id)
    database.add_job("unassigned", "anima", "기본", [])
    assert database.get_job_inputs("assigned")["folder_id"] == folder_id
    assert database.get_job_inputs("unassigned")["folder_id"] is None
    database.job_folders.delete_folder(folder_id)
    with pytest.raises(ValueError, match="분류를 찾을 수 없습니다"):
        database.add_job("rejected", "anima", "실패", [], folder_id)
    assert database.get_job("rejected") is None
    assert database.list_jobs()["total"] == 2


def test_summary_thumbnails_follow_catalog_paths_and_ignore_deleted_or_missing_outputs(tmp_path: Path) -> None:
    """작업 대표 미리보기는 최대 3개이며 현재 Catalog 경로와 가용·삭제 상태를 따릅니다."""

    database = Database(tmp_path / "jobs.sqlite3")
    request_id = add_catalog_test_request(database)
    database.complete_request(request_id, [f"image-{image_index}.png" for image_index in range(6)])
    with sqlite3.connect(database.database_path) as connection:
        connection.execute("UPDATE output_files SET is_deleted=1 WHERE relative_path='image-5.png'")
        connection.execute("UPDATE output_files SET is_available=0 WHERE relative_path='image-4.png'")
        connection.execute("UPDATE output_files SET relative_path='moved/image-3.png' WHERE relative_path='image-3.png'")
    thumbnails = database.list_job_summaries()["items"][0]["preview_files"]
    assert [thumbnail["path"] for thumbnail in thumbnails] == ["moved/image-3.png", "image-2.png", "image-1.png"]
