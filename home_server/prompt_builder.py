"""상황 단위 Prompt를 wildcard 문구로 조립합니다."""

from __future__ import annotations

import random
from typing import Any


SCENARIO_FIELDS = ("characters", "situation", "details", "emotion", "location")


def selected_scenarios(body: dict[str, Any], selected_ids: list[str]) -> list[dict[str, Any]]:
    """체크한 상황을 원래 순서대로 찾아 반환합니다."""

    scenarios = body.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("scenarios는 목록이어야 합니다.")
    selected = [scenario for scenario in scenarios if scenario.get("id") in selected_ids]
    if selected_ids and len(selected) != len(set(selected_ids)):
        raise ValueError("선택한 상황 중 존재하지 않는 항목이 있습니다.")
    return selected


def scenario_text(scenario: dict[str, Any], separator: str) -> str:
    """한 상황의 캐릭터·상황·동작·감정·장소를 연결합니다."""

    fragments = [str(scenario.get(field, "")).strip() for field in SCENARIO_FIELDS]
    return separator.join(fragment for fragment in fragments if fragment)


def compile_prompt(body: dict[str, Any], selected_ids: list[str]) -> str:
    """공통 문구와 선택 상황을 중첩 wildcard 문구로 조립합니다."""

    separator = str(body.get("separator", ", "))
    scenarios = selected_scenarios(body, selected_ids)
    use_weights = any(float(scenario.get("weight", 1)) != 1 for scenario in scenarios)
    options = []
    for scenario in scenarios:
        option = scenario_text(scenario, separator)
        if not option:
            continue
        weight = float(scenario.get("weight", 1))
        if weight <= 0:
            raise ValueError("상황 가중치는 0보다 커야 합니다.")
        options.append(f"{weight:g}::{option}" if use_weights and len(scenarios) > 1 else option)
    situation_text = "{" + "|".join(options) + "}" if len(options) > 1 else (options[0] if options else "")
    fragments = [str(body.get("prefix", "")).strip(), situation_text, str(body.get("suffix", "")).strip()]
    return separator.join(fragment for fragment in fragments if fragment)


def choose_scenario(body: dict[str, Any], selected_ids: list[str], seed: int) -> dict[str, Any] | None:
    """상황별 가중치를 반영해 한 요청에 사용할 상황을 고릅니다."""

    scenarios = selected_scenarios(body, selected_ids)
    if not scenarios:
        return None
    weights = [float(scenario.get("weight", 1)) for scenario in scenarios]
    if any(weight <= 0 for weight in weights):
        raise ValueError("상황 가중치는 0보다 커야 합니다.")
    return random.Random(seed).choices(scenarios, weights=weights, k=1)[0]


def compile_selected_prompt(body: dict[str, Any], scenario: dict[str, Any] | None) -> str:
    """선택한 한 상황의 내부 wildcard가 남은 Prompt를 만듭니다."""

    separator = str(body.get("separator", ", "))
    situation_text = scenario_text(scenario, separator) if scenario else ""
    fragments = [str(body.get("prefix", "")).strip(), situation_text, str(body.get("suffix", "")).strip()]
    return separator.join(fragment for fragment in fragments if fragment)
