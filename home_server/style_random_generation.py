"""프로젝트 허용 범위에서 중복 없는 초기 조합을 제한된 횟수만 추첨합니다."""

import random
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field

from .style_projects import snapshot_hash
from .style_generation_sizing import DEFAULT_RANDOM_COMBINATION_COUNT, GENERATION_COUNT_POLICY_VERSION, MAXIMUM_RANDOM_COMBINATION_COUNT
from .style_lora_strength_policy import fixed_clip_style_component


RANDOM_SELECTION_VERSION = "initial-random-v3"
STRENGTH_STEP = Decimal("0.05")
ATTEMPTS_PER_COMBINATION = 30


class RandomStyleGenerationPlanInput(BaseModel):
    """이미지 Seed와 독립적인 초기 조합 Preview를 요청합니다."""

    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    combinationCount: int = Field(default=DEFAULT_RANDOM_COMBINATION_COUNT, ge=1, le=MAXIMUM_RANDOM_COMBINATION_COUNT)


def combination_selection_fingerprint(components: list[dict]) -> str:
    """성분 순서·파일 Metadata를 제외하고 실제 작가·LoRA 강도를 비교합니다."""

    normalized_components = []
    for component in components:
        normalized = {"identifier": component["identifier"], "strength": float(component["strength"]) or 0.0}
        clip_strength = component.get("clip_strength")
        if component["identifier"].startswith("lora:") and clip_strength is not None and clip_strength != component["strength"]:
            normalized["clip_strength"] = float(clip_strength) or 0.0
        normalized_components.append(normalized)
    return snapshot_hash(sorted(normalized_components, key=lambda component: component["identifier"]))


def component_strength_step_bounds(policy: dict) -> tuple[int, int]:
    """설정 범위에 포함되는 STR 0.05 배수의 정수 인덱스 경계를 계산합니다."""

    minimum_strength = Decimal(str(policy["minimumStrength"]))
    maximum_strength = Decimal(str(policy["maximumStrength"]))
    minimum_index = int((minimum_strength / STRENGTH_STEP).to_integral_value(rounding=ROUND_CEILING))
    maximum_index = int((maximum_strength / STRENGTH_STEP).to_integral_value(rounding=ROUND_FLOOR))
    if minimum_index > maximum_index:
        raise ValueError(f"STR 범위 {minimum_strength}~{maximum_strength}에 0.05의 배수가 없습니다. STR 범위를 조정해 주세요.")
    return minimum_index, maximum_index


def validate_component_strength_ranges(settings: dict) -> None:
    """새 조합에 사용할 수 있는 성분은 추첨 전에 유효한 STR 배수가 있는지 확인합니다."""

    for identifier, policy in sorted(settings["componentPolicies"].items()):
        component_kind = identifier.split(":", 1)[0]
        if not policy["enabled"] or settings[component_kind + "MaximumCount"] == 0:
            continue
        try:
            component_strength_step_bounds(policy)
        except ValueError as exception:
            raise ValueError(f"{identifier}: {exception}") from exception


def quantized_component_strength(strength: float, policy: dict) -> float:
    """상속·변이 값은 설정 범위 안의 가장 가까운 STR 0.05 배수로 맞춥니다."""

    minimum_index, maximum_index = component_strength_step_bounds(policy)
    nearest_index = int((Decimal(str(strength)) / STRENGTH_STEP).to_integral_value(rounding=ROUND_HALF_UP))
    bounded_index = max(minimum_index, min(maximum_index, nearest_index))
    return float(STRENGTH_STEP * bounded_index)


def random_component_strength(policy: dict, selection_random: random.Random) -> float:
    """설정 범위에 포함되는 STR 0.05 배수 중 하나를 균등 추첨합니다."""

    minimum_index, maximum_index = component_strength_step_bounds(policy)
    selected_index = selection_random.randint(minimum_index, maximum_index)
    return float(STRENGTH_STEP * selected_index)


def draw_initial_combinations(settings: dict, requested_count: int, selection_seed: str, existing_fingerprints: set[str]) -> tuple[list[list[dict]], dict]:
    """개수·성분·STR을 추첨하고 중복이 반복되면 부족한 수를 명시해 종료합니다."""

    validate_component_strength_ranges(settings)
    selection_random = random.Random(f"{RANDOM_SELECTION_VERSION}:{selection_seed}")
    available_components = {"artist": [], "lora": []}
    for identifier, policy in sorted(settings["componentPolicies"].items()):
        if policy["enabled"]:
            available_components[identifier.split(":", 1)[0]].append(identifier)
    fingerprints = set(existing_fingerprints)
    component_sets = []
    attempts = 0
    maximum_attempts = requested_count * ATTEMPTS_PER_COMBINATION
    while len(component_sets) < requested_count and attempts < maximum_attempts:
        attempts += 1
        components = []
        for component_kind in ("artist", "lora"):
            permitted_identifiers = available_components[component_kind]
            minimum_count = settings[component_kind + "MinimumCount"]
            maximum_count = min(settings[component_kind + "MaximumCount"], len(permitted_identifiers))
            selected_count = selection_random.randint(minimum_count, maximum_count)
            for identifier in sorted(selection_random.sample(permitted_identifiers, selected_count)):
                strength = random_component_strength(settings["componentPolicies"][identifier], selection_random)
                components.append(fixed_clip_style_component(identifier, strength))
        fingerprint = combination_selection_fingerprint(components)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        component_sets.append(components)
    provenance = {
        "mode": "random", "algorithm": RANDOM_SELECTION_VERSION, "selectionSeed": selection_seed,
        "countPolicyVersion": GENERATION_COUNT_POLICY_VERSION,
        "strengthStep": float(STRENGTH_STEP), "requestedCount": requested_count,
        "actualCount": len(component_sets), "attempts": attempts, "maximumAttempts": maximum_attempts,
        "shortfallCount": requested_count - len(component_sets),
        "componentCountRanges": {
            component_kind: {"minimum": settings[component_kind + "MinimumCount"], "maximum": settings[component_kind + "MaximumCount"]}
            for component_kind in ("artist", "lora")
        },
        "componentPolicies": {
            identifier: dict(policy) for identifier, policy in settings["componentPolicies"].items() if policy["enabled"]
        },
    }
    return component_sets, provenance
