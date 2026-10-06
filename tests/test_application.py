"""인증과 모델별 Prompt, 파일 경계, 제출 상태 API를 검증합니다."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.application import _normalize_single_output, create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY


class FakeComfyClient:
    """실제 GPU 작업 없이 ComfyUI queue 응답을 흉내 냅니다."""

    def __init__(self) -> None:
        """접수한 Prompt와 대기열을 초기화합니다."""

        self.submissions = []
        self.wildcard_prompts = []

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

        return {"queue_running": [], "queue_pending": [[0, f"prompt-{index}"] for index in range(1, len(self.submissions) + 1)]}

    async def history(self, prompt_id: str) -> dict:
        """완료 기록이 없음을 반환합니다."""

        return {}

    async def cancel_pending(self, prompt_id: str) -> None:
        """대기 요청 취소 동작을 흉내 냅니다."""

        return None


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

        preset_response = client.post("/api/presets", json={
            "name": "Test", "workflow": "anima", "body": {"prefix": "a portrait", "scenarios": []},
        })
        assert preset_response.status_code == 200
        assert preset_response.json()["version"] == 1
        second_version = client.post("/api/presets", json={
            "preset_id": preset_response.json()["preset_id"], "name": "Test", "workflow": "anima",
            "body": {"prefix": "a different portrait", "scenarios": []},
        })
        assert second_version.json()["version"] == 2
        versions = client.get(f"/api/presets/{preset_response.json()['preset_id']}/versions").json()
        assert [version["version"] for version in versions] == [2, 1]

        batch_response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prefix": "a portrait", "scenarios": []},
            "count": 1, "settings": {"width": 512, "height": 512}, "loras": [],
        })
        assert batch_response.status_code == 200
        request_id = batch_response.json()["request_ids"][0]
        for _ in range(30):
            jobs = client.get("/api/jobs").json()
            if jobs[0]["prompt_id"]:
                break
            time.sleep(0.05)
        assert jobs[0]["request_id"] == request_id
        assert jobs[0]["prompt_id"] == "prompt-1"
        assert fake_comfy.submissions[0][0]["13"]["inputs"]["path"].startswith("from_home_server/anima/")
        assert client.post(f"/api/jobs/{request_id}/cancel").json()["status"] == "cancelled"

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
    assert "작업 접수" in log_text
    assert "test-password" not in log_text
    assert "a portrait" not in log_text


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
        batch_response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prefix": "portrait {calm|happy}", "scenarios": []},
            "count": 2, "settings": {"batch_size": 2},
        })
        assert batch_response.status_code == 200
        request_ids = batch_response.json()["request_ids"]
        assert len(set(request_ids)) == 2
        for attempt_index in range(30):
            jobs = client.get("/api/jobs").json()
            if len(jobs) == 2 and all(job["prompt_id"] for job in jobs):
                break
            time.sleep(0.05)

        assert len(fake_comfy.submissions) == 2
        assert {job["prompt_id"] for job in jobs} == {"prompt-1", "prompt-2"}
        assert fake_comfy.wildcard_prompts == ["portrait {calm|happy}", ""] * 2
        for submission_index, (request_workflow, metadata) in enumerate(fake_comfy.submissions):
            wildcard_seed = 11 + submission_index
            assert request_workflow["51"]["inputs"]["value"] == 1
            assert request_workflow["3"]["inputs"]["populated_text"] == f"portrait choice {wildcard_seed}"
            assert request_workflow["24"]["inputs"]["seed"] == 21 + submission_index
            assert metadata["home_server_request"]["wildcard_seed"] == wildcard_seed
            assert metadata["home_server_request"]["request_id"] == request_ids[submission_index]
            assert "batch_size" not in metadata["home_server_request"]["settings"]
        assert all("batch_size" not in job["detail"]["settings"] for job in jobs)


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
            "selected_scenario_ids": [], "upload_ids": upload_ids, "settings": {}, "loras": [],
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


def test_single_video_output_uses_common_request_name(tmp_path: Path) -> None:
    """MiniMax saver의 자동 접미사를 단일 결과물에서만 제거합니다."""

    output_directory = tmp_path / "output"
    managed_directory = output_directory / "from_home_server"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=managed_directory,
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    app = create_app(config)
    output_folder = managed_directory / "minimax_h3" / "2026-10-06" / "batch123"
    output_folder.mkdir(parents=True)
    original_file = output_folder / "request123_00001_audio.webm"
    original_file.write_bytes(b"video")
    _normalize_single_output(app.state.home_server, {
        "output_stem": "from_home_server/minimax_h3/2026-10-06/batch123/request123",
    })
    assert not original_file.exists()
    assert (output_folder / "request123.webm").read_bytes() == b"video"
