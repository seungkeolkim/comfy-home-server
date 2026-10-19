"""실제 결과물 경로와 독립된 작업 분류와 소속을 관리합니다."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from typing import Any


class JobFolderStore:
    """최대 3단계 분류와 작업당 하나의 소속을 Transaction으로 유지합니다."""

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        """작업 저장소와 같은 DB 연결 설정을 사용합니다."""

        self.connection_factory = connection_factory

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """기존 작업 column을 변경하지 않고 분류 전용 테이블을 준비합니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS job_folders ("
            "folder_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "parent_id TEXT REFERENCES job_folders(folder_id) ON DELETE CASCADE)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS job_folders_sibling_name "
            "ON job_folders(COALESCE(parent_id, ''), name COLLATE NOCASE)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS job_folder_assignments ("
            "job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE, "
            "folder_id TEXT NOT NULL REFERENCES job_folders(folder_id) ON DELETE CASCADE)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS job_folder_assignments_folder ON job_folder_assignments(folder_id)"
        )

    @staticmethod
    def build_job_filter(
        connection: sqlite3.Connection, job_id: str = "", folder_id: str = "", search: str = "",
    ) -> tuple[str, list[str]]:
        """목록·전체 선택·삭제 후보에 같은 분류 및 설명 검색 범위를 적용합니다."""

        conditions = []
        parameters = []
        if job_id:
            conditions.append("jobs.job_id = ?")
            parameters.append(job_id)
        if folder_id == "unassigned":
            conditions.append("NOT EXISTS (SELECT 1 FROM job_folder_assignments WHERE job_id=jobs.job_id)")
        elif folder_id:
            if connection.execute("SELECT 1 FROM job_folders WHERE folder_id=?", (folder_id,)).fetchone() is None:
                raise LookupError("작업 분류를 찾을 수 없습니다.")
            conditions.append(
                "jobs.job_id IN (SELECT job_id FROM job_folder_assignments WHERE folder_id IN ("
                "WITH RECURSIVE descendants(folder_id) AS (SELECT folder_id FROM job_folders WHERE folder_id=? "
                "UNION ALL SELECT children.folder_id FROM job_folders children "
                "JOIN descendants ON children.parent_id=descendants.folder_id) SELECT folder_id FROM descendants))"
            )
            parameters.append(folder_id)
        if search.strip():
            conditions.append("instr(lower(jobs.description), lower(?)) > 0")
            parameters.append(search.strip())
        return (" WHERE " + " AND ".join(conditions) if conditions else ""), parameters

    @staticmethod
    def read_folder_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        """작은 분류 트리를 한 번 읽어 깊이·경로·하위 범위 계산에 재사용합니다."""

        return {row["folder_id"]: dict(row) for row in connection.execute("SELECT * FROM job_folders")}

    @staticmethod
    def descendant_identifiers(folders: dict[str, dict[str, Any]], folder_id: str) -> list[str]:
        """자기 자신을 포함한 모든 하위 분류를 순회합니다."""

        identifiers = [folder_id]
        pending_identifiers = [folder_id]
        while pending_identifiers:
            parent_identifier = pending_identifiers.pop()
            for folder in folders.values():
                if folder["parent_id"] == parent_identifier:
                    identifiers.append(folder["folder_id"])
                    pending_identifiers.append(folder["folder_id"])
        return identifiers

    @staticmethod
    def folder_path(folders: dict[str, dict[str, Any]], folder_id: str | None) -> list[str]:
        """루트부터 현재 분류까지 안정적인 식별자 경로를 반환합니다."""

        identifiers = []
        while folder_id is not None:
            if folder_id not in folders:
                raise LookupError("작업 분류를 찾을 수 없습니다.")
            identifiers.insert(0, folder_id)
            folder_id = folders[folder_id]["parent_id"]
        return identifiers

    def list_folders(self) -> dict[str, Any]:
        """하위 포함 작업 수와 분류 경로를 함께 반환합니다."""

        with self.connection_factory() as connection:
            connection.execute("BEGIN")
            folders = self.read_folder_rows(connection)
            direct_counts = dict(connection.execute(
                "SELECT folder_id, COUNT(*) FROM job_folder_assignments GROUP BY folder_id"
            ).fetchall())
            total_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        items = []
        for folder in folders.values():
            path_identifiers = self.folder_path(folders, folder["folder_id"])
            descendant_identifiers = self.descendant_identifiers(folders, folder["folder_id"])
            items.append({
                **folder, "depth": len(path_identifiers),
                "path": " / ".join(folders[identifier]["name"] for identifier in path_identifiers),
                "path_ids": path_identifiers,
                "job_count": sum(direct_counts.get(identifier, 0) for identifier in descendant_identifiers),
                "descendant_folder_count": len(descendant_identifiers) - 1,
            })
        items.sort(key=lambda folder: (folder["path"].casefold(), folder["folder_id"]))
        return {"items": items, "total_count": total_count, "unassigned_count": total_count - sum(direct_counts.values())}

    def save_folder(self, name: str, parent_id: str | None, folder_id: str | None = None) -> str:
        """동일 부모 이름·순환·하위 트리를 포함한 깊이를 검증하고 생성 또는 수정합니다."""

        name = name.strip()
        if not name or len(name) > 80 or any(character in name for character in "/\\\r\n\x00"):
            raise ValueError("분류 이름은 경로 구분자 없이 1~80자의 한 줄로 입력해 주세요.")
        identifier = folder_id or uuid.uuid4().hex
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            folders = self.read_folder_rows(connection)
            if folder_id is not None and folder_id not in folders:
                raise LookupError("작업 분류를 찾을 수 없습니다.")
            descendants = self.descendant_identifiers(folders, identifier) if folder_id else []
            if parent_id in descendants:
                raise ValueError("자기 자신이나 하위 분류 안으로 이동할 수 없습니다.")
            parent_depth = len(self.folder_path(folders, parent_id))
            subtree_height = 1
            if folder_id:
                original_depth = len(self.folder_path(folders, identifier))
                for descendant_id in descendants:
                    subtree_height = max(subtree_height, len(self.folder_path(folders, descendant_id)) - original_depth + 1)
            if parent_depth + subtree_height > 3:
                raise ValueError("작업 분류는 하위 분류를 포함해 최대 3단계까지 만들 수 있습니다.")
            try:
                connection.execute(
                    "INSERT INTO job_folders(folder_id,name,parent_id) VALUES (?,?,?) "
                    "ON CONFLICT(folder_id) DO UPDATE SET name=excluded.name,parent_id=excluded.parent_id",
                    (identifier, name, parent_id),
                )
            except sqlite3.IntegrityError as exception:
                raise ValueError("같은 위치에 같은 이름의 분류가 있습니다.") from exception
        return identifier

    def delete_folder(self, folder_id: str) -> dict[str, int]:
        """하위 분류와 소속만 제거해 작업·요청·결과물을 그대로 미분류 상태로 남깁니다."""

        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            folders = self.read_folder_rows(connection)
            if folder_id not in folders:
                raise LookupError("작업 분류를 찾을 수 없습니다.")
            identifiers = self.descendant_identifiers(folders, folder_id)
            placeholders = ",".join("?" for _ in identifiers)
            moved_count = connection.execute(
                f"SELECT COUNT(*) FROM job_folder_assignments WHERE folder_id IN ({placeholders})", identifiers,
            ).fetchone()[0]
            connection.execute("DELETE FROM job_folders WHERE folder_id=?", (folder_id,))
        return {"deleted_folder_count": len(identifiers), "moved_job_count": moved_count}

    @staticmethod
    def assign_jobs(connection: sqlite3.Connection, job_ids: list[str], folder_id: str | None) -> None:
        """모든 대상을 먼저 검증한 뒤 보호·진행 상태와 무관하게 소속만 변경합니다."""

        if folder_id is not None and connection.execute(
            "SELECT 1 FROM job_folders WHERE folder_id=?", (folder_id,),
        ).fetchone() is None:
            raise ValueError("작업 분류를 찾을 수 없습니다. 분류 목록을 새로 확인해 주세요.")
        for job_id in job_ids:
            if connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone() is None:
                raise LookupError("이동할 작업을 찾을 수 없습니다. 목록을 새로 확인해 주세요.")
        for job_id in job_ids:
            if folder_id is None:
                connection.execute("DELETE FROM job_folder_assignments WHERE job_id=?", (job_id,))
            else:
                connection.execute(
                    "INSERT INTO job_folder_assignments(job_id,folder_id) VALUES (?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET folder_id=excluded.folder_id", (job_id, folder_id),
                )

    def move_jobs(self, job_ids: list[str], folder_id: str | None) -> dict[str, int]:
        """중간 실패 시 전체 이동을 취소하도록 하나의 쓰기 Transaction을 사용합니다."""

        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assign_jobs(connection, list(dict.fromkeys(job_ids)), folder_id)
        return {"moved_job_count": len(set(job_ids))}
