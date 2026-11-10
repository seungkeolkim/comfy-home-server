"""프로젝트 범위 안에서 Mutate·Crossover·Random 자녀를 재현 가능하게 만듭니다."""

import random

from .style_random_generation import combination_selection_fingerprint, random_component_strength


EVOLUTION_POLICY_VERSION = "style-evolution-v1"


def component_preference_scores(candidates: list[dict], statistics: dict) -> dict:
    """평가된 활성·퇴역 조합의 Ridge 기여도를 원본 60회 Coordinate Descent로 구합니다."""

    rated_candidates = [candidate for candidate in candidates if statistics.get(candidate["identifier"], {}).get("matches", 0) or statistics.get(candidate["identifier"], {}).get("placed")]
    if not rated_candidates:
        return {}
    mean_rating = sum(statistics[candidate["identifier"]]["rating"] for candidate in rated_candidates) / len(rated_candidates)
    residuals = [statistics[candidate["identifier"]]["rating"] - mean_rating for candidate in rated_candidates]
    observations = {}
    for row_index, candidate in enumerate(rated_candidates):
        for component in candidate["components"]:
            observations.setdefault(component["identifier"], []).append((row_index, component["strength"]))
    scores = dict.fromkeys(observations, 0.0)
    for _ in range(60):
        for identifier, hits in observations.items():
            previous_score = scores[identifier]
            next_score = sum(strength * (residuals[row_index] + strength * previous_score) for row_index, strength in hits) / (sum(strength * strength for _, strength in hits) + 2.0)
            for row_index, strength in hits:
                residuals[row_index] -= strength * (next_score - previous_score)
            scores[identifier] = next_score
    return {identifier: round(score) for identifier, score in scores.items()}


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
        """새 작가는 기여도·부모 사용량, 새 LoRA는 원본과 같이 균등 선택합니다."""

        used_identifiers = {component["identifier"] for component in components}
        available_identifiers = [identifier for identifier in policies if identifier not in used_identifiers]
        if kind == "artist":
            weights = [preference.get(identifier, 1.0) / (1 + parent_usage.get(identifier, 0)) for identifier in available_identifiers]
            identifier = selection_random.choices(available_identifiers, weights=weights)[0]
        else:
            identifier = selection_random.choice(available_identifiers)
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
    artist_identifiers = [identifier for identifier, policy in settings["componentPolicies"].items() if identifier.startswith("artist:") and policy["enabled"]]
    maximum_score = max((abs(component_scores.get(identifier, 0)) for identifier in artist_identifiers), default=0)
    preference = {identifier: 2 ** (component_scores.get(identifier, 0) / maximum_score) if maximum_score else 1.0 for identifier in artist_identifiers}
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
        "requestedCount": requested_count, "actualCount": len(children), "shortfallCount": requested_count - len(children),
        "attempts": attempts, "maximumAttempts": requested_count * 30, "artistPreference": "ridge-60-usage", "newLoraChoice": "uniform",
        "modeCounts": {mode: sum(child["mode"] == mode for child in children) for mode in ("mutate", "crossover", "random")},
    }
    return children, provenance
