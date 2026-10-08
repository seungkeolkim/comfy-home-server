"""LoRA 조합의 인증, snapshot 보존, 저장 검증과 실제 제출 입력을 확인합니다."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from home_server.application import create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from home_server.database import Database


class LoraPresetComfyClient:
    """실제 생성 없이 LoRA 목록과 접수한 workflow를 기록합니다."""

    def __init__(self) -> None:
        """사용 가능한 파일과 제출 기록을 준비합니다."""

        self.available_loras = ["first.safetensors", "second.safetensors"]
        self.submissions = []
        self.connected = True

    async def close(self) -> None:
        """가짜 client에는 종료할 연결이 없습니다."""

    async def list_loras(self) -> list[str]:
        """테스트에서 변경할 수 있는 현재 파일 목록을 반환합니다."""

        if not self.connected:
            raise RuntimeError("ComfyUI is offline")
        return self.available_loras

    async def populate_wildcards(self, prompt: str, seed: int) -> str:
        """LoRA 검증에서는 Prompt를 그대로 전달합니다."""

        return prompt

    async def submit(self, workflow: dict, metadata: dict) -> str:
        """적용된 LoRA 강도를 검증할 수 있도록 제출 내용을 보관합니다."""

        self.submissions.append(workflow)
        return f"prompt-{len(self.submissions)}"

    async def queue(self) -> dict:
        """접수한 요청을 대기 상태로 유지합니다."""

        return {"queue_running": [], "queue_pending": [[0, f"prompt-{index}"] for index in range(1, len(self.submissions) + 1)]}


@pytest.fixture
def lora_preset_client(tmp_path: Path) -> Iterator[tuple[TestClient, FastAPI, LoraPresetComfyClient]]:
    """독립된 DB와 가짜 ComfyUI를 사용하는 API client를 제공합니다."""

    output_directory = tmp_path / "output"
    config = AppConfig(
        host="127.0.0.1", port=8388, password="test-password", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory,
        managed_output_directory=output_directory / "from_home_server",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
    application = create_app(config)
    comfy_client = LoraPresetComfyClient()
    application.state.home_server.comfy = comfy_client
    with TestClient(application) as client:
        yield client, application, comfy_client


def test_lora_preset_crud_keeps_snapshots_independent(lora_preset_client) -> None:
    """조합의 생성·수정·삭제와 개별 기본값 독립성 및 DB 재연결 보존을 검증합니다."""

    client, application, comfy_client = lora_preset_client
    preset_payload = {
        "name": "  Portrait  ", "workflow": "anima",
        "loras": [
            {"name": "first.safetensors", "strength": 0.65, "clip_strength": 0.4},
            {"name": "second.safetensors", "strength": -0.2, "clip_strength": 0},
        ],
    }
    assert client.get("/api/loras/presets").status_code == 401
    assert client.post("/api/loras/presets", json=preset_payload).status_code == 401
    assert client.put("/api/loras/presets/missing", json=preset_payload).status_code == 401
    assert client.delete("/api/loras/presets/missing").status_code == 401
    client.post("/api/login", json={"password": "test-password"})

    created_response = client.post("/api/loras/presets", json=preset_payload)
    assert created_response.status_code == 201
    original_preset = created_response.json()
    assert original_preset["name"] == "Portrait"
    assert original_preset["loras"] == preset_payload["loras"]
    original_identifier = original_preset["preset_id"]
    assert client.post("/api/loras/profiles", json={
        "name": "first.safetensors", "workflow": "anima", "strength": 0.95, "clip_strength": 0.9,
    }).status_code == 200
    assert client.get("/api/loras/presets").json()[0]["loras"][0]["strength"] == 0.65

    preset_payload["name"] = "Portrait variant"
    preset_payload["loras"][0]["strength"] = 0.8
    copied_preset = client.post("/api/loras/presets", json=preset_payload).json()
    assert copied_preset["preset_id"] != original_identifier
    stored_presets = {preset["preset_id"]: preset for preset in client.get("/api/loras/presets").json()}
    assert stored_presets[original_identifier]["loras"][0]["strength"] == 0.65
    assert client.put(f"/api/loras/presets/{original_identifier}", json=preset_payload).json()["loras"][0]["strength"] == 0.8
    assert client.put("/api/loras/presets/missing", json=preset_payload).status_code == 404

    reconnected_database = Database(application.state.home_server.database.database_path)
    assert len(reconnected_database.list_lora_presets()) == 2
    comfy_client.available_loras = []
    comfy_client.connected = False
    assert client.get("/api/loras").status_code == 502
    assert len(client.get("/api/loras/presets").json()) == 2
    assert client.put(f"/api/loras/presets/{original_identifier}", json=preset_payload).status_code == 200
    assert client.delete(f"/api/loras/presets/{original_identifier}").status_code == 200
    assert client.delete(f"/api/loras/presets/{original_identifier}").status_code == 404
    assert len(client.get("/api/loras/presets").json()) == 1


@pytest.mark.parametrize("invalid_payload", [
    {"name": "   ", "workflow": "anima", "loras": [{"name": "first.safetensors"}]},
    {"name": "Invalid", "workflow": "unknown", "loras": [{"name": "first.safetensors"}]},
    {"name": "Invalid", "workflow": "anima", "loras": []},
    {"name": "Invalid", "workflow": "anima", "loras": [{"name": "   "}]},
    {"name": "Invalid", "workflow": "anima", "loras": [{"name": "first.safetensors", "strength": "NaN"}]},
    {"name": "Invalid", "workflow": "anima", "loras": [{"name": "first.safetensors", "clip_strength": "Infinity"}]},
    {"name": "Invalid", "workflow": "anima", "loras": [{"name": "first.safetensors"}, {"name": "first.safetensors"}]},
    {"name": "Invalid", "workflow": "minimax_h3", "loras": [{"name": f"lora-{index}.safetensors"} for index in range(11)]},
])
def test_lora_preset_rejects_invalid_combinations(lora_preset_client, invalid_payload: dict) -> None:
    """빈 조합·중복·잘못된 강도·지원하지 않는 workflow를 저장 전에 거부합니다."""

    client, application, comfy_client = lora_preset_client
    client.post("/api/login", json={"password": "test-password"})
    assert client.post("/api/loras/presets", json=invalid_payload).status_code == 422
    assert client.get("/api/loras/presets").json() == []


def test_lora_presets_keep_workflow_weights_and_submit_snapshot(lora_preset_client) -> None:
    """Workflow별 강도를 보존하고 저장된 Anima 조합을 실제 adapter 입력에 적용합니다."""

    client, application, comfy_client = lora_preset_client
    client.post("/api/login", json={"password": "test-password"})
    minimax_preset = client.post("/api/loras/presets", json={
        "name": "Motion", "workflow": "minimax_h3",
        "loras": [{"name": "first.safetensors", "strength": 0.7, "video_strength": 0.8, "audio_strength": 0}],
    }).json()
    assert minimax_preset["loras"] == [{"name": "first.safetensors", "strength": 0.7, "video_strength": 0.8, "audio_strength": 0}]
    anima_preset = client.post("/api/loras/presets", json={
        "name": "Portrait", "workflow": "anima",
        "loras": [{"name": "second.safetensors", "strength": 0.6, "clip_strength": 0.35}],
    }).json()
    tag_group = client.post("/api/tags/groups", json={"name": "Scenes"}).json()
    scene_tag = client.post("/api/tags/entries", json={
        "group_id": tag_group["group_id"], "tag_key": "SCENE", "name": "Portrait",
        "content": "subject", "weight": 1,
    }).json()
    response = client.post("/api/batches", json={
        "workflow": "anima", "body": {"prompt": "portrait, [SCENE]"}, "count": 1, "loras": anima_preset["loras"],
        "selected_tag_ids": [scene_tag["tag_id"]],
    })
    assert response.status_code == 200
    for attempt_index in range(30):
        if comfy_client.submissions:
            break
        time.sleep(0.05)
    applied_lora = comfy_client.submissions[0]["5"]["inputs"]["loras"]["__value__"][0]
    assert applied_lora["name"] == "second.safetensors"
    assert applied_lora["strength"] == 0.6
    assert applied_lora["clipStrength"] == 0.35
    comfy_client.available_loras = []
    assert client.post("/api/batches", json={
        "workflow": "anima", "body": {"prompt": "portrait, [SCENE]"}, "loras": anima_preset["loras"],
        "selected_tag_ids": [scene_tag["tag_id"]],
    }).status_code == 422
