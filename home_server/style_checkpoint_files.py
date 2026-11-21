"""Checkpoint의 파일 검증은 유지하고 변경되지 않은 이미지의 SHA-256만 재사용합니다."""

import hashlib
import json
import stat


class StyleCheckpointFileStore:
    """작은 파일 식별 정보와 Hash를 DB에 보관해 재시작 뒤에도 원본 재독을 줄입니다."""

    def __init__(self, server) -> None:
        """기존 관리 경로 검증을 통해서만 실제 파일에 접근합니다."""

        self.server = server

    @staticmethod
    def prepare_schema(connection) -> None:
        """기존 Checkpoint 본문과 독립적인 파일 Hash Cache를 만듭니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_checkpoint_file_hashes ("
            "output_id INTEGER PRIMARY KEY REFERENCES output_files(output_id) ON DELETE CASCADE, "
            "project_id TEXT NOT NULL REFERENCES style_projects(project_id), file_identity TEXT NOT NULL, sha256 TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS style_checkpoint_hashes_project ON style_checkpoint_file_hashes(project_id)")

    @staticmethod
    def file_identity(image_path, file_stat) -> str:
        """경로·크기·수정/변경 시각·파일 ID가 같은 경우에만 Hash를 재사용합니다."""

        return json.dumps([str(image_path), file_stat.st_size, file_stat.st_mtime_ns,
                           file_stat.st_ctime_ns, file_stat.st_dev, file_stat.st_ino])

    @staticmethod
    def calculate_file_hash(image_path) -> str:
        """원본 전체를 RAM에 올리지 않고 일정 크기 Chunk로 SHA-256을 계산합니다."""

        digest = hashlib.sha256()
        with image_path.open("rb") as image_file:
            while True:
                image_chunk = image_file.read(1024 * 1024)
                if not image_chunk:
                    break
                digest.update(image_chunk)
        return digest.hexdigest()

    def describe_assets(self, connection, project_identifier: str, asset_rows) -> list[dict]:
        """매 파일의 존재·식별 정보를 확인하고 신규·변경 파일만 읽어 Manifest를 만듭니다."""

        cached_hashes = {row["output_id"]: row for row in connection.execute(
            "SELECT output_id,file_identity,sha256 FROM style_checkpoint_file_hashes WHERE project_id=?", (project_identifier,),
        )}
        assets = []
        changed_hashes = []
        for row in asset_rows:
            asset = dict(row)
            assets.append(asset)
            if not row["is_available"] or row["is_deleted"]:
                continue
            image_path = self.server.managed_path(row["relative_path"])
            try:
                file_stat = image_path.stat()
            except FileNotFoundError:
                asset["missingFile"] = True
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                asset["missingFile"] = True
                continue
            file_identity = self.file_identity(image_path, file_stat)
            cached_hash = cached_hashes.get(row["output_id"])
            if cached_hash is not None and cached_hash["file_identity"] == file_identity:
                digest = cached_hash["sha256"]
            else:
                digest = self.calculate_file_hash(image_path)
                if self.file_identity(image_path, image_path.stat()) != file_identity:
                    raise ValueError("Checkpoint를 만드는 중 이미지 파일이 변경됐습니다. 다시 시도해 주세요.")
                changed_hashes.append((row["output_id"], project_identifier, file_identity, digest))
            asset.update(sha256=digest, fileSize=file_stat.st_size)
        connection.executemany(
            "INSERT INTO style_checkpoint_file_hashes VALUES(?,?,?,?) ON CONFLICT(output_id) DO UPDATE SET "
            "project_id=excluded.project_id,file_identity=excluded.file_identity,sha256=excluded.sha256", changed_hashes,
        )
        return assets
