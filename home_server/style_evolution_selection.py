"""StyleLab의 고정 부모 Ladder로 진화 자녀의 생존과 승격 경계를 계산합니다."""

import math


STYLELAB_SELECTION_POLICY = "stylelab-parent-selection-v1"


def batch_history(selection: dict) -> list[dict]:
    """기록은 보존하되 현재 Batch의 부모·자녀 사이 유효한 Vote만 해석합니다."""

    allowed_identifiers = set(selection["parent_ids"]) | set(selection["candidate_ids"])
    history = []
    for vote in selection["history"]:
        if vote.get("batch_id") != selection["batch_id"]:
            continue
        if vote.get("type") not in {"selection_vote", "selection_skip"}:
            continue
        pair = vote.get("pair", {})
        first_identifier, second_identifier = pair.get("a"), pair.get("b")
        if first_identifier not in allowed_identifiers or second_identifier not in allowed_identifiers:
            continue
        if vote["type"] == "selection_vote" and vote.get("winner_id") not in (first_identifier, second_identifier):
            continue
        history.append(vote)
    return history


def child_ladder_votes(selection: dict) -> tuple[list[str], dict]:
    """자녀가 기준 Ladder 각 위치에서 받은 승리·패배·비슷함을 시간순으로 모읍니다."""

    frozen_scores = selection["parent_scores"]
    ladder = sorted(selection["parent_ids"], key=lambda identifier: (frozen_scores[identifier], identifier))
    rung_by_identifier = {identifier: index for index, identifier in enumerate(ladder)}
    votes = {identifier: [] for identifier in selection["candidate_ids"]}
    for vote in reversed(batch_history(selection)):
        first_identifier, second_identifier = vote["pair"]["a"], vote["pair"]["b"]
        if first_identifier in votes and second_identifier in rung_by_identifier:
            child_identifier, parent_identifier = first_identifier, second_identifier
        elif second_identifier in votes and first_identifier in rung_by_identifier:
            child_identifier, parent_identifier = second_identifier, first_identifier
        else:
            continue
        result = "tie" if vote["type"] == "selection_skip" else "win" if vote["winner_id"] == child_identifier else "loss"
        votes[child_identifier].append((rung_by_identifier[parent_identifier], result))
    return ladder, votes


def child_auxiliary_scores(selection: dict) -> tuple[dict, dict]:
    """K 480 보조 점수를 자녀끼리의 순서 판정에 쓰되 부모 점수는 고정합니다."""

    scores = dict(selection["parent_scores"])
    children = set(selection["candidate_ids"])
    scores.update({identifier: min(scores.values()) for identifier in children})
    counts = dict.fromkeys(children, 0)
    for vote in reversed(batch_history(selection)):
        if vote["type"] != "selection_vote":
            continue
        first_identifier, second_identifier = vote["pair"]["a"], vote["pair"]["b"]
        first_expected = 1 / (1 + 10 ** ((scores[second_identifier] - scores[first_identifier]) / 4000))
        first_won = vote["winner_id"] == first_identifier
        updates = {
            first_identifier: round(scores[first_identifier] + 480 * (int(first_won) - first_expected)),
            second_identifier: round(scores[second_identifier] + 480 * (int(not first_won) - (1 - first_expected))),
        }
        for identifier, updated_score in updates.items():
            if identifier in children:
                scores[identifier] = updated_score
                counts[identifier] += 1
    return scores, counts


def selection_slot_bounds(votes: list, ladder_size: int) -> tuple[int, int]:
    """원본 이진 탐색과 동일하게 비슷함을 상향 확인의 출발점으로 처리합니다."""

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
    return lower_slot, upper_slot


def least_conflicting_slots(votes: list, ladder_size: int) -> list[int]:
    """모순된 선호가 있어도 원본과 같은 최소 모순 Slot 집합을 찾습니다."""

    costs = []
    for slot_index in range(ladder_size + 1):
        violations = sum(
            (result == "win" and slot_index <= rung_index)
            or (result == "loss" and slot_index > rung_index)
            or (result == "tie" and slot_index not in (rung_index, rung_index + 1))
            for rung_index, result in votes
        )
        costs.append(violations)
    return [slot_index for slot_index, cost in enumerate(costs) if cost == min(costs)]


def verification_rung(best_slots: list[int], slot_index: int, tried_rungs: set[int], ladder_size: int) -> int | None:
    """승격 경계를 바꿀 수 있는 애매한 구간과 위아래 인접 부모만 추가 확인합니다."""

    if len(best_slots) > 1:
        open_rungs = [index for index in range(best_slots[0], best_slots[-1]) if index not in tried_rungs]
        if open_rungs:
            return open_rungs[len(open_rungs) // 2]
    for window in ([index for index in (slot_index + 1, slot_index + 2) if index < ladder_size], [index for index in (slot_index - 2, slot_index - 3) if index >= 0]):
        if window and not tried_rungs.intersection(window):
            return window[0]
    return None


def build_selection_ranking(selection: dict) -> dict:
    """자녀의 이진 배치·경계 검증·동일 Slot 대결과 순서 보존 점수를 계산합니다."""

    history = batch_history(selection)
    ladder, child_votes = child_ladder_votes(selection)
    ladder_size = len(ladder)
    auxiliary_scores, counts = child_auxiliary_scores(selection)
    information = {}
    for identifier, votes in child_votes.items():
        tried_rungs = {index for index, _ in votes}
        lower_slot, upper_slot = selection_slot_bounds(votes, ladder_size)
        next_rung = None
        if votes and votes[-1][1] == "tie":
            higher_rung = votes[-1][0] + 1
            if higher_rung < upper_slot and higher_rung not in tried_rungs:
                next_rung = higher_rung
        if next_rung is None:
            open_rungs = [index for index in range(lower_slot, upper_slot) if index not in tried_rungs]
            if open_rungs:
                target_rung = (lower_slot + upper_slot) // 2
                if lower_slot == 0:
                    target_rung = lower_slot
                next_rung = min(open_rungs, key=lambda index: (abs(index - target_rung), index))
        best_slots = [lower_slot] if next_rung is not None else least_conflicting_slots(votes, ladder_size)
        information[identifier] = {"slot": best_slots[(len(best_slots) - 1) // 2], "best": best_slots, "rung": next_rung, "bisecting": next_rung is not None, "lo": lower_slot, "hi": upper_slot, "votes": votes, "tried": tried_rungs}
    head_to_head, played_pairs = {}, set()
    for vote in history:
        first_identifier, second_identifier = vote["pair"]["a"], vote["pair"]["b"]
        if first_identifier in information and second_identifier in information:
            played_pairs.add(frozenset((first_identifier, second_identifier)))
            if vote["type"] == "selection_vote":
                winner_identifier = vote["winner_id"]
                head_to_head[winner_identifier] = head_to_head.get(winner_identifier, 0) + 1
    slots = {}
    for identifier, child_information in information.items():
        slots.setdefault(child_information["slot"], []).append(identifier)
    ascending = []
    for slot_index in range(ladder_size + 1):
        ascending.extend(sorted(slots.get(slot_index, []), key=lambda identifier: (head_to_head.get(identifier, 0), auxiliary_scores.get(identifier, 0), identifier)))
        if slot_index < ladder_size:
            ascending.append(ladder[slot_index])
    if not any(child["bisecting"] for child in information.values()):
        maximum_votes = math.ceil(math.log2(ladder_size + 1)) + 5
        ranks = {identifier: index for index, identifier in enumerate(reversed(ascending), 1)}
        for identifier, child in information.items():
            if child["slot"] > 0 and len(child["votes"]) < maximum_votes and ladder_size - 3 < ranks[identifier] <= ladder_size + 3:
                child["rung"] = verification_rung(child["best"], child["slot"], child["tried"], ladder_size)
    frozen_scores = selection["parent_scores"]
    scores = {identifier: frozen_scores[identifier] for identifier in ladder}
    for slot_index, identifiers in slots.items():
        levels = sorted({head_to_head.get(identifier, 0) for identifier in identifiers})
        lower_score = frozen_scores[ladder[slot_index - 1]] if slot_index else frozen_scores[ladder[0]] - 480
        upper_score = frozen_scores[ladder[slot_index]] if slot_index < ladder_size else frozen_scores[ladder[-1]] + 240 * (len(levels) + 1)
        for identifier in identifiers:
            level = levels.index(head_to_head.get(identifier, 0)) + 1
            scores[identifier] = round(lower_score + level * (upper_score - lower_score) / (len(levels) + 1))
    boundary_pairs = []
    promotion_cut = len(ascending) - ladder_size
    references_finished = not any(child["rung"] is not None for child in information.values())
    if references_finished and 0 < promotion_cut < len(ascending):
        lower_identifier, higher_identifier = ascending[promotion_cut - 1], ascending[promotion_cut]
        if lower_identifier in information and higher_identifier in information and information[lower_identifier]["slot"] == information[higher_identifier]["slot"]:
            group = slots[information[lower_identifier]["slot"]]
            boundary_pairs = [(first_identifier, second_identifier) for index, first_identifier in enumerate(group) for second_identifier in group[index + 1:] if frozenset((first_identifier, second_identifier)) not in played_pairs]
    unfinished_children = {identifier for pair in boundary_pairs for identifier in pair}
    completed_identifiers = []
    for identifier, child in information.items():
        child["placementComplete"] = bool(child["votes"]) and child["rung"] is None and identifier not in unfinished_children
        if child["placementComplete"]:
            completed_identifiers.append(identifier)
    return {"ladder": ladder, "info": information, "ascending": ascending, "scores": scores, "counts": counts,
            "boundary_pairs": boundary_pairs, "completed_identifiers": completed_identifiers, "admission_slot": 0}


def next_selection_pair(selection: dict, ready_identifiers: list[str], ranking: dict | None = None) -> tuple[str, str] | None:
    """준비된 Case를 가진 자녀를 배치하고 같은 구간 신규의 남은 대결을 이어갑니다."""

    ranking = ranking or build_selection_ranking(selection)
    ready_set = set(ready_identifiers)
    waiting = [(len(child["votes"]), identifier, child["rung"]) for identifier, child in ranking["info"].items() if child["rung"] is not None and identifier in ready_set and ranking["ladder"][child["rung"]] in ready_set]
    if waiting:
        _, identifier, rung_index = min(waiting)
        return identifier, ranking["ladder"][rung_index]
    if any(identifier not in ready_set for identifier in selection["candidate_ids"]):
        return None
    return next((pair for pair in ranking["boundary_pairs"] if all(identifier in ready_set for identifier in pair)), None)


def apply_selection_choice(state: dict, choice: str) -> None:
    """Batch Vote만 누적하고 부모 전적은 바꾸지 않은 채 자녀 점수·경기 수를 재구성합니다."""

    selection = state["evolution"]
    match = state["match"]
    vote = {"batch_id": selection["batch_id"], "pair": {"a": match["a"], "b": match["b"]}, "type": "selection_skip" if choice == "similar" else "selection_vote"}
    if choice != "similar":
        vote["winner_id"] = match[choice]
    selection["history"].insert(0, vote)
    synchronize_selection_statistics(state)
    state["lastPair"] = [match["a"], match["b"]]
    state["match"] = None


def synchronize_selection_statistics(state: dict) -> None:
    """명시적 Elo 보정은 유지하면서 현재 부모 기준의 자녀 점수·전적을 재계산합니다."""

    selection = state["evolution"]
    ranking = build_selection_ranking(selection)
    history = batch_history(selection)
    rating_offsets = selection.get("ratingOffsets", {})
    for identifier in selection["candidate_ids"]:
        statistics = state["statistics"][identifier]
        decisive_votes = ranking["counts"][identifier]
        judged = bool(ranking["info"][identifier]["votes"])
        statistics["rating"] = (ranking["scores"][identifier] if judged else 10000) + rating_offsets.get(identifier, 0)
        statistics["matches"] = decisive_votes
        statistics["wins"] = sum(vote.get("winner_id") == identifier for vote in history if vote["type"] == "selection_vote") if decisive_votes else 0
        statistics["skips"] = sum(identifier in vote["pair"].values() for vote in history if vote["type"] == "selection_skip")
        statistics["placementPending"] = False
        statistics["placed"] = judged or identifier in rating_offsets
