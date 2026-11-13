"""StyleLab 부모 선별·신규 Placement 경계·진행 Batch의 안전한 정책 복원을 검증합니다."""

import copy
import hashlib
import json

import pytest

from home_server.style_evolution_selection import STYLELAB_SELECTION_POLICY, build_selection_ranking, next_selection_pair, synchronize_selection_statistics
from home_server.style_projects import encode_snapshot
from home_server.style_voting import StyleVoteInput
from home_server.style_voting_rules import choose_next_match, initial_candidate_statistics, new_match
from test_style_evolution import evolution_view, finish_evolution, prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_voting import read_selection, statistics_by_identifier, undo_input, vote_input


def rendered_asset_hashes(server, client, project: dict) -> dict:
    """모든 실제 임시 PNG를 읽어 정책 변경이 파일을 바꾸지 않는지 대조합니다."""

    results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
    hashes = {}
    for candidate in results["candidates"]:
        for render in candidate["renders"]:
            for output_file in render["files"]:
                image_bytes = server.managed_path(output_file["path"]).read_bytes()
                hashes[output_file["path"]] = hashlib.sha256(image_bytes).hexdigest()
    return hashes


def selection_with_children_in_slot(slot_index: int) -> dict:
    """세 부모를 모두 비교한 자녀 세 명을 지정한 부모 사이 Slot에 배치합니다."""

    parents = ["parent-low", "parent-middle", "parent-high"]
    children = ["child-first", "child-second", "child-third"]
    selection = {
        "batch_id": "fixture-batch",
        "placement_policy": STYLELAB_SELECTION_POLICY,
        "parent_ids": parents,
        "parent_scores": dict(zip(parents, [10000, 10320, 10640])),
        "candidate_ids": children,
        "history": [],
    }
    for child_identifier in children:
        for parent_index, parent_identifier in enumerate(parents):
            selection["history"].insert(0, {
                "batch_id": selection["batch_id"],
                "pair": {"a": child_identifier, "b": parent_identifier},
                "type": "selection_vote",
                "winner_id": child_identifier if parent_index < slot_index else parent_identifier,
            })
    return selection


def attach_legacy_reference_ladder(selection: dict, source_statistics: dict) -> None:
    """잘못된 전체 Ladder 정책이 저장했던 필드를 Migration 입력에 재현합니다."""

    selection["placement_policy"] = "full-ladder-placement-v2"
    selection["reference_ids"] = list(source_statistics)
    selection["reference_scores"] = {
        identifier: statistics["rating"]
        for identifier, statistics in source_statistics.items()
    }


@pytest.mark.parametrize("existing_count", [23, 24])
def test_random_newcomers_follow_original_twenty_four_reference_threshold(existing_count: int) -> None:
    """일반 Random은 평가된 기존 후보 24개 미만이면 신규끼리, 24개부터 기존 Ladder와 비교합니다."""

    existing_identifiers = [f"existing-{index:02d}" for index in range(existing_count)]
    newcomer_identifiers = ["new-first", "new-second"]
    statistics = {}
    for identifier in existing_identifiers + newcomer_identifiers:
        statistics[identifier] = initial_candidate_statistics()
    for index, identifier in enumerate(existing_identifiers):
        statistics[identifier].update(rating=14000 + index * 100, placed=True)
    state = {"statistics": statistics, "placement": None, "lastPair": [], "skippedTies": []}

    match = choose_next_match(state, list(statistics))

    if existing_count < 24:
        assert match["kind"] == "league" and match["metadata"]["fresh"]
        assert {match["a"], match["b"]} == set(newcomer_identifiers)
        assert state["placement"] is None
    else:
        assert match["kind"] == "place"
        assert match["a"] in newcomer_identifiers
        assert match["b"] in existing_identifiers
        assert statistics[match["a"]]["placementPending"]


@pytest.mark.parametrize("slot_index", [0, 3])
def test_children_outside_promotion_boundary_do_not_require_peer_comparisons(slot_index: int) -> None:
    """같은 Slot이어도 모두 탈락하거나 모두 승격하면 불필요한 자녀끼리 대결을 만들지 않습니다."""

    selection = selection_with_children_in_slot(slot_index)
    ranking = build_selection_ranking(selection)

    assert ranking["boundary_pairs"] == []
    assert set(ranking["completed_identifiers"]) == set(selection["candidate_ids"])
    assert next_selection_pair(selection, selection["parent_ids"] + selection["candidate_ids"]) is None


def test_same_slot_children_compare_only_when_crossing_promotion_boundary() -> None:
    """상위 부모 수만큼 승격시키는 경계에 걸친 같은 Slot 자녀만 서로 비교합니다."""

    selection = selection_with_children_in_slot(2)
    children = selection["candidate_ids"]
    state = {
        "evolution": selection,
        "statistics": {
            identifier: initial_candidate_statistics()
            for identifier in selection["parent_ids"] + children
        },
    }
    synchronize_selection_statistics(state)
    ranking = build_selection_ranking(selection)
    assert len(ranking["boundary_pairs"]) == 3
    assert ranking["completed_identifiers"] == []
    assert all(state["statistics"][identifier]["placed"] for identifier in children)
    assert all(not state["statistics"][identifier].get("placementPending", False) for identifier in children)

    for first_index, first_identifier in enumerate(children):
        for second_identifier in children[first_index + 1:]:
            selection["history"].insert(0, {
                "batch_id": selection["batch_id"],
                "pair": {"a": first_identifier, "b": second_identifier},
                "type": "selection_vote",
                "winner_id": first_identifier,
            })
    ranking = build_selection_ranking(selection)
    assert ranking["boundary_pairs"] == []
    assert set(ranking["completed_identifiers"]) == set(children)


def test_legacy_nonparent_votes_remain_in_history_but_do_not_change_selection_statistics() -> None:
    """옛 비부모 승패·비슷함은 원본 이력에 남기되 부모 선별 점수·전적에는 반영하지 않습니다."""

    selection = selection_with_children_in_slot(0)
    original_state = {
        "evolution": selection,
        "statistics": {
            identifier: initial_candidate_statistics()
            for identifier in selection["parent_ids"] + selection["candidate_ids"]
        },
    }
    synchronize_selection_statistics(original_state)
    migrated_state = copy.deepcopy(original_state)
    migrated_selection = migrated_state["evolution"]
    for child_identifier in selection["candidate_ids"]:
        for vote_type in ("selection_vote", "selection_skip"):
            legacy_vote = {
                "batch_id": selection["batch_id"],
                "pair": {"a": child_identifier, "b": "legacy-nonparent"},
                "type": vote_type,
            }
            if vote_type == "selection_vote":
                legacy_vote["winner_id"] = child_identifier
            migrated_selection["history"].insert(0, legacy_vote)
    original_history = copy.deepcopy(migrated_selection["history"])

    synchronize_selection_statistics(migrated_state)

    assert migrated_state["statistics"] == original_state["statistics"]
    assert migrated_selection["history"] == original_history
    original_ranking = build_selection_ranking(selection)
    migrated_ranking = build_selection_ranking(migrated_selection)
    for field in ("ladder", "scores", "counts", "ascending", "boundary_pairs", "completed_identifiers"):
        assert migrated_ranking[field] == original_ranking[field]


def test_child_losing_to_lowest_parent_finishes_in_one_vote(rated_population) -> None:
    """기존 10개 중 상위 부모 3개만 기준으로 삼고 최하위 부모 패배는 한 표로 종료합니다."""

    _, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    original_statistics = statistics_by_identifier(read_selection(client, project))
    plan = prepare_evolution(client, project, 1)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    child_identifier = plan["candidates"][0]["identifier"]
    batch = evolution_view(client, project)["batch"]
    parents = batch["parentIdentifiers"]
    lowest_parent = min(parents, key=lambda identifier: original_statistics[identifier]["rating"])
    selection = read_selection(client, project)

    assert batch["placementPolicy"] == STYLELAB_SELECTION_POLICY
    assert len(original_statistics) == 10 and len(parents) == 3
    assert selection["automaticPlacement"]["referenceCount"] == 3
    assert {selection["match"]["a"], selection["match"]["b"]} == {child_identifier, lowest_parent}
    choice = "a" if selection["match"]["a"] == lowest_parent else "b"
    response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
    assert response.status_code == 200, response.text
    selection = response.json()
    child_statistics = statistics_by_identifier(selection)[child_identifier]

    assert selection["match"] is None
    assert selection["automaticPlacement"]["completedCount"] == 1
    assert child_statistics["matches"] == child_statistics["losses"] == 1
    assert child_statistics["rated"] and not child_statistics["placementPending"]
    assert child_statistics["rating"] < original_statistics[lowest_parent]["rating"]
    for identifier, original in original_statistics.items():
        current = statistics_by_identifier(selection)[identifier]
        for field in ("rating", "matches", "wins", "losses", "skips"):
            assert current[field] == original[field]
    assert evolution_view(client, project)["batch"]["canConfirm"]
    result, _ = finish_evolution(client, project, "confirm")
    assert result["enteredCount"] == result["retiredExistingCount"] == 0
    assert result["failedCount"] == 1


def test_migration_preserves_legacy_votes_files_commands_and_undo(rated_population) -> None:
    """기존 전체 Ladder 표와 파일은 보존하고 비부모 표를 제외해 재계산하며 옛 Undo도 복원합니다."""

    server, fake, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    source_statistics = statistics_by_identifier(read_selection(client, project))
    plan = prepare_evolution(client, project, 1)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    child_identifier = plan["candidates"][0]["identifier"]
    selection = read_selection(client, project)
    lowest_parent = next(
        selection["match"][side] for side in ("a", "b")
        if selection["match"][side] in source_statistics
    )
    parent_choice = "a" if selection["match"]["a"] == lowest_parent else "b"
    response = client.post(endpoint + "/votes", json=vote_input(selection, parent_choice))
    assert response.status_code == 200, response.text

    with server.database._connect() as connection:
        arena_row = connection.execute(
            "SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone()
        state = json.loads(arena_row["state_json"])
        batch_row = connection.execute(
            "SELECT batch_id,batch_json FROM style_evolution_batches WHERE plan_id=?",
            (plan["planIdentifier"],),
        ).fetchone()
        batch = json.loads(batch_row["batch_json"])
        attach_legacy_reference_ladder(state["evolution"], source_statistics)
        attach_legacy_reference_ladder(batch, source_statistics)
        nonparent_identifier = next(
            identifier for identifier in source_statistics
            if identifier not in batch["parent_ids"]
        )
        candidates, ready_identifiers = server.style_voting.load_evaluation_candidates(
            connection, project["identifier"], project["evaluationIdentifier"],
        )
        state["match"] = new_match("select", child_identifier, nonparent_identifier, batchIdentifier=batch_row["batch_id"])
        legacy_payload = StyleVoteInput(**vote_input({
            "evaluationIdentifier": project["evaluationIdentifier"],
            "revision": arena_row["revision"],
            "match": state["match"],
        }, "a"))
        server.style_voting.record_vote(connection, state, ready_identifiers, candidates, legacy_payload)
        state["match"] = new_match("select", child_identifier, nonparent_identifier, batchIdentifier=batch_row["batch_id"])
        state["statistics"][child_identifier].update(matches=2, wins=1, rating=10150, placed=False, placementPending=True)
        original_history = copy.deepcopy(state["evolution"]["history"])
        original_undo_stack = list(state["undoStack"])
        server.style_voting.save_arena(connection, project["evaluationIdentifier"], arena_row["revision"] + 1, state)
        connection.execute(
            "UPDATE style_evolution_batches SET batch_json=? WHERE batch_id=?",
            (encode_snapshot(batch), batch_row["batch_id"]),
        )
        original_events = connection.execute("SELECT * FROM style_vote_events ORDER BY rowid").fetchall()
        original_commands = connection.execute("SELECT * FROM style_voting_commands ORDER BY rowid").fetchall()
        assert len(original_events) == 2 and len(original_commands) == 1
    original_assets = rendered_asset_hashes(server, client, project)
    submissions_before = len(fake.submissions)

    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        migrated_arena = tuple(connection.execute(
            "SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone())
        assert connection.execute("SELECT * FROM style_vote_events ORDER BY rowid").fetchall() == original_events
        assert connection.execute("SELECT * FROM style_voting_commands ORDER BY rowid").fetchall() == original_commands
        migrated_state = json.loads(migrated_arena[1])
        assert migrated_state["evolution"]["history"] == original_history
        assert migrated_state["undoStack"] == original_undo_stack
        assert migrated_state["evolution"]["placement_policy"] == STYLELAB_SELECTION_POLICY
    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        assert tuple(connection.execute(
            "SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone()) == migrated_arena

    selection = read_selection(client, project)
    child_statistics = statistics_by_identifier(selection)[child_identifier]
    assert selection["canUndo"] and selection["match"] is None
    assert selection["automaticPlacement"]["referenceCount"] == 3
    assert child_statistics["matches"] == child_statistics["losses"] == 1
    assert child_statistics["wins"] == child_statistics["skips"] == 0
    assert evolution_view(client, project)["batch"]["canConfirm"]
    assert rendered_asset_hashes(server, client, project) == original_assets
    assert len(fake.submissions) == submissions_before

    undone = client.post(endpoint + "/undo", json=undo_input(selection))
    assert undone.status_code == 200, undone.text
    selection = undone.json()
    assert selection["match"] is None and selection["canUndo"]
    assert selection["automaticPlacement"]["referenceCount"] == 3
    with server.database._connect() as connection:
        restored_state = json.loads(connection.execute(
            "SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone()[0])
        assert restored_state["evolution"]["placement_policy"] == STYLELAB_SELECTION_POLICY
        assert restored_state["evolution"]["history"] == original_history[1:]
    undone = client.post(endpoint + "/undo", json=undo_input(selection))
    assert undone.status_code == 200, undone.text
    selection = undone.json()
    assert not selection["canUndo"]
    assert {selection["match"]["a"], selection["match"]["b"]} == {child_identifier, lowest_parent}
    assert not evolution_view(client, project)["batch"]["canConfirm"]
    assert rendered_asset_hashes(server, client, project) == original_assets


def test_planned_batch_migration_keeps_submission_revision_and_closed_batches(rated_population) -> None:
    """미제출 계획은 같은 Revision으로 이어 제출하고 취소된 Batch JSON은 소급 변경하지 않습니다."""

    server, _, client, project, _ = rated_population
    source_statistics = statistics_by_identifier(read_selection(client, project))
    archived_plan = prepare_evolution(client, project, 1)
    finish_evolution(client, project, "cancel")
    plan = prepare_evolution(client, project, 1)
    with server.database._connect() as connection:
        for saved_plan in (archived_plan, plan):
            batch_row = connection.execute(
                "SELECT batch_json FROM style_evolution_batches WHERE plan_id=?",
                (saved_plan["planIdentifier"],),
            ).fetchone()
            batch = json.loads(batch_row[0])
            attach_legacy_reference_ladder(batch, source_statistics)
            connection.execute(
                "UPDATE style_evolution_batches SET batch_json=? WHERE plan_id=?",
                (encode_snapshot(batch), saved_plan["planIdentifier"]),
            )
        archived_before = tuple(connection.execute(
            "SELECT * FROM style_evolution_batches WHERE plan_id=?",
            (archived_plan["planIdentifier"],),
        ).fetchone())
        original_revision = connection.execute(
            "SELECT revision FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone()[0]

    server.style_evolution.migrate_pending_placements()
    server.style_evolution.migrate_pending_placements()
    with server.database._connect() as connection:
        assert connection.execute(
            "SELECT revision FROM style_voting_arenas WHERE evaluation_id=?",
            (project["evaluationIdentifier"],),
        ).fetchone()[0] == original_revision
        assert tuple(connection.execute(
            "SELECT * FROM style_evolution_batches WHERE plan_id=?",
            (archived_plan["planIdentifier"],),
        ).fetchone()) == archived_before
        migrated_batch = json.loads(connection.execute(
            "SELECT batch_json FROM style_evolution_batches WHERE plan_id=?",
            (plan["planIdentifier"],),
        ).fetchone()[0])
        assert migrated_batch["placement_policy"] == STYLELAB_SELECTION_POLICY
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    assert evolution_view(client, project)["batch"]["placementPolicy"] == STYLELAB_SELECTION_POLICY
    assert read_selection(client, project)["automaticPlacement"]["referenceCount"] == 3
