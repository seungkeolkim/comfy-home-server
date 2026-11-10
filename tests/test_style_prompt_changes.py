"""생성 후 Prompt 저장·재접속·같은 조합 재생성의 실제 DB·파일 경계를 확인합니다."""

import copy
import hashlib
import json
import uuid

from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_evolution import wait_for_plan
from test_style_voting import read_selection, statistics_by_identifier


def save_changed_prompts(client, project, **additional_settings):
    """기존 두 Prompt에 세 번째 Case를 더하고 실제 프로젝트 설정으로 저장합니다."""

    settings = copy.deepcopy(project["settings"])
    settings["promptCases"].append({"identifier": "third-case", "name": "세 번째", "prompt": "night garden", "negativePrompt": "blur"})
    settings.update(additional_settings)
    response = client.put(f"/api/style-projects/{project['identifier']}", json={
        "settings": settings, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex,
    })
    assert response.status_code == 200, response.text
    return response.json()


def regeneration_payload(project, candidates):
    """수동 성분 대신 실제 원본 ID와 현재 저장 Revision만 전달합니다."""

    return {"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex,
            "candidateIdentifiers": [candidate["identifier"] for candidate in candidates]}


def test_third_prompt_saved_after_images_and_original_snapshots_preserved(tmp_path):
    """이미지 생성 뒤에도 세 번째 Prompt·해상도를 저장하고 별도 조회에서 그대로 읽습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    endpoint = f"/api/style-projects/{project['identifier']}"
    try:
        original_plan, _, original_results = submit_and_wait(client, project, plan_input)
        original_plan_snapshot = application.state.home_server.style_generation.store.plan(original_plan["planIdentifier"], project["identifier"])
        original_arena = read_selection(client, project)
        image_hashes = {file["path"]: hashlib.sha256(application.state.home_server.managed_path(file["path"]).read_bytes()).hexdigest()
                        for candidate in original_results["candidates"] for render in candidate["renders"] for file in render["files"]}
        updated = save_changed_prompts(client, project, width=768)
        assert updated["evaluationIdentifier"] != project["evaluationIdentifier"]
        assert updated["generation"] == project["generation"]
        assert client.get(endpoint).json()["settings"]["promptCases"][2]["prompt"] == "night garden"
        assert client.get("/api/style-workspace").json()["projects"][0]["promptCases"][2]["name"] == "세 번째"
        assert client.get(endpoint + "/generation-results").json()["candidates"] == original_results["candidates"]
        assert application.state.home_server.style_generation.store.plan(original_plan["planIdentifier"], project["identifier"]) == original_plan_snapshot
        assert statistics_by_identifier(read_selection(client, project)) == statistics_by_identifier(original_arena)
        for relative_path, expected_hash in image_hashes.items():
            assert hashlib.sha256(application.state.home_server.managed_path(relative_path).read_bytes()).hexdigest() == expected_hash
        with application.state.home_server.database._connect() as connection:
            assert len(json.loads(connection.execute("SELECT settings_json FROM style_projects WHERE project_id=?", (project["identifier"],)).fetchone()[0])["promptCases"]) == 3
            assert connection.execute("SELECT COUNT(*) FROM style_evaluation_revisions WHERE project_id=?", (project["identifier"],)).fetchone()[0] == 2
    finally:
        client.__exit__(None, None, None)


def test_same_combinations_render_all_new_prompts_without_copying_ratings(tmp_path):
    """세대·작가·LoRA·독립 CLIP은 유지하고 새 Prompt 세 개를 실제로 생성합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    endpoint = f"/api/style-projects/{project['identifier']}"
    try:
        for component in plan_input["combinations"][0]["components"]:
            if component["identifier"].startswith("lora:"):
                component["clip_strength"] = 0
        _, _, original_results = submit_and_wait(client, project, plan_input)
        original_arena = read_selection(client, project)
        updated = save_changed_prompts(client, project)
        payload = regeneration_payload(updated, original_results["candidates"])
        response = client.post(endpoint + "/prompt-regeneration-plans", json=payload)
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["imageCount"] == 6 and len(plan["cases"]) == 3
        assert plan["generationNumber"] == updated["generation"]
        assert plan["selection"]["sourceCandidateIdentifiers"] == payload["candidateIdentifiers"]
        assert [candidate["components"] for candidate in plan["candidates"]] == [candidate["components"] for candidate in original_results["candidates"]]
        assert client.post(endpoint + "/prompt-regeneration-plans", json=payload).json() == plan
        response = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        results = wait_for_plan(client, updated, plan)
        new_candidates = [candidate for candidate in results["candidates"] if candidate["evaluationIdentifier"] == updated["evaluationIdentifier"]]
        assert len(new_candidates) == 2
        assert all(len(candidate["renders"]) == 3 for candidate in new_candidates)
        assert all(render["files"] for candidate in new_candidates for render in candidate["renders"])
        assert statistics_by_identifier(read_selection(client, project)) == statistics_by_identifier(original_arena)
        assert all(statistics["rating"] == 10000 and statistics["matches"] == 0 for statistics in statistics_by_identifier(read_selection(client, updated)).values())
    finally:
        client.__exit__(None, None, None)


def test_prompt_regeneration_checks_owner_revision_and_preserves_frozen_components(tmp_path):
    """새 추첨 범위를 바꿔도 원본 조합은 고정하며 잘못된 원본·Revision은 거부합니다."""

    _, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    endpoint = f"/api/style-projects/{project['identifier']}"
    try:
        _, _, original_results = submit_and_wait(client, project, plan_input)
        updated = save_changed_prompts(client, project, loraMinimumCount=0, loraMaximumCount=0)
        payload = regeneration_payload(updated, original_results["candidates"])
        stale_payload = {**payload, "expectedRevision": project["revision"]}
        assert client.post(endpoint + "/prompt-regeneration-plans", json=stale_payload).status_code == 409
        unknown_payload = {**payload, "candidateIdentifiers": [uuid.uuid4().hex]}
        assert client.post(endpoint + "/prompt-regeneration-plans", json=unknown_payload).status_code == 404
        duplicate_payload = {**payload, "candidateIdentifiers": [payload["candidateIdentifiers"][0]] * 2}
        assert client.post(endpoint + "/prompt-regeneration-plans", json=duplicate_payload).status_code == 422
        response = client.post(endpoint + "/prompt-regeneration-plans", json=payload)
        assert response.status_code == 201, response.text
        assert [candidate["components"] for candidate in response.json()["candidates"]] == [candidate["components"] for candidate in original_results["candidates"]]
    finally:
        client.__exit__(None, None, None)


def test_prompt_and_project_name_can_be_saved_together_after_generation(tmp_path):
    """이름·Prompt 동시 저장도 기존 관리 Rename과 한 저장 요청으로 완료합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, original_results = submit_and_wait(client, project, plan_input)
        original_hashes = sorted(hashlib.sha256(application.state.home_server.managed_path(file["path"]).read_bytes()).hexdigest()
                                 for candidate in original_results["candidates"] for render in candidate["renders"] for file in render["files"])
        updated = save_changed_prompts(client, project, name="새 프로젝트 이름")
        assert updated["name"] == "새 프로젝트 이름"
        results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        assert sorted(hashlib.sha256(application.state.home_server.managed_path(file["path"]).read_bytes()).hexdigest()
                      for candidate in results["candidates"] for render in candidate["renders"] for file in render["files"]) == original_hashes
    finally:
        client.__exit__(None, None, None)
