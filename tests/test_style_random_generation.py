"""초기 추첨의 범위·중복·Preview 경계와 여러 Prompt 제출을 검증합니다."""

import copy
import random
import time
import uuid

import pytest

from home_server.style_projects import ProjectSettings
from home_server.style_random_generation import combination_selection_fingerprint, draw_initial_combinations, random_component_strength
from test_style_generation import StyleComfyClient, prepare_style_generation


def random_plan_input(project: dict, combination_count: int = 4) -> dict:
    """한 Preview 요청은 재전송해도 같은 Operation ID를 유지합니다."""

    return {"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": combination_count}


def test_draw_respects_counts_ranges_enabled_components_and_reproducibility() -> None:
    """0을 포함한 개수 범위·음수 STR·고정 범위를 지키며 순서에 영향받지 않습니다."""

    settings = ProjectSettings(
        name="추첨", promptCases=[{"identifier": "portrait", "name": "인물", "prompt": "portrait"}],
        artistMinimumCount=1, artistMaximumCount=2, loraMinimumCount=1, loraMaximumCount=2,
        componentPolicies={
            "artist:first": {"enabled": True, "minimumStrength": -0.123, "maximumStrength": -0.002},
            "artist:second": {"enabled": True, "minimumStrength": 0.4, "maximumStrength": 0.4},
            "lora:first": {"enabled": True, "minimumStrength": 0.2001, "maximumStrength": 0.2002},
            "lora:second": {"enabled": True, "minimumStrength": 0, "maximumStrength": 1},
            "lora:disabled": {"enabled": False, "minimumStrength": 1, "maximumStrength": 1},
        },
    ).model_dump()
    combinations, provenance = draw_initial_combinations(settings, 32, "selection-seed", set())
    assert len(combinations) == 32
    assert len({combination_selection_fingerprint(components) for components in combinations}) == 32
    assert draw_initial_combinations(settings, 32, "selection-seed", set()) == (combinations, provenance)
    changed_order = copy.deepcopy(settings)
    changed_order["componentPolicies"] = dict(reversed(list(settings["componentPolicies"].items())))
    assert draw_initial_combinations(changed_order, 32, "selection-seed", set())[0] == combinations
    for components in combinations:
        for kind in ("artist", "lora"):
            assert 1 <= sum(component["identifier"].startswith(kind + ":") for component in components) <= 2
        for component in components:
            policy = settings["componentPolicies"][component["identifier"]]
            assert policy["enabled"]
            assert policy["minimumStrength"] <= component["strength"] <= policy["maximumStrength"]
    assert provenance["shortfallCount"] == 0


def test_strength_grid_preserves_non_aligned_endpoints() -> None:
    """좁은 범위와 0.01 배수가 아닌 경계도 범위 밖으로 반올림하지 않습니다."""

    policy = {"minimumStrength": 0.2001, "maximumStrength": 0.2002}
    strengths = {random_component_strength(policy, random.Random(index)) for index in range(100)}
    assert strengths == {0.2001, 0.2002}
    assert random_component_strength({"minimumStrength": -0.4, "maximumStrength": -0.4}, random.Random(0)) == -0.4


def test_fingerprint_ignores_order_metadata_and_implicit_clip_but_preserves_zero_clip() -> None:
    """동일한 LoRA 강도를 Metadata 차이로 중복 우회하지 못하게 합니다."""

    components = [{"identifier": "artist:one", "strength": 1}, {"identifier": "lora:one", "strength": 0.4}]
    equivalent = [{"identifier": "lora:one", "strength": 0.4, "clip_strength": 0.4, "file_identity": {"sha256": "changed"}}, components[0]]
    assert combination_selection_fingerprint(components) == combination_selection_fingerprint(equivalent)
    equivalent[0]["clip_strength"] = 0
    assert combination_selection_fingerprint(components) != combination_selection_fingerprint(equivalent)


def test_random_preview_is_idempotent_and_submits_frozen_four_by_three_then_retries(tmp_path) -> None:
    """Preview는 작업을 만들지 않고 12개 Render와 실패 재시도는 원본 조합을 사용합니다."""

    fake_client = StyleComfyClient()
    fake_client.fail_first_submission = True
    application, client, project, _ = prepare_style_generation(tmp_path, fake_client)
    try:
        settings = copy.deepcopy(project["settings"])
        settings["promptCases"].append({"identifier": "street", "name": "거리", "prompt": "street, {artist}"})
        settings["artistMinimumCount"] = 1
        settings["loraMinimumCount"] = 1
        project_response = client.put(f"/api/style-projects/{project['identifier']}", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "settings": settings})
        assert project_response.status_code == 200, project_response.text
        project = project_response.json()
        endpoint = f"/api/style-projects/{project['identifier']}/random-generation-plans"
        payload = random_plan_input(project)
        response = client.post(endpoint, json=payload)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["imageCount"] == 12
        assert plan["sampling"]["seed"] == 123456
        assert plan["selection"]["mode"] == "random"
        assert plan["selection"]["selectionSeed"] != str(plan["sampling"]["seed"])
        assert not fake_client.submissions
        assert client.get("/api/jobs?include_style=true").json()["total"] == 0
        assert client.post(endpoint, json=payload).json() == plan
        assert client.post(endpoint, json={**payload, "combinationCount": 5}).status_code == 409
        next_plan = client.post(endpoint, json=random_plan_input(project)).json()
        fingerprints = {combination_selection_fingerprint(candidate["components"]) for candidate in plan["candidates"]}
        assert not fingerprints.intersection(combination_selection_fingerprint(candidate["components"]) for candidate in next_plan["candidates"])
        submission_endpoint = f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit"
        submission = client.post(submission_endpoint, json={"operationIdentifier": uuid.uuid4().hex})
        assert submission.status_code == 200, submission.text
        results = wait_for_random_plan(client, project, plan)
        renders = [render for candidate in results for render in candidate["renders"]]
        assert len(renders) == 12
        assert sum(render["status"] == "failed" for render in renders) == 1
        original_components = {candidate["identifier"]: candidate["components"] for candidate in plan["candidates"]}
        for graph, metadata in fake_client.submissions:
            context = metadata["home_server_request"]["style_context"]
            components = original_components[context["candidate_id"]]
            lora = next(component for component in components if component["identifier"].startswith("lora:"))
            assert graph["5"]["inputs"]["loras"]["__value__"][0]["strength"] == lora["strength"]
            assert graph["24"]["inputs"]["seed"] == 123456
        retry_response = client.post(submission_endpoint, json={"operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True})
        assert retry_response.status_code == 200, retry_response.text
        retried_results = wait_for_random_plan(client, project, plan)
        assert len(fake_client.submissions) == 13
        assert fake_client.submissions[0][0]["5"] == fake_client.submissions[-1][0]["5"]
        assert all(candidate["components"] == original_components[candidate["identifier"]] for candidate in retried_results)
        assert client.post(endpoint, json=payload).json()["candidates"] == plan["candidates"]
    finally:
        client.__exit__(None, None, None)


def wait_for_random_plan(client, project: dict, plan: dict) -> list[dict]:
    """대상 계획의 모든 Render가 종료 상태가 될 때까지 기다립니다."""

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        candidates = [candidate for candidate in results["candidates"] if candidate["planIdentifier"] == plan["planIdentifier"]]
        latest_renders = [next(render for render in reversed(candidate["renders"]) if render["caseIdentifier"] == prompt_case["identifier"]) for candidate in candidates for prompt_case in plan["cases"]]
        if latest_renders and all(render["status"] in {"completed", "failed", "cancelled", "stopped"} for render in latest_renders):
            return candidates
        time.sleep(0.05)
    raise AssertionError("Random 생성이 제한 시간 안에 끝나지 않았습니다.")


def test_base_model_only_shortage_and_exhaustion_are_bounded_without_jobs(tmp_path) -> None:
    """가능한 조합이 하나면 부족분을 표시하고 모두 사용한 경우 작업 없이 거절합니다."""

    fake_client = StyleComfyClient()
    application, client, project, _ = prepare_style_generation(tmp_path, fake_client)
    try:
        settings = copy.deepcopy(project["settings"])
        settings.update(artistMaximumCount=0, loraMaximumCount=0)
        response = client.put(f"/api/style-projects/{project['identifier']}", json={"settings": settings, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        project = response.json()
        endpoint = f"/api/style-projects/{project['identifier']}/random-generation-plans"
        response = client.post(endpoint, json=random_plan_input(project))
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["selection"]["actualCount"] == 1
        assert plan["selection"]["shortfallCount"] == 3
        assert plan["selection"]["attempts"] == 120
        assert plan["candidates"][0]["components"] == []
        assert plan["imageCount"] == 2
        response = client.post(endpoint, json=random_plan_input(project))
        assert response.status_code == 422, response.text
        assert "새 조합" in response.json()["detail"]
        assert not fake_client.submissions
        assert client.get("/api/jobs?include_style=true").json()["total"] == 0
    finally:
        client.__exit__(None, None, None)


def test_concurrent_preview_duplicate_is_rejected_before_commit(tmp_path, monkeypatch) -> None:
    """사전 검사 중 다른 계획이 같은 조합을 저장하면 두 번째 계획을 남기지 않습니다."""

    application, client, project, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        settings = copy.deepcopy(project["settings"])
        settings.update(artistMaximumCount=0, loraMaximumCount=0)
        response = client.put(f"/api/style-projects/{project['identifier']}", json={"settings": settings, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        project = response.json()
        generation_service = application.state.home_server.style_generation
        original_preflight = generation_service.preflight
        competing_plan = None

        async def preflight_with_competing_plan(workflow, components):
            """첫 계획의 비동기 사전 검사 사이에 경쟁 계획을 확정합니다."""

            nonlocal competing_plan
            monkeypatch.setattr(generation_service, "preflight", original_preflight)
            from home_server.style_random_generation import RandomStyleGenerationPlanInput

            competing_plan = await generation_service.create_plan(project["identifier"], RandomStyleGenerationPlanInput(**random_plan_input(project, 1)))
            await original_preflight(workflow, components)

        monkeypatch.setattr(generation_service, "preflight", preflight_with_competing_plan)
        response = client.post(f"/api/style-projects/{project['identifier']}/random-generation-plans", json=random_plan_input(project, 1))
        assert response.status_code == 409, response.text
        plans = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()["plans"]
        assert [plan["planIdentifier"] for plan in plans] == [competing_plan["planIdentifier"]]
        assert client.get("/api/jobs?include_style=true").json()["total"] == 0
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("combination_count", [0, 33, 1.5])
def test_random_batch_validation_does_not_create_plan(tmp_path, combination_count) -> None:
    """허용 범위 밖의 Batch 크기는 추첨·저장 전에 거절합니다."""

    application, client, project, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        response = client.post(f"/api/style-projects/{project['identifier']}/random-generation-plans", json=random_plan_input(project, combination_count))
        assert response.status_code == 422
        assert client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()["plans"] == []
    finally:
        client.__exit__(None, None, None)
