"""전체 기존 순위표·신규끼리 비교·미확정 Elo·진행 세대의 정책 전환을 검증합니다."""

import copy
import hashlib
import json

from home_server.style_evolution_selection import AUTOMATIC_PLACEMENT_POLICY, build_selection_ranking, next_selection_pair, synchronize_selection_statistics
from home_server.style_projects import encode_snapshot
from home_server.style_voting import StyleVoteInput
from home_server.style_voting_rules import choose_next_match, initial_candidate_statistics
from test_style_evolution import evolution_view, finish_evolution, prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_voting import read_selection, statistics_by_identifier, undo_input, vote_input


def rendered_asset_hashes(server, client, project: dict) -> dict:
    """모든 실제 임시 PNG를 읽어 정책 변경이 파일을 바꾸지 않는지 대조합니다."""

    results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
    hashes = {}
    for candidate in results["candidates"]:
        for render in candidate["renders"]:
            for output_file in render["files"]:
                hashes[output_file["path"]] = hashlib.sha256(server.managed_path(output_file["path"]).read_bytes()).hexdigest()
    return hashes


def test_existing_reference_disables_single_vote_fresh_shortcut() -> None:
    """기존 기준점이 하나라도 있으면 신규끼리 한 표만 받고 기존 순위표를 건너뛰지 않습니다."""

    statistics = {identifier: initial_candidate_statistics() for identifier in ["existing", "new-first", "new-second"]}
    statistics["existing"].update(rating=14000, placed=True)
    state = {"statistics": statistics, "placement": None, "lastPair": [], "skippedTies": []}
    match = choose_next_match(state, list(statistics))
    assert match["kind"] == "place" and match["b"] == "existing"
    assert statistics[match["a"]]["placementPending"]


def test_shared_slot_stays_provisional_until_all_peer_comparisons_finish() -> None:
    """자신의 대결을 끝냈어도 같은 구간의 남은 대결이 Elo를 바꿀 수 있으면 미확정입니다."""

    references = [f"reference-{index}" for index in range(10)]
    scores = {identifier: 10000 + index * 100 for index, identifier in enumerate(references)}
    children = ["child-first", "child-second", "child-third"]
    selection = {"batch_id": "fixture-batch", "placement_policy": AUTOMATIC_PLACEMENT_POLICY,
        "parent_ids": references[-3:], "parent_scores": {identifier: scores[identifier] for identifier in references[-3:]},
        "reference_ids": references, "reference_scores": scores, "candidate_ids": children, "history": []}
    for child in children:
        for reference in references:
            selection["history"].append({"batch_id": "fixture-batch", "pair": {"a": child, "b": reference}, "type": "selection_vote", "winner_id": child})
    for opponent in children[1:]:
        selection["history"].insert(0, {"batch_id": "fixture-batch", "pair": {"a": children[0], "b": opponent}, "type": "selection_vote", "winner_id": children[0]})
    state = {"evolution": selection, "statistics": {identifier: initial_candidate_statistics() for identifier in references + children}}
    synchronize_selection_statistics(state)
    assert build_selection_ranking(selection)["completed_identifiers"] == []
    assert state["statistics"][children[0]]["placementPending"]
    selection["history"].insert(0, {"batch_id": "fixture-batch", "pair": {"a": children[1], "b": children[2]}, "type": "selection_vote", "winner_id": children[1]})
    synchronize_selection_statistics(state)
    assert set(build_selection_ranking(selection)["completed_identifiers"]) == set(children)
    assert all(not state["statistics"][identifier]["placementPending"] for identifier in children)


def test_automatic_placement_searches_all_references_and_orders_newcomers(rated_population) -> None:
    """최하위 부모에 진 후보도 여러 기존 조합·같은 구간 신규와 비교한 뒤 확정합니다."""

    _, _, client, project, source_plan = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    source = statistics_by_identifier(read_selection(client, project))
    plan = prepare_evolution(client, project, 3)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    children = [candidate["identifier"] for candidate in plan["candidates"]]
    qualities = {candidate["identifier"]: 10000 + index * 100 for index, candidate in enumerate(source_plan["candidates"])}
    qualities.update(dict(zip(children, [10350, 10375, 10750])))
    parents = set(evolution_view(client, project)["batch"]["parentIdentifiers"])
    compared_with_nonparents = False
    compared_newcomers = False
    comparisons_by_child = dict.fromkeys(children, 0)
    selection = read_selection(client, project)
    assert selection["automaticPlacement"]["referenceCount"] == 10
    for identifier in children:
        assert statistics_by_identifier(selection)[identifier]["placementPending"]
        assert statistics_by_identifier(selection)[identifier]["rank"] is None
    for _ in range(100):
        view = evolution_view(client, project)
        if view["batch"]["canConfirm"]:
            break
        match = selection["match"]
        assert match and match["kind"] == "select"
        pair = {match["a"], match["b"]}
        if pair <= set(children):
            compared_newcomers = True
            assert not view["batch"]["canConfirm"]
            assert selection["automaticPlacement"]["comparingNewcomers"]
        elif any(identifier not in parents and identifier not in children for identifier in pair):
            compared_with_nonparents = True
        choice = "a" if qualities[match["a"]] > qualities[match["b"]] else "b"
        response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
        assert response.status_code == 200, response.text
        selection = response.json()
        for identifier in pair & set(children):
            comparisons_by_child[identifier] += 1
            if comparisons_by_child[identifier] == 1:
                statistics = statistics_by_identifier(selection)[identifier]
                assert statistics["placementPending"] and not statistics["rated"]
                assert statistics["rank"] is None
        for identifier, original in source.items():
            current = statistics_by_identifier(selection)[identifier]
            for field in ("rating", "matches", "wins", "losses", "skips"):
                assert current[field] == original[field]
    else:
        raise AssertionError("자동 Placement가 종료되지 않았습니다.")
    assert compared_with_nonparents and compared_newcomers
    assert min(comparisons_by_child.values()) >= 3
    assert set(view["batch"]["completedCandidateIdentifiers"]) == set(children)
    assert view["batch"]["enteredCandidateIdentifiers"] == [children[2]]
    statistics = statistics_by_identifier(selection)
    assert statistics[children[0]]["rating"] < statistics[children[1]]["rating"] < statistics[children[2]]["rating"]
    assert all(not statistics[identifier]["placementPending"] and statistics[identifier]["rated"] for identifier in children)
    result, _ = finish_evolution(client, project, "confirm")
    assert result["enteredCount"] == result["retiredExistingCount"] == 1
    assert result["failedCount"] == 2


def test_migration_preserves_legacy_votes_files_and_undo_then_reopens_placement(rated_population) -> None:
    """한 표 탈락 상태를 실제 옛 Snapshot으로 구성해 표·파일을 보존하고 Undo까지 이어갑니다."""

    server, fake, client, project, _ = rated_population
    plan = prepare_evolution(client, project, 6)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    children = {candidate["identifier"] for candidate in plan["candidates"]}
    with server.database._connect() as connection:
        row = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()
        state = json.loads(row["state_json"])
        batch_row = connection.execute("SELECT batch_id,batch_json FROM style_evolution_batches WHERE plan_id=?", (plan["planIdentifier"],)).fetchone()
        batch = json.loads(batch_row["batch_json"])
        for field in ("placement_policy", "reference_ids", "reference_scores"):
            state["evolution"].pop(field)
            batch.pop(field)
        for identifier in children:
            state["statistics"][identifier].pop("placementPending", None)
        candidates, ready_identifiers = server.style_voting.load_evaluation_candidates(connection, project["identifier"], project["evaluationIdentifier"])
        state["match"] = choose_next_match(state, ready_identifiers)
        for _ in range(6):
            match = state["match"]
            assert match and match["kind"] == "select"
            choice = "b" if match["a"] in children else "a"
            payload = StyleVoteInput(**vote_input({"evaluationIdentifier": project["evaluationIdentifier"], "revision": row["revision"], "match": match}, choice))
            server.style_voting.record_vote(connection, state, ready_identifiers, candidates, payload)
            server.style_voting.synchronize_candidates(state, candidates, ready_identifiers)
        assert state["match"] is None
        assert next_selection_pair(state["evolution"], ready_identifiers) is None
        original_history = copy.deepcopy(state["evolution"]["history"])
        server.style_voting.save_arena(connection, project["evaluationIdentifier"], row["revision"] + 6, state)
        connection.execute("UPDATE style_evolution_batches SET batch_json=? WHERE batch_id=?", (encode_snapshot(batch), batch_row["batch_id"]))
        original_events = connection.execute("SELECT * FROM style_vote_events ORDER BY rowid").fetchall()
        original_commands = connection.execute("SELECT * FROM style_voting_commands ORDER BY rowid").fetchall()
    original_assets = rendered_asset_hashes(server, client, project)
    submissions_before = len(fake.submissions)
    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        migrated_revision = connection.execute("SELECT revision FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0]
        assert connection.execute("SELECT * FROM style_vote_events ORDER BY rowid").fetchall() == original_events
        assert connection.execute("SELECT * FROM style_voting_commands ORDER BY rowid").fetchall() == original_commands
    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        assert connection.execute("SELECT revision FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0] == migrated_revision
        state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
        assert state["evolution"]["history"] == original_history
    selection = read_selection(client, project)
    assert selection["canUndo"] and selection["match"]["kind"] == "select"
    assert not evolution_view(client, project)["batch"]["canConfirm"]
    assert all(statistics_by_identifier(selection)[identifier]["placementPending"] for identifier in children)
    assert rendered_asset_hashes(server, client, project) == original_assets
    assert len(fake.submissions) == submissions_before
    undone = client.post(f"/api/style-projects/{project['identifier']}/undo", json=undo_input(selection))
    assert undone.status_code == 200, undone.text
    assert undone.json()["automaticPlacement"]["referenceCount"] == 10
    with server.database._connect() as connection:
        state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
        assert len(state["evolution"]["history"]) == 5
        assert state["evolution"]["placement_policy"] == AUTOMATIC_PLACEMENT_POLICY


def test_planned_batch_upgrade_keeps_submission_revision_and_closed_batches(rated_population) -> None:
    """미제출 계획은 같은 Revision으로 이어 제출하고 취소 이력 JSON은 소급 변경하지 않습니다."""

    server, _, client, project, _ = rated_population
    archived_plan = prepare_evolution(client, project, 1)
    finish_evolution(client, project, "cancel")
    plan = prepare_evolution(client, project, 1)
    with server.database._connect() as connection:
        row = connection.execute("SELECT batch_json FROM style_evolution_batches WHERE plan_id=?", (plan["planIdentifier"],)).fetchone()
        batch = json.loads(row[0])
        for field in ("placement_policy", "reference_ids", "reference_scores"):
            batch.pop(field)
        connection.execute("UPDATE style_evolution_batches SET batch_json=? WHERE plan_id=?", (encode_snapshot(batch), plan["planIdentifier"]))
        archived_before = tuple(connection.execute("SELECT * FROM style_evolution_batches WHERE plan_id=?", (archived_plan["planIdentifier"],)).fetchone())
        original_revision = connection.execute("SELECT revision FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0]
    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        assert connection.execute("SELECT revision FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0] == original_revision
        assert tuple(connection.execute("SELECT * FROM style_evolution_batches WHERE plan_id=?", (archived_plan["planIdentifier"],)).fetchone()) == archived_before
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    assert evolution_view(client, project)["batch"]["placementPolicy"] == AUTOMATIC_PLACEMENT_POLICY
