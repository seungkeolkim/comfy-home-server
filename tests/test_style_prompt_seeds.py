"""Prompt별 Seed의 정확한 저장·확정·실제 Graph·과거 계획·Fork 격리를 검증합니다."""

import copy
import json
import random
import time
import uuid

import pytest

from home_server.style_projects import encode_snapshot
from test_style_evolution import prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_project_forks import create_fork, read_snapshot_document, snapshot_options
from test_style_voting import read_selection


def prompt_seed_payload(project: dict, seed) -> dict:
    """정수 정밀도를 유지한 Seed와 설정 Revision·멱등 명령을 묶습니다."""

    return {"seed": seed, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex}


def save_prompt_seed(client, project: dict, case_identifier: str, seed) -> dict:
    """Prompt Seed 전용 API에서 성공한 프로젝트만 반환합니다."""

    response = client.put(f"/api/style-projects/{project['identifier']}/prompt-cases/{case_identifier}/seed", json=prompt_seed_payload(project, seed))
    assert response.status_code == 200, response.text
    return response.json()


def test_prompt_seed_save_changes_only_one_case_and_captures_snapshot(tmp_path) -> None:
    """한 Prompt의 Seed만 저장하고 동시 초안에 해당하는 다른 조건을 바꾸지 않습니다."""

    application, client, source, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        server = application.state.home_server
        snapshot = snapshot_options(client, source)["snapshots"][0]
        payload = prompt_seed_payload(source, "18446744073709551615")
        endpoint = f"/api/style-projects/{source['identifier']}/prompt-cases/portrait/seed"
        response = client.put(endpoint, json=payload)
        assert response.status_code == 200, response.text
        updated = response.json()
        expected = copy.deepcopy(source["settings"])
        expected["promptCases"][0]["seed"] = "18446744073709551615"
        assert updated["settings"] == expected
        assert updated["revision"] == source["revision"] + 1
        assert updated["generation"] == 0
        assert updated["evaluationIdentifier"] != source["evaluationIdentifier"]
        assert client.put(endpoint, json=payload).json() == updated
        options = snapshot_options(client, updated)["snapshots"]
        assert len(options) == 1
        assert options[0]["identifier"] == snapshot["identifier"]
        assert options[0]["revision"] == snapshot["revision"] + 1
        assert read_snapshot_document(server, snapshot["identifier"])["settings"]["promptCases"][0]["seed"] == 18446744073709551615
        assert client.put(endpoint, json={**payload, "seed": 1}).status_code == 409
        assert client.put(endpoint, json=prompt_seed_payload(source, 2)).status_code == 409
        assert client.get(f"/api/style-projects/{source['identifier']}").json()["settings"] == expected
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("invalid_seed", [-1, 18446744073709551616, 1.5, "abc", "", None])
def test_invalid_prompt_seeds_are_rejected_without_settings_mutation(tmp_path, invalid_seed) -> None:
    """음수·범위 초과·소수·빈 값은 저장하지 않고 기존 설정을 유지합니다."""

    _, client, source, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        endpoint = f"/api/style-projects/{source['identifier']}"
        response = client.put(endpoint + "/prompt-cases/portrait/seed", json=prompt_seed_payload(source, invalid_seed))
        assert response.status_code == 422, response.text
        assert client.get(endpoint).json() == source
    finally:
        client.__exit__(None, None, None)


def test_prompt_seed_authentication_scope_and_snapshot_failure_are_atomic(tmp_path) -> None:
    """다른 소유·잘못된 필드·Snapshot 실패와 인증 누락을 안전하게 거부합니다."""

    application, client, source, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        endpoint = f"/api/style-projects/{source['identifier']}"
        payload = prompt_seed_payload(source, 0)
        assert client.put(endpoint + "/prompt-cases/missing/seed", json=payload).status_code == 404
        assert client.put("/api/style-projects/missing/prompt-cases/portrait/seed", json=payload).status_code == 404
        assert client.put(endpoint + "/prompt-cases/portrait/seed", json={**payload, "prompt": "unwanted edit"}).status_code == 422
        with application.state.home_server.database._connect() as connection:
            connection.execute("CREATE TRIGGER refuse_prompt_seed_snapshot BEFORE UPDATE ON style_project_generation_snapshots BEGIN SELECT RAISE(ABORT,'fixture seed snapshot failure'); END")
        assert client.put(endpoint + "/prompt-cases/portrait/seed", json=payload).status_code == 409
        assert client.get(endpoint).json() == source
        client.cookies.clear()
        assert client.put(endpoint + "/prompt-cases/portrait/seed", json=payload).status_code == 401
    finally:
        client.__exit__(None, None, None)


def test_each_prompt_seed_reaches_graph_metadata_results_and_fork(tmp_path) -> None:
    """Seed 0·64bit 최대값·기본값을 모든 조합에서 정확히 사용하고 Fork에도 보존합니다."""

    fake_client = StyleComfyClient()
    application, client, source, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        source = save_prompt_seed(client, source, "portrait", 0)
        source = save_prompt_seed(client, source, "garden", "18446744073709551615")
        settings = copy.deepcopy(source["settings"])
        settings["promptCases"].append({"identifier": "legacy-default", "name": "기본 Seed", "prompt": "landscape"})
        response = client.put(f"/api/style-projects/{source['identifier']}", json={
            "settings": settings, "expectedRevision": source["revision"], "operationIdentifier": uuid.uuid4().hex,
        })
        assert response.status_code == 200, response.text
        source = response.json()
        plan_input.update(expectedRevision=source["revision"], operationIdentifier=uuid.uuid4().hex)
        plan, _, results = submit_and_wait(client, source, plan_input)
        expected_seeds = {"portrait": 0, "garden": 18446744073709551615, "legacy-default": 123456}
        assert [prompt_case["seed"] for prompt_case in plan["cases"]] == [0, "18446744073709551615", 123456]
        assert len(fake_client.submissions) == 6
        for graph, metadata in fake_client.submissions:
            prepared = metadata["home_server_request"]
            expected_seed = expected_seeds[prepared["style_context"]["case_id"]]
            assert graph["24"]["inputs"]["seed"] == expected_seed
            assert prepared["settings"]["seed"] == expected_seed
            case_identifier = prepared["style_context"]["case_id"]
            expected_resolution_seed = random.Random(f"{expected_seed}:{case_identifier}").randrange(2**31)
            assert prepared["wildcard_seed"] == expected_resolution_seed
        for candidate in results["candidates"]:
            for render in candidate["renders"]:
                assert str(render["settings"]["seed"]) == str(expected_seeds[render["caseIdentifier"]])
        forked = create_fork(client, source)
        assert forked["settings"]["promptCases"] == source["settings"]["promptCases"]
        assert forked["generation"] == 0
        with application.state.home_server.database._connect() as connection:
            render_plans = [json.loads(row[0]) for row in connection.execute("SELECT render_plan_json FROM style_candidate_renders")]
        assert all(render_plan["sampling"]["seed"] == expected_seeds[render_plan["case"]["identifier"]] for render_plan in render_plans)
    finally:
        client.__exit__(None, None, None)


def test_changed_prompt_seed_preserves_old_images_and_retry_then_uses_new_seed(tmp_path) -> None:
    """확정 후에도 기존 실패 계획은 옛 Seed로 재시도하고 새 조건의 재생성에만 반영합니다."""

    fake_client = StyleComfyClient()
    fake_client.fail_first_submission = True
    application, client, source, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        plan, _, before = submit_and_wait(client, source, plan_input)
        old_contents = {file["path"]: application.state.home_server.managed_path(file["path"]).read_bytes()
                        for candidate in before["candidates"] for render in candidate["renders"] for file in render["files"]}
        updated = save_prompt_seed(client, source, "portrait", 888)
        endpoint = f"/api/style-projects/{source['identifier']}"
        assert client.get(endpoint + "/generation-results").json()["candidates"] == before["candidates"]
        for relative_path, contents in old_contents.items():
            assert application.state.home_server.managed_path(relative_path).read_bytes() == contents
        retry = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={
            "operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True,
        })
        assert retry.status_code == 200, retry.text
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            candidates = client.get(endpoint + "/generation-results").json()["candidates"]
            latest_portrait = [render for render in candidates[0]["renders"] if render["caseIdentifier"] == "portrait"][-1]
            if latest_portrait["status"] == "completed":
                break
            time.sleep(0.04)
        assert latest_portrait["status"] == "completed"
        assert fake_client.submissions[4][0]["24"]["inputs"]["seed"] == 123456
        response = client.post(endpoint + "/prompt-regeneration-plans", json={
            "candidateIdentifiers": [candidate["identifier"] for candidate in before["candidates"]],
            "expectedRevision": updated["revision"], "operationIdentifier": uuid.uuid4().hex,
        })
        assert response.status_code == 201, response.text
        new_plan = response.json()
        submit_existing_plan(client, updated, new_plan)
        wait_for_plan(client, updated, new_plan)
        assert [graph["24"]["inputs"]["seed"] for graph, _ in fake_client.submissions[5:]] == [888, 123456, 888, 123456]
    finally:
        client.__exit__(None, None, None)


def test_legacy_settings_save_and_legacy_parent_plans_keep_the_same_conditions(rated_population) -> None:
    """개별 Seed가 없던 설정·부모 계획을 읽어도 평가 조건과 진화가 불필요하게 바뀌지 않습니다."""

    server, _, client, source, parent_plan = rated_population
    settings = copy.deepcopy(source["settings"])
    for prompt_case in settings["promptCases"]:
        prompt_case.pop("seed", None)
    response = client.put(f"/api/style-projects/{source['identifier']}", json={
        "settings": settings, "expectedRevision": source["revision"], "operationIdentifier": uuid.uuid4().hex,
    })
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["evaluationIdentifier"] == source["evaluationIdentifier"]
    with server.database._connect() as connection:
        row = connection.execute("SELECT plan_json FROM style_generation_plans WHERE plan_id=?", (parent_plan["planIdentifier"],)).fetchone()
        document = json.loads(row[0])
        for prompt_case in document["cases"]:
            prompt_case.pop("seed", None)
        connection.execute("UPDATE style_generation_plans SET plan_json=? WHERE plan_id=?", (encode_snapshot(document), parent_plan["planIdentifier"]))
    plan = prepare_evolution(client, updated, 1)
    assert [prompt_case["seed"] for prompt_case in plan["cases"]] == [123456, 123456]
    submit_existing_plan(client, updated, plan)
    wait_for_plan(client, updated, plan)


def test_evolution_children_preserve_each_prompt_seed(tmp_path) -> None:
    """부모와 자녀의 모든 Prompt에서 같은 개별 Seed를 유지합니다."""

    fake_client = StyleComfyClient()
    application, client, source, _ = prepare_style_generation(tmp_path, fake_client)
    try:
        source = save_prompt_seed(client, source, "portrait", 0)
        source = save_prompt_seed(client, source, "garden", 987654321)
        response = client.post(f"/api/style-projects/{source['identifier']}/random-generation-plans", json={
            "expectedRevision": source["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 10,
        })
        assert response.status_code == 201, response.text
        initial_plan = response.json()
        submit_existing_plan(client, source, initial_plan)
        wait_for_plan(client, source, initial_plan)
        read_selection(client, source)
        with application.state.home_server.database._connect() as connection:
            row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (source["evaluationIdentifier"],)).fetchone()
            arena = json.loads(row[0])
            for index, candidate in enumerate(initial_plan["candidates"]):
                arena["statistics"][candidate["identifier"]].update(rating=10000 + index * 100, matches=3, wins=2, placed=True)
            arena.update(match=None, placement=None)
            connection.execute("UPDATE style_voting_arenas SET state_json=?,revision=revision+1 WHERE evaluation_id=?", (encode_snapshot(arena), source["evaluationIdentifier"]))
        plan = prepare_evolution(client, source, 1)
        assert [prompt_case["seed"] for prompt_case in plan["cases"]] == [0, 987654321]
        submit_existing_plan(client, source, plan)
        wait_for_plan(client, source, plan)
        assert [graph["24"]["inputs"]["seed"] for graph, _ in fake_client.submissions[-2:]] == [0, 987654321]
    finally:
        client.__exit__(None, None, None)
