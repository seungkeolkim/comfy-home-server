"""인증과 모델별 Prompt, 파일 경계, 제출 상태 API를 검증합니다."""

import json
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.application import create_app, selected_tag_definitions
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from home_server.database import Database
from home_server.tag_builder import resolve_tag_prompt


class FakeComfyClient:
    """실제 GPU 작업 없이 ComfyUI queue 응답을 흉내 냅니다."""

    def __init__(self) -> None:
        """접수한 Prompt와 대기열을 초기화합니다."""

        self.submissions = []
        self.wildcard_prompts = []
        self.history_records = {}
        self.running_prompt_ids = set()

    async def close(self) -> None:
        """가짜 client는 정리할 연결이 없습니다."""

    async def list_loras(self) -> list[str]:
        """테스트용 LoRA 목록을 반환합니다."""

        return ["example.safetensors"]

    async def populate_wildcards(self, prompt: str, seed: int) -> str:
        """테스트에서는 입력 Prompt를 그대로 확정합니다."""

        self.wildcard_prompts.append(prompt)
        return prompt

    async def upload_image(self, image_path: Path, file_name: str) -> str:
        """입력 이미지의 ComfyUI 업로드 경로를 흉내 냅니다."""

        return f"from_home_server/{file_name}"

    async def submit(self, workflow: dict, metadata: dict) -> str:
        """제출 내용을 보관하고 임의의 접수 ID를 반환합니다."""

        self.submissions.append((workflow, metadata))
        return f"prompt-{len(self.submissions)}"

    async def queue(self) -> dict:
        """접수한 요청을 대기 중인 것으로 보여줍니다."""

        pending_requests = []
        running_requests = []
        for submission_index in range(1, len(self.submissions) + 1):
            prompt_id = f"prompt-{submission_index}"
            if prompt_id not in self.history_records:
                if prompt_id in self.running_prompt_ids:
                    running_requests.append([0, prompt_id])
                else:
                    pending_requests.append([0, prompt_id])
        return {"queue_running": running_requests, "queue_pending": pending_requests}

    async def history(self, prompt_id: str) -> dict:
        """테스트에서 지정한 완료 기록을 반환합니다."""

        return {prompt_id: self.history_records[prompt_id]} if prompt_id in self.history_records else {}

    async def cancel_prompt(self, prompt_id: str) -> bool:
        """지정한 대기·실행 요청의 중단 기록을 만듭니다."""

        if prompt_id in self.history_records:
            return False
        self.history_records[prompt_id] = {"status": {"status_str": "interrupted"}, "outputs": {}}
        self.running_prompt_ids.discard(prompt_id)
        return True


def create_test_anima_tag(client: TestClient, content: str = "subject") -> str:
    """Anima API 테스트에서 사용할 SCENE 태그를 생성합니다."""

    group_response = client.post("/api/tags/groups", json={"name": "Test group", "tag_key": "SCENE"})
    assert group_response.status_code == 201
    tag_response = client.post("/api/tags/entries", json={
        "group_id": group_response.json()["group_id"],
        "name": "Test scene", "content": content, "weight": 1,
    })
    assert tag_response.status_code == 201
    return tag_response.json()["tag_id"]


def test_login_batch_and_output_folder_boundary(tmp_path: Path) -> None:
    """인증 후 제출하고 관리 output 안에서만 파일을 이동합니다."""

    output_directory = tmp_path / "comfy_output"
    managed_directory = output_directory / "from_home_server"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test-password", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy
    with TestClient(app) as client:
        assert client.get("/api/presets").status_code == 401
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
        profile_response = client.post("/api/loras/profiles", json={
            "name": "example.safetensors", "workflow": "anima", "strength": 0.75,
            "clip_strength": 0.5,
        })
        assert profile_response.json()["saved"] is True
        assert client.get("/api/loras").json()["profiles"][0]["settings"]["strength"] == 0.75
        selected_tag_id = create_test_anima_tag(client)

        preset_response = client.post("/api/presets", json={
            "name": "Test", "workflow": "anima",
            "body": {"prompt": "a portrait, [SCENE]"},
        })
        assert preset_response.status_code == 200
        assert preset_response.json()["version"] == 1
        second_version = client.post("/api/presets", json={
            "preset_id": preset_response.json()["preset_id"], "name": "Test", "workflow": "anima",
            "body": {"prompt": "a different portrait, [SCENE]"},
        })
        assert second_version.json()["version"] == 2
        versions = client.get(f"/api/presets/{preset_response.json()['preset_id']}/versions").json()
        assert [version["version"] for version in versions] == [2, 1]

        batch_response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prompt": "a portrait, [SCENE]"},
            "selected_tag_ids": [selected_tag_id],
            "count": 1, "settings": {"width": 512, "height": 512}, "loras": [],
        })
        assert batch_response.status_code == 200
        request_id = batch_response.json()["request_ids"][0]
        job_id = batch_response.json()["job_id"]
        for _ in range(30):
            jobs = client.get("/api/jobs").json()["items"]
            if jobs[0]["requests"][0]["prompt_id"]:
                break
            time.sleep(0.05)
        assert jobs[0]["job_id"] == job_id
        assert jobs[0]["request_count"] == 1
        assert jobs[0]["requests"][0]["request_id"] == request_id
        assert jobs[0]["requests"][0]["prompt_id"] == "prompt-1"
        assert fake_comfy.submissions[0][0]["13"]["inputs"]["path"] == "from_home_server/anima"
        assert client.post(f"/api/requests/{request_id}/cancel").json()["status"] == "cancelling"
        assert client.get("/api/jobs", params={"refresh": True}).json()["items"][0]["status"] == "cancelled"

        image_path = managed_directory / "anima" / "sample.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(b"example")
        assert client.get("/api/outputs").json()["total"] == 1
        assert client.get("/media/../secret.png").status_code != 200
        moved = client.post("/api/outputs/move", json={"source": "anima/sample.png", "destination_folder": "sorted"})
        assert moved.status_code == 200
        assert moved.json()["path"] == "sorted/sample.png"
        assert not image_path.exists()
        assert client.post("/api/outputs/move", json={"source": "../secret.png", "destination_folder": "sorted"}).status_code == 422

    log_text = (tmp_path / "runtime" / "logs" / "home_server.log").read_text(encoding="utf-8")
    assert "Batch 생성" in log_text
    assert "요청 접수" in log_text
    assert "test-password" not in log_text
    assert "a portrait" not in log_text


def test_output_pagination_and_transient_preview(tmp_path: Path) -> None:
    """목록을 나누고 원본을 유지한 채 인증된 작은 preview만 전송합니다."""

    output_directory = tmp_path / "output"
    managed_directory = output_directory / "from_home_server"
    image_directory = managed_directory / "anima"
    image_directory.mkdir(parents=True)
    original_path = image_directory / "large.png"
    Image.new("RGB", (1600, 1200), (31, 64, 96)).save(original_path)
    Image.new("RGB", (100, 100), (50, 60, 70)).save(image_directory / "animation.gif")
    for image_number in range(25):
        (image_directory / f"small-{image_number:02d}.png").write_bytes(b"listed file")
    (image_directory / "movie.webm").write_bytes(b"listed video")
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    with TestClient(app) as client:
        preview_url = "/api/outputs/preview/anima/large.png"
        assert client.get(preview_url).status_code == 401
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        first_page = client.get("/api/outputs").json()
        second_page = client.get("/api/outputs", params={"page": 2}).json()
        assert first_page["total"] == 28
        assert first_page["page_size"] == 24
        assert first_page["total_pages"] == 2
        assert len(first_page["files"]) == 24
        assert len(second_page["files"]) == 4
        assert {file["path"] for file in first_page["files"]}.isdisjoint(
            file["path"] for file in second_page["files"]
        )
        assert client.get("/api/outputs", params={"page": 0}).status_code == 422
        assert client.get("/api/outputs", params={"page_size": 101}).status_code == 422
        assert client.get("/api/outputs", params={"page": 3}).json()["files"] == []
        assert client.get("/api/outputs", params={"prefix": "anima/large"}).json()["total"] == 1
        image_file = client.get("/api/outputs", params={"prefix": "anima/large"}).json()["files"][0]
        assert (image_file["width"], image_file["height"], image_file["dimensions_source"]) == (1600, 1200, "file")
        video_file = next(file for file in [*first_page["files"], *second_page["files"]] if file["name"] == "movie.webm")
        assert (video_file["width"], video_file["height"]) == (None, None)

        preview_response = client.get(preview_url)
        assert preview_response.status_code == 200
        assert preview_response.headers["content-type"] == "image/webp"
        assert preview_response.headers["cache-control"].startswith("private")
        assert len(preview_response.content) < original_path.stat().st_size
        with Image.open(BytesIO(preview_response.content)) as preview_image:
            assert preview_image.size == (384, 288)
        assert client.get(preview_url, headers={
            "If-None-Match": preview_response.headers["etag"],
        }).status_code == 304
        Image.new("RGB", (1600, 1200), (120, 80, 40)).save(original_path)
        updated_preview = client.get(preview_url, headers={
            "If-None-Match": preview_response.headers["etag"],
        })
        assert updated_preview.status_code == 200
        assert updated_preview.headers["etag"] != preview_response.headers["etag"]
        assert client.get("/api/outputs/preview/anima/animation.gif").headers["content-type"] == "image/webp"
        assert client.get("/api/outputs/preview/anima/small-00.png").status_code == 422
        assert client.get("/api/outputs/preview/anima/movie.webm").status_code == 404
        assert client.get("/api/outputs/preview/../outside.png").status_code != 200
        assert client.get("/media/anima/large.png").content == original_path.read_bytes()
        assert sorted(path.name for path in image_directory.iterdir()) == [
            "animation.gif", "large.png", "movie.webm",
            *(f"small-{image_number:02d}.png" for image_number in range(25)),
        ]


def test_anima_request_count_submits_independent_single_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 횟수만큼 wildcard를 별도로 확장하고 한 장씩 ComfyUI에 제출합니다."""

    output_directory = tmp_path / "comfy_output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test-password", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    generation_seeds = iter([11, 21, 12, 22])

    def next_generation_seed(upper_bound: int) -> int:
        """wildcard와 sampling의 요청별 seed를 결정적으로 제공합니다."""

        return next(generation_seeds)

    fake_comfy = FakeComfyClient()

    async def resolve_test_wildcard(prompt: str, seed: int) -> str:
        """wildcard 확장 호출마다 사용한 seed를 최종 Prompt에 남깁니다."""

        fake_comfy.wildcard_prompts.append(prompt)
        return f"portrait choice {seed}" if prompt else ""

    monkeypatch.setattr("home_server.application.secrets.randbelow", next_generation_seed)
    monkeypatch.setattr(fake_comfy, "populate_wildcards", resolve_test_wildcard)
    app = create_app(config)
    app.state.home_server.comfy = fake_comfy

    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
        selected_tag_id = create_test_anima_tag(client, "subject")
        batch_response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prompt": "portrait {calm|happy}, [SCENE]"},
            "selected_tag_ids": [selected_tag_id],
            "count": 2, "settings": {"batch_size": 2, "width": 1280, "height": 720},
        })
        assert batch_response.status_code == 200
        request_ids = batch_response.json()["request_ids"]
        job_id = batch_response.json()["job_id"]
        assert len(set(request_ids)) == 2
        for attempt_index in range(30):
            jobs = client.get("/api/jobs").json()["items"]
            if len(jobs) == 1 and all(request["prompt_id"] for request in jobs[0]["requests"]):
                break
            time.sleep(0.05)

        assert len(fake_comfy.submissions) == 2
        assert jobs[0]["job_id"] == job_id
        assert jobs[0]["request_count"] == 2
        requests = jobs[0]["requests"]
        assert {request["prompt_id"] for request in requests} == {"prompt-1", "prompt-2"}
        assert fake_comfy.wildcard_prompts == ["portrait {calm|happy}, subject", ""] * 2
        for submission_index, (request_workflow, metadata) in enumerate(fake_comfy.submissions):
            wildcard_seed = 11 + submission_index
            assert request_workflow["13"]["inputs"]["path"] == "from_home_server/anima"
            assert request_workflow["13"]["inputs"]["filename"] == "%time_%seed"
            assert request_workflow["13"]["inputs"]["time_format"] == "%y%m%d_%H%M%S"
            assert request_workflow["51"]["inputs"]["value"] == 1
            assert request_workflow["45"]["inputs"]["value"] == 1280
            assert request_workflow["48"]["inputs"]["value"] == 720
            assert request_workflow["3"]["inputs"]["populated_text"] == f"portrait choice {wildcard_seed}"
            assert request_workflow["24"]["inputs"]["seed"] == 21 + submission_index
            assert metadata["home_server_request"]["wildcard_seed"] == wildcard_seed
            assert metadata["home_server_request"]["request_id"] == request_ids[submission_index]
            assert metadata["home_server_request"]["job_id"] == job_id
            assert "batch_size" not in metadata["home_server_request"]["settings"]
        assert all("batch_size" not in request["detail"]["settings"] for request in requests)
        assert all(request["detail"]["settings"]["width"] == 1280 for request in requests)
        assert all(request["detail"]["settings"]["height"] == 720 for request in requests)
        assert {request["output_stem"] for request in requests} == {"from_home_server/anima/%time_%seed"}

        result_directory = config.managed_output_directory / "anima"
        result_directory.mkdir(parents=True)
        for request_index in (1, 2):
            filename = f"result-{request_index}.png"
            (result_directory / filename).write_bytes(b"image")
            fake_comfy.history_records[f"prompt-{request_index}"] = {
                "status": {"status_str": "success"},
                "outputs": {"13": {"images": [{
                    "filename": filename, "subfolder": "from_home_server/anima", "type": "output",
                }]}},
            }
        completed_job = client.get("/api/jobs", params={"refresh": True}).json()["items"][0]
        assert completed_job["status"] == "completed"
        grouped_outputs = client.get("/api/outputs", params={"job_id": job_id}).json()
        assert {file["path"] for file in grouped_outputs["files"]} == {
            "anima/result-1.png", "anima/result-2.png",
        }
        assert client.get("/api/outputs", params={"request_id": request_ids[0]}).json()["total"] == 1


def test_minimax_batch_preserves_plain_prompt_for_each_image(tmp_path: Path) -> None:
    """MiniMax preset·미리보기·여러 이미지 제출에서 평문을 확장하지 않습니다."""

    output_directory = tmp_path / "comfy_output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test-password", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy
    plain_text = "[Scene]\n{camera|lighting}\n__literal__"

    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
        preset_response = client.post("/api/presets", json={
            "name": "MiniMax plain text", "workflow": "minimax_h3", "body": {"prompt": plain_text},
        })
        assert preset_response.status_code == 200
        assert preset_response.json()["body"] == {"prompt": plain_text}
        assert client.post("/api/presets", json={
            "name": "Invalid", "workflow": "minimax_h3", "body": {"prefix": plain_text},
        }).status_code == 422

        preview_response = client.post("/api/prompts/preview", json={
            "workflow": "minimax_h3", "body": {"prompt": plain_text}, "count": 5,
        })
        assert preview_response.status_code == 200
        assert preview_response.json()["combined_prompt"] == plain_text
        assert preview_response.json()["examples"][0]["prompt"] == plain_text
        assert fake_comfy.wildcard_prompts == []

        upload_ids = []
        for image_name in ("first.png", "second.png"):
            upload_response = client.post("/api/uploads", files={"file": (image_name, b"image", "image/png")})
            assert upload_response.status_code == 200
            upload_ids.append(upload_response.json()["upload_id"])

        batch_response = client.post("/api/batches", json={
            "workflow": "minimax_h3", "body": {"prompt": plain_text},
            "upload_ids": upload_ids, "settings": {}, "loras": [],
        })
        assert batch_response.status_code == 200
        assert len(batch_response.json()["request_ids"]) == 2
        for _ in range(30):
            if len(fake_comfy.submissions) == 2:
                break
            time.sleep(0.05)
        assert len(fake_comfy.submissions) == 2
        assert fake_comfy.wildcard_prompts == []
        for request_workflow, metadata in fake_comfy.submissions:
            director_inputs = request_workflow["2730"]["inputs"]
            assert director_inputs["prompt"] == plain_text
            assert director_inputs["external_prompt_overwrite"] == plain_text
            assert json.loads(director_inputs["timeline_data"])["resolved_prompt"] == plain_text
            assert metadata["home_server_request"]["prompt"] == plain_text


def test_job_groups_partial_results_from_independent_requests(tmp_path: Path) -> None:
    """한 요청이 실패해도 상위 작업에서 완료된 결과를 함께 조회합니다."""

    output_directory = tmp_path / "output"
    managed_directory = output_directory / "from_home_server"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        selected_tag_id = create_test_anima_tag(client)
        response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prompt": "portrait, [SCENE]"}, "count": 2,
            "selected_tag_ids": [selected_tag_id],
        }).json()
        for attempt_index in range(30):
            if len(fake_comfy.submissions) == 2:
                break
            time.sleep(0.05)
        assert len(fake_comfy.submissions) == 2

        result_path = managed_directory / "anima" / "result.png"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(b"result")
        (result_path.parent / "unrelated.png").write_bytes(b"unrelated")
        fake_comfy.history_records["prompt-1"] = {
            "status": {"status_str": "success"},
            "outputs": {"13": {"images": [{
                "filename": "result.png", "subfolder": "from_home_server/anima", "type": "output",
            }]}},
        }
        fake_comfy.history_records["prompt-2"] = {"status": {"status_str": "error"}, "outputs": {}}
        jobs = client.get("/api/jobs", params={"refresh": True}).json()["items"]
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == response["job_id"]
        assert jobs[0]["status"] == "partial"
        assert jobs[0]["status_counts"] == {"completed": 1, "failed": 1}
        assert [request["request_index"] for request in jobs[0]["requests"]] == [1, 2]
        assert client.get("/api/outputs", params={"job_id": response["job_id"]}).json()["files"][0]["path"] == "anima/result.png"
        assert client.get("/api/outputs", params={"job_id": response["job_id"]}).json()["total"] == 1
        assert client.get("/api/outputs", params={"request_id": response["request_ids"][1]}).json()["total"] == 0
        assert client.get("/api/outputs", params={"job_id": "missing"}).status_code == 404
        assert client.get("/api/outputs", params={"job_id": response["job_id"], "request_id": response["request_ids"][0]}).status_code == 422


def test_job_description_cancel_and_history_actions(tmp_path: Path) -> None:
    """설명·페이지 조회, 실행 중 취소, 두 삭제 방식과 이동 파일을 확인합니다."""

    output_directory = tmp_path / "output"
    managed_directory = output_directory / "from_home_server"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        selected_tag_id = create_test_anima_tag(client)
        batch = {"workflow": "anima", "body": {"prompt": "portrait, [SCENE]"}, "count": 2,
                 "selected_tag_ids": [selected_tag_id]}
        assert client.post("/api/batches", json={**batch, "description": "bad\nline"}).status_code == 422
        response = client.post("/api/batches", json={**batch, "description": "  조명 비교  "})
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        for attempt_index in range(30):
            job = app.state.home_server.database.get_job(job_id)
            if all(request["prompt_id"] for request in job["requests"]):
                break
            time.sleep(0.05)
        assert job["description"] == "조명 비교"
        assert len(fake_comfy.submissions) == 2
        fake_comfy.running_prompt_ids.add("prompt-1")
        jobs_page = client.get("/api/jobs", params={"page": 1, "page_size": 1, "refresh": True}).json()
        assert jobs_page["items"][0]["description"] == "조명 비교"
        assert jobs_page["active_count"] == 1
        assert client.delete(f"/api/jobs/{job_id}").status_code == 409
        cancel = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel.json() == {"cancelled_count": 2, "failed_count": 0}
        assert client.get("/api/jobs", params={"refresh": True}).json()["items"][0]["status"] == "cancelled"
        assert client.post(f"/api/requests/{response.json()['request_ids'][0]}/cancel").status_code == 409

        retained_file = managed_directory / "anima" / "retained.png"
        retained_file.parent.mkdir(parents=True)
        retained_file.write_bytes(b"retained")
        history_request_id = "history-request"
        database = app.state.home_server.database
        database.add_job("history-job", "anima", "이력만", [{
            "request_id": history_request_id, "status": "completed", "output_stem": "anima/example",
            "detail": {},
        }])
        database.complete_request(history_request_id, ["anima/retained.png"])
        filtered_jobs = client.get("/api/jobs", params={"job_id": "history-job"}).json()
        assert filtered_jobs["total"] == 1
        assert [job["job_id"] for job in filtered_jobs["items"]] == ["history-job"]
        assert client.get("/api/jobs", params={"job_id": "missing"}).json()["items"] == []
        history_delete = client.delete("/api/jobs/history-job")
        assert history_delete.json() == {"deleted": True, "deleted_files": 0, "missing_files": 0}
        assert retained_file.exists()

        removed_file = managed_directory / "anima" / "removed.png"
        removed_file.write_bytes(b"removed")
        moved_file = managed_directory / "sorted" / "moved.png"
        moved_file.parent.mkdir(parents=True)
        moved_file.write_bytes(b"moved")
        database.add_job("output-job", "anima", "파일 삭제", [{
            "request_id": "output-request", "status": "completed", "output_stem": "anima/example",
            "detail": {},
        }])
        database.complete_request("output-request", [
            "anima/removed.png", "anima/moved.png", "anima/retained.png",
        ])
        moved_file.write_bytes(b"moved")
        retained_file.unlink()
        file_delete = client.delete("/api/jobs/output-job", params={"delete_outputs": True})
        assert file_delete.json() == {"deleted": True, "deleted_files": 1, "missing_files": 2}
        assert not removed_file.exists()
        assert moved_file.exists()
        assert database.get_job("output-job") is None
        assert client.delete("/api/jobs/output-job").status_code == 404

    log_text = (tmp_path / "runtime" / "logs" / "home_server.log").read_text(encoding="utf-8")
    assert "원래 위치에 결과물 없음" in log_text


@pytest.mark.parametrize("workflow", ["anima", "minimax_h3"])
def test_saver_history_outputs_keep_native_names(tmp_path: Path, workflow: str) -> None:
    """실제 출력 참조로 작업 결과를 조회하며 Saver의 파일명을 그대로 유지합니다."""

    output_directory = tmp_path / "output"
    managed_directory = output_directory / "from_home_server"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        upload_ids = []
        if workflow == "minimax_h3":
            upload_response = client.post("/api/uploads", files={"file": ("input.png", b"image", "image/png")})
            upload_ids.append(upload_response.json()["upload_id"])
        body = {"prompt": "portrait, [SCENE]"} if workflow == "anima" else {"prompt": "quiet scene"}
        selected_tag_ids = [create_test_anima_tag(client)] if workflow == "anima" else []
        response = client.post("/api/batches", json={
            "workflow": workflow, "body": body, "upload_ids": upload_ids,
            "selected_tag_ids": selected_tag_ids,
            "settings": {"width": 768, "height": 1024},
        })
        assert response.status_code == 200
        request_id = response.json()["request_ids"][0]
        for attempt_index in range(30):
            job = client.get("/api/jobs").json()["items"][0]
            if job["requests"][0]["prompt_id"]:
                break
            time.sleep(0.05)
        assert job["requests"][0]["prompt_id"] == "prompt-1"
        assert client.get("/api/outputs", params={"request_id": request_id}).json()["files"] == []

        output_folder = managed_directory / workflow
        output_folder.mkdir(parents=True)
        filename = "261006_153012_123456.png" if workflow == "anima" else "261006_153012_123456_00001_audio.webm"
        original_file = output_folder / filename
        original_file.write_bytes(b"result")
        (output_folder / "unrelated.png").write_bytes(b"other result")
        output_kind = "images" if workflow == "anima" else "gifs"
        saver_identifier = "13" if workflow == "anima" else "2568"
        fake_comfy.history_records["prompt-1"] = {
            "status": {"status_str": "success"},
            "outputs": {saver_identifier: {output_kind: [
                {"filename": filename, "subfolder": f"from_home_server/{workflow}", "type": "output"},
                {"filename": "secret.png", "subfolder": "from_home_server/../outside", "type": "output"},
                {"filename": "preview.png", "subfolder": f"from_home_server/{workflow}", "type": "temp"},
            ]}},
        }
        completed_job = client.get("/api/jobs", params={"refresh": True}).json()["items"][0]
        assert completed_job["status"] == "completed"
        assert completed_job["requests"][0]["detail"]["resolved"]["output_paths"] == [f"{workflow}/{filename}"]
        fake_comfy.history_records.clear()
        outputs = client.get("/api/outputs", params={"request_id": request_id}).json()
        assert [result["path"] for result in outputs["files"]] == [f"{workflow}/{filename}"]
        assert outputs["files"][0]["job_id"] == completed_job["job_id"]
        assert (outputs["files"][0]["width"], outputs["files"][0]["height"]) == (768, 1024)
        assert outputs["files"][0]["dimensions_source"] == "settings"
        grouped_outputs = client.get("/api/outputs", params={"job_id": completed_job["job_id"]}).json()
        assert [result["path"] for result in grouped_outputs["files"]] == [f"{workflow}/{filename}"]
        all_outputs = client.get("/api/outputs").json()["files"]
        assert next(file for file in all_outputs if file["name"] == "unrelated.png")["job_id"] is None
        assert original_file.read_bytes() == b"result"
        original_file.unlink()
        assert client.get("/api/outputs", params={"request_id": request_id}).json()["total"] == 0


@pytest.mark.parametrize("delete_outputs", [False, True])
def test_job_protection_blocks_history_and_file_deletion_until_unlocked(tmp_path: Path, delete_outputs: bool) -> None:
    """삭제 보호는 인증된 API에서도 이력·파일 삭제를 막고 해제 후에만 허용합니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    application = create_app(config)
    application.state.home_server.comfy = FakeComfyClient()
    database = application.state.home_server.database
    database.add_job("protected-job", "anima", "test work", [{
        "request_id": "protected-request", "status": "completed", "output_stem": "anima/example", "detail": {},
    }])
    result_file = config.managed_output_directory / "anima" / "protected.png"
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(b"protected result")
    database.complete_request("protected-request", ["anima/protected.png"])

    with TestClient(application) as client:
        protection_endpoint = "/api/jobs/protected-job/protection"
        assert client.get("/api/jobs/deletion-candidates").status_code == 401
        assert client.patch(protection_endpoint, json={"deletion_protected": True}).status_code == 401
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        assert client.patch("/api/jobs/missing/protection", json={"deletion_protected": True}).status_code == 404
        assert client.patch(protection_endpoint, json={}).status_code == 422
        assert client.get("/api/jobs/deletion-candidates").json()["job_ids"] == ["protected-job"]
        protected_response = client.patch(protection_endpoint, json={"deletion_protected": True})
        assert protected_response.json() == {"job_id": "protected-job", "deletion_protected": True}
        assert client.get("/api/jobs").json()["items"][0]["deletion_protected"] is True
        assert Database(database.database_path).get_job("protected-job")["deletion_protected"] is True
        assert client.get("/api/jobs/deletion-candidates").json()["job_ids"] == []
        deletion_endpoint = f"/api/jobs/protected-job?delete_outputs={str(delete_outputs).lower()}"
        deletion_response = client.delete(deletion_endpoint)
        assert deletion_response.status_code == 409
        assert "삭제 보호" in deletion_response.json()["detail"]
        assert result_file.read_bytes() == b"protected result"
        assert database.get_job("protected-job") is not None
        assert client.patch(protection_endpoint, json={"deletion_protected": False}).status_code == 200
        assert client.get("/api/jobs/deletion-candidates").json()["job_ids"] == ["protected-job"]
        deletion_response = client.delete(deletion_endpoint)
        assert deletion_response.status_code == 200
        assert deletion_response.json()["deleted_files"] == int(delete_outputs)
        assert result_file.exists() is not delete_outputs
        assert database.get_job("protected-job") is None


def test_protection_changed_after_job_read_still_preserves_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """작업 조회 직후 보호가 설정되면 DB의 재검사로 파일 삭제도 차단합니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    application = create_app(config)
    application.state.home_server.comfy = FakeComfyClient()
    database = application.state.home_server.database
    database.add_job("racing-job", "anima", "", [{
        "request_id": "racing-request", "status": "completed", "output_stem": "anima/example", "detail": {},
    }])
    result_file = config.managed_output_directory / "anima" / "result.png"
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(b"retained")
    database.complete_request("racing-request", ["anima/result.png"])
    read_original_job = database.get_job

    def read_job_then_protect(job_identifier: str) -> dict | None:
        """응답 Snapshot을 얻은 직후 다른 요청의 보호 설정을 재현합니다."""

        original_snapshot = read_original_job(job_identifier)
        database.set_job_deletion_protection(job_identifier, True)
        return original_snapshot

    monkeypatch.setattr(database, "get_job", read_job_then_protect)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        response = client.delete("/api/jobs/racing-job?delete_outputs=true")
        assert response.status_code == 409
        assert "삭제 보호" in response.json()["detail"]
        assert result_file.read_bytes() == b"retained"
        assert read_original_job("racing-job")["deletion_protected"] is True


def test_negative_tags_are_validated_previewed_and_submitted_as_fixed_text(tmp_path: Path) -> None:
    """Negative 전용 중첩 참조와 wildcard를 확정하고 오류는 ComfyUI 제출 전에 거부합니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()

    async def resolve_test_wildcards(prompt: str, seed: int) -> str:
        """태그 확정 뒤 전달된 wildcard 본문을 기록하고 테스트용 문구 하나로 치환합니다."""

        fake_comfy.wildcard_prompts.append(prompt)
        return prompt.replace("{blur|noise}", "blur")

    fake_comfy.populate_wildcards = resolve_test_wildcards
    app.state.home_server.comfy = fake_comfy
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        selected_tags = []
        for reference_key, content in (("AVOID", "[BAD_DETAIL]"), ("BAD_DETAIL", "bad hands, {blur|noise}")):
            group = client.post("/api/tags/groups", json={"name": reference_key, "tag_key": reference_key}).json()
            tag = client.post("/api/tags/entries", json={
                "group_id": group["group_id"], "name": reference_key, "content": content,
            }).json()
            selected_tags.append(tag)
        body = {"prompt": "portrait", "negative": "lowres, [AVOID]"}
        selected_ids = [tag["tag_id"] for tag in selected_tags]
        for selected_subset, missing_key in (([], "AVOID"), (selected_ids[:1], "BAD_DETAIL")):
            for endpoint in ("/api/prompts/preview", "/api/batches"):
                rejected = client.post(endpoint, json={
                    "workflow": "anima", "body": body, "selected_tag_ids": selected_subset,
                })
                assert rejected.status_code == 422
                assert missing_key in rejected.json()["detail"]
        assert fake_comfy.submissions == []
        assert fake_comfy.wildcard_prompts == []
        assert client.get("/api/jobs").json()["total"] == 0
        for endpoint in ("/api/prompts/preview", "/api/batches"):
            assert client.post(endpoint, json={
                "workflow": "anima", "body": {"prompt": "portrait", "negative": None},
            }).status_code == 422

        preview_response = client.post("/api/prompts/preview", json={
            "workflow": "anima", "body": body, "selected_tag_ids": selected_ids, "count": 1,
        })
        assert preview_response.status_code == 200
        example = preview_response.json()["examples"][0]
        assert example["prompt"] == "portrait"
        assert example["negative"] == "lowres, bad hands, blur"
        assert example["selected_path"] == []
        assert [item["tag_key"] for item in example["negative_selected_path"]] == ["AVOID", "BAD_DETAIL"]
        assert fake_comfy.wildcard_prompts == ["portrait", "lowres, bad hands, {blur|noise}"]

        submission_response = client.post("/api/batches", json={
            "workflow": "anima", "body": body, "selected_tag_ids": selected_ids, "count": 1,
        })
        assert submission_response.status_code == 200
        for attempt_index in range(30):
            job = app.state.home_server.database.get_job(submission_response.json()["job_id"])
            if job["requests"][0]["prompt_id"]:
                break
            time.sleep(0.05)
        request_detail = job["requests"][0]["detail"]
        assert request_detail["body"]["negative"] == "lowres, [AVOID]"
        assert request_detail["resolved"]["negative"] == example["negative"]
        assert request_detail["resolved"]["negative_selected_path"] == example["negative_selected_path"]
        submitted_workflow, metadata = fake_comfy.submissions[0]
        assert submitted_workflow["4"]["inputs"]["populated_text"] == example["negative"]
        assert submitted_workflow["4"]["inputs"]["mode"] == "fixed"
        assert metadata["home_server_request"]["negative"] == example["negative"]
        assert metadata["home_server_request"]["negative_selected_path"] == example["negative_selected_path"]

        cycle_tag = selected_tags[1]
        assert client.put(f"/api/tags/entries/{cycle_tag['tag_id']}", json={
            "group_id": cycle_tag["group_id"], "name": "BAD_DETAIL", "content": "[AVOID]",
        }).status_code == 200
        for endpoint in ("/api/prompts/preview", "/api/batches"):
            rejected = client.post(endpoint, json={
                "workflow": "anima", "body": body, "selected_tag_ids": selected_ids,
            })
            assert rejected.status_code == 422
            assert "cycle" in rejected.json()["detail"]
        assert len(fake_comfy.submissions) == 1
        assert client.get("/api/jobs").json()["total"] == 1


def test_shared_group_references_update_candidates_and_preserve_snapshots(tmp_path: Path) -> None:
    """동일 참조의 여러 그룹을 추첨하고 그룹 편집과 항목 이동 시 현재 후보만 갱신합니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    app.state.home_server.comfy = FakeComfyClient()
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/tags/groups", json={"name": "참조 없음"}).status_code == 422
        groups = []
        for group_name in ("첫 캐릭터 그룹", "둘째 캐릭터 그룹"):
            response = client.post("/api/tags/groups", json={"name": group_name, "tag_key": "CHR"})
            assert response.status_code == 201
            groups.append(response.json())
        entries = []
        for group_index, entry_name in ((0, "A"), (0, "B"), (1, "C")):
            response = client.post("/api/tags/entries", json={
                "group_id": groups[group_index]["group_id"], "name": entry_name,
                "content": f"character {entry_name}", "weight": 1,
                "tag_key": "IGNORED_ENTRY_KEY",
            })
            assert response.status_code == 201
            assert "tag_key" not in response.json()
            entries.append(response.json())

        catalog = client.get("/api/tags").json()
        assert [group["tag_key"] for group in catalog["groups"]] == ["CHR", "CHR"]
        assert all("tag_key" not in entry for entry in catalog["entries"])
        selected_ids = [entry["tag_id"] for entry in entries]
        database = app.state.home_server.database
        selected_definitions = selected_tag_definitions(database, selected_ids, "[CHR]")
        assert all(definition["tag_key"] == "CHR" for definition in selected_definitions)
        assert {resolve_tag_prompt({"prompt": "[CHR]"}, selected_definitions, seed)[0] for seed in range(100)} == {
            "character A", "character B", "character C",
        }
        database.add_job("group-snapshot", "anima", "그룹 편집 전", [{
            "request_id": "group-snapshot-request", "status": "completed", "output_stem": "anima/example",
            "detail": {"selected_tags": selected_definitions},
        }])

        update_response = client.put(f"/api/tags/groups/{groups[0]['group_id']}", json={
            "name": groups[0]["name"], "tag_key": "PEOPLE", "default_expanded": False,
        })
        assert update_response.status_code == 200
        current_definitions = selected_tag_definitions(database, selected_ids, "[CHR] [PEOPLE]")
        assert [definition["tag_key"] for definition in current_definitions] == ["PEOPLE", "PEOPLE", "CHR"]
        assert resolve_tag_prompt({"prompt": "[CHR]"}, current_definitions, 1)[0] == "character C"
        historical_tags = database.get_job("group-snapshot")["requests"][0]["detail"]["selected_tags"]
        assert historical_tags == selected_definitions

        moved_entry = client.put(f"/api/tags/entries/{entries[0]['tag_id']}", json={
            "group_id": groups[1]["group_id"], "name": "A", "content": "character A", "weight": 3,
        })
        assert moved_entry.status_code == 200
        moved_definitions = selected_tag_definitions(database, selected_ids, "[CHR] [PEOPLE]")
        assert [definition["tag_key"] for definition in moved_definitions] == ["CHR", "PEOPLE", "CHR"]
        preview_response = client.post("/api/prompts/preview", json={
            "workflow": "anima", "body": {"prompt": "[CHR]"}, "selected_tag_ids": selected_ids, "count": 5,
        })
        assert preview_response.status_code == 200
        assert all(example["prompt"] in {"character A", "character C"} for example in preview_response.json()["examples"])


def test_tag_api_previews_and_submits_snapshot_before_comfy_queue(tmp_path: Path) -> None:
    """태그 그룹과 항목을 저장하고 확정 Prompt 및 선택 경로를 작업에 남깁니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    fake_comfy = FakeComfyClient()
    app.state.home_server.comfy = fake_comfy

    with TestClient(app) as client:
        assert client.get("/api/tags").status_code == 401
        client.post("/api/login", json={"password": "test"})
        action_group = client.post("/api/tags/groups", json={
            "name": "장면", "tag_key": "ACTION", "default_expanded": True,
        }).json()
        character_group = client.post("/api/tags/groups", json={
            "name": "캐릭터", "tag_key": "CHR", "default_expanded": False,
        }).json()
        assert character_group["default_expanded"] is False
        assert client.delete(f"/api/tags/groups/{action_group['group_id']}").status_code == 200
        action_group = client.post("/api/tags/groups", json={"name": "장면", "tag_key": "ACTION"}).json()
        pair_group = client.post("/api/tags/groups", json={"name": "구성", "tag_key": "TWOCHR"}).json()

        def create_tag(group_id: str, name: str, content: str) -> dict:
            """테스트에서 사용할 태그 항목을 API로 저장합니다."""

            response = client.post("/api/tags/entries", json={
                "group_id": group_id, "name": name,
                "content": content, "weight": 1,
            })
            assert response.status_code == 201
            return response.json()

        action_tag = create_tag(action_group["group_id"], "싸움", "[TWOCHR], fight")
        pair_tag = create_tag(pair_group["group_id"], "두 사람", "[CHR] and [CHR]")
        character_tag = create_tag(character_group["group_id"], "A", "character A")
        selected_ids = [action_tag["tag_id"], pair_tag["tag_id"], character_tag["tag_id"]]
        assert client.delete(f"/api/tags/groups/{character_group['group_id']}").status_code == 409
        assert client.post("/api/tags/groups", json={
            "name": "잘못됨", "tag_key": "bad-key",
        }).status_code == 422

        body = {"prompt": "quality, [ACTION]"}
        missing_action = client.post("/api/batches", json={
            "workflow": "anima", "body": body, "selected_tag_ids": [],
        })
        assert missing_action.status_code == 422
        assert "[ACTION]" in missing_action.json()["detail"]
        missing_character = client.post("/api/batches", json={
            "workflow": "anima", "body": body,
            "selected_tag_ids": [action_tag["tag_id"], pair_tag["tag_id"]],
        })
        assert missing_character.status_code == 422
        assert "[CHR]" in missing_character.json()["detail"]
        preview = client.post("/api/prompts/preview", json={
            "workflow": "anima", "body": body,
            "selected_tag_ids": selected_ids, "count": 1,
        })
        assert preview.status_code == 200
        example = preview.json()["examples"][0]
        assert example["prompt"] == "quality, character A and character A, fight"
        assert [item["name"] for item in example["selected_path"]] == ["싸움", "두 사람", "A", "A"]

        response = client.post("/api/batches", json={
            "workflow": "anima", "body": body,
            "selected_tag_ids": selected_ids, "count": 1,
        })
        assert response.status_code == 200
        for _ in range(30):
            job = app.state.home_server.database.get_job(response.json()["job_id"])
            if job["requests"][0]["prompt_id"]:
                break
            time.sleep(0.05)
        request = job["requests"][0]
        assert request["detail"]["selected_tags"][2]["content"] == "character A"
        assert request["detail"]["resolved"]["prompt"] == example["prompt"]
        assert len(request["detail"]["resolved"]["selected_path"]) == 4
        assert fake_comfy.submissions[0][0]["3"]["inputs"]["mode"] == "fixed"
        assert fake_comfy.submissions[0][0]["3"]["inputs"]["populated_text"] == example["prompt"]

        saved_preset = client.post("/api/presets", json={
            "name": "태그 버전", "workflow": "anima",
            "body": {**body, "prefix": "obsolete", "selected_tag_ids": selected_ids},
        })
        assert saved_preset.status_code == 200
        saved_body = saved_preset.json()["body"]
        assert saved_body == {**body, "negative": ""}

        assert client.put(f"/api/tags/entries/{character_tag['tag_id']}", json={
            "group_id": character_group["group_id"],
            "name": "A", "content": "character B", "weight": 1,
        }).status_code == 200
        assert app.state.home_server.database.get_job(response.json()["job_id"])["requests"][0]["detail"]["selected_tags"][2]["content"] == "character A"
        historical_preview = client.post("/api/prompts/preview", json={
            "workflow": "anima", "body": saved_body,
            "selected_tag_ids": selected_ids, "count": 1,
        })
        assert historical_preview.json()["examples"][0]["prompt"] == "quality, character B and character B, fight"
        saved_again = client.post("/api/presets", json={
            "preset_id": saved_preset.json()["preset_id"], "name": "태그 버전",
            "workflow": "anima", "body": saved_body,
        })
        assert saved_again.status_code == 200
        assert saved_again.json()["version"] == 2
        assert saved_again.json()["body"] == saved_body
        current_preview = client.post("/api/prompts/preview", json={
            "workflow": "anima", "body": body,
            "selected_tag_ids": selected_ids, "count": 1,
        })
        assert "character B" in current_preview.json()["examples"][0]["prompt"]

        assert client.put(f"/api/tags/entries/{pair_tag['tag_id']}", json={
            "group_id": pair_group["group_id"],
            "name": "두 사람", "content": "[ACTION]", "weight": 1,
        }).status_code == 200
        rejected = client.post("/api/batches", json={
            "workflow": "anima", "body": body,
            "selected_tag_ids": selected_ids,
        })
        assert rejected.status_code == 422
        assert "cycle" in rejected.json()["detail"]
        assert client.get("/api/jobs").json()["total"] == 1
