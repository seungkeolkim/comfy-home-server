"""프로젝트 허용 범위에서 중복 없는 초기 조합을 제한된 횟수만 추첨합니다."""

import random
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .style_projects import snapshot_hash


RANDOM_SELECTION_VERSION = "initial-random-v1"
STRENGTH_STEP = Decimal("0.01")
ATTEMPTS_PER_COMBINATION = 30


class RandomStyleGenerationPlanInput(BaseModel):
    """이미지 Seed와 독립적인 초기 조합 Preview를 요청합니다."""

    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    operationIdentifier: str = Field(min_length=16, max_length=100)
    combinationCount: int = Field(default=4, ge=1, le=32)


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


def random_component_strength(policy: dict, selection_random: random.Random) -> float:
    """최솟값부터 STR 0.01 간격과 최댓값 중 하나를 고르며 범위를 벗어나지 않습니다."""

    minimum_strength = Decimal(str(policy["minimumStrength"]))
    maximum_strength = Decimal(str(policy["maximumStrength"]))
    full_steps = int((maximum_strength - minimum_strength) // STRENGTH_STEP)
    has_extra_endpoint = minimum_strength + STRENGTH_STEP * full_steps != maximum_strength
    selected_index = selection_random.randrange(full_steps + 1 + int(has_extra_endpoint))
    if selected_index > full_steps:
        return float(maximum_strength)
    return float(minimum_strength + STRENGTH_STEP * selected_index)


def draw_initial_combinations(settings: dict, requested_count: int, selection_seed: str, existing_fingerprints: set[str]) -> tuple[list[list[dict]], dict]:
    """개수·성분·STR을 추첨하고 중복이 반복되면 부족한 수를 명시해 종료합니다."""

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
                components.append({"identifier": identifier, "strength": random_component_strength(settings["componentPolicies"][identifier], selection_random)})
        fingerprint = combination_selection_fingerprint(components)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        component_sets.append(components)
    provenance = {
        "mode": "random", "algorithm": RANDOM_SELECTION_VERSION, "selectionSeed": selection_seed,
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
