"""Fresh 스타일 프로젝트의 설정과 불변 평가 조건을 저장합니다."""

from __future__ import annotations

import hashlib
import copy
import json
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .output_directories import validate_directory_name
from .workflows import load_workflows


class ComponentRange(BaseModel):
    """성분의 사용 여부와 같은 값도 허용하는 STR 범위를 검증합니다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = False
    minimumStrength: float = Field(default=0.4, ge=-20, le=20)
    maximumStrength: float = Field(default=1, ge=-20, le=20)

    @model_validator(mode="after")
    def validate_range(self):
        """비활성 성분도 잘못된 범위를 영속화하지 않게 합니다."""

        if self.minimumStrength > self.maximumStrength:
            raise ValueError("최소 STR은 최대 STR보다 클 수 없습니다.")
        return self


class PromptCase(BaseModel):
    """화면 순서와 별개인 안정적인 Case ID를 보존합니다."""

    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=1, max_length=3000)
    negativePrompt: str = Field(default="", max_length=3000)


class ComponentCountSettings(BaseModel):
    """조합 하나에 포함할 작가·LoRA 개수를 각각 제한합니다."""

    artistMinimumCount: int = Field(default=0, ge=0, le=100)
    artistMaximumCount: int = Field(default=8, ge=0, le=100)
    loraMinimumCount: int = Field(default=0, ge=0, le=100)
    loraMaximumCount: int = Field(default=2, ge=0, le=100)

    @model_validator(mode="after")
    def validate_component_counts(self):
        """개수 범위의 역전을 거부하고 0~0은 해당 종류의 미사용으로 허용합니다."""

        if self.artistMinimumCount > self.artistMaximumCount or self.loraMinimumCount > self.loraMaximumCount:
            raise ValueError("최소 사용 개수는 최대 사용 개수보다 클 수 없습니다.")
        return self


class ProjectSettings(ComponentCountSettings):
    """현재 이미지 Adapter가 제어하는 설정만 저장합니다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(default="", max_length=2000)
    pipelineIdentifier: Literal["anima"] = "anima"
    promptCases: list[PromptCase] = Field(min_length=1, max_length=20)
    negativePrompt: str = Field(default="", max_length=3000)
    seed: int = Field(default=42, ge=0, le=18446744073709551615)
    aspectRatio: str = Field(default="2:3", max_length=20)
    width: int = Field(default=576, ge=1, le=8192)
    height: int = Field(default=864, ge=1, le=8192)
    steps: int = Field(default=12, ge=1, le=200)
    cfg: float = Field(default=1, ge=0, le=100)
    componentPolicies: dict[str, ComponentRange] = Field(default_factory=dict, max_length=5000)
    defaultsRevision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_project(self):
        """출력 폴더 이름과 Case의 소유 관계를 명확하게 검증합니다."""

        self.name = self.name.strip()
        validate_directory_name(self.name)
        case_identifiers = set()
        for prompt_case in self.promptCases:
            if not prompt_case.name.strip() or not prompt_case.prompt.strip():
                raise ValueError("각 Prompt의 이름과 내용을 입력해 주세요.")
            if prompt_case.identifier in case_identifiers:
                raise ValueError("Prompt Case ID가 중복되었습니다.")
            case_identifiers.add(prompt_case.identifier)
        for component_identifier in self.componentPolicies:
            if not component_identifier.startswith(("artist:", "lora:")):
                raise ValueError("알 수 없는 성분 Identifier입니다.")
        for kind, label in (("artist", "작가"), ("lora", "LoRA")):
            enabled_count = sum(policy.enabled for identifier, policy in self.componentPolicies.items() if identifier.startswith(kind + ":"))
            if getattr(self, kind + "MinimumCount") > enabled_count:
                raise ValueError(f"{label} 최소 사용 개수보다 허용한 성분이 부족합니다.")
        return self


class ProjectWriteInput(BaseModel):
    """생성의 중복 제출과 다른 탭의 설정 덮어쓰기를 구분합니다."""

    model_config = ConfigDict(extra="forbid")
    settings: ProjectSettings
    operationIdentifier: str = Field(min_length=16, max_length=100)
    expectedRevision: int | None = Field(default=None, ge=1)


class ArtistRegistration(BaseModel):
    """작가 Catalog에는 실제 등록한 이름만 허용합니다."""

    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(pattern=r"^artist:[^\s,:@<>{}\[\]|\\]+$", max_length=200)
    name: str = Field(min_length=1, max_length=190)
    kind: Literal["작가"] = "작가"

    @model_validator(mode="after")
    def validate_identity(self):
        """표시 이름과 식별자가 다른 작가로 등록되는 것을 막습니다."""

        if self.identifier != f"artist:{self.name}":
            raise ValueError("작가 이름과 Identifier가 일치하지 않습니다.")
        return self


class GlobalStyleSettings(ComponentCountSettings):
    """전역 기본값과 등록 작가를 프로젝트 성적과 분리합니다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    revision: int = Field(default=1, ge=1)
    pipelineIdentifier: Literal["anima"] = "anima"
    artistMinimumStrength: float = Field(default=0.4, ge=-20, le=20)
    artistMaximumStrength: float = Field(default=1.2, ge=-20, le=20)
    loraMinimumStrength: float = Field(default=0.4, ge=-20, le=20)
    loraMaximumStrength: float = Field(default=1, ge=-20, le=20)
    availableComponents: dict[str, bool] = Field(default_factory=dict, max_length=5000)
    additionalArtists: list[ArtistRegistration] = Field(default_factory=list, max_length=3000)

    @model_validator(mode="after")
    def validate_defaults(self):
        """범위 역전과 같은 작가 중복 등록을 거부합니다."""

        if self.artistMinimumStrength > self.artistMaximumStrength or self.loraMinimumStrength > self.loraMaximumStrength:
            raise ValueError("최소 STR은 최대 STR보다 클 수 없습니다.")
        identifiers = [artist.identifier for artist in self.additionalArtists]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("이미 등록된 작가입니다.")
        return self


class StyleRevisionConflict(Exception):
    """다른 탭에서 바뀐 내용을 오래된 초안으로 덮어쓰지 않습니다."""


def browser_sampling_settings(settings: dict) -> dict:
    """JavaScript 정수 정밀도 밖의 Seed만 십진 문자열로 전달합니다."""

    public_settings = copy.deepcopy(settings)
    if int(public_settings.get("seed", 0)) > 9007199254740991:
        public_settings["seed"] = str(public_settings["seed"])
    return public_settings


def evaluation_without_seed(contract: dict) -> dict:
    """기존 이미지 보존 여부를 판단할 때 Seed 이외의 실제 생성 조건을 비교합니다."""

    normalized_contract = copy.deepcopy(contract)
    normalized_contract["sampling"].pop("seed", None)
    return normalized_contract


def encode_snapshot(value: Any) -> str:
    """내용 비교와 Hash에 동일한 JSON 직렬화를 사용합니다."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def snapshot_hash(value: Any) -> str:
    """불변 조건 Snapshot의 SHA-256을 반환합니다."""

    return hashlib.sha256(encode_snapshot(value).encode("utf-8")).hexdigest()


class StyleProjectStore:
    """같은 CHS DB의 독립적인 트랜잭션으로 프로젝트를 관리합니다."""

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        """DB 복원 뒤에도 현재 파일에 연결하도록 Factory만 보관합니다."""

        self.connection_factory = connection_factory

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """현재 단계에 필요한 프로젝트·평가·글로벌 설정만 준비합니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_projects ("
            "project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, settings_json TEXT NOT NULL, "
            "active_evaluation_id TEXT NOT NULL, storage_binding_json TEXT NOT NULL, "
            "creation_operation_id TEXT UNIQUE NOT NULL, creation_payload_hash TEXT NOT NULL, "
            "last_operation_id TEXT NOT NULL, last_payload_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_evaluation_revisions ("
            "evaluation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "condition_hash TEXT NOT NULL, contract_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS style_evaluation_project ON style_evaluation_revisions(project_id)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_workspace_settings ("
            "identifier INTEGER PRIMARY KEY CHECK(identifier=1), settings_json TEXT NOT NULL)"
        )

    def global_settings(self) -> dict:
        """저장 전에는 예시 성분이 없는 초기값을 반환합니다."""

        with self.connection_factory() as connection:
            row = connection.execute("SELECT settings_json FROM style_workspace_settings WHERE identifier=1").fetchone()
        return GlobalStyleSettings(**json.loads(row[0])).model_dump() if row else GlobalStyleSettings().model_dump()

    def save_global_settings(self, settings: GlobalStyleSettings) -> dict:
        """기존 프로젝트를 변경하지 않고 글로벌 기본값만 저장합니다."""

        saved_settings = settings.model_dump()
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT settings_json FROM style_workspace_settings WHERE identifier=1").fetchone()
            current_settings = json.loads(row[0]) if row else GlobalStyleSettings().model_dump()
            if settings.revision != current_settings["revision"]:
                raise StyleRevisionConflict("다른 탭에서 글로벌 설정을 변경했습니다. 초안을 보존한 채 다시 불러와 주세요.")
            saved_settings["revision"] += 1
            connection.execute(
                "INSERT INTO style_workspace_settings VALUES(1,?) "
                "ON CONFLICT(identifier) DO UPDATE SET settings_json=excluded.settings_json",
                (encode_snapshot(saved_settings),),
            )
        return saved_settings

    def list_projects(self) -> list[dict]:
        """프로젝트별 저장된 설정을 최근 생성 순서로 반환합니다."""

        with self.connection_factory() as connection:
            rows = connection.execute("SELECT * FROM style_projects ORDER BY created_at DESC, project_id").fetchall()
            generation_numbers = dict(connection.execute("SELECT evaluation_id,generation_number FROM style_evolution_timelines"))
            candidate_counts = dict(connection.execute(
                "SELECT project_id,COUNT(DISTINCT candidate_id) FROM style_candidates JOIN style_candidate_renders USING(candidate_id) "
                "JOIN style_projects USING(project_id) JOIN style_candidate_memberships USING(candidate_id) WHERE lifecycle IN ('active','evolving') GROUP BY project_id"
            ).fetchall())
        return [{**self.project_from_row(row), "generation": generation_numbers.get(row["active_evaluation_id"], 1), "candidateCount": candidate_counts.get(row["project_id"], 0)} for row in rows]

    def project_from_row(self, row: sqlite3.Row) -> dict:
        """설정 저장 응답에도 현재 세대를 반영하고 후보 목록은 별도로 조회합니다."""

        settings = browser_sampling_settings(ProjectSettings(**json.loads(row["settings_json"])).model_dump())
        with self.connection_factory() as connection:
            timeline = connection.execute("SELECT generation_number FROM style_evolution_timelines WHERE evaluation_id=?", (row["active_evaluation_id"],)).fetchone()
        return {
            "identifier": row["project_id"], "revision": row["revision"], "settings": settings,
            "name": settings["name"], "promptCases": settings["promptCases"], "generation": timeline[0] if timeline else 1,
            "evaluationIdentifier": row["active_evaluation_id"], "candidateCount": 0,
            "candidates": [], "decisions": [], "savedCandidates": [], "excludedComponents": [], "pairIndex": 0,
            "storageBinding": json.loads(row["storage_binding_json"]),
        }

    def save_project(self, payload: ProjectWriteInput, workflow_directory: Path, project_identifier: str | None = None,
                     *, connection: sqlite3.Connection | None = None, storage_binding_override: dict | None = None) -> dict:
        """설정 저장과 평가 Snapshot 추가를 하나의 Transaction으로 처리합니다."""

        settings = payload.settings.model_dump()
        payload_hash = snapshot_hash(settings)
        saved_at = datetime.now(timezone.utc).isoformat()
        with nullcontext(connection) if connection is not None else self.connection_factory() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if project_identifier:
                existing = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
                if existing is None:
                    raise LookupError("프로젝트를 찾을 수 없습니다.")
            else:
                existing = connection.execute(
                    "SELECT * FROM style_projects WHERE creation_operation_id=?", (payload.operationIdentifier,),
                ).fetchone()
            if existing is not None:
                operation_matches = existing["last_operation_id"] == payload.operationIdentifier
                creation_matches = not project_identifier and existing["creation_operation_id"] == payload.operationIdentifier
                if operation_matches or creation_matches:
                    expected_hash = existing["creation_payload_hash"] if creation_matches else existing["last_payload_hash"]
                    if payload_hash != expected_hash:
                        raise StyleRevisionConflict("같은 요청 Identifier로 다른 설정을 저장할 수 없습니다.")
                    return self.project_from_row(existing)
                if connection.execute("SELECT 1 FROM style_evolution_batches WHERE project_id=? AND status IN ('planned','active')", (project_identifier,)).fetchone():
                    raise StyleRevisionConflict("준비·진행 중인 진화를 확정하거나 취소한 뒤 프로젝트 설정을 변경해 주세요.")
                if payload.expectedRevision != existing["revision"]:
                    raise StyleRevisionConflict("다른 탭에서 프로젝트를 변경했습니다. 초안을 보존한 채 다시 불러와 주세요.")
            project_identifier = existing["project_id"] if existing else uuid.uuid4().hex
            previous_contract = None
            if existing:
                previous_contract = json.loads(connection.execute(
                    "SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=? AND project_id=?",
                    (existing["active_evaluation_id"], project_identifier),
                ).fetchone()[0])
            contract = self.evaluation_contract(settings, workflow_directory, previous_contract)
            evaluation_identifier = existing["active_evaluation_id"] if existing else uuid.uuid4().hex
            if previous_contract is None or snapshot_hash(contract) != snapshot_hash(previous_contract):
                evaluation_identifier = uuid.uuid4().hex
            model_file_name = contract["workflow"]["model_identifier"].replace("\\", "/").rsplit("/", 1)[-1]
            model_folder = Path(model_file_name).stem
            validate_directory_name(model_folder)
            storage_binding = {
                "project_id": project_identifier, "workflow_identifier": settings["pipelineIdentifier"],
                "model_folder": model_folder, "project_folder": f"{settings['name']}__{project_identifier}",
                "root": "from_comfy_home_style", "state": "not_created", "folder_id": None,
            }
            if storage_binding_override is not None:
                storage_binding = storage_binding_override
            elif existing:
                previous_binding = json.loads(existing["storage_binding_json"])
                if previous_binding["state"] == "created":
                    if settings["name"] != json.loads(existing["settings_json"])["name"]:
                        raise StyleRevisionConflict("실제 출력 폴더는 프로젝트 관리 Rename으로 변경해야 합니다.")
                    storage_binding = previous_binding
            connection.execute(
                "INSERT INTO style_projects VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision, settings_json=excluded.settings_json, "
                "active_evaluation_id=excluded.active_evaluation_id, storage_binding_json=excluded.storage_binding_json, "
                "last_operation_id=excluded.last_operation_id, last_payload_hash=excluded.last_payload_hash, updated_at=excluded.updated_at",
                (project_identifier, existing["revision"] + 1 if existing else 1, encode_snapshot(settings), evaluation_identifier,
                 encode_snapshot(storage_binding), existing["creation_operation_id"] if existing else payload.operationIdentifier,
                 existing["creation_payload_hash"] if existing else payload_hash, payload.operationIdentifier, payload_hash,
                 existing["created_at"] if existing else saved_at, saved_at),
            )
            if previous_contract is None or evaluation_identifier != existing["active_evaluation_id"]:
                connection.execute("INSERT INTO style_evaluation_revisions VALUES(?,?,?,?,?)", (
                    evaluation_identifier, project_identifier, snapshot_hash(contract), encode_snapshot(contract), saved_at,
                ))
                if existing:
                    previous_generation = connection.execute(
                        "SELECT generation_number FROM style_evolution_timelines WHERE evaluation_id=?",
                        (existing["active_evaluation_id"],),
                    ).fetchone()
                    connection.execute("INSERT INTO style_evolution_timelines VALUES(?,?,?)", (
                        evaluation_identifier, project_identifier, previous_generation[0] if previous_generation else 1,
                    ))
            row = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
        return self.project_from_row(row)

    @staticmethod
    def evaluation_contract(settings: dict, workflow_directory: Path, previous_contract: dict | None) -> dict:
        """재현할 Workflow와 Case별 조건을 표시명·탐색 범위와 분리해 고정합니다."""

        if previous_contract:
            workflow_snapshot = previous_contract["workflow"]
        else:
            api_workflow, ui_workflow = load_workflows(workflow_directory, settings["pipelineIdentifier"])
            workflow_snapshot = {
                "identifier": settings["pipelineIdentifier"], "adapter_version": "anima-current-v1",
                "api": api_workflow, "ui": ui_workflow,
                "api_hash": snapshot_hash(api_workflow), "ui_hash": snapshot_hash(ui_workflow),
                "model_identifier": api_workflow["1"]["inputs"]["unet_name"],
            }
        return {
            "schema_version": 1, "workflow": workflow_snapshot, "vote_policy": "prompt-set-bundle-v1",
            "prompt_cases": StyleProjectStore.frozen_case_labels(settings["promptCases"], previous_contract), "negative_prompt": settings["negativePrompt"],
            "sampling": {field: settings[field] for field in ("seed", "width", "height", "steps", "cfg")},
            "prompt_resolution_policy": "freeze-per-case-before-render",
        }

    @staticmethod
    def frozen_case_labels(prompt_cases: list[dict], previous_contract: dict | None) -> list[dict]:
        """표시 이름만 바꿀 때 기존 불변 Snapshot과 평가 ID를 유지합니다."""

        previous_names = {prompt_case["identifier"]: prompt_case["name"] for prompt_case in (previous_contract or {}).get("prompt_cases", [])}
        return [{**prompt_case, "name": previous_names.get(prompt_case["identifier"], prompt_case["name"])} for prompt_case in prompt_cases]
