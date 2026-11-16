"""스타일 탐색의 새 조합·실제 생성·CHS 등록에 같은 고정 CLIP을 적용합니다."""


FIXED_STYLE_LORA_CLIP_STRENGTH = 1.0
STYLE_LORA_STRENGTH_POLICY_VERSION = "style-lora-fixed-clip-v1"


def fixed_clip_style_component(identifier: str, strength: float) -> dict:
    """작가는 STR만, LoRA는 STR과 고정 CLIP 1을 가진 새 성분을 만듭니다."""

    component = {"identifier": identifier, "strength": strength}
    if identifier.startswith("lora:"):
        component["clip_strength"] = FIXED_STYLE_LORA_CLIP_STRENGTH
    return component


def fixed_clip_style_lora_selections(components: list[dict]) -> list[dict]:
    """원본 Snapshot을 수정하지 않고 생성·등록용 LoRA의 CLIP을 1로 고정합니다."""

    selected_loras = []
    for component in components:
        if not component["identifier"].startswith("lora:"):
            continue
        selected_loras.append({
            "name": component["identifier"][5:],
            "strength": component["strength"],
            "clip_strength": FIXED_STYLE_LORA_CLIP_STRENGTH,
        })
    return selected_loras
