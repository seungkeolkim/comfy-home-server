"""Prompt, LoRA 설정, 상위 작업과 개별 요청을 SQLite에 보관합니다."""

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
        """설정 데이터를 유지하고 작업 스키마를 현재 버전으로 전환합니다."""

        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema_version > 2:
                raise RuntimeError("지원하지 않는 DB 버전입니다.")
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
            if schema_version == 0:
                connection.execute("DROP TABLE IF EXISTS jobs")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    workflow TEXT NOT NULL,
                    request_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT ''
                )"""
            )
            if schema_version == 1:
                connection.execute("ALTER TABLE jobs ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS job_requests (
                    request_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    request_index INTEGER NOT NULL,
                    prompt_id TEXT,
                    status TEXT NOT NULL,
                    output_stem TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (job_id, request_index)
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs(created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS job_requests_job_id ON job_requests(job_id, request_index)")
            if schema_version < 2:
                connection.execute("PRAGMA user_version = 2")

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
        """상위 작업과 모든 하위 요청을 하나의 transaction으로 저장합니다."""

        timestamp = current_timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (job_id, workflow, request_count, created_at, description) VALUES (?, ?, ?, ?, ?)",
                (job_id, workflow, len(requests), timestamp, description),
            )
            for request_index, request in enumerate(requests, start=1):
                connection.execute(
                    "INSERT INTO job_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request["request_id"], job_id, request_index, None, request["status"],
                        request["output_stem"], json.dumps(request["detail"], ensure_ascii=False),
                        None, timestamp, timestamp,
                    ),
                )

    def list_jobs(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        """상위 작업을 페이지 단위로 조회하고 전체 활성 작업 수를 반환합니다."""

        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            active_count = connection.execute(
                "SELECT COUNT(DISTINCT job_id) FROM job_requests "
                "WHERE status IN ('submitting', 'pending', 'running', 'cancelling')"
            ).fetchone()[0]
            job_rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            request_rows = []
            if job_rows:
                placeholders = ",".join("?" for _ in job_rows)
                request_rows = connection.execute(
                    "SELECT job_requests.*, jobs.workflow FROM job_requests JOIN jobs USING (job_id) "
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

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """한 상위 작업과 하위 요청을 조회합니다."""

        with self._connect() as connection:
            job_row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job_row is None:
                return None
            request_rows = connection.execute(
                "SELECT job_requests.*, jobs.workflow FROM job_requests JOIN jobs USING (job_id) "
                "WHERE job_requests.job_id = ? ORDER BY request_index", (job_id,)
            ).fetchall()
        return self._job_from_row(job_row, [self._request_from_row(row) for row in request_rows])

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """한 ComfyUI 요청을 조회합니다."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_requests.*, jobs.workflow FROM job_requests JOIN jobs USING (job_id) "
                "WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._request_from_row(row) if row else None

    def list_active_requests(self, limit: int = 1000) -> list[dict[str, Any]]:
        """아직 제출 중이거나 ComfyUI 상태를 기다리는 요청을 반환합니다."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_requests.*, jobs.workflow FROM job_requests JOIN jobs USING (job_id) "
                "WHERE status IN ('submitting', 'pending', 'running', 'cancelling') "
                "ORDER BY job_requests.created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._request_from_row(row) for row in rows]

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
                "WHERE request_id = ? AND status IN ('pending', 'running')",
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

    def delete_job(self, job_id: str) -> bool:
        """활성 요청이 없는 작업의 하위 요청과 이력을 함께 삭제합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job_row is None:
                return False
            active_count = connection.execute(
                "SELECT COUNT(*) FROM job_requests WHERE job_id = ? "
                "AND status IN ('submitting', 'pending', 'running', 'cancelling')",
                (job_id,),
            ).fetchone()[0]
            if active_count:
                raise ValueError("진행 중인 작업은 삭제할 수 없습니다.")
            connection.execute("DELETE FROM job_requests WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        return True

    def complete_request(self, request_id: str, output_paths: list[str]) -> None:
        """완료 요청의 실제 출력 참조를 보관합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT detail_json FROM job_requests WHERE request_id = ?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("완료한 요청을 찾을 수 없습니다.")
            detail = json.loads(row["detail_json"])
            detail.setdefault("resolved", {})["output_paths"] = output_paths
            connection.execute(
                "UPDATE job_requests SET status = ?, detail_json = ?, updated_at = ? WHERE request_id = ?",
                ("completed", json.dumps(detail, ensure_ascii=False), current_timestamp(), request_id),
            )

    def set_request_accepted(self, request_id: str, prompt_id: str, resolved: dict[str, Any]) -> None:
        """ComfyUI 접수 ID와 확정 Prompt를 개별 요청에 기록합니다."""

        with self._connect() as connection:
            row = connection.execute("SELECT detail_json FROM job_requests WHERE request_id = ?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("접수한 요청을 찾을 수 없습니다.")
            detail = json.loads(row["detail_json"])
            detail["resolved"] = resolved
            connection.execute(
                "UPDATE job_requests SET prompt_id = ?, status = ?, detail_json = ?, updated_at = ? WHERE request_id = ?",
                (prompt_id, "pending", json.dumps(detail, ensure_ascii=False), current_timestamp(), request_id),
            )

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
            "detail": json.loads(row["detail_json"]), "error_message": row["error_message"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _job_from_row(self, row: sqlite3.Row, requests: list[dict[str, Any]]) -> dict[str, Any]:
        """요청 상태에서 상위 작업의 진행률과 최종 상태를 계산합니다."""

        status_counts: dict[str, int] = {}
        for request in requests:
            request_status = request["status"]
            status_counts[request_status] = status_counts.get(request_status, 0) + 1
        if status_counts.get("running"):
            status = "running"
        elif status_counts.get("cancelling"):
            status = "cancelling"
        elif status_counts.get("pending"):
            status = "pending"
        elif status_counts.get("submitting"):
            status = "submitting"
        elif status_counts.get("completed") == len(requests):
            status = "completed"
        elif status_counts.get("completed"):
            status = "partial"
        elif status_counts.get("cancelled") == len(requests):
            status = "cancelled"
        elif status_counts.get("stopped") == len(requests):
            status = "stopped"
        else:
            status = "failed"
        return {
            "job_id": row["job_id"], "workflow": row["workflow"],
            "description": row["description"],
            "request_count": row["request_count"], "created_at": row["created_at"],
            "updated_at": max((request["updated_at"] for request in requests), default=row["created_at"]),
            "status": status, "status_counts": status_counts, "requests": requests,
        }
