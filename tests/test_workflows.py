"""두 workflow에 요청 값이 올바른 위치로 들어가는지 확인합니다."""

import copy
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from home_server.configuration import PROJECT_DIRECTORY
from home_server.workflows import (
    MINIMAX_LORA_NODE_IDENTIFIERS, WORKFLOW_OUTPUT_NAMES, load_workflows, prepare_anima,
    prepare_minimax, validate_minimax_loras,
)


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


@pytest.mark.parametrize("selected_loras", [
    [],
    [{"name": "example.safetensors", "strength": 0.7, "clip_strength": 0.5}],
], ids=["no-loras", "active-lora"])
def test_anima_negpip_routes_model_and_clip_in_execution_and_embedded_workflow(selected_loras: list[dict]) -> None:
    """CFG 1의 음수 Prompt 가중치와 LoRA가 실행·복원 양쪽에서 NegPiP를 거치는지 확인합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    positive_prompt = "portrait, (blurry:-1), (bad anatomy:-1)"
    request_workflow, metadata_workflow = prepare_anima(
        api_workflow, ui_workflow, positive_prompt, "low quality", {"cfg": 1}, selected_loras, OUTPUT_STEM,
    )
    negpip_node_identifier = next(
        node_identifier for node_identifier, node in request_workflow.items() if node["class_type"] == "CLIPNegPip"
    )
    assert request_workflow[negpip_node_identifier]["inputs"] == {"model": ["5", 0], "clip": ["5", 1]}
    assert request_workflow["6"]["inputs"]["model"] == [negpip_node_identifier, 0]
    assert request_workflow["28"]["inputs"]["model"] == [negpip_node_identifier, 0]
    for node_identifier in ("53", "54", "19"):
        assert request_workflow[node_identifier]["inputs"]["clip"] == [negpip_node_identifier, 1]
    assert request_workflow["24"]["inputs"]["cfg"] == 1
    assert request_workflow["3"]["inputs"]["populated_text"] == positive_prompt
    assert request_workflow["4"]["inputs"]["populated_text"] == "low quality"

    metadata_nodes = {node["id"]: node for node in metadata_workflow["nodes"]}
    negpip_node = metadata_nodes[int(negpip_node_identifier)]
    assert negpip_node["mode"] == 0
    negpip_links = [link for link in metadata_workflow["links"] if link[1] == negpip_node["id"] or link[3] == negpip_node["id"]]
    assert {(link[3], link[4]) for link in negpip_links if link[1] == negpip_node["id"]} == {
        (49, 0), (53, 0), (54, 0), (19, 1), (22, 3),
    }
    for link_identifier, source_identifier, source_slot, target_identifier, target_slot, connection_type in negpip_links:
        source_output = metadata_nodes[source_identifier]["outputs"][source_slot]
        target_input = metadata_nodes[target_identifier]["inputs"][target_slot]
        assert link_identifier in source_output["links"]
        assert target_input["link"] == link_identifier
        assert source_output["type"] == target_input["type"] == connection_type
    for source_slot in (0, 1):
        incoming_link = next(link for link in negpip_links if link[3] == negpip_node["id"] and link[4] == source_slot)
        assert incoming_link[1:3] == [5, source_slot]
        assert metadata_nodes[5]["outputs"][source_slot]["links"] == [incoming_link[0]]
    assert metadata_nodes[43]["inputs"][3]["link"] == 91
    assert metadata_nodes[3]["widgets_values_named"]["populated_text"] == positive_prompt


def test_anima_templates_have_no_saved_lora_or_trigger_word_state() -> None:
    """두 기본 Workflow는 빈 LoRA·trigger 목록과 살아 있는 UI 연결로 시작합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    assert api_workflow["5"]["inputs"]["text"] == ""
    assert api_workflow["5"]["inputs"]["loras"] == {"__value__": []}
    assert api_workflow["43"]["inputs"]["toggle_trigger_words"] == {"__value__": []}
    assert api_workflow["43"]["inputs"]["orinalMessage"] == ""
    assert api_workflow["43"]["inputs"]["default_active"] is False
    assert api_workflow["43"]["inputs"]["allow_strength_adjustment"] is False
    assert api_workflow["43"]["inputs"]["trigger_words"] == ["5", 2]
    for node in ui_workflow["nodes"]:
        if str(node["id"]) == "5":
            expected_values = {"text": "", "loras": []}
        elif str(node["id"]) == "43":
            expected_values = {
                "toggle_trigger_words": [], "orinalMessage": "",
                "default_active": False, "allow_strength_adjustment": False,
            }
        else:
            continue
        widget_names = list(node["widgets_values_named"])
        for widget_name, expected_value in expected_values.items():
            assert node["widgets_values_named"][widget_name] == expected_value
            assert node["widgets_values"][widget_names.index(widget_name)] == expected_value


@pytest.mark.parametrize("empty_trigger_words", [False, True], ids=["stale-groups", "empty-list"])
def test_anima_trigger_words_are_disabled_without_adding_entries(empty_trigger_words: bool) -> None:
    """찌꺼기는 비우고 실행 시 자동 삽입을 막으면서 복원 후 UI의 목록 갱신 연결은 유지합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    trigger_entries = [] if empty_trigger_words else [
        {"text": "stale trigger", "active": True, "items": [{"text": "stale child", "active": True}]},
    ]
    api_workflow["43"]["inputs"].update({
        "toggle_trigger_words": {"__value__": trigger_entries},
        "orinalMessage": "stale trigger", "default_active": True,
    })
    template_trigger_node = next(node for node in ui_workflow["nodes"] if str(node["id"]) == "43")
    for widget_name, widget_value in (
        ("toggle_trigger_words", trigger_entries), ("orinalMessage", "stale trigger"), ("default_active", True),
    ):
        widget_index = list(template_trigger_node["widgets_values_named"]).index(widget_name)
        template_trigger_node["widgets_values_named"][widget_name] = widget_value
        template_trigger_node["widgets_values"][widget_index] = widget_value
    original_api_workflow = copy.deepcopy(api_workflow)
    original_ui_workflow = copy.deepcopy(ui_workflow)
    request_workflow, metadata_workflow = prepare_anima(
        api_workflow, ui_workflow, "user prompt", "user negative", {},
        [{"name": "example.safetensors", "strength": 0.7}], OUTPUT_STEM,
    )
    trigger_inputs = request_workflow["43"]["inputs"]
    assert trigger_inputs["default_active"] is False
    assert trigger_inputs["allow_strength_adjustment"] is False
    assert trigger_inputs["trigger_words"] == ""
    assert trigger_inputs["orinalMessage"] == ""
    assert trigger_inputs["toggle_trigger_words"] == {"__value__": []}
    trigger_node = next(node for node in metadata_workflow["nodes"] if str(node["id"]) == "43")
    named_values = trigger_node["widgets_values_named"]
    assert named_values["default_active"] is False
    assert named_values["orinalMessage"] == ""
    assert named_values["allow_strength_adjustment"] is False
    assert named_values["toggle_trigger_words"] == []
    widget_names = list(named_values)
    assert trigger_node["widgets_values"][widget_names.index("toggle_trigger_words")] == []
    assert trigger_node["widgets_values"][widget_names.index("default_active")] is False
    trigger_input = next(node_input for node_input in trigger_node["inputs"] if node_input["name"] == "trigger_words")
    assert trigger_input["link"] is not None
    assert any(link[0] == trigger_input["link"] and link[1:4] == [5, 2, 43] for link in metadata_workflow["links"])
    assert metadata_workflow["links"] == ui_workflow["links"]
    lora_node = next(node for node in metadata_workflow["nodes"] if str(node["id"]) == "5")
    original_lora_node = next(node for node in ui_workflow["nodes"] if str(node["id"]) == "5")
    assert lora_node["outputs"][0]["links"] == original_lora_node["outputs"][0]["links"]
    assert lora_node["outputs"][1]["links"] == original_lora_node["outputs"][1]["links"]
    assert lora_node["outputs"][2]["links"] == original_lora_node["outputs"][2]["links"]
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
    assert json.loads(request["2678"]["inputs"]["stack_data"]) == [{"on": True, "lora": "motion.safetensors", "str": 0.6}]
    assert request["2678"]["inputs"]["audio"] == 0
    assert request["2678"]["inputs"]["video"] == 1
    expected_output_stem = f"from_home_server/minimax_h3/{WORKFLOW_OUTPUT_NAMES['minimax_h3']}"
    assert request["2568"]["inputs"]["filename_prefix"] == expected_output_stem
    assert request["2568"]["inputs"]["seed"] == ["2739", 0]
    assert request["1512:2591"]["inputs"]["noise"] == ["2739", 1]
    seed_links = [link for link in metadata["links"] if link[1] == 2739 and link[2] == 0 and link[3] == 2568]
    assert len(seed_links) == 1
    saver_node = next(node for node in metadata["nodes"] if node["id"] == 2568)
    assert next(node_input for node_input in saver_node["inputs"] if node_input["name"] == "seed")["link"] == seed_links[0][0]
    assert any(node.get("widgets_values_named", {}).get("filename_prefix") == expected_output_stem for node in metadata["nodes"])


@pytest.mark.parametrize("lora_count", [0, 1, 2, 10])
def test_minimax_modality_weights_chain_and_metadata_round_trip(lora_count: int) -> None:
    """LoRA별 서로 다른 weight와 0, 빈 slot 및 복원용 세 저장 위치가 일치하는지 확인합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "minimax_h3")
    original_templates = copy.deepcopy((api_workflow, ui_workflow))
    selected_loras = []
    for slot_index in range(lora_count):
        selected_loras.append({
            "name": f"motion-{slot_index}.safetensors", "strength": 0 if slot_index == 0 else -0.2,
            "video_strength": slot_index / 2, "audio_strength": 0 if slot_index % 2 == 0 else 5,
        })
    request_workflow, metadata = prepare_minimax(
        api_workflow, ui_workflow, "input.png", "quiet scene", {}, selected_loras,
        f"from_home_server/minimax_h3/{WORKFLOW_OUTPUT_NAMES['minimax_h3']}",
    )
    restored_metadata = json.loads(json.dumps(metadata))
    metadata_nodes = {str(node["id"]): node for node in restored_metadata["nodes"]}
    previous_output = ["2730", 5]
    for slot_index, node_identifier in enumerate(MINIMAX_LORA_NODE_IDENTIFIERS):
        loader_node = request_workflow[node_identifier]
        loader_inputs = loader_node["inputs"]
        assert loader_node["class_type"] == "H3ModalityLoraLoader"
        assert loader_inputs["model"] == previous_output
        previous_output = [node_identifier, 0]
        saved_node = metadata_nodes[node_identifier]
        saved_widgets = saved_node["widgets_values_named"]
        assert saved_node["widgets_values"] == list(saved_widgets.values())
        assert saved_node["properties"]["stack_data"] == saved_widgets["stack_data"] == loader_inputs["stack_data"]
        assert loader_inputs["text"] == saved_widgets["text"] == 1
        assert loader_inputs["evict_model"] is saved_widgets["evict_model"] is False
        if slot_index < lora_count:
            selected_lora = selected_loras[slot_index]
            assert json.loads(loader_inputs["stack_data"]) == [{
                "on": True, "lora": selected_lora["name"], "str": selected_lora["strength"],
            }]
            assert loader_inputs["video"] == saved_widgets["video"] == selected_lora["video_strength"]
            assert loader_inputs["audio"] == saved_widgets["audio"] == selected_lora["audio_strength"]
        else:
            assert json.loads(loader_inputs["stack_data"]) == []
            assert loader_inputs["video"] == loader_inputs["audio"] == 1
    for consumer_identifier in ("1512:2590", "1512:2679", "1512:2692"):
        assert request_workflow[consumer_identifier]["inputs"]["model"] == previous_output
    assert request_workflow["1512:2701"]["inputs"]["clip"] == ["1512:2587", 0]
    assert (api_workflow, ui_workflow) == original_templates


def test_minimax_modality_template_links_preserve_clip_and_model_consumers() -> None:
    """Top-level·subgraph의 연결 양끝과 CLIP 직결을 검사해 복원 시 끊긴 배선을 잡습니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "minimax_h3")
    assert not any(node["class_type"] == "DaSiWa_LTX2LoraLoader" for node in api_workflow.values())
    metadata_nodes = {node["id"]: node for node in ui_workflow["nodes"]}
    for link_identifier, source_identifier, source_slot, target_identifier, target_slot, connection_type in ui_workflow["links"]:
        assert link_identifier in metadata_nodes[source_identifier]["outputs"][source_slot]["links"]
        assert metadata_nodes[target_identifier]["inputs"][target_slot]["link"] == link_identifier
        assert metadata_nodes[source_identifier]["outputs"][source_slot]["type"] == connection_type
        target_type = metadata_nodes[target_identifier]["inputs"][target_slot]["type"]
        assert target_type == "*" or connection_type in target_type.split(",")
    subgraph = next(graph for graph in ui_workflow["definitions"]["subgraphs"] if graph["id"] == metadata_nodes[1512]["type"])
    clip_link = next(link for link in subgraph["links"] if link["target_id"] == 2701 and link["target_slot"] == 0)
    assert (clip_link["origin_id"], clip_link["origin_slot"]) == (2587, 0)
    assert subgraph["inputs"][22]["linkIds"] == []
    assert metadata_nodes[1512]["inputs"][22]["link"] is None


@pytest.mark.parametrize("invalid_selection", [
    [{"name": "motion.safetensors", "audio_strength": -0.1}],
    [{"name": "motion.safetensors", "video_strength": 5.1}],
    [{"name": "motion.safetensors", "strength": float("nan")}],
    [{"name": "motion.safetensors", "audio_strength": "Infinity"}],
    [{"name": "motion.safetensors", "video_strength": None}],
    [{"name": f"motion-{slot_index}.safetensors"} for slot_index in range(11)],
])
def test_minimax_modality_loader_rejects_invalid_weights(invalid_selection: list[dict]) -> None:
    """Loader가 받을 수 없는 weight나 개수는 요청 전에 거부합니다."""

    with pytest.raises(ValueError):
        validate_minimax_loras(invalid_selection)


def test_adapter_rejects_output_path_escape() -> None:
    """요청 값으로 앱 output 밖의 저장 경로를 만들 수 없게 합니다."""

    api_workflow, ui_workflow = load_workflows(WORKFLOW_DIRECTORY, "anima")
    with pytest.raises(ValueError):
        prepare_anima(api_workflow, ui_workflow, "test", "", {}, [], "from_home_server/../outside")
