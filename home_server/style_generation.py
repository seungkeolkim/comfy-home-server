"""프로젝트 조건으로 고정 조합을 계획하고 CHS 요청에 연결합니다."""

import asyncio
import json
import random
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .output_directories import resolve_output_directory
from .output_roots import STYLE_OUTPUT_PREFIX, STYLE_OUTPUT_ROOT_NAME
from .style_generation_store import StyleGenerationStore
from .style_generation_sizing import MAXIMUM_RANDOM_COMBINATION_COUNT
from .style_lora_strength_policy import (
    FIXED_STYLE_LORA_CLIP_STRENGTH,
    STYLE_LORA_STRENGTH_POLICY_VERSION,
    fixed_clip_style_component,
    fixed_clip_style_lora_selections,
)
from .style_projects import ProjectSettings, StyleRevisionConflict, browser_sampling_settings, encode_snapshot, snapshot_hash
from .style_random_generation import RandomStyleGenerationPlanInput, combination_selection_fingerprint, draw_initial_combinations
from .tag_builder import resolve_anima_prompts
from .workflows import prepare_anima


ARTIST_INSERTION_MARKER = "STYLECOMPOSITIONARTISTSLOTFROZEN"


class StyleCandidateFavoriteInput(BaseModel):
    """전송 재시도가 상태를 다시 뒤집지 않도록 원하는 즐겨찾기 값을 받습니다."""

    model_config = ConfigDict(extra="forbid")
    isFavorite: StrictBool


class GenerationComponent(BaseModel):
    """프로젝트 성분과 STR을 받으며 LoRA CLIP은 계획에서 1로 정규화합니다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    identifier: str = Field(min_length=1, max_length=500)
    strength: float = Field(ge=-20, le=20)
    clip_strength: float | None = Field(default=None, ge=-20, le=20)


class FixedCombination(BaseModel):
    """이번 단계의 한 조합은 명시적인 성분 목록으로만 구성합니다."""

    model_config = ConfigDict(extra="forbid")
    components: list[GenerationComponent] = Field(default_factory=list, max_length=100)


class StyleGenerationPlanInput(BaseModel):
    """저장된 프로젝트 Revision에 묶인 소량 생성 계획을 요청합니다."""

    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    combinations: list[FixedCombination] = Field(min_length=1, max_length=2)


class StyleGenerationSubmitInput(BaseModel):
    """Preview로 확인한 계획의 제출·재시도를 구분합니다."""

    model_config = ConfigDict(extra="forbid")
    operationIdentifier: str = Field(min_length=16, max_length=100)
    retryFailedOnly: bool = False


class StylePromptRegenerationInput(BaseModel):
    """기존 조합을 고정하고 저장한 새 Prompt 조건에서 다시 그립니다."""

    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    candidateIdentifiers: list[str] = Field(min_length=1, max_length=MAXIMUM_RANDOM_COMBINATION_COUNT)


class StylePromptGenerationPlanInput(StyleGenerationPlanInput):
    """서버가 읽은 조합만 기존 생성 경로에 전달합니다."""

    combinations: list[FixedCombination] = Field(min_length=1, max_length=MAXIMUM_RANDOM_COMBINATION_COUNT)


def compose_artist_prompt(common_prompt: str, components: list[dict]) -> str:
    """작가 슬롯만 조합별로 치환하고 LoRA는 Prompt에 쓰지 않습니다."""

    artist_terms = []
    for component in components:
        if not component["identifier"].startswith("artist:"):
            continue
        artist_name = component["identifier"][len("artist:"):].replace("_", " ")
        artist_name = artist_name.replace("(", "\\(").replace(")", "\\)")
        artist_terms.append(f"(@{artist_name}:{component['strength']:g})")
    artist_prompt = ", ".join(artist_terms)
    if ARTIST_INSERTION_MARKER in common_prompt:
        return common_prompt.replace(ARTIST_INSERTION_MARKER, artist_prompt)
    return ", ".join(part for part in [common_prompt, artist_prompt] if part)


def combination_letter_label(combination_index: int) -> str:
    """조합이 26개를 넘어도 A..Z, AA..AZ 순서로 짧은 내부 Label을 만듭니다."""

    remaining_number = combination_index + 1
    letters = []
    while remaining_number:
        remaining_number, letter_index = divmod(remaining_number - 1, 26)
        letters.append(chr(ord("A") + letter_index))
    return "".join(reversed(letters))


class StyleGenerationService:
    """생성·관리 Rename을 직렬화하며 실제 작업은 Home Queue를 재사용합니다."""

    def __init__(self, server) -> None:
        """Worker와 파일 경로를 공유하는 Home 인스턴스를 보관합니다."""

        self.server = server
        self.store = StyleGenerationStore(server.database._connect)
        self.mutation_lock = threading.RLock()

    def recover_renames(self) -> None:
        """출력 목록 동기화 전에 미완료 프로젝트 Rename을 복구합니다."""

        from .style_project_rename import StyleProjectRenameService

        StyleProjectRenameService(self).recover()

    def options(self, project_identifier: str) -> dict:
        """저장된 범위 안의 두 강도 예시를 만들고 생성 전에 편집하게 합니다."""

        project = self.store.project(project_identifier)
        settings = ProjectSettings(**json.loads(project["settings_json"])).model_dump()
        combinations = []
        for strength_fraction in [1 / 3, 2 / 3]:
            components = []
            selected_counts = {"artist": 0, "lora": 0}
            for identifier, policy in settings["componentPolicies"].items():
                if not policy["enabled"]:
                    continue
                kind = identifier.split(":", 1)[0]
                if selected_counts[kind] >= settings[kind + "MaximumCount"]:
                    continue
                selected_counts[kind] += 1
                strength = policy["minimumStrength"] + (policy["maximumStrength"] - policy["minimumStrength"]) * strength_fraction
                components.append(fixed_clip_style_component(identifier, round(strength, 6)))
            combinations.append({"components": components})
        if combinations[0] == combinations[1]:
            combinations = combinations[:1]
        return {"projectRevision": project["revision"], "settings": browser_sampling_settings(settings), "combinations": combinations}

    async def preflight(self, workflow: dict, components: list[dict]) -> None:
        """현재 설치된 LoRA와 실제 Saver 의존 Node를 제출 전에 확인합니다."""

        installed_loras = set(await self.server.comfy.list_loras())
        for component in components:
            if component["identifier"].startswith("lora:") and component["identifier"][5:] not in installed_loras:
                raise ValueError(f"ComfyUI에서 LoRA를 찾을 수 없습니다: {component['identifier'][5:]}")
        required_nodes = set()

        def collect_dependencies(node_identifier: str) -> None:
            """정의만 존재하는 미사용 Node는 의존성 검사에 포함하지 않습니다."""

            if node_identifier in required_nodes:
                return
            required_nodes.add(node_identifier)
            for input_value in workflow[node_identifier]["inputs"].values():
                if isinstance(input_value, list) and len(input_value) == 2 and isinstance(input_value[0], str) and input_value[0] in workflow:
                    collect_dependencies(input_value[0])

        collect_dependencies("13")
        for class_type in sorted({workflow[node_identifier]["class_type"] for node_identifier in required_nodes}):
            node_info = await self.server.comfy.request_json("GET", "/object_info/" + quote(class_type, safe=""))
            if class_type not in node_info:
                raise ValueError(f"ComfyUI에 필요한 Node가 없습니다: {class_type}")
            required_inputs = node_info[class_type].get("input", {}).get("required", {})
            for node_identifier in required_nodes:
                node = workflow[node_identifier]
                if node["class_type"] != class_type:
                    continue
                for input_name in ("unet_name", "clip_name", "vae_name"):
                    specification = required_inputs.get(input_name)
                    if specification and isinstance(specification[0], list) and node["inputs"].get(input_name) not in specification[0]:
                        raise ValueError(f"등록 Workflow의 모델 파일을 찾을 수 없습니다: {node['inputs'].get(input_name)}")

    async def create_prompt_regeneration_plan(self, project_identifier: str, payload: StylePromptRegenerationInput) -> dict:
        """이전 조건의 활성 조합·독립 STR을 읽고 새 조건의 별도 평가 계획을 만듭니다."""

        if len(set(payload.candidateIdentifiers)) != len(payload.candidateIdentifiers):
            raise ValueError("같은 조합을 중복 선택할 수 없습니다.")
        source_candidates = []
        with self.server.database._connect() as connection:
            for identifier in payload.candidateIdentifiers:
                row = connection.execute(
                    "SELECT candidates.* FROM style_candidates AS candidates JOIN style_candidate_memberships USING(candidate_id) "
                    "WHERE project_id=? AND candidate_id=? AND lifecycle='active' "
                    "AND EXISTS(SELECT 1 FROM style_candidate_renders WHERE candidate_id=candidates.candidate_id)",
                    (project_identifier, identifier),
                ).fetchone()
                if not row:
                    raise LookupError("다시 그릴 프로젝트의 조합을 찾을 수 없습니다.")
                source_candidates.append(dict(row))
        if len({candidate["evaluation_id"] for candidate in source_candidates}) != 1:
            raise ValueError("같은 Prompt 조건의 조합을 선택해 주세요.")
        source = {"mode": "prompt-regeneration", "sourceEvaluationIdentifier": source_candidates[0]["evaluation_id"],
                  "sourceCandidateIdentifiers": payload.candidateIdentifiers,
                  "sourceComponents": [json.loads(candidate["components_json"]) for candidate in source_candidates]}
        combinations = []
        for components in source["sourceComponents"]:
            frozen_components = []
            for component in components:
                frozen_component = dict(component)
                frozen_component.pop("file_identity", None)
                frozen_components.append(frozen_component)
            combinations.append({"components": frozen_components})
        plan_input = StylePromptGenerationPlanInput(expectedRevision=payload.expectedRevision,
            operationIdentifier=payload.operationIdentifier, combinations=combinations)
        return await self.create_plan(project_identifier, plan_input, regeneration_source=source)

    async def create_plan(self, project_identifier: str, payload: StyleGenerationPlanInput | RandomStyleGenerationPlanInput, *, evolution_context: dict | None = None, regeneration_source: dict | None = None) -> dict:
        """Case별 공통 전개를 한 번 고정하고 후보 간 동일 조건을 저장합니다."""

        request_body = payload.model_dump()
        if regeneration_source:
            request_body["regenerationSource"] = regeneration_source
        request_hash = snapshot_hash(request_body)
        with self.server.database._connect() as connection:
            existing = connection.execute("SELECT plan_id,payload_hash FROM style_generation_plans WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
        if existing:
            if request_hash != existing["payload_hash"]:
                raise StyleRevisionConflict("같은 요청 ID의 생성 계획이 이미 다르게 저장됐습니다.")
            return self.store.plan(existing["plan_id"], project_identifier)
        project = self.store.project(project_identifier)
        if project["revision"] != payload.expectedRevision:
            raise StyleRevisionConflict("프로젝트가 변경됐습니다. 저장한 최신 설정으로 다시 계획해 주세요.")
        settings = ProjectSettings(**json.loads(project["settings_json"])).model_dump()
        selection = {"mode": "manual"}
        if regeneration_source:
            selection = dict(regeneration_source)
            selection.pop("sourceComponents")
        if regeneration_source and regeneration_source["sourceEvaluationIdentifier"] == project["active_evaluation_id"]:
            raise ValueError("Prompt나 생성 조건을 변경해 저장한 뒤 다시 그려 주세요.")
        if isinstance(payload, RandomStyleGenerationPlanInput):
            with self.server.database._connect() as connection:
                previous_candidates = connection.execute("SELECT components_json FROM style_candidates WHERE project_id=? AND evaluation_id=?", (project_identifier, project["active_evaluation_id"])).fetchall()
            existing_fingerprints = {combination_selection_fingerprint(json.loads(candidate[0])) for candidate in previous_candidates}
            selection_seed = snapshot_hash({"projectIdentifier": project_identifier, "operationIdentifier": payload.operationIdentifier})
            component_sets, selection = draw_initial_combinations(settings, payload.combinationCount, selection_seed, existing_fingerprints)
            if not component_sets:
                raise ValueError("중복을 제외하고 새 조합을 찾지 못했습니다. 사용 성분·개수·STR 범위를 넓히거나 다른 추첨을 시도해 주세요. 생성 작업은 접수하지 않았습니다.")
        else:
            component_sets = [combination.model_dump(exclude_none=True)["components"] for combination in payload.combinations]
        fingerprints = set()
        for components in component_sets:
            for kind, label in (("artist", "작가"), ("lora", "LoRA")):
                component_count = sum(component["identifier"].startswith(kind + ":") for component in components)
                if not regeneration_source and not settings[kind + "MinimumCount"] <= component_count <= settings[kind + "MaximumCount"]:
                    raise ValueError(f"{label} 사용 개수가 프로젝트의 최소·최대 범위를 벗어났습니다.")
            identifiers = set()
            for component in components:
                identifier = component["identifier"]
                policy = settings["componentPolicies"].get(identifier)
                if not regeneration_source and (not policy or not policy["enabled"]):
                    raise ValueError(f"프로젝트에서 사용하도록 선택하지 않은 성분입니다: {identifier}")
                if identifier in identifiers:
                    raise ValueError("같은 조합에 성분을 중복 넣을 수 없습니다.")
                identifiers.add(identifier)
                if not regeneration_source and not policy["minimumStrength"] <= component["strength"] <= policy["maximumStrength"]:
                    raise ValueError(f"프로젝트 STR 범위를 벗어났습니다: {identifier}")
                if "clip_strength" in component and not identifier.startswith("lora:"):
                    raise ValueError("작가에는 CLIP 강도를 별도로 지정할 수 없습니다.")
                if identifier.startswith("lora:"):
                    component["clip_strength"] = FIXED_STYLE_LORA_CLIP_STRENGTH
            fingerprint = combination_selection_fingerprint(components)
            if not regeneration_source and fingerprint in fingerprints:
                raise ValueError("A/B 조합이 동일합니다. 범위 안에서 강도나 포함 성분을 다르게 선택해 주세요.")
            fingerprints.add(fingerprint)
        with self.server.database._connect() as connection:
            evaluation = connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=? AND project_id=?", (project["active_evaluation_id"], project_identifier)).fetchone()
            generation_number = self.server.style_evolution.store.current_generation_number(connection, project["active_evaluation_id"])
            if not evolution_context and self.server.style_evolution.store.find_open_evolution_batch(connection, project["active_evaluation_id"]):
                raise StyleRevisionConflict("진화를 확정하거나 취소한 뒤 일반 조합을 추가해 주세요.")
        contract = json.loads(evaluation[0])
        await self.preflight(contract["workflow"]["api"], [component for components in component_sets for component in components])
        lora_names = [component["identifier"][5:] for components in component_sets for component in components if component["identifier"].startswith("lora:")]
        identities = await self.server.comfy.lora_identities(lora_names)
        if regeneration_source:
            for components in regeneration_source["sourceComponents"]:
                for component in components:
                    previous_identity = component.get("file_identity")
                    if not previous_identity or not previous_identity.get("sha256"):
                        continue
                    current_identity = identities.get(component["identifier"][5:].replace("\\", "/"))
                    if not current_identity or any(previous_identity.get(field) != current_identity.get(field) for field in ("sha256", "file_size", "modified")):
                        raise ValueError("기존 조합의 LoRA 파일이 변경됐습니다. 파일을 확인한 뒤 다시 시도해 주세요.")
        for components in component_sets:
            for component in components:
                if component["identifier"].startswith("lora:"):
                    component["file_identity"] = identities.get(component["identifier"][5:].replace("\\", "/"))
        resolved_cases = []
        for case_index, prompt_case in enumerate(contract["prompt_cases"] if not evolution_context else []):
            resolution_seed = random.Random(f"{contract['sampling']['seed']}:{prompt_case['identifier']}").randrange(2**31)
            body = {"prompt": prompt_case["prompt"].replace("{artist}", ARTIST_INSERTION_MARKER),
                    "negative": "\n".join(part for part in [contract["negative_prompt"], prompt_case.get("negativePrompt", "")] if part)}
            positive_template, negative_template, _, _ = resolve_anima_prompts(body, [], resolution_seed)
            resolved_cases.append({
                "identifier": prompt_case["identifier"], "name": prompt_case["name"], "index": case_index + 1,
                "prompt": await self.server.comfy.populate_wildcards(positive_template, resolution_seed),
                "negative": await self.server.comfy.populate_wildcards(negative_template, resolution_seed),
                "resolutionSeed": resolution_seed,
            })
        if evolution_context:
            resolved_cases = evolution_context["resolvedCases"]
            generation_number = evolution_context["targetGeneration"]
            selection = {"mode": "evolution", **evolution_context["provenance"], "batchIdentifier": evolution_context["identifier"]}
        selection.update(loraStrengthPolicy=STYLE_LORA_STRENGTH_POLICY_VERSION, loraClipStrength=FIXED_STYLE_LORA_CLIP_STRENGTH)
        plan_identifier = uuid.uuid4().hex
        candidates = [{"identifier": uuid.uuid4().hex, "label": combination_letter_label(index), "components": components} for index, components in enumerate(component_sets)]
        plan = {"projectIdentifier": project_identifier, "evaluationIdentifier": project["active_evaluation_id"],
                "cases": resolved_cases, "candidates": candidates, "sampling": contract["sampling"],
                "workflowHash": contract["workflow"]["api_hash"], "imageCount": len(candidates) * len(resolved_cases), "selection": selection, "generationNumber": generation_number}
        with self.mutation_lock, self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT plan_id,payload_hash FROM style_generation_plans WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 생성 계획을 저장할 수 없습니다.")
                return self.store.plan(existing["plan_id"], project_identifier)
            current = connection.execute("SELECT revision FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
            if current[0] != project["revision"]:
                raise StyleRevisionConflict("계획 중 프로젝트가 변경됐습니다. 새 설정으로 다시 계획해 주세요.")
            if regeneration_source:
                for identifier in regeneration_source["sourceCandidateIdentifiers"]:
                    membership = connection.execute("SELECT lifecycle FROM style_candidate_memberships WHERE candidate_id=?", (identifier,)).fetchone()
                    if not membership or membership[0] != "active":
                        raise StyleRevisionConflict("원본 조합이 변경됐습니다. 최신 목록에서 다시 선택해 주세요.")
            if not evolution_context and (self.server.style_evolution.store.find_open_evolution_batch(connection, project["active_evaluation_id"]) or generation_number != self.server.style_evolution.store.current_generation_number(connection, project["active_evaluation_id"])):
                raise StyleRevisionConflict("계획 중 세대 상태가 바뀌었습니다. 최신 세대에서 다시 시작해 주세요.")
            if selection["mode"] == "random":
                previous_candidates = connection.execute("SELECT components_json FROM style_candidates WHERE project_id=? AND evaluation_id=?", (project_identifier, project["active_evaluation_id"])).fetchall()
                current_fingerprints = {combination_selection_fingerprint(json.loads(candidate[0])) for candidate in previous_candidates}
                if fingerprints & current_fingerprints:
                    raise StyleRevisionConflict("다른 Preview에서 같은 조합을 먼저 준비했습니다. 다시 뽑아 확인해 주세요.")
            previous_count = connection.execute(
                "SELECT COUNT(*) FROM style_candidate_memberships JOIN style_candidates USING(candidate_id) WHERE project_id=? AND generation_number=?",
                (project_identifier, generation_number),
            ).fetchone()[0]
            for candidate_index, candidate in enumerate(candidates, previous_count + 1):
                candidate["combinationNumber"] = candidate_index
                candidate["displayName"] = f"세대{generation_number:03}-조합{candidate_index:02}"
            connection.execute("INSERT INTO style_generation_plans VALUES(?,?,?,?,?,?,?,?)", (
                plan_identifier, project_identifier, project["active_evaluation_id"], project["revision"], payload.operationIdentifier,
                request_hash, encode_snapshot(plan), datetime.now(timezone.utc).isoformat(),
            ))
            for candidate in candidates:
                connection.execute("INSERT INTO style_candidates VALUES(?,?,?,?,?,?,?)", (
                    candidate["identifier"], project_identifier, project["active_evaluation_id"], plan_identifier,
                    candidate["label"], encode_snapshot(candidate["components"]), snapshot_hash(candidate["components"]),
                ))
                if not evolution_context:
                    connection.execute("INSERT INTO style_candidate_memberships VALUES(?,?,?,?,?,?,?)", (candidate["identifier"], project["active_evaluation_id"], generation_number, "active", None, selection["mode"], "[]"))
            if evolution_context:
                self.server.style_evolution.register_evolution_plan(connection, plan_identifier, candidates, evolution_context)
        return self.store.plan(plan_identifier, project_identifier)

    async def preflight_plan(self, project_identifier: str, plan_identifier: str, retry: bool) -> None:
        """제출 직전에도 파일 Identity와 Node를 확인하며 이전 성공 요청은 재제출하지 않습니다."""

        plan = self.store.plan(plan_identifier, project_identifier)
        if plan["jobIdentifiers"] and not retry:
            return
        with self.server.database._connect() as connection:
            row = connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=? AND project_id=?", (plan["evaluationIdentifier"], project_identifier)).fetchone()
        components = [component for candidate in plan["candidates"] for component in candidate["components"]]
        await self.preflight(json.loads(row[0])["workflow"]["api"], components)
        file_names = [component["identifier"][5:] for component in components if component["identifier"].startswith("lora:")]
        identities = await self.server.comfy.lora_identities(file_names)
        for component in components:
            previous = component.get("file_identity")
            if not previous or not previous.get("sha256"):
                continue
            current = identities.get(component["identifier"][5:].replace("\\", "/"))
            if not current or any(previous.get(field) != current.get(field) for field in ("sha256", "file_size", "modified")):
                raise ValueError(f"계획한 LoRA 파일 정보가 바뀌었거나 확인되지 않습니다. 새 계획을 확인해 주세요: {component['identifier']}")

    def submit_plan(self, project_identifier: str, plan_identifier: str, payload: StyleGenerationSubmitInput) -> tuple[str, list[dict]]:
        """확인한 계획만 원자적으로 Job·Render에 연결하고 중복 제출을 막습니다."""

        with self.mutation_lock, self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT job_id,plan_id,project_id FROM style_job_ownership WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["plan_id"] != plan_identifier or existing["project_id"] != project_identifier:
                    raise StyleRevisionConflict("다른 생성 요청에 사용한 Operation ID입니다.")
                return existing["job_id"], []
            plan = self.store.plan(plan_identifier, project_identifier)
            project = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
            if not payload.retryFailedOnly and (project["active_evaluation_id"] != plan["evaluationIdentifier"] or project["revision"] != plan["projectRevision"]):
                raise StyleRevisionConflict("계획 이후 프로젝트가 변경됐습니다. 새 계획을 확인해 주세요.")
            if connection.execute("SELECT 1 FROM style_project_renames WHERE project_id=? AND state!='completed'", (project_identifier,)).fetchone():
                raise StyleRevisionConflict("프로젝트 폴더 이름 변경을 마친 뒤 생성해 주세요.")
            if plan["jobIdentifiers"] and not payload.retryFailedOnly:
                return plan["jobIdentifiers"][0], []
            self.server.style_evolution.prepare_plan_submission(connection, project_identifier, plan, payload.retryFailedOnly)
            generation_number = plan.get("generationNumber", 1)
            binding = json.loads(project["storage_binding_json"])
            project_directory = resolve_output_directory(self.server.style_output_directory, f"{binding['model_folder']}/{binding['project_folder']}", must_exist=False)
            project_directory.mkdir(parents=True, exist_ok=True)
            binding = self.ensure_managed_folders(connection, project_identifier, binding)
            connection.execute("UPDATE style_projects SET storage_binding_json=? WHERE project_id=?", (encode_snapshot(binding), project_identifier))
            sequence = connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM style_job_ownership WHERE project_id=?", (project_identifier,)).fetchone()[0]
            generation_sequence = connection.execute(
                "SELECT COUNT(*)+1 FROM style_job_ownership JOIN style_generation_plans USING(plan_id) WHERE style_job_ownership.project_id=? AND COALESCE(json_extract(plan_json,'$.generationNumber'),1)=?",
                (project_identifier, generation_number),
            ).fetchone()[0]
            job_identifier = uuid.uuid4().hex
            common_detail = {"body": {"prompt": "스타일 구성 · 저장된 Prompt 묶음", "negative": ""},
                             "settings": plan["sampling"], "loras": [], "selected_tags": [], "style_plan_identifier": plan_identifier}
            requests = []
            render_records = []
            for candidate_index, candidate in enumerate(plan["candidates"], 1):
                membership = connection.execute("SELECT lifecycle FROM style_candidate_memberships WHERE candidate_id=?", (candidate["identifier"],)).fetchone()
                if membership and membership[0] in {"deleting", "deleted"}:
                    continue
                combination_number = candidate.get("combinationNumber", candidate_index)
                for prompt_case in plan["cases"]:
                    previous = connection.execute(
                        "SELECT status FROM style_candidate_renders JOIN job_requests USING(request_id) "
                        "WHERE candidate_id=? AND case_id=? ORDER BY style_candidate_renders.rowid DESC LIMIT 1",
                        (candidate["identifier"], prompt_case["identifier"]),
                    ).fetchone()
                    if payload.retryFailedOnly and (not previous or previous[0] not in {"failed", "cancelled"}):
                        continue
                    render_identifier = uuid.uuid4().hex
                    request_identifier = uuid.uuid4().hex
                    output_stem = f"{STYLE_OUTPUT_PREFIX}{binding['model_folder']}/{binding['project_folder']}/세대{generation_number:03}-조합{combination_number:02}-Prompt{prompt_case['index']:02}-{render_identifier}"
                    render_plan = {"projectIdentifier": project_identifier, "candidateIdentifier": candidate["identifier"], "components": candidate["components"],
                                   "case": prompt_case, "sampling": plan["sampling"], "evaluationIdentifier": plan["evaluationIdentifier"], "generationNumber": generation_number}
                    detail = {**common_detail, "resolved": {"style_render_identifier": render_identifier}}
                    requests.append({"request_id": request_identifier, "job_id": job_identifier, "workflow": "anima", "status": "submitting", "output_stem": output_stem, "detail": detail})
                    render_records.append((render_identifier, candidate["identifier"], plan_identifier, prompt_case["identifier"], request_identifier, encode_snapshot(render_plan)))
            if not requests:
                raise StyleRevisionConflict("실패·취소가 확인된 재시도 대상이 없습니다. 미확인 요청은 자동 재제출하지 않습니다.")
            self.server.database.add_job(job_identifier, "anima", f"세대{generation_number:03}-{generation_sequence:02} 이미지 생성", requests, binding["folder_id"], origin="style", connection=connection)
            connection.execute("INSERT INTO style_job_ownership VALUES(?,?,?,?,?)", (job_identifier, project_identifier, plan_identifier, payload.operationIdentifier, sequence))
            connection.executemany("INSERT INTO style_candidate_renders VALUES(?,?,?,?,?,?)", render_records)
        return job_identifier, requests

    @staticmethod
    def ensure_managed_folders(connection, project_identifier: str, binding: dict) -> dict:
        """모델·프로젝트 분류를 자동 생성하고 사용자의 일반 분류를 가져오지 않습니다."""

        if binding.get("folder_id"):
            return {**binding, "state": "created"}
        model_row = connection.execute("SELECT folder_id FROM style_managed_folders WHERE model_identifier=? AND project_id IS NULL", (binding["model_folder"],)).fetchone()
        if model_row:
            model_folder_identifier = model_row[0]
        else:
            if connection.execute("SELECT 1 FROM job_folders WHERE parent_id IS NULL AND name=?", (binding["model_folder"],)).fetchone():
                raise StyleRevisionConflict("같은 이름의 일반 작업분류가 있습니다. 일반 분류의 이름을 바꾼 뒤 다시 생성해 주세요.")
            model_folder_identifier = uuid.uuid4().hex
            connection.execute("INSERT INTO job_folders VALUES(?,?,NULL)", (model_folder_identifier, binding["model_folder"]))
            connection.execute("INSERT INTO style_managed_folders VALUES(?,?,NULL)", (model_folder_identifier, binding["model_folder"]))
        project_folder_identifier = uuid.uuid4().hex
        connection.execute("INSERT INTO job_folders VALUES(?,?,?)", (project_folder_identifier, binding["project_folder"], model_folder_identifier))
        connection.execute("INSERT INTO style_managed_folders VALUES(?,?,?)", (project_folder_identifier, binding["model_folder"], project_identifier))
        return {**binding, "folder_id": project_folder_identifier, "state": "created"}

    def prepare_request(self, request: dict) -> dict:
        """공통 Adapter에 STR·고정 CLIP 1을 전달하고 실제 Graph를 기록합니다."""

        render_identifier = request["detail"]["resolved"]["style_render_identifier"]
        with self.server.database._connect() as connection:
            row = connection.execute("SELECT render_plan_json FROM style_candidate_renders WHERE render_id=? AND request_id=?", (render_identifier, request["request_id"])).fetchone()
            render_plan = json.loads(row[0])
            contract = json.loads(connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=?", (render_plan["evaluationIdentifier"],)).fetchone()[0])
        prompt_text = compose_artist_prompt(render_plan["case"]["prompt"], render_plan["components"])
        selected_loras = fixed_clip_style_lora_selections(render_plan["components"])
        request_workflow, metadata_workflow = prepare_anima(contract["workflow"]["api"], contract["workflow"]["ui"], prompt_text,
                                                          render_plan["case"]["negative"], render_plan["sampling"], selected_loras, request["output_stem"])
        prepared = {"prompt": prompt_text, "negative": render_plan["case"]["negative"], "settings": render_plan["sampling"],
                    "loras": selected_loras, "wildcard_seed": render_plan["case"]["resolutionSeed"], "tag_seed": render_plan["case"]["resolutionSeed"],
                    "selected_path": [], "negative_selected_path": [], "style_render_identifier": render_identifier,
                    "prepared_graph": request_workflow, "metadata_workflow": metadata_workflow}
        prepared["style_context"] = {"project_id": render_plan["projectIdentifier"], "evaluation_id": render_plan["evaluationIdentifier"],
                                     "candidate_id": render_plan["candidateIdentifier"], "render_id": render_identifier,
                                     "case_id": render_plan["case"]["identifier"], "generation": render_plan.get("generationNumber", 1)}
        prepared["style_context"]["component_identities"] = {component["identifier"]: component.get("file_identity") for component in render_plan["components"] if component["identifier"].startswith("lora:")}
        with self.server.database._connect() as connection:
            connection.execute("UPDATE request_results SET result_json=? WHERE request_id=?", (encode_snapshot(prepared), request["request_id"]))
        return prepared
