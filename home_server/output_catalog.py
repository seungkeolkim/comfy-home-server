"""기존 요청 JSON을 보존하면서 결과물 목록용 column과 index를 관리합니다."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .job_folders import JobFolderStore
from .output_listing import (
    IMAGE_OUTPUT_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_OUTPUT_EXTENSIONS,
    iterate_output_directory_entries, output_filename_metadata,
)
from .output_timing import OutputTimingRecorder, measure_output_step


OUTPUT_SORT_ORDER = "generated_at DESC, length(seed) DESC, seed DESC, relative_path DESC"
LOGGER = logging.getLogger(__name__)
INPUT_IMAGE_FILTER = "(" + " OR ".join(
    "lower(relative_path) LIKE '%" + extension + "'" for extension in sorted(IMAGE_OUTPUT_EXTENSIONS)
) + ")"


def normalized_output_path(relative_path: str) -> str | None:
    """JSON에 남은 경로를 검증하고 관리 상대 경로와 미디어 확장자만 허용합니다."""

    if not isinstance(relative_path, str):
        return None
    normalized_path = relative_path.replace("\\", "/")
    path_components = normalized_path.split("/")
    if normalized_path.startswith("/") or ":" in path_components[0]:
        return None
    if any(component in {"", ".", ".."} for component in path_components):
        return None
    if Path(normalized_path).suffix.lower() not in MEDIA_EXTENSIONS:
        return None
    return normalized_path


def requested_dimensions(settings: dict[str, Any]) -> tuple[int | None, int | None]:
    """요청 해상도를 양수 integer로 바꾸고 값이 불완전하면 미상으로 남깁니다."""

    try:
        width = int(settings["width"])
        height = int(settings["height"])
    except (KeyError, TypeError, ValueError):
        return None, None
    return (width, height) if min(width, height) > 0 else (None, None)


def output_neighbor_condition(current_row: sqlite3.Row, direction: str) -> tuple[str, list[Any]]:
    """목록의 내림차순과 NULL 순서를 유지하는 인접 Cursor 조건을 구성합니다."""

    cursor_columns = ("generated_at", "length(seed)", "seed", "relative_path")
    cursor_values = (current_row["generated_at"], current_row["seed_length"], current_row["seed"], current_row["relative_path"])
    alternatives = []
    parameters = []
    equal_conditions = []
    equal_values = []
    for column, value in zip(cursor_columns, cursor_values):
        comparison = None
        comparison_values = []
        if value is None:
            if direction == "previous":
                comparison = f"{column} IS NOT NULL"
        else:
            comparison = f"{column} > ?" if direction == "previous" else f"({column} < ? OR {column} IS NULL)"
            comparison_values.append(value)
        if comparison is not None:
            alternatives.append("(" + " AND ".join([*equal_conditions, comparison]) + ")")
            parameters.extend([*equal_values, *comparison_values])
        equal_conditions.append(f"{column} IS ?")
        equal_values.append(value)
    return "(" + " OR ".join(alternatives) + ")", parameters


class OutputCatalog:
    """파일당 한 행을 유지하고 일반 목록 요청은 FS·JSON 없이 조회합니다."""

    def __init__(self, database_path: Path) -> None:
        """기존 작업 DB와 같은 DB 파일을 사용합니다."""

        self.database_path = database_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """FK와 row 이름을 설정하고 transaction 및 connection을 확실히 정리합니다."""

        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """원래 JSON과 독립된 결과물 column 및 목록·필터용 index를 만듭니다."""

        connection.execute(
            """CREATE TABLE IF NOT EXISTS output_files (
                output_id INTEGER PRIMARY KEY,
                original_relative_path TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                request_id TEXT REFERENCES job_requests(request_id) ON DELETE SET NULL,
                job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
                generated_at REAL,
                seed TEXT,
                requested_width INTEGER,
                requested_height INTEGER,
                is_available INTEGER NOT NULL DEFAULT 1,
                is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1))
            )"""
        )
        output_columns = {column[1] for column in connection.execute("PRAGMA table_info(output_files)")}
        if "is_deleted" not in output_columns:
            connection.execute(
                "ALTER TABLE output_files ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0 "
                "CHECK (is_deleted IN (0, 1))"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS output_files_deleted_original "
            "ON output_files (request_id, original_relative_path) WHERE is_deleted=1"
        )
        # Seed는 unsigned 64-bit도 보존하도록 decimal 문자열과 길이로 정렬합니다.
        for index_name, filter_column in (
            ("output_files_listing", ""),
            ("output_files_job_listing", "job_id, "),
            ("output_files_request_listing", "request_id, "),
        ):
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON output_files "
                f"({filter_column}{OUTPUT_SORT_ORDER}) WHERE is_available = 1"
            )

    @staticmethod
    def _store_output(
        connection: sqlite3.Connection,
        relative_path: str,
        request_id: str | None = None,
        job_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """파일명 metadata를 최초 등록 때 읽고 같은 경로의 최신 생성 요청을 반영합니다."""

        generated_at, generation_seed = output_filename_metadata(Path(relative_path))
        connection.execute(
            "INSERT INTO output_files (original_relative_path,relative_path,request_id,job_id,"
            "generated_at,seed,requested_width,requested_height,is_available) VALUES (?,?,?,?,?,?,?,?,1) "
            "ON CONFLICT(relative_path) DO UPDATE SET original_relative_path=excluded.original_relative_path,"
            "request_id=excluded.request_id,job_id=excluded.job_id,generated_at=excluded.generated_at,"
            "seed=excluded.seed,requested_width=excluded.requested_width,"
            "requested_height=excluded.requested_height,is_available=1 WHERE output_files.is_deleted=0",
            (
                relative_path, relative_path, request_id, job_id, generated_at,
                str(generation_seed) if generation_seed is not None else None, width, height,
            ),
        )

    @staticmethod
    def register_request_outputs(
        connection: sqlite3.Connection,
        request_id: str,
        resolved_result: dict[str, Any] | None = None,
    ) -> None:
        """요청 완료 transaction 안에서 결과 JSON을 유지한 채 목록용 값을 추가 저장합니다."""

        request_row = connection.execute(
            "SELECT job_requests.job_id,request_results.result_json,job_inputs.input_json "
            "FROM job_requests JOIN request_results USING(request_id) JOIN job_inputs USING(job_id) "
            "WHERE request_id=?", (request_id,),
        ).fetchone()
        if request_row is None:
            return
        if resolved_result is None:
            resolved_result = json.loads(request_row["result_json"])
        settings = resolved_result.get("settings") or json.loads(request_row["input_json"]).get("settings", {})
        width, height = requested_dimensions(settings)
        for output_path in resolved_result.get("output_paths", []):
            relative_path = normalized_output_path(output_path)
            if relative_path is not None:
                deleted_original = connection.execute(
                    "SELECT 1 FROM output_files WHERE request_id=? AND original_relative_path=? AND is_deleted=1",
                    (request_id, relative_path),
                ).fetchone()
                if deleted_original is not None:
                    continue
                OutputCatalog._store_output(
                    connection, relative_path, request_id, request_row["job_id"], width, height,
                )

    @staticmethod
    def backfill_from_requests(connection: sqlite3.Connection) -> None:
        """기존 JSON을 한 번 읽어 column을 채우고 중복 경로는 최신 요청으로 연결합니다."""

        backfill_started_at = time.perf_counter()
        source_rows = connection.execute(
            "SELECT job_requests.request_id,request_results.result_json FROM job_requests "
            "JOIN request_results USING(request_id) ORDER BY job_requests.updated_at ASC"
        ).fetchall()
        for source_row in source_rows:
            resolved_result = json.loads(source_row["result_json"])
            if resolved_result.get("output_paths"):
                OutputCatalog.register_request_outputs(connection, source_row["request_id"], resolved_result)
        LOGGER.info(
            "OUTPUT_CATALOG event=backfill requests=%s elapsed_ms=%.3f",
            len(source_rows), (time.perf_counter() - backfill_started_at) * 1000,
        )

    def synchronize(self, managed_directory: Path) -> dict[str, int]:
        """서버 시작·수동 새로고침 때 FS 목록을 대조하며 실제 해상도·크기는 읽지 않습니다."""

        scan_started_at = time.perf_counter()
        physical_paths = set()
        for directory_entry in iterate_output_directory_entries(managed_directory):
            output_path = Path(directory_entry.path)
            if directory_entry.is_file(follow_symlinks=False) and output_path.suffix.lower() in MEDIA_EXTENSIONS:
                physical_paths.add(output_path.relative_to(managed_directory).as_posix())
        scan_elapsed_ms = (time.perf_counter() - scan_started_at) * 1000
        synchronization_started_at = time.perf_counter()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            recorded_rows = connection.execute("SELECT relative_path,is_available,is_deleted FROM output_files").fetchall()
            known_paths = set()
            deleted_paths = set()
            availability_updates = []
            for recorded_row in recorded_rows:
                relative_path = recorded_row["relative_path"]
                known_paths.add(relative_path)
                if recorded_row["is_deleted"]:
                    deleted_paths.add(relative_path)
                is_available = int(relative_path in physical_paths and not recorded_row["is_deleted"])
                if is_available != recorded_row["is_available"]:
                    availability_updates.append((is_available, relative_path))
            connection.executemany(
                "UPDATE output_files SET is_available=? WHERE relative_path=?", availability_updates,
            )
            new_paths = physical_paths - known_paths
            for relative_path in sorted(new_paths):
                self._store_output(connection, relative_path)
        synchronization_result = {
            "available": len(physical_paths - deleted_paths),
            "added": len(new_paths),
            "availability_changes": len(availability_updates),
        }
        LOGGER.info(
            "OUTPUT_CATALOG event=sync available=%s added=%s availability_changes=%s "
            "scan_ms=%.3f database_ms=%.3f",
            synchronization_result["available"], len(new_paths), len(availability_updates), scan_elapsed_ms,
            (time.perf_counter() - synchronization_started_at) * 1000,
        )
        return synchronization_result

    @staticmethod
    def build_output_folder_filter(connection: sqlite3.Connection, folder_id: str) -> tuple[str, list[str]]:
        """작업 분류의 하위 범위를 재사용하며 이력 없는 결과물도 미분류에 포함합니다."""

        if not folder_id:
            return "", []
        if folder_id == "unassigned":
            return (
                " AND NOT EXISTS (SELECT 1 FROM job_folder_assignments "
                "WHERE job_folder_assignments.job_id=output_files.job_id)", []
            )
        job_filter, parameters = JobFolderStore.build_job_filter(connection, folder_id=folder_id)
        return " AND output_files.job_id IN (SELECT jobs.job_id FROM jobs" + job_filter + ")", parameters

    def list_files(
        self,
        page: int,
        page_size: int,
        prefix: str = "",
        job_id: str = "",
        request_id: str = "",
        output_timing: OutputTimingRecorder | None = None,
        folder_id: str = "",
    ) -> dict[str, Any]:
        """JSON을 읽지 않고 index에서 필터·정렬·pagination 및 요청 해상도를 조회합니다."""

        conditions = ["is_available = 1", "is_deleted = 0"]
        query_values = []
        if job_id:
            conditions.append("job_id = ?")
            query_values.append(job_id)
        if request_id:
            conditions.append("request_id = ?")
            query_values.append(request_id)
        if prefix:
            # 기존 startswith와 같이 대소문자·wildcard 문자를 그대로 비교합니다.
            conditions.append("substr(relative_path, 1, ?) = ?")
            query_values.extend((len(prefix), prefix))
        filter_clause = " AND ".join(conditions)
        with self._connect() as connection:
            connection.execute("BEGIN")
            folder_condition, folder_parameters = self.build_output_folder_filter(connection, folder_id)
            filter_clause += folder_condition
            query_values.extend(folder_parameters)
            with measure_output_step(output_timing, "catalog_filter_validation", emit=True):
                if job_id and connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone() is None:
                    raise LookupError("작업을 찾을 수 없습니다.")
                if request_id and connection.execute("SELECT 1 FROM job_requests WHERE request_id=?", (request_id,)).fetchone() is None:
                    raise LookupError("요청을 찾을 수 없습니다.")
            with measure_output_step(output_timing, "catalog_count", emit=True):
                total = connection.execute(
                    f"SELECT COUNT(*) FROM output_files WHERE {filter_clause}", query_values,
                ).fetchone()[0]
            with measure_output_step(output_timing, "catalog_page_query", emit=True):
                page_rows = connection.execute(
                    "SELECT output_id,relative_path,generated_at,seed,job_id,request_id,requested_width,requested_height,"
                    "(SELECT favorite_id FROM favorite_output_links WHERE favorite_output_links.output_id=output_files.output_id) "
                    "AS favorite_id,"
                    "COALESCE((SELECT deletion_protected FROM jobs WHERE jobs.job_id=output_files.job_id),0) "
                    "AS deletion_protected "
                    f"FROM output_files WHERE {filter_clause} ORDER BY {OUTPUT_SORT_ORDER} LIMIT ? OFFSET ?",
                    (*query_values, page_size, (page - 1) * page_size),
                ).fetchall()
        page_files = []
        for page_row in page_rows:
            output_path = Path(page_row["relative_path"])
            width, height = page_row["requested_width"], page_row["requested_height"]
            is_video = output_path.suffix.lower() in VIDEO_OUTPUT_EXTENSIONS
            generation_seed = int(page_row["seed"]) if page_row["seed"] is not None else None
            page_files.append({
                "output_id": page_row["output_id"],
                "path": page_row["relative_path"],
                "name": output_path.name,
                "generated_at": page_row["generated_at"],
                "seed": generation_seed,
                "kind": "video" if is_video else "image",
                "job_id": page_row["job_id"],
                "request_id": page_row["request_id"], "favorite_id": page_row["favorite_id"],
                "deletion_protected": bool(page_row["deletion_protected"]),
                "width": width,
                "height": height,
                "dimensions_source": "settings" if width and height else None,
            })
        return {
            "files": page_files, "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_file_neighbors(
        self, output_id: int, job_id: str = "", request_id: str = "", prefix: str = "",
        folder_id: str = "",
        favorite_id: str = "",
    ) -> dict[str, dict[str, Any] | None]:
        """현재 파일의 보호 상태와 같은 범위의 인접 파일을 페이지·FS·이력 JSON 없이 읽습니다."""

        conditions = ["is_available=1", "is_deleted=0"]
        parameters = []
        if job_id:
            conditions.append("job_id=?")
            parameters.append(job_id)
        if request_id:
            conditions.append("request_id=?")
            parameters.append(request_id)
        if favorite_id:
            conditions.append("output_id IN (SELECT output_id FROM favorite_output_links WHERE favorite_id=?)")
            parameters.append(favorite_id)
        if prefix:
            conditions.append("substr(relative_path,1,?)=?")
            parameters.extend((len(prefix), prefix))
        filter_clause = " AND ".join(conditions)
        neighbors = {"previous": None, "next": None}
        with self._connect() as connection:
            connection.execute("BEGIN")
            folder_condition, folder_parameters = self.build_output_folder_filter(connection, folder_id)
            filter_clause += folder_condition
            parameters.extend(folder_parameters)
            current_row = connection.execute(
                "SELECT generated_at,length(seed) AS seed_length,seed,relative_path,"
                "COALESCE((SELECT deletion_protected FROM jobs WHERE jobs.job_id=output_files.job_id),0) AS deletion_protected "
                f"FROM output_files WHERE {filter_clause} AND output_id=?",
                [*parameters, output_id],
            ).fetchone()
            if current_row is None:
                raise LookupError("현재 조회 범위에서 결과물을 찾을 수 없습니다. 목록을 새로고침해 주세요.")
            current_path = Path(current_row["relative_path"])
            neighbors["current"] = {
                "output_id": output_id, "path": current_row["relative_path"], "name": current_path.name,
                "kind": "video" if current_path.suffix.lower() in VIDEO_OUTPUT_EXTENSIONS else "image",
                "deletion_protected": bool(current_row["deletion_protected"]),
            }
            for direction in ("previous", "next"):
                cursor_condition, cursor_parameters = output_neighbor_condition(current_row, direction)
                sort_order = OUTPUT_SORT_ORDER.replace("DESC", "ASC") if direction == "previous" else OUTPUT_SORT_ORDER
                neighbor_row = connection.execute(
                    f"SELECT output_id,relative_path FROM output_files WHERE {filter_clause} AND {cursor_condition} ORDER BY {sort_order} LIMIT 1",
                    [*parameters, *cursor_parameters],
                ).fetchone()
                if neighbor_row is not None:
                    output_path = Path(neighbor_row["relative_path"])
                    neighbors[direction] = {
                        "output_id": neighbor_row["output_id"], "path": neighbor_row["relative_path"], "name": output_path.name,
                        "kind": "video" if output_path.suffix.lower() in VIDEO_OUTPUT_EXTENSIONS else "image",
                    }
        return neighbors

    def get_video_source(self, output_id: int) -> dict[str, Any]:
        """영상의 최신 현재 경로를 조회하고 삭제·미등록·다른 종류의 결과물을 거부합니다."""

        with self._connect() as connection:
            output_row = connection.execute(
                "SELECT output_id,relative_path,is_deleted FROM output_files WHERE output_id=?", (output_id,),
            ).fetchone()
        if output_row is None or output_row["is_deleted"]:
            raise FileNotFoundError("영상을 찾을 수 없습니다.")
        if Path(output_row["relative_path"]).suffix.lower() not in VIDEO_OUTPUT_EXTENSIONS:
            raise ValueError("영상 결과물만 미리보기를 지원합니다.")
        return dict(output_row)

    def video_output_id(self, relative_path: str) -> int:
        """정지 Thumbnail 경로를 현재 영상 식별자로 변환합니다."""

        with self._connect() as connection:
            output_row = connection.execute(
                "SELECT output_id FROM output_files WHERE relative_path=? AND is_deleted=0", (relative_path,),
            ).fetchone()
        if output_row is None:
            raise FileNotFoundError("영상을 찾을 수 없습니다.")
        return output_row["output_id"]

    def iter_video_sources(self, request_id: str | None = None) -> Iterator[dict[str, Any]]:
        """현재 영상 후보를 ID Keyset으로 페이지 조회하며 전체 목록을 메모리에 올리지 않습니다."""

        previous_identifier = 9223372036854775807
        while True:
            with self._connect() as connection:
                query = (
                    "SELECT output_id,relative_path FROM output_files WHERE output_id<? "
                    "AND is_available=1 AND is_deleted=0 AND "
                    "(lower(relative_path) LIKE '%.mp4' OR lower(relative_path) LIKE '%.webm' "
                    "OR lower(relative_path) LIKE '%.mkv' OR lower(relative_path) LIKE '%.mov')"
                )
                query_values: list[Any] = [previous_identifier]
                if request_id is not None:
                    query += " AND request_id=?"
                    query_values.append(request_id)
                output_rows = connection.execute(query + " ORDER BY output_id DESC LIMIT 100", query_values).fetchall()
            if not output_rows:
                return
            for output_row in output_rows:
                yield dict(output_row)
            previous_identifier = output_rows[-1]["output_id"]

    def list_input_images(self, directory_path: str) -> list[dict[str, Any]]:
        """현재 폴더 직하위의 사용 가능한 이미지 ID와 현재 경로만 파일명순으로 반환합니다."""

        directory_prefix = f"{directory_path}/" if directory_path else ""
        with self._connect() as connection:
            image_rows = connection.execute(
                "SELECT output_id,relative_path FROM output_files WHERE is_available=1 AND is_deleted=0 "
                "AND substr(relative_path,1,?)=? AND instr(substr(relative_path,?),'/')=0",
                (len(directory_prefix), directory_prefix, len(directory_prefix) + 1),
            ).fetchall()
        image_files = []
        for image_row in image_rows:
            image_path = Path(image_row["relative_path"])
            if image_path.suffix.lower() in IMAGE_OUTPUT_EXTENSIONS:
                image_files.append({"output_id": image_row["output_id"], "path": image_row["relative_path"], "name": image_path.name})
        image_files.sort(key=lambda image: (image["name"].casefold(), image["name"], image["path"]))
        return image_files

    def list_input_jobs(self, page: int, page_size: int) -> dict[str, Any]:
        """이미지가 남은 작업의 작은 요약만 페이지 조회하고 Prompt·하위 이력은 읽지 않습니다."""

        image_counts_query = (
            "WITH image_counts AS (SELECT job_id,COUNT(*) AS image_count FROM output_files "
            f"WHERE is_available=1 AND is_deleted=0 AND {INPUT_IMAGE_FILTER} GROUP BY job_id) "
        )
        with self._connect() as connection:
            total = connection.execute(
                image_counts_query + "SELECT COUNT(*) FROM jobs JOIN image_counts USING(job_id)"
            ).fetchone()[0]
            job_rows = connection.execute(
                image_counts_query + "SELECT jobs.job_id,jobs.workflow,jobs.description,jobs.created_at,image_count "
                "FROM jobs JOIN image_counts USING(job_id) ORDER BY jobs.created_at DESC,jobs.rowid DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
        return {"items": [dict(job_row) for job_row in job_rows], "page": page, "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size)}

    def list_job_input_images(self, job_id: str) -> dict[str, Any]:
        """작업의 현재 이미지 경로를 폴더와 무관하게 조회하고 영상·삭제 결과물은 제외합니다."""

        with self._connect() as connection:
            job_row = connection.execute(
                "SELECT job_id,workflow,description,created_at FROM jobs WHERE job_id=?", (job_id,),
            ).fetchone()
            if job_row is None:
                raise LookupError("입력 작업을 찾을 수 없습니다.")
            image_rows = connection.execute(
                "SELECT output_id,relative_path FROM output_files "
                f"WHERE job_id=? AND is_available=1 AND is_deleted=0 AND {INPUT_IMAGE_FILTER}", (job_id,),
            ).fetchall()
        image_files = []
        for image_row in image_rows:
            image_path = Path(image_row["relative_path"])
            image_files.append({"output_id": image_row["output_id"], "path": image_row["relative_path"], "name": image_path.name})
        image_files.sort(key=lambda image: (image["name"].casefold(), image["name"], image["path"]))
        return {"job": {**dict(job_row), "image_count": len(image_files)}, "files": image_files}

    def get_input_images(self, output_ids: list[int], input_job_id: str | None = None) -> list[dict[str, Any]]:
        """삭제·누락·영상 입력을 거부하고 선택 이미지의 최신 경로를 같은 조회에서 확인합니다."""

        if not output_ids or len(output_ids) > 100 or len(set(output_ids)) != len(output_ids) or any(identifier <= 0 for identifier in output_ids):
            raise ValueError("입력 이미지는 중복 없이 1~100장을 선택해 주세요.")
        placeholders = ",".join("?" for _ in output_ids)
        with self._connect() as connection:
            if input_job_id is not None and connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (input_job_id,)).fetchone() is None:
                raise ValueError("입력 작업이 삭제되었거나 더 이상 사용할 수 없습니다.")
            image_rows = connection.execute(
                f"SELECT output_id,relative_path,job_id FROM output_files WHERE output_id IN ({placeholders}) AND is_available=1 AND is_deleted=0",
                output_ids,
            ).fetchall()
        if len(image_rows) != len(output_ids):
            raise ValueError("선택한 이미지가 삭제되었거나 더 이상 사용할 수 없습니다. 다시 선택해 주세요.")
        image_files = []
        for image_row in image_rows:
            if input_job_id is not None and image_row["job_id"] != input_job_id:
                raise ValueError("선택한 작업에 속한 이미지만 함께 제출할 수 있습니다. 다시 선택해 주세요.")
            image_path = Path(image_row["relative_path"])
            if image_path.suffix.lower() not in IMAGE_OUTPUT_EXTENSIONS:
                raise ValueError("영상은 MiniMax 입력 이미지로 사용할 수 없습니다.")
            image_files.append({"output_id": image_row["output_id"], "path": image_row["relative_path"], "name": image_path.name})
        image_files.sort(key=lambda image: (image["name"].casefold(), image["name"], image["path"]))
        return image_files

    def list_deletable_output_ids(self, job_id: str = "", request_id: str = "", folder_id: str = "") -> list[int]:
        """현재 필터의 모든 페이지에서 삭제 보호되지 않은 결과물 ID만 조회합니다."""

        return self.list_selection_candidates(job_id, request_id, folder_id)["deletable_output_ids"]

    def list_selection_candidates(
        self, job_id: str = "", request_id: str = "", folder_id: str = "",
    ) -> dict[str, list[int]]:
        """작업 상태와 무관하게 현재 필터의 전체 결과물과 삭제 보호되지 않은 ID를 조회합니다."""

        conditions = ["is_available=1", "is_deleted=0"]
        query_values = []
        if job_id:
            conditions.append("job_id=?")
            query_values.append(job_id)
        if request_id:
            conditions.append("request_id=?")
            query_values.append(request_id)
        with self._connect() as connection:
            connection.execute("BEGIN")
            folder_condition, folder_parameters = self.build_output_folder_filter(connection, folder_id)
            query_values.extend(folder_parameters)
            if job_id and connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone() is None:
                raise LookupError("작업을 찾을 수 없습니다.")
            if request_id and connection.execute("SELECT 1 FROM job_requests WHERE request_id=?", (request_id,)).fetchone() is None:
                raise LookupError("요청을 찾을 수 없습니다.")
            candidate_rows = connection.execute(
                "SELECT output_id,relative_path,"
                "COALESCE((SELECT deletion_protected FROM jobs WHERE jobs.job_id=output_files.job_id),0) "
                "AS deletion_protected FROM output_files WHERE " + " AND ".join(conditions) + folder_condition,
                query_values,
            ).fetchall()
        output_ids = []
        deletable_output_ids = []
        for candidate_row in candidate_rows:
            output_extension = Path(candidate_row["relative_path"]).suffix.lower()
            if output_extension in MEDIA_EXTENSIONS:
                output_ids.append(candidate_row["output_id"])
            if output_extension in MEDIA_EXTENSIONS and not candidate_row["deletion_protected"]:
                deletable_output_ids.append(candidate_row["output_id"])
        return {"output_ids": output_ids, "deletable_output_ids": deletable_output_ids}

    def list_job_output_ids_for_move(self, job_id: str) -> list[int]:
        """생성이 끝난 작업에서 삭제되지 않고 현재 사용 가능한 결과물 ID를 조회합니다."""

        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone() is None:
                raise LookupError("작업을 찾을 수 없습니다.")
            active_request = connection.execute(
                "SELECT 1 FROM job_requests WHERE job_id=? "
                "AND status IN ('submitting','pending','running','cancelling') LIMIT 1", (job_id,),
            ).fetchone()
            if active_request is not None:
                raise ValueError("진행 중인 작업은 생성이 끝난 뒤 결과물을 이동해 주세요.")
            output_rows = connection.execute(
                "SELECT output_id FROM output_files WHERE job_id=? AND is_available=1 AND is_deleted=0 "
                "ORDER BY output_id", (job_id,),
            ).fetchall()
        return [output_row["output_id"] for output_row in output_rows]

    def get_output_path_for_move(self, output_id: int) -> str:
        """이동할 결과물의 현재 경로를 조회하고 삭제된 결과물은 거부합니다."""

        with self._connect() as connection:
            output_row = connection.execute(
                "SELECT relative_path,is_deleted FROM output_files WHERE output_id=?", (output_id,),
            ).fetchone()
        if output_row is None:
            raise LookupError("결과물을 찾을 수 없습니다.")
        if output_row["is_deleted"]:
            raise ValueError("삭제된 결과물은 이동할 수 없습니다.")
        return output_row["relative_path"]

    def is_deleted(self, relative_path: str) -> bool:
        """삭제 표시된 경로인지 확인하여 원본과 썸네일 접근을 차단합니다."""

        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM output_files WHERE relative_path=? AND is_deleted=1", (relative_path,),
            ).fetchone() is not None

    def delete_file(self, output_id: int, remove_file: Callable[[str], bool]) -> dict[str, Any]:
        """삭제 보호·이동과 경합하지 않도록 잠근 뒤 파일을 지우고 삭제 표시를 보존합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            output_row = connection.execute(
                "SELECT output_files.relative_path,output_files.is_deleted,jobs.deletion_protected "
                "FROM output_files LEFT JOIN jobs USING(job_id) WHERE output_id=?", (output_id,),
            ).fetchone()
            if output_row is None:
                raise LookupError("결과물을 찾을 수 없습니다.")
            if output_row["is_deleted"]:
                return {"deleted": True, "path": output_row["relative_path"], "deleted_files": 0}
            if output_row["deletion_protected"]:
                raise ValueError("삭제 보호된 작업입니다. 보호를 해제한 뒤 삭제해 주세요.")
            # DB 변경 실패를 파일 삭제보다 먼저 확인하고, 파일 삭제 실패 시 transaction을 되돌립니다.
            connection.execute(
                "UPDATE output_files SET is_deleted=1,is_available=0 WHERE output_id=?", (output_id,),
            )
            removed_file = remove_file(output_row["relative_path"])
        return {"deleted": True, "path": output_row["relative_path"], "deleted_files": int(removed_file)}

    def move_file(
        self, source_relative_path: str, destination_relative_path: str,
        move_physical_file: Callable[[], None] | None = None,
        *, expected_output_id: int | None = None,
    ) -> None:
        """현재 경로만 변경하고 원래 생성 경로·요청 metadata·작업 연결은 보존합니다."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source_row = connection.execute(
                "SELECT output_id,is_deleted FROM output_files WHERE relative_path=?", (source_relative_path,),
            ).fetchone()
            if expected_output_id is not None and (source_row is None or source_row["output_id"] != expected_output_id):
                raise ValueError("결과물 경로가 변경되었습니다. 목록을 새로고침한 뒤 다시 이동해 주세요.")
            if source_row is not None and source_row["is_deleted"]:
                raise ValueError("삭제된 결과물은 이동할 수 없습니다.")
            if source_row is None:
                self._store_output(connection, source_relative_path)
            if source_relative_path == destination_relative_path:
                return
            connection.execute("DELETE FROM output_files WHERE relative_path=?", (destination_relative_path,))
            connection.execute(
                "UPDATE output_files SET relative_path=?,is_available=1 WHERE relative_path=?",
                (destination_relative_path, source_relative_path),
            )
            if move_physical_file is not None:
                move_physical_file()
