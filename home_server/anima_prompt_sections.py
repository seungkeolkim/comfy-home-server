"""Anima 원본 Prompt를 구분자 기준으로 나누고 작업별 본문을 검증합니다."""

import re
from typing import Any

from .tag_builder import anima_negative_prompt, anima_prompt


ANIMA_PROMPT_SEPARATOR_PATTERN = re.compile(r"^[ \t]*-{5,}[ \t]*\r?$", re.MULTILINE)


def split_anima_prompt_sections(body: dict[str, Any]) -> list[dict[str, Any]]:
    """단독 구분자 줄로 나눈 유효한 본문을 반환하고 단일 Prompt 원문은 보존합니다."""

    prompt_text = body.get("prompt")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("Anima Prompt를 입력해 주세요.")
    anima_negative_prompt(body)
    raw_sections = ANIMA_PROMPT_SEPARATOR_PATTERN.split(prompt_text)
    prompt_sections = []
    for raw_section in raw_sections:
        section_text = raw_section.strip() if len(raw_sections) > 1 else raw_section
        if not section_text.strip():
            continue
        section_body = {**body, "prompt": section_text}
        try:
            anima_prompt(section_body)
        except ValueError as exception:
            raise ValueError(f"Prompt {len(prompt_sections) + 1}: {exception}") from exception
        prompt_sections.append(section_body)
    if not prompt_sections:
        raise ValueError("Anima Prompt를 입력해 주세요.")
    return prompt_sections
