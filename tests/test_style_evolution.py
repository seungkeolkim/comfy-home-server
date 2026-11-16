"""고정 부모 Selection·세대 확정·취소·재시도·Checkpoint의 실제 효과를 검증합니다."""

import ast
import copy
import json
import math
import random
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest

from home_server.database import Database
from home_server.style_evolution_breeding import breed_component_kind, draw_evolution_children
from home_server.style_evolution_selection import STYLELAB_SELECTION_POLICY, build_selection_ranking, next_selection_pair
from home_server.style_projects import encode_snapshot, snapshot_hash
from test_style_generation import StyleComfyClient, prepare_style_generation
from test_style_voting import read_selection, statistics_by_identifier, undo_input, vote_input


def wait_for_plan(client, project: dict, plan: dict) -> dict:
    """실제 임시 PNG가 모든 Case에서 완료될 때까지 제한 시간 안에 기다립니다."""

    endpoint = f"/api/style-projects/{project['identifier']}"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        results = client.get(endpoint + "/generation-results").json()
        candidates = [candidate for candidate in results["candidates"] if candidate["planIdentifier"] == plan["planIdentifier"]]
        if candidates and all(len(candidate["renders"]) == len(plan["cases"]) and all(render["status"] == "completed" for render in candidate["renders"]) for candidate in candidates):
            return results
        time.sleep(0.04)
    raise AssertionError(candidates)


def submit_existing_plan(client, project: dict, plan: dict) -> dict:
    """준비된 일반·진화 계획을 동일한 Home 생성 경로에 제출합니다."""

    response = client.post(f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
    assert response.status_code == 200, response.text
    return response.json()


def evolution_view(client, project: dict) -> dict:
    """현재 평가 조건의 진화 준비·진행 상태를 조회합니다."""

    response = client.get(f"/api/style-projects/{project['identifier']}/evolution", params={"evaluationIdentifier": project["evaluationIdentifier"]})
    assert response.status_code == 200, response.text
    return response.json()


def prepare_evolution(client, project: dict, child_count: int = 3) -> dict:
    """현재 Project·Arena Revision에 고정한 다음 세대 계획을 만듭니다."""

    view = evolution_view(client, project)
    response = client.post(f"/api/style-projects/{project['identifier']}/evolution-plans", json={"operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"], "expectedVotingRevision": view["votingRevision"], "childCount": child_count})
    assert response.status_code == 201, response.text
    return response.json()


def finish_evolution(client, project: dict, action: str) -> tuple[dict, dict]:
    """최신 Revision으로 Batch를 확정·취소하고 재전송용 Payload도 반환합니다."""

    view = evolution_view(client, project)
    payload = {"operationIdentifier": uuid.uuid4().hex, "expectedVotingRevision": view["votingRevision"]}
    response = client.post(f"/api/style-projects/{project['identifier']}/evolution-batches/{view['batch']['identifier']}/{action}", json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload


@pytest.fixture
def rated_population(tmp_path):
    """실제 파일이 있는 10개 후보에 서로 다른 Fixture 점수를 넣어 세대 전환을 격리합니다."""

    fake = StyleComfyClient()
    application, client, project, _ = prepare_style_generation(tmp_path, fake)
    try:
        endpoint = f"/api/style-projects/{project['identifier']}"
        response = client.post(endpoint + "/random-generation-plans", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 10})
        assert response.status_code == 201, response.text
        plan = response.json()
        submit_existing_plan(client, project, plan)
        wait_for_plan(client, project, plan)
        read_selection(client, project)
        server = application.state.home_server
        with server.database._connect() as connection:
            row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()
            state = json.loads(row[0])
            for index, candidate in enumerate(plan["candidates"]):
                state["statistics"][candidate["identifier"]].update(rating=10000 + index * 100, matches=3, wins=2, placed=True)
            state.update(match=None, placement=None)
            connection.execute("UPDATE style_voting_arenas SET state_json=?,revision=revision+1 WHERE evaluation_id=?", (encode_snapshot(state), project["evaluationIdentifier"]))
        assert evolution_view(client, project)["canPrepare"]
        yield server, fake, client, project, plan
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("selection_policy", [None, STYLELAB_SELECTION_POLICY, "full-ladder-placement-v2"])
def test_selection_matches_original_golden_with_ties_and_conflicting_votes(selection_policy) -> None:
    """원본 함수와 다양한 경로의 점수·Slot·다음 대결·경계 처리를 비교합니다."""

    snapshot = Path(__file__).resolve().parents[1] / "docs/style-lab-rebuild/source_reference/style_lab/app__core.py.md"
    source = snapshot.read_text(encoding="utf-8").split("```python\n", 1)[1].rsplit("```", 1)[0]
    names = {"calc_elo", "_batch_votes", "selection_scores", "selection_votes", "_bisect", "_climb_rung", "_best_slots", "_next_rung", "_check_rung", "selection_ranking", "selection_next_pair"}
    module = ast.Module(body=[node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    legacy = {"math": math, "RATING_SCALE": 10, "ELO_K": 320, "START_ELO": 10000, "PLACE_GAP": 480, "SELECTION_EXTRA_VOTES": 4, "SELECTION_CUT_WINDOW": 3}
    exec(compile(module, str(snapshot), "exec"), legacy)
    for seed in range(30):
        selection = {"batch_id": "batch", "parent_ids": ["parent-low", "parent-mid", "parent-high"], "parent_scores": {"parent-low": 10000, "parent-mid": 10320, "parent-high": 10640}, "candidate_ids": ["child-a", "child-b", "child-c"], "history": []}
        if selection_policy:
            selection.update(placement_policy=selection_policy, reference_ids=["nonparent", *selection["parent_ids"]],
                reference_scores={"nonparent": 9000, **selection["parent_scores"]})
        ready = selection["parent_ids"] + selection["candidate_ids"]
        combinations = [{"id": identifier} for identifier in ready]
        choice_random = random.Random(seed)
        for _ in range(60):
            ranking = build_selection_ranking(selection)
            expected = legacy["selection_ranking"](selection, selection["history"])
            for field in ("ladder", "ascending", "scores", "counts", "boundary_pairs"):
                assert ranking[field] == expected[field]
            for identifier in selection["candidate_ids"]:
                for field in ("slot", "rung", "votes", "best", "bisecting", "tried"):
                    assert ranking["info"][identifier][field] == expected["info"][identifier][field]
            pair = next_selection_pair(selection, ready, ranking)
            expected_pair = legacy["selection_next_pair"](selection, combinations, selection["history"], expected)
            assert pair == tuple(candidate["id"] for candidate in expected_pair) if expected_pair else pair is None
            if not pair:
                break
            choice = choice_random.choice(["a", "b", "similar"])
            event = {"batch_id": "batch", "pair": dict(zip(("a", "b"), pair)), "type": "selection_skip" if choice == "similar" else "selection_vote"}
            if choice != "similar":
                event["winner_id"] = event["pair"][choice]
            selection["history"].insert(0, event)
        else:
            raise AssertionError("Selection이 유한 횟수 안에 종료되지 않았습니다.")


def test_breeding_exclusions_limits_clip_zero_and_duplicate_exhaustion() -> None:
    """세 Mode 모두 새 범위·제외·독립 CLIP 0을 지키며 중복 공간은 유한 종료합니다."""

    settings = {"artistMinimumCount": 0, "artistMaximumCount": 0, "loraMinimumCount": 1, "loraMaximumCount": 1,
                "componentPolicies": {"lora:allowed": {"enabled": True, "minimumStrength": 0.4, "maximumStrength": 0.4}, "lora:excluded": {"enabled": False, "minimumStrength": 0, "maximumStrength": 1}}}
    parent = {"identifier": "first", "components": [{"identifier": "lora:allowed", "strength": 0.8, "clip_strength": 0}, {"identifier": "lora:excluded", "strength": 0.7}]}
    other = {"identifier": "second", "components": []}
    for mode in ("mutate", "crossover", "random"):
        components = breed_component_kind(settings, parent, other, mode, "lora", random.Random(1), {}, {})
        assert len(components) == 1
        assert components[0]["identifier"] == "lora:allowed" and components[0]["strength"] == 0.4
        if mode != "random":
            assert components[0]["clip_strength"] == 0
    children, provenance = draw_evolution_children(settings, [parent, other], {}, [], 6, "seed")
    assert children and len(children) <= 2
    assert provenance["shortfallCount"] == 6 - len(children)
    assert provenance["attempts"] <= 180
    assert draw_evolution_children(settings, [parent, other], {}, [], 6, "seed") == (children, provenance)


def test_all_breeding_modes_quantize_legacy_parents_without_modifying_them() -> None:
    """기존 소수 STR의 부모도 자녀만 0.05 배수로 바꾸고 독립 CLIP과 원본은 보존합니다."""

    settings = {
        "artistMinimumCount": 1, "artistMaximumCount": 1, "loraMinimumCount": 1, "loraMaximumCount": 1,
        "componentPolicies": {
            "artist:legacy": {"enabled": True, "minimumStrength": 0.401, "maximumStrength": 0.799},
            "lora:legacy": {"enabled": True, "minimumStrength": -0.121, "maximumStrength": 0.373},
        },
    }
    parents = [
        {"identifier": "first", "components": [{"identifier": "artist:legacy", "strength": 0.63}, {"identifier": "lora:legacy", "strength": 0.37, "clip_strength": 0}]},
        {"identifier": "second", "components": [{"identifier": "artist:legacy", "strength": 0.57}, {"identifier": "lora:legacy", "strength": 0.13, "clip_strength": 0}]},
    ]
    original_parents = copy.deepcopy(parents)
    for mode in ("mutate", "crossover", "random"):
        for component_kind in ("artist", "lora"):
            for selection_seed in range(50):
                components = breed_component_kind(settings, parents[0], parents[1], mode, component_kind, random.Random(selection_seed), {}, {})
                assert len(components) == 1
                component = components[0]
                policy = settings["componentPolicies"][component["identifier"]]
                assert policy["minimumStrength"] <= component["strength"] <= policy["maximumStrength"]
                assert Decimal(str(component["strength"])) % Decimal("0.05") == 0
                if component_kind == "lora" and mode != "random":
                    assert component["clip_strength"] == 0
    assert parents == original_parents


def test_one_generation_freezes_parents_supports_undo_and_confirms_checkpoint(rated_population) -> None:
    """실제 PNG·CHS Job·Selection·Undo·생존·퇴역·2세대 경로를 한 Cycle로 검증합니다."""

    server, fake, client, project, initial_plan = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    source = statistics_by_identifier(read_selection(client, project))
    wildcard_count = len(fake.wildcard_prompts)
    plan = prepare_evolution(client, project)
    assert plan["generationNumber"] == 2 and plan["cases"] == initial_plan["cases"]
    assert plan["selection"]["strengthStep"] == 0.05
    assert all(Decimal(str(component["strength"])) % Decimal("0.05") == 0 for candidate in plan["candidates"] for component in candidate["components"])
    assert len(fake.wildcard_prompts) == wildcard_count
    assert len(fake.submissions) == 20
    batch = evolution_view(client, project)["batch"]
    assert batch["status"] == "planned" and not batch["canConfirm"]
    job = submit_existing_plan(client, project, plan)
    results = wait_for_plan(client, project, plan)
    child_identifiers = {candidate["identifier"] for candidate in plan["candidates"]}
    assert all(candidate["lifecycle"] == "evolving" for candidate in results["candidates"] if candidate["identifier"] in child_identifiers)
    selection = read_selection(client, project)
    assert selection["match"]["kind"] == "select" and not selection["canUndo"]
    premature = client.post(endpoint + f"/evolution-batches/{batch['identifier']}/confirm", json={"operationIdentifier": uuid.uuid4().hex, "expectedVotingRevision": selection["revision"]})
    assert premature.status_code == 422
    response = client.post(endpoint + "/votes", json=vote_input(selection))
    assert response.status_code == 200, response.text
    voted = response.json()
    undo = client.post(endpoint + "/undo", json=undo_input(voted))
    assert undo.status_code == 200, undo.text
    assert undo.json()["rankings"] == selection["rankings"]
    selection = undo.json()
    for _ in range(60):
        if selection["match"] is None:
            break
        assert selection["match"]["kind"] == "select"
        choice = "a" if selection["match"]["a"] in child_identifiers else "b"
        response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
        assert response.status_code == 200, response.text
        selection = response.json()
        current = statistics_by_identifier(selection)
        for identifier in source:
            for field in ("rating", "matches", "wins", "losses", "skips"):
                assert current[identifier][field] == source[identifier][field]
    else:
        raise AssertionError("Selection이 종료되지 않았습니다.")
    assert evolution_view(client, project)["batch"]["canConfirm"]
    result, payload = finish_evolution(client, project, "confirm")
    assert result["enteredCount"] == 3 and len(result["survivingIdentifiers"]) == 10
    assert result["retiredExistingCount"] == 3
    assert client.post(endpoint + f"/evolution-batches/{batch['identifier']}/confirm", json=payload).json() == result
    assert not read_selection(client, project)["canUndo"]
    results = client.get(endpoint + "/generation-results").json()
    assert results["currentGeneration"] == 2
    assert sum(candidate["lifecycle"] == "active" for candidate in results["candidates"]) == 10
    assert sum(candidate["lifecycle"] == "retired" for candidate in results["candidates"]) == 3
    assert len([file for candidate in results["candidates"] for render in candidate["renders"] for file in render["files"]]) == 26
    assert all("세대002-" in render["files"][0]["path"] for candidate in results["candidates"] if candidate["identifier"] in child_identifiers for render in candidate["renders"])
    assert server.database.get_job(job["jobIdentifier"])["description"].startswith("세대002-")
    with server.database._connect() as connection:
        checkpoints = connection.execute("SELECT * FROM style_generation_checkpoints ORDER BY generation_number").fetchall()
        assert [row["generation_number"] for row in checkpoints] == [1, 2]
        for row in checkpoints:
            snapshot = json.loads(row["snapshot_json"])
            assert snapshot_hash(snapshot) == row["snapshot_hash"]
            assert len(snapshot["assets"]) == (20 if row["generation_number"] == 1 else 26)
            assert all(len(asset["sha256"]) == 64 for asset in snapshot["assets"])
        assert len(json.loads(checkpoints[0]["snapshot_json"])["candidates"]) == 10
    fresh = client.post(endpoint + "/random-generation-plans", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 1})
    assert fresh.status_code == 201 and fresh.json()["generationNumber"] == 2
    assert next(item for item in client.get("/api/style-projects").json()["projects"] if item["identifier"] == project["identifier"])["generation"] == 2
    prepare_evolution(client, project, 1)
    cancelled, _ = finish_evolution(client, project, "cancel")
    assert cancelled["generationNumber"] == 2 and cancelled["selectionHistory"] == []
    settings = {**project["settings"], "purpose": "2세대 표시 확인"}
    saved = client.put(endpoint, json={"settings": settings, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex})
    assert saved.status_code == 200 and saved.json()["generation"] == 2


def test_cancel_restores_parent_state_and_keeps_child_images(rated_population) -> None:
    """자녀 Vote 뒤 취소해도 부모 점수·세대가 복구되고 파일·작업·취소 기록은 남습니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    before = read_selection(client, project)
    plan = prepare_evolution(client, project, 2)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    selection = read_selection(client, project)
    assert client.post(endpoint + "/votes", json=vote_input(selection, "similar")).status_code == 200
    result, _ = finish_evolution(client, project, "cancel")
    assert result["generationNumber"] == 1 and len(result["selectionHistory"]) == 1
    restored = read_selection(client, project)
    assert restored["rankings"] == before["rankings"]
    assert [restored["match"][key] for key in ("a", "b")] == [before["match"][key] for key in ("a", "b")]
    assert restored["match"]["token"] != before["match"]["token"]
    results = client.get(endpoint + "/generation-results").json()
    children = [candidate for candidate in results["candidates"] if candidate["planIdentifier"] == plan["planIdentifier"]]
    assert all(candidate["lifecycle"] == "cancelled" for candidate in children)
    assert all(server.managed_path(render["files"][0]["path"]).is_file() for child in children for render in child["renders"])
    retry = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True})
    assert retry.status_code == 409
    assert evolution_view(client, project)["canPrepare"]


def test_planned_batch_stale_votes_and_settings_are_rejected(rated_population) -> None:
    """부모가 바뀐 계획·동시 일반 생성·설정 변경을 막고 계획 취소 뒤 정상화합니다."""

    _, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    plan = prepare_evolution(client, project)
    setting_response = client.put(endpoint, json={"settings": project["settings"], "operationIdentifier": uuid.uuid4().hex, "expectedRevision": project["revision"]})
    assert setting_response.status_code == 409
    normal = client.post(endpoint + "/random-generation-plans", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 1})
    assert normal.status_code == 409
    selection = read_selection(client, project)
    assert client.post(endpoint + "/votes", json=vote_input(selection)).status_code == 200
    response = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
    assert response.status_code == 409
    finish_evolution(client, project, "cancel")
    assert evolution_view(client, project)["batch"] is None


def test_schema_seventeen_migration_keeps_verified_backup(tmp_path) -> None:
    """17→18은 원본 Backup을 남기고 기존 Preset·선별 테이블을 보존합니다."""

    path = tmp_path / "migration.sqlite3"
    database = Database(path)
    database.save_preset("kept", "보존", "anima", {"prompt": "keep"})
    with sqlite3.connect(path) as connection:
        for table in ("style_evolution_commands", "style_generation_checkpoints", "style_candidate_memberships", "style_evolution_batches", "style_evolution_timelines"):
            connection.execute("DROP TABLE " + table)
        connection.execute("PRAGMA user_version=17")
    migrated = Database(path)
    assert migrated.list_presets()[0]["preset_id"] == "kept"
    backups = list((tmp_path / "backups").glob("migration_before_style_evolution_*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_insufficient_evaluation_never_creates_children_or_jobs(tmp_path) -> None:
    """최소 10개 조건을 API에서도 지키며 준비 전 오류는 후보·Job을 만들지 않습니다."""

    server_application, client, project, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        endpoint = f"/api/style-projects/{project['identifier']}"
        view = evolution_view(client, project)
        assert not view["canPrepare"] and view["evaluatedCount"] == 0
        response = client.post(endpoint + "/evolution-plans", json={"operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"], "expectedVotingRevision": view["votingRevision"], "childCount": 3})
        assert response.status_code == 422 and "10개" in response.text
        with server_application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM style_candidates").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    finally:
        client.__exit__(None, None, None)


def test_concurrent_preparations_idempotency_and_cancelling_pending_children(rated_population) -> None:
    """동시 계획은 하나만 허용하며 생성 중 취소는 자녀 요청에만 전달합니다."""

    server, fake, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    view = evolution_view(client, project)
    payloads = [{"operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"], "expectedVotingRevision": view["votingRevision"], "childCount": 2} for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, endpoint + "/evolution-plans", json=payload) for payload in payloads]
        responses = [future.result(timeout=8) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    accepted_index = next(index for index, response in enumerate(responses) if response.status_code == 201)
    plan = responses[accepted_index].json()
    replay = client.post(endpoint + "/evolution-plans", json=payloads[accepted_index])
    assert replay.status_code == 201 and replay.json() == plan
    conflicting = {**payloads[accepted_index], "childCount": 3}
    assert client.post(endpoint + "/evolution-plans", json=conflicting).status_code == 409
    fake.complete_submissions = False
    job = submit_existing_plan(client, project, plan)
    assert not evolution_view(client, project)["batch"]["canConfirm"]
    result, payload = finish_evolution(client, project, "cancel")
    assert result["jobIdentifiers"] == [job["jobIdentifier"]]
    with server.database._connect() as connection:
        assert connection.execute("SELECT cancellation_requested FROM jobs WHERE job_id=?", (job["jobIdentifier"],)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM jobs WHERE cancellation_requested=1").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM style_candidate_memberships WHERE lifecycle='cancelled'").fetchone()[0] == 2
    assert client.post(endpoint + f"/evolution-batches/{plan['selection']['batchIdentifier']}/cancel", json=payload).json() == result
    assert read_selection(client, project)["activeEvolutionIdentifier"] is None


def test_losing_children_retire_without_replacing_parents_or_reusing_old_plans(rated_population) -> None:
    """자녀가 최하위 부모에게 모두 지면 부모를 유지하고 이전 세대 계획은 제출하지 않습니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    pending = client.post(endpoint + "/random-generation-plans", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 1}).json()
    plan = prepare_evolution(client, project, 2)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    children = {candidate["identifier"] for candidate in plan["candidates"]}
    selection = read_selection(client, project)
    for _ in range(10):
        if not selection["match"]:
            break
        choice = "b" if selection["match"]["a"] in children else "a"
        response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
        assert response.status_code == 200, response.text
        selection = response.json()
    assert not selection["match"]
    # 새 Database 객체로 다시 읽어도 Batch·Selection과 확정 조건을 복구합니다.
    server.database = Database(server.database.database_path)
    assert evolution_view(client, project)["batch"]["canConfirm"]
    result, _ = finish_evolution(client, project, "confirm")
    assert result["enteredCount"] == result["retiredExistingCount"] == 0
    assert result["failedCount"] == 2 and len(result["survivingIdentifiers"]) == 10
    response = client.post(endpoint + f"/generation-plans/{pending['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
    assert response.status_code == 409
    assert client.get("/api/jobs?include_style=true").json()["total"] == 2
