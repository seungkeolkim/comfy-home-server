"""운영 데이터나 GPU 없이 설치본과 CHS의 합성 자녀 Selection 순서를 비교합니다."""

import copy
import importlib.util
import json
from pathlib import Path

from home_server.style_evolution_selection import build_selection_ranking, next_selection_pair


def load_installed_stylelab_core(source_path: Path):
    """조사 대상 설치본의 순수 Core 함수를 별도 Module로 불러옵니다."""

    module_specification = importlib.util.spec_from_file_location("audited_stylelab_core", source_path)
    core_module = importlib.util.module_from_spec(module_specification)
    module_specification.loader.exec_module(core_module)
    return core_module


def compare_always_losing_child(core_module) -> dict:
    """기존 10개 모두보다 선호도가 낮은 자녀 1개의 배치 경로를 비교합니다."""

    reference_scores = {f"reference-{index:02d}": 10000 + index * 100 for index in range(10)}
    parent_identifiers = list(reference_scores)[-3:]
    original_selection = {
        "batch_id": "synthetic-batch", "candidate_ids": ["synthetic-child"],
        "parent_ids": parent_identifiers,
        "parent_scores": {identifier: reference_scores[identifier] for identifier in parent_identifiers},
        "history": [],
    }
    chs_selection = copy.deepcopy(original_selection)
    chs_selection.update(placement_policy="full-ladder-placement-v2", reference_ids=list(reference_scores), reference_scores=reference_scores)
    original_combinations = [{"id": identifier} for identifier in parent_identifiers + ["synthetic-child"]]
    original_trace = []
    chs_trace = []
    for _ in range(30):
        next_pair = core_module.selection_next_pair(original_selection, original_combinations, original_selection["history"])
        if next_pair is None:
            break
        first_identifier, second_identifier = [candidate["id"] for candidate in next_pair]
        original_trace.append([first_identifier, second_identifier])
        original_selection["history"].insert(0, {"type": "selection_vote", "batch_id": "synthetic-batch", "pair": {"a": first_identifier, "b": second_identifier}, "winner_id": second_identifier})
    for _ in range(30):
        next_pair = next_selection_pair(chs_selection, list(reference_scores) + ["synthetic-child"])
        if next_pair is None:
            break
        first_identifier, second_identifier = next_pair
        chs_trace.append([first_identifier, second_identifier])
        chs_selection["history"].insert(0, {"type": "selection_vote", "batch_id": "synthetic-batch", "pair": {"a": first_identifier, "b": second_identifier}, "winner_id": second_identifier})
    original_ranking = core_module.selection_ranking(original_selection, original_selection["history"])
    chs_ranking = build_selection_ranking(chs_selection)
    return {
        "evidenceType": "synthetic-source-execution", "browserVerified": False, "gpuUsed": False,
        "scenario": "one child loses to every reference; ten existing candidates; three parents",
        "stylelab": {"voteCount": len(original_trace), "pairs": original_trace, "slot": original_ranking["info"]["synthetic-child"]["slot"]},
        "chs": {"voteCount": len(chs_trace), "pairs": chs_trace, "slot": chs_ranking["info"]["synthetic-child"]["slot"], "admissionSlot": chs_ranking["admission_slot"]},
    }


if __name__ == "__main__":
    installed_core = load_installed_stylelab_core(Path("C:/Users/azzib/Desktop/ComfyUI/StyleLab/Anima-Style-Lab-2.0/app/core.py"))
    comparison_result = compare_always_losing_child(installed_core)
    Path(__file__).with_name("selection-policy-trace.json").write_text(json.dumps(comparison_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison_result, ensure_ascii=False, indent=2))
