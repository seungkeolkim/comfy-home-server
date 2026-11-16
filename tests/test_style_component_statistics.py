"""성분 통계의 원본 산식·프로젝트 격리·Undo·삭제·진화 추첨 효과를 검증합니다."""

import ast
import copy
import random
import uuid
from collections import Counter
from pathlib import Path

import pytest

from home_server.style_component_statistics import component_preference_scores, component_selection_preferences
from home_server.style_evolution_breeding import breed_component_kind
from test_style_evolution import prepare_evolution, rated_population
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_management import management_payload
from test_style_prompt_changes import save_changed_prompts
from test_style_voting import read_selection, undo_input, vote_input


def component_statistics(client, project: dict, evaluation_identifier: str | None = None) -> dict:
    """기본 조회는 현재 평가 조건만 읽고 다른 조건은 명시적으로 요청합니다."""

    parameters = {"evaluationIdentifier": evaluation_identifier} if evaluation_identifier else {}
    response = client.get(f"/api/style-projects/{project['identifier']}/component-statistics", params=parameters)
    assert response.status_code == 200, response.text
    return response.json()


def test_component_scores_match_legacy_ridge_and_ignore_ineligible_candidates() -> None:
    """공통 성분·음수 STR·퇴역을 원본과 비교하고 진행·취소·삭제 후보는 제외합니다."""

    snapshot = Path(__file__).resolve().parents[1] / "docs/style-lab-rebuild/source_reference/style_lab/app__core.py.md"
    source = snapshot.read_text(encoding="utf-8").split("```python\n", 1)[1].rsplit("```", 1)[0]
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "artist_scores")
    legacy = {"ARTIST_SCORE_PRIOR": 2.0, "is_rated": lambda candidate: True,
              "parse_style_combo": lambda components: [(component["strength"], component["identifier"]) for component in components]}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(snapshot), "exec"), legacy)
    candidates = []
    statistics = {}
    for index, lifecycle in enumerate(["active", "retired", "active", "evolving", "cancelled", "deleted"]):
        identifier = f"candidate-{index}"
        candidates.append({"identifier": identifier, "lifecycle": lifecycle, "components": [
            {"identifier": "artist:shared", "strength": 0.4 + index * 0.1},
            {"identifier": f"lora:style-{index % 2}", "strength": -0.5 if index == 1 else 0.7},
        ]})
        statistics[identifier] = {"matches": 3, "placed": True, "rating": 10000 + index * 120}
    expected = legacy["artist_scores"]([{"elo": statistics[candidate["identifier"]]["rating"], "style": candidate["components"]} for candidate in candidates[:3]])
    assert component_preference_scores(candidates, statistics) == {identifier: score for identifier, (score, _) in expected.items()}
    assert component_preference_scores([], statistics) == {}
    statistics["candidate-0"]["placementPending"] = True
    assert component_preference_scores(candidates, statistics) == component_preference_scores(candidates[1:], statistics)


@pytest.mark.parametrize("kind", ["artist", "lora"])
def test_preference_changes_sampling_without_removing_exploration_or_changing_strength(kind) -> None:
    """두 종류 모두 높은 점수를 더 자주 고르되 낮은 점수·미관측 성분과 STR 범위를 보존합니다."""

    identifiers = [f"{kind}:favored", f"{kind}:disliked", f"{kind}:unseen"]
    scores = {identifiers[0]: 100, identifiers[1]: -100, "artist:other-kind": 1000000 if kind == "lora" else 0}
    preferences = component_selection_preferences(scores, identifiers + ["artist:other-kind"])
    assert [preferences[identifier] for identifier in identifiers] == [2.0, 0.5, 1.0]
    assert component_selection_preferences({}, identifiers) == dict.fromkeys(identifiers, 1.0)
    settings = {kind + "MinimumCount": 1, kind + "MaximumCount": 1, "componentPolicies": {
        identifier: {"enabled": True, "minimumStrength": 0.4, "maximumStrength": 0.6} for identifier in identifiers}}
    selection_random = random.Random(314159)
    counts = Counter()
    for _ in range(3000):
        selected = breed_component_kind(settings, {"components": []}, {"components": []}, "random", kind, selection_random, {}, preferences)[0]
        counts[selected["identifier"]] += 1
        assert 0.4 <= selected["strength"] <= 0.6
    assert counts[identifiers[0]] > counts[identifiers[2]] > counts[identifiers[1]] > 250
    assert 3.3 < counts[identifiers[0]] / counts[identifiers[1]] < 4.8


def test_statistics_follow_votes_undo_conditions_and_complete_candidate_deletion(tmp_path) -> None:
    """기존 Vote만 읽어 승패를 복원하고 다른 프로젝트·새 Prompt·삭제 이력은 섞지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    endpoint = f"/api/style-projects/{project['identifier']}"
    try:
        server = application.state.home_server
        before = component_statistics(client, project)
        assert all(value["ratedCombinationCount"] == value["matches"] == 0 for value in before["components"].values())
        with server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM style_voting_arenas").fetchone()[0] == 0
        plan_input["combinations"] = [
            {"components": [{"identifier": "artist:example", "strength": 0.7}]},
            {"components": [{"identifier": "lora:example.safetensors", "strength": 0.8}]},
        ]
        _, _, results = submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        original_candidates = {candidate["identifier"]: candidate for candidate in results["candidates"]}
        winner_identifier = selection["match"]["a"]
        winner_component = original_candidates[winner_identifier]["components"][0]["identifier"]
        voted_response = client.post(endpoint + "/votes", json=vote_input(selection))
        assert voted_response.status_code == 200, voted_response.text
        voted = voted_response.json()
        statistics = component_statistics(client, project)
        assert statistics["components"][winner_component]["wins"] == 1
        assert statistics["components"][winner_component]["winRate"] == 1.0
        assert statistics["components"][winner_component]["score"] > 0
        assert statistics["components"][winner_component]["selectionMultiplier"] == 2.0
        assert sum(value["losses"] for value in statistics["components"].values()) == 1
        undo = client.post(endpoint + "/undo", json=undo_input(voted))
        assert undo.status_code == 200, undo.text
        assert component_statistics(client, project)["components"] == before["components"]
        assert client.post(endpoint + "/votes", json=vote_input(undo.json())).status_code == 200
        other_settings = copy.deepcopy(project["settings"])
        other_settings["name"] = "별도 프로젝트"
        other = client.post("/api/style-projects", json={"operationIdentifier": uuid.uuid4().hex, "settings": other_settings}).json()
        assert all(value["matches"] == 0 and value["score"] == 0 for value in component_statistics(client, other)["components"].values())
        assert client.get(endpoint + "/component-statistics", params={"evaluationIdentifier": other["evaluationIdentifier"]}).status_code == 404
        deletion = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [winner_identifier]))
        assert deletion.status_code == 200, deletion.text
        assert all(value["matches"] == 0 and value["score"] == 0 for value in component_statistics(client, project)["components"].values())
        changed_project = save_changed_prompts(client, project)
        assert all(value["matches"] == value["ratedCombinationCount"] == 0 for value in component_statistics(client, changed_project)["components"].values())
        assert component_statistics(client, changed_project)["evaluationIdentifier"] != project["evaluationIdentifier"]
    finally:
        client.__exit__(None, None, None)


def test_existing_shared_components_do_not_receive_win_credit(tmp_path) -> None:
    """같은 LoRA가 양쪽에 들어 있으면 STR이 달라도 성분 승패는 누적하지 않습니다."""

    _, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        response = client.post(f"/api/style-projects/{project['identifier']}/votes", json=vote_input(selection))
        assert response.status_code == 200
        statistics = component_statistics(client, project)["components"]
        assert all(value["matches"] == 0 for value in statistics.values())
        assert all(value["ratedCombinationCount"] == 2 for value in statistics.values())
    finally:
        client.__exit__(None, None, None)


def test_evolution_records_the_same_component_preferences_shown_in_settings(rated_population) -> None:
    """설정 표시와 실제 새 세대의 추첨 점수·배수 Snapshot이 일치하는지 확인합니다."""

    _, _, client, project, _ = rated_population
    statistics = component_statistics(client, project)
    plan = prepare_evolution(client, project)
    provenance = plan["selection"]
    assert provenance["algorithm"] == "style-evolution-v3"
    assert provenance["newLoraChoice"] == "ridge-60-usage"
    for identifier, multiplier in provenance["componentPreferenceMultipliers"].items():
        assert multiplier == statistics["components"][identifier]["selectionMultiplier"]
        assert provenance["componentScores"].get(identifier, 0) == statistics["components"][identifier]["score"]
