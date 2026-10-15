"""두 workflow에 요청 값이 올바른 위치로 들어가는지 확인합니다."""

import copy
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from home_server.configuration import PROJECT_DIRECTORY
from home_server.workflows import WORKFLOW_OUTPUT_NAMES, load_workflows, prepare_anima, prepare_minimax


WORKFLOW_DIRECTORY = PROJECT_DIRECTORY / "data" / "workflows"
OUTPUT_STEM = f"from_home_server/anima/{WORKFLOW_OUTPUT_NAMES['anima']}"


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


@pytest.mark.parametrize("selected_loras", [
    [],
    [
        {"name": "portraits/example.safetensors", "strength": 0.7, "clip_strength": 0.5},
        {"name": "zero-clip.safetensors", "strength": -0.2, "clip_strength": 0},
        {"name": "default-clip.safetensors", "strength": 0.4},
    ],
], ids=["no-loras", "active-loras-with-separate-clip"])
def test_anima_embedded_workflow_preserves_restorable_lora_widgets(selected_loras: list[dict]) -> None:
    """PNG의 UI Workflow에 활성 LoRA 배열과 독립적인 Model/CLIP 강도가 남는지 검증합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    original_api_workflow = copy.deepcopy(api_workflow)
    original_ui_workflow = copy.deepcopy(ui_workflow)
    request_workflow, metadata_workflow = prepare_anima(
        api_workflow, ui_workflow, "portrait", "blurry", {}, selected_loras, OUTPUT_STEM,
    )
    image_metadata = PngInfo()
    image_metadata.add_text("workflow", json.dumps(metadata_workflow, ensure_ascii=False))
    image_metadata.add_text("prompt", json.dumps(request_workflow, ensure_ascii=False))
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(image_buffer, format="PNG", pnginfo=image_metadata)
    image_buffer.seek(0)
    with Image.open(image_buffer) as saved_image:
        restored_workflow = json.loads(saved_image.info["workflow"])
        restored_prompt = json.loads(saved_image.info["prompt"])

    lora_node = next(node for node in restored_workflow["nodes"] if str(node["id"]) == "5")
    widget_identifiers = lora_node["properties"]["__lm_widget_ids"]
    restored_loras = lora_node["widgets_values"][widget_identifiers.index("loras")]
    assert isinstance(restored_loras, list)
    assert restored_loras == lora_node["widgets_values_named"]["loras"]
    assert [entry["name"] for entry in restored_loras] == [entry["name"] for entry in selected_loras]
    assert lora_node["widgets_values"][widget_identifiers.index("text")] == restored_prompt["5"]["inputs"]["text"]
    assert lora_node["widgets_values"][widget_identifiers.index("__lm_autocomplete_meta_text")] == {
        "version": 1, "textWidgetName": "text",
    }
    executed_loras = restored_prompt["5"]["inputs"]["loras"]["__value__"]
    for restored_lora, executed_lora, selected_lora in zip(restored_loras, executed_loras, selected_loras, strict=True):
        model_strength = selected_lora["strength"]
        clip_strength = selected_lora.get("clip_strength", model_strength)
        assert restored_lora["active"] is True
        assert restored_lora["strength"] == model_strength
        assert float(restored_lora["clipStrength"]) == clip_strength
        assert restored_lora["expanded"] == (model_strength != clip_strength)
        if clip_strength == 0 and model_strength != 0:
            assert restored_lora["clipStrength"] == "0"
        assert executed_lora["clipStrength"] == clip_strength

    assert api_workflow == original_api_workflow
    assert ui_workflow == original_ui_workflow


@pytest.mark.parametrize("empty_trigger_words", [False, True], ids=["existing-groups", "empty-list"])
def test_anima_trigger_words_are_disabled_without_adding_entries(empty_trigger_words: bool) -> None:
    """실행과 UI Metadata에서 자동 trigger word 유입을 끊고 기존 항목만 모두 끕니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    if empty_trigger_words:
        api_workflow["43"]["inputs"]["toggle_trigger_words"] = {"__value__": []}
    original_api_workflow = copy.deepcopy(api_workflow)
    original_ui_workflow = copy.deepcopy(ui_workflow)
    expected_entries = copy.deepcopy(api_workflow["43"]["inputs"]["toggle_trigger_words"]["__value__"])
    pending_entries = list(expected_entries)
    while pending_entries:
        trigger_entry = pending_entries.pop()
        trigger_entry["active"] = False
        pending_entries.extend(trigger_entry.get("items", []))

    request_workflow, metadata_workflow = prepare_anima(
        api_workflow, ui_workflow, "user prompt", "user negative", {},
        [{"name": "example.safetensors", "strength": 0.7}], OUTPUT_STEM,
    )
    trigger_inputs = request_workflow["43"]["inputs"]
    assert trigger_inputs["default_active"] is False
    assert trigger_inputs["trigger_words"] == ""
    assert trigger_inputs["orinalMessage"] == ""
    assert trigger_inputs["toggle_trigger_words"] == {"__value__": expected_entries}
    trigger_node = next(node for node in metadata_workflow["nodes"] if str(node["id"]) == "43")
    named_values = trigger_node["widgets_values_named"]
    assert named_values["default_active"] is False
    assert named_values["orinalMessage"] == ""
    assert named_values["toggle_trigger_words"] == expected_entries
    widget_names = list(named_values)
    assert trigger_node["widgets_values"][widget_names.index("toggle_trigger_words")] == expected_entries
    assert trigger_node["widgets_values"][widget_names.index("default_active")] is False
    trigger_input = next(node_input for node_input in trigger_node["inputs"] if node_input["name"] == "trigger_words")
    assert trigger_input["link"] is None
    assert not any(link[3] == 43 and link[4] == trigger_node["inputs"].index(trigger_input) for link in metadata_workflow["links"])
    lora_node = next(node for node in metadata_workflow["nodes"] if str(node["id"]) == "5")
    original_lora_node = next(node for node in ui_workflow["nodes"] if str(node["id"]) == "5")
    assert lora_node["outputs"][0]["links"] == original_lora_node["outputs"][0]["links"]
    assert lora_node["outputs"][1]["links"] == original_lora_node["outputs"][1]["links"]
    assert lora_node["outputs"][2]["links"] == []
    assert trigger_node["outputs"] == next(node for node in ui_workflow["nodes"] if str(node["id"]) == "43")["outputs"]
    assert request_workflow["3"]["inputs"]["populated_text"] == "user prompt"
    assert request_workflow["4"]["inputs"]["populated_text"] == "user negative"
    assert request_workflow["5"]["inputs"]["loras"]["__value__"][0]["active"] is True
    assert api_workflow == original_api_workflow
    assert ui_workflow == original_ui_workflow


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
