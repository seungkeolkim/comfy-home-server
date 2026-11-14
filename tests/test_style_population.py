"""큰 조합 Pool·원본 생성 규모·마지막 제출 수량의 프로젝트 격리를 검증합니다."""

import copy
import uuid

from home_server.style_generation_sizing import GENERATION_COUNT_POLICY_VERSION, generation_sizing_from_plans
from home_server.style_projects import encode_snapshot
from test_style_evolution import evolution_view, finish_evolution, submit_existing_plan, wait_for_plan
from test_style_generation import StyleComfyClient, prepare_style_generation
from test_style_prompt_changes import regeneration_payload, save_changed_prompts
from test_style_voting import read_selection, vote_input


def test_random_default_fifty_and_thousand_limit_without_gpu_submission(tmp_path) -> None:
    """기본 50개·최대 1000개가 중복 없는 계획으로 준비되고 확인 전에는 생성하지 않습니다."""

    fake = StyleComfyClient()
    _, client, project, _ = prepare_style_generation(tmp_path, fake)
    try:
        settings = copy.deepcopy(project["settings"])
        settings.update(artistMinimumCount=1, loraMinimumCount=1)
        project = client.put(f"/api/style-projects/{project['identifier']}", json={
            "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "settings": settings,
        }).json()
        endpoint = f"/api/style-projects/{project['identifier']}"
        payload = {"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex}
        response = client.post(endpoint + "/random-generation-plans", json=payload)
        assert response.status_code == 201, response.text
        assert len(response.json()["candidates"]) == 50
        assert response.json()["imageCount"] == 100
        assert client.post(endpoint + "/random-generation-plans", json=payload).json() == response.json()
        large_response = client.post(endpoint + "/random-generation-plans", json={
            **payload, "operationIdentifier": uuid.uuid4().hex, "combinationCount": 1000,
        })
        assert large_response.status_code == 201, large_response.text
        candidates = large_response.json()["candidates"]
        assert len(candidates) == 1000
        labels = [candidate["label"] for candidate in candidates]
        assert labels[25:28] == ["Z", "AA", "AB"]
        assert labels[51:54] == ["AZ", "BA", "BB"]
        assert len(set(labels)) == 1000
        assert all(label.isascii() and label.isalpha() for label in labels)
        sizing = client.get(endpoint + "/generation-results?summary=true").json()["generationSizing"]
        assert sizing["randomCombinationCount"] == 50
        assert not fake.submissions
        assert client.get("/api/jobs?include_style=true").json()["total"] == 0
    finally:
        client.__exit__(None, None, None)


def test_fifty_population_uses_fifteen_parents_and_retains_size_across_generation(tmp_path) -> None:
    """50개 Pool에서 부모 15개·자녀 12개를 사용하고 확정·Prompt 변경 후에도 50개를 유지합니다."""

    fake = StyleComfyClient()
    application, client, project, _ = prepare_style_generation(tmp_path, fake)
    try:
        endpoint = f"/api/style-projects/{project['identifier']}"
        response = client.post(endpoint + "/random-generation-plans", json={
            "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex,
        })
        assert response.status_code == 201, response.text
        initial_plan = response.json()
        submit_existing_plan(client, project, initial_plan)
        wait_for_plan(client, project, initial_plan)
        read_selection(client, project)
        server = application.state.home_server
        with server.database._connect() as connection:
            _, state = server.style_voting.load_arena(connection, project["identifier"], project["evaluationIdentifier"])
            for candidate_index, candidate in enumerate(initial_plan["candidates"]):
                state["statistics"][candidate["identifier"]].update(rating=10000 + candidate_index * 100, matches=3, wins=2, placed=True)
            state.update(match=None, placement=None)
            connection.execute("UPDATE style_voting_arenas SET state_json=?,revision=revision+1 WHERE evaluation_id=?", (encode_snapshot(state), project["evaluationIdentifier"]))
        view = evolution_view(client, project)
        assert view["candidateCount"] == 50 and len(view["parentCandidateIdentifiers"]) == 15
        assert view["canPrepare"]
        payload = {"operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"], "expectedVotingRevision": view["votingRevision"]}
        assert client.post(endpoint + "/evolution-plans", json={**payload, "childCount": 61}).status_code == 422
        maximum = client.post(endpoint + "/evolution-plans", json={**payload, "childCount": 60})
        assert maximum.status_code == 201, maximum.text
        assert len(maximum.json()["candidates"]) == 60
        finish_evolution(client, project, "cancel")
        view = evolution_view(client, project)
        response = client.post(endpoint + "/evolution-plans", json={
            **payload, "operationIdentifier": uuid.uuid4().hex, "expectedVotingRevision": view["votingRevision"],
        })
        assert response.status_code == 201, response.text
        plan = response.json()
        assert len(plan["candidates"]) == 12
        assert len(evolution_view(client, project)["batch"]["parentIdentifiers"]) == 15
        submit_existing_plan(client, project, plan)
        wait_for_plan(client, project, plan)
        child_identifiers = {candidate["identifier"] for candidate in plan["candidates"]}
        for comparison_index in range(200):
            selection = read_selection(client, project)
            if selection["match"] is None:
                break
            choice = "a" if selection["match"]["a"] in child_identifiers else "b"
            vote = client.post(endpoint + "/votes", json=vote_input(selection, choice))
            assert vote.status_code == 200, vote.text
        else:
            raise AssertionError("큰 Pool의 자녀 선별이 끝나지 않았습니다.")
        before_confirm_submissions = len(fake.submissions)
        result, _ = finish_evolution(client, project, "confirm")
        assert len(result["survivingIdentifiers"]) == 50
        assert len(result["nextParentIdentifiers"]) == 15
        assert len(fake.submissions) == before_confirm_submissions == 124
        results = server.style_generation.store.results(project["identifier"], summary=True)
        active_candidates = [candidate for candidate in results["candidates"] if candidate["lifecycle"] == "active"]
        assert len(active_candidates) == 50
        assert results["generationSizing"]["randomCombinationCount"] == 50
        assert results["generationSizing"]["evolutionChildCount"] == 12
        updated_project = save_changed_prompts(client, project)
        regeneration = client.post(endpoint + "/prompt-regeneration-plans", json=regeneration_payload(updated_project, active_candidates))
        assert regeneration.status_code == 201, regeneration.text
        assert len(regeneration.json()["candidates"]) == 50
        assert regeneration.json()["imageCount"] == 150
        assert len(fake.submissions) == before_confirm_submissions
    finally:
        client.__exit__(None, None, None)


def test_saved_counts_ignore_unsubmitted_and_legacy_plans() -> None:
    """새 제출 계획만 종류별로 복원하고 다른 프로젝트나 과거 기본값은 섞지 않습니다."""

    selection = {"mode": "random", "requestedCount": 80, "countPolicyVersion": GENERATION_COUNT_POLICY_VERSION}
    plans = [
        {"selection": {**selection, "requestedCount": 100}, "jobIdentifiers": []},
        {"selection": {"mode": "random", "requestedCount": 4}, "jobIdentifiers": ["legacy-job"]},
        {"selection": selection, "jobIdentifiers": ["random-job"]},
        {"selection": {**selection, "mode": "evolution", "requestedCount": 24}, "jobIdentifiers": ["evolution-job"]},
        {"selection": {**selection, "requestedCount": 70}, "jobIdentifiers": ["older-job"]},
    ]
    sizing = generation_sizing_from_plans(plans)
    assert sizing["randomCombinationCount"] == 80
    assert sizing["evolutionChildCount"] == 24
    fresh_project = generation_sizing_from_plans([])
    assert fresh_project["randomCombinationCount"] == 50
    assert fresh_project["evolutionChildCount"] == 12
