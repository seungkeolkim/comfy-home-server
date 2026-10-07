"""기존 설정 데이터 보존과 작업 계층 저장을 검증합니다."""

import sqlite3
from pathlib import Path

import pytest

from home_server.database import Database


def test_legacy_job_migration_preserves_prompts_and_lora_settings(tmp_path: Path) -> None:
    """기존 요청 기록만 폐기하고 Prompt와 LoRA 데이터를 유지합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE presets (preset_id TEXT PRIMARY KEY, name TEXT, workflow TEXT,
                version INTEGER, body_json TEXT, updated_at TEXT);
            CREATE TABLE preset_versions (preset_id TEXT, version INTEGER, body_json TEXT,
                saved_at TEXT, PRIMARY KEY (preset_id, version));
            CREATE TABLE lora_profiles (file_name TEXT, workflow TEXT, settings_json TEXT,
                updated_at TEXT, PRIMARY KEY (file_name, workflow));
            CREATE TABLE lora_presets (preset_id TEXT PRIMARY KEY, name TEXT, workflow TEXT,
                loras_json TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE jobs (request_id TEXT PRIMARY KEY, batch_id TEXT, prompt_id TEXT,
                workflow TEXT, status TEXT, output_stem TEXT, detail_json TEXT,
                error_message TEXT, created_at TEXT, updated_at TEXT);
            INSERT INTO presets VALUES ('prompt-1', 'Portrait', 'anima', 1, '{"prefix":"portrait"}', 'time');
            INSERT INTO preset_versions VALUES ('prompt-1', 1, '{"prefix":"portrait"}', 'time');
            INSERT INTO lora_profiles VALUES ('portrait.safetensors', 'anima', '{"strength":0.7}', 'time');
            INSERT INTO lora_presets VALUES ('lora-1', 'Portrait', 'anima',
                '[{"name":"portrait.safetensors","strength":0.7}]', 'time', 'time');
            INSERT INTO jobs VALUES ('old-request', 'old-batch', 'old-prompt', 'anima',
                'completed', 'anima/old', '{}', NULL, 'time', 'time');
            """
        )

    database = Database(database_path)
    assert database.list_jobs()["items"] == []
    assert database.list_presets()[0]["body"] == {"prefix": "portrait"}
    assert database.list_preset_versions("prompt-1")[0]["version"] == 1
    assert database.list_lora_profiles()[0]["settings"] == {"strength": 0.7}
    assert database.list_lora_presets()[0]["loras"][0]["name"] == "portrait.safetensors"

    requests = [{
        "request_id": "new-request", "status": "submitting", "output_stem": "anima/%time_%seed",
        "detail": {"body": {"prefix": "portrait"}},
    }]
    database.add_job("new-job", "anima", "Portrait test", requests)
    assert Database(database_path).get_job("new-job")["request_count"] == 1
    assert Database(database_path).get_job("new-job")["description"] == "Portrait test"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        database.add_job("rolled-back", "anima", "", requests)
    assert database.get_job("rolled-back") is None


def test_grouped_job_migration_keeps_existing_history(tmp_path: Path) -> None:
    """기존 상위 작업과 하위 요청을 보존하며 설명 필드만 추가합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA user_version = 1;
            CREATE TABLE jobs (job_id TEXT PRIMARY KEY, workflow TEXT NOT NULL,
                request_count INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE job_requests (request_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(job_id), request_index INTEGER NOT NULL,
                prompt_id TEXT, status TEXT NOT NULL, output_stem TEXT NOT NULL,
                detail_json TEXT NOT NULL, error_message TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE (job_id, request_index));
            INSERT INTO jobs VALUES ('old-job', 'anima', 1, '2026-10-06');
            INSERT INTO job_requests VALUES ('old-request', 'old-job', 1, 'prompt-1',
                'completed', 'anima/example', '{}', NULL, '2026-10-06', '2026-10-06');
            """
        )

    database = Database(database_path)
    job = database.get_job("old-job")
    assert job is not None
    assert job["description"] == ""
    assert job["requests"][0]["request_id"] == "old-request"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_prompt_preset_keeps_multiple_scenarios_across_versions(tmp_path: Path) -> None:
    """하나의 Prompt preset에 여러 상황을 버전별로 함께 보관합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    first_body = {"prefix": "portrait", "scenarios": [
        {"id": "day", "name": "주간", "situation": "daylight"},
    ]}
    second_body = {"prefix": "portrait", "scenarios": [
        {"id": "day", "name": "주간", "situation": "daylight"},
        {"id": "night", "name": "야간", "situation": "nightlight"},
    ]}
    database.save_preset("portrait", "다중 상황", "anima", first_body)
    database.save_preset("portrait", "다중 상황", "anima", second_body)

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
