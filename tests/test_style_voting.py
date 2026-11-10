"""실제 Render를 사용하는 선별의 Elo·Undo·멱등성·격리·원본 산식을 검증합니다."""

import ast
import copy
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from home_server.style_voting_rules import apply_match_choice, calculate_regular_ratings, choose_next_match, initial_candidate_statistics, placement_position, placement_rating
from home_server.database import Database
from test_application import create_processing_test_app
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait


CLIENT_IDENTIFIER = "browser-client-0123456789abcdef"


def read_selection(client, project: dict, client_identifier: str = CLIENT_IDENTIFIER, evaluation_identifier: str | None = None) -> dict:
    """고정 Browser 식별자로 현재 평가 구간의 서버 Match를 조회합니다."""

    response = client.get(f"/api/style-projects/{project['identifier']}/selection", params={"evaluationIdentifier": evaluation_identifier or project["evaluationIdentifier"], "clientIdentifier": client_identifier})
    assert response.status_code == 200, response.text
    return response.json()


def vote_input(selection: dict, choice: str = "a", client_identifier: str = CLIENT_IDENTIFIER) -> dict:
    """화면에 표시된 정확한 Revision·Token·A/B 의미로 한 표를 만듭니다."""

    return {"evaluationIdentifier": selection["evaluationIdentifier"], "clientIdentifier": client_identifier, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": selection["revision"], "matchToken": selection["match"]["token"], "choice": choice}


def undo_input(selection: dict, client_identifier: str = CLIENT_IDENTIFIER) -> dict:
    """최신 본인 Event를 명시해 다른 선택에 대한 Undo를 막습니다."""

    return {"evaluationIdentifier": selection["evaluationIdentifier"], "clientIdentifier": client_identifier, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": selection["revision"], "eventIdentifier": selection["undoEventIdentifier"]}


def statistics_by_identifier(selection: dict) -> dict:
    """Rank 정렬과 무관하게 후보별 수치와 순위를 비교합니다."""

    return {entry["identifier"]: entry for entry in selection["rankings"]}


def test_vote_skip_undo_restores_exact_pair_and_exclusive_components(tmp_path) -> None:
    """여러 Prompt도 한 경기이며 공통 LoRA 제외·Skip 불변·Undo A/B 복원을 확인합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan_input["combinations"][1]["components"] = plan_input["combinations"][1]["components"][:1]
        plan, _, _ = submit_and_wait(client, project, plan_input)
        original = read_selection(client, project)
        match = original["match"]
        assert match["kind"] == "league"
        assert read_selection(client, project) == original
        endpoint = f"/api/style-projects/{project['identifier']}"
        response = client.post(endpoint + "/votes", json=vote_input(original))
        assert response.status_code == 200, response.text
        voted = response.json()
        statistics = statistics_by_identifier(voted)
        assert statistics[match["a"]]["rating"] == 10160
        assert statistics[match["b"]]["rating"] == 9840
        assert statistics[match["a"]]["matches"] == statistics[match["b"]]["matches"] == 1
        assert statistics[match["a"]]["wins"] == statistics[match["b"]]["losses"] == 1
        assert statistics[match["a"]]["rank"] == 1
        assert set(voted["componentStatistics"]) == {"artist:example"}
        assert voted["componentStatistics"]["artist:example"]["matches"] == 1
        assert voted["match"]["token"] != match["token"]
        skipped_response = client.post(endpoint + "/votes", json=vote_input(voted, "similar"))
        assert skipped_response.status_code == 200, skipped_response.text
        skipped = skipped_response.json()
        for identifier, entry in statistics_by_identifier(skipped).items():
            for field_name in ("rating", "matches", "wins", "losses"):
                assert entry[field_name] == statistics[identifier][field_name]
            assert entry["skips"] == 1
        assert skipped["componentStatistics"] == voted["componentStatistics"]
        unskip_response = client.post(endpoint + "/undo", json=undo_input(skipped))
        assert unskip_response.status_code == 200, unskip_response.text
        unskip = unskip_response.json()
        assert unskip["rankings"] == voted["rankings"]
        assert [unskip["match"][side] for side in ("a", "b")] == [voted["match"][side] for side in ("a", "b")]
        undo_response = client.post(endpoint + "/undo", json=undo_input(unskip))
        assert undo_response.status_code == 200, undo_response.text
        undone = undo_response.json()
        assert undone["rankings"] == original["rankings"]
        assert undone["componentStatistics"] == {}
        assert not undone["canUndo"]
        assert [undone["match"][side] for side in ("a", "b")] == [match[side] for side in ("a", "b")]
        assert undone["match"]["token"] != match["token"]
        stale_token = vote_input(undone)
        stale_token["matchToken"] = match["token"]
        assert client.post(endpoint + "/votes", json=stale_token).status_code == 409
        assert client.get("/api/jobs?include_style=true").json()["total"] == 1
    finally:
        client.__exit__(None, None, None)


def test_vote_idempotency_concurrency_and_other_browser_undo_rejection(tmp_path) -> None:
    """동일 요청 재전송은 한 표, 동시 다른 선택은 하나만, 타 Browser Undo는 거절합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        endpoint = f"/api/style-projects/{project['identifier']}"
        first_payload = vote_input(selection)
        second_payload = vote_input(selection, "b", "another-browser-0123456789")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.post, endpoint + "/votes", json=payload) for payload in (first_payload, second_payload)]
            responses = [future.result() for future in futures]
        assert sorted(response.status_code for response in responses) == [200, 409]
        accepted_index = next(index for index, response in enumerate(responses) if response.status_code == 200)
        accepted_payload = (first_payload, second_payload)[accepted_index]
        accepted = responses[accepted_index].json()
        assert client.post(endpoint + "/votes", json=accepted_payload).json() == accepted
        assert client.post(endpoint + "/votes", json={**accepted_payload, "choice": "similar"}).status_code == 409
        other_identifier = "third-browser-0123456789"
        other_selection = read_selection(client, project, other_identifier)
        assert not other_selection["canUndo"]
        assert other_selection["undoUnavailableReason"]
        assert client.post(endpoint + "/undo", json=undo_input(other_selection, other_identifier)).status_code == 409
        owner_selection = read_selection(client, project, accepted_payload["clientIdentifier"])
        assert client.post(endpoint + "/undo", json=undo_input(owner_selection, accepted_payload["clientIdentifier"])).status_code == 200
        with application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT count(*) FROM style_vote_events").fetchone()[0] == 1
    finally:
        client.__exit__(None, None, None)


def test_placement_freezes_ladder_and_undo_restores_newcomer(tmp_path) -> None:
    """새 후보 하나는 기존 Ladder 점수를 바꾸지 않고 배치되며 Undo로 돌아갑니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan_input["combinations"] = plan_input["combinations"][:1]
        first_plan, _, _ = submit_and_wait(client, project, plan_input)
        first_selection = read_selection(client, project)
        anchor_identifier = first_plan["candidates"][0]["identifier"]
        assert first_selection["match"] is None
        assert statistics_by_identifier(first_selection)[anchor_identifier]["placed"]
        plan_input["operationIdentifier"] = uuid.uuid4().hex
        plan_input["combinations"][0]["components"][0]["strength"] = 0.5
        second_plan, _, _ = submit_and_wait(client, project, plan_input)
        newcomer_identifier = second_plan["candidates"][0]["identifier"]
        placement = read_selection(client, project)
        assert placement["match"]["kind"] == "place"
        assert placement["match"]["a"] == newcomer_identifier
        endpoint = f"/api/style-projects/{project['identifier']}"
        voted = client.post(endpoint + "/votes", json=vote_input(placement)).json()
        statistics = statistics_by_identifier(voted)
        assert statistics[newcomer_identifier]["rating"] == 10480
        assert statistics[newcomer_identifier]["placed"]
        assert statistics[newcomer_identifier]["wins"] == 1
        assert statistics[anchor_identifier] == statistics_by_identifier(first_selection)[anchor_identifier] | {"rank": 2}
        undone = client.post(endpoint + "/undo", json=undo_input(voted)).json()
        assert undone["match"]["kind"] == "place"
        assert undone["rankings"] == placement["rankings"]
        skipped = client.post(endpoint + "/votes", json=vote_input(undone, "similar")).json()
        assert statistics_by_identifier(skipped)[newcomer_identifier]["placed"]
        assert statistics_by_identifier(skipped)[anchor_identifier]["rating"] == 10000
    finally:
        client.__exit__(None, None, None)


def test_selection_persists_restart_and_undo_is_evaluation_isolated(tmp_path) -> None:
    """서버 재시작 후 점수·Undo를 복원하고 Seed가 바뀐 평가 구간과 섞지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        endpoint = f"/api/style-projects/{project['identifier']}"
        voted = client.post(endpoint + "/votes", json=vote_input(selection)).json()
        settings = copy.deepcopy(project["settings"])
        settings["seed"] += 1
        response = client.put(endpoint, json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "settings": settings})
        assert response.status_code == 200, response.text
        updated_project = response.json()
        new_selection = read_selection(client, updated_project)
        assert new_selection["rankings"] == []
        assert new_selection["match"] is None
        assert not new_selection["canUndo"]
    finally:
        client.__exit__(None, None, None)
    restarted = create_processing_test_app(tmp_path, StyleComfyClient())
    with TestClient(restarted) as restarted_client:
        restarted_client.post("/api/login", json={"password": "test"})
        restored = read_selection(restarted_client, project)
        assert restored["rankings"] == voted["rankings"]
        assert restored["match"] == voted["match"]
        undo_response = restarted_client.post(endpoint + "/undo", json=undo_input(restored))
        assert undo_response.status_code == 200, undo_response.text
        assert undo_response.json()["rankings"] == selection["rankings"]
        assert read_selection(restarted_client, updated_project)["rankings"] == []


def test_incomplete_images_are_not_votable_and_stale_pair_is_rejected(tmp_path) -> None:
    """Case 하나라도 준비되지 않으면 비교를 접수하지 않고 같은 후보 Pair도 거절합니다."""

    fake_client = StyleComfyClient()
    fake_client.fail_first_submission = True
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        plan, _, _ = submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        assert len(selection["readyCandidateIdentifiers"]) == 1
        assert selection["match"] is None
        endpoint = f"/api/style-projects/{project['identifier']}"
        invalid_vote = {"evaluationIdentifier": project["evaluationIdentifier"], "clientIdentifier": CLIENT_IDENTIFIER, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": selection["revision"], "matchToken": "invalid-match-token-0000", "choice": "a"}
        assert client.post(endpoint + "/votes", json=invalid_vote).status_code == 409
        other_selection = client.get(endpoint + "/selection", params={"evaluationIdentifier": "missing-evaluation", "clientIdentifier": CLIENT_IDENTIFIER})
        assert other_selection.status_code == 404
    finally:
        client.__exit__(None, None, None)


def load_legacy_rating_functions() -> dict:
    """보관한 원문의 순수 함수만 AST로 꺼내 실제 원본 산식을 Golden 기준으로 사용합니다."""

    snapshot_path = Path(__file__).resolve().parents[1] / "docs/style-lab-rebuild/source_reference/style_lab/app__core.py.md"
    source = snapshot_path.read_text(encoding="utf-8").split("```python\n", 1)[1].rsplit("```", 1)[0]
    selected_names = {"calc_elo", "_bisect", "_climb_rung", "_best_slots", "placement_state", "placement_elo"}
    source_module = ast.parse(source)
    selected_module = ast.Module(body=[node for node in source_module.body if isinstance(node, ast.FunctionDef) and node.name in selected_names], type_ignores=[])
    namespace = {"RATING_SCALE": 10, "ELO_K": 320, "START_ELO": 10000, "PLACE_GAP": 480}
    exec(compile(selected_module, str(snapshot_path), "exec"), namespace)
    return namespace


def test_regular_and_placement_match_legacy_golden_functions() -> None:
    """일반 Elo·경계 반올림·Tie 경로·모순 Vote의 Slot을 원본 함수와 비교합니다."""

    legacy = load_legacy_rating_functions()
    for first_rating, second_rating in [(10000, 10000), (10160, 9840), (5000, 20000), (9999, 10001)]:
        for first_won in (True, False):
            assert calculate_regular_ratings(first_rating, second_rating, first_won) == legacy["calc_elo"](first_rating, second_rating, first_won)
    for ladder_size in range(1, 9):
        frontier = [[]]
        for _ in range(5):
            next_frontier = []
            for votes in frontier:
                expected_position = legacy["placement_state"](votes, ladder_size)
                assert placement_position(votes, ladder_size) == expected_position
                if expected_position[1] is not None:
                    for result in ("win", "loss", "tie"):
                        next_frontier.append(votes + [(expected_position[1], result)])
            frontier = next_frontier
        for votes in [[(0, "loss"), (0, "win")], [(0, "tie"), (ladder_size - 1, "loss")]]:
            assert placement_position(votes, ladder_size) == legacy["placement_state"](votes, ladder_size)
    for ladder_scores in [[], [10000], [9999, 10000], [9840, 10000, 10160]]:
        for slot_index in range(len(ladder_scores) + 1):
            assert placement_rating(slot_index, ladder_scores) == legacy["placement_elo"](slot_index, ladder_scores)


def test_boundary_skip_is_remembered_without_changing_ratings() -> None:
    """경계 동점 Skip은 같은 Pair의 같은 점수 질문을 다시 강요하지 않습니다."""

    identifiers = ["first", "second", "third", "fourth"]
    state = {"statistics": {identifier: {**initial_candidate_statistics(), "matches": 1} for identifier in identifiers}, "componentStatistics": {}, "placement": None, "skippedTies": [], "lastPair": [], "match": None}
    for _ in range(6):
        state["match"] = choose_next_match(state, identifiers)
        assert state["match"]["kind"] == "tie"
        apply_match_choice(state, "similar", {})
    assert choose_next_match(state, identifiers)["kind"] == "league"
    assert all(candidate["rating"] == 10000 for candidate in state["statistics"].values())


def test_undo_limit_survives_repeated_undo_and_new_generation(tmp_path) -> None:
    """최근 30개 한도를 영속 유지하고 투표 뒤 만든 이미지와 후보를 Undo가 삭제하지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        endpoint = f"/api/style-projects/{project['identifier']}"
        for _ in range(32):
            response = client.post(endpoint + "/votes", json=vote_input(selection, "similar"))
            assert response.status_code == 200, response.text
            selection = response.json()
        plan_input["operationIdentifier"] = uuid.uuid4().hex
        submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        assert len(selection["rankings"]) == 4
        for _ in range(30):
            response = client.post(endpoint + "/undo", json=undo_input(selection))
            assert response.status_code == 200, response.text
            selection = response.json()
        assert not selection["canUndo"]
        assert len(selection["rankings"]) == 4
        assert client.get("/api/jobs?include_style=true").json()["total"] == 2
        assert client.get("/api/outputs?include_style=true").json()["total"] == 8
    finally:
        client.__exit__(None, None, None)


def test_deleted_image_and_foreign_candidate_are_rejected_without_score_change(tmp_path) -> None:
    """파일 삭제·서로 다른 소유 후보·같은 후보 Pair를 실제 수치 변경 전에 거절합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        selection = read_selection(client, project)
        endpoint = f"/api/style-projects/{project['identifier']}"
        pair_payload = {key: value for key, value in vote_input(selection).items() if key not in {"matchToken", "choice"}}
        pair_payload.update(firstCandidateIdentifier=selection["match"]["a"], secondCandidateIdentifier=selection["match"]["a"])
        assert client.post(endpoint + "/selection-pair", json=pair_payload).status_code == 422
        pair_payload.update(operationIdentifier=uuid.uuid4().hex, secondCandidateIdentifier="another-project-candidate")
        assert client.post(endpoint + "/selection-pair", json=pair_payload).status_code == 422
        candidate = next(candidate for candidate in results["candidates"] if candidate["identifier"] == selection["match"]["a"])
        image_path = application.state.home_server.managed_path(candidate["renders"][0]["files"][0]["path"])
        image_path.unlink()
        response = client.post(endpoint + "/votes", json=vote_input(selection))
        assert response.status_code == 422
        latest = read_selection(client, project)
        assert all(entry["matches"] == 0 for entry in latest["rankings"])
        assert latest["match"] is None
        assert len(latest["readyCandidateIdentifiers"]) == 1
    finally:
        client.__exit__(None, None, None)


def test_schema_sixteen_migration_keeps_source_backup_and_existing_data(tmp_path) -> None:
    """16→17 Migration은 검증된 원본 Backup 뒤 새 평가 테이블만 추가합니다."""

    database_path = tmp_path / "migration.sqlite3"
    database = Database(database_path)
    database.save_preset("kept-preset", "기존 Preset", "anima", {"prompt": "keep"})
    with sqlite3.connect(database_path) as connection:
        for table_name in ("style_voting_commands", "style_vote_events", "style_voting_arenas"):
            connection.execute("DROP TABLE " + table_name)
        connection.execute("PRAGMA user_version = 16")
    migrated = Database(database_path)
    assert migrated.list_presets()[0]["preset_id"] == "kept-preset"
    backup_paths = list((tmp_path / "backups").glob("migration_before_style_voting_*.sqlite3"))
    assert len(backup_paths) == 1
    with sqlite3.connect(backup_paths[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
