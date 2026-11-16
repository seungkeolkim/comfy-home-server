"""스타일 생성→LoRA 등록→일반 생성의 실제 Workflow에 같은 CLIP 1을 검증합니다."""

import copy
import time

import pytest

from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_lora_presets import candidate_registration_endpoint


@pytest.mark.parametrize("requested_clip_strength", [None, 0, 0.6, 1])
def test_style_generation_and_registered_preset_keep_str_and_fix_clip(tmp_path, requested_clip_strength):
    """CLIP 생략·구형 입력에 관계없이 STR 0.4/0.8과 CLIP 1을 두 생성 경로에 전달합니다."""

    fake_client = StyleComfyClient()
    _, client, project, payload = prepare_style_generation(tmp_path, fake_client)
    try:
        for combination in payload["combinations"]:
            for component in combination["components"]:
                if not component["identifier"].startswith("lora:"):
                    continue
                component.pop("clip_strength", None)
                if requested_clip_strength is not None:
                    component["clip_strength"] = requested_clip_strength
        original_payload = copy.deepcopy(payload)
        plan, _, original_results = submit_and_wait(client, project, payload)
        assert payload == original_payload
        assert plan["selection"]["loraStrengthPolicy"] == "style-lora-fixed-clip-v1"
        assert plan["selection"]["loraClipStrength"] == 1
        planned_strengths = []
        for candidate in plan["candidates"]:
            for component in candidate["components"]:
                if component["identifier"].startswith("lora:"):
                    planned_strengths.append(component["strength"])
                    assert component["clip_strength"] == 1
                else:
                    assert "clip_strength" not in component
        assert planned_strengths == [0.4, 0.8]
        for workflow, metadata in fake_client.submissions:
            loaded_lora = workflow["5"]["inputs"]["loras"]["__value__"][0]
            assert loaded_lora["strength"] in planned_strengths
            assert loaded_lora["clipStrength"] == 1
            assert metadata["home_server_request"]["loras"][0]["clip_strength"] == 1

        candidate = plan["candidates"][0]
        response = client.put(candidate_registration_endpoint(project, candidate), json={"isRegistered": True})
        assert response.status_code == 200, response.text
        preset = client.get("/api/loras/presets").json()[0]
        assert preset["loras"] == [{"name": "example.safetensors", "strength": 0.4, "clip_strength": 1}]
        before_general_count = len(fake_client.submissions)
        response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prompt": "portrait"}, "count": 1,
            "settings": {"width": 64, "height": 96, "steps": 3, "cfg": 1},
            "loras": preset["loras"], "lora_preset_id": preset["preset_id"],
        })
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 10
        while len(fake_client.submissions) == before_general_count and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(fake_client.submissions) == before_general_count + 1
        general_lora = fake_client.submissions[-1][0]["5"]["inputs"]["loras"]["__value__"][0]
        assert general_lora["strength"] == 0.4
        assert general_lora["clipStrength"] == 1
        results = client.get(f"/api/style-projects/{project['identifier']}/generation-results").json()
        assert [candidate["components"] for candidate in results["candidates"]] == [candidate["components"] for candidate in original_results["candidates"]]
    finally:
        client.__exit__(None, None, None)
