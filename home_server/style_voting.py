"""프로젝트 평가 구간별 Match·Vote·Elo와 영속 Undo를 저장합니다."""

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .style_projects import StyleRevisionConflict, encode_snapshot, snapshot_hash
from .style_evolution_selection import build_selection_ranking, synchronize_selection_statistics
from .style_voting_rules import VOTING_POLICY_VERSION, apply_match_choice, candidate_is_rated, choose_next_match, initial_candidate_statistics, new_match, remove_deleted_candidate_state


class StyleVotingCommand(BaseModel):
    """최신 평가 Revision과 요청 ID로 재전송·다른 기기 충돌을 구별합니다."""

    model_config = ConfigDict(extra="forbid")
    evaluationIdentifier: str = Field(min_length=1, max_length=100)
    clientIdentifier: str = Field(min_length=16, max_length=100)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    expectedRevision: int = Field(ge=1)


class StyleVoteInput(StyleVotingCommand):
    """표시된 A/B 위치와 Match Token에 묶어 조합 단위 한 표를 받습니다."""

    matchToken: str = Field(min_length=16, max_length=100)
    choice: Literal["a", "b", "similar"]


class StyleUndoInput(StyleVotingCommand):
    """다른 최신 선택을 잘못 취소하지 않도록 대상 Event를 명시합니다."""

    eventIdentifier: str = Field(min_length=16, max_length=100)


class StylePairInput(StyleVotingCommand):
    """일반 비교의 A/B를 명시적으로 고르며 신규 배치 Pair는 변경하지 않습니다."""

    firstCandidateIdentifier: str = Field(min_length=1, max_length=100)
    secondCandidateIdentifier: str = Field(min_length=1, max_length=100)


class StyleCandidateRatingInput(StyleVotingCommand):
    """한 평가 조건의 선택 조합들에 같은 Elo를 명시적으로 지정합니다."""

    candidateIdentifiers: list[str] = Field(min_length=1, max_length=100)
    rating: int = Field(strict=True, ge=0, le=1_000_000)


def ranked_candidate_statistics(identifiers: list[str], statistics: dict) -> list[dict]:
    """평가된 후보를 우선 정렬하고 동점은 승률·경기 수·생성 순·ID로 풉니다."""

    entries = []
    for creation_index, identifier in enumerate(identifiers):
        candidate = dict(statistics.get(identifier, initial_candidate_statistics()))
        entries.append({"identifier": identifier, **candidate, "losses": candidate["matches"] - candidate["wins"], "creationIndex": creation_index, "rated": candidate_is_rated(candidate)})
    entries.sort(key=lambda entry: (
        not entry["rated"], -entry["rating"] if entry["rated"] else 0,
        -entry["wins"] / entry["matches"] if entry["matches"] else 0,
        -entry["matches"], entry["creationIndex"], entry["identifier"],
    ))
    evaluated_rank = 0
    for entry in entries:
        if entry["rated"]:
            evaluated_rank += 1
        entry["rank"] = evaluated_rank if entry["rated"] else None
    return entries


class StyleVotingService:
    """SQLite Transaction으로 Match와 투표 전후 Snapshot을 함께 보관합니다."""

    def __init__(self, server) -> None:
        """이미지 소유 관계와 같은 DB 연결 Factory를 사용합니다."""

        self.server = server

    @staticmethod
    def prepare_schema(connection) -> None:
        """평가 상태·Undo 가능한 Vote·멱등 명령 응답을 분리해 만듭니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_voting_arenas ("
            "evaluation_id TEXT PRIMARY KEY REFERENCES style_evaluation_revisions(evaluation_id), "
            "project_id TEXT NOT NULL REFERENCES style_projects(project_id), revision INTEGER NOT NULL, state_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_vote_events ("
            "event_id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL REFERENCES style_voting_arenas(evaluation_id), "
            "client_id TEXT NOT NULL, match_json TEXT NOT NULL, choice TEXT NOT NULL, "
            "before_json TEXT NOT NULL, after_json TEXT NOT NULL, undone_by TEXT, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_voting_commands ("
            "operation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "evaluation_id TEXT NOT NULL REFERENCES style_voting_arenas(evaluation_id), "
            "action TEXT NOT NULL, payload_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )

    def load_evaluation_candidates(self, connection, project_identifier: str, evaluation_identifier: str) -> tuple[list[dict], list[str]]:
        """전체 Case의 최신 Render가 완료되고 파일이 있는 조합만 투표 준비로 인정합니다."""

        evaluation = connection.execute("SELECT 1 FROM style_evaluation_revisions WHERE evaluation_id=? AND project_id=?", (evaluation_identifier, project_identifier)).fetchone()
        if not evaluation:
            raise LookupError("프로젝트의 평가 조건을 찾을 수 없습니다.")
        rows = connection.execute(
            "SELECT candidates.*,plans.plan_json FROM style_candidates AS candidates "
            "JOIN style_generation_plans AS plans USING(plan_id) JOIN style_candidate_memberships AS memberships USING(candidate_id) "
            "LEFT JOIN style_evolution_batches AS batches ON batches.batch_id=memberships.batch_id "
            "WHERE candidates.project_id=? AND candidates.evaluation_id=? AND (memberships.lifecycle='active' OR (memberships.lifecycle='evolving' AND batches.status='active')) ORDER BY candidates.rowid",
            (project_identifier, evaluation_identifier),
        ).fetchall()
        candidates = []
        ready_identifiers = []
        for row in rows:
            latest_renders = {}
            render_rows = connection.execute(
                "SELECT renders.case_id,requests.status,(SELECT files.relative_path FROM output_files AS files WHERE files.request_id=renders.request_id "
                "AND files.is_available=1 AND files.is_deleted=0 LIMIT 1) AS relative_path FROM style_candidate_renders AS renders "
                "JOIN job_requests AS requests USING(request_id) WHERE renders.candidate_id=? ORDER BY renders.rowid", (row["candidate_id"],),
            ).fetchall()
            for render in render_rows:
                latest_renders[render["case_id"]] = render
            if not latest_renders:
                continue
            candidates.append({"identifier": row["candidate_id"], "components": json.loads(row["components_json"])})
            cases = json.loads(row["plan_json"])["cases"]
            all_cases_ready = True
            for prompt_case in cases:
                render = latest_renders.get(prompt_case["identifier"])
                if not render or render["status"] != "completed" or not render["relative_path"]:
                    all_cases_ready = False
                    break
                try:
                    file_exists = self.server.managed_path(render["relative_path"]).is_file()
                except (ValueError, OSError):
                    file_exists = False
                if not file_exists:
                    all_cases_ready = False
                    break
            if all_cases_ready:
                ready_identifiers.append(row["candidate_id"])
        return candidates, ready_identifiers

    def load_arena(self, connection, project_identifier: str, evaluation_identifier: str) -> tuple[int, dict]:
        """최초 조회에 빈 Arena를 만들고 이미지 생성과 독립된 평가 상태를 읽습니다."""

        row = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=? AND project_id=?", (evaluation_identifier, project_identifier)).fetchone()
        if row:
            state = json.loads(row["state_json"])
            revision = row["revision"]
            changed = self.server.style_evolution.migrate_parent_selection(connection, project_identifier, evaluation_identifier, state)
            deleted_identifiers = [membership[0] for membership in connection.execute(
                "SELECT candidate_id FROM style_candidate_memberships WHERE evaluation_id=? AND lifecycle IN ('deleting','deleted')", (evaluation_identifier,),
            )]
            if remove_deleted_candidate_state(state, deleted_identifiers) or changed:
                revision += 1
                self.save_arena(connection, evaluation_identifier, revision, state)
            return revision, state
        state = {"policyVersion": VOTING_POLICY_VERSION, "statistics": {}, "componentStatistics": {}, "match": None, "placement": None, "skippedTies": [], "lastPair": [], "undoStack": []}
        connection.execute("INSERT INTO style_voting_arenas VALUES(?,?,?,?)", (evaluation_identifier, project_identifier, 1, encode_snapshot(state)))
        return 1, state

    def synchronize_candidates(self, state: dict, candidates: list[dict], ready_identifiers: list[str]) -> None:
        """새 완료 후보를 추가하되 현재 유효한 A/B와 Token은 Polling 중 유지합니다."""

        for candidate in candidates:
            state["statistics"].setdefault(candidate["identifier"], initial_candidate_statistics())
        match = state["match"]
        if match and (match["a"] not in ready_identifiers or match["b"] not in ready_identifiers):
            state["match"] = None
        if not state["match"]:
            state["match"] = choose_next_match(state, ready_identifiers)

    def save_arena(self, connection, evaluation_identifier: str, revision: int, state: dict) -> None:
        """Revision과 상태를 한 Transaction에서 교체합니다."""

        connection.execute("UPDATE style_voting_arenas SET revision=?,state_json=? WHERE evaluation_id=?", (revision, encode_snapshot(state), evaluation_identifier))

    def arena_view(self, connection, project_identifier: str, evaluation_identifier: str, client_identifier: str, revision: int, state: dict, candidates: list[dict], ready_identifiers: list[str]) -> dict:
        """서버 점수와 현재 Pair·Undo 소유 정보를 Browser에 반환합니다."""

        latest_event_identifier = state["undoStack"][-1] if state["undoStack"] else None
        latest_event = connection.execute("SELECT client_id,choice FROM style_vote_events WHERE event_id=?", (latest_event_identifier,)).fetchone() if latest_event_identifier else None
        automatic_placement = None
        if state.get("evolution"):
            ranking = build_selection_ranking(state["evolution"])
            automatic_placement = {"candidateCount": len(state["evolution"]["candidate_ids"]), "completedCount": len(ranking["completed_identifiers"]),
                "referenceCount": len(ranking["ladder"]), "comparingNewcomers": bool(state.get("match") and state["match"]["a"] in ranking["info"] and state["match"]["b"] in ranking["info"])}
        return {
            "projectIdentifier": project_identifier, "evaluationIdentifier": evaluation_identifier, "revision": revision,
            "policyVersion": VOTING_POLICY_VERSION, "match": state["match"],
            "activeEvolutionIdentifier": state["evolution"]["batch_id"] if state.get("evolution") else None,
            "automaticPlacement": automatic_placement,
            "rankings": ranked_candidate_statistics([candidate["identifier"] for candidate in candidates], state["statistics"]),
            "readyCandidateIdentifiers": ready_identifiers, "componentStatistics": state["componentStatistics"],
            "undoEventIdentifier": latest_event_identifier,
            "canUndo": bool(latest_event and latest_event["client_id"] == client_identifier),
            "undoUnavailableReason": "최근 선택은 다른 Browser에서 했습니다." if latest_event and latest_event["client_id"] != client_identifier else "",
        }

    def read(self, project_identifier: str, evaluation_identifier: str, client_identifier: str) -> dict:
        """재접속 시 현재 Pair와 점수를 복원하고 새 이미지가 준비된 경우만 갱신합니다."""

        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidates, ready_identifiers = self.load_evaluation_candidates(connection, project_identifier, evaluation_identifier)
            revision, state = self.load_arena(connection, project_identifier, evaluation_identifier)
            previous_snapshot = encode_snapshot(state)
            self.synchronize_candidates(state, candidates, ready_identifiers)
            if encode_snapshot(state) != previous_snapshot:
                revision += 1
                self.save_arena(connection, evaluation_identifier, revision, state)
            return self.arena_view(connection, project_identifier, evaluation_identifier, client_identifier, revision, state, candidates, ready_identifiers)

    def execute(self, project_identifier: str, action: str, payload: StyleVotingCommand) -> dict:
        """Vote·Undo·Pair 변경을 검증 후 원자 반영하고 재전송에는 저장한 응답을 줍니다."""

        request_hash = snapshot_hash({"projectIdentifier": project_identifier, "action": action, **payload.model_dump()})
        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_hash,response_json FROM style_voting_commands WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 선택을 저장할 수 없습니다.")
                return json.loads(existing["response_json"])
            candidates, ready_identifiers = self.load_evaluation_candidates(connection, project_identifier, payload.evaluationIdentifier)
            revision, state = self.load_arena(connection, project_identifier, payload.evaluationIdentifier)
            if revision != payload.expectedRevision:
                raise StyleRevisionConflict("다른 화면에서 선별 상태가 변경됐습니다. 최신 대결을 확인한 뒤 다시 선택해 주세요.")
            for candidate in candidates:
                state["statistics"].setdefault(candidate["identifier"], initial_candidate_statistics())
            if action == "vote":
                self.record_vote(connection, state, ready_identifiers, candidates, payload)
            elif action == "undo":
                self.restore_vote(connection, state, payload)
                self.server.style_evolution.migrate_parent_selection(connection, project_identifier, payload.evaluationIdentifier, state)
            elif action == "pair":
                self.select_pair(state, ready_identifiers, payload)
            elif action == "rating":
                self.set_candidate_ratings(connection, project_identifier, state, payload)
            else:
                raise ValueError("지원하지 않는 선별 명령입니다.")
            self.synchronize_candidates(state, candidates, ready_identifiers)
            revision += 1
            self.save_arena(connection, payload.evaluationIdentifier, revision, state)
            response = self.arena_view(connection, project_identifier, payload.evaluationIdentifier, payload.clientIdentifier, revision, state, candidates, ready_identifiers)
            connection.execute("INSERT INTO style_voting_commands VALUES(?,?,?,?,?,?,?)", (
                payload.operationIdentifier, project_identifier, payload.evaluationIdentifier, action, request_hash, encode_snapshot(response), datetime.now(timezone.utc).isoformat(),
            ))
            return response

    def set_candidate_ratings(self, connection, project_identifier: str, state: dict, payload: StyleCandidateRatingInput) -> None:
        """직접 Elo 수정은 승패를 유지하며 Undo·Placement의 이전 점수 복구를 차단합니다."""

        identifiers = payload.candidateIdentifiers
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("같은 조합을 중복 선택할 수 없습니다.")
        for identifier in identifiers:
            candidate = connection.execute(
                "SELECT lifecycle FROM style_candidates JOIN style_candidate_memberships USING(candidate_id) WHERE candidate_id=? AND project_id=? AND style_candidates.evaluation_id=?",
                (identifier, project_identifier, payload.evaluationIdentifier),
            ).fetchone()
            if not candidate or candidate["lifecycle"] not in {"active", "retired", "evolving"}:
                raise LookupError("Elo를 수정할 프로젝트의 조합을 찾을 수 없습니다.")
        for identifier in identifiers:
            statistics = state["statistics"].setdefault(identifier, initial_candidate_statistics())
            statistics.update(rating=payload.rating, placed=True, placementPending=False)
        if state.get("evolution"):
            self.update_evolution_rating_baseline(connection, state, identifiers, payload.rating)
        state.update(match=None, placement=None, undoStack=[], lastPair=[], skippedTies=[])

    def update_evolution_rating_baseline(self, connection, state: dict, identifiers: list[str], rating: int) -> None:
        """원본 Style Lab처럼 수동 수정만 부모 기준점을 바꾸고 자녀의 보정량을 보존합니다."""

        selection = state["evolution"]
        offsets = selection.setdefault("ratingOffsets", {})
        row = connection.execute("SELECT batch_json FROM style_evolution_batches WHERE batch_id=?", (selection["batch_id"],)).fetchone()
        batch = json.loads(row[0])
        for identifier in identifiers:
            if identifier in selection["parent_scores"]:
                selection["parent_scores"][identifier] = rating
                batch["parent_scores"][identifier] = rating
            if identifier in selection.get("reference_scores", {}):
                selection["reference_scores"][identifier] = rating
                batch["reference_scores"][identifier] = rating
        ranking = build_selection_ranking(selection)
        for identifier in identifiers:
            if identifier in selection["candidate_ids"]:
                judged = bool(ranking["info"][identifier]["votes"])
                base_rating = ranking["scores"][identifier] if judged else 10000
                offsets[identifier] = rating - base_rating
            if identifier in batch["beforeArena"]["statistics"]:
                batch["beforeArena"]["statistics"][identifier].update(rating=rating, placed=True)
        batch["beforeArena"].update(match=None, placement=None, undoStack=[], lastPair=[], skippedTies=[])
        synchronize_selection_statistics(state)
        connection.execute("UPDATE style_evolution_batches SET batch_json=? WHERE batch_id=?", (encode_snapshot(batch), selection["batch_id"]))

    def record_vote(self, connection, state: dict, ready_identifiers: list[str], candidates: list[dict], payload: StyleVoteInput) -> None:
        """전 Case가 준비된 현재 Token에만 한 표를 기록하며 Undo Snapshot을 남깁니다."""

        match = state["match"]
        if not match or match["token"] != payload.matchToken:
            raise StyleRevisionConflict("지금 표시된 대결과 다른 요청입니다. 최신 대결에서 선택해 주세요.")
        if match["a"] not in ready_identifiers or match["b"] not in ready_identifiers:
            raise ValueError("모든 Prompt의 이미지가 준비된 두 조합만 선별할 수 있습니다.")
        before = copy.deepcopy(state)
        event_identifier = uuid.uuid4().hex
        apply_match_choice(state, payload.choice, {candidate["identifier"]: candidate["components"] for candidate in candidates})
        state["undoStack"] = (state["undoStack"] + [event_identifier])[-30:]
        connection.execute("INSERT INTO style_vote_events VALUES(?,?,?,?,?,?,?,?,?)", (
            event_identifier, payload.evaluationIdentifier, payload.clientIdentifier, encode_snapshot(match), payload.choice,
            encode_snapshot(before), encode_snapshot(state), None, datetime.now(timezone.utc).isoformat(),
        ))

    def restore_vote(self, connection, state: dict, payload: StyleUndoInput) -> None:
        """최신 본인 Vote의 점수·전적·Placement·A/B를 복구하고 Token은 새로 발급합니다."""

        if not state["undoStack"] or state["undoStack"][-1] != payload.eventIdentifier:
            raise StyleRevisionConflict("최신 선택만 되돌릴 수 있습니다. 화면을 갱신한 뒤 다시 확인해 주세요.")
        event = connection.execute("SELECT * FROM style_vote_events WHERE event_id=? AND evaluation_id=? AND undone_by IS NULL", (payload.eventIdentifier, payload.evaluationIdentifier)).fetchone()
        if not event or event["client_id"] != payload.clientIdentifier:
            raise StyleRevisionConflict("다른 Browser의 최신 선택을 대신 되돌릴 수 없습니다.")
        preserved_statistics = state["statistics"]
        remaining_undo_stack = state["undoStack"][:-1]
        restored = json.loads(event["before_json"])
        for identifier, statistics in preserved_statistics.items():
            restored["statistics"].setdefault(identifier, statistics)
        restored["undoStack"] = remaining_undo_stack
        restored["match"]["token"] = uuid.uuid4().hex
        state.clear()
        state.update(restored)
        connection.execute("UPDATE style_vote_events SET undone_by=? WHERE event_id=?", (payload.operationIdentifier, payload.eventIdentifier))

    def select_pair(self, state: dict, ready_identifiers: list[str], payload: StylePairInput) -> None:
        """진행 중 배치·필수 동점 질문을 우회하지 않는 범위에서만 직접 Pair를 고릅니다."""

        match = state["match"]
        if not match or match["kind"] != "league":
            raise ValueError("신규 배치·경계 동점 비교를 마친 뒤 직접 조합을 선택할 수 있습니다.")
        identifiers = [payload.firstCandidateIdentifier, payload.secondCandidateIdentifier]
        if len(set(identifiers)) != 2 or any(identifier not in ready_identifiers for identifier in identifiers):
            raise ValueError("같은 평가 조건에서 모든 이미지가 준비된 서로 다른 두 조합을 선택해 주세요.")
        fresh = bool(match["metadata"].get("fresh"))
        if any(candidate_is_rated(state["statistics"][identifier]) == fresh for identifier in identifiers):
            raise ValueError("신규 조합 배치와 일반 비교를 섞을 수 없습니다. 현재 비교를 먼저 마쳐 주세요.")
        state["match"] = new_match("league", identifiers[0], identifiers[1], fresh=fresh)
