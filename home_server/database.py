"""Prompt, LoRA 설정, 상위 작업과 개별 요청을 SQLite에 보관합니다."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .output_timing import OutputTimingRecorder, measure_output_step
from .output_catalog import OutputCatalog


def current_timestamp() -> str:
    """UTC ISO 형식의 현재 시간을 반환합니다."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """요청마다 독립적인 SQLite 연결을 사용합니다."""

    def __init__(self, database_path: Path) -> None:
        """현재 버전의 SQLite schema를 준비합니다."""

        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema_version == 4:
                self._backup_before_group_tag_migration(connection)
            elif schema_version in {5, 6, 7, 8}:
                self._backup_before_schema_change(connection, "job_request_storage")
            elif schema_version == 9:
                self._backup_before_schema_change(connection, "output_catalog")
            connection.execute("BEGIN IMMEDIATE")
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema_version not in {0, 4, 5, 6, 7, 8, 9, 10}:
                raise RuntimeError("지원하지 않는 DB 버전입니다.")
            if schema_version == 4:
                self._migrate_group_tag_keys(connection)
            for create_statement in (
                """CREATE TABLE IF NOT EXISTS presets (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS preset_versions (
                    preset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    PRIMARY KEY (preset_id, version)
                )""",
                """CREATE TABLE IF NOT EXISTS lora_profiles (
                    file_name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (file_name, workflow)
                )""",
                """CREATE TABLE IF NOT EXISTS lora_presets (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    loras_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
            ):
                connection.execute(create_statement)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    workflow TEXT NOT NULL,
                    request_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    deletion_protected INTEGER NOT NULL DEFAULT 0
                )"""
            )
            job_columns = {column[1] for column in connection.execute("PRAGMA table_info(jobs)")}
            if "deletion_protected" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN deletion_protected INTEGER NOT NULL DEFAULT 0")
            if "cancellation_requested" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS job_requests (
                    request_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    request_index INTEGER NOT NULL,
                    prompt_id TEXT,
                    status TEXT NOT NULL,
                    output_stem TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_id, request_index)
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs(created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS job_requests_job_id ON job_requests(job_id, request_index)")
            connection.execute("CREATE INDEX IF NOT EXISTS job_requests_status ON job_requests(status)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS job_inputs (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
                    input_json TEXT NOT NULL,
                    selected_tags_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS request_results (
                    request_id TEXT PRIMARY KEY REFERENCES job_requests(request_id) ON DELETE CASCADE,
                    upload_id TEXT,
                    result_json TEXT NOT NULL
                )"""
            )
            if schema_version < 9:
                self._migrate_job_request_storage(connection)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tag_groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tag_key TEXT NOT NULL,
                    default_expanded INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tag_entries (
                    tag_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES tag_groups(group_id),
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS tag_entries_group ON tag_entries(group_id, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS tag_groups_key ON tag_groups(tag_key)")
            OutputCatalog.prepare_schema(connection)
            if schema_version < 10:
                OutputCatalog.backfill_from_requests(connection)
            connection.execute("PRAGMA user_version = 10")

    def _separate_request_detail(
        self, detail: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str | None, dict[str, Any]]:
        """제출 입력에서 공통 설정·후보와 요청별 이미지·확정 결과를 분리합니다."""

        common_inputs = {}
        for detail_key, detail_value in detail.items():
            if detail_key not in {"selected_tags", "upload_id", "resolved"}:
                common_inputs[detail_key] = detail_value
        return common_inputs, detail.get("selected_tags", []), detail.get("upload_id"), detail.get("resolved", {})

    def _migrate_job_request_storage(self, connection: sqlite3.Connection) -> None:
        """이전 모든 요청을 새 구조로 옮긴 뒤 원래 Snapshot 저장소를 제거합니다."""

        request_columns = {column[1] for column in connection.execute("PRAGMA table_info(job_requests)")}
        legacy_details_exist = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'request_details'"
        ).fetchone() is not None
        if "detail_json" in request_columns:
            detail_query = "SELECT request_id, detail_json FROM job_requests WHERE job_id = ? ORDER BY request_index"
        elif legacy_details_exist:
            detail_query = (
                "SELECT request_id, detail_json FROM job_requests JOIN request_details USING (request_id) "
                "WHERE job_id = ? ORDER BY request_index"
            )
        else:
            return

        migrated_request_count = 0
        for job_row in connection.execute("SELECT job_id FROM jobs").fetchall():
            job_inputs = None
            selected_tags = []
            for request_row in connection.execute(detail_query, (job_row["job_id"],)):
                detail = json.loads(request_row["detail_json"])
                common_inputs, candidate_tags, upload_id, resolved_result = self._separate_request_detail(detail)
                if job_inputs is None:
                    job_inputs = common_inputs
                    selected_tags = candidate_tags
                elif job_inputs != common_inputs or selected_tags != candidate_tags:
                    raise ValueError(f"작업 내 공통 입력이 달라 Migration을 중단합니다: {job_row['job_id']}")
                connection.execute(
                    "INSERT INTO request_results (request_id, upload_id, result_json) VALUES (?, ?, ?)",
                    (request_row["request_id"], upload_id, json.dumps(resolved_result, ensure_ascii=False)),
                )
                migrated_request_count += 1
            connection.execute(
                "INSERT INTO job_inputs (job_id, input_json, selected_tags_json) VALUES (?, ?, ?)",
                (job_row["job_id"], json.dumps(job_inputs or {}, ensure_ascii=False),
                 json.dumps(selected_tags, ensure_ascii=False)),
            )
        expected_request_count = connection.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0]
        if migrated_request_count != expected_request_count:
            raise ValueError("상세가 누락된 요청이 있어 Migration을 중단합니다.")
        if legacy_details_exist:
            original_detail_count = connection.execute("SELECT COUNT(*) FROM request_details").fetchone()[0]
            if original_detail_count != migrated_request_count:
                raise ValueError("요청에 연결되지 않은 상세 Row가 있어 Migration을 중단합니다.")
            connection.execute("DROP TABLE request_details")
        if "detail_json" in request_columns:
            connection.execute("ALTER TABLE job_requests DROP COLUMN detail_json")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Migration 이후 FK 무결성 검사에 실패했습니다.")

    def _backup_before_group_tag_migration(self, connection: sqlite3.Connection) -> None:
        """SQLite backup API로 schema 변경 전 일관된 복구용 DB를 보관합니다."""

        self._backup_before_schema_change(connection, "group_tag_keys")

    def _backup_before_schema_change(self, connection: sqlite3.Connection, change_name: str) -> None:
        """데이터를 옮기기 전 검증된 SQLite 백업을 만들어 실패 시 기존 DB를 보존합니다."""

        backup_directory = self.database_path.parent / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        backup_path = backup_directory / f"{self.database_path.stem}_before_{change_name}_{backup_timestamp}.sqlite3"
        with sqlite3.connect(backup_path) as backup_connection:
            connection.backup(backup_connection)
            integrity_result = backup_connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity_result != "ok":
                raise RuntimeError("DB 백업의 무결성 검사에 실패하여 migration을 중단합니다.")

    def _migrate_group_tag_keys(self, connection: sqlite3.Connection) -> None:
        """기존 그룹의 공통 참조 태그를 옮기고 개별 항목의 참조 column을 제거합니다."""

        inconsistent_group = connection.execute(
            """SELECT tag_groups.name FROM tag_groups JOIN tag_entries USING (group_id)
            GROUP BY tag_groups.group_id HAVING COUNT(DISTINCT tag_entries.tag_key) > 1 LIMIT 1"""
        ).fetchone()
        if inconsistent_group is not None:
            raise RuntimeError(f"그룹 안의 참조 태그가 서로 달라 migration할 수 없습니다: {inconsistent_group['name']}")

        connection.execute("ALTER TABLE tag_groups ADD COLUMN tag_key TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """UPDATE tag_groups SET tag_key = COALESCE(
                (SELECT MIN(tag_entries.tag_key) FROM tag_entries
                 WHERE tag_entries.group_id = tag_groups.group_id), '')"""
        )
        connection.execute(
            """CREATE TABLE migrated_tag_entries (
                tag_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL REFERENCES tag_groups(group_id),
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                weight REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO migrated_tag_entries
            SELECT tag_id, group_id, name, content, weight, created_at, updated_at FROM tag_entries"""
        )
        connection.execute("DROP TABLE tag_entries")
        connection.execute("ALTER TABLE migrated_tag_entries RENAME TO tag_entries")

    def _connect(self) -> sqlite3.Connection:
        """row 이름으로 결과를 읽는 SQLite 연결을 엽니다."""

        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def list_presets(self) -> list[dict[str, Any]]:
        """최신 Prompt preset 목록을 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM presets ORDER BY updated_at DESC").fetchall()
        return [self._preset_from_row(row) for row in rows]

    def get_preset(self, preset_id: str) -> dict[str, Any] | None:
        """식별자에 해당하는 최신 preset을 반환합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT * FROM presets WHERE preset_id = ?", (preset_id,)).fetchone()
        return self._preset_from_row(row) if row else None

    def save_preset(self, preset_id: str, name: str, workflow: str, body: dict[str, Any]) -> dict[str, Any]:
        """Preset의 새 버전을 추가하고 최신 내용을 갱신합니다."""

        saved_at = current_timestamp()
        body_json = json.dumps(body, ensure_ascii=False)
        with self._connect() as connection:
            row = connection.execute("SELECT version FROM presets WHERE preset_id = ?", (preset_id,)).fetchone()
            version = int(row["version"]) + 1 if row else 1
            connection.execute(
                """INSERT INTO presets VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(preset_id) DO UPDATE SET
                name=excluded.name, workflow=excluded.workflow, version=excluded.version,
                body_json=excluded.body_json, updated_at=excluded.updated_at""",
                (preset_id, name, workflow, version, body_json, saved_at),
            )
            connection.execute(
                "INSERT INTO preset_versions VALUES (?, ?, ?, ?)",
                (preset_id, version, body_json, saved_at),
            )
        return self.get_preset(preset_id) or {}

    def list_preset_versions(self, preset_id: str) -> list[dict[str, Any]]:
        """Preset의 이전 저장 내용을 최신순으로 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM preset_versions WHERE preset_id = ? ORDER BY version DESC", (preset_id,)
            ).fetchall()
        return [{"version": row["version"], "body": json.loads(row["body_json"]), "saved_at": row["saved_at"]} for row in rows]

    def list_tag_groups(self) -> list[dict[str, Any]]:
        """화면 표시 그룹과 기본 펼침 상태를 생성 순서로 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM tag_groups ORDER BY created_at, group_id").fetchall()
        return [self._tag_group_from_row(row) for row in rows]

    def get_tag_group(self, group_id: str) -> dict[str, Any] | None:
        """식별자에 해당하는 태그 그룹을 반환합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tag_groups WHERE group_id = ?", (group_id,)).fetchone()
        return self._tag_group_from_row(row) if row else None

    def save_tag_group(self, group_id: str, name: str, tag_key: str, default_expanded: bool) -> dict[str, Any]:
        """그룹의 참조 태그와 표시 설정을 저장하며 동일 참조의 여러 그룹을 허용합니다."""

        timestamp = current_timestamp()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO tag_groups
                (group_id, name, tag_key, default_expanded, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET name=excluded.name,
                tag_key=excluded.tag_key, default_expanded=excluded.default_expanded,
                updated_at=excluded.updated_at""",
                (group_id, name, tag_key, int(default_expanded), timestamp, timestamp),
            )
        return self.get_tag_group(group_id) or {}

    def delete_tag_group(self, group_id: str) -> bool:
        """비어 있는 그룹만 삭제하며 항목이 있으면 SQLite 제약으로 거부합니다."""

        with self._connect() as connection:
            result = connection.execute("DELETE FROM tag_groups WHERE group_id = ?", (group_id,))
        return result.rowcount > 0

    def list_tag_entries(self) -> list[dict[str, Any]]:
        """그룹과 생성 순서로 모든 태그 항목을 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT tag_entries.* FROM tag_entries JOIN tag_groups USING (group_id)
                ORDER BY tag_groups.created_at, tag_groups.group_id,
                tag_entries.created_at, tag_entries.tag_id"""
            ).fetchall()
        return [self._tag_entry_from_row(row) for row in rows]

    def get_tag_entry(self, tag_id: str) -> dict[str, Any] | None:
        """식별자에 해당하는 태그 항목을 반환합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tag_entries WHERE tag_id = ?", (tag_id,)).fetchone()
        return self._tag_entry_from_row(row) if row else None

    def get_selected_tag_definitions(self, selected_tag_ids: list[str]) -> list[dict[str, Any]]:
        """선택한 항목과 그룹 참조를 한 SQL Snapshot에서 함께 읽습니다."""

        if not selected_tag_ids:
            return []
        placeholders = ",".join("?" for _ in selected_tag_ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT tag_entries.*, tag_groups.tag_key, tag_groups.name AS group_name "
                "FROM tag_entries JOIN tag_groups USING (group_id) "
                f"WHERE tag_entries.tag_id IN ({placeholders})", tuple(selected_tag_ids),
            ).fetchall()
        definitions = []
        for row in rows:
            definition = self._tag_entry_from_row(row)
            definition["tag_key"] = row["tag_key"]
            definition["group_name"] = row["group_name"]
            definitions.append(definition)
        return definitions

    def save_tag_entry(self, tag_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """태그 항목의 안정적인 ID를 유지하며 본문과 선택 속성을 저장합니다."""

        timestamp = current_timestamp()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO tag_entries VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tag_id) DO UPDATE SET group_id=excluded.group_id,
                name=excluded.name, content=excluded.content,
                weight=excluded.weight, updated_at=excluded.updated_at""",
                (
                    tag_id, values["group_id"], values["name"],
                    values["content"], values["weight"],
                    timestamp, timestamp,
                ),
            )
        return self.get_tag_entry(tag_id) or {}

    def delete_tag_entry(self, tag_id: str) -> bool:
        """태그 항목의 현재 정의만 삭제하고 기존 작업 기록은 유지합니다."""

        with self._connect() as connection:
            result = connection.execute("DELETE FROM tag_entries WHERE tag_id = ?", (tag_id,))
        return result.rowcount > 0

    def _tag_group_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """그룹 row를 API 응답으로 변환합니다."""

        return {
            "group_id": row["group_id"], "name": row["name"],
            "tag_key": row["tag_key"],
            "default_expanded": bool(row["default_expanded"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _tag_entry_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """태그 항목 row를 API 응답으로 변환합니다."""

        return {
            "tag_id": row["tag_id"], "group_id": row["group_id"],
            "name": row["name"],
            "content": row["content"], "weight": row["weight"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def list_lora_profiles(self) -> list[dict[str, Any]]:
        """Workflow별 LoRA 기본 강도 설정을 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM lora_profiles ORDER BY file_name, workflow").fetchall()
        return [
            {"name": row["file_name"], "workflow": row["workflow"],
             "settings": json.loads(row["settings_json"]), "updated_at": row["updated_at"]}
            for row in rows
        ]

    def save_lora_profile(self, file_name: str, workflow: str, settings: dict[str, Any]) -> None:
        """하나의 LoRA에 대한 workflow별 기본 강도를 저장합니다."""

        with self._connect() as connection:
            connection.execute(
                """INSERT INTO lora_profiles VALUES (?, ?, ?, ?)
                ON CONFLICT(file_name, workflow) DO UPDATE SET
                settings_json=excluded.settings_json, updated_at=excluded.updated_at""",
                (file_name, workflow, json.dumps(settings, ensure_ascii=False), current_timestamp()),
            )

    def list_lora_presets(self) -> list[dict[str, Any]]:
        """LoRA 조합과 저장된 강도를 최근 수정 순서로 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM lora_presets ORDER BY updated_at DESC, preset_id").fetchall()
        return [self._lora_preset_from_row(row) for row in rows]

    def create_lora_preset(self, preset_id: str, name: str, workflow: str, selected_loras: list[dict[str, Any]]) -> dict[str, Any]:
        """개별 LoRA 기본값과 독립된 조합 snapshot을 저장합니다."""

        saved_at = current_timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO lora_presets VALUES (?, ?, ?, ?, ?, ?)",
                (preset_id, name, workflow, json.dumps(selected_loras, ensure_ascii=False), saved_at, saved_at),
            )
            row = connection.execute("SELECT * FROM lora_presets WHERE preset_id = ?", (preset_id,)).fetchone()
        return self._lora_preset_from_row(row)

    def update_lora_preset(self, preset_id: str, name: str, workflow: str, selected_loras: list[dict[str, Any]]) -> dict[str, Any] | None:
        """지정한 기존 조합만 갱신하고 없는 식별자는 새로 생성하지 않습니다."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE lora_presets SET name = ?, workflow = ?, loras_json = ?, updated_at = ? WHERE preset_id = ?",
                (name, workflow, json.dumps(selected_loras, ensure_ascii=False), current_timestamp(), preset_id),
            )
            row = connection.execute("SELECT * FROM lora_presets WHERE preset_id = ?", (preset_id,)).fetchone()
        return self._lora_preset_from_row(row) if row else None

    def delete_lora_preset(self, preset_id: str) -> bool:
        """저장된 LoRA 조합을 삭제하고 실제 삭제 여부를 반환합니다."""

        with self._connect() as connection:
            result = connection.execute("DELETE FROM lora_presets WHERE preset_id = ?", (preset_id,))
        return result.rowcount > 0

    def _lora_preset_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """LoRA 조합 row를 화면과 API에서 사용할 응답으로 변환합니다."""

        return {
            "preset_id": row["preset_id"], "name": row["name"], "workflow": row["workflow"],
            "loras": json.loads(row["loras_json"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def add_job(self, job_id: str, workflow: str, description: str, requests: list[dict[str, Any]]) -> None:
        """공통 입력은 작업당 한 번, 확정 결과는 요청별로 같은 transaction에 저장합니다."""

        timestamp = current_timestamp()
        common_inputs, selected_tags, _, _ = self._separate_request_detail(requests[0]["detail"] if requests else {})
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (job_id, workflow, request_count, created_at, description) VALUES (?, ?, ?, ?, ?)",
                (job_id, workflow, len(requests), timestamp, description),
            )
            connection.execute(
                "INSERT INTO job_inputs (job_id, input_json, selected_tags_json) VALUES (?, ?, ?)",
                (job_id, json.dumps(common_inputs, ensure_ascii=False), json.dumps(selected_tags, ensure_ascii=False)),
            )
            for request_index, request in enumerate(requests, start=1):
                request_inputs, request_tags, upload_id, resolved_result = self._separate_request_detail(request["detail"])
                if request_inputs != common_inputs or request_tags != selected_tags:
                    raise ValueError("같은 작업의 모든 요청은 공통 입력과 태그 후보가 같아야 합니다.")
                connection.execute(
                    "INSERT INTO job_requests "
                    "(request_id, job_id, request_index, prompt_id, status, output_stem, error_message, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request["request_id"], job_id, request_index, None, request["status"],
                        request["output_stem"],
                        None, timestamp, timestamp,
                    ),
                )
                connection.execute(
                    "INSERT INTO request_results (request_id, upload_id, result_json) VALUES (?, ?, ?)",
                    (request["request_id"], upload_id, json.dumps(resolved_result, ensure_ascii=False)),
                )

    def list_jobs(self, page: int = 1, page_size: int = 10, job_id: str = "") -> dict[str, Any]:
        """상위 작업을 페이지 단위로 조회하고 전체 활성 작업 수를 반환합니다."""

        filter_clause = " WHERE job_id = ?" if job_id else ""
        filter_values = (job_id,) if job_id else ()
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM jobs" + filter_clause, filter_values).fetchone()[0]
            active_count = connection.execute(
                "SELECT COUNT(DISTINCT job_id) FROM job_requests "
                "WHERE status IN ('submitting', 'pending', 'running', 'cancelling')"
            ).fetchone()[0]
            job_rows = connection.execute(
                "SELECT jobs.*, job_inputs.input_json FROM jobs JOIN job_inputs USING (job_id)" + filter_clause
                + " ORDER BY created_at DESC, jobs.rowid DESC LIMIT ? OFFSET ?",
                (*filter_values, page_size, (page - 1) * page_size),
            ).fetchall()
            request_rows = []
            if job_rows:
                placeholders = ",".join("?" for _ in job_rows)
                request_rows = connection.execute(
                    "SELECT job_requests.*, jobs.workflow, request_results.upload_id, request_results.result_json "
                    "FROM job_requests JOIN jobs USING (job_id) JOIN request_results USING (request_id) "
                    f"WHERE job_requests.job_id IN ({placeholders}) ORDER BY request_index",
                    tuple(row["job_id"] for row in job_rows),
                ).fetchall()
        requests_by_job: dict[str, list[dict[str, Any]]] = {row["job_id"]: [] for row in job_rows}
        for request_row in request_rows:
            requests_by_job[request_row["job_id"]].append(self._request_from_row(request_row))
        return {
            "items": [self._job_from_row(row, requests_by_job[row["job_id"]]) for row in job_rows],
            "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "active_count": active_count,
        }

    def count_active_jobs(self) -> int:
        """상세 Snapshot을 읽지 않고 활성 작업 수만 조회합니다."""

        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(DISTINCT job_id) FROM job_requests "
                "WHERE status IN ('submitting', 'pending', 'running', 'cancelling')"
            ).fetchone()[0]

    def list_job_summaries(self, page: int = 1, page_size: int = 10, job_id: str = "") -> dict[str, Any]:
        """공통 입력과 상태 집계만 읽으며 선택 후보 JSON은 읽지 않습니다."""

        filter_clause = " WHERE job_id = ?" if job_id else ""
        filter_values = (job_id,) if job_id else ()
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM jobs" + filter_clause, filter_values).fetchone()[0]
            job_rows = connection.execute(
                "SELECT jobs.*, job_inputs.input_json FROM jobs JOIN job_inputs USING (job_id)" + filter_clause
                + " ORDER BY created_at DESC, jobs.rowid DESC LIMIT ? OFFSET ?",
                (*filter_values, page_size, (page - 1) * page_size),
            ).fetchall()
            items = []
            for job_row in job_rows:
                status_rows = connection.execute(
                    "SELECT status, COUNT(*) AS request_count, MAX(updated_at) AS updated_at, "
                    "SUM(CASE WHEN status = 'cancelling' AND error_message IS NOT NULL THEN 1 ELSE 0 END) "
                    "AS cancellation_failures FROM job_requests WHERE job_id = ? GROUP BY status",
                    (job_row["job_id"],),
                ).fetchall()
                status_counts = {row["status"]: row["request_count"] for row in status_rows}
                first_request = connection.execute(
                    "SELECT json_extract(result_json, '$.settings') AS resolved_settings "
                    "FROM job_requests JOIN request_results USING (request_id) "
                    "WHERE job_id = ? ORDER BY request_index LIMIT 1",
                    (job_row["job_id"],),
                ).fetchone()
                common_inputs = json.loads(job_row["input_json"])
                summary_detail = {}
                for detail_key in ("body", "settings", "loras", "lora_preset_name"):
                    if detail_key in common_inputs:
                        summary_detail[detail_key] = common_inputs[detail_key]
                resolved_settings = None
                if first_request and first_request["resolved_settings"]:
                    resolved_settings = json.loads(first_request["resolved_settings"])
                if resolved_settings:
                    summary_detail["resolved"] = {"settings": resolved_settings}
                items.append({
                    "job_id": job_row["job_id"], "workflow": job_row["workflow"],
                    "description": job_row["description"], "request_count": job_row["request_count"],
                    "created_at": job_row["created_at"],
                    "updated_at": max((row["updated_at"] for row in status_rows), default=job_row["created_at"]),
                    "deletion_protected": bool(job_row["deletion_protected"]),
                    "cancellation_requested": bool(job_row["cancellation_requested"]),
                    "cancellation_failures": sum(row["cancellation_failures"] for row in status_rows),
                    "status": self._job_status(status_counts, job_row["request_count"]),
                    "status_counts": status_counts, "summary": summary_detail,
                })
        return {
            "items": items, "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "active_count": self.count_active_jobs(),
        }

    def get_job_inputs(self, job_id: str) -> dict[str, Any] | None:
        """작업 단위 복원에 필요한 공통 입력과 체크 후보를 한 번만 읽습니다."""

        with self._connect() as connection:
            job_row = connection.execute(
                "SELECT jobs.*, job_inputs.input_json, job_inputs.selected_tags_json "
                "FROM jobs JOIN job_inputs USING (job_id) WHERE job_id = ?", (job_id,),
            ).fetchone()
            if job_row is None:
                return None
        inputs = json.loads(job_row["input_json"])
        inputs["selected_tags"] = json.loads(job_row["selected_tags_json"])
        return {
            "job_id": job_id, "workflow": job_row["workflow"], "description": job_row["description"],
            "request_count": job_row["request_count"],
            "inputs": inputs,
        }

    def list_deletable_job_ids(self, job_id: str = "") -> list[str]:
        """모든 페이지에서 보호되지 않고 활성 요청이 없는 작업 ID를 반환합니다."""

        filter_clause = " AND jobs.job_id = ?" if job_id else ""
        filter_values = (job_id,) if job_id else ()
        with self._connect() as connection:
            job_rows = connection.execute(
                "SELECT jobs.job_id FROM jobs WHERE jobs.deletion_protected = 0 "
                "AND NOT EXISTS (SELECT 1 FROM job_requests WHERE job_requests.job_id = jobs.job_id "
                "AND status IN ('submitting', 'pending', 'running', 'cancelling'))"
                + filter_clause + " ORDER BY jobs.created_at DESC, jobs.rowid DESC",
                filter_values,
            ).fetchall()
        return [job_row["job_id"] for job_row in job_rows]

    def set_job_deletion_protection(self, job_id: str, deletion_protected: bool) -> bool:
        """작업의 삭제 보호 설정을 저장하고 작업이 없으면 False를 반환합니다."""

        with self._connect() as connection:
            result = connection.execute(
                "UPDATE jobs SET deletion_protected = ? WHERE job_id = ?",
                (int(deletion_protected), job_id),
            )
        return result.rowcount > 0

    def find_output_requests(
        self, output_paths: list[str], *, output_timing: OutputTimingRecorder | None = None,
    ) -> dict[str, dict[str, Any]]:
        """현재 페이지 결과물의 원래 생성 경로를 작업과 요청 설정에 연결합니다."""

        if not output_paths:
            return {}
        placeholders = ",".join("?" for _ in output_paths)
        with measure_output_step(output_timing, "mapping_db_connect", emit=True):
            connection = self._connect()
        with connection:
            with measure_output_step(output_timing, "mapping_sql_execute", emit=True):
                output_cursor = connection.execute(
                    "SELECT job_requests.job_id, job_inputs.input_json, request_results.result_json, "
                    "output_path.value AS output_path FROM job_requests JOIN job_inputs USING (job_id) "
                    "JOIN request_results USING (request_id) "
                    "JOIN json_each(request_results.result_json, '$.output_paths') AS output_path "
                    f"WHERE output_path.value IN ({placeholders}) "
                    "ORDER BY job_requests.updated_at DESC",
                    tuple(output_paths),
                )
            with measure_output_step(output_timing, "mapping_sql_fetch", emit=True):
                rows = output_cursor.fetchall()
        requests_by_output_path = {}
        with measure_output_step(output_timing, "mapping_json_decode", emit=True):
            for row in rows:
                if row["output_path"] in requests_by_output_path:
                    continue
                resolved_result = json.loads(row["result_json"])
                settings = resolved_result.get("settings") or json.loads(row["input_json"]).get("settings", {})
                requests_by_output_path[row["output_path"]] = {
                    "job_id": row["job_id"], "settings": settings,
                }
        return requests_by_output_path

    def get_job(self, job_id: str, *, output_timing: OutputTimingRecorder | None = None) -> dict[str, Any] | None:
        """작업의 작은 공통 입력과 하위 요청 확정 결과만 조회합니다."""

        with measure_output_step(output_timing, "filter_db_connect", emit=True):
            connection = self._connect()
        with connection:
            with measure_output_step(output_timing, "filter_job_sql", emit=True):
                job_row = connection.execute(
                    "SELECT jobs.*, job_inputs.input_json FROM jobs JOIN job_inputs USING (job_id) WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            if job_row is None:
                return None
            with measure_output_step(output_timing, "filter_requests_sql", emit=True):
                request_rows = connection.execute(
                    "SELECT job_requests.*, jobs.workflow, request_results.upload_id, request_results.result_json "
                    "FROM job_requests JOIN jobs USING (job_id) JOIN request_results USING (request_id) "
                    "WHERE job_requests.job_id = ? ORDER BY request_index", (job_id,)
                ).fetchall()
        with measure_output_step(output_timing, "filter_job_json_decode", emit=True):
            requests = [self._request_from_row(row) for row in request_rows]
            return self._job_from_row(job_row, requests)

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """한 요청의 확정 결과와 작은 작업 공통 입력을 JOIN해서 조회합니다."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_requests.*, jobs.workflow, job_inputs.input_json, "
                "request_results.upload_id, request_results.result_json "
                "FROM job_requests JOIN jobs USING (job_id) JOIN job_inputs USING (job_id) "
                "JOIN request_results USING (request_id) "
                "WHERE request_id = ?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        request = self._request_from_row(row)
        request["inputs"] = json.loads(row["input_json"])
        return request

    def list_active_requests(self, limit: int | None = None, job_id: str = "") -> list[dict[str, Any]]:
        """감시·취소에 필요한 작은 상태만 읽고 선택 작업으로 범위를 제한할 수 있습니다."""

        with self._connect() as connection:
            filter_clause = " AND job_requests.job_id = ?" if job_id else ""
            limit_clause = " LIMIT ?" if limit is not None else ""
            query_values = []
            if job_id:
                query_values.append(job_id)
            if limit is not None:
                query_values.append(limit)
            rows = connection.execute(
                "SELECT request_id, job_id, prompt_id, status, updated_at, jobs.workflow "
                "FROM job_requests JOIN jobs USING (job_id) "
                "WHERE status IN ('submitting', 'pending', 'running', 'cancelling') "
                + filter_clause + " ORDER BY job_requests.created_at DESC" + limit_clause,
                tuple(query_values),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_submission_state(self, request_id: str) -> dict[str, Any] | None:
        """전송 전후의 취소 여부를 작은 row로 확인합니다."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_id, status, prompt_id FROM job_requests WHERE request_id = ?", (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def request_job_cancellation(self, job_id: str) -> int | None:
        """제출 중인 요청까지 취소 의도를 원자적으로 기록하고 대상 수를 반환합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone() is None:
                return None
            active_count = connection.execute(
                "SELECT COUNT(*) FROM job_requests WHERE job_id = ? "
                "AND status IN ('submitting', 'pending', 'running', 'cancelling')", (job_id,),
            ).fetchone()[0]
            if active_count:
                connection.execute("UPDATE jobs SET cancellation_requested = 1 WHERE job_id = ?", (job_id,))
                connection.execute(
                    "UPDATE job_requests SET status = 'cancelling', error_message = NULL, updated_at = ? "
                    "WHERE job_id = ? AND status IN ('submitting', 'pending', 'running')",
                    (current_timestamp(), job_id),
                )
        return active_count

    def cancel_unsubmitted_request(self, request_id: str) -> None:
        """제출 loop가 전송하지 않았다고 확인한 요청만 취소 완료로 기록합니다."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE job_requests SET status = 'cancelled', error_message = NULL, updated_at = ? "
                "WHERE request_id = ? AND prompt_id IS NULL AND status = 'cancelling'",
                (current_timestamp(), request_id),
            )

    def record_cancellation_error(self, request_ids: list[str], error_message: str | None) -> None:
        """취소 전송의 오류를 한 transaction으로 기록하고 terminal 상태는 보존합니다."""

        with self._connect() as connection:
            connection.executemany(
                "UPDATE job_requests SET error_message = ? WHERE request_id = ? AND status = 'cancelling'",
                [(error_message, request_id) for request_id in request_ids],
            )

    def apply_request_states(self, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """감시에서 확인한 상태를 묶어 저장하며 취소 의도를 queue 상태로 덮어쓰지 않습니다."""

        if not updates:
            return []
        timestamp = current_timestamp()
        applied_updates = []
        with self._connect() as connection:
            for update in updates:
                if update["status"] in {"pending", "running"}:
                    change_result = connection.execute(
                        "UPDATE job_requests SET status = ?, updated_at = ? WHERE request_id = ? "
                        "AND status IN ('pending', 'running') AND status != ?",
                        (update["status"], timestamp, update["request_id"], update["status"]),
                    )
                elif "output_paths" in update:
                    change_result = connection.execute(
                        "UPDATE job_requests SET status = 'completed', error_message = NULL, updated_at = ? "
                        "WHERE request_id = ? AND status IN ('pending', 'running', 'cancelling')",
                        (timestamp, update["request_id"]),
                    )
                    if change_result.rowcount:
                        connection.execute(
                            "UPDATE request_results SET result_json = json_set(result_json, '$.output_paths', json(?)) "
                            "WHERE request_id = ?",
                            (json.dumps(update["output_paths"], ensure_ascii=False), update["request_id"]),
                        )
                        OutputCatalog.register_request_outputs(connection, update["request_id"])
                else:
                    allowed_states = "('pending', 'running')" if update["status"] == "stopped" else "('pending', 'running', 'cancelling')"
                    change_result = connection.execute(
                        "UPDATE job_requests SET status = ?, error_message = ?, updated_at = ? "
                        f"WHERE request_id = ? AND status IN {allowed_states}",
                        (update["status"], update.get("error_message"), timestamp, update["request_id"]),
                    )
                if change_result.rowcount:
                    applied_updates.append(update)
        return applied_updates

    def update_request(self, request_id: str, status: str, error_message: str | None = None) -> None:
        """개별 요청의 상태와 오류를 갱신합니다."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE job_requests SET status = ?, error_message = ?, updated_at = ? WHERE request_id = ?",
                (status, error_message, current_timestamp(), request_id),
            )

    def mark_request_cancelling(self, request_id: str) -> bool:
        """대기·실행 중 요청에만 취소 진행 상태를 설정합니다."""

        with self._connect() as connection:
            result = connection.execute(
                "UPDATE job_requests SET status = 'cancelling', updated_at = ? "
                "WHERE request_id = ? AND status IN ('submitting', 'pending', 'running', 'cancelling')",
                (current_timestamp(), request_id),
            )
        return result.rowcount > 0

    def update_queue_state(self, request_id: str, status: str) -> None:
        """취소 중 상태를 덮어쓰지 않고 queue 상태만 반영합니다."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE job_requests SET status = ?, updated_at = ? "
                "WHERE request_id = ? AND status IN ('pending', 'running')",
                (status, current_timestamp(), request_id),
            )

    def delete_job(self, job_id: str, before_deletion: Callable[[], list[str] | None] | None = None) -> bool:
        """보호·활성 상태를 잠금 안에서 검사한 뒤 파일 처리와 이력 삭제를 수행합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute("SELECT deletion_protected FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job_row is None:
                return False
            if job_row["deletion_protected"]:
                raise ValueError("삭제 보호된 작업입니다. 보호를 해제한 뒤 삭제해 주세요.")
            active_count = connection.execute(
                "SELECT COUNT(*) FROM job_requests WHERE job_id = ? "
                "AND status IN ('submitting', 'pending', 'running', 'cancelling')",
                (job_id,),
            ).fetchone()[0]
            if active_count:
                raise ValueError("진행 중인 작업은 삭제할 수 없습니다.")
            if before_deletion is not None:
                removed_paths = before_deletion()
                if removed_paths:
                    connection.executemany(
                        "UPDATE output_files SET is_available=0 WHERE relative_path=?",
                        [(relative_path,) for relative_path in removed_paths],
                    )
            connection.execute("DELETE FROM job_requests WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        return True

    def complete_request(self, request_id: str, output_paths: list[str]) -> None:
        """완료 요청의 실제 출력 참조를 보관합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT result_json FROM request_results WHERE request_id = ?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("완료한 요청을 찾을 수 없습니다.")
            resolved_result = json.loads(row["result_json"])
            resolved_result["output_paths"] = output_paths
            connection.execute(
                "UPDATE job_requests SET status = ?, updated_at = ? WHERE request_id = ?",
                ("completed", current_timestamp(), request_id),
            )
            connection.execute("UPDATE request_results SET result_json = ? WHERE request_id = ?",
                               (json.dumps(resolved_result, ensure_ascii=False), request_id))
            OutputCatalog.register_request_outputs(connection, request_id, resolved_result)

    def set_request_accepted(self, request_id: str, prompt_id: str, resolved: dict[str, Any]) -> None:
        """ComfyUI 접수 ID와 확정 Prompt를 개별 요청에 기록합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM job_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise ValueError("접수한 요청을 찾을 수 없습니다.")
            connection.execute(
                "UPDATE job_requests SET prompt_id = ?, status = ?, updated_at = ? WHERE request_id = ?",
                (prompt_id, "cancelling" if row["status"] == "cancelling" else "pending",
                 current_timestamp(), request_id),
            )
            connection.execute("UPDATE request_results SET result_json = ? WHERE request_id = ?",
                               (json.dumps(resolved, ensure_ascii=False), request_id))

    def _preset_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """DB row를 preset 응답으로 변환합니다."""

        return {
            "preset_id": row["preset_id"], "name": row["name"], "workflow": row["workflow"],
            "version": row["version"], "body": json.loads(row["body_json"]),
            "updated_at": row["updated_at"],
        }

    def _request_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """DB row를 개별 요청 응답으로 변환합니다."""

        return {
            "request_id": row["request_id"], "job_id": row["job_id"], "workflow": row["workflow"],
            "request_index": row["request_index"], "prompt_id": row["prompt_id"],
            "status": row["status"], "output_stem": row["output_stem"],
            "upload_id": row["upload_id"], "result": json.loads(row["result_json"]),
            "error_message": row["error_message"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _job_from_row(self, row: sqlite3.Row, requests: list[dict[str, Any]]) -> dict[str, Any]:
        """요청 상태에서 상위 작업의 진행률과 최종 상태를 계산합니다."""

        status_counts: dict[str, int] = {}
        for request in requests:
            request_status = request["status"]
            status_counts[request_status] = status_counts.get(request_status, 0) + 1
        return {
            "job_id": row["job_id"], "workflow": row["workflow"],
            "inputs": json.loads(row["input_json"]),
            "description": row["description"],
            "deletion_protected": bool(row["deletion_protected"]),
            "cancellation_requested": bool(row["cancellation_requested"]),
            "request_count": row["request_count"], "created_at": row["created_at"],
            "updated_at": max((request["updated_at"] for request in requests), default=row["created_at"]),
            "status": self._job_status(status_counts, len(requests)), "status_counts": status_counts, "requests": requests,
        }

    def _job_status(self, status_counts: dict[str, int], request_count: int) -> str:
        """상태 집계만으로 상세 조회와 요약 조회의 동일한 작업 상태를 계산합니다."""

        if status_counts.get("running"):
            status = "running"
        elif status_counts.get("cancelling"):
            status = "cancelling"
        elif status_counts.get("pending"):
            status = "pending"
        elif status_counts.get("submitting"):
            status = "submitting"
        elif status_counts.get("completed") == request_count:
            status = "completed"
        elif status_counts.get("completed"):
            status = "partial"
        elif status_counts.get("cancelled") == request_count:
            status = "cancelled"
        elif status_counts.get("stopped") == request_count:
            status = "stopped"
        else:
            status = "failed"
        return status
