"""이미지·조합 Elo와 분리한 세대별 설정·성분 선호도·승패 Snapshot을 보관합니다."""

import json
import uuid
from datetime import datetime, timezone

from .style_component_statistics import component_preference_scores, component_win_loss_statistics, inherited_component_statistics, read_component_statistics
from .style_projects import ProjectSettings, encode_snapshot, snapshot_hash


FORK_SNAPSHOT_FORMAT = "style-project-settings-snapshot-v2"


class StyleForkSnapshotStore:
    """현재 세대는 설정 저장 때 갱신하고 지난 세대의 마지막 상태는 보존합니다."""

    @staticmethod
    def prepare_schema(connection) -> None:
        """작은 세대 Snapshot과 새 프로젝트의 독립적인 Fork 출처·승패를 만듭니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_project_generation_snapshots ("
            "snapshot_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id) ON DELETE CASCADE, "
            "evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id) ON DELETE CASCADE, "
            "generation_number INTEGER NOT NULL CHECK(generation_number>=0), "
            "checkpoint_id TEXT UNIQUE REFERENCES style_generation_checkpoints(checkpoint_id) ON DELETE SET NULL, "
            "revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(project_id,generation_number))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_project_forks ("
            "project_id TEXT PRIMARY KEY REFERENCES style_projects(project_id) ON DELETE CASCADE, "
            "source_project_id TEXT NOT NULL, source_project_name TEXT NOT NULL, source_evaluation_id TEXT NOT NULL, "
            "source_generation_number INTEGER NOT NULL CHECK(source_generation_number>=0), "
            "source_snapshot_id TEXT REFERENCES style_project_generation_snapshots(snapshot_id) ON DELETE SET NULL, "
            "source_snapshot_hash TEXT NOT NULL, include_component_statistics INTEGER NOT NULL CHECK(include_component_statistics IN (0,1)), "
            "component_statistics_json TEXT NOT NULL, "
            "operation_id TEXT UNIQUE NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL)"
        )

    @staticmethod
    def capture_checkpoint(connection, checkpoint_identifier: str, checkpoint: dict, created_at: str, *, replace_existing: bool = True) -> str:
        """세대 확정 때 갱신하되 과거 Checkpoint의 재조회로 저장한 설정을 덮어쓰지 않습니다."""

        existing = connection.execute(
            "SELECT snapshot_id FROM style_project_generation_snapshots WHERE project_id=? AND generation_number=?",
            (checkpoint["projectIdentifier"], checkpoint["generationNumber"]),
        ).fetchone()
        if existing and not replace_existing:
            return existing[0]
        document = StyleForkSnapshotStore.checkpoint_document(connection, checkpoint)
        return StyleForkSnapshotStore.save_document(
            connection, checkpoint["projectIdentifier"], checkpoint["evaluationIdentifier"], checkpoint["generationNumber"],
            document, checkpoint_identifier, created_at,
        )

    @staticmethod
    def checkpoint_document(connection, checkpoint: dict) -> dict:
        """원본 Elo·Graph·이미지 참조 없이 해당 시점의 설정과 누적 성분 승패를 추출합니다."""

        eligible_identifiers = {membership["candidate_id"] for membership in checkpoint["memberships"] if membership["lifecycle"] in {"active", "retired"}}
        rendered_identifiers = {render["candidate_id"] for render in checkpoint["renders"]}
        eligible_identifiers.intersection_update(rendered_identifiers)
        candidates = []
        lifecycle_by_identifier = {membership["candidate_id"]: membership["lifecycle"] for membership in checkpoint["memberships"]}
        for candidate in checkpoint["candidates"]:
            if candidate["candidate_id"] in eligible_identifiers:
                candidates.append({"identifier": candidate["candidate_id"], "components": json.loads(candidate["components_json"]),
                                   "lifecycle": lifecycle_by_identifier[candidate["candidate_id"]]})
        votes = connection.execute(
            "SELECT json_extract(events.match_json,'$.a') AS first_candidate,"
            "json_extract(events.match_json,'$.b') AS second_candidate,events.choice "
            "FROM style_vote_events AS events WHERE evaluation_id=? AND events.rowid<=? AND choice IN ('a','b') "
            "AND json_extract(events.match_json,'$.kind') IN ('league','top','tie') "
            "AND (undone_by IS NULL OR NOT EXISTS(SELECT 1 FROM style_voting_commands AS commands "
            "WHERE commands.operation_id=events.undone_by AND commands.rowid<=?)) ORDER BY events.rowid",
            (checkpoint["evaluationIdentifier"], checkpoint["voteEventBoundary"], checkpoint["votingCommandBoundary"]),
        ).fetchall()
        component_statistics = component_win_loss_statistics(candidates, votes)
        scores = component_preference_scores(candidates, checkpoint["arena"]["statistics"])
        inherited_statistics = inherited_component_statistics(connection, checkpoint["projectIdentifier"])
        for identifier in component_statistics.keys() | scores.keys() | inherited_statistics.keys():
            statistics = component_statistics.setdefault(identifier, {"matches": 0, "wins": 0, "losses": 0})
            inherited = inherited_statistics.get(identifier, {"matches": 0, "wins": 0, "losses": 0, "score": 0})
            for field in ("matches", "wins", "losses"):
                statistics[field] += inherited[field]
            statistics["score"] = scores.get(identifier, 0) + inherited.get("score", 0)
        workflow = checkpoint["contract"]["workflow"]
        return {
            "format": FORK_SNAPSHOT_FORMAT,
            "settings": ProjectSettings(**checkpoint["settings"]).model_dump(),
            "componentStatistics": component_statistics,
            "workflow": {"identifier": workflow["identifier"], "modelIdentifier": workflow["model_identifier"],
                         "apiHash": workflow["api_hash"], "uiHash": workflow["ui_hash"]},
        }

    @staticmethod
    def save_document(connection, project_identifier: str, evaluation_identifier: str, generation_number: int,
                      document: dict, checkpoint_identifier: str | None = None, saved_at: str | None = None) -> str:
        """같은 세대는 마지막 저장 내용으로 갱신하고 다른 세대의 Snapshot은 유지합니다."""

        saved_at = saved_at or datetime.now(timezone.utc).isoformat()
        document_hash = snapshot_hash(document)
        existing = connection.execute(
            "SELECT * FROM style_project_generation_snapshots WHERE project_id=? AND generation_number=?",
            (project_identifier, generation_number),
        ).fetchone()
        if existing and existing["snapshot_hash"] == document_hash:
            return existing["snapshot_id"]
        snapshot_identifier = existing["snapshot_id"] if existing else uuid.uuid4().hex
        connection.execute(
            "INSERT INTO style_project_generation_snapshots VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project_id,generation_number) DO UPDATE SET evaluation_id=excluded.evaluation_id, "
            "checkpoint_id=excluded.checkpoint_id,revision=excluded.revision,snapshot_json=excluded.snapshot_json, "
            "snapshot_hash=excluded.snapshot_hash,updated_at=excluded.updated_at",
            (snapshot_identifier, project_identifier, evaluation_identifier, generation_number, checkpoint_identifier,
             existing["revision"] + 1 if existing else 1, encode_snapshot(document), document_hash,
             existing["created_at"] if existing else saved_at, saved_at),
        )
        return snapshot_identifier

    @staticmethod
    def capture_project(connection, project_identifier: str) -> str:
        """현재 저장된 설정·성분 선호도·승패를 해당 프로젝트의 현재 세대에 저장합니다."""

        project = connection.execute("SELECT settings_json,active_evaluation_id FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
        evaluation_identifier = project["active_evaluation_id"]
        timeline = connection.execute("SELECT generation_number FROM style_evolution_timelines WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()
        contract = json.loads(connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()[0])
        statistics = read_component_statistics(connection, project_identifier, evaluation_identifier)["components"]
        component_statistics = {}
        for identifier, observation in statistics.items():
            component_statistics[identifier] = {field: observation[field] for field in ("score", "matches", "wins", "losses")}
        workflow = contract["workflow"]
        document = {"format": FORK_SNAPSHOT_FORMAT, "settings": ProjectSettings(**json.loads(project["settings_json"])).model_dump(),
                    "componentStatistics": component_statistics,
                    "workflow": {"identifier": workflow["identifier"], "modelIdentifier": workflow["model_identifier"],
                                 "apiHash": workflow["api_hash"], "uiHash": workflow["ui_hash"]}}
        return StyleForkSnapshotStore.save_document(connection, project_identifier, evaluation_identifier, timeline[0] if timeline else 0, document)

    @staticmethod
    def backfill_checkpoints(connection) -> None:
        """옛 불변 Checkpoint만 읽어 빠진 세대 Snapshot을 채우고 이미 저장된 것은 유지합니다."""

        rows = connection.execute(
            "SELECT checkpoints.* FROM style_generation_checkpoints AS checkpoints "
            "LEFT JOIN style_project_generation_snapshots AS snapshots "
            "ON snapshots.project_id=checkpoints.project_id AND snapshots.generation_number=checkpoints.generation_number "
            "WHERE snapshots.snapshot_id IS NULL ORDER BY checkpoints.created_at DESC,checkpoints.rowid DESC",
        )
        for row in rows:
            checkpoint = json.loads(row["snapshot_json"])
            if snapshot_hash(checkpoint) != row["snapshot_hash"]:
                raise ValueError("Fork Snapshot을 만들 Checkpoint의 무결성 검증에 실패했습니다.")
            StyleForkSnapshotStore.capture_checkpoint(connection, row["checkpoint_id"], checkpoint, row["created_at"], replace_existing=False)
