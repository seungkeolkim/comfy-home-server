"""스타일 목록의 일괄 조회와 비교 대상 파일 검증 범위를 확인합니다."""

import copy
import uuid
from unittest.mock import patch

from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_evolution import rated_population, evolution_view
from test_style_voting import read_selection, vote_input


def test_summary_preserves_cards_without_reading_request_graphs(tmp_path) -> None:
    """Summary와 상세의 카드·순위는 같으며 조회 수가 Render 수에 비례하지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        store = application.state.home_server.style_generation.store
        connection_factory = store.connection_factory
        statements = []

        def traced_connection():
            """해당 목록 요청의 SQL만 수집하며 운영 연결 방식은 유지합니다."""

            connection = connection_factory()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(store, "connection_factory", traced_connection):
            summary = store.results(project["identifier"], summary=True)
        assert len(statements) <= 12
        assert not any("request_results" in statement for statement in statements)
        detailed = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        reduced = copy.deepcopy(detailed)
        for candidate in reduced["candidates"]:
            for render in candidate["renders"]:
                for field_name in ("prompt", "negative", "settings", "loras"):
                    render.pop(field_name)
        assert summary == reduced
        endpoint_summary = client.get(f"/api/style-projects/{project['identifier']}/generation-results?summary=true")
        assert endpoint_summary.status_code == 200
        assert endpoint_summary.json() == summary
        assert detailed["candidates"][0]["renders"][0]["settings"]["seed"] == 123456
        assert detailed["candidates"][0]["renders"][0]["prompt"]
    finally:
        client.__exit__(None, None, None)


def test_selection_checks_pair_files_and_rejects_missing_second_prompt(tmp_path) -> None:
    """8개 조합의 전체 파일 대신 Pair만 검사하고 두 번째 Prompt 유실도 투표 전에 거절합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        template = plan_input["combinations"][0]
        for batch_index in range(4):
            plan_input["combinations"] = []
            plan_input["operationIdentifier"] = uuid.uuid4().hex
            for combination_index in range(2):
                combination = copy.deepcopy(template)
                combination["components"][0]["strength"] = 0.2 + (batch_index * 2 + combination_index) * 0.08
                plan_input["combinations"].append(combination)
            _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        with patch.object(server, "managed_path", wraps=server.managed_path) as managed_path:
            selection = read_selection(client, project)
            assert managed_path.call_count == 4
            assert len(selection["readyCandidateIdentifiers"]) == 8
            managed_path.reset_mock()
            evolution = client.get(f"/api/style-projects/{project['identifier']}/evolution", params={"evaluationIdentifier": project["evaluationIdentifier"]})
            assert evolution.status_code == 200, evolution.text
            assert managed_path.call_count == 4
            managed_path.reset_mock()
            voted = client.post(f"/api/style-projects/{project['identifier']}/votes", json=vote_input(selection))
            assert voted.status_code == 200, voted.text
            assert managed_path.call_count <= 8
        selection = read_selection(client, project)
        candidate = next(candidate for candidate in results["candidates"] if candidate["identifier"] == selection["match"]["a"])
        server.managed_path(candidate["renders"][1]["files"][0]["path"]).unlink()
        rejected = client.post(f"/api/style-projects/{project['identifier']}/votes", json=vote_input(selection))
        assert rejected.status_code == 422
        latest = read_selection(client, project)
        assert latest["rankings"] == selection["rankings"]
        assert candidate["identifier"] not in latest["readyCandidateIdentifiers"]
        assert candidate["identifier"] not in [latest["match"]["a"], latest["match"]["b"]]
    finally:
        client.__exit__(None, None, None)


def test_evolution_preparation_still_checks_files_outside_current_pair(rated_population) -> None:
    """조회에서 Catalog를 사용해도 진화 준비는 현재 Pair 밖의 유실 파일까지 검사합니다."""

    server, _, client, project, _ = rated_population
    selection = read_selection(client, project)
    pair_identifiers = {selection["match"]["a"], selection["match"]["b"]}
    results = server.style_generation.store.results(project["identifier"], summary=True)
    missing_candidate = next(candidate for candidate in results["candidates"] if candidate["identifier"] not in pair_identifiers)
    server.managed_path(missing_candidate["renders"][1]["files"][0]["path"]).unlink()
    view = evolution_view(client, project)
    response = client.post(f"/api/style-projects/{project['identifier']}/evolution-plans", json={
        "operationIdentifier": uuid.uuid4().hex, "expectedProjectRevision": project["revision"],
        "expectedVotingRevision": view["votingRevision"], "childCount": 3,
    })
    assert response.status_code == 422, response.text
    assert read_selection(client, project)["rankings"] == selection["rankings"]
    with server.database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM style_evolution_batches").fetchone()[0] == 0
