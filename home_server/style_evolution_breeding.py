"""프로젝트 범위 안에서 Mutate·Crossover·Random 자녀를 재현 가능하게 만듭니다."""

import random

from .style_random_generation import combination_selection_fingerprint, random_component_strength
from .style_generation_sizing import GENERATION_COUNT_POLICY_VERSION
from .style_component_statistics import COMPONENT_PREFERENCE_POLICY_VERSION, component_preference_scores, component_selection_preferences


EVOLUTION_POLICY_VERSION = "style-evolution-v2"


def bounded_strength(strength: float, policy: dict) -> float:
    """새 정책의 범위 안으로 상속·변이 STR을 보정하되 부모 원본은 변경하지 않습니다."""

    return max(policy["minimumStrength"], min(policy["maximumStrength"], round(strength, 2)))


def inherit_component(component: dict, policy: dict, jitter: float, selection_random: random.Random) -> dict:
    """명시적인 독립 CLIP 0을 보존하며 Model STR만 허용 범위에서 변이합니다."""

    inherited = {"identifier": component["identifier"], "strength": bounded_strength(component["strength"] + selection_random.uniform(-jitter, jitter), policy)}
    if component.get("clip_strength") is not None and component["clip_strength"] != component["strength"]:
        inherited["clip_strength"] = component["clip_strength"]
    return inherited


def breed_component_kind(settings: dict, first_parent: dict, second_parent: dict, mode: str, kind: str, selection_random: random.Random, parent_usage: dict, preference: dict) -> list[dict]:
    """작가·LoRA별 범위·개수·상속 제외를 적용하면서 같은 진화 Mode를 사용합니다."""

    policies = {identifier: policy for identifier, policy in sorted(settings["componentPolicies"].items()) if identifier.startswith(kind + ":") and policy["enabled"]}
    minimum_count = settings[kind + "MinimumCount"]
    maximum_count = min(settings[kind + "MaximumCount"], len(policies))
    if maximum_count == 0:
        return []
    first_components = [component for component in first_parent["components"] if component["identifier"] in policies]
    second_components = [component for component in second_parent["components"] if component["identifier"] in policies]
    components = []
    if mode == "crossover":
        inherited = {component["identifier"]: component for component in first_components}
        for component in second_components:
            inherited.setdefault(component["identifier"], component)
        components = [inherit_component(component, policies[identifier], 0, selection_random) for identifier, component in inherited.items()]
        selection_random.shuffle(components)
        components = components[:selection_random.randint(minimum_count, maximum_count)]
    elif mode == "mutate":
        jitter = 0.3 if kind == "artist" else 0.2
        components = [inherit_component(component, policies[component["identifier"]], jitter, selection_random) for component in first_components]
        selection_random.shuffle(components)
        components = components[:maximum_count]

    def fresh_component() -> dict:
        """작가와 LoRA 모두 기여도와 부모 사용량을 반영해 중복 없이 선택합니다."""

        used_identifiers = {component["identifier"] for component in components}
        available_identifiers = [identifier for identifier in policies if identifier not in used_identifiers]
        weights = [preference.get(identifier, 1.0) / (1 + parent_usage.get(identifier, 0)) for identifier in available_identifiers]
        identifier = selection_random.choices(available_identifiers, weights=weights)[0]
        return {"identifier": identifier, "strength": random_component_strength(policies[identifier], selection_random)}

    if mode == "mutate":
        action_count = selection_random.randint(1, 3) if kind == "artist" else int(selection_random.random() < 0.5)
        for _ in range(action_count):
            actions = []
            can_draw = len(components) < len(policies)
            if components and can_draw:
                actions.append("replace")
            if len(components) > minimum_count:
                actions.append("remove")
            if can_draw and len(components) < maximum_count:
                actions.append("add")
            if not actions:
                break
            action = selection_random.choice(actions)
            if action == "replace":
                replacement = fresh_component()
                components[selection_random.randrange(len(components))] = replacement
            elif action == "remove":
                components.pop(selection_random.randrange(len(components)))
            else:
                components.append(fresh_component())
    target_count = selection_random.randint(minimum_count, maximum_count) if mode == "random" else minimum_count
    while len(components) < target_count:
        components.append(fresh_component())
    return sorted(components, key=lambda component: component["identifier"])


def draw_evolution_children(settings: dict, parents: list[dict], statistics: dict, all_candidates: list[dict], requested_count: int, selection_seed: str) -> tuple[list[dict], dict]:
    """상위 부모 선형 가중치와 1:1:1 Mode 확률로 중복 없는 자녀를 유한 추첨합니다."""

    selection_random = random.Random(f"{EVOLUTION_POLICY_VERSION}:{selection_seed}")
    existing_fingerprints = {combination_selection_fingerprint(candidate["components"]) for candidate in all_candidates}
    component_scores = component_preference_scores(all_candidates, statistics)
    enabled_identifiers = [identifier for identifier, policy in settings["componentPolicies"].items() if policy["enabled"]]
    preference = component_selection_preferences(component_scores, enabled_identifiers)
    parent_usage = {}
    for parent in parents:
        for component in parent["components"]:
            identifier = component["identifier"]
            parent_usage[identifier] = parent_usage.get(identifier, 0) + 1
    parent_weights = [2 - index / max(len(parents) - 1, 1) for index in range(len(parents))]
    children = []
    attempts = 0
    while len(children) < requested_count and attempts < requested_count * 30:
        attempts += 1
        first_index = selection_random.choices(range(len(parents)), weights=parent_weights)[0]
        remaining_indices = [index for index in range(len(parents)) if index != first_index]
        second_index = selection_random.choices(remaining_indices, weights=[parent_weights[index] for index in remaining_indices])[0]
        first_parent, second_parent = parents[first_index], parents[second_index]
        mode = selection_random.choice(["mutate", "crossover", "random"])
        components = []
        for kind in ("artist", "lora"):
            components.extend(breed_component_kind(settings, first_parent, second_parent, mode, kind, selection_random, parent_usage, preference))
        fingerprint = combination_selection_fingerprint(components)
        if not components or fingerprint in existing_fingerprints:
            continue
        existing_fingerprints.add(fingerprint)
        children.append({"components": components, "mode": mode, "parentIdentifiers": [first_parent["identifier"], second_parent["identifier"]] if mode == "crossover" else [first_parent["identifier"]] if mode == "mutate" else []})
    provenance = {
        "mode": "evolution", "algorithm": EVOLUTION_POLICY_VERSION, "selectionSeed": selection_seed,
        "countPolicyVersion": GENERATION_COUNT_POLICY_VERSION,
        "requestedCount": requested_count, "actualCount": len(children), "shortfallCount": requested_count - len(children),
        "attempts": attempts, "maximumAttempts": requested_count * 30, "artistPreference": "ridge-60-usage", "newLoraChoice": "ridge-60-usage",
        "componentPreferencePolicy": COMPONENT_PREFERENCE_POLICY_VERSION, "componentScores": component_scores,
        "componentPreferenceMultipliers": preference, "parentComponentUsage": parent_usage,
        "modeCounts": {mode: sum(child["mode"] == mode for child in children) for mode in ("mutate", "crossover", "random")},
    }
    return children, provenance
