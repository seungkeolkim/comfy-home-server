"""세대 Timeline·후보 소속·진화 Batch·확정 Checkpoint를 보관합니다."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .style_projects import encode_snapshot, snapshot_hash


class StyleEvolutionStore:
    """삭제 대신 후보 상태를 바꾸고 재생 가능한 불변 세대 Snapshot을 남깁니다."""

    def __init__(self, server) -> None:
        """같은 Home DB와 관리 이미지 경로를 사용합니다."""

        self.server = server

    @staticmethod
    def prepare_schema(connection) -> None:
        """기존 후보는 1세대 활성 상태로 두고 진화 전용 테이블만 추가합니다."""

        connection.execute("CREATE TABLE IF NOT EXISTS style_evolution_timelines (evaluation_id TEXT PRIMARY KEY REFERENCES style_evaluation_revisions(evaluation_id), project_id TEXT NOT NULL REFERENCES style_projects(project_id), generation_number INTEGER NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS style_evolution_batches (batch_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id), plan_id TEXT NOT NULL UNIQUE REFERENCES style_generation_plans(plan_id), status TEXT NOT NULL, batch_json TEXT NOT NULL, result_json TEXT, operation_id TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
        connection.execute("CREATE INDEX IF NOT EXISTS style_evolution_scope ON style_evolution_batches(project_id,evaluation_id,status)")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS style_evolution_one_open_batch ON style_evolution_batches(evaluation_id) WHERE status IN ('planned','active')")
        connection.execute("CREATE TABLE IF NOT EXISTS style_candidate_memberships (candidate_id TEXT PRIMARY KEY REFERENCES style_candidates(candidate_id), evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id), generation_number INTEGER NOT NULL, lifecycle TEXT NOT NULL, batch_id TEXT REFERENCES style_evolution_batches(batch_id), breeding_mode TEXT NOT NULL, parent_ids_json TEXT NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO style_candidate_memberships SELECT candidate_id,evaluation_id,1,'active',NULL,'legacy','[]' FROM style_candidates")
        connection.execute("CREATE TABLE IF NOT EXISTS style_generation_checkpoints (checkpoint_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id), generation_number INTEGER NOT NULL, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(evaluation_id,generation_number))")
        connection.execute("CREATE TABLE IF NOT EXISTS style_evolution_commands (operation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), batch_id TEXT NOT NULL REFERENCES style_evolution_batches(batch_id), action TEXT NOT NULL, payload_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)")

    @staticmethod
    def current_generation_number(connection, evaluation_identifier: str) -> int:
        """기존 평가 조건은 Timeline이 생기기 전까지 1세대로 취급합니다."""

        row = connection.execute("SELECT generation_number FROM style_evolution_timelines WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()
        return row[0] if row else 1

    @staticmethod
    def find_open_evolution_batch(connection, evaluation_identifier: str):
        """같은 평가 조건에서 준비·진행 중인 Batch 하나만 반환합니다."""

        return connection.execute("SELECT * FROM style_evolution_batches WHERE evaluation_id=? AND status IN ('planned','active')", (evaluation_identifier,)).fetchone()

    def create_generation_checkpoint(self, connection, project_identifier: str, evaluation_identifier: str, generation_number: int, state: dict, reason: str) -> str:
        """설정·평가 상태·Event 경계·후보·실제 파일 Manifest를 불변 Snapshot으로 저장합니다."""

        existing = connection.execute("SELECT checkpoint_id FROM style_generation_checkpoints WHERE evaluation_id=? AND generation_number=?", (evaluation_identifier, generation_number)).fetchone()
        if existing:
            return existing[0]
        project = connection.execute("SELECT settings_json,storage_binding_json FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
        evaluation = connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()
        scope = (project_identifier, evaluation_identifier, generation_number)
        memberships = [dict(row) for row in connection.execute(
            "SELECT memberships.* FROM style_candidate_memberships AS memberships JOIN style_candidates USING(candidate_id) "
            "WHERE project_id=? AND memberships.evaluation_id=? AND generation_number<=? ORDER BY style_candidates.rowid", scope)]
        candidates = [dict(row) for row in connection.execute(
            "SELECT candidates.* FROM style_candidates AS candidates JOIN style_candidate_memberships USING(candidate_id) "
            "WHERE project_id=? AND candidates.evaluation_id=? AND generation_number<=? ORDER BY candidates.rowid", scope)]
        plans = [dict(row) for row in connection.execute(
            "SELECT DISTINCT plans.* FROM style_generation_plans AS plans JOIN style_candidates AS candidates USING(plan_id) "
            "JOIN style_candidate_memberships USING(candidate_id) WHERE candidates.project_id=? AND candidates.evaluation_id=? AND generation_number<=? ORDER BY plans.created_at", scope)]
        renders = [dict(row) for row in connection.execute(
            "SELECT renders.*,requests.status,requests.error_message FROM style_candidate_renders AS renders "
            "JOIN style_candidates AS candidates USING(candidate_id) JOIN style_candidate_memberships USING(candidate_id) JOIN job_requests AS requests USING(request_id) "
            "WHERE project_id=? AND candidates.evaluation_id=? AND generation_number<=? ORDER BY renders.rowid", scope)]
        batches = [dict(row) for row in connection.execute(
            "SELECT * FROM style_evolution_batches WHERE project_id=? AND evaluation_id=? AND CAST(json_extract(batch_json,'$.targetGeneration') AS INTEGER)<=? ORDER BY rowid", scope)]
        assets = []
        for row in connection.execute(
            "SELECT DISTINCT files.output_id,files.relative_path,files.is_available,files.is_deleted FROM output_files AS files "
            "JOIN style_candidate_renders USING(request_id) JOIN style_candidates AS candidates USING(candidate_id) JOIN style_candidate_memberships USING(candidate_id) "
            "WHERE project_id=? AND candidates.evaluation_id=? AND generation_number<=? ORDER BY files.output_id", scope):
            asset = dict(row)
            if row["is_available"] and not row["is_deleted"]:
                image_path = self.server.managed_path(row["relative_path"])
                if image_path.is_file():
                    asset["sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
                    asset["fileSize"] = image_path.stat().st_size
                else:
                    asset["missingFile"] = True
            assets.append(asset)
        event_boundary = connection.execute("SELECT COALESCE(MAX(rowid),0) FROM style_vote_events WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()[0]
        command_boundary = connection.execute("SELECT COALESCE(MAX(rowid),0) FROM style_voting_commands WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()[0]
        evolution_boundary = connection.execute("SELECT COALESCE(MAX(commands.rowid),0) FROM style_evolution_commands AS commands JOIN style_evolution_batches USING(batch_id) WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()[0]
        snapshot = {"format": "style-generation-checkpoint-v1", "reason": reason, "projectIdentifier": project_identifier, "evaluationIdentifier": evaluation_identifier, "generationNumber": generation_number,
                    "settings": json.loads(project["settings_json"]), "storageBinding": json.loads(project["storage_binding_json"]), "contract": json.loads(evaluation[0]), "arena": state,
                    "memberships": memberships, "candidates": candidates, "plans": plans, "renders": renders, "batches": batches, "evolutionCommandBoundary": evolution_boundary, "assets": assets, "voteEventBoundary": event_boundary, "votingCommandBoundary": command_boundary}
        identifier = uuid.uuid4().hex
        connection.execute("INSERT INTO style_generation_checkpoints VALUES(?,?,?,?,?,?,?)", (identifier, project_identifier, evaluation_identifier, generation_number, encode_snapshot(snapshot), snapshot_hash(snapshot), datetime.now(timezone.utc).isoformat()))
        return identifier
