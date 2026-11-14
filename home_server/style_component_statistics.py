"""프로젝트 평가 조건별 작가·LoRA 기여도와 실제 대결 전적을 읽기 전용으로 계산합니다."""

import json

from .style_voting_rules import candidate_is_rated


COMPONENT_PREFERENCE_POLICY_VERSION = "ridge-60-component-preference-v1"


def rated_component_candidates(candidates: list[dict], statistics: dict) -> list[dict]:
    """확정된 활성·퇴역 후보만 사용하고 진행·취소·삭제 후보의 점수는 제외합니다."""

    return [candidate for candidate in candidates
            if candidate.get("lifecycle", "active") in {"active", "retired"}
            and candidate_is_rated(statistics.get(candidate["identifier"], {"matches": 0, "placed": False}))]


def component_preference_scores(candidates: list[dict], statistics: dict) -> dict:
    """원본 StyleLab과 같은 Ridge 계수 2.0·Coordinate Descent 60회로 기여도를 구합니다."""

    rated_candidates = rated_component_candidates(candidates, statistics)
    if not rated_candidates:
        return {}
    mean_rating = sum(statistics[candidate["identifier"]]["rating"] for candidate in rated_candidates) / len(rated_candidates)
    residuals = [statistics[candidate["identifier"]]["rating"] - mean_rating for candidate in rated_candidates]
    observations = {}
    for row_index, candidate in enumerate(rated_candidates):
        for component in candidate["components"]:
            observations.setdefault(component["identifier"], []).append((row_index, component["strength"]))
    scores = dict.fromkeys(observations, 0.0)
    for _ in range(60):
        for identifier, hits in observations.items():
            previous_score = scores[identifier]
            numerator = sum(strength * (residuals[row_index] + strength * previous_score) for row_index, strength in hits)
            denominator = sum(strength * strength for _, strength in hits) + 2.0
            next_score = numerator / denominator
            for row_index, strength in hits:
                residuals[row_index] -= strength * (next_score - previous_score)
            scores[identifier] = next_score
    return {identifier: round(score) for identifier, score in scores.items()}


def component_selection_preferences(scores: dict, identifiers: list[str]) -> dict:
    """종류별 점수를 0.5~2배의 선택 보정으로 바꾸고 미관측 성분도 탐색 기회를 유지합니다."""

    preferences = {}
    for kind in ("artist", "lora"):
        kind_identifiers = [identifier for identifier in identifiers if identifier.startswith(kind + ":")]
        maximum_score = max((abs(scores.get(identifier, 0)) for identifier in kind_identifiers), default=0)
        for identifier in kind_identifiers:
            preferences[identifier] = 2 ** (scores.get(identifier, 0) / maximum_score) if maximum_score else 1.0
    return preferences


def read_component_statistics(connection, project_identifier: str, evaluation_identifier: str | None = None) -> dict:
    """기존 후보·Elo·유효 Vote를 일괄 조회하며 Arena 생성이나 Revision 변경을 하지 않습니다."""

    project = connection.execute("SELECT active_evaluation_id,settings_json FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
    if project is None:
        raise LookupError("프로젝트를 찾을 수 없습니다.")
    evaluation_identifier = evaluation_identifier or project["active_evaluation_id"]
    evaluation = connection.execute("SELECT 1 FROM style_evaluation_revisions WHERE evaluation_id=? AND project_id=?", (evaluation_identifier, project_identifier)).fetchone()
    if evaluation is None:
        raise LookupError("프로젝트의 평가 조건을 찾을 수 없습니다.")
    candidate_rows = connection.execute(
        "SELECT candidates.candidate_id,candidates.components_json,memberships.lifecycle FROM style_candidates AS candidates "
        "JOIN style_candidate_memberships AS memberships USING(candidate_id) "
        "WHERE candidates.project_id=? AND candidates.evaluation_id=? AND memberships.lifecycle IN ('active','retired') "
        "AND EXISTS(SELECT 1 FROM style_candidate_renders WHERE candidate_id=candidates.candidate_id) ORDER BY candidates.rowid",
        (project_identifier, evaluation_identifier),
    ).fetchall()
    candidates = [{"identifier": row["candidate_id"], "components": json.loads(row["components_json"]), "lifecycle": row["lifecycle"]} for row in candidate_rows]
    arena = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE project_id=? AND evaluation_id=?", (project_identifier, evaluation_identifier)).fetchone()
    statistics = json.loads(arena["state_json"])["statistics"] if arena else {}
    scores = component_preference_scores(candidates, statistics)
    policies = json.loads(project["settings_json"])["componentPolicies"]
    enabled_identifiers = [identifier for identifier, policy in policies.items() if policy["enabled"]]
    preferences = component_selection_preferences(scores, enabled_identifiers)
    components = {identifier: {"score": 0, "ratedCombinationCount": 0, "matches": 0, "wins": 0} for identifier in policies}
    for candidate in rated_component_candidates(candidates, statistics):
        for component in candidate["components"]:
            observation = components.setdefault(component["identifier"], {"score": 0, "ratedCombinationCount": 0, "matches": 0, "wins": 0})
            observation["ratedCombinationCount"] += 1
    components_by_candidate = {candidate["identifier"]: {component["identifier"] for component in candidate["components"]} for candidate in candidates}
    votes = connection.execute(
        "SELECT json_extract(match_json,'$.a') AS first_candidate,json_extract(match_json,'$.b') AS second_candidate,choice "
        "FROM style_vote_events WHERE evaluation_id=? AND undone_by IS NULL AND choice IN ('a','b') "
        "AND json_extract(match_json,'$.kind') IN ('league','top','tie') ORDER BY rowid", (evaluation_identifier,),
    )
    for vote in votes:
        first_components = components_by_candidate.get(vote["first_candidate"])
        second_components = components_by_candidate.get(vote["second_candidate"])
        if first_components is None or second_components is None:
            continue
        # 양쪽에 같은 성분이 있으면 STR 차이만으로 해당 성분의 승패를 단정하지 않습니다.
        for identifier in first_components ^ second_components:
            observation = components.setdefault(identifier, {"score": 0, "ratedCombinationCount": 0, "matches": 0, "wins": 0})
            observation["matches"] += 1
            observation["wins"] += int((identifier in first_components) == (vote["choice"] == "a"))
    for identifier, observation in components.items():
        observation.update(score=scores.get(identifier, 0), losses=observation["matches"] - observation["wins"],
                           winRate=observation["wins"] / observation["matches"] if observation["matches"] else None,
                           selectionMultiplier=preferences.get(identifier, 1.0))
    return {"projectIdentifier": project_identifier, "evaluationIdentifier": evaluation_identifier,
            "votingRevision": arena["revision"] if arena else None, "policyVersion": COMPONENT_PREFERENCE_POLICY_VERSION,
            "components": components}
