"""Random 추가와 진화 생성의 명시적 API 및 확정 단계의 경계를 검증합니다."""

import uuid

from test_style_evolution import evolution_view, finish_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_generation import StyleComfyClient, prepare_style_generation
from test_style_voting import read_selection, vote_input


def evolution_request(project: dict, evolution: dict, count: int) -> dict:
    """명시적으로 읽은 Project·Voting Revision에 진화 생성 요청을 고정합니다."""

    return {"operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"],
            "expectedVotingRevision": evolution["votingRevision"], "childCount": count}


def test_initial_candidate_request_replays_without_drawing_or_submitting_again(tmp_path) -> None:
    """확인 전 준비·응답 유실 재전송·오래된 설정의 거절을 실제 계획에서 검증합니다."""

    fake = StyleComfyClient()
    _, client, project, _ = prepare_style_generation(tmp_path, fake)
    try:
        endpoint = f"/api/style-projects/{project['identifier']}/random-generation-plans"
        initial = evolution_view(client, project)
        assert initial["candidateCount"] == 0 and initial["history"] == []
        payload = {"operationIdentifier": uuid.uuid4().hex, "expectedRevision": project["revision"], "combinationCount": 10}
        response = client.post(endpoint, json=payload)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["selection"]["mode"] == "random" and plan["generationNumber"] == 1
        assert plan["operationIdentifier"] == payload["operationIdentifier"]
        assert len(plan["candidates"]) == 10 and not fake.submissions
        assert client.post(endpoint, json=payload).json() == plan
        assert client.post(endpoint, json={**payload, "combinationCount": 11}).status_code == 409
        assert client.post(endpoint, json={**payload, "expectedRevision": 999}).status_code == 409
        submit_existing_plan(client, project, plan)
        wait_for_plan(client, project, plan)
        ready = evolution_view(client, project)
        assert ready["candidateCount"] == ready["readyCandidateCount"] == 10
        assert ready["evaluatedCount"] == 0 and not ready["canPrepare"]
        additional = client.post(endpoint, json={**payload, "operationIdentifier": uuid.uuid4().hex, "combinationCount": 2})
        assert additional.status_code == 201, additional.text
        assert additional.json()["selection"]["mode"] == "random"
        assert evolution_view(client, project)["batch"] is None
        assert len(fake.submissions) == 20
    finally:
        client.__exit__(None, None, None)


def test_explicit_evolution_advances_two_generations_with_frozen_parents_and_history(rated_population) -> None:
    """명시적 진화 API에서 확정된 세대·생존·다음 Batch가 분리됨을 검증합니다."""

    _, fake, client, project, initial_plan = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    initial = evolution_view(client, project)
    assert initial["candidateCount"] == 10 and initial["evaluatedCount"] == 10
    assert initial["parentCandidateIdentifiers"] == [candidate["identifier"] for candidate in reversed(initial_plan["candidates"][-3:])]
    created_batches = []
    for generation_number in [2, 3]:
        before = evolution_view(client, project)
        for _ in range(20):
            if before["canPrepare"]:
                break
            selection = read_selection(client, project)
            assert selection["match"]["kind"] == "tie"
            response = client.post(endpoint + "/votes", json=vote_input(selection, "similar"))
            assert response.status_code == 200, response.text
            before = evolution_view(client, project)
        assert before["canPrepare"]
        payload = evolution_request(project, before, 2)
        response = client.post(endpoint + "/evolution-plans", json=payload)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["selection"]["mode"] == "evolution" and plan["generationNumber"] == generation_number
        batch = evolution_view(client, project)["batch"]
        created_batches.append(batch["identifier"])
        assert batch["parentIdentifiers"] == before["parentCandidateIdentifiers"]
        assert batch["candidateIdentifiers"] == [candidate["identifier"] for candidate in plan["candidates"]]
        assert batch["completedCandidateIdentifiers"] == []
        assert batch["plan"]["operationIdentifier"] == payload["operationIdentifier"]
        assert client.post(endpoint + "/evolution-plans", json=payload).json() == plan
        assert client.post(endpoint + "/evolution-plans", json=evolution_request(project, evolution_view(client, project), 1)).status_code == 409
        submit_existing_plan(client, project, plan)
        wait_for_plan(client, project, plan)
        children = set(batch["candidateIdentifiers"])
        for _ in range(60):
            current = evolution_view(client, project)
            if current["batch"]["canConfirm"]:
                break
            selection = read_selection(client, project)
            choice = "a" if selection["match"]["a"] in children else "b"
            voted = client.post(endpoint + "/votes", json=vote_input(selection, choice))
            assert voted.status_code == 200, voted.text
        else:
            raise AssertionError("자녀 선별이 종료되지 않았습니다.")
        assert set(current["batch"]["completedCandidateIdentifiers"]) == children
        assert set(current["batch"]["enteredCandidateIdentifiers"]) == children
        confirmed, confirmation_payload = finish_evolution(client, project, "confirm")
        assert confirmed["generationNumber"] == generation_number
        current = evolution_view(client, project)
        assert current["currentGeneration"] == generation_number and current["batch"] is None
        history = current["history"][0]
        assert history["batchIdentifier"] == batch["identifier"]
        assert history["operationIdentifier"] == payload["operationIdentifier"]
        assert history["enteredCount"] == 2 and history["failedCount"] == 0
        assert set(history["enteredIdentifiers"]) == children
        assert client.post(endpoint + f"/evolution-batches/{batch['identifier']}/confirm", json=confirmation_payload).json() == confirmed
    assert created_batches[0] != created_batches[1]
    assert len(current["history"]) == 2
    assert len(fake.submissions) == 28


def test_cancelled_candidate_request_cannot_restart_a_cancelled_batch(rated_population) -> None:
    """취소된 Operation은 재제출하지 않으며 새로운 요청으로만 다음 후보를 준비합니다."""

    _, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}/evolution-plans"
    payload = evolution_request(project, evolution_view(client, project), 2)
    response = client.post(endpoint, json=payload)
    assert response.status_code == 201, response.text
    finish_evolution(client, project, "cancel")
    assert client.post(endpoint, json=payload).json()["evolutionStatus"] == "cancelled"
    rejected_submission = client.post(
        f"/api/style-projects/{project['identifier']}/generation-plans/{response.json()['planIdentifier']}/submit",
        json={"operationIdentifier": uuid.uuid4().hex},
    )
    assert rejected_submission.status_code == 409
    current = evolution_view(client, project)
    assert current["currentGeneration"] == 1 and current["history"][0]["status"] == "cancelled"
    assert current["history"][0]["enteredIdentifiers"] == []
    fresh = client.post(endpoint, json=evolution_request(project, current, 2))
    assert fresh.status_code == 201 and fresh.json()["planIdentifier"] != response.json()["planIdentifier"]


def test_random_addition_never_becomes_evolution_when_population_is_ready(rated_population) -> None:
    """평가가 끝난 Pool에서도 Random 추가는 부모·다음 세대를 만들지 않습니다."""

    _, fake, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    before = evolution_view(client, project)
    assert before["canPrepare"]
    submission_count = len(fake.submissions)
    response = client.post(endpoint + "/random-generation-plans", json={
        "operationIdentifier": uuid.uuid4().hex, "expectedRevision": project["revision"], "combinationCount": 2,
    })
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["selection"]["mode"] == "random"
    assert plan["generationNumber"] == before["currentGeneration"]
    assert len(fake.submissions) == submission_count
    assert evolution_view(client, project)["batch"] is None
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    after = evolution_view(client, project)
    assert after["currentGeneration"] == before["currentGeneration"]
    assert after["candidateCount"] == before["candidateCount"] + 2
    assert after["batch"] is None
    assert client.post(endpoint + "/candidate-generation-plans", json={}).status_code == 404
