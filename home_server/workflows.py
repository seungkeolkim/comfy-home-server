"""지원하는 두 ComfyUI workflow를 요청별로 수정합니다."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


WORKFLOW_FILES = {
    "anima": "AnimaTurboV9/AnimaStandardTurboV9_empty",
    "minimax_h3": "DasiwaMinimaxH3/DasiwaMinimaxH3WorkflowsT2VA_cMMH3V23_bypassfix_empty",
}

WORKFLOW_OUTPUT_NAMES = {
    "anima": "%time_%seed",
    "minimax_h3": "%date:yyMMdd_HHmmss%_%seed%",
}


def load_workflows(workflow_directory: Path, workflow_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """선택한 workflow의 API JSON과 UI JSON을 읽습니다."""

    if workflow_name not in WORKFLOW_FILES:
        raise ValueError("지원하지 않는 workflow입니다.")
    file_prefix = workflow_directory / WORKFLOW_FILES[workflow_name]
    api_workflow = json.loads(file_prefix.with_name(file_prefix.name + "_api.json").read_text(encoding="utf-8-sig"))
    ui_workflow = json.loads(file_prefix.with_suffix(".json").read_text(encoding="utf-8-sig"))
    return api_workflow, ui_workflow


def update_ui_widget(ui_workflow: dict[str, Any], node_id: str, name: str, value: Any) -> None:
    """Drag and drop metadata의 widget 값도 API 요청과 맞춥니다."""

    for node in ui_workflow.get("nodes", []):
        if str(node.get("id")) != node_id:
            continue
        named_values = node.get("widgets_values_named")
        if not isinstance(named_values, dict):
            return
        widget_names = list(named_values)
        named_values[name] = value
        if name in widget_names:
            widget_index = widget_names.index(name)
            widget_values = node.get("widgets_values")
            if isinstance(widget_values, list) and widget_index < len(widget_values):
                widget_values[widget_index] = value
        return


def connect_ui_seed(metadata_workflow: dict[str, Any]) -> None:
    """MiniMax metadata에도 sampling seed와 Saver의 연결을 기록합니다."""

    source_node = None
    target_node = None
    for node in metadata_workflow["nodes"]:
        if str(node["id"]) == "2739":
            source_node = node
        if str(node["id"]) == "2568":
            target_node = node
    if source_node is None or target_node is None:
        raise ValueError("MiniMax seed 또는 Saver node가 없습니다.")
    for input_index, node_input in enumerate(target_node["inputs"]):
        if node_input["name"] != "seed":
            continue
        workflow_links = metadata_workflow.setdefault("links", [])
        link_identifier = max([metadata_workflow.get("last_link_id", 0)] + [link[0] for link in workflow_links]) + 1
        node_input["link"] = link_identifier
        source_links = source_node["outputs"][0].get("links") or []
        source_links.append(link_identifier)
        source_node["outputs"][0]["links"] = source_links
        workflow_links.append([link_identifier, source_node["id"], 0, target_node["id"], input_index, "INT"])
        metadata_workflow["last_link_id"] = link_identifier
        return
    raise ValueError("MiniMax Saver에 seed 입력이 없습니다.")


def validate_output_stem(output_stem: str) -> str:
    """출력 경로가 앱 관리 폴더 아래의 단순 상대 경로인지 확인합니다."""

    normalized = output_stem.replace("\\", "/")
    components = normalized.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("출력 경로에 잘못된 구성요소가 있습니다.")
    path_components = components[:-1]
    if components[-1] not in WORKFLOW_OUTPUT_NAMES.values():
        path_components.append(components[-1])
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", component) for component in path_components):
        raise ValueError("출력 경로에는 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다.")
    return normalized


def prepare_anima(
    api_workflow: dict[str, Any],
    ui_workflow: dict[str, Any],
    positive_prompt: str,
    negative_prompt: str,
    settings: dict[str, Any],
    selected_loras: list[dict[str, Any]],
    output_stem: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Anima의 Prompt, sampling, LoRA, 출력 파일 경로를 적용합니다."""

    request_workflow = copy.deepcopy(api_workflow)
    metadata_workflow = copy.deepcopy(ui_workflow)
    output_path = validate_output_stem(output_stem)
    output_directory, output_name = output_path.rsplit("/", 1)

    width = int(settings.get("width", 1024))
    height = int(settings.get("height", 1536))
    seed = int(settings.get("seed", 42))
    steps = int(settings.get("steps", 12))
    cfg = float(settings.get("cfg", 1))
    if min(width, height, steps) <= 0:
        raise ValueError("해상도와 steps는 1 이상이어야 합니다.")

    for node_id, prompt_text in (("3", positive_prompt), ("4", negative_prompt)):
        prompt_inputs = request_workflow[node_id]["inputs"]
        prompt_inputs["wildcard_text"] = prompt_text
        prompt_inputs["populated_text"] = prompt_text
        prompt_inputs["mode"] = "fixed"
        for key in ("wildcard_text", "populated_text", "mode"):
            update_ui_widget(metadata_workflow, node_id, key, prompt_inputs[key])

    request_workflow["24"]["inputs"].update({"seed": seed, "steps": steps, "cfg": cfg})
    request_workflow["45"]["inputs"]["value"] = width
    request_workflow["48"]["inputs"]["value"] = height
    # 요청마다 wildcard를 별도로 선택하도록 한 요청은 한 장만 생성합니다.
    request_workflow["51"]["inputs"]["value"] = 1
    for node_id, name, value in (
        ("24", "seed", seed), ("24", "steps", steps), ("24", "cfg", cfg),
        ("45", "value", width), ("48", "value", height), ("51", "value", 1),
    ):
        update_ui_widget(metadata_workflow, node_id, name, value)

    lora_entries = []
    for selected_lora in selected_loras:
        model_strength = float(selected_lora.get("strength", 1))
        lora_entries.append({
            "name": str(selected_lora["name"]), "strength": model_strength,
            "clipStrength": float(selected_lora.get("clip_strength", model_strength)),
            "active": True, "expanded": False, "selected": False, "locked": False,
        })
    request_workflow["5"]["inputs"]["loras"] = {"__value__": lora_entries}
    request_workflow["5"]["inputs"]["text"] = " ".join(
        f"<lora:{entry['name']}:{entry['strength']}:{entry['clipStrength']}>" for entry in lora_entries
    )
    update_ui_widget(metadata_workflow, "5", "loras", {"__value__": lora_entries})
    update_ui_widget(metadata_workflow, "5", "text", request_workflow["5"]["inputs"]["text"])

    save_inputs = request_workflow["13"]["inputs"]
    save_inputs["path"] = output_directory
    save_inputs["filename"] = output_name
    save_inputs["time_format"] = "%y%m%d_%H%M%S"
    save_inputs["embed_workflow"] = True
    update_ui_widget(metadata_workflow, "13", "path", output_directory)
    update_ui_widget(metadata_workflow, "13", "filename", output_name)
    update_ui_widget(metadata_workflow, "13", "time_format", save_inputs["time_format"])
    return request_workflow, metadata_workflow


def build_minimax_timeline(
    original_text: str, uploaded_image: str, prompt_text: str, width: int, height: int, duration: float,
) -> str:
    """첫·마지막 frame과 Prompt를 Director timeline에 반영합니다."""

    timeline = json.loads(original_text or "{}")
    timeline.pop("continuity", None)
    timeline["items"] = [
        {"id": "home-first-frame", "type": "image", "slot": 0, "order": 0, "enabled": True, "value": uploaded_image},
        {"id": "home-last-frame", "type": "image", "slot": 1, "order": 1, "enabled": True, "value": uploaded_image},
    ]
    timeline["resolved_prompt"] = prompt_text
    builder_state = timeline.get("builder_state") or {}
    builder_state.update({"mode": "FL2VA", "duration": duration, "prompt_mode": "simple", "simple_prompt": prompt_text})
    timeline["builder_state"] = builder_state
    resolution = timeline.get("resolution") or {}
    resolution.update({"custom_width": width, "custom_height": height})
    timeline["resolution"] = resolution
    return json.dumps(timeline, ensure_ascii=False, separators=(",", ":"))


def apply_minimax_upscale(workflow: dict[str, Any], mode: str, model_name: str) -> None:
    """선택한 2배 upscale node를 video 저장 node 앞에 삽입합니다."""

    if mode == "off":
        return
    combine_inputs = workflow["2568"]["inputs"]
    source_images = combine_inputs["images"]
    if mode == "simple":
        node_id = "home_upscale_simple"
        workflow[node_id] = {
            "class_type": "DaSiWa_TorchResize",
            "inputs": {
                "image": source_images, "size_mode": "Multiplier", "aspect_mode": "Fit",
                "target_width": 1920, "target_height": 1080, "scale_multiplier": 2,
                "interpolation": "Lanczos", "gamma_correct": True, "divisible_by": 1,
                "pad_color": "0, 0, 0", "crop_position": "center", "batch_size": 0,
                "max_batch_megapixels": 16, "cache_size": 64,
            },
        }
    elif mode == "model":
        workflow["home_upscale_model_loader"] = {
            "class_type": "UpscaleModelLoader", "inputs": {"model_name": model_name},
        }
        node_id = "home_upscale_model"
        workflow[node_id] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["home_upscale_model_loader", 0], "image": source_images},
        }
    elif mode == "rtx":
        node_id = "home_upscale_rtx"
        workflow[node_id] = {
            "class_type": "DaSiWa_RTX_UpscalerRefiner",
            "inputs": {
                "images": source_images, "denoise": False, "denoise_quality": "Ultra",
                "deblur": False, "deblur_quality": "Ultra", "upscale": "VSR",
                "upscale_quality": "Ultra", "resize_type": "Scale", "scale": 2,
                "megapixels": 2, "width": 1920, "height": 1080, "divisible_by": "32",
                "ratio_preset": "16:9", "resize_method": "Center Crop (Fill)",
                "device_id": 0, "empty_cache": True, "use_mmap": False,
                "auto_unload_models": True,
            },
        }
    else:
        raise ValueError("지원하지 않는 upscale mode입니다.")
    combine_inputs["images"] = [node_id, 0]


def prepare_minimax(
    api_workflow: dict[str, Any], ui_workflow: dict[str, Any], uploaded_image: str,
    prompt_text: str, settings: dict[str, Any], selected_loras: list[dict[str, Any]],
    output_stem: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """MiniMax FL2VA 요청의 Director, LoRA, upscale, 저장 경로를 설정합니다."""

    request_workflow = copy.deepcopy(api_workflow)
    metadata_workflow = copy.deepcopy(ui_workflow)
    width = int(settings.get("width", 720))
    height = int(settings.get("height", 720))
    duration = float(settings.get("duration", 10))
    frame_rate = float(settings.get("frame_rate", 24))
    if min(width, height, duration, frame_rate) <= 0:
        raise ValueError("해상도, 길이, frame rate는 0보다 커야 합니다.")
    if settings.get("auto_align", True):
        width = ((width + 31) // 32) * 32
        height = ((height + 31) // 32) * 32

    director_inputs = request_workflow["2730"]["inputs"]
    director_inputs.update({
        "mode": "FL2VA", "prompt": prompt_text, "width": width, "height": height,
        "duration": duration, "frame_rate": frame_rate,
        "ref_image_size": str(settings.get("ref_image_size", "match")),
        "external_prompt_overwrite": prompt_text,
    })
    director_inputs["timeline_data"] = build_minimax_timeline(
        str(director_inputs.get("timeline_data", "{}")), uploaded_image,
        prompt_text, width, height, duration,
    )
    builder_state = json.loads(str(director_inputs.get("builder_state", "{}")))
    builder_state.update({"mode": "FL2VA", "duration": duration, "prompt_mode": "simple", "simple_prompt": prompt_text})
    director_inputs["builder_state"] = json.dumps(builder_state, ensure_ascii=False, separators=(",", ":"))
    for key in ("mode", "prompt", "width", "height", "duration", "frame_rate", "ref_image_size", "timeline_data", "builder_state"):
        update_ui_widget(metadata_workflow, "2730", key, director_inputs[key])

    for node in request_workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "DaSiWa_SeedControl":
            state = json.loads(str(node["inputs"].get("seed_control_state", "{}")))
            if state.get("mode") == "random":
                node["inputs"]["seed_value"] = 0

    stack_entries = []
    for selected_lora in selected_loras:
        stack_entries.append({
            "on": True, "lora": str(selected_lora["name"]),
            "str": float(selected_lora.get("strength", 1)),
            "vs": float(selected_lora.get("video_strength", 1)),
            "as": float(selected_lora.get("audio_strength", 1)),
        })
    if len(stack_entries) > 10:
        raise ValueError("MiniMax workflow에는 LoRA를 최대 10개 적용할 수 있습니다.")
    while len(stack_entries) < 10:
        stack_entries.append({"on": True, "lora": "None", "str": 1, "vs": 1, "as": 1})
    stack_json = json.dumps(stack_entries, ensure_ascii=False, separators=(",", ":"))
    request_workflow["2678"]["inputs"]["stack_data"] = stack_json
    update_ui_widget(metadata_workflow, "2678", "stack_data", stack_json)

    output_path = validate_output_stem(output_stem)
    combine_inputs = request_workflow["2568"]["inputs"]
    combine_inputs["filename_prefix"] = output_path
    combine_inputs["seed"] = ["2739", 0]
    combine_inputs["save_metadata"] = True
    update_ui_widget(metadata_workflow, "2568", "filename_prefix", output_path)
    update_ui_widget(metadata_workflow, "2568", "save_metadata", True)
    connect_ui_seed(metadata_workflow)
    apply_minimax_upscale(
        request_workflow, str(settings.get("upscale_mode", "off")),
        str(settings.get("upscale_model_name", "2x-AnimeSharpV4_RCAN.safetensors")),
    )
    return request_workflow, metadata_workflow
