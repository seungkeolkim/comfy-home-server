"""조합 이름·수동 Elo·전체 Prompt 폐기의 소유·동시성·파일 효과를 검증합니다."""

import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

import home_server.application as application_module
from test_style_evolution import finish_evolution, prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_voting import CLIENT_IDENTIFIER, read_selection, statistics_by_identifier, vote_input


def management_payload(client, project: dict, identifiers: list[str], rating: int | None = None) -> dict:
    """현재 평가 Revision·안정적인 조합 ID로 관리 요청을 만듭니다."""

    selection = read_selection(client, project)
    payload = {"evaluationIdentifier": project["evaluationIdentifier"], "clientIdentifier": CLIENT_IDENTIFIER, "expectedRevision": selection["revision"], "operationIdentifier": uuid.uuid4().hex, "candidateIdentifiers": identifiers}
    if rating is not None:
        payload["rating"] = rating
    return payload


def test_combination_names_follow_generation_file_rule_across_batches(tmp_path) -> None:
    """새 조합 번호는 같은 세대의 여러 생성 묶음 사이에서도 중복되지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        first_plan, _, first_results = submit_and_wait(client, project, plan_input)
        second_input = copy.deepcopy(plan_input)
        second_input["operationIdentifier"] = uuid.uuid4().hex
        second_input["combinations"] = second_input["combinations"][:1]
        second_input["combinations"][0]["components"][0]["strength"] = 0.6
        second_plan, _, results = submit_and_wait(client, project, second_input)
        assert [candidate["combinationNumber"] for candidate in first_plan["candidates"]] == [1, 2]
        assert second_plan["candidates"][0]["combinationNumber"] == 3
        assert [candidate["displayName"] for candidate in results["candidates"]] == ["세대001-조합01", "세대001-조합02", "세대001-조합03"]
        for candidate in results["candidates"]:
            for render in candidate["renders"]:
                assert render["files"][0]["path"].split("/")[-1].startswith(candidate["displayName"] + "-Prompt")
        assert first_results["candidates"][0]["displayName"] == "세대001-조합01"
    finally:
        client.__exit__(None, None, None)


def test_direct_rating_preserves_record_and_clears_old_undo(tmp_path) -> None:
    """Elo 0·다중 수정·재전송을 지원하고 이전 Undo가 직접 수정값을 덮지 않습니다."""

    _, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        voted = client.post(endpoint + "/votes", json=vote_input(read_selection(client, project))).json()
        previous = statistics_by_identifier(voted)
        identifiers = [candidate["identifier"] for candidate in plan["candidates"]]
        payload = management_payload(client, project, identifiers, 0)
        response = client.post(endpoint + "/candidate-ratings", json=payload)
        assert response.status_code == 200, response.text
        selection = response.json()
        assert not selection["canUndo"]
        for identifier, statistics in statistics_by_identifier(selection).items():
            assert statistics["rating"] == 0 and statistics["rated"]
            for field in ("matches", "wins", "losses", "skips"):
                assert statistics[field] == previous[identifier][field]
        assert selection["match"]["token"] != voted["match"]["token"]
        assert client.post(endpoint + "/candidate-ratings", json=payload).json() == selection
        assert client.post(endpoint + "/candidate-ratings", json={**payload, "rating": 9000}).status_code == 409
        for invalid in (-1, 1.5, "10000"):
            assert client.post(endpoint + "/candidate-ratings", json={**management_payload(client, project, identifiers), "rating": invalid}).status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_rating_concurrency_scope_and_unknown_target_are_atomic(tmp_path) -> None:
    """동시 Elo 변경은 하나만 반영하고 다른 평가·존재하지 않는 ID는 전체 거부합니다."""

    _, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        identifier = plan["candidates"][0]["identifier"]
        original = read_selection(client, project)
        invalid = management_payload(client, project, [identifier, "missing"], 15000)
        assert client.post(endpoint + "/candidate-ratings", json=invalid).status_code == 404
        assert read_selection(client, project)["rankings"] == original["rankings"]
        first = management_payload(client, project, [identifier], 15000)
        second = {**first, "operationIdentifier": uuid.uuid4().hex, "rating": 16000}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.post, endpoint + "/candidate-ratings", json=payload) for payload in (first, second)]
            responses = [future.result(timeout=5) for future in futures]
        assert sorted(response.status_code for response in responses) == [200, 409]
        duplicate = management_payload(client, project, [identifier, identifier], 10000)
        assert client.post(endpoint + "/candidate-ratings", json=duplicate).status_code == 422
        foreign = client.post("/api/style-projects", json={"settings": {**project["settings"], "name": "다른 프로젝트"}, "operationIdentifier": uuid.uuid4().hex}).json()
        foreign_payload = management_payload(client, foreign, [identifier], 10000)
        assert client.post(f"/api/style-projects/{foreign['identifier']}/candidate-ratings", json=foreign_payload).status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_deleting_combination_removes_all_cases_and_cached_files_only(tmp_path) -> None:
    """전체 Prompt 이미지만 지우고 다른 조합·작업 이력·생성 조건은 유지합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        endpoint = f"/api/style-projects/{project['identifier']}"
        target = results["candidates"][0]
        other = results["candidates"][1]
        files = [file for render in target["renders"] for file in render["files"]]
        for file in files:
            assert client.get("/api/outputs/preview/" + file["path"]).status_code == 200
        before_job = server.database.get_job(job["jobIdentifier"])
        payload = management_payload(client, project, [target["identifier"]])
        response = client.post(endpoint + "/candidate-deletions", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["deletedCandidateCount"] == 1 and response.json()["deletedOutputCount"] == 2
        assert client.post(endpoint + "/candidate-deletions", json=payload).json() == response.json()
        for file in files:
            assert not server.managed_path(file["path"]).exists()
            assert client.get("/media/" + file["path"]).status_code == 404
            assert client.get("/api/outputs/preview/" + file["path"]).status_code == 404
        for render in other["renders"]:
            assert server.managed_path(render["files"][0]["path"]).is_file()
        assert server.database.get_job(job["jobIdentifier"])["requests"] == before_job["requests"]
        server.output_catalog.synchronize(server.config.managed_output_directory, server.style_output_directory)
        after = client.get(endpoint + "/generation-results").json()
        assert [candidate["identifier"] for candidate in after["candidates"]] == [other["identifier"]]
        assert target["identifier"] not in {entry["identifier"] for entry in read_selection(client, project)["rankings"]}
        with server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM output_files WHERE is_deleted=1").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert client.post(endpoint + "/candidate-ratings", json=management_payload(client, project, [target["identifier"]], 10000)).status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_partial_file_failure_is_visible_and_recoverable_after_restart(tmp_path, monkeypatch) -> None:
    """일부 파일 삭제 실패는 숨겨진 조합을 되살리지 않고 영속 명령으로 이어갑니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        target = results["candidates"][0]
        endpoint = f"/api/style-projects/{project['identifier']}"
        payload = management_payload(client, project, [target["identifier"]])
        original_delete = application_module.delete_recorded_output
        call_count = 0

        def fail_second_image(selected_server, output_identifier):
            """첫 파일이 실제 삭제된 뒤 두 번째 파일만 잠긴 상황을 만듭니다."""

            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("fixture file lock")
            return original_delete(selected_server, output_identifier)

        monkeypatch.setattr(application_module, "delete_recorded_output", fail_second_image)
        response = client.post(endpoint + "/candidate-deletions", json=payload)
        assert response.status_code == 409
        partial = client.get(endpoint + "/generation-results").json()
        assert len(partial["pendingCandidateDeletions"]) == 1
        assert partial["pendingCandidateDeletions"][0]["operationIdentifier"] == payload["operationIdentifier"]
        assert target["identifier"] not in {candidate["identifier"] for candidate in partial["candidates"]}
        monkeypatch.setattr(application_module, "delete_recorded_output", original_delete)
        server.style_candidate_deletion.recover_pending_deletions()
        assert not client.get(endpoint + "/generation-results").json()["pendingCandidateDeletions"]
        assert client.post(endpoint + "/candidate-deletions", json=payload).json()["status"] == "deleted"
        assert all(not server.managed_path(file["path"]).exists() for render in target["renders"] for file in render["files"])
    finally:
        client.__exit__(None, None, None)


def test_protection_stale_revision_and_foreign_ids_prevent_every_file_delete(tmp_path) -> None:
    """검증 실패는 어떤 파일도 지우지 않고 전체 대상의 소유·보호를 먼저 확인합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, job, results = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        identifiers = [candidate["identifier"] for candidate in results["candidates"]]
        files = [file for candidate in results["candidates"] for render in candidate["renders"] for file in render["files"]]
        server = application.state.home_server
        invalid = management_payload(client, project, [identifiers[0], "foreign"])
        assert client.post(endpoint + "/candidate-deletions", json=invalid).status_code == 404
        stale = management_payload(client, project, identifiers)
        client.post(endpoint + "/votes", json=vote_input(read_selection(client, project)))
        assert client.post(endpoint + "/candidate-deletions", json=stale).status_code == 409
        server.database.set_job_deletion_protection(job["jobIdentifier"], True)
        protected = management_payload(client, project, identifiers)
        assert client.post(endpoint + "/candidate-deletions", json=protected).status_code == 409
        assert all(server.managed_path(file["path"]).is_file() for file in files)
        assert len(client.get(endpoint + "/generation-results").json()["candidates"]) == 2
    finally:
        client.__exit__(None, None, None)


def test_evolution_allows_explicit_elo_changes_but_protects_deletion(rated_population) -> None:
    """진화 중 직접 고친 부모 Elo는 자녀 배치에 반영하고 취소 뒤에도 보존합니다."""

    _, fake, client, project, source_plan = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    identifier = read_selection(client, project)["rankings"][0]["identifier"]
    plan = prepare_evolution(client, project, 1)
    assert client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [identifier])).status_code == 409
    fake.complete_submissions = False
    submit_existing_plan(client, project, plan)
    assert client.post(endpoint + "/candidate-ratings", json=management_payload(client, project, [identifier], 14000)).status_code == 200
    assert client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [identifier])).status_code == 409
    finish_evolution(client, project, "cancel")
    assert statistics_by_identifier(read_selection(client, project))[identifier]["rating"] == 14000
    assert client.post(endpoint + "/candidate-ratings", json=management_payload(client, project, [identifier], 14000)).status_code == 200


def test_manual_child_rating_survives_other_selection_votes(rated_population) -> None:
    """한 자녀의 직접 Elo 보정이 다른 자녀의 Vote·Skip에서 초기화되지 않습니다."""

    _, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    plan = prepare_evolution(client, project, 2)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    child_identifier = sorted(candidate["identifier"] for candidate in plan["candidates"])[-1]
    response = client.post(endpoint + "/candidate-ratings", json=management_payload(client, project, [child_identifier], 15000))
    assert response.status_code == 200, response.text
    selection = response.json()
    assert selection["match"]["a"] != child_identifier and selection["match"]["b"] != child_identifier
    voted = client.post(endpoint + "/votes", json=vote_input(selection)).json()
    assert statistics_by_identifier(voted)[child_identifier]["rating"] == 15000
    finish_evolution(client, project, "cancel")


def test_database_rejection_before_deletion_keeps_all_files(tmp_path) -> None:
    """삭제 의도 저장이 실패하면 선택한 파일과 기존 활성 상태를 모두 유지합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        identifiers = [candidate["identifier"] for candidate in results["candidates"]]
        files = [file for candidate in results["candidates"] for render in candidate["renders"] for file in render["files"]]
        payload = management_payload(client, project, identifiers)
        with server.database._connect() as connection:
            connection.execute("CREATE TRIGGER refuse_candidate_deletion BEFORE UPDATE OF lifecycle ON style_candidate_memberships WHEN NEW.lifecycle='deleting' BEGIN SELECT RAISE(ABORT,'fixture DB failure'); END")
        response = client.post(f"/api/style-projects/{project['identifier']}/candidate-deletions", json=payload)
        assert response.status_code == 409
        assert all(server.managed_path(file["path"]).is_file() for file in files)
        with server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM style_candidate_memberships WHERE lifecycle='active'").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM style_voting_commands WHERE action='delete'").fetchone()[0] == 0
    finally:
        client.__exit__(None, None, None)


def test_generation_job_numbers_restart_inside_each_generation(rated_population) -> None:
    """Job 메모의 회차는 세대마다 01부터, 조합 번호는 그 세대 안에서 이어집니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    plan = prepare_evolution(client, project, 1)
    first_job = submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    selection = read_selection(client, project)
    child_identifier = plan["candidates"][0]["identifier"]
    for _ in range(20):
        if selection["match"] is None:
            break
        choice = "b" if selection["match"]["a"] == child_identifier else "a"
        response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
        assert response.status_code == 200, response.text
        selection = response.json()
    assert selection["match"] is None
    finish_evolution(client, project, "confirm")
    second_plan = client.post(endpoint + "/random-generation-plans", json={"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 1}).json()
    second_job = submit_existing_plan(client, project, second_plan)
    wait_for_plan(client, project, second_plan)
    assert server.database.get_job(first_job["jobIdentifier"])["description"] == "세대002-01 이미지 생성"
    assert server.database.get_job(second_job["jobIdentifier"])["description"] == "세대002-02 이미지 생성"
    assert second_plan["candidates"][0]["displayName"] == "세대002-조합02"
