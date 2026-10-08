"""Anima Prompt 본문에 적힌 태그 참조를 검증하고 확정합니다."""

from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from typing import Any


TAG_REFERENCE_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_]*)\]")
MAX_SELECTED_TAGS = 200
MAX_TAG_DEPTH = 32
MAX_TAG_REPLACEMENTS = 256
MAX_PROMPT_LENGTH = 16_000


def referenced_tag_keys(template_text: str) -> list[str]:
    """본문에 등장하는 대문자 태그 참조를 순서대로 찾습니다."""

    return TAG_REFERENCE_PATTERN.findall(template_text)


def anima_prompt(body: dict[str, Any]) -> str:
    """Anima Prompt 텍스트를 검증한 뒤 원문 그대로 반환합니다."""

    prompt_text = body.get("prompt")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("Anima Prompt를 입력해 주세요.")
    if len(prompt_text) > MAX_PROMPT_LENGTH:
        raise ValueError("Anima Prompt 길이 제한을 초과했습니다.")
    return prompt_text


def validate_tag_selection(prompt_text: str, selected_tags: list[dict[str, Any]]) -> None:
    """Prompt에서 도달할 수 있는 모든 선택지의 누락과 cycle을 검사합니다."""

    if len(selected_tags) > MAX_SELECTED_TAGS:
        raise ValueError(f"태그 항목은 최대 {MAX_SELECTED_TAGS}개 선택할 수 있습니다.")
    selected_ids = [tag["tag_id"] for tag in selected_tags]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("같은 태그 항목을 중복 선택할 수 없습니다.")

    candidates_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in selected_tags:
        if not math.isfinite(float(tag["weight"])) or float(tag["weight"]) <= 0:
            raise ValueError("태그 선택 weight는 0보다 커야 합니다.")
        candidates_by_key[tag["tag_key"]].append(tag)

    visiting_ids: set[str] = set()
    checked_depths: dict[str, int] = {}

    def visit_tag(tag: dict[str, Any], path: list[str]) -> None:
        """선택된 항목의 하위 참조를 모두 방문합니다."""

        tag_id = tag["tag_id"]
        if tag_id in visiting_ids:
            raise ValueError(f"태그 참조 cycle이 있습니다: {' → '.join([*path, tag['name']])}")
        if len(path) >= MAX_TAG_DEPTH:
            raise ValueError(f"태그 참조 깊이는 최대 {MAX_TAG_DEPTH}단계입니다.")
        if checked_depths.get(tag_id, -1) >= len(path):
            return
        visiting_ids.add(tag_id)
        for tag_key in referenced_tag_keys(tag["content"]):
            visit_key(tag_key, [*path, tag["name"]])
        visiting_ids.remove(tag_id)
        checked_depths[tag_id] = len(path)

    def visit_key(tag_key: str, path: list[str]) -> None:
        """참조 키의 모든 선택지를 방문해 어느 선택이든 유효한지 확인합니다."""

        candidates = candidates_by_key.get(tag_key, [])
        if not candidates:
            raise ValueError(f"[{tag_key}]에 대해 선택된 태그 항목이 없습니다.")
        for candidate in candidates:
            visit_tag(candidate, path)

    for root_key in referenced_tag_keys(prompt_text):
        visit_key(root_key, [])


def resolve_tag_prompt(
    body: dict[str, Any], selected_tags: list[dict[str, Any]], seed: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Prompt 본문에서 시작해 각 참조를 weight에 따라 독립적으로 확장합니다."""

    prompt_text = anima_prompt(body)
    validate_tag_selection(prompt_text, selected_tags)
    random_generator = random.Random(seed)
    candidates_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in selected_tags:
        candidates_by_key[tag["tag_key"]].append(tag)
    selected_path: list[dict[str, Any]] = []
    replacement_count = 0

    def expand_text(template_text: str, depth: int) -> str:
        """텍스트의 각 참조를 해당 키의 선택지 중 하나로 치환합니다."""

        nonlocal replacement_count
        if depth >= MAX_TAG_DEPTH:
            raise ValueError(f"태그 참조 깊이는 최대 {MAX_TAG_DEPTH}단계입니다.")

        def replace_reference(match: re.Match[str]) -> str:
            """참조 하나의 후보를 뽑고 그 후보의 본문을 재귀적으로 확장합니다."""

            nonlocal replacement_count
            replacement_count += 1
            if replacement_count > MAX_TAG_REPLACEMENTS:
                raise ValueError("태그 치환 횟수 제한을 초과했습니다.")
            candidates = candidates_by_key[match.group(1)]
            chosen_tag = random_generator.choices(
                candidates, weights=[candidate["weight"] for candidate in candidates], k=1,
            )[0]
            selected_path.append({
                "tag_id": chosen_tag["tag_id"], "tag_key": chosen_tag["tag_key"],
                "name": chosen_tag["name"], "depth": depth,
            })
            return expand_text(chosen_tag["content"], depth + 1)

        expanded_text = TAG_REFERENCE_PATTERN.sub(replace_reference, template_text)
        if len(expanded_text) > MAX_PROMPT_LENGTH:
            raise ValueError("태그 치환 후 Prompt 길이 제한을 초과했습니다.")
        return expanded_text

    return expand_text(prompt_text, 0), selected_path
