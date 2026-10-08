"""Prompt 본문에서 시작하는 Anima 태그 참조와 cycle 검증을 확인합니다."""

import pytest

from home_server.tag_builder import resolve_tag_prompt, validate_tag_selection


def tag_entry(tag_id: str, tag_key: str, content: str, weight: float = 1) -> dict:
    """그래프 테스트에 사용할 태그 항목을 만듭니다."""

    return {
        "tag_id": tag_id, "tag_key": tag_key, "name": tag_id,
        "content": content, "weight": weight,
    }


def test_multi_hop_tag_selection_keeps_each_reference_independent() -> None:
    """Prompt에서 두 단계 내려가며 동일한 CHR 참조를 독립적으로 선택합니다."""

    selected_tags = [
        tag_entry("fight", "ACTION", "[TWOCHR], fight"),
        tag_entry("pair", "TWOCHR", "[CHR] and [CHR]"),
        tag_entry("character-a", "CHR", "character A"),
        tag_entry("character-b", "CHR", "character B"),
    ]
    validate_tag_selection("quality, [ACTION]", selected_tags)
    body = {"prompt": "quality, [ACTION]"}
    prompt, selected_path = resolve_tag_prompt(body, selected_tags, 11)
    assert prompt.startswith("quality, ")
    assert prompt.endswith(", fight")
    assert [item["tag_key"] for item in selected_path] == ["ACTION", "TWOCHR", "CHR", "CHR"]
    assert [item["depth"] for item in selected_path] == [0, 1, 2, 2]
    assert resolve_tag_prompt(body, selected_tags, 11) == (prompt, selected_path)


def test_shared_tag_pool_allows_all_combinations() -> None:
    """두 ACTION 항목이 같은 CHR 선택 집합을 공유합니다."""

    selected_tags = [
        tag_entry("pose", "ACTION", "[CHR], posing"),
        tag_entry("eat", "ACTION", "[CHR], eating"),
        tag_entry("a", "CHR", "character A"),
        tag_entry("b", "CHR", "character B"),
    ]
    results = {resolve_tag_prompt({"prompt": "[ACTION]"}, selected_tags, seed)[0] for seed in range(100)}
    assert results == {
        "character A, posing", "character B, posing",
        "character A, eating", "character B, eating",
    }


def test_weight_applies_to_each_referenced_tag_choice() -> None:
    """상위 참조와 하위 참조에 저장된 weight를 각각 적용합니다."""

    selected_tags = [
        tag_entry("common", "ACTION", "[CHR], common", weight=9),
        tag_entry("rare", "ACTION", "[CHR], rare", weight=1),
        tag_entry("character-a", "CHR", "character A", weight=9),
        tag_entry("character-b", "CHR", "character B", weight=1),
    ]
    chosen_paths = [resolve_tag_prompt({"prompt": "[ACTION]"}, selected_tags, seed)[1] for seed in range(1000)]
    assert sum(path[0]["name"] == "common" for path in chosen_paths) > 800
    assert sum(path[1]["name"] == "character-a" for path in chosen_paths) > 800


@pytest.mark.parametrize("selected_tags, message", [
    ([], "[ACTION]"),
    ([tag_entry("root", "ACTION", "[CHR]")], "[CHR]"),
    ([tag_entry("root", "ACTION", "[ACTION]")], "cycle"),
    ([tag_entry("root", "ACTION", "[PAIR]"),
      tag_entry("pair", "PAIR", "[CHR]"), tag_entry("character", "CHR", "[PAIR]")], "cycle"),
])
def test_selection_rejects_missing_candidates_and_cycles(selected_tags: list[dict], message: str) -> None:
    """랜덤 추첨 전에 누락과 직접·간접 cycle을 거부합니다."""

    with pytest.raises(ValueError, match=message):
        validate_tag_selection("[ACTION]", selected_tags)


def test_disconnected_cycle_does_not_block_prompt() -> None:
    """Prompt에서 닿지 않는 체크 항목의 cycle은 이번 요청에 영향을 주지 않습니다."""

    selected_tags = [
        tag_entry("root", "ACTION", "quiet scene"),
        tag_entry("unused", "LOOP", "[LOOP]"),
    ]
    validate_tag_selection("[ACTION]", selected_tags)
    assert resolve_tag_prompt({"prompt": "[ACTION]"}, selected_tags, 1)[0] == "quiet scene"


def test_possible_cycle_in_unselected_random_branch_is_rejected() -> None:
    """weight가 낮아도 선택 가능한 cycle 경로가 있으면 제출을 막습니다."""

    selected_tags = [
        tag_entry("safe", "CHR", "character A", weight=100),
        tag_entry("recursive", "CHR", "[ACTION]", weight=0.01),
        tag_entry("root", "ACTION", "[CHR]"),
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_tag_selection("[ACTION]", selected_tags)


def test_longest_possible_path_is_checked_before_submission() -> None:
    """같은 항목에 짧은 경로로 먼저 도달해도 긴 경로의 한도를 검사합니다."""

    selected_tags = [tag_entry("root", "ROOT", "[SHARED] [CHAIN0]")]
    for index in range(31):
        next_reference = f"[CHAIN{index + 1}]" if index < 30 else "[SHARED]"
        selected_tags.append(tag_entry(f"chain-{index}", f"CHAIN{index}", next_reference))
    selected_tags.append(tag_entry("shared", "SHARED", "done"))
    with pytest.raises(ValueError, match="깊이"):
        validate_tag_selection("[ROOT]", selected_tags)


def test_plain_anima_prompt_needs_no_tag_selection() -> None:
    """태그 참조가 없는 Anima Prompt는 원문 그대로 통과합니다."""

    assert resolve_tag_prompt({"prompt": "quiet scene"}, [], 1) == ("quiet scene", [])
