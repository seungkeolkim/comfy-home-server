"""현재 SQLite schema와 작업 계층 저장을 검증합니다."""

import sqlite3
from pathlib import Path

import pytest

from home_server.database import Database


def test_new_database_stores_jobs_presets_and_tags(tmp_path: Path) -> None:
    """새 schema에서 설정과 작업을 저장하고 작업 중복 시 transaction을 되돌립니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    assert database.list_tag_groups() == []
    assert database.list_tag_entries() == []
    database.save_preset("portrait", "Portrait", "anima", {"prompt": "portrait, [SCENE]"})
    database.save_lora_profile("portrait.safetensors", "anima", {"strength": 0.7})
    requests = [{
        "request_id": "new-request", "status": "submitting", "output_stem": "anima/%time_%seed",
        "detail": {"body": {"prompt": "portrait, [SCENE]"}},
    }]
    database.add_job("new-job", "anima", "Portrait test", requests)

    reopened_database = Database(database_path)
    assert reopened_database.get_job("new-job")["description"] == "Portrait test"
    assert reopened_database.list_presets()[0]["body"] == {"prompt": "portrait, [SCENE]"}
    assert reopened_database.list_lora_profiles()[0]["settings"] == {"strength": 0.7}
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    with pytest.raises(sqlite3.IntegrityError):
        database.add_job("rolled-back", "anima", "", requests)
    assert database.get_job("rolled-back") is None


def test_unsupported_database_version_is_rejected(tmp_path: Path) -> None:
    """구형 DB를 조용히 덮어쓰지 않고 백업 복원을 요구합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(RuntimeError, match="지원하지 않는 DB 버전"):
        Database(database_path)


def test_prompt_preset_keeps_literal_references_across_versions(tmp_path: Path) -> None:
    """Prompt preset 버전에는 태그 참조가 포함된 텍스트만 보관합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    first_body = {"prompt": "portrait, [SCENE]", "negative": ""}
    second_body = {"prompt": "portrait, [SCENE], [LIGHT]", "negative": ""}
    database.save_preset("portrait", "태그 조합", "anima", first_body)
    database.save_preset("portrait", "태그 조합", "anima", second_body)

    reopened_database = Database(database_path)
    assert reopened_database.get_preset("portrait")["body"] == second_body
    versions = reopened_database.list_preset_versions("portrait")
    assert [version["body"] for version in versions] == [second_body, first_body]


def test_job_pagination_and_active_deletion_guard(tmp_path: Path) -> None:
    """페이지 경계와 전체 활성 건수를 계산하고 진행 중 삭제를 거부합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    for job_number in range(12):
        status = "pending" if job_number == 0 else "completed"
        database.add_job(
            f"job-{job_number}", "anima", f"설명 {job_number}", [{
                "request_id": f"request-{job_number}", "status": status,
                "output_stem": "anima/example", "detail": {},
            }],
        )
    first_page = database.list_jobs(page=1, page_size=10)
    second_page = database.list_jobs(page=2, page_size=10)
    assert first_page["total"] == 12
    assert first_page["total_pages"] == 2
    assert first_page["active_count"] == 1
    assert len(first_page["items"]) == 10
    assert len(second_page["items"]) == 2
    assert {job["job_id"] for job in first_page["items"]}.isdisjoint(
        job["job_id"] for job in second_page["items"]
    )
    filtered_page = database.list_jobs(job_id="job-0")
    assert filtered_page["total"] == 1
    assert filtered_page["active_count"] == 1
    assert [job["job_id"] for job in filtered_page["items"]] == ["job-0"]
    assert database.list_jobs(job_id="missing")["total"] == 0
    with pytest.raises(ValueError, match="진행 중"):
        database.delete_job("job-0")
    assert database.delete_job("job-1") is True
    assert database.get_job("job-1") is None


def test_output_paths_map_to_their_original_requests(tmp_path: Path) -> None:
    """결과물의 원래 생성 경로를 작업과 요청 설정에 연결합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    database.add_job("first-job", "anima", "", [{
        "request_id": "first-request", "status": "completed", "output_stem": "anima/example",
        "detail": {"settings": {"width": 768, "height": 1024}},
    }])
    database.add_job("second-job", "anima", "", [{
        "request_id": "second-request", "status": "completed", "output_stem": "anima/example",
        "detail": {},
    }])
    database.complete_request("first-request", ["anima/first.png"])
    database.complete_request("second-request", ["anima/second.png"])

    assert database.find_output_requests([]) == {}
    assert database.find_output_requests(["anima/first.png", "anima/second.png", "anima/moved.png"]) == {
        "anima/first.png": {"job_id": "first-job", "settings": {"width": 768, "height": 1024}},
        "anima/second.png": {"job_id": "second-job", "settings": {}},
    }
