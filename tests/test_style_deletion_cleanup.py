"""조합 폐기의 Placement·공유 Job·빈 Job·이전 삭제 복구와 DB 실패 재시도를 검증합니다."""

import json
import time
import uuid

import home_server.style_candidate_deletion as deletion_module
from home_server.style_projects import encode_snapshot
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_management import management_payload
from test_style_voting import read_selection, vote_input


def test_deleting_placement_reference_removes_pair_and_empty_job(tmp_path) -> None:
    """배치 기준 조합 삭제 뒤 신규만 남아도 재귀 오류·유령 대결 없이 모든 이력을 지웁니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        endpoint = f"/api/style-projects/{project['identifier']}"
        first, second = [candidate["identifier"] for candidate in results["candidates"]]
        rated = client.post(endpoint + "/candidate-ratings", json=management_payload(client, project, [first], 13000))
        assert rated.status_code == 200
        before = read_selection(client, project)
        assert before["match"]["kind"] == "place"
        stale_vote = vote_input(before)
        response = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [first]))
        assert response.status_code == 200, response.text
        selection = read_selection(client, project)
        assert selection["match"] is None
        assert [entry["identifier"] for entry in selection["rankings"]] == [second]
        assert selection["rankings"][0]["rated"]
        assert client.post(endpoint + "/votes", json=stale_vote).status_code == 409
        assert client.get(f"/api/jobs/{job['jobIdentifier']}").json()["request_count"] == 2
        with server.database._connect() as connection:
            state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas").fetchone()[0])
            assert first not in state["statistics"] and state["placement"] is None
        final_payload = management_payload(client, project, [second])
        final = client.post(endpoint + "/candidate-deletions", json=final_payload)
        assert final.status_code == 200, final.text
        assert final.json()["deletedJobIdentifiers"] == [job["jobIdentifier"]]
        assert client.post(endpoint + "/candidate-deletions", json=final_payload).json() == final.json()
        assert client.get(f"/api/jobs/{job['jobIdentifier']}").status_code == 404
        assert client.get("/api/jobs?include_style=true").json()["total"] == 0
        assert not client.get(endpoint + "/generation-results").json()["candidates"]
        assert not read_selection(client, project)["rankings"]
        rejected = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
        assert rejected.status_code == 409
        with server.database._connect() as connection:
            for table in ("output_files", "job_requests", "request_results", "jobs", "job_inputs", "job_folder_assignments", "style_job_ownership", "style_candidate_renders"):
                assert connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0, table
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        client.__exit__(None, None, None)


def test_old_completed_deletion_cleans_remaining_requests_once(tmp_path, monkeypatch) -> None:
    """이전 삭제 완료 영수증의 남은 요청·Elo를 한 번만 정리하고 다른 조합은 보존합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, job, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        first, second = [candidate["identifier"] for candidate in results["candidates"]]
        endpoint = f"/api/style-projects/{project['identifier']}"
        before = read_selection(client, project)
        original_cleanup = deletion_module.remove_deleted_candidate_history

        def preserve_legacy_history(connection, identifiers):
            """이전 구현처럼 파일만 삭제하고 생성 이력은 남깁니다."""

            return {}

        monkeypatch.setattr(deletion_module, "remove_deleted_candidate_history", preserve_legacy_history)
        payload = management_payload(client, project, [first])
        deleted = client.post(endpoint + "/candidate-deletions", json=payload)
        assert deleted.status_code == 200
        legacy_receipt = deleted.json()
        legacy_receipt.pop("cleanupVersion")
        with server.database._connect() as connection:
            connection.execute("UPDATE style_voting_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(legacy_receipt), payload["operationIdentifier"]))
            connection.execute("UPDATE style_voting_arenas SET state_json=?", (encode_snapshot({
                "policyVersion": "style-arena-v2", "statistics": {entry["identifier"]: {key: entry[key] for key in ("rating", "matches", "wins", "skips", "placed")} for entry in before["rankings"]},
                "componentStatistics": {}, "match": before["match"], "placement": None, "lastPair": [], "undoStack": [], "skippedTies": [],
            }),))
        monkeypatch.setattr(deletion_module, "remove_deleted_candidate_history", original_cleanup)
        server.style_candidate_deletion.recover_pending_deletions()
        assert [entry["identifier"] for entry in read_selection(client, project)["rankings"]] == [second]
        assert server.database.get_job(job["jobIdentifier"])["request_count"] == 2
        receipt = client.post(endpoint + "/candidate-deletions", json=payload).json()
        assert receipt["cleanupVersion"] == 2 and receipt["deletedRequestCount"] == 2
        server.style_candidate_deletion.recover_pending_deletions()
        assert client.post(endpoint + "/candidate-deletions", json=payload).json() == receipt
    finally:
        client.__exit__(None, None, None)


def test_history_transaction_failure_remains_recoverable(tmp_path) -> None:
    """파일 삭제 후 DB 정리가 실패해도 요청 제거는 Rollback되고 같은 명령으로 복구됩니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        endpoint = f"/api/style-projects/{project['identifier']}"
        payload = management_payload(client, project, [results["candidates"][0]["identifier"]])
        with server.database._connect() as connection:
            connection.execute("CREATE TRIGGER reject_history_cleanup BEFORE DELETE ON job_requests BEGIN SELECT RAISE(ABORT,'fixture history failure'); END")
        response = client.post(endpoint + "/candidate-deletions", json=payload)
        assert response.status_code == 409
        with server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0] == 4
            assert connection.execute("SELECT COUNT(*) FROM style_candidate_renders").fetchone()[0] == 4
            connection.execute("DROP TRIGGER reject_history_cleanup")
        server.style_candidate_deletion.recover_pending_deletions()
        recovered = client.post(endpoint + "/candidate-deletions", json=payload)
        assert recovered.status_code == 200 and recovered.json()["cleanupVersion"] == 2
        assert recovered.json()["deletedRequestCount"] == 2
    finally:
        client.__exit__(None, None, None)


def test_deletion_cleans_retry_jobs_and_preserves_general_history(tmp_path) -> None:
    """같은 조합의 실패·재시도를 여러 Job에서 제거하고 일반 작업은 그대로 보존합니다."""

    fake = StyleComfyClient()
    fake.fail_first_submission = True
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake)
    try:
        plan, original_job, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        endpoint = f"/api/style-projects/{project['identifier']}"
        server.database.add_job("general-preserved", "anima", "보존할 일반 작업", [{
            "request_id": "general-request-preserved", "status": "completed", "output_stem": "anima/general", "detail": {},
        }])
        general_before = server.database.get_job("general-preserved")
        retry = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True})
        assert retry.status_code == 200, retry.text
        retry_identifier = retry.json()["jobIdentifier"]
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if server.database.get_job(retry_identifier)["requests"][0]["status"] == "completed":
                break
            time.sleep(0.04)
        assert server.database.get_job(retry_identifier)["requests"][0]["status"] == "completed"
        target_identifier = results["candidates"][0]["identifier"]
        deleted = client.post(endpoint + "/candidate-deletions", json=management_payload(client, project, [target_identifier]))
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deletedRequestCount"] == 3
        assert deleted.json()["deletedJobIdentifiers"] == [retry_identifier]
        assert server.database.get_job(original_job["jobIdentifier"])["request_count"] == 2
        assert server.database.get_job("general-preserved") == general_before
        assert client.get(f"/api/jobs/{retry_identifier}").status_code == 404
    finally:
        client.__exit__(None, None, None)
