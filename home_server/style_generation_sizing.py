"""StyleLab의 생성 규모와 프로젝트별 마지막 제출 수량을 공유합니다."""


GENERATION_COUNT_POLICY_VERSION = "stylelab-generation-counts-v1"
DEFAULT_RANDOM_COMBINATION_COUNT = 50
MAXIMUM_RANDOM_COMBINATION_COUNT = 1000
DEFAULT_EVOLUTION_CHILD_COUNT = 12
MAXIMUM_EVOLUTION_CHILD_COUNT = 60


def generation_sizing_from_plans(plans: list[dict]) -> dict:
    """최신 제출 계획에서 수량만 복원하며 미제출 계획·과거 소량 기본값은 제외합니다."""

    sizing = {
        "randomCombinationCount": DEFAULT_RANDOM_COMBINATION_COUNT,
        "randomMaximumCount": MAXIMUM_RANDOM_COMBINATION_COUNT,
        "evolutionChildCount": DEFAULT_EVOLUTION_CHILD_COUNT,
        "evolutionMaximumCount": MAXIMUM_EVOLUTION_CHILD_COUNT,
        "recommendedPopulationCount": DEFAULT_RANDOM_COMBINATION_COUNT,
    }
    restored_modes = set()
    for plan in plans:
        selection = plan.get("selection", {})
        mode = selection.get("mode")
        if mode not in {"random", "evolution"} or mode in restored_modes:
            continue
        if not plan["jobIdentifiers"] or selection.get("countPolicyVersion") != GENERATION_COUNT_POLICY_VERSION:
            continue
        count = selection.get("requestedCount")
        maximum_count = sizing["randomMaximumCount"] if mode == "random" else sizing["evolutionMaximumCount"]
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= maximum_count:
            continue
        count_field = "randomCombinationCount" if mode == "random" else "evolutionChildCount"
        sizing[count_field] = count
        restored_modes.add(mode)
    return sizing
