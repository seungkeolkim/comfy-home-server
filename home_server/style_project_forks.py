"""저장된 설정 또는 확정 세대의 정적 Snapshot으로 독립적인 새 프로젝트를 만듭니다."""

import copy
import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .style_fork_snapshots import FORK_SNAPSHOT_FORMAT
from .style_fork_snapshots import StyleForkSnapshotStore
from .style_projects import ProjectSettings, ProjectWriteInput, StyleRevisionConflict, encode_snapshot, snapshot_hash


class ProjectForkInput(BaseModel):
    """모든 세대에서 같은 Snapshot ID·Revision·통계 포함 옵션으로 복사 대상을 고정합니다."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    expectedSnapshotRevision: int = Field(ge=1)
    sourceSnapshotIdentifier: str = Field(min_length=1, max_length=100)
    includeComponentStatistics: StrictBool = False


class StyleProjectForkStore:
    """새 소유 ID·출력 폴더와 복사된 설정·승패만 저장하며 생성 요청은 만들지 않습니다."""

    def __init__(self, project_store, workflow_directory) -> None:
        """기존 프로젝트 검증·저장을 공유합니다."""

        self.project_store = project_store
        self.workflow_directory = workflow_directory

    @staticmethod
    def settings_summary(settings: dict) -> dict:
        """Fork 선택에는 Prompt 이름과 사용 성분 수만 전달합니다."""

        policies = settings["componentPolicies"]
        return {
            "promptNames": [prompt_case["name"] for prompt_case in settings["promptCases"]],
            "enabledArtistCount": sum(policy["enabled"] for identifier, policy in policies.items() if identifier.startswith("artist:")),
            "enabledLoraCount": sum(policy["enabled"] for identifier, policy in policies.items() if identifier.startswith("lora:")),
        }

    def options(self, project_identifier: str) -> dict:
        """현재 세대와 과거 세대에 실제 저장된 설정 Snapshot을 선택지로 제공합니다."""

        with self.project_store.connection_factory() as connection:
            project = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
            if project is None:
                raise LookupError("Fork할 프로젝트를 찾을 수 없습니다.")
            settings = json.loads(project["settings_json"])
            snapshots = []
            for row in connection.execute(
                "SELECT snapshot_id,evaluation_id,generation_number,revision,snapshot_json,updated_at "
                "FROM style_project_generation_snapshots WHERE project_id=? ORDER BY generation_number DESC,updated_at DESC,snapshot_id",
                (project_identifier,),
            ):
                document = json.loads(row["snapshot_json"])
                snapshots.append({"identifier": row["snapshot_id"], "evaluationIdentifier": row["evaluation_id"],
                                  "generationNumber": row["generation_number"], "revision": row["revision"], "updatedAt": row["updated_at"],
                                  **self.settings_summary(document["settings"])})
        return {"projectIdentifier": project_identifier, "sourceProjectName": settings["name"],
                "currentSnapshotIdentifier": snapshots[0]["identifier"] if snapshots else None, "snapshots": snapshots}

    def create_fork(self, source_project_identifier: str, payload: ProjectForkInput) -> dict:
        """검증·프로젝트 생성·출처·승패 복사를 원자 처리하고 중복 제출을 한 번만 반영합니다."""

        request_hash = snapshot_hash({"sourceProjectIdentifier": source_project_identifier, **payload.model_dump()})
        with self.project_store.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT project_id,payload_hash FROM style_project_forks WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 프로젝트를 Fork할 수 없습니다.")
                target_identifier = existing["project_id"]
            else:
                source = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (source_project_identifier,)).fetchone()
                if source is None:
                    raise LookupError("Fork할 프로젝트를 찾을 수 없습니다.")
                document, source_generation, source_evaluation = self.source_document(connection, source, payload)
                copied_settings = copy.deepcopy(document["settings"])
                source_project_name = copied_settings["name"]
                copied_settings["name"] = payload.name
                validated_settings = ProjectSettings(**copied_settings)
                if connection.execute("SELECT 1 FROM style_projects WHERE creation_operation_id=?", (payload.operationIdentifier,)).fetchone():
                    raise StyleRevisionConflict("이미 다른 프로젝트 생성에 사용한 요청 ID입니다.")
                created = self.project_store.save_project(
                    ProjectWriteInput(settings=validated_settings, operationIdentifier=payload.operationIdentifier),
                    self.workflow_directory, connection=connection, record_snapshot=False,
                )
                target_identifier = created["identifier"]
                connection.execute(
                    "INSERT INTO style_project_forks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (target_identifier, source_project_identifier, source_project_name, source_evaluation, source_generation,
                     payload.sourceSnapshotIdentifier, snapshot_hash(document), int(payload.includeComponentStatistics),
                     encode_snapshot(document["componentStatistics"] if payload.includeComponentStatistics else {}),
                     payload.operationIdentifier, request_hash, datetime.now(timezone.utc).isoformat()),
                )
                StyleForkSnapshotStore.capture_project(connection, target_identifier)
        with self.project_store.connection_factory() as connection:
            target = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (target_identifier,)).fetchone()
        return self.project_store.project_from_row(target)

    @staticmethod
    def source_document(connection, source, payload: ProjectForkInput) -> tuple[dict, int, str]:
        """설정 변경 뒤 오래된 화면에서 Fork하지 않도록 모든 세대의 Snapshot Revision을 검사합니다."""
        snapshot = connection.execute(
            "SELECT * FROM style_project_generation_snapshots WHERE snapshot_id=? AND project_id=?",
            (payload.sourceSnapshotIdentifier, source["project_id"]),
        ).fetchone()
        if snapshot is None:
            raise LookupError("이 프로젝트의 세대 Snapshot을 찾을 수 없습니다.")
        if snapshot["revision"] != payload.expectedSnapshotRevision:
            raise StyleRevisionConflict("선택한 세대의 설정이 변경됐습니다. Fork 기준을 다시 불러온 뒤 확인해 주세요.")
        document = json.loads(snapshot["snapshot_json"])
        if snapshot_hash(document) != snapshot["snapshot_hash"] or document["format"] != FORK_SNAPSHOT_FORMAT:
            raise StyleRevisionConflict("확정 세대 Snapshot의 무결성 검증에 실패했습니다.")
        return document, snapshot["generation_number"], snapshot["evaluation_id"]
