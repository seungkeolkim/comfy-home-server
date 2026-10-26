"""운영 DB와 분리된 백업 관리 및 읽기 전용 파일 진단을 제공합니다."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .database import DATABASE_SCHEMA_VERSION, current_timestamp
from .output_listing import MEDIA_EXTENSIONS


class DatabaseDescriptionInput(BaseModel):
    """백업 생성과 설명 수정에 같은 한 줄 입력 규칙을 적용합니다."""

    description: str = Field(default="", max_length=200)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        """설명 앞뒤 공백을 제거하고 여러 줄 입력을 거절합니다."""

        if "\n" in value or "\r" in value:
            raise ValueError("백업 설명은 한 줄로 입력해 주세요.")
        return value.strip()


class DatabaseRestoreInput(BaseModel):
    """사용자가 현재 DB 백업 여부를 확인했는지 검증합니다."""

    backup_confirmed: Literal[True]


class BackupDeletionInput(BaseModel):
    """휴지통 없는 백업 삭제의 명시적 확인을 검증합니다."""

    confirmed: Literal[True]


class AdministrationMaintenance:
    """복원 중 HTTP 요청과 비동기 상태 갱신의 진입을 제어합니다."""

    def __init__(self) -> None:
        """단일 서버 Event loop에서 사용할 복원 상태와 작업 수를 준비합니다."""

        self.restoring = False
        self.active_operations = 0
        self.idle = asyncio.Event()
        self.idle.set()

    @contextmanager
    def operation(self) -> Iterator[None]:
        """현재 요청을 추적하고 복원이 시작된 뒤의 새 요청은 거절합니다."""

        if self.restoring:
            raise HTTPException(503, "DB 복원 중입니다. 잠시 후 다시 시도해 주세요.")
        self.active_operations += 1
        self.idle.clear()
        try:
            yield
        finally:
            self.active_operations -= 1
            if not self.active_operations:
                self.idle.set()


def readonly_database(database_path: Path) -> sqlite3.Connection:
    """없는 파일을 생성하지 않는 읽기 전용 SQLite 연결을 엽니다."""

    return sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)


class AdministrationStore:
    """별도 DB에 백업 설명과 운영 DB 복원으로 지워지지 않는 이력을 보관합니다."""

    def __init__(self, database_path: Path) -> None:
        """운영 DB를 수정하지 않고 관리자용 테이블만 준비합니다."""

        self.operational_database_path = database_path
        self.database_path = database_path.parent / "administration.sqlite3"
        self.backup_directory = database_path.parent / "backups"
        self.backup_directory.mkdir(exist_ok=True)
        self.mutation_lock = threading.Lock()
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS database_backups (backup_id TEXT PRIMARY KEY, "
                "file_name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL, source TEXT NOT NULL, deleted_at TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS administration_history (operation_id TEXT PRIMARY KEY, "
                "action TEXT NOT NULL, backup_id TEXT, file_name TEXT, description TEXT NOT NULL, "
                "started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, error_message TEXT)"
            )
            connection.execute(
                "UPDATE administration_history SET status='interrupted',finished_at=?,"
                "error_message='서버가 종료되어 실행 결과를 확인하지 못했습니다.' WHERE status='running'",
                (current_timestamp(),),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """관리용 DB Transaction과 Windows 파일 Handle을 함께 정리합니다."""

        with closing(sqlite3.connect(self.database_path, timeout=15)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    def backup_path(self, file_name: str) -> Path:
        """관리 폴더 바로 아래의 일반 백업 파일만 허용합니다."""

        candidate = self.backup_directory / file_name
        if Path(file_name).name != file_name or candidate.is_symlink() or candidate.is_junction():
            raise ValueError("올바른 백업 파일 경로가 아닙니다.")
        if candidate.resolve().parent != self.backup_directory.resolve():
            raise ValueError("백업 폴더 밖의 파일에는 접근할 수 없습니다.")
        return candidate

    def discover_backups(self) -> None:
        """기존 백업 파일을 등록하되 수정한 설명과 삭제 이력은 보존합니다."""

        with self.connect() as connection:
            for backup_path in self.backup_directory.iterdir():
                if backup_path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
                    continue
                if backup_path.is_symlink() or not backup_path.is_file():
                    continue
                created_at = datetime.fromtimestamp(backup_path.stat().st_mtime, timezone.utc).isoformat()
                connection.execute(
                    "INSERT OR IGNORE INTO database_backups "
                    "(backup_id,file_name,created_at,source) VALUES (?,?,?,'existing')",
                    (uuid.uuid4().hex, backup_path.name, created_at),
                )

    def get_backup(self, backup_id: str) -> dict[str, Any]:
        """삭제되지 않은 백업의 관리 정보를 읽습니다."""

        with self.connect() as connection:
            backup = connection.execute(
                "SELECT * FROM database_backups WHERE backup_id=? AND deleted_at IS NULL", (backup_id,),
            ).fetchone()
        if backup is None:
            raise LookupError("백업을 찾을 수 없습니다.")
        return dict(backup)

    def list_backups(self) -> dict[str, Any]:
        """파일의 현재 schema version만 비교하며 전체 무결성 검사는 실행하지 않습니다."""

        with self.mutation_lock:
            return self._list_available_backups()

    def _list_available_backups(self) -> dict[str, Any]:
        """생성·삭제와 겹치지 않는 상태에서 파일과 관리 목록을 대조합니다."""

        self.discover_backups()
        with self.connect() as connection:
            backups = [dict(row) for row in connection.execute(
                "SELECT * FROM database_backups WHERE deleted_at IS NULL ORDER BY created_at DESC,rowid DESC",
            )]
        for backup in backups:
            backup.update({"schema_version": None, "size_bytes": None, "restorable": False, "unavailable_reason": ""})
            try:
                backup_path = self.backup_path(backup["file_name"])
                backup["size_bytes"] = backup_path.stat().st_size
                with closing(readonly_database(backup_path)) as connection:
                    backup["schema_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
                backup["restorable"] = backup["schema_version"] == DATABASE_SCHEMA_VERSION
                if not backup["restorable"]:
                    backup["unavailable_reason"] = "Schema version이 달라 복원할 수 없습니다."
            except (OSError, sqlite3.Error, ValueError):
                backup["unavailable_reason"] = "백업 파일을 읽을 수 없습니다."
        return {"items": backups, "current_schema_version": DATABASE_SCHEMA_VERSION}

    def start_operation(self, action: str, backup_id: str | None, file_name: str | None, description: str) -> str:
        """실행 전에 이력을 기록하여 중단된 작업도 추적할 수 있게 합니다."""

        operation_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO administration_history "
                "(operation_id,action,backup_id,file_name,description,started_at,status) VALUES (?,?,?,?,?,?,'running')",
                (operation_id, action, backup_id, file_name, description, current_timestamp()),
            )
        return operation_id

    def finish_operation(self, operation_id: str, error: Exception | None = None) -> None:
        """실행 결과와 실패 사유를 운영 DB와 독립적으로 저장합니다."""

        with self.connect() as connection:
            connection.execute(
                "UPDATE administration_history SET finished_at=?,status=?,error_message=? WHERE operation_id=?",
                (current_timestamp(), "failed" if error else "completed", str(error) if error else None, operation_id),
            )

    @contextmanager
    def mutation(self, action: str, backup: dict[str, Any]) -> Iterator[None]:
        """백업 변경을 직렬화하고 예외가 발생해도 실행 이력을 남깁니다."""

        if not self.mutation_lock.acquire(blocking=False):
            raise RuntimeError("다른 백업 작업이 진행 중입니다.")
        try:
            operation_id = self.start_operation(action, backup["backup_id"], backup["file_name"], backup["description"])
            try:
                yield
            except Exception as exception:
                self.finish_operation(operation_id, exception)
                raise
            else:
                self.finish_operation(operation_id)
        finally:
            self.mutation_lock.release()

    def create_backup(self, description: str) -> dict[str, Any]:
        """SQLite backup API로 운영 DB만 복사하고 관리 정보는 별도로 저장합니다."""

        backup_id = uuid.uuid4().hex
        backup = {"backup_id": backup_id, "file_name": f"home_server_manual_{backup_id}.sqlite3", "description": description}
        with self.mutation("backup", backup):
            backup_path = self.backup_path(backup["file_name"])
            try:
                with closing(readonly_database(self.operational_database_path)) as source:
                    with closing(sqlite3.connect(backup_path)) as destination:
                        source.backup(destination, progress=backup_deadline(time.monotonic() + 30))
                with self.connect() as connection:
                    connection.execute(
                        "INSERT INTO database_backups (backup_id,file_name,description,created_at,source) "
                        "VALUES (?,?,?,?,'manual')",
                        (backup_id, backup["file_name"], description, current_timestamp()),
                    )
            except Exception:
                backup_path.unlink(missing_ok=True)
                raise
        return self.get_backup(backup_id)

    def update_description(self, backup_id: str, description: str) -> dict[str, Any]:
        """백업 파일을 바꾸지 않고 관리용 DB의 설명만 수정합니다."""

        backup = self.get_backup(backup_id)
        with self.mutation("description", {**backup, "description": description}):
            with self.connect() as connection:
                connection.execute("UPDATE database_backups SET description=? WHERE backup_id=?", (description, backup_id))
        return self.get_backup(backup_id)

    def delete_backup(self, backup_id: str) -> dict[str, bool]:
        """백업 파일을 즉시 삭제하고 관리 정보에는 삭제 시각만 남깁니다."""

        backup = self.get_backup(backup_id)
        with self.mutation("delete", backup):
            self.backup_path(backup["file_name"]).unlink(missing_ok=True)
            with self.connect() as connection:
                connection.execute("UPDATE database_backups SET deleted_at=? WHERE backup_id=?", (current_timestamp(), backup_id))
        return {"deleted": True}

    def restore_backup(self, backup_id: str, ensure_idle: Callable[[], None]) -> dict[str, bool]:
        """동일 schema의 DB만 복원하며 파일·관리 이력·백업 파일은 변경하지 않습니다."""

        backup = self.get_backup(backup_id)
        with self.mutation("restore", backup):
            ensure_idle()
            with closing(readonly_database(self.backup_path(backup["file_name"]))) as source:
                if source.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
                    raise ValueError("Schema version이 달라 복원할 수 없습니다.")
                # 복원본의 진행 상태가 ComfyUI 재실행이나 취소로 이어지지 않도록 복사본에서 정리합니다.
                with closing(sqlite3.connect(":memory:")) as prepared:
                    source.backup(prepared, progress=backup_deadline(time.monotonic() + 30))
                    prepared.execute(
                        "UPDATE job_requests SET status='stopped',updated_at=?,"
                        "error_message='DB 복원으로 이전 실행 상태의 추적을 중단했습니다.' "
                        "WHERE status IN ('submitting','pending','running','cancelling')", (current_timestamp(),),
                    )
                    prepared.commit()
                    with closing(sqlite3.connect(self.operational_database_path, timeout=15)) as destination:
                        prepared.backup(destination, progress=backup_deadline(time.monotonic() + 30))
        return {"restored": True}

    def list_history(self, page: int) -> dict[str, Any]:
        """성공·실패·중단 이력을 삭제된 백업의 설명과 함께 페이지로 조회합니다."""

        with self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM administration_history").fetchone()[0]
            items = [dict(row) for row in connection.execute(
                "SELECT * FROM administration_history ORDER BY started_at DESC,rowid DESC LIMIT 25 OFFSET ?",
                ((page - 1) * 25,),
            )]
        return {"items": items, "page": page, "total": total, "total_pages": max(1, (total + 24) // 25)}


def backup_deadline(deadline: float) -> Callable:
    """SQLite Lock 대기가 무한히 이어지지 않도록 backup progress Callback을 만듭니다."""

    def check_deadline(status: int, remaining: int, total: int) -> None:
        """복사나 Lock 대기 시간이 제한을 넘으면 SQLite backup을 중단합니다."""

        if status != sqlite3.SQLITE_DONE and time.monotonic() > deadline:
            raise RuntimeError("DB 작업 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")

    return check_deadline


def scan_files(directory: Path, excluded_paths: set[Path] | None = None) -> tuple[dict[str, int], list[str]]:
    """Symlink와 Junction을 따라가지 않고 파일 크기와 접근 오류만 읽습니다."""

    files = {}
    errors = []
    pending_directories = [directory]
    while pending_directories:
        current_directory = pending_directories.pop()
        try:
            if current_directory.is_symlink() or current_directory.is_junction():
                continue
            if not current_directory.exists():
                continue
            with os.scandir(current_directory) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    if excluded_paths and entry_path in excluded_paths:
                        continue
                    if entry.is_symlink() or entry_path.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending_directories.append(entry_path)
                    elif entry.is_file(follow_symlinks=False):
                        files[entry_path.relative_to(directory).as_posix()] = entry.stat(follow_symlinks=False).st_size
        except OSError:
            errors.append(str(current_directory))
    return files, errors


def diagnose_connections(server: Any) -> dict[str, Any]:
    """복원 후 파일과 DB의 차이를 조회하며 Catalog나 실제 파일을 수정하지 않습니다."""

    output_files, output_errors = scan_files(server.config.managed_output_directory)
    physical_outputs = {name for name in output_files if Path(name).suffix.lower() in MEDIA_EXTENSIONS}
    input_files, input_errors = scan_files(server.config.runtime_directory / "favorite_inputs")
    with closing(readonly_database(server.database.database_path)) as connection:
        recorded_outputs = connection.execute("SELECT relative_path,is_deleted FROM output_files").fetchall()
        favorite_inputs = connection.execute(
            "SELECT input_asset_name FROM request_favorites WHERE input_asset_name IS NOT NULL",
        ).fetchall()
    known_outputs = {row[0] for row in recorded_outputs}
    expected_outputs = {row[0] for row in recorded_outputs if not row[1]}
    expected_inputs = {row[0] for row in favorite_inputs}
    findings = {
        "missing_outputs": expected_outputs - physical_outputs,
        "unregistered_outputs": physical_outputs - known_outputs,
        "deleted_outputs_present": {row[0] for row in recorded_outputs if row[1]} & physical_outputs,
        "missing_favorite_inputs": expected_inputs - input_files.keys(),
        "unreferenced_favorite_inputs": input_files.keys() - expected_inputs,
    }
    return {
        "checked_at": current_timestamp(), "access_errors": output_errors + input_errors,
        "findings": {name: {"total": len(paths), "paths": sorted(paths)[:100]} for name, paths in findings.items()},
    }


def storage_overview(server: Any) -> dict[str, Any]:
    """운영 폴더별 파일 크기와 해당 디스크 여유 공간을 요청 시에만 집계합니다."""

    runtime_directory = server.config.runtime_directory
    locations = [
        ("운영 DB", server.database.database_path),
        ("관리용 DB", server.administration.database_path),
        ("DB 백업", runtime_directory / "backups"),
        ("결과물", server.config.managed_output_directory),
        ("Preview cache", runtime_directory / "cache"),
        ("임시 입력", runtime_directory / "uploads"),
        ("즐겨찾기 입력", runtime_directory / "favorite_inputs"),
        ("로그", runtime_directory / "logs"),
    ]
    items = []
    classified_paths = set()
    for name, location in locations:
        classified_paths.add(location)
        try:
            if location.is_file():
                files, errors = {location.name: location.stat().st_size}, []
                for suffix in ("-wal", "-shm", "-journal"):
                    companion_path = location.with_name(location.name + suffix)
                    classified_paths.add(companion_path)
                    if companion_path.is_file() and not companion_path.is_symlink():
                        files[companion_path.name] = companion_path.stat().st_size
            else:
                files, errors = scan_files(location)
            disk_path = location if location.is_dir() else location.parent
            while not disk_path.exists():
                disk_path = disk_path.parent
            disk = shutil.disk_usage(disk_path)
            items.append({"name": name, "size_bytes": sum(files.values()), "file_count": len(files),
                          "disk_total_bytes": disk.total, "disk_free_bytes": disk.free, "access_errors": errors})
        except OSError:
            items.append({"name": name, "size_bytes": None, "file_count": None,
                          "disk_total_bytes": None, "disk_free_bytes": None, "access_errors": [str(location)]})
    remaining_files, remaining_errors = scan_files(runtime_directory, classified_paths)
    runtime_disk = shutil.disk_usage(runtime_directory)
    items.append({"name": "기타 runtime", "size_bytes": sum(remaining_files.values()), "file_count": len(remaining_files),
                  "disk_total_bytes": runtime_disk.total, "disk_free_bytes": runtime_disk.free, "access_errors": remaining_errors})
    return {"checked_at": current_timestamp(), "items": items}


async def administration_call(function: Callable, *arguments: Any) -> Any:
    """동기 관리자 작업을 Worker에서 실행하고 사용자에게 처리 가능한 오류를 전달합니다."""

    try:
        return await asyncio.to_thread(function, *arguments)
    except LookupError as exception:
        raise HTTPException(404, str(exception)) from exception
    except ValueError as exception:
        raise HTTPException(422, str(exception)) from exception
    except (OSError, sqlite3.Error, RuntimeError) as exception:
        raise HTTPException(409, str(exception)) from exception


def create_administration_router(server: Any) -> APIRouter:
    """기존 Session 인증 아래에서 수동 관리 기능만 등록합니다."""

    router = APIRouter(prefix="/api/administration")

    @router.get("/backups")
    async def list_database_backups():
        """Schema 호환 여부와 함께 백업 목록을 조회합니다."""

        return await administration_call(server.administration.list_backups)

    @router.post("/backups", status_code=201)
    async def create_database_backup(payload: DatabaseDescriptionInput):
        """운영 DB의 수동 백업을 생성합니다."""

        return await administration_call(server.administration.create_backup, payload.description)

    @router.patch("/backups/{backup_id}/description")
    async def update_backup_description(backup_id: str, payload: DatabaseDescriptionInput):
        """선택한 백업의 설명만 변경합니다."""

        return await administration_call(server.administration.update_description, backup_id, payload.description)

    @router.delete("/backups/{backup_id}")
    async def delete_database_backup(backup_id: str, payload: BackupDeletionInput):
        """확인된 백업을 휴지통 없이 즉시 삭제합니다."""

        return await administration_call(server.administration.delete_backup, backup_id)

    @router.post("/backups/{backup_id}/restore")
    async def restore_database_backup(backup_id: str, payload: DatabaseRestoreInput):
        """기존 작업이 끝난 뒤 다른 DB 접근을 막고 선택한 백업을 복원합니다."""

        maintenance = server.administration_maintenance
        if maintenance.restoring:
            raise HTTPException(409, "다른 DB 복원이 진행 중입니다.")
        maintenance.restoring = True
        try:
            try:
                await asyncio.wait_for(maintenance.idle.wait(), timeout=30)
            except TimeoutError as exception:
                raise HTTPException(409, "진행 중인 요청이 있어 복원할 수 없습니다. 잠시 후 다시 시도해 주세요.") from exception
            restore_task = asyncio.create_task(administration_call(
                server.administration.restore_backup, backup_id, server.ensure_restore_idle,
            ))
            try:
                result = await asyncio.shield(restore_task)
            except asyncio.CancelledError:
                # Worker가 DB를 쓰는 동안 Gate가 먼저 열리지 않도록 실제 완료를 기다립니다.
                await restore_task
                raise
            server.missing_request_since.clear()
            server.cancellation_retry_after.clear()
            return result
        finally:
            maintenance.restoring = False

    @router.get("/history")
    async def list_administration_history(page: int = Query(default=1, ge=1)):
        """백업·복원·삭제·설명 변경의 실행 이력을 조회합니다."""

        return await administration_call(server.administration.list_history, page)

    @router.post("/diagnostics")
    async def inspect_data_connections():
        """파일을 변경하지 않고 데이터 연결 상태만 검사합니다."""

        return await administration_call(diagnose_connections, server)

    @router.post("/storage")
    async def inspect_storage_usage():
        """삭제 기능 없이 현재 저장 공간 사용 현황을 조회합니다."""

        return await administration_call(storage_overview, server)

    return router
