"""하위 요청의 원본·태그 후보·확정 설정과 MiniMax 입력을 독립적으로 보관합니다."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .job_folders import JobFolderStore
from .minimax_inputs import MAX_INPUT_BYTES, read_input_dimensions, resolve_input_image


class RequestFavoriteStore:
    """원본 작업 삭제와 결과물 이동에 영향을 받지 않는 요청 Snapshot을 관리합니다."""

    def __init__(self, connection_factory: Callable, runtime_directory: Path) -> None:
        """같은 SQLite 연결과 즐겨찾기 전용 입력 보관 위치를 사용합니다."""

        self.connection_factory = connection_factory
        self.input_directory = runtime_directory / "favorite_inputs"

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """요청당 하나의 즐겨찾기와 여러 결과물의 안정적인 ID 연결을 준비합니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS request_favorites (favorite_id TEXT PRIMARY KEY, "
            "source_request_id TEXT NOT NULL UNIQUE, source_job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL, "
            "workflow TEXT NOT NULL, description TEXT NOT NULL, snapshot_json TEXT NOT NULL, "
            "input_asset_name TEXT, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS favorite_output_links (output_id INTEGER PRIMARY KEY "
            "REFERENCES output_files(output_id) ON DELETE CASCADE, "
            "favorite_id TEXT NOT NULL REFERENCES request_favorites(favorite_id) ON DELETE CASCADE)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS favorite_output_links_favorite ON favorite_output_links(favorite_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS request_favorites_job ON request_favorites(source_job_id)")

    def save_output(self, output_id: int, output_root: Path) -> dict[str, Any]:
        """확정된 요청과 입력 이미지를 먼저 검증하고 Snapshot 및 결과물 연결을 원자적으로 저장합니다."""

        created_input_path = None
        try:
            with self.connection_factory() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT favorite_id FROM favorite_output_links WHERE output_id=?", (output_id,),
                ).fetchone()
                if existing:
                    return {"favorite_id": existing["favorite_id"], "created": False}
                source = connection.execute(
                    "SELECT job_requests.*,jobs.workflow,jobs.description,job_inputs.input_json,output_files.seed AS output_seed,"
                    "job_inputs.selected_tags_json,request_results.result_json FROM output_files "
                    "JOIN job_requests USING(request_id) JOIN jobs ON jobs.job_id=job_requests.job_id "
                    "JOIN job_inputs ON job_inputs.job_id=jobs.job_id JOIN request_results USING(request_id) "
                    "WHERE output_files.output_id=? AND output_files.is_deleted=0", (output_id,),
                ).fetchone()
                if source is None:
                    raise LookupError("생성 요청이 남아 있는 결과물만 즐겨찾기에 저장할 수 있습니다.")
                existing = connection.execute(
                    "SELECT favorite_id FROM request_favorites WHERE source_request_id=?", (source["request_id"],),
                ).fetchone()
                if existing:
                    self.link_request_outputs(connection, source["request_id"], existing["favorite_id"])
                    return {"favorite_id": existing["favorite_id"], "created": False}
                resolved = json.loads(source["result_json"])
                original_inputs = json.loads(source["input_json"])
                if source["output_seed"] is not None:
                    resolved.setdefault("settings", {})["seed"] = int(source["output_seed"])
                if not isinstance(resolved.get("prompt"), str) or "seed" not in resolved.get("settings", {}):
                    raise ValueError("확정 Prompt와 Seed 기록이 없는 요청은 그대로 복원할 수 없습니다.")
                favorite_id = uuid.uuid4().hex
                input_asset_name = None
                if source["workflow"] == "minimax_h3":
                    source_image = resolved.get("source_image") or {}
                    image_row = connection.execute(
                        "SELECT relative_path FROM output_files WHERE output_id=? AND is_deleted=0 AND is_available=1",
                        (source_image.get("output_id"),),
                    ).fetchone()
                    if image_row is None:
                        raise ValueError("MiniMax 원본 입력 이미지가 없어 즐겨찾기에 보관할 수 없습니다.")
                    input_path = resolve_input_image(output_root, image_row["relative_path"])
                    if input_path.stat().st_size > MAX_INPUT_BYTES:
                        raise ValueError("입력 이미지 한 장은 50 MB 이하여야 합니다.")
                    read_input_dimensions(input_path)
                    input_asset_name = favorite_id + input_path.suffix.lower()
                    self.input_directory.mkdir(parents=True, exist_ok=True)
                    created_input_path = self.input_directory / input_asset_name
                    with input_path.open("rb") as source_file, created_input_path.open("xb") as destination_file:
                        shutil.copyfileobj(source_file, destination_file)
                snapshot = {
                    "inputs": original_inputs, "selected_tags": json.loads(source["selected_tags_json"]),
                    "resolved": resolved, "request_index": source["request_index"],
                    "source_job_id": source["job_id"],
                }
                connection.execute(
                    "INSERT INTO request_favorites (favorite_id,source_request_id,source_job_id,workflow,description,"
                    "snapshot_json,input_asset_name,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (favorite_id, source["request_id"], source["job_id"], source["workflow"], source["description"],
                     json.dumps(snapshot, ensure_ascii=False), input_asset_name,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                self.link_request_outputs(connection, source["request_id"], favorite_id)
                return {"favorite_id": favorite_id, "created": True}
        except Exception:
            if created_input_path is not None:
                created_input_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def link_request_outputs(connection: sqlite3.Connection, request_id: str, favorite_id: str) -> None:
        """같은 요청의 여러 결과물을 하나의 즐겨찾기로 연결합니다."""

        connection.execute(
            "INSERT OR IGNORE INTO favorite_output_links SELECT output_id,? FROM output_files WHERE request_id=?",
            (favorite_id, request_id),
        )

    def get(self, favorite_id: str) -> dict[str, Any]:
        """원본 이력이 삭제되어도 저장된 복원 자료를 반환합니다."""

        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT request_favorites.*,(SELECT folder_id FROM job_folder_assignments WHERE job_id=source_job_id) "
                "AS folder_id FROM request_favorites WHERE favorite_id=?", (favorite_id,),
            ).fetchone()
        if row is None:
            raise LookupError("즐겨찾기를 찾을 수 없습니다.")
        return {**json.loads(row["snapshot_json"]), **dict(row)}

    def delete(self, favorite_id: str) -> dict[str, bool]:
        """즐겨찾기와 전용 입력 복사본만 제거하고 원본 작업·결과물은 보존합니다."""

        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT input_asset_name FROM request_favorites WHERE favorite_id=?", (favorite_id,),
            ).fetchone()
            if row is None:
                raise LookupError("즐겨찾기를 찾을 수 없습니다.")
            connection.execute("DELETE FROM request_favorites WHERE favorite_id=?", (favorite_id,))
        if row["input_asset_name"]:
            (self.input_directory / row["input_asset_name"]).unlink(missing_ok=True)
        return {"deleted": True}

    def list_favorites(
        self, page: int, page_size: int, folder_id: str = "", job_id: str = "", request_id: str = "",
    ) -> dict[str, Any]:
        """현재 작업 분류와 조회 범위에서 요청당 한 건씩 작은 목록을 페이지 조회합니다."""

        with self.connection_factory() as connection:
            connection.execute("BEGIN")
            conditions = []
            parameters = []
            if folder_id == "unassigned":
                conditions.append("NOT EXISTS (SELECT 1 FROM job_folder_assignments WHERE job_id=source_job_id)")
            elif folder_id:
                job_filter, folder_parameters = JobFolderStore.build_job_filter(connection, folder_id=folder_id)
                conditions.append("source_job_id IN (SELECT jobs.job_id FROM jobs" + job_filter + ")")
                parameters.extend(folder_parameters)
            if job_id:
                conditions.append("source_job_id=?")
                parameters.append(job_id)
            if request_id:
                conditions.append("source_request_id=?")
                parameters.append(request_id)
            filter_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            total = connection.execute("SELECT COUNT(*) FROM request_favorites" + filter_clause, parameters).fetchone()[0]
            favorite_rows = connection.execute(
                "SELECT favorite_id,source_request_id,source_job_id,workflow,description,created_at FROM request_favorites"
                + filter_clause + " ORDER BY created_at DESC,favorite_id DESC LIMIT ? OFFSET ?",
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
            items = []
            for row in favorite_rows:
                preview = connection.execute(
                    "SELECT output_files.output_id,relative_path,requested_width,requested_height FROM favorite_output_links "
                    "JOIN output_files USING(output_id) WHERE favorite_id=? AND is_deleted=0 AND is_available=1 "
                    "ORDER BY output_files.output_id LIMIT 1", (row["favorite_id"],),
                ).fetchone()
                preview_file = None
                if preview:
                    output_path = Path(preview["relative_path"])
                    preview_file = {
                        "output_id": preview["output_id"], "path": preview["relative_path"], "name": output_path.name,
                        "kind": "video" if output_path.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"} else "image",
                        "width": preview["requested_width"], "height": preview["requested_height"],
                    }
                items.append({**dict(row), "file": preview_file})
        return {"items": items, "page": page, "total": total, "total_pages": max(1, (total + page_size - 1) // page_size)}

    def copy_input_for_submission(self, favorite: dict[str, Any], upload_directory: Path) -> str:
        """즐겨찾기 해제와 무관하게 접수된 요청이 실행되도록 입력을 임시 업로드로 복사합니다."""

        if not favorite["input_asset_name"]:
            raise ValueError("보관된 입력 이미지가 없습니다.")
        source_path = self.input_directory / favorite["input_asset_name"]
        upload_id = uuid.uuid4().hex
        destination_path = upload_directory / (upload_id + source_path.suffix)
        try:
            with source_path.open("rb") as source_file, destination_path.open("xb") as destination_file:
                shutil.copyfileobj(source_file, destination_file)
        except Exception:
            destination_path.unlink(missing_ok=True)
            raise
        return upload_id
