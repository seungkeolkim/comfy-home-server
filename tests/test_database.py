"""현재 SQLite schema와 작업 계층 저장을 검증합니다."""

import sqlite3
import json
from pathlib import Path

import pytest

from home_server.database import Database


def create_legacy_group_tag_database(database_path: Path) -> None:
    """다른 설정과 작업 snapshot을 포함한 version 4 fixture를 준비합니다."""

    database = Database(database_path)
    database.save_tag_group("first-group", "첫 그룹", "CHR", True)
    database.save_tag_group("second-group", "둘째 그룹", "CHR", False)
    database.save_tag_group("empty-group", "빈 그룹", "UNUSED", False)
    for tag_identifier, group_identifier, content in (
        ("first-entry", "first-group", "character A"),
        ("second-entry", "first-group", "character B"),
        ("third-entry", "second-group", "character C"),
    ):
        database.save_tag_entry(tag_identifier, {
            "group_id": group_identifier, "name": tag_identifier, "content": content, "weight": 2.5,
        })
    database.save_preset("legacy-preset", "기존 Prompt", "anima", {"prompt": "[CHR]"})
    database.save_lora_profile("existing.safetensors", "anima", {"strength": 0.7})
    database.create_lora_preset("legacy-loras", "기존 조합", "anima", [{"name": "existing.safetensors"}])
    database.add_job("historical-job", "anima", "기존 이력", [{
        "request_id": "historical-request", "status": "completed", "output_stem": "anima/old",
        "detail": {"selected_tags": [{"tag_id": "first-entry", "tag_key": "CHR", "content": "old snapshot"}]},
    }])
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE tag_entries ADD COLUMN tag_key TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """UPDATE tag_entries SET tag_key =
            (SELECT tag_key FROM tag_groups WHERE tag_groups.group_id = tag_entries.group_id)"""
        )
        connection.execute("DROP INDEX tag_groups_key")
        connection.execute("ALTER TABLE tag_groups DROP COLUMN tag_key")
        connection.execute("CREATE INDEX tag_entries_key ON tag_entries(tag_key)")
        connection.execute("PRAGMA user_version = 4")


def test_group_tag_migration_backs_up_and_preserves_all_records(tmp_path: Path) -> None:
    """중복 참조와 빈 그룹을 migration하고 다른 데이터 및 항목의 ID와 속성을 보존합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    create_legacy_group_tag_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        original_entries = [dict(row) for row in connection.execute("SELECT * FROM tag_entries ORDER BY tag_id")]
        original_tables = {}
        for table_name in ("presets", "preset_versions", "lora_profiles", "lora_presets", "jobs", "job_requests"):
            original_tables[table_name] = [tuple(row) for row in connection.execute(f"SELECT * FROM {table_name}")]

    migrated_database = Database(database_path)
    assert migrated_database.get_tag_group("first-group")["tag_key"] == "CHR"
    assert migrated_database.get_tag_group("second-group")["tag_key"] == "CHR"
    assert migrated_database.get_tag_group("second-group")["default_expanded"] is False
    assert migrated_database.get_tag_group("empty-group")["tag_key"] == ""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        migrated_entries = [dict(row) for row in connection.execute("SELECT * FROM tag_entries ORDER BY tag_id")]
        for original_entry in original_entries:
            original_entry.pop("tag_key")
        assert migrated_entries == original_entries
        for table_name, original_rows in original_tables.items():
            migrated_rows = [tuple(row) for row in connection.execute(f"SELECT * FROM {table_name}")]
            assert migrated_rows == original_rows
        group_index = next(row for row in connection.execute("PRAGMA index_list(tag_groups)") if row["name"] == "tag_groups_key")
        assert group_index["unique"] == 0

    backup_paths = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as backup_connection:
        assert backup_connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert backup_connection.execute("SELECT DISTINCT tag_key FROM tag_entries").fetchall() == [("CHR",)]
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_group_tag_migration_rejects_mixed_keys_without_modifying_database(tmp_path: Path) -> None:
    """한 그룹의 참조가 서로 다르면 백업을 남기고 schema와 데이터를 그대로 유지합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    create_legacy_group_tag_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE tag_entries SET tag_key = 'OTHER' WHERE tag_id = 'second-entry'")
    with pytest.raises(RuntimeError, match="서로 달라"):
        Database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert "tag_key" not in [row[1] for row in connection.execute("PRAGMA table_info(tag_groups)")]
        assert connection.execute("SELECT tag_key FROM tag_entries WHERE tag_id = 'second-entry'").fetchone()[0] == "OTHER"
        assert connection.execute("SELECT COUNT(*) FROM tag_entries").fetchone()[0] == 3
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
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


def test_job_protection_migration_preserves_existing_history(tmp_path: Path) -> None:
    """Version 5의 작업·설정을 보존해 보호 column을 추가하고 재접속 후에도 유지합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    original_body = {"prompt": "original prompt", "negative": "negative prompt"}
    database.save_preset("original-preset", "Original", "anima", original_body)
    database.add_job("original-job", "anima", "migration test", [{
        "request_id": "original-request", "status": "completed", "output_stem": "anima/example",
        "detail": {"body": original_body},
    }])
    database.complete_request("original-request", ["anima/original.png"])
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE jobs DROP COLUMN deletion_protected")
        connection.execute("PRAGMA user_version = 5")

    migrated_database = Database(database_path)
    migrated_job = migrated_database.get_job("original-job")
    assert migrated_job["deletion_protected"] is False
    assert migrated_job["description"] == "migration test"
    assert migrated_job["inputs"]["body"] == original_body
    assert migrated_job["requests"][0]["result"]["output_paths"] == ["anima/original.png"]
    assert migrated_database.get_preset("original-preset")["body"] == original_body
    assert migrated_database.set_job_deletion_protection("original-job", True)
    assert Database(database_path).get_job("original-job")["deletion_protected"] is True
    assert not migrated_database.set_job_deletion_protection("missing-job", True)


def test_all_page_deletion_candidates_exclude_protected_and_active_jobs(tmp_path: Path) -> None:
    """모든 페이지의 후보를 조회하고 보호 작업과 각종 진행 중 작업을 제외합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    active_statuses = ["submitting", "pending", "running", "cancelling"]
    for job_number in range(25):
        status = active_statuses[job_number] if job_number < len(active_statuses) else "completed"
        database.add_job(f"job-{job_number}", "anima", "", [{
            "request_id": f"request-{job_number}", "status": status,
            "output_stem": "anima/example", "detail": {},
        }])
    database.set_job_deletion_protection("job-4", True)
    database.set_job_deletion_protection("job-24", True)
    assert set(database.list_deletable_job_ids()) == {f"job-{job_number}" for job_number in range(5, 24)}
    assert database.list_deletable_job_ids("job-4") == []
    assert database.list_deletable_job_ids("job-5") == ["job-5"]
    assert database.list_deletable_job_ids("missing-job") == []
    database.set_job_deletion_protection("job-4", False)
    assert "job-4" in database.list_deletable_job_ids()


def test_protection_is_checked_before_file_callback_and_locked_until_deletion(tmp_path: Path) -> None:
    """보호를 먼저 검사하고 파일 처리 중에는 다른 연결의 보호 설정 변경을 막습니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    database.add_job("protected-job", "anima", "", [{
        "request_id": "protected-request", "status": "completed", "output_stem": "anima/example", "detail": {},
    }])
    database.set_job_deletion_protection("protected-job", True)
    callback_invocations = []

    def verify_deletion_lock() -> None:
        """다른 writer가 파일 처리 중 끼어들 수 없는지 확인합니다."""

        callback_invocations.append("called")
        with sqlite3.connect(database_path, timeout=0) as concurrent_connection:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                concurrent_connection.execute("UPDATE jobs SET deletion_protected = 1 WHERE job_id = 'protected-job'")

    with pytest.raises(ValueError, match="삭제 보호"):
        database.delete_job("protected-job", before_deletion=verify_deletion_lock)
    assert callback_invocations == []
    assert database.get_job("protected-job") is not None
    database.set_job_deletion_protection("protected-job", False)
    assert database.delete_job("protected-job", before_deletion=verify_deletion_lock)
    assert callback_invocations == ["called"]
    assert database.get_job("protected-job") is None


def test_large_job_summary_and_monitor_do_not_parse_child_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """100개 후보 Snapshot을 보존하면서 목록·감시에는 작은 상태 정보만 사용합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    detail = {"body": {"prompt": "portrait"}, "selected_tags": [{"content": "candidate" * 5000}],
              "settings": {"width": 768, "height": 1024}, "loras": []}
    requests = []
    for request_index in range(100):
        requests.append({"request_id": f"request-{request_index}", "status": "submitting",
                         "output_stem": "anima/output", "detail": detail})
    database.add_job("large-job", "anima", "large", requests)

    def reject_snapshot_conversion(row: sqlite3.Row) -> dict:
        """요약·감시 조회가 개별 상세 변환을 호출하면 실패시킵니다."""

        raise AssertionError("전체 요청 Snapshot을 파싱했습니다.")

    monkeypatch.setattr(database, "_request_from_row", reject_snapshot_conversion)
    summaries = database.list_job_summaries()
    assert len(json.dumps(summaries).encode()) < 2000
    assert "requests" not in summaries["items"][0]
    assert "selected_tags" not in summaries["items"][0]["summary"]
    assert summaries["items"][0]["status_counts"] == {"submitting": 100}
    active_requests = database.list_active_requests()
    assert len(active_requests) == 100
    assert all("detail" not in request for request in active_requests)
    with database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_inputs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM request_results").fetchone()[0] == 100
        assert json.loads(connection.execute("SELECT selected_tags_json FROM job_inputs").fetchone()[0]) == detail["selected_tags"]


def test_active_monitor_does_not_hide_older_requests_above_a_thousand(tmp_path: Path) -> None:
    """감시·취소 대상이 1000개를 넘더라도 오래된 활성 요청을 누락하지 않습니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    for job_index in range(11):
        requests = []
        for request_index in range(100):
            requests.append({"request_id": f"request-{job_index}-{request_index}", "status": "pending",
                             "output_stem": "anima/output", "detail": {}})
        database.add_job(f"job-{job_index}", "anima", "", requests)
    assert len(database.list_active_requests()) == 1100
    assert len(database.list_active_requests(limit=10)) == 10
    assert len(database.list_active_requests(job_id="job-5")) == 100
    assert {request["job_id"] for request in database.list_active_requests(job_id="job-5", limit=10)} == {"job-5"}
    assert len(database.list_active_requests(job_id="job-5", limit=10)) == 10
    assert database.list_active_requests(job_id="missing") == []


def test_cancellation_survives_late_acceptance_and_queue_updates(tmp_path: Path) -> None:
    """취소 도중 접수된 prompt ID를 추적하고 이전 queue Snapshot이 취소를 덮어쓰지 않습니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    database.add_job("cancel-job", "anima", "", [{
        "request_id": "inflight-request", "status": "submitting", "output_stem": "anima/output", "detail": {},
    }])
    assert database.request_job_cancellation("cancel-job") == 1
    assert Database(database_path).get_job("cancel-job")["cancellation_requested"] is True
    database.set_request_accepted("inflight-request", "late-prompt", {"prompt": "resolved"})
    database.apply_request_states([{"request_id": "inflight-request", "status": "pending"}])
    request = database.get_request("inflight-request")
    assert request["status"] == "cancelling"
    assert request["prompt_id"] == "late-prompt"
    database.cancel_unsubmitted_request("inflight-request")
    assert database.get_request("inflight-request")["status"] == "cancelling"


def test_version_six_migration_preserves_protected_history_and_inputs(tmp_path: Path) -> None:
    """Version 6의 보호 설정과 원본 Snapshot을 유지하며 취소 의도 column만 추가합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    detail = {"body": {"prompt": "saved"}, "selected_tags": [{"tag_id": "original"}]}
    database.add_job("protected", "anima", "", [{
        "request_id": "saved", "status": "completed", "output_stem": "anima/output", "detail": detail,
    }])
    database.set_job_deletion_protection("protected", True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE jobs DROP COLUMN cancellation_requested")
        connection.execute("PRAGMA user_version = 6")
    migrated_database = Database(database_path)
    assert migrated_database.get_job("protected")["deletion_protected"] is True
    assert migrated_database.get_job("protected")["cancellation_requested"] is False
    assert migrated_database.get_job_inputs("protected")["inputs"] == detail
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11


@pytest.mark.parametrize("schema_version", [6, 7, 8])
def test_request_storage_migration_preserves_inputs_results_and_cascade(tmp_path: Path, schema_version: int) -> None:
    """이전 Snapshot을 모두 분리하고 백업·재시작·FK·삭제 규칙을 검증합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    detail = {"body": {"prompt": "original"}, "selected_tags": [{"content": "candidate" * 5000}],
              "resolved": {"prompt": "resolved", "output_paths": ["anima/image.png"]}}
    database.add_job("legacy", "anima", "legacy", [{
        "request_id": "legacy-request", "status": "completed", "output_stem": "anima/output", "detail": detail,
    }])
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE job_inputs")
        connection.execute("DROP TABLE request_results")
        if schema_version == 8:
            connection.execute("CREATE TABLE request_details (request_id TEXT PRIMARY KEY REFERENCES job_requests(request_id) ON DELETE CASCADE, detail_json TEXT NOT NULL)")
            connection.execute("INSERT INTO request_details VALUES (?, ?)", ("legacy-request", json.dumps(detail)))
        else:
            connection.execute("ALTER TABLE job_requests ADD COLUMN detail_json TEXT NOT NULL DEFAULT '{}'")
            connection.execute("UPDATE job_requests SET detail_json = ?", (json.dumps(detail),))
        if schema_version == 6:
            connection.execute("ALTER TABLE jobs DROP COLUMN cancellation_requested")
        connection.execute(f"PRAGMA user_version = {schema_version}")
    migrated_database = Database(database_path)
    assert migrated_database.get_job_inputs("legacy")["inputs"] == {
        "body": detail["body"], "selected_tags": detail["selected_tags"],
    }
    assert migrated_database.get_request("legacy-request")["result"] == detail["resolved"]
    assert migrated_database.get_request("legacy-request")["inputs"] == {"body": detail["body"]}
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        assert "detail_json" not in {row[1] for row in connection.execute("PRAGMA table_info(job_requests)")}
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'request_details'").fetchone() is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    backup_paths = list((tmp_path / "backups").glob("*before_job_request_storage*.sqlite3"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as backup_connection:
        original_table = "request_details" if schema_version == 8 else "job_requests"
        assert json.loads(backup_connection.execute(f"SELECT detail_json FROM {original_table}").fetchone()[0]) == detail
        assert backup_connection.execute("PRAGMA user_version").fetchone()[0] == schema_version
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*before_job_request_storage*.sqlite3"))) == 1
    assert migrated_database.delete_job("legacy")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM request_results").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM job_inputs").fetchone()[0] == 0


def test_version_eight_migration_preserves_every_request_and_minimax_upload(tmp_path: Path) -> None:
    """같은 작업의 서로 다른 이미지·Seed·선택 경로·미확정 결과를 빠짐없이 옮깁니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    original_details = {}
    for workflow in ("anima", "minimax_h3"):
        requests = []
        for request_index in range(4):
            detail = {
                "body": {"prompt": f"{workflow} prompt", "negative": "negative"},
                "settings": {"width": 768, "height": 1024}, "loras": [{"name": "example"}],
                "selected_tags": [{"tag_id": "checked", "content": "large candidate" * 1000}],
                "prompt_preset_id": "preset", "lora_preset_name": "saved name",
                "upload_id": f"image-{request_index}" if workflow == "minimax_h3" else None,
            }
            if request_index != 3:
                detail["resolved"] = {
                    "prompt": f"resolved {request_index}", "negative": "resolved negative",
                    "selected_path": [{"tag_id": "checked", "name": "saved tag", "depth": request_index}],
                    "negative_selected_path": [{"tag_id": "negative", "name": "saved negative"}],
                    "wildcard_seed": request_index,
                    "settings": {"width": 768, "height": 1024, "seed": request_index},
                    "output_paths": [f"{workflow}/image-{request_index}.png"],
                    "unknown_result_field": {"keep": True},
                }
            request_id = f"{workflow}-{request_index}"
            original_details[request_id] = detail
            requests.append({"request_id": request_id, "status": "completed" if request_index < 3 else "cancelled",
                             "output_stem": "output", "detail": detail})
        database.add_job(workflow, workflow, "migration", requests)
    database.set_job_deletion_protection("anima", True)
    with sqlite3.connect(database_path) as connection:
        original_jobs = connection.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()
        original_requests = connection.execute("SELECT * FROM job_requests ORDER BY request_id").fetchall()
        connection.execute("DROP TABLE job_inputs")
        connection.execute("DROP TABLE request_results")
        connection.execute("CREATE TABLE request_details (request_id TEXT PRIMARY KEY REFERENCES job_requests(request_id), detail_json TEXT NOT NULL)")
        for request_id, detail in original_details.items():
            connection.execute("INSERT INTO request_details VALUES (?, ?)", (request_id, json.dumps(detail)))
        connection.execute("PRAGMA user_version = 8")
    migrated = Database(database_path)
    for request_id, detail in original_details.items():
        request = migrated.get_request(request_id)
        workflow = request["workflow"]
        inputs = migrated.get_job_inputs(workflow)["inputs"]
        assert inputs == {key: value for key, value in detail.items() if key not in {"resolved", "upload_id"}}
        assert request["result"] == detail.get("resolved", {})
        assert request["upload_id"] == detail["upload_id"]
        assert "selected_tags" not in request["inputs"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT * FROM jobs ORDER BY job_id").fetchall() == original_jobs
        assert connection.execute("SELECT * FROM job_requests ORDER BY request_id").fetchall() == original_requests
        assert connection.execute("SELECT COUNT(*) FROM job_inputs").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM request_results").fetchone()[0] == 8
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("invalid_detail", ["different_inputs", "missing_detail", "invalid_json", "orphan_detail"])
def test_storage_migration_failure_leaves_original_database_untouched(tmp_path: Path, invalid_detail: str) -> None:
    """손실 위험이 있는 이전 Row는 백업 후 전체 Transaction을 되돌립니다."""

    database_path = tmp_path / "home_server.sqlite3"
    database = Database(database_path)
    database.add_job("original", "anima", "", [
        {"request_id": f"request-{request_index}", "status": "cancelled", "output_stem": "output",
         "detail": {"body": {"prompt": "same"}}} for request_index in range(2)
    ])
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE job_inputs")
        connection.execute("DROP TABLE request_results")
        connection.execute("CREATE TABLE request_details (request_id TEXT PRIMARY KEY REFERENCES job_requests(request_id), detail_json TEXT NOT NULL)")
        connection.execute("INSERT INTO request_details VALUES ('request-0', ?)", (json.dumps({"body": {"prompt": "same"}}),))
        if invalid_detail != "missing_detail":
            detail_json = "invalid-json" if invalid_detail == "invalid_json" else json.dumps({
                "body": {"prompt": "same" if invalid_detail == "orphan_detail" else "different"},
            })
            connection.execute("INSERT INTO request_details VALUES ('request-1', ?)", (detail_json,))
        if invalid_detail == "orphan_detail":
            connection.execute("INSERT INTO request_details VALUES ('orphan', '{}')")
        connection.execute("PRAGMA user_version = 8")
        original_details = connection.execute("SELECT * FROM request_details ORDER BY request_id").fetchall()
    with pytest.raises(ValueError):
        Database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute("SELECT * FROM request_details ORDER BY request_id").fetchall() == original_details
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN ('job_inputs', 'request_results')").fetchall() == []
    assert len(list((tmp_path / "backups").glob("*before_job_request_storage*.sqlite3"))) == 1


def test_detail_queries_and_updates_never_read_candidate_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """확정 결과의 조회·접수·완료·결과물 연결에는 후보 JSON을 읽거나 전송하지 않습니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    marker = "unused-candidate" * 10000
    detail = {"body": {"prompt": "[TAG]"}, "selected_tags": [{"content": marker}],
              "settings": {"width": 768, "height": 1024}, "loras": []}
    database.add_job("large", "anima", "", [
        {"request_id": f"request-{request_index}", "status": "pending", "output_stem": "output", "detail": detail}
        for request_index in range(100)
    ])
    original_json_loads = json.loads

    def reject_candidate_parsing(serialized_value: str, *arguments, **keyword_arguments):
        """후보를 포함한 JSON을 파싱하면 테스트를 실패시킵니다."""

        assert marker not in serialized_value
        return original_json_loads(serialized_value, *arguments, **keyword_arguments)

    monkeypatch.setattr(json, "loads", reject_candidate_parsing)
    database.set_request_accepted("request-0", "prompt", {"prompt": "final", "selected_path": [{"name": "chosen"}]})
    database.complete_request("request-0", ["anima/image.png"])
    assert len(json.dumps(database.get_job("large")).encode()) < 50000
    assert len(json.dumps(database.list_jobs()).encode()) < 50000
    assert database.get_request("request-0")["result"]["prompt"] == "final"
    assert database.list_job_summaries()["items"][0]["status_counts"] == {"completed": 1, "pending": 99}
    assert database.find_output_requests(["anima/image.png"])["anima/image.png"]["job_id"] == "large"
