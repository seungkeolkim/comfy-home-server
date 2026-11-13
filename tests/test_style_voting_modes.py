"""선별 Mode 전환이 신규·진화 평가와 일반 리그의 점수·Undo를 분리하는지 검증합니다."""

import copy
import json
import uuid

import pytest

from home_server.style_voting_rules import apply_match_choice, choose_next_match, initial_candidate_statistics, league_candidate_identifiers
from test_style_evolution import evolution_view, finish_evolution, prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_voting import CLIENT_IDENTIFIER, read_selection, statistics_by_identifier, undo_input, vote_input


def make_voting_state(rated_count: int, newcomer_count: int = 0) -> tuple[dict, list[str]]:
    """서로 다른 점수의 기존 후보와 미평가 후보를 가진 독립 Arena를 만듭니다."""

    identifiers = [f"existing-{index:02d}" for index in range(rated_count)]
    statistics = {}
    for index, identifier in enumerate(identifiers):
        statistics[identifier] = {**initial_candidate_statistics(), "rating": 10000 + 100 * index, "matches": 3, "wins": 2}
    for index in range(newcomer_count):
        identifier = f"newcomer-{index:02d}"
        identifiers.append(identifier)
        statistics[identifier] = initial_candidate_statistics()
    return {"mode": "auto", "statistics": statistics, "componentStatistics": {}, "placement": None,
            "skippedTies": [], "lastPair": [], "match": None, "undoStack": []}, identifiers


def mode_input(selection: dict, mode: str) -> dict:
    """현재 Revision에 연결한 Mode 변경 명령을 만듭니다."""

    return {"evaluationIdentifier": selection["evaluationIdentifier"], "clientIdentifier": CLIENT_IDENTIFIER,
            "operationIdentifier": uuid.uuid4().hex, "expectedRevision": selection["revision"], "mode": mode}


def change_mode(client, project: dict, mode: str) -> dict:
    """실제 API로 Mode를 변경하고 저장된 선별 상태를 반환합니다."""

    selection = read_selection(client, project)
    response = client.post(f"/api/style-projects/{project['identifier']}/selection-mode", json=mode_input(selection, mode))
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode
    return response.json()


def test_manual_modes_pause_newcomer_placement_without_losing_progress() -> None:
    """수동 리그 투표 뒤에도 진행 중 Placement의 고정 Ladder와 투표를 유지합니다."""

    state, identifiers = make_voting_state(24, 1)
    state["match"] = choose_next_match(state, identifiers)
    assert state["match"]["kind"] == "place"
    apply_match_choice(state, "a", {})
    placement = copy.deepcopy(state["placement"])
    assert placement and placement["votes"]
    for mode in ("league", "top"):
        state["mode"] = mode
        state["match"] = choose_next_match(state, identifiers)
        assert state["match"]["kind"] == mode
        assert "newcomer-00" not in (state["match"]["a"], state["match"]["b"])
        apply_match_choice(state, "a", {identifier: [] for identifier in identifiers})
        assert state["placement"] == placement
    state["mode"] = "auto"
    assert choose_next_match(state, identifiers)["kind"] == "place"
    assert state["placement"] == placement


@pytest.mark.parametrize("mode", ["auto", "league", "top"])
def test_boundary_tie_precedes_evolution_or_manual_league(mode) -> None:
    """모든 Mode에서 기존 후보의 상위 30% 경계 동점을 진화 자녀보다 먼저 비교합니다."""

    state, identifiers = make_voting_state(10)
    state["mode"] = mode
    state["statistics"]["existing-06"]["rating"] = state["statistics"]["existing-07"]["rating"]
    state["evolution"] = {"candidate_ids": ["child"], "batch_id": "current-batch"}
    state["statistics"]["child"] = {**initial_candidate_statistics(), "rating": 10700, "placed": True}
    match = choose_next_match(state, identifiers + ["child"])
    assert match["kind"] == "tie"
    assert {match["a"], match["b"]} == {"existing-06", "existing-07"}


@pytest.mark.parametrize("rated_count, expected_count", [(2, 2), (4, 2), (10, 3), (20, 6)])
def test_top_mode_uses_floor_thirty_percent_and_at_least_two(rated_count, expected_count) -> None:
    """상위 리그는 평가한 기존 후보의 30%를 내림하고 최소 두 후보를 유지합니다."""

    state, identifiers = make_voting_state(rated_count, 1)
    state["mode"] = "top"
    state["evolution"] = {"candidate_ids": ["child"], "batch_id": "current-batch"}
    state["statistics"]["child"] = {**initial_candidate_statistics(), "rating": 99999, "placed": True}
    expected = list(reversed(identifiers[:rated_count]))[:expected_count]
    assert league_candidate_identifiers(state, identifiers + ["child"]) == expected
    for _ in range(8):
        match = choose_next_match(state, identifiers + ["child"])
        assert match["kind"] == "top"
        assert match["a"] in expected and match["b"] in expected


def test_mode_api_persists_without_vote_and_undo_keeps_selected_mode(rated_population) -> None:
    """Mode만 바꾸면 투표·Undo가 늘지 않고 이전 Vote를 Undo해도 현재 Mode를 보존합니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    original = read_selection(client, project)
    payload = mode_input(original, "league")
    response = client.post(endpoint + "/selection-mode", json=payload)
    assert response.status_code == 200, response.text
    league = response.json()
    assert league["revision"] == original["revision"] + 1
    assert league["match"]["token"] != original["match"]["token"]
    assert league["rankings"] == original["rankings"]
    assert league["canUndo"] == original["canUndo"]
    assert client.post(endpoint + "/selection-mode", json=payload).json() == league
    assert client.post(endpoint + "/selection-mode", json=mode_input(original, "top")).status_code == 409
    invalid = mode_input(league, "unsupported")
    assert client.post(endpoint + "/selection-mode", json=invalid).status_code == 422
    stale_vote = vote_input(league)
    stale_vote["matchToken"] = original["match"]["token"]
    assert client.post(endpoint + "/votes", json=stale_vote).status_code == 409
    with server.database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM style_vote_events").fetchone()[0] == 0
        saved = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
    assert saved["mode"] == "league"
    voted = client.post(endpoint + "/votes", json=vote_input(league)).json()
    top = change_mode(client, project, "top")
    assert top["undoEventIdentifier"] == voted["undoEventIdentifier"]
    undone_response = client.post(endpoint + "/undo", json=undo_input(top))
    assert undone_response.status_code == 200, undone_response.text
    undone = undone_response.json()
    assert undone["mode"] == "top"
    assert undone["rankings"] == original["rankings"]
    assert [undone["match"][side] for side in ("a", "b")] == [league["match"][side] for side in ("a", "b")]
    assert read_selection(client, project)["mode"] == "top"


def test_top_pair_cannot_include_lower_rank_and_modes_are_evaluation_local(rated_population) -> None:
    """수동 Pair도 상위 리그 범위를 지키고 새 Prompt 평가에는 이전 Mode를 전파하지 않습니다."""

    _, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    top = change_mode(client, project, "top")
    pair_payload = {key: value for key, value in mode_input(top, "top").items() if key != "mode"}
    pair_payload.update(firstCandidateIdentifier=top["rankings"][0]["identifier"], secondCandidateIdentifier=top["rankings"][-1]["identifier"])
    response = client.post(endpoint + "/selection-pair", json=pair_payload)
    assert response.status_code == 422, response.text
    settings = copy.deepcopy(project["settings"])
    settings["seed"] += 1
    updated_response = client.put(endpoint, json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "settings": settings})
    assert updated_response.status_code == 200, updated_response.text
    updated_project = updated_response.json()
    assert read_selection(client, updated_project)["mode"] == "auto"
    assert read_selection(client, project)["mode"] == "top"


@pytest.mark.parametrize("final_action", ["confirm", "cancel"])
def test_evolution_keeps_manual_votes_through_selection_undo_and_finish(rated_population, final_action) -> None:
    """진화 중 일반 투표를 자녀 Undo·확정·취소가 지우지 않고 고정 부모 기준점도 보존합니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    plan = prepare_evolution(client, project, 1)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    automatic = read_selection(client, project)
    assert automatic["match"]["kind"] == "select"
    assert not evolution_view(client, project)["batch"]["canConfirm"]
    with server.database._connect() as connection:
        original_state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
    parent_scores = original_state["evolution"]["parent_scores"]
    league = change_mode(client, project, "league")
    parents = sorted(parent_scores, key=parent_scores.get)
    pair_payload = {key: value for key, value in mode_input(league, "league").items() if key != "mode"}
    pair_payload.update(firstCandidateIdentifier=parents[0], secondCandidateIdentifier=parents[-1])
    paired_response = client.post(endpoint + "/selection-pair", json=pair_payload)
    assert paired_response.status_code == 200, paired_response.text
    paired = paired_response.json()
    voted_response = client.post(endpoint + "/votes", json=vote_input(paired, "a"))
    assert voted_response.status_code == 200, voted_response.text
    voted = voted_response.json()
    children = {candidate["identifier"] for candidate in plan["candidates"]}
    retained_statistics = {identifier: statistics for identifier, statistics in statistics_by_identifier(voted).items() if identifier not in children}
    assert retained_statistics[parents[0]]["rating"] != parent_scores[parents[0]]
    automatic = change_mode(client, project, "auto")
    assert automatic["match"]["kind"] == "select"
    child_side = "a" if automatic["match"]["a"] in children else "b"
    child_loses = "b" if child_side == "a" else "a"
    selected_response = client.post(endpoint + "/votes", json=vote_input(automatic, child_loses))
    assert selected_response.status_code == 200, selected_response.text
    selected = selected_response.json()
    assert selected["match"] is None
    undone_response = client.post(endpoint + "/undo", json=undo_input(selected))
    assert undone_response.status_code == 200, undone_response.text
    undone = undone_response.json()
    assert {identifier: statistics for identifier, statistics in statistics_by_identifier(undone).items() if identifier not in children} == retained_statistics
    selected_response = client.post(endpoint + "/votes", json=vote_input(undone, child_loses))
    assert selected_response.status_code == 200, selected_response.text
    manual = change_mode(client, project, "league")
    assert manual["match"]["kind"] == "league"
    assert not children.intersection((manual["match"]["a"], manual["match"]["b"]))
    forbidden_pair = {key: value for key, value in mode_input(manual, "league").items() if key != "mode"}
    forbidden_pair.update(firstCandidateIdentifier=next(iter(children)), secondCandidateIdentifier=parents[0])
    assert client.post(endpoint + "/selection-pair", json=forbidden_pair).status_code == 422
    assert evolution_view(client, project)["batch"]["canConfirm"]
    with server.database._connect() as connection:
        state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
    assert state["evolution"]["parent_scores"] == parent_scores
    for identifier in children:
        assert state["statistics"][identifier]["rating"] == min(parent_scores.values()) - 240
    finish_evolution(client, project, final_action)
    finished = read_selection(client, project)
    assert finished["mode"] == "league"
    assert finished["componentStatistics"] == voted["componentStatistics"]
    assert not finished["canUndo"]
    for identifier, expected in retained_statistics.items():
        actual = statistics_by_identifier(finished)[identifier]
        for field in ("rating", "matches", "wins", "skips"):
            assert actual[field] == expected[field]
