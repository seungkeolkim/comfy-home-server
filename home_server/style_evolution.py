"""다음 세대의 계획·생성·고정 부모 선별·확정·취소를 연결합니다."""

import copy
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .style_evolution_breeding import draw_evolution_children
from .style_evolution_selection import STYLELAB_SELECTION_POLICY, build_selection_ranking, next_selection_pair, synchronize_selection_statistics
from .style_evolution_store import StyleEvolutionStore
from .style_generation import FixedCombination, StyleGenerationPlanInput
from .style_generation_sizing import DEFAULT_EVOLUTION_CHILD_COUNT, MAXIMUM_EVOLUTION_CHILD_COUNT
from .style_projects import ProjectSettings, StyleRevisionConflict, encode_snapshot, snapshot_hash
from .style_voting import ranked_candidate_statistics
from .style_voting_rules import boundary_tie_match, candidate_is_rated, initial_candidate_statistics
from .style_component_statistics import inherited_component_statistics


class EvolutionPlanInput(BaseModel):
    """현재 프로젝트·평가 Revision을 기준으로 실제 자녀 수를 준비합니다."""

    model_config = ConfigDict(extra="forbid")
    operationIdentifier: str = Field(min_length=16, max_length=100)
    expectedProjectRevision: int = Field(ge=1)
    expectedVotingRevision: int = Field(ge=1)
    childCount: int = Field(default=DEFAULT_EVOLUTION_CHILD_COUNT, ge=1, le=MAXIMUM_EVOLUTION_CHILD_COUNT)


class EvolutionGenerationPlanInput(StyleGenerationPlanInput):
    """일반 고정 A/B API의 제한을 바꾸지 않고 내부 진화 조합을 전달합니다."""

    combinations: list[FixedCombination] = Field(min_length=1, max_length=MAXIMUM_EVOLUTION_CHILD_COUNT)


class EvolutionActionInput(BaseModel):
    """확정·취소 대상 Batch와 최신 평가 Revision을 명시합니다."""

    model_config = ConfigDict(extra="forbid")
    operationIdentifier: str = Field(min_length=16, max_length=100)
    expectedVotingRevision: int = Field(ge=1)


class StyleEvolutionService:
    """모든 Score·후보 상태 전환을 같은 DB Transaction에서 처리합니다."""

    def __init__(self, server) -> None:
        """기존 생성·투표 서비스와 관리 이미지 경로를 공유합니다."""

        self.server = server
        self.store = StyleEvolutionStore(server)

    def migrate_parent_selection(self, connection, project_identifier: str, evaluation_identifier: str, state: dict) -> bool:
        """미확정 Batch를 고정 부모 기준으로 복원하며 기존 Vote·Undo 기록은 보존합니다."""

        row = self.store.find_open_evolution_batch(connection, evaluation_identifier)
        if not row or row["project_id"] != project_identifier:
            return False
        batch = json.loads(row["batch_json"])
        parent_policy = {
            "placement_policy": STYLELAB_SELECTION_POLICY,
            "reference_ids": batch["parent_ids"],
            "reference_scores": batch["parent_scores"],
        }
        if any(batch.get(field) != value for field, value in parent_policy.items()):
            batch.update(copy.deepcopy(parent_policy))
            connection.execute("UPDATE style_evolution_batches SET batch_json=? WHERE batch_id=?", (encode_snapshot(batch), row["batch_id"]))
        if row["status"] != "active":
            return False
        selection = state.get("evolution")
        if not selection or selection["batch_id"] != row["batch_id"]:
            raise RuntimeError("진화 Batch와 선별 상태가 일치하지 않습니다.")
        before = encode_snapshot(state)
        policy_changed = any(selection.get(field) != value for field, value in parent_policy.items())
        selection.update(copy.deepcopy(parent_policy))
        if policy_changed:
            state["match"] = None
        synchronize_selection_statistics(state)
        if policy_changed:
            _, ready_identifiers = self.server.style_voting.load_evaluation_candidates(connection, project_identifier, evaluation_identifier)
            self.server.style_voting.synchronize_candidates(state, [], ready_identifiers)
        return encode_snapshot(state) != before

    def migrate_pending_placements(self) -> None:
        """서버 시작 때 진행·계획 중 Batch만 갱신해 확정 이력과 실제 파일은 건드리지 않습니다."""

        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT project_id,evaluation_id FROM style_evolution_batches WHERE status IN ('planned','active')").fetchall()
            for row in rows:
                arena = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?", (row["evaluation_id"],)).fetchone()
                if not arena:
                    raise RuntimeError("진화 Batch의 선별 상태를 찾을 수 없습니다.")
                state = json.loads(arena["state_json"])
                if self.migrate_parent_selection(connection, row["project_id"], row["evaluation_id"], state):
                    self.server.style_voting.save_arena(connection, row["evaluation_id"], arena["revision"] + 1, state)

    def load_evolution_context(self, connection, project_identifier: str, evaluation_identifier: str, *, verify_files: bool = True) -> tuple[dict, int, dict, list[dict], list[str]]:
        """평가 소유·현재 Arena·준비된 활성 조합을 같은 연결에서 읽습니다."""

        project = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
        if not project:
            raise LookupError("프로젝트를 찾을 수 없습니다.")
        candidates, ready_identifiers = self.server.style_voting.load_evaluation_candidates(connection, project_identifier, evaluation_identifier, verify_files=verify_files)
        revision, state = self.server.style_voting.load_arena(connection, project_identifier, evaluation_identifier)
        before = encode_snapshot(state)
        if verify_files:
            self.server.style_voting.synchronize_candidates(state, candidates, ready_identifiers)
        else:
            self.server.style_voting.synchronize_available_match(state, candidates, ready_identifiers)
        if encode_snapshot(state) != before:
            revision += 1
            self.server.style_voting.save_arena(connection, evaluation_identifier, revision, state)
        return dict(project), revision, state, candidates, ready_identifiers

    def evolution_blockers(self, connection, project: dict, evaluation_identifier: str, state: dict, candidates: list[dict], ready_identifiers: list[str]) -> list[str]:
        """최소 평가 수·미배치 후보·동점·진행 작업을 숨기지 않고 안내합니다."""

        messages = []
        if project["active_evaluation_id"] != evaluation_identifier:
            messages.append("현재 프로젝트의 생성 조건에서 다음 세대를 만들 수 있습니다.")
        ready_set = set(ready_identifiers)
        rated = [candidate["identifier"] for candidate in candidates if candidate["identifier"] in ready_set and candidate_is_rated(state["statistics"][candidate["identifier"]])]
        if len(rated) < 10:
            messages.append(f"평가된 그림체 10개가 필요합니다. 현재 {len(rated)}개이며 {10 - len(rated)}개를 더 평가해 주세요.")
        waiting = [candidate for candidate in candidates if candidate["identifier"] not in ready_set or not candidate_is_rated(state["statistics"][candidate["identifier"]])]
        if waiting:
            messages.append(f"생성·신규 배치를 마치지 않은 그림체 {len(waiting)}개를 먼저 완료해 주세요.")
        if len(rated) >= 10 and boundary_tie_match(state, rated):
            messages.append("상위 30% 경계의 동점을 선별에서 먼저 해소해 주세요.")
        active_request = connection.execute("SELECT 1 FROM style_candidate_renders JOIN style_candidates USING(candidate_id) JOIN job_requests USING(request_id) WHERE project_id=? AND evaluation_id=? AND job_requests.status IN ('submitting','pending','running','cancelling') LIMIT 1", (project["project_id"], evaluation_identifier)).fetchone()
        if active_request:
            messages.append("이 프로젝트의 진행 중 생성·취소 작업을 먼저 마쳐 주세요.")
        if connection.execute("SELECT 1 FROM style_voting_commands WHERE project_id=? AND evaluation_id=? AND action='delete' AND json_extract(response_json,'$.status')='deleting'", (project["project_id"], evaluation_identifier)).fetchone():
            messages.append("완료되지 않은 조합 폐기를 먼저 마쳐 주세요.")
        settings = ProjectSettings(**json.loads(project["settings_json"]))
        if settings.artistMaximumCount + settings.loraMaximumCount == 0 or not any(policy.enabled for policy in settings.componentPolicies.values()):
            messages.append("진화할 작가 또는 LoRA 성분을 하나 이상 허용해 주세요.")
        return messages

    def read_evolution(self, project_identifier: str, evaluation_identifier: str) -> dict:
        """현재 세대·진행 Batch·필요 평가량과 마지막 확정 결과를 조회합니다."""

        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project, revision, state, candidates, ready_identifiers = self.load_evolution_context(connection, project_identifier, evaluation_identifier, verify_files=False)
            row = self.store.find_open_evolution_batch(connection, evaluation_identifier)
            generation_number = self.store.current_generation_number(connection, evaluation_identifier)
            rated_count = sum(candidate_is_rated(state["statistics"][identifier]) for identifier in ready_identifiers)
            messages = self.evolution_blockers(connection, project, evaluation_identifier, state, candidates, ready_identifiers) if not row else []
            batch_view = self.build_batch_view(connection, row, state, ready_identifiers) if row else None
            latest = connection.execute("SELECT result_json FROM style_evolution_batches WHERE evaluation_id=? AND status='confirmed' ORDER BY rowid DESC LIMIT 1", (evaluation_identifier,)).fetchone()
            checkpoints = [dict(checkpoint) for checkpoint in connection.execute("SELECT generation_number,created_at FROM style_generation_checkpoints WHERE evaluation_id=? ORDER BY generation_number", (evaluation_identifier,))]
            ranked = ranked_candidate_statistics(ready_identifiers, state["statistics"])
            rated = [candidate for candidate in ranked if candidate["rated"]]
            parent_identifiers = [candidate["identifier"] for candidate in rated[:len(rated) * 3 // 10]] if len(rated) >= 10 else []
            if row:
                parent_identifiers = json.loads(row["batch_json"])["parent_ids"]
            pending_requests = connection.execute(
                "SELECT COUNT(*) FROM style_candidate_renders JOIN style_candidates USING(candidate_id) JOIN job_requests USING(request_id) "
                "WHERE project_id=? AND evaluation_id=? AND job_requests.status IN ('submitting','pending','running','cancelling')",
                (project_identifier, evaluation_identifier),
            ).fetchone()[0]
            return {"projectIdentifier": project_identifier, "evaluationIdentifier": evaluation_identifier, "projectRevision": project["revision"], "votingRevision": revision,
                    "currentGeneration": generation_number, "evaluatedCount": rated_count, "minimumEvaluatedCount": 10, "canPrepare": not row and not messages,
                    "candidateCount": len(candidates), "readyCandidateCount": len(ready_identifiers), "pendingRequestCount": pending_requests,
                    "parentCandidateIdentifiers": parent_identifiers, "history": self.read_generation_history(connection, evaluation_identifier),
                    "blockers": messages, "batch": batch_view, "lastConfirmed": json.loads(latest[0]) if latest else None, "checkpoints": checkpoints}

    @staticmethod
    def read_generation_history(connection, evaluation_identifier: str) -> list[dict]:
        """기존 Batch 결과에서 세대별 생존·탈락과 원본 후보 ID만 조회합니다."""

        history = []
        for row in connection.execute("SELECT * FROM style_evolution_batches WHERE evaluation_id=? AND status IN ('confirmed','cancelled') ORDER BY rowid DESC", (evaluation_identifier,)):
            batch = json.loads(row["batch_json"])
            result = json.loads(row["result_json"] or "{}")
            surviving = set(result.get("survivingIdentifiers", []))
            history.append({"batchIdentifier": row["batch_id"], "operationIdentifier": row["operation_id"], "status": row["status"],
                "sourceGeneration": batch["sourceGeneration"], "targetGeneration": batch["targetGeneration"],
                "candidateIdentifiers": batch["candidate_ids"], "parentIdentifiers": batch["parent_ids"],
                "enteredIdentifiers": [identifier for identifier in batch["candidate_ids"] if identifier in surviving],
                "enteredCount": result.get("enteredCount", 0), "failedCount": result.get("failedCount", 0),
                "childCount": len(batch["candidate_ids"]), "createdAt": row["created_at"]})
        return history

    def build_batch_view(self, connection, row, state: dict, ready_identifiers: list[str]) -> dict:
        """성분 목록 없이 자녀 준비 수와 확정에 필요한 상태를 반환합니다."""

        batch = json.loads(row["batch_json"])
        plan = self.server.style_generation.store.plan(row["plan_id"], row["project_id"])
        ready_children = [identifier for identifier in batch["candidate_ids"] if identifier in ready_identifiers]
        request_states = [request[0] for request in connection.execute("SELECT job_requests.status FROM style_candidate_renders JOIN job_requests USING(request_id) WHERE plan_id=? AND style_candidate_renders.rowid IN (SELECT MAX(rowid) FROM style_candidate_renders WHERE plan_id=? GROUP BY candidate_id,case_id)", (row["plan_id"], row["plan_id"]))]
        selection = state.get("evolution")
        all_ready = len(ready_children) == len(batch["candidate_ids"]) and all(identifier in ready_identifiers for identifier in batch.get("reference_ids", batch["parent_ids"]))
        ranking = build_selection_ranking(selection) if selection else None
        next_pair = next_selection_pair(selection, ready_identifiers, ranking) if selection else None
        complete_count = len(ranking["completed_identifiers"]) if ranking else 0
        phase = "planned" if row["status"] == "planned" else "ready" if all_ready and next_pair is None else "generating" if any(status in {"submitting", "pending", "running", "cancelling"} for status in request_states) else "failed" if not all_ready else "selecting"
        return {"identifier": row["batch_id"], "status": row["status"], "phase": phase, "sourceGeneration": batch["sourceGeneration"], "targetGeneration": batch["targetGeneration"], "plan": plan,
                "candidateIdentifiers": batch["candidate_ids"], "parentIdentifiers": batch["parent_ids"],
                "completedCandidateIdentifiers": ranking["completed_identifiers"] if ranking else [],
                "enteredCandidateIdentifiers": [identifier for identifier, child in ranking["info"].items() if child["slot"] > ranking["admission_slot"]] if ranking and all_ready and next_pair is None else [],
                "placementPolicy": batch.get("placement_policy"), "referenceCandidateIdentifiers": batch.get("reference_ids", batch["parent_ids"]),
                "remainingPlacementCount": len(batch["candidate_ids"]) - complete_count,
                "childCount": len(batch["candidate_ids"]), "readyChildCount": len(ready_children), "completedSelectionCount": complete_count, "canConfirm": row["status"] == "active" and all_ready and next_pair is None,
                "failedRequestCount": sum(status in {"failed", "cancelled", "stopped"} for status in request_states), "modeCounts": plan["selection"]["modeCounts"]}

    async def prepare_evolution_plan(self, project_identifier: str, payload: EvolutionPlanInput) -> dict:
        """GPU 제출 없이 부모·조합·조건을 고정하고 실제 장수 확인에 필요한 계획을 저장합니다."""

        request_hash = snapshot_hash({"projectIdentifier": project_identifier, **payload.model_dump()})
        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM style_evolution_batches WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 진화 계획을 만들 수 없습니다.")
                return self.server.style_generation.store.plan(existing["plan_id"], project_identifier)
            project_row = connection.execute("SELECT active_evaluation_id FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
            if not project_row:
                raise LookupError("프로젝트를 찾을 수 없습니다.")
            evaluation_identifier = project_row[0]
            project, revision, state, candidates, ready_identifiers = self.load_evolution_context(connection, project_identifier, evaluation_identifier)
            if payload.expectedProjectRevision != project["revision"] or payload.expectedVotingRevision != revision:
                raise StyleRevisionConflict("프로젝트 또는 선별 결과가 바뀌었습니다. 최신 상태에서 다시 시작해 주세요.")
            if self.store.find_open_evolution_batch(connection, evaluation_identifier):
                raise StyleRevisionConflict("이미 준비하거나 진행 중인 진화가 있습니다. 먼저 생성·확정 또는 취소해 주세요.")
            messages = self.evolution_blockers(connection, project, evaluation_identifier, state, candidates, ready_identifiers)
            if messages:
                raise ValueError(" ".join(messages))
            ranked = ranked_candidate_statistics([candidate["identifier"] for candidate in candidates], state["statistics"])
            parent_identifiers = [entry["identifier"] for entry in ranked[:len(ranked) * 3 // 10]]
            parents = [next(candidate for candidate in candidates if candidate["identifier"] == identifier) for identifier in parent_identifiers]
            all_candidates = [{"identifier": row["candidate_id"], "components": json.loads(row["components_json"]), "lifecycle": row["lifecycle"]} for row in connection.execute(
                "SELECT candidates.*,memberships.lifecycle FROM style_candidates AS candidates JOIN style_candidate_memberships AS memberships USING(candidate_id) "
                "WHERE candidates.project_id=? AND candidates.evaluation_id=? ORDER BY candidates.rowid", (project_identifier, evaluation_identifier))]
            settings = ProjectSettings(**json.loads(project["settings_json"])).model_dump()
            source_generation = self.store.current_generation_number(connection, evaluation_identifier)
            parent_plans = []
            for identifier in parent_identifiers:
                row = connection.execute("SELECT plan_json FROM style_generation_plans JOIN style_candidates USING(plan_id) WHERE candidate_id=?", (identifier,)).fetchone()
                parent_plans.append(json.loads(row[0]))
            reference_cases = parent_plans[0]["cases"]
            case_contents = [{key: value for key, value in prompt_case.items() if key != "name"} for prompt_case in reference_cases]
            if any([{key: value for key, value in prompt_case.items() if key != "name"} for prompt_case in plan["cases"]] != case_contents for plan in parent_plans):
                raise ValueError("부모의 실제 Prompt 전개가 서로 다릅니다. 같은 조건으로 생성한 조합을 평가해 주세요.")
            context = {"identifier": uuid.uuid4().hex, "projectIdentifier": project_identifier, "evaluationIdentifier": evaluation_identifier,
                       "sourceGeneration": source_generation, "targetGeneration": source_generation + 1, "parent_ids": parent_identifiers,
                       "parent_scores": {identifier: state["statistics"][identifier]["rating"] for identifier in parent_identifiers},
                       "placement_policy": STYLELAB_SELECTION_POLICY, "reference_ids": list(parent_identifiers),
                       "reference_scores": {identifier: state["statistics"][identifier]["rating"] for identifier in parent_identifiers},
                       "sourceCandidateIdentifiers": [candidate["identifier"] for candidate in candidates], "beforeArena": copy.deepcopy(state), "votingRevision": revision,
                       "operationIdentifier": payload.operationIdentifier, "payloadHash": request_hash, "resolvedCases": reference_cases}
        selection_seed = snapshot_hash({"projectIdentifier": project_identifier, "operationIdentifier": payload.operationIdentifier})
        with self.server.database._connect() as connection:
            inherited_statistics = inherited_component_statistics(connection, project_identifier)
        prior_scores = {identifier: observation.get("score", 0) for identifier, observation in inherited_statistics.items()}
        children, provenance = draw_evolution_children(settings, parents, state["statistics"], all_candidates, payload.childCount, selection_seed, component_prior_scores=prior_scores)
        provenance["componentPriorScores"] = prior_scores
        if not children:
            raise ValueError("범위 안에서 중복 없는 자녀를 만들지 못했습니다. 성분·개수·STR 범위를 넓혀 주세요.")
        context["children"] = children
        context["provenance"] = provenance
        plan_input = EvolutionGenerationPlanInput(expectedRevision=payload.expectedProjectRevision, operationIdentifier=payload.operationIdentifier, combinations=[FixedCombination(components=child["components"]) for child in children])
        parent_loras = {component["identifier"][5:]: component.get("file_identity") for parent in parents for component in parent["components"] if component["identifier"].startswith("lora:") and (component.get("file_identity") or {}).get("sha256")}
        if parent_loras:
            identities = await self.server.comfy.lora_identities(list(parent_loras))
            for name, previous_identity in parent_loras.items():
                current_identity = identities.get(name.replace("\\", "/"))
                if not current_identity or current_identity.get("sha256") != previous_identity["sha256"]:
                    raise ValueError(f"부모가 사용한 LoRA 파일이 바뀌었거나 확인되지 않습니다: {name}")
        return await self.server.style_generation.create_plan(project_identifier, plan_input, evolution_context=context)

    def register_evolution_plan(self, connection, plan_identifier: str, candidates: list[dict], context: dict) -> None:
        """생성 계획·후보와 같은 Transaction에서 진화 Batch를 등록합니다."""

        evaluation_identifier = context["evaluationIdentifier"]
        current = connection.execute("SELECT revision FROM style_voting_arenas WHERE evaluation_id=?", (evaluation_identifier,)).fetchone()
        if not current or current[0] != context["votingRevision"] or self.store.current_generation_number(connection, evaluation_identifier) != context["sourceGeneration"]:
            raise StyleRevisionConflict("자녀를 준비하는 동안 평가 결과가 바뀌었습니다. 최신 결과로 다시 시작해 주세요.")
        if self.store.find_open_evolution_batch(connection, evaluation_identifier):
            raise StyleRevisionConflict("다른 화면에서 진화를 먼저 준비했습니다.")
        batch = {**context, "candidate_ids": [candidate["identifier"] for candidate in candidates]}
        connection.execute("INSERT INTO style_evolution_batches VALUES(?,?,?,?,?,?,?,?,?,?)", (context["identifier"], context["projectIdentifier"], evaluation_identifier, plan_identifier, "planned", encode_snapshot(batch), None, context["operationIdentifier"], context["payloadHash"], datetime.now(timezone.utc).isoformat()))
        for candidate, child in zip(candidates, context["children"]):
            connection.execute("INSERT INTO style_candidate_memberships VALUES(?,?,?,?,?,?,?)", (candidate["identifier"], evaluation_identifier, context["targetGeneration"], "evolving", context["identifier"], child["mode"], encode_snapshot(child["parentIdentifiers"])))

    def prepare_plan_submission(self, connection, project_identifier: str, plan: dict, retry: bool) -> None:
        """일반 생성을 진화와 섞지 않으며 제출 직전에 부모 Revision을 다시 확인합니다."""

        row = connection.execute("SELECT * FROM style_evolution_batches WHERE plan_id=? AND project_id=?", (plan["planIdentifier"], project_identifier)).fetchone()
        open_batch = self.store.find_open_evolution_batch(connection, plan["evaluationIdentifier"])
        if not row:
            if open_batch:
                raise StyleRevisionConflict("진화를 확정하거나 취소한 뒤 일반 조합을 추가해 주세요.")
            if not retry and plan.get("generationNumber", 1) != max(1, self.store.current_generation_number(connection, plan["evaluationIdentifier"])):
                raise StyleRevisionConflict("이전 세대에서 준비한 생성 계획입니다. 현재 세대의 새 조합으로 다시 시작해 주세요.")
            return
        if row["status"] in {"cancelled", "confirmed"}:
            raise StyleRevisionConflict("종료한 진화 세대는 다시 제출할 수 없습니다.")
        if retry:
            if row["status"] != "active":
                raise StyleRevisionConflict("먼저 자녀 생성을 시작해 주세요.")
            return
        batch = json.loads(row["batch_json"])
        arena = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?", (row["evaluation_id"],)).fetchone()
        if arena["revision"] != batch["votingRevision"]:
            raise StyleRevisionConflict("계획 후 선별 결과가 바뀌었습니다. 준비한 진화를 취소하고 최신 결과로 다시 시작해 주세요.")
        state = json.loads(arena["state_json"])
        _, ready_identifiers = self.server.style_voting.load_evaluation_candidates(connection, project_identifier, row["evaluation_id"])
        if any(identifier not in ready_identifiers for identifier in batch["sourceCandidateIdentifiers"]):
            raise ValueError("부모 세대의 이미지 준비 상태가 바뀌었습니다. 현재 결과를 확인해 주세요.")
        self.store.create_generation_checkpoint(connection, project_identifier, row["evaluation_id"], batch["sourceGeneration"], state, "before-first-evolution")
        state["evolution"] = {"batch_id": row["batch_id"], "parent_ids": batch["parent_ids"], "parent_scores": batch["parent_scores"], "candidate_ids": batch["candidate_ids"], "history": []}
        for field in ("placement_policy", "reference_ids", "reference_scores"):
            state["evolution"][field] = copy.deepcopy(batch[field])
        for identifier in batch["candidate_ids"]:
            state["statistics"][identifier] = initial_candidate_statistics()
        synchronize_selection_statistics(state)
        state.update(match=None, placement=None, undoStack=[], lastPair=[])
        self.server.style_voting.save_arena(connection, row["evaluation_id"], arena["revision"] + 1, state)
        connection.execute("UPDATE style_evolution_batches SET status='active' WHERE batch_id=?", (row["batch_id"],))

    def execute_evolution_action(self, project_identifier: str, batch_identifier: str, action: str, payload: EvolutionActionInput) -> dict:
        """세대 확정·취소를 원자 처리하고 같은 요청의 재전송을 한 번만 반영합니다."""

        request_hash = snapshot_hash({"projectIdentifier": project_identifier, "batchIdentifier": batch_identifier, "action": action, **payload.model_dump()})
        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT payload_hash,response_json FROM style_evolution_commands WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if previous:
                if previous["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 세대 처리를 할 수 없습니다.")
                return json.loads(previous["response_json"])
            row = connection.execute("SELECT * FROM style_evolution_batches WHERE batch_id=? AND project_id=?", (batch_identifier, project_identifier)).fetchone()
            if not row:
                raise LookupError("프로젝트의 진화 세대를 찾을 수 없습니다.")
            if row["status"] not in {"planned", "active"}:
                raise StyleRevisionConflict("이미 확정하거나 취소한 세대입니다.")
            batch = json.loads(row["batch_json"])
            _, revision, state, _, ready_identifiers = self.load_evolution_context(connection, project_identifier, row["evaluation_id"])
            if revision != payload.expectedVotingRevision:
                raise StyleRevisionConflict("선별 상태가 바뀌었습니다. 최신 상태에서 다시 확인해 주세요.")
            connection.execute("INSERT INTO style_evolution_commands VALUES(?,?,?,?,?,?,?)", (payload.operationIdentifier, project_identifier, batch_identifier, action, request_hash, "{}", datetime.now(timezone.utc).isoformat()))
            result = self.confirm_generation(connection, row, batch, state, ready_identifiers) if action == "confirm" else self.cancel_generation(connection, row, batch, state)
            self.server.style_voting.save_arena(connection, row["evaluation_id"], revision + 1, state)
            connection.execute("UPDATE style_evolution_batches SET result_json=? WHERE batch_id=?", (encode_snapshot(result), batch_identifier))
            if action == "confirm":
                result["checkpointIdentifier"] = self.store.create_generation_checkpoint(connection, project_identifier, row["evaluation_id"], batch["targetGeneration"], state, "generation-confirmed")
            connection.execute("UPDATE style_evolution_batches SET result_json=? WHERE batch_id=?", (encode_snapshot(result), batch_identifier))
            connection.execute("UPDATE style_evolution_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(result), payload.operationIdentifier))
            return result

    def confirm_generation(self, connection, row, batch: dict, state: dict, ready_identifiers: list[str]) -> dict:
        """부모 점수를 바꾸지 않고 생존 자녀만 편입하고 하위 기존 후보를 퇴역시킵니다."""

        if row["status"] != "active" or not state.get("evolution"):
            raise ValueError("자녀 생성과 평가를 먼저 시작해 주세요.")
        if any(identifier not in ready_identifiers for identifier in batch["candidate_ids"] + batch.get("reference_ids", batch["parent_ids"])):
            raise ValueError("모든 자녀·부모의 Prompt 이미지가 준비돼야 세대를 확정할 수 있습니다.")
        ranking = build_selection_ranking(state["evolution"])
        if next_selection_pair(state["evolution"], ready_identifiers, ranking):
            raise ValueError("남은 자녀 선별을 먼저 마쳐 주세요.")
        children = set(batch["candidate_ids"])
        parents = set(batch["parent_ids"])
        failed = {identifier for identifier in children if ranking["info"][identifier]["slot"] <= ranking["admission_slot"]}
        entered = children - failed
        ordered = sorted(set(batch["sourceCandidateIdentifiers"]) | entered, key=lambda identifier: (state["statistics"][identifier]["rating"], identifier in parents, identifier), reverse=True)
        removable = [identifier for identifier in reversed(ordered) if identifier not in children]
        dropped = set(removable[:len(entered)])
        for identifier in failed | dropped:
            connection.execute("UPDATE style_candidate_memberships SET lifecycle='retired' WHERE candidate_id=?", (identifier,))
        for identifier in entered:
            connection.execute("UPDATE style_candidate_memberships SET lifecycle='active' WHERE candidate_id=?", (identifier,))
        connection.execute("INSERT INTO style_evolution_timelines VALUES(?,?,?) ON CONFLICT(evaluation_id) DO UPDATE SET generation_number=excluded.generation_number", (row["evaluation_id"], row["project_id"], batch["targetGeneration"]))
        connection.execute("UPDATE style_evolution_batches SET status='confirmed' WHERE batch_id=?", (row["batch_id"],))
        selection_history = state["evolution"]["history"]
        state.update(evolution=None, match=None, placement=None, undoStack=[], lastPair=[])
        survivors = [identifier for identifier in ordered if identifier not in dropped]
        ranked = ranked_candidate_statistics(survivors, state["statistics"])
        return {"status": "confirmed", "generationNumber": batch["targetGeneration"], "enteredCount": len(entered), "failedCount": len(failed), "retiredExistingCount": len(dropped),
                "survivingIdentifiers": survivors, "retiredIdentifiers": sorted(failed | dropped), "nextParentIdentifiers": [entry["identifier"] for entry in ranked[:len(ranked) * 3 // 10]], "selectionHistory": selection_history}

    def cancel_generation(self, connection, row, batch: dict, state: dict) -> dict:
        """자녀와 해당 선별을 취소하되 진행 중 일반 리그에서 바뀐 기존 후보 점수는 보존합니다."""

        cancelled_statistics = {identifier: state["statistics"].get(identifier) for identifier in batch["candidate_ids"]}
        selection_history = copy.deepcopy((state.get("evolution") or {}).get("history", []))
        if row["status"] == "active":
            restored = copy.deepcopy(batch["beforeArena"])
            children = set(batch["candidate_ids"])
            retained_statistics = {identifier: copy.deepcopy(statistics) for identifier, statistics in state["statistics"].items() if identifier not in children}
            retained_mode = state.get("mode", "auto")
            unchanged_existing_candidates = retained_statistics == restored["statistics"] and retained_mode == restored.get("mode", "auto")
            restored.update(statistics=retained_statistics, componentStatistics=copy.deepcopy(state["componentStatistics"]), mode=retained_mode,
                            skippedTies=copy.deepcopy(state["skippedTies"]), undoStack=[])
            if restored.get("match") and unchanged_existing_candidates:
                restored["match"]["token"] = uuid.uuid4().hex
            else:
                restored["match"] = None
            state.clear()
            state.update(restored)
        connection.execute("UPDATE style_candidate_memberships SET lifecycle='cancelled' WHERE batch_id=?", (row["batch_id"],))
        connection.execute("UPDATE style_evolution_batches SET status='cancelled' WHERE batch_id=?", (row["batch_id"],))
        job_identifiers = [job[0] for job in connection.execute("SELECT job_id FROM style_job_ownership WHERE plan_id=?", (row["plan_id"],))]
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for job_identifier in job_identifiers:
            connection.execute("UPDATE jobs SET cancellation_requested=1 WHERE job_id=? AND EXISTS(SELECT 1 FROM job_requests WHERE job_id=? AND status IN ('submitting','pending','running','cancelling'))", (job_identifier, job_identifier))
            connection.execute("UPDATE job_requests SET status='cancelling',error_message=NULL,updated_at=? WHERE job_id=? AND status IN ('submitting','pending','running')", (timestamp, job_identifier))
        return {"status": "cancelled", "generationNumber": batch["sourceGeneration"], "cancelledChildCount": len(batch["candidate_ids"]), "jobIdentifiers": job_identifiers, "cancelledStatistics": cancelled_statistics, "selectionHistory": selection_history}
