"""생존 조합 폐기 후 기존 순위의 보관 조합으로 결원을 보충하는 동작을 검증합니다."""

import copy
import json

import pytest

import home_server.application as application_module
from home_server.style_projects import encode_snapshot
from home_server.style_voting_rules import initial_candidate_statistics
from test_style_evolution import finish_evolution, prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_management import management_payload
from test_style_voting import read_selection, statistics_by_identifier, vote_input


@pytest.fixture
def confirmed_population(rated_population):
    """실제 선별·세대 확정으로 생존 10개와 보관 3개가 있는 프로젝트를 만듭니다."""

    server, _, client, project, _ = rated_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    plan = prepare_evolution(client, project, 3)
    submit_existing_plan(client, project, plan)
    wait_for_plan(client, project, plan)
    child_identifiers = {candidate["identifier"] for candidate in plan["candidates"]}
    selection = read_selection(client, project)
    for _ in range(60):
        if selection["match"] is None:
            break
        choice = "a" if selection["match"]["a"] in child_identifiers else "b"
        response = client.post(endpoint + "/votes", json=vote_input(selection, choice))
        assert response.status_code == 200, response.text
        selection = response.json()
    else:
        raise AssertionError("Fixture 선별을 종료하지 못했습니다.")
    finish_evolution(client, project, "confirm")
    results = client.get(endpoint + "/generation-results").json()
    assert sum(candidate["lifecycle"] == "active" for candidate in results["candidates"]) == 10
    assert sum(candidate["lifecycle"] == "retired" for candidate in results["candidates"]) == 3
    return server, client, project, results


def retired_candidates_by_rating(results: dict) -> list[dict]:
    """Fixture의 서로 다른 Elo를 가진 보관 조합을 높은 순서로 반환합니다."""

    return sorted(
        [candidate for candidate in results["candidates"] if candidate["lifecycle"] == "retired"],
        key=lambda candidate: candidate["statistics"]["rating"], reverse=True,
    )


def test_active_deletion_promotes_next_rank_without_changing_scores_or_images(confirmed_population) -> None:
    """폐기 후 즉시 정원을 채우고 기존 Elo·승패·이미지와 재전송 응답을 보존합니다."""

    server, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    selection = read_selection(client, project)
    deleted_identifier = selection["rankings"][0]["identifier"]
    expected_candidate = retired_candidates_by_rating(results)[0]
    expected_identifier = expected_candidate["identifier"]
    with server.database._connect() as connection:
        original_statistics = json.loads(connection.execute(
            "SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],),
        ).fetchone()[0])["statistics"][expected_identifier]
    image_contents = {
        output_file["path"]: server.managed_path(output_file["path"]).read_bytes()
        for render in expected_candidate["renders"] for output_file in render["files"]
    }
    payload = management_payload(client, project, [deleted_identifier])
    response = client.post(endpoint + "/candidate-deletions", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["promotedCandidateIdentifiers"] == [expected_identifier]
    assert client.post(endpoint + "/candidate-deletions", json=payload).json() == response.json()
    server.style_candidate_deletion.recover_pending_deletions()
    selection = read_selection(client, project)
    statistics = statistics_by_identifier(selection)
    assert len(statistics) == 10 and deleted_identifier not in statistics
    assert statistics[expected_identifier]["rated"]
    for field, value in original_statistics.items():
        assert statistics[expected_identifier][field] == value
    for relative_path, contents in image_contents.items():
        assert server.managed_path(relative_path).read_bytes() == contents
    assert not selection["canUndo"]
    after = client.get(endpoint + "/generation-results").json()
    assert sum(candidate["lifecycle"] == "active" for candidate in after["candidates"]) == 10
    assert sum(candidate["lifecycle"] == "retired" for candidate in after["candidates"]) == 2
    next_plan = prepare_evolution(client, project, 1)
    assert next_plan["generationNumber"] == 3


def test_bulk_deletion_refills_only_active_slots_and_excludes_deleted_retired(confirmed_population) -> None:
    """함께 폐기한 보관 조합은 승격하지 않고 활성 결원 수만큼 다음 순위를 올립니다."""

    _, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    active_identifiers = [entry["identifier"] for entry in read_selection(client, project)["rankings"][:2]]
    retired = retired_candidates_by_rating(results)
    deleted_identifiers = active_identifiers + [retired[0]["identifier"]]
    response = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, deleted_identifiers))
    assert response.status_code == 200, response.text
    assert response.json()["promotedCandidateIdentifiers"] == [candidate["identifier"] for candidate in retired[1:]]
    selection = read_selection(client, project)
    assert len(selection["rankings"]) == 10
    assert not set(deleted_identifiers).intersection(entry["identifier"] for entry in selection["rankings"])


@pytest.mark.parametrize("invalid_reason", ["missing_file", "incomplete_prompt", "unrated", "cancelled"])
def test_unavailable_retired_candidate_is_skipped(confirmed_population, invalid_reason) -> None:
    """파일·Prompt·평가가 미완료이거나 취소된 조합 대신 다음 정상 순위를 승격합니다."""

    server, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    retired = retired_candidates_by_rating(results)
    invalid_candidate = retired[0]
    invalid_identifier = invalid_candidate["identifier"]
    if invalid_reason == "missing_file":
        server.managed_path(invalid_candidate["renders"][0]["files"][0]["path"]).unlink()
    else:
        with server.database._connect() as connection:
            if invalid_reason == "incomplete_prompt":
                connection.execute("UPDATE job_requests SET status='failed' WHERE request_id=?", (invalid_candidate["renders"][0]["requestIdentifier"],))
            elif invalid_reason == "cancelled":
                connection.execute("UPDATE style_candidate_memberships SET lifecycle='cancelled' WHERE candidate_id=?", (invalid_identifier,))
            else:
                row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()
                state = json.loads(row[0])
                state["statistics"][invalid_identifier] = initial_candidate_statistics()
                connection.execute("UPDATE style_voting_arenas SET state_json=? WHERE evaluation_id=?", (encode_snapshot(state), project["evaluationIdentifier"]))
    deleted_identifier = read_selection(client, project)["rankings"][0]["identifier"]
    response = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [deleted_identifier]))
    assert response.status_code == 200, response.text
    assert response.json()["promotedCandidateIdentifiers"] == [retired[1]["identifier"]]
    assert len(read_selection(client, project)["rankings"]) == 10


def test_population_shortage_uses_available_retired_without_generating_images(confirmed_population) -> None:
    """보관 조합이 부족하면 가능한 만큼만 보충하고 새 생성이나 삭제 조합 복원은 하지 않습니다."""

    _, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    deleted_identifiers = [entry["identifier"] for entry in read_selection(client, project)["rankings"][:5]]
    response = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, deleted_identifiers))
    assert response.status_code == 200, response.text
    assert response.json()["promotedCandidateIdentifiers"] == [candidate["identifier"] for candidate in retired_candidates_by_rating(results)]
    assert len(read_selection(client, project)["rankings"]) == 8
    assert len(client.get(endpoint + "/generation-results").json()["candidates"]) == 8


def test_promotion_database_failure_rolls_back_deletion_before_files(confirmed_population) -> None:
    """승격 Transaction이 실패하면 폐기 상태·점수·파일까지 삭제 전으로 유지합니다."""

    server, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    selection = read_selection(client, project)
    payload = management_payload(client, project, [selection["rankings"][0]["identifier"]])
    with server.database._connect() as connection:
        connection.execute("CREATE TRIGGER refuse_population_promotion BEFORE UPDATE OF lifecycle ON style_candidate_memberships WHEN OLD.lifecycle='retired' AND NEW.lifecycle='active' BEGIN SELECT RAISE(ABORT,'fixture promotion failure'); END")
    response = client.post(endpoint + "/candidate-deletions", json=payload)
    assert response.status_code == 409, response.text
    assert read_selection(client, project)["rankings"] == selection["rankings"]
    after = client.get(endpoint + "/generation-results").json()
    assert [candidate["lifecycle"] for candidate in after["candidates"]] == [candidate["lifecycle"] for candidate in results["candidates"]]
    for candidate in results["candidates"]:
        for render in candidate["renders"]:
            for output_file in render["files"]:
                assert server.managed_path(output_file["path"]).is_file()
    with server.database._connect() as connection:
        assert not connection.execute("SELECT 1 FROM style_voting_commands WHERE operation_id=?", (payload["operationIdentifier"],)).fetchone()


def test_partial_file_failure_does_not_promote_twice_on_recovery(confirmed_population, monkeypatch) -> None:
    """파일 정리 재시도와 시작 시 복구가 활성 수를 중복으로 늘리지 않습니다."""

    server, client, project, results = confirmed_population
    endpoint = f"/api/style-projects/{project['identifier']}"
    deleted_identifier = read_selection(client, project)["rankings"][0]["identifier"]
    expected_identifier = retired_candidates_by_rating(results)[0]["identifier"]
    payload = management_payload(client, project, [deleted_identifier])
    original_delete = application_module.delete_recorded_output

    def fail_output_deletion(selected_server, output_identifier):
        """승격 이후 첫 이미지 정리에서 복구 가능한 파일 오류를 발생시킵니다."""

        raise OSError("fixture output lock")

    monkeypatch.setattr(application_module, "delete_recorded_output", fail_output_deletion)
    response = client.post(endpoint + "/candidate-deletions", json=payload)
    assert response.status_code == 409, response.text
    assert len(read_selection(client, project)["rankings"]) == 10
    monkeypatch.setattr(application_module, "delete_recorded_output", original_delete)
    server.style_candidate_deletion.recover_pending_deletions()
    retried = client.post(endpoint + "/candidate-deletions", json=copy.deepcopy(payload))
    assert retried.status_code == 200, retried.text
    assert retried.json()["promotedCandidateIdentifiers"] == [expected_identifier]
    assert len(read_selection(client, project)["rankings"]) == 10
