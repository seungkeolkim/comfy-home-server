"""고정 생성·출력 분리·관리 Rename의 실제 API·DB·파일 효과를 검증합니다."""

import copy
import json
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

import pytest
import httpx
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from home_server.style_projects import ProjectWriteInput
from home_server.style_project_rename import StyleProjectRenameService
from test_application import FakeComfyClient, create_processing_test_app


class StyleComfyClient(FakeComfyClient):
    """등록 Graph를 받아 실제 임시 PNG와 Comfy History를 만듭니다."""

    def __init__(self) -> None:
        """완료·실패·대기 조건을 제어할 값을 준비합니다."""

        super().__init__()
        self.output_directory = None
        self.complete_submissions = True
        self.fail_first_submission = False
        self.checked_nodes = []

    async def request_json(self, method: str, path: str, **kwargs):
        """필수 Node의 존재 검사를 실제 요청 경로와 같은 형태로 반환합니다."""

        class_type = unquote(path.rsplit("/", 1)[-1])
        self.checked_nodes.append(class_type)
        return {class_type: {"input": {}}}

    async def lora_identities(self, file_names: list[str]) -> dict:
        """고정 파일 Hash를 제공해 계획과 제출의 동일성 검사를 검증합니다."""

        return {name: {"sha256": "a" * 64, "file_size": 1024, "modified": 1, "source": "test"} for name in file_names}

    async def populate_wildcards(self, prompt: str, seed: int) -> str:
        """같은 Case의 전개가 후보마다 다시 실행되지 않는지 기록합니다."""

        self.wildcard_prompts.append((prompt, seed))
        return prompt.replace("{morning|night}", "morning")

    async def submit(self, workflow: dict, metadata: dict) -> str:
        """실제 해상도·Workflow Metadata가 있는 생성물을 반환합니다."""

        prompt_identifier = await super().submit(workflow, metadata)
        if not self.complete_submissions:
            return prompt_identifier
        if self.fail_first_submission and len(self.submissions) == 1:
            self.history_records[prompt_identifier] = {"status": {"status_str": "error", "messages": []}, "outputs": {}}
            return prompt_identifier
        saver = workflow["13"]["inputs"]
        output_directory = self.output_directory / saver["path"]
        output_directory.mkdir(parents=True, exist_ok=True)
        file_name = saver["filename"] + ".png"
        png_metadata = PngImagePlugin.PngInfo()
        for key, value in {"prompt": workflow, **metadata}.items():
            png_metadata.add_text(key, json.dumps(value, ensure_ascii=False))
        Image.new("RGB", (workflow["45"]["inputs"]["value"], workflow["48"]["inputs"]["value"]), "navy").save(output_directory / file_name, pnginfo=png_metadata)
        self.history_records[prompt_identifier] = {"status": {"status_str": "success"}, "outputs": {"13": {"images": [{"filename": file_name, "subfolder": saver["path"], "type": "output"}]}}}
        return prompt_identifier


def prepare_style_generation(tmp_path: Path, fake_client: StyleComfyClient):
    """일반 작업과 같은 실제 프로젝트 API를 사용하는 격리 앱을 만듭니다."""

    application = create_processing_test_app(tmp_path, fake_client)
    fake_client.output_directory = application.state.home_server.config.comfy_output_directory
    client = TestClient(application)
    client.__enter__()
    client.post("/api/login", json={"password": "test"})
    settings = {
        "name": "실제 설정 프로젝트", "pipelineIdentifier": "anima", "width": 64, "height": 96, "steps": 3, "cfg": 1,
        "promptCases": [{"identifier": "portrait", "name": "인물", "prompt": "portrait, {morning|night}, {artist}"},
                        {"identifier": "garden", "name": "정원", "prompt": "garden, {artist}"}],
        "negativePrompt": "bad quality", "seed": 123456,
        "componentPolicies": {"lora:example.safetensors": {"enabled": True, "minimumStrength": 0.2, "maximumStrength": 0.9},
                              "artist:example": {"enabled": True, "minimumStrength": 0.4, "maximumStrength": 0.8}},
    }
    response = client.post("/api/style-projects", json={"settings": settings, "operationIdentifier": uuid.uuid4().hex})
    assert response.status_code == 201, response.text
    project = response.json()
    plan_input = {"expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex,
                  "combinations": [
                      {"components": [{"identifier": "lora:example.safetensors", "strength": 0.4, "clip_strength": 0}, {"identifier": "artist:example", "strength": 0.5}]},
                      {"components": [{"identifier": "lora:example.safetensors", "strength": 0.8, "clip_strength": 0}, {"identifier": "artist:example", "strength": 0.7}]},
                  ]}
    return application, client, project, plan_input


def submit_and_wait(client, project, plan_input, expected_states=None):
    """고정 계획을 제출한 뒤 Home 감시가 완료할 때까지 기다립니다."""

    response = client.post(f"/api/style-projects/{project['identifier']}/generation-plans", json=plan_input)
    assert response.status_code == 201, response.text
    plan = response.json()
    submit_input = {"operationIdentifier": uuid.uuid4().hex}
    response = client.post(f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit", json=submit_input)
    assert response.status_code == 200, response.text
    job = response.json()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        states = [render["status"] for candidate in results["candidates"] for render in candidate["renders"]]
        if states and not any(state in {"submitting", "pending", "running", "cancelling"} for state in states):
            return plan, job, results
        time.sleep(0.05)
    raise AssertionError(states)


def test_project_generation_freezes_cases_seed_loras_and_metadata(tmp_path: Path) -> None:
    """프로젝트 조건의 2×2 이미지가 같은 Adapter와 Seed로 생성됩니다."""

    fake_client = StyleComfyClient()
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        assert plan["imageCount"] == 4
        assert len(fake_client.submissions) == 4
        assert len(fake_client.wildcard_prompts) == 4
        assert "UltralyticsDetectorProvider" not in fake_client.checked_nodes
        for graph, metadata in fake_client.submissions:
            assert graph["24"]["inputs"]["seed"] == 123456
            assert graph["24"]["inputs"]["steps"] == 3
            assert graph["45"]["inputs"]["value"] == 64
            assert graph["5"]["inputs"]["loras"]["__value__"][0]["clipStrength"] == 0
            assert graph["462"]["class_type"] == "CLIPNegPip"
            assert graph["13"]["inputs"]["extension"] == "png"
            assert metadata["home_server_request"]["style_context"]["project_id"] == project["identifier"]
            assert "{artist}" not in metadata["home_server_request"]["prompt"]
            assert "bad quality" == metadata["home_server_request"]["negative"]
        assert [render["status"] for candidate in results["candidates"] for render in candidate["renders"]] == ["completed"] * 4
        file = results["candidates"][0]["renders"][0]["files"][0]
        assert file["path"].startswith("from_comfy_home_style/")
        assert client.get("/media/" + file["path"]).status_code == 200
        assert client.get("/api/outputs/preview/" + file["path"]).status_code == 200
        server = application.state.home_server
        with Image.open(server.managed_path(file["path"])) as image:
            assert image.size == (64, 96)
            assert json.loads(image.info["home_server_request"])["settings"]["seed"] == 123456
        same_job = client.post(f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex}).json()
        assert same_job["jobIdentifier"] == job["jobIdentifier"]
        assert len(fake_client.submissions) == 4
        assert client.get("/api/style-projects").json()["projects"][0]["candidateCount"] == 2
    finally:
        client.__exit__(None, None, None)


def test_style_visibility_filters_counts_selection_neighbors_and_moves(tmp_path: Path) -> None:
    """숨김·전체 선택·폴더 건수·직접 API 이동 차단을 같은 범위로 검증합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        file = results["candidates"][0]["renders"][0]["files"][0]
        assert client.get("/api/jobs").json()["total"] == 0
        assert client.get("/api/jobs", params={"include_style": True}).json()["total"] == 1
        assert client.get("/api/outputs").json()["total"] == 0
        assert client.get("/api/outputs", params={"include_style": True}).json()["total"] == 4
        assert client.get("/api/job-folders").json()["items"] == []
        folders = client.get("/api/job-folders", params={"include_style": True}).json()
        assert len(folders["items"]) == 2
        assert all(folder["managed_by_style"] for folder in folders["items"])
        assert client.get("/api/outputs/selection-candidates").json()["output_ids"] == []
        assert len(client.get("/api/outputs/selection-candidates", params={"include_style": True}).json()["output_ids"]) == 4
        assert client.get(f"/api/outputs/{file['output_id']}/neighbors").status_code == 404
        assert client.get(f"/api/outputs/{file['output_id']}/neighbors", params={"include_style": True}).status_code == 200
        assert client.post("/api/jobs/folder", json={"job_ids": [job["jobIdentifier"]], "folder_id": None}).status_code == 422
        project_folder = folders["items"][1]
        assert client.put(f"/api/job-folders/{project_folder['folder_id']}", json={"name": "우회", "parent_id": None}).status_code == 422
        response = client.post("/api/outputs/move", json={"source": file["path"], "destination_folder": "other"})
        assert response.status_code == 422
        assert "스타일" in response.json()["detail"]
        assert client.put(f"/api/outputs/{file['output_id']}/favorite").status_code == 200
        assert client.get("/api/favorites").json()["total"] == 0
        assert client.get("/api/favorites", params={"include_style": True}).json()["total"] == 1
    finally:
        client.__exit__(None, None, None)


def test_project_rename_moves_files_and_preserves_ids_memos_snapshots(tmp_path: Path) -> None:
    """폴더·분류명·조회 참조를 바꾸되 생성 기록과 메모는 수정하지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        old_file = results["candidates"][0]["renders"][0]["files"][0]
        server = application.state.home_server
        old_path = server.managed_path(old_file["path"])
        original_bytes = old_path.read_bytes()
        settings = copy.deepcopy(project["settings"])
        settings["name"] = "바꾼 프로젝트"
        payload = {"settings": settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": project["revision"]}
        response = client.put(f"/api/style-projects/{project['identifier']}", json=payload)
        assert response.status_code == 200, response.text
        renamed = response.json()
        assert renamed["evaluationIdentifier"] == project["evaluationIdentifier"]
        new_results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        new_file = new_results["candidates"][0]["renders"][0]["files"][0]
        assert new_file["output_id"] == old_file["output_id"]
        assert "바꾼 프로젝트" in new_file["path"]
        assert not old_path.exists()
        assert server.managed_path(new_file["path"]).read_bytes() == original_bytes
        assert client.get("/media/" + new_file["path"]).status_code == 200
        assert server.database.get_job(job["jobIdentifier"])["description"] == "세대001-01 이미지 생성"
        assert client.put(f"/api/style-projects/{project['identifier']}", json=payload).status_code == 200
        assert len(client.get("/api/outputs", params={"include_style": True}).json()["files"]) == 4
        server.output_catalog.synchronize(server.config.managed_output_directory, server.style_output_directory)
        assert len(client.get("/api/outputs", params={"include_style": True}).json()["files"]) == 4
    finally:
        client.__exit__(None, None, None)


def test_failed_case_retry_does_not_repeat_completed_renders(tmp_path: Path) -> None:
    """실패한 한 Case만 재생성하고 완료 이미지와 후보는 유지합니다."""

    fake_client = StyleComfyClient()
    fake_client.fail_first_submission = True
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        plan, job, results = submit_and_wait(client, project, plan_input)
        assert len(fake_client.submissions) == 4
        response = client.post(f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True})
        assert response.status_code == 200, response.text
        assert len(response.json()["requestIdentifiers"]) == 1
        deadline = time.monotonic() + 5
        while len(fake_client.submissions) < 5 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(fake_client.submissions) == 5
        assert len(client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()["candidates"]) == 2
    finally:
        client.__exit__(None, None, None)


def test_plan_rejects_unselected_out_of_range_duplicate_and_changed_files(tmp_path: Path) -> None:
    """잘못된 조합·바뀐 파일을 Queue 접수 전에 거절합니다."""

    fake_client = StyleComfyClient()
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    endpoint = f"/api/style-projects/{project['identifier']}/generation-plans"
    try:
        for identifier, strength in [("artist:unselected", 0.5), ("lora:example.safetensors", 2)]:
            invalid = copy.deepcopy(plan_input)
            invalid["combinations"][0]["components"][0] = {"identifier": identifier, "strength": strength}
            assert client.post(endpoint, json=invalid).status_code == 422
        invalid = copy.deepcopy(plan_input)
        invalid["combinations"][1] = {"components": list(reversed(invalid["combinations"][0]["components"]))}
        assert client.post(endpoint, json=invalid).status_code == 422
        response = client.post(endpoint, json=plan_input)
        assert response.status_code == 201, response.text
        plan = response.json()

        async def changed_identities(file_names: list[str]) -> dict:
            """계획 이후 교체된 파일의 Hash를 재현합니다."""

            return {name: {"sha256": "b" * 64, "file_size": 1024, "modified": 1} for name in file_names}

        fake_client.lora_identities = changed_identities
        response = client.post(endpoint + f"/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 422, response.text
        assert "LoRA" in response.json()["detail"]
        assert application.state.home_server.database.list_jobs(include_style=True)["total"] == 0
        assert fake_client.submissions == []
    finally:
        client.__exit__(None, None, None)


def test_stale_plan_and_active_project_rename_are_rejected(tmp_path: Path) -> None:
    """이전 설정으로 생성하거나 실행 중 폴더를 변경하지 못하게 합니다."""

    fake_client = StyleComfyClient()
    fake_client.complete_submissions = False
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    endpoint = f"/api/style-projects/{project['identifier']}"
    try:
        plan = client.post(endpoint + "/generation-plans", json=plan_input).json()
        settings = copy.deepcopy(project["settings"])
        settings["purpose"] = "revision changed"
        updated = client.put(endpoint, json={"settings": settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": project["revision"]}).json()
        response = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 409
        plan_input["expectedRevision"] = updated["revision"]
        plan_input["operationIdentifier"] = uuid.uuid4().hex
        plan = client.post(endpoint + "/generation-plans", json=plan_input).json()
        response = client.post(endpoint + f"/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        settings["name"] = "실행 중 이름 변경"
        response = client.put(endpoint, json={"settings": settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": updated["revision"]})
        assert response.status_code == 409
        assert "끝난 뒤" in response.json()["detail"]
    finally:
        client.__exit__(None, None, None)


def test_interrupted_rename_recovers_without_overwriting_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """폴더 이동 후 DB 반영 실패를 재현하고 같은 Operation으로 복구합니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        original_file = results["candidates"][0]["renders"][0]["files"][0]
        original_bytes = server.managed_path(original_file["path"]).read_bytes()
        settings = copy.deepcopy(project["settings"])
        settings["name"] = "복구된 프로젝트"
        payload = ProjectWriteInput(settings=settings, expectedRevision=project["revision"], operationIdentifier=uuid.uuid4().hex)
        repository = server.database.style_projects
        original_save = repository.save_project

        def interrupted_save(*arguments, **keyword_arguments):
            """파일 Rename 직후 DB Transaction만 실패시킵니다."""

            raise OSError("simulated interruption after folder rename")

        monkeypatch.setattr(repository, "save_project", interrupted_save)
        with pytest.raises(OSError):
            StyleProjectRenameService(server.style_generation).save_project(project["identifier"], payload)
        with server.database._connect() as connection:
            assert connection.execute("SELECT state FROM style_project_renames").fetchone()[0] == "pending_error"
        monkeypatch.setattr(repository, "save_project", original_save)
        server.style_generation.recover_renames()
        files = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()["candidates"][0]["renders"][0]["files"]
        assert files[0]["output_id"] == original_file["output_id"]
        assert "복구된 프로젝트" in files[0]["path"]
        assert server.managed_path(files[0]["path"]).read_bytes() == original_bytes
        assert len(list(server.style_output_directory.rglob("*.png"))) == 4
    finally:
        client.__exit__(None, None, None)


def test_mixed_bulk_move_rejects_before_moving_general_file(tmp_path: Path) -> None:
    """일반 이미지와 스타일 이미지의 혼합 이동은 첫 파일부터 이동하지 않습니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        _, _, results = submit_and_wait(client, project, plan_input)
        server = application.state.home_server
        general_path = server.config.managed_output_directory / "general.png"
        Image.new("RGB", (64, 96), "red").save(general_path)
        server.output_catalog.synchronize(server.config.managed_output_directory, server.style_output_directory)
        general_file = client.get("/api/outputs").json()["files"][0]
        style_file = results["candidates"][0]["renders"][0]["files"][0]
        response = client.post("/api/outputs/move-batch", json={"output_ids": [general_file["output_id"], style_file["output_id"]], "destination_folder": "moved"})
        assert response.status_code == 422, response.text
        assert general_path.is_file()
        assert not (server.config.managed_output_directory / "moved" / "general.png").exists()
    finally:
        client.__exit__(None, None, None)


def test_missing_node_and_uncertain_submission_cannot_be_resubmitted(tmp_path: Path) -> None:
    """필수 Node 누락은 사전 거절하고 접수 미확인은 중복 생성하지 않습니다."""

    fake_client = StyleComfyClient()
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    endpoint = f"/api/style-projects/{project['identifier']}/generation-plans"
    try:
        original_request = fake_client.request_json

        async def missing_node(method: str, path: str, **keyword_arguments):
            """NegPip만 설치되지 않은 ComfyUI를 재현합니다."""

            if path.endswith("CLIPNegPip"):
                return {}
            return await original_request(method, path, **keyword_arguments)

        fake_client.request_json = missing_node
        response = client.post(endpoint, json=plan_input)
        assert response.status_code == 422
        assert "CLIPNegPip" in response.json()["detail"]

        async def unavailable_node(method: str, path: str, **keyword_arguments):
            """ComfyUI 사전 확인의 연결 실패를 재현합니다."""

            raise httpx.ConnectError("ComfyUI unavailable")

        fake_client.request_json = unavailable_node
        response = client.post(endpoint, json=plan_input)
        assert response.status_code == 502
        assert "접수하지 않았습니다" in response.json()["detail"]
        fake_client.request_json = original_request

        async def uncertain_submit(workflow: dict, metadata: dict) -> str:
            """접수 여부를 확인하지 못한 연결 종료를 재현합니다."""

            raise RuntimeError("connection closed before acknowledgement")

        fake_client.submit = uncertain_submit
        plan, _, results = submit_and_wait(client, project, plan_input)
        assert {render["status"] for candidate in results["candidates"] for render in candidate["renders"]} == {"stopped"}
        response = client.post(endpoint + f"/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex, "retryFailedOnly": True})
        assert response.status_code == 409
        assert "미확인" in response.json()["detail"]
        assert application.state.home_server.database.list_jobs(include_style=True)["total"] == 1
    finally:
        client.__exit__(None, None, None)


def test_style_cancellation_preserves_general_queue_request(tmp_path: Path) -> None:
    """프로젝트 생성 취소가 같은 ComfyUI의 일반 작업을 취소하지 않습니다."""

    fake_client = StyleComfyClient()
    fake_client.complete_submissions = False
    application, client, project, plan_input = prepare_style_generation(tmp_path, fake_client)
    try:
        plan = client.post(f"/api/style-projects/{project['identifier']}/generation-plans", json=plan_input).json()
        job = client.post(f"/api/style-projects/{project['identifier']}/generation-plans/{plan['planIdentifier']}/submit", json={"operationIdentifier": uuid.uuid4().hex}).json()
        deadline = time.monotonic() + 5
        while len(fake_client.submissions) < 4 and time.monotonic() < deadline:
            time.sleep(0.02)
        fake_client.submissions.append(({}, {}))
        database = application.state.home_server.database
        database.add_job("general-keep", "anima", "일반 작업 유지", [{"request_id": "general-keep-request", "status": "submitting", "output_stem": "anima/output", "detail": {}}])
        database.set_request_accepted("general-keep-request", "prompt-5", {})
        assert client.post(f"/api/jobs/{job['jobIdentifier']}/cancel").status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            statuses = [request["status"] for request in database.get_job(job["jobIdentifier"])["requests"]]
            if statuses == ["cancelled"] * 4:
                break
            time.sleep(0.05)
        assert statuses == ["cancelled"] * 4
        assert database.get_request("general-keep-request")["status"] == "pending"
        assert "prompt-5" not in fake_client.history_records
    finally:
        client.__exit__(None, None, None)
