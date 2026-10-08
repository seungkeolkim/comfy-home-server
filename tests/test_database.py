"""현재 SQLite schema와 작업 계층 저장을 검증합니다."""

import sqlite3
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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        migrated_entries = [dict(row) for row in connection.execute("SELECT * FROM tag_entries ORDER BY tag_id")]
        for original_entry in original_entries:
            original_entry.pop("tag_key")
        assert migrated_entries == original_entries
        for table_name, original_rows in original_tables.items():
            assert [tuple(row) for row in connection.execute(f"SELECT * FROM {table_name}")] == original_rows
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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
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
