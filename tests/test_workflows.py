"""두 workflow에 요청 값이 올바른 위치로 들어가는지 확인합니다."""

import json
from pathlib import Path

import pytest

from home_server.configuration import PROJECT_DIRECTORY
from home_server.prompt_builder import choose_scenario, compile_prompt
from home_server.workflows import WORKFLOW_OUTPUT_NAMES, load_workflows, prepare_anima, prepare_minimax


WORKFLOW_DIRECTORY = PROJECT_DIRECTORY / "data" / "workflows"
OUTPUT_STEM = f"from_home_server/anima/{WORKFLOW_OUTPUT_NAMES['anima']}"


def test_prompt_builder_keeps_situations_together() -> None:
    """중첩 wildcard가 다른 상황의 필드를 서로 섞지 않는지 확인합니다."""

    body = {"prefix": "quality", "separator": ", ", "scenarios": [
        {"id": "a", "name": "A", "characters": "person A", "situation": "indoors", "emotion": "calm"},
        {"id": "b", "name": "B", "characters": "person B", "situation": "outdoors", "emotion": "happy"},
    ]}
    combined = compile_prompt(body, ["a", "b"])
    assert "{person A, indoors, calm|person B, outdoors, happy}" in combined
    assert choose_scenario(body, ["a"], 12)["id"] == "a"


def test_anima_adapter_sets_prompt_lora_and_output() -> None:
    """Anima의 실제 실행 입력과 drag and drop metadata를 함께 수정합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    request, metadata = prepare_anima(
        api_workflow, ui_workflow, "a calm portrait", "blurry",
        {"width": 768, "height": 1024, "seed": 77, "steps": 8, "cfg": 1.2, "batch_size": 2},
        [{"name": "example.safetensors", "strength": 0.7, "clip_strength": 0.5}], OUTPUT_STEM,
    )
    assert request["3"]["inputs"]["populated_text"] == "a calm portrait"
    assert request["3"]["inputs"]["mode"] == "fixed"
    assert request["4"]["inputs"]["populated_text"] == "blurry"
    assert request["51"]["inputs"]["value"] == 1
    assert any(str(node["id"]) == "51" and node["widgets_values_named"]["value"] == 1 for node in metadata["nodes"])
    assert request["5"]["inputs"]["loras"]["__value__"][0]["clipStrength"] == 0.5
    assert request["13"]["inputs"]["path"] == "from_home_server/anima"
    assert request["13"]["inputs"]["filename"] == "%time_%seed"
    assert request["13"]["inputs"]["time_format"] == "%y%m%d_%H%M%S"
    assert request["57"]["inputs"]["seed_value"] == ["24", 0]
    assert any(node.get("widgets_values_named", {}).get("filename") == "%time_%seed" for node in metadata["nodes"])


def test_minimax_adapter_sets_timeline_and_output() -> None:
    """MiniMax의 첫·마지막 이미지와 LoRA, 저장 위치를 검증합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "minimax_h3")
    request, metadata = prepare_minimax(
        api_workflow, ui_workflow, "from_home_server/input.png", "quiet scene",
        {"width": 721, "height": 721, "duration": 8, "frame_rate": 24, "upscale_mode": "off"},
        [{"name": "motion.safetensors", "strength": 0.6, "video_strength": 1, "audio_strength": 0}],
        f"from_home_server/minimax_h3/{WORKFLOW_OUTPUT_NAMES['minimax_h3']}",
    )
    director = request["2730"]["inputs"]
    timeline = json.loads(director["timeline_data"])
    assert (director["width"], director["height"]) == (736, 736)
    assert [item["value"] for item in timeline["items"]] == ["from_home_server/input.png"] * 2
    assert timeline["resolved_prompt"] == "quiet scene"
    assert json.loads(request["2678"]["inputs"]["stack_data"])[0]["as"] == 0
    expected_output_stem = f"from_home_server/minimax_h3/{WORKFLOW_OUTPUT_NAMES['minimax_h3']}"
    assert request["2568"]["inputs"]["filename_prefix"] == expected_output_stem
    assert request["2568"]["inputs"]["seed"] == ["2739", 0]
    assert request["1512:2591"]["inputs"]["noise"] == ["2739", 1]
    seed_links = [link for link in metadata["links"] if link[1] == 2739 and link[2] == 0 and link[3] == 2568]
    assert len(seed_links) == 1
    saver_node = next(node for node in metadata["nodes"] if node["id"] == 2568)
    assert next(node_input for node_input in saver_node["inputs"] if node_input["name"] == "seed")["link"] == seed_links[0][0]
    assert any(node.get("widgets_values_named", {}).get("filename_prefix") == expected_output_stem for node in metadata["nodes"])


def test_adapter_rejects_output_path_escape() -> None:
    """요청 값으로 앱 output 밖의 저장 경로를 만들 수 없게 합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    with pytest.raises(ValueError):
        prepare_anima(api_workflow, ui_workflow, "test", "", {}, [], "from_home_server/../outside")
