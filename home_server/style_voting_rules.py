"""기존 Style Lab의 일반 Elo·신규 배치·비교 우선순위를 복원합니다."""

import math
from bisect import bisect_left
import random
import uuid

from .style_evolution_selection import apply_selection_choice, next_selection_pair


VOTING_POLICY_VERSION = "style-arena-v2"
FRESH_NEWCOMER_LADDER_THRESHOLD = 24


def initial_candidate_statistics() -> dict:
    """생성만 완료한 후보는 Elo 10000·미평가 상태로 시작합니다."""

    return {"rating": 10000, "matches": 0, "wins": 0, "skips": 0, "placed": False}


def remove_deleted_candidate_state(state: dict, candidate_identifiers: list[str]) -> bool:
    """삭제한 조합의 Elo·현재 대결·Placement 참조를 지우고 이전 Undo의 부활을 막습니다."""

    deleted_identifiers = set(candidate_identifiers)
    removed_statistics = any(identifier in state["statistics"] for identifier in deleted_identifiers)
    match = state.get("match")
    placement = state.get("placement")
    affected_match = bool(match and deleted_identifiers.intersection((match["a"], match["b"])))
    affected_placement = bool(placement and deleted_identifiers.intersection([placement["identifier"], *placement["ladder"]]))
    affected_pairs = bool(deleted_identifiers.intersection(state["lastPair"]))
    affected_ties = any(deleted_identifiers.intersection(pair["identifiers"]) for pair in state["skippedTies"])
    if not any((removed_statistics, affected_match, affected_placement, affected_pairs, affected_ties)):
        return False
    for identifier in deleted_identifiers:
        state["statistics"].pop(identifier, None)
    if affected_match or affected_placement:
        state["match"] = None
    if affected_placement:
        if placement["identifier"] not in deleted_identifiers:
            state["statistics"][placement["identifier"]]["placementPending"] = False
        state["placement"] = None
    state["lastPair"] = [identifier for identifier in state["lastPair"] if identifier not in deleted_identifiers]
    state["skippedTies"] = [pair for pair in state["skippedTies"] if not deleted_identifiers.intersection(pair["identifiers"])]
    state["undoStack"] = []
    return True


def candidate_is_rated(statistics: dict) -> bool:
    """일반 대결 경험이나 완료한 Placement가 있는 후보를 구별합니다."""

    return not statistics.get("placementPending", False) and (statistics["matches"] > 0 or statistics["placed"])


def calculate_regular_ratings(first_rating: int, second_rating: int, first_won: bool) -> tuple[int, int]:
    """K 320·Scale 4000과 Python 짝수 반올림으로 일반 Elo를 갱신합니다."""

    exponent = max(-300, min(300, (second_rating - first_rating) / 4000))
    first_expected = 1 / (1 + 10 ** exponent)
    return round(first_rating + 320 * (int(first_won) - first_expected)), round(second_rating + 320 * (int(not first_won) - (1 - first_expected)))


def placement_position(votes: list, ladder_size: int) -> tuple[int, int | None]:
    """원본 이진 탐색·Tie 상향 확인·최소 모순 Slot 선택을 같은 순서로 수행합니다."""

    lower_slot, upper_slot = 0, ladder_size
    for rung_index, result in votes:
        if not lower_slot <= rung_index < upper_slot:
            continue
        if result == "win":
            lower_slot = rung_index + 1
        elif result == "loss":
            upper_slot = rung_index
        else:
            lower_slot = rung_index
    tried_rungs = {rung_index for rung_index, _ in votes}
    if votes and votes[-1][1] == "tie":
        higher_rung = votes[-1][0] + 1
        if higher_rung < upper_slot and higher_rung not in tried_rungs:
            return lower_slot, higher_rung
    open_rungs = [rung_index for rung_index in range(lower_slot, upper_slot) if rung_index not in tried_rungs]
    if open_rungs:
        middle_rung = (lower_slot + upper_slot) // 2
        return lower_slot, min(open_rungs, key=lambda rung_index: (abs(rung_index - middle_rung), rung_index))
    violation_counts = []
    for slot_index in range(ladder_size + 1):
        violations = 0
        for rung_index, result in votes:
            if result == "win" and slot_index <= rung_index:
                violations += 1
            elif result == "loss" and slot_index > rung_index:
                violations += 1
            elif result == "tie" and slot_index not in (rung_index, rung_index + 1):
                violations += 1
        violation_counts.append(violations)
    best_slots = [slot_index for slot_index, violations in enumerate(violation_counts) if violations == min(violation_counts)]
    return best_slots[(len(best_slots) - 1) // 2], None


def placement_rating(slot_index: int, ladder_scores: list[int]) -> int:
    """Ladder 바깥은 480 간격, 내부는 양옆 점수의 중간에 신규 후보를 배치합니다."""

    if not ladder_scores:
        return 10000
    if slot_index <= 0:
        return round(ladder_scores[0] - 480)
    if slot_index >= len(ladder_scores):
        return round(ladder_scores[-1] + 480)
    return round((ladder_scores[slot_index - 1] + ladder_scores[slot_index]) / 2)


def new_match(kind: str, first_identifier: str, second_identifier: str, **metadata) -> dict:
    """같은 Pair가 다시 나와도 이전 Token으로 투표할 수 없게 합니다."""

    return {"token": uuid.uuid4().hex, "kind": kind, "a": first_identifier, "b": second_identifier, "metadata": metadata}


def boundary_tie_match(state: dict, rated_identifiers: list[str]) -> dict | None:
    """상위 30% 경계의 6개 이하 동점 집단에서 아직 Skip하지 않은 Pair를 찾습니다."""

    statistics = state["statistics"]
    ordered_identifiers = sorted(rated_identifiers, key=lambda identifier: -statistics[identifier]["rating"])
    boundary_count = len(ordered_identifiers) * 3 // 10
    if not 0 < boundary_count < len(ordered_identifiers):
        return None
    boundary_rating = statistics[ordered_identifiers[boundary_count]]["rating"]
    if statistics[ordered_identifiers[boundary_count - 1]]["rating"] != boundary_rating:
        return None
    tied_identifiers = [identifier for identifier in ordered_identifiers if statistics[identifier]["rating"] == boundary_rating]
    if len(tied_identifiers) > 6:
        return None
    for first_index, first_identifier in enumerate(tied_identifiers):
        for second_identifier in tied_identifiers[first_index + 1:]:
            skip_key = {"identifiers": sorted([first_identifier, second_identifier]), "rating": boundary_rating}
            if skip_key not in state["skippedTies"]:
                return new_match("tie", first_identifier, second_identifier)
    return None


def league_match_weights(state: dict, identifiers: list[str], rated_identifiers: list[str]) -> list[float]:
    """적은 경기 수를 우대하고 Tier 확정 이후 원본 Tier 배수를 적용합니다."""

    statistics = state["statistics"]
    confirmation_count = round(math.log2(max(len(rated_identifiers), 2))) + 3
    tier_multipliers = [(0.1, 1.0), (0.3, 0.9), (0.7, 0.6), (0.9, 0.3), (1.0, 0.1)]
    weights = []
    ordered_ratings = sorted(statistics[identifier]["rating"] for identifier in rated_identifiers)
    for identifier in identifiers:
        candidate = statistics[identifier]
        weight = 1 / (candidate["matches"] + 1)
        if len(rated_identifiers) >= 2 and candidate["matches"] >= confirmation_count:
            rank = len(ordered_ratings) - bisect_left(ordered_ratings, candidate["rating"])
            percentile = rank / len(rated_identifiers)
            weight *= next(multiplier for boundary, multiplier in tier_multipliers if percentile <= boundary)
        weights.append(weight)
    return weights


def league_candidate_identifiers(state: dict, ready_identifiers: list[str]) -> list[str]:
    """진화 자녀를 제외하고 현재 Mode의 일반 리그에 참여할 기존 후보를 고릅니다."""

    statistics = state["statistics"]
    children = set((state.get("evolution") or {}).get("candidate_ids", []))
    rated_identifiers = [identifier for identifier in ready_identifiers if identifier not in children and candidate_is_rated(statistics[identifier])]
    if state.get("mode", "auto") != "top":
        return rated_identifiers
    creation_order = {identifier: index for index, identifier in enumerate(ready_identifiers)}
    ranked_identifiers = sorted(rated_identifiers, key=lambda identifier: (
        -statistics[identifier]["rating"],
        -(statistics[identifier]["wins"] / statistics[identifier]["matches"] if statistics[identifier]["matches"] else 0),
        -statistics[identifier]["matches"], creation_order[identifier], identifier,
    ))
    return ranked_identifiers[:max(2, len(ranked_identifiers) * 3 // 10)]


def choose_newcomer_match(state: dict, ready_identifiers: list[str], rated_identifiers: list[str]) -> dict | None:
    """자동 Mode에서만 진행 중 신규 Placement와 미평가 조합 비교를 이어갑니다."""

    statistics = state["statistics"]
    newcomers = [identifier for identifier in ready_identifiers if not candidate_is_rated(statistics[identifier])]
    placement = state["placement"]
    if placement and (placement["identifier"] not in newcomers or any(identifier not in ready_identifiers for identifier in placement["ladder"])):
        state["placement"] = placement = None
    if not placement and len(rated_identifiers) < FRESH_NEWCOMER_LADDER_THRESHOLD and len(newcomers) >= 2:
        first_identifier, second_identifier = random.sample(newcomers, 2)
        return new_match("league", first_identifier, second_identifier, fresh=True)
    if not placement and newcomers:
        if not rated_identifiers:
            statistics[newcomers[0]].update(placed=True, placementPending=False)
            return choose_next_match(state, ready_identifiers)
        ladder = sorted(rated_identifiers, key=lambda identifier: (statistics[identifier]["rating"], identifier))
        state["placement"] = placement = {
            "identifier": newcomers[0], "ladder": ladder,
            "scores": [statistics[identifier]["rating"] for identifier in ladder], "votes": [],
        }
        statistics[placement["identifier"]]["placementPending"] = True
    if placement:
        _, rung_index = placement_position(placement["votes"], len(placement["ladder"]))
        return new_match("place", placement["identifier"], placement["ladder"][rung_index], rungIndex=rung_index)
    return None


def choose_next_match(state: dict, ready_identifiers: list[str]) -> dict | None:
    """자동 선별 또는 수동 리그를 고르되 모든 Mode에서 상위 30% 경계 동점을 먼저 풉니다."""

    statistics = state["statistics"]
    selection = state.get("evolution")
    children = set(selection["candidate_ids"]) if selection else set()
    regular_identifiers = [identifier for identifier in ready_identifiers if identifier not in children]
    rated_identifiers = [identifier for identifier in regular_identifiers if candidate_is_rated(statistics[identifier])]
    mode = state.get("mode", "auto")
    if mode == "auto":
        newcomer_match = choose_newcomer_match(state, regular_identifiers, rated_identifiers)
        if newcomer_match:
            return newcomer_match
    boundary_match = boundary_tie_match(state, rated_identifiers)
    if boundary_match:
        return boundary_match
    if mode == "auto" and selection:
        pair = next_selection_pair(selection, ready_identifiers)
        return new_match("select", *pair, batchIdentifier=selection["batch_id"]) if pair else None
    rated_identifiers = league_candidate_identifiers(state, ready_identifiers)
    if len(rated_identifiers) < 2:
        return None
    for _ in range(10):
        first_identifier = random.choices(rated_identifiers, weights=league_match_weights(state, rated_identifiers, rated_identifiers))[0]
        remaining_identifiers = [identifier for identifier in rated_identifiers if identifier != first_identifier]
        second_identifier = random.choices(remaining_identifiers, weights=league_match_weights(state, remaining_identifiers, rated_identifiers))[0]
        if len(rated_identifiers) == 2 or {first_identifier, second_identifier} != set(state["lastPair"]):
            break
    return new_match("top" if mode == "top" else "league", first_identifier, second_identifier)


def apply_match_choice(state: dict, choice: str, components_by_candidate: dict) -> None:
    """Match Kind별 승패·Skip·배치와 공통 성분을 제외한 관측 통계를 갱신합니다."""

    match = state["match"]
    if match["kind"] == "select":
        apply_selection_choice(state, choice)
        return
    first_statistics = state["statistics"][match["a"]]
    second_statistics = state["statistics"][match["b"]]
    if choice == "similar":
        first_statistics["skips"] += 1
        second_statistics["skips"] += 1
    if match["kind"] == "place":
        placement = state["placement"]
        placement["votes"].append([match["metadata"]["rungIndex"], {"a": "win", "b": "loss", "similar": "tie"}[choice]])
        slot_index, next_rung = placement_position(placement["votes"], len(placement["ladder"]))
        if next_rung is None:
            played_votes = [result for _, result in placement["votes"] if result != "tie"]
            first_statistics.update(rating=placement_rating(slot_index, placement["scores"]), placed=True, placementPending=False)
            first_statistics["matches"] += len(played_votes)
            first_statistics["wins"] += played_votes.count("win")
            state["placement"] = None
    elif choice == "similar":
        if match["kind"] == "tie":
            state["skippedTies"].append({"identifiers": sorted([match["a"], match["b"]]), "rating": first_statistics["rating"]})
    else:
        first_statistics["rating"], second_statistics["rating"] = calculate_regular_ratings(first_statistics["rating"], second_statistics["rating"], choice == "a")
        first_statistics["matches"] += 1
        second_statistics["matches"] += 1
        (first_statistics if choice == "a" else second_statistics)["wins"] += 1
        first_components = {component["identifier"] for component in components_by_candidate[match["a"]]}
        second_components = {component["identifier"] for component in components_by_candidate[match["b"]]}
        for identifier in first_components ^ second_components:
            observations = state["componentStatistics"].setdefault(identifier, {"matches": 0, "wins": 0})
            observations["matches"] += 1
            observations["wins"] += int((identifier in first_components) == (choice == "a"))
    state["lastPair"] = [match["a"], match["b"]]
    state["match"] = None
