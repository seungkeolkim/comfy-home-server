"""Prompt 버전과 제출 작업을 SQLite에 보관합니다."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def current_timestamp() -> str:
    """UTC ISO 형식의 현재 시간을 반환합니다."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """요청마다 독립적인 SQLite 연결을 사용합니다."""

    def __init__(self, database_path: Path) -> None:
        """DB 위치를 기억하고 필요한 테이블을 만듭니다."""

        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS presets (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preset_versions (
                    preset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    PRIMARY KEY (preset_id, version)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    request_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    prompt_id TEXT,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_stem TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs(created_at DESC);
                CREATE TABLE IF NOT EXISTS lora_profiles (
                    file_name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (file_name, workflow)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """row 이름으로 결과를 읽는 SQLite 연결을 엽니다."""

        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
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

    def add_job(self, job: dict[str, Any]) -> None:
        """제출 결과와 요청 snapshot을 기록합니다."""

        timestamp = current_timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job["request_id"], job["batch_id"], job.get("prompt_id"), job["workflow"],
                    job["status"], job["output_stem"], json.dumps(job["detail"], ensure_ascii=False),
                    job.get("error_message"), timestamp, timestamp,
                ),
            )

    def list_jobs(self, limit: int = 200) -> list[dict[str, Any]]:
        """최근 작업과 제출 snapshot을 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def get_job(self, request_id: str) -> dict[str, Any] | None:
        """하나의 작업을 조회합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def update_job(self, request_id: str, status: str, error_message: str | None = None) -> None:
        """작업 상태와 오류를 갱신합니다."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? WHERE request_id = ?",
                (status, error_message, current_timestamp(), request_id),
            )

    def set_job_accepted(self, request_id: str, prompt_id: str, resolved: dict[str, Any]) -> None:
        """ComfyUI 접수 ID와 최종 Prompt 정보를 함께 기록합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT detail_json FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("접수한 작업을 찾을 수 없습니다.")
            detail = json.loads(row["detail_json"])
            detail["resolved"] = resolved
            connection.execute(
                "UPDATE jobs SET prompt_id = ?, status = ?, detail_json = ?, updated_at = ? WHERE request_id = ?",
                (prompt_id, "pending", json.dumps(detail, ensure_ascii=False), current_timestamp(), request_id),
            )

    def _preset_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """DB row를 preset 응답으로 변환합니다."""

        return {
            "preset_id": row["preset_id"], "name": row["name"], "workflow": row["workflow"],
            "version": row["version"], "body": json.loads(row["body_json"]),
            "updated_at": row["updated_at"],
        }

    def _job_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """DB row를 작업 응답으로 변환합니다."""

        return {
            "request_id": row["request_id"], "batch_id": row["batch_id"],
            "prompt_id": row["prompt_id"], "workflow": row["workflow"],
            "status": row["status"], "output_stem": row["output_stem"],
            "detail": json.loads(row["detail_json"]), "error_message": row["error_message"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
