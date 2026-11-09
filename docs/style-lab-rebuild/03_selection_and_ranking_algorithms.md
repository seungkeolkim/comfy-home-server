# 선별·순위 알고리즘 복원

이 문서의 수치와 Match별 처리는 기존 구현의 복원 기준입니다. 새 [여러 Prompt 탐색](20_web_ux_fusion_multi_prompt_and_component_differences.md)은 같은 후보 A/B의 Case별 결과 묶음을 비교하고 조합 단위로 한 번 선택합니다. Prompt별 투표는 제공하지 않습니다. Match·Elo·Placement·Selection·Undo 계약을 별도 검증하며 Prompt 수만큼 한 표를 중복 반영하지 않습니다.

## 기본 수치와 정렬

현재 `core.py` 기준입니다. 이 수치는 일반 Elo 관례에서 추측하지 않고 원문 그대로 복원해야 합니다.

| 항목 | 값·계약 |
| --- | --- |
| 시작 Elo | 10000 |
| Rating Scale | 10 |
| 일반 투표 K | 320 |
| 기대 승률 | `1 / (1 + 10 ** ((rating_b-rating_a)/4000))` |
| 새 점수 | 기존 값에 `K*(관측 승패-기대 승률)`을 더해 Python `round` |
| 평가됨 | `matches >= 1` 또는 `placed=True` |
| 순위 정렬 | Elo 내림차순 → 승률 내림차순 → 경기 수 내림차순 → 오래된 생성 순 → ID |
| Tier | S 10%, A 다음 20%, B 다음 40%, C 다음 20%, D 마지막 10% |
| 진화 부모 | 평가된 후보의 상위 30%, `top_tier_cut`의 정수 경계 |
| Tier 확정 경기 수 | `round(log2(max(pool_size,2)))+3` |
| 경계 동점 수동 해소 상한 | 동일 점수 후보 6개 |

예: 동점 10000 대결에서 A가 이기면 일반 Elo는 10160 / 9840입니다. `round`의 Tie 처리도 언어마다 다르므로 Golden Fixture로 고정합니다. Tier의 +/- 표시는 각 Tier 구간을 3등분한 표시용 값이며 부모 선택 기준은 기본 S/A입니다.

## 대결 선택 우선순위

`Engine._priority_pair`, `_fresh_pair`, `_placement_pair`, `_league_pair`를 함께 복원합니다.

1. 사용자가 시작한 Tune/Improve의 대결이 모든 Arena Mode보다 우선합니다.
2. Auto에서는 새 후보끼리 비교 또는 기존 Ladder에 신규 후보 배치를 먼저 처리합니다.
3. 상위 30% 경계의 작은 동점 집단을 해소합니다.
4. Auto에서 필요한 Placement·진화 Selection 대결을 처리합니다.
5. 작업이 없으면 전체 리그 또는 상위 Pool의 일반 대결을 고릅니다.

평가된 후보가 24개 미만일 때는 신규 후보 두 개를 먼저 비교합니다. 한 표로 두 후보를 평가할 수 있게 합니다. 이미 진행 중인 Placement를 중간에 버리지는 않습니다.

일반 리그는 비교 횟수가 적은 후보를 우대하는 `1/(matches+1)` 가중치를 쓰며, Tier 확정 뒤에는 S/A/B/C/D에 각각 1.0/0.9/0.6/0.3/0.1 배수를 적용합니다. 직전 Pair 반복도 피하려고 시도합니다.

## 신규 Placement와 진화 Selection은 다릅니다

신규 Placement는 기존 Ladder의 점수를 고정한 채 신규 후보의 자리를 찾습니다. 양 끝 배치 간격은 `PLACE_GAP=480`, 내부 자리는 인접한 Ladder 점수 사이를 기준으로 계산합니다.

진화 Selection은 Batch 시작 시의 `parent_scores`와 `batch_id`가 필수입니다. 부모 점수는 비교 중 고정하고, 자녀의 승패·비슷함을 모아 배치를 재구성합니다. 이것을 매번 부모·자녀 양쪽 Elo를 일반 투표처럼 갱신하는 방식으로 단순화하면 원본 동작과 달라집니다.

### `selection_ranking` 복원 절차

1. 현재 Batch의 Vote만 추립니다. 과거 세대 Vote를 섞지 않습니다.
2. 부모 Ladder의 Rung별 승리·패배·비슷함을 자녀별로 모읍니다.
3. 이진 탐색 범위를 줄입니다. Tie는 해당 Rung 위쪽 검증으로 이어질 수 있습니다.
4. Vote가 모순되면 모순 수가 최소인 Slot 후보를 찾습니다. 복수 후보의 선택 규칙도 원문대로 유지합니다.
5. 같은 Slot의 자녀는 Head-to-head, 보조 Elo, ID 순으로 배치합니다.
6. 승격 여부를 바꿀 수 있는 경계만 추가 검증합니다. 모든 자녀를 완전 리그로 비교하지 않습니다.
7. 확정 순서를 해치지 않도록 자녀 점수를 배치합니다.

정확한 Slot 산식·검증 Pair 선택은 Snapshot의 `selection_votes`, `_bisect`, `_best_slots`, `_check_rung`, `selection_ranking`, `selection_next_pair`, `apply_selection_ratings`를 함께 옮깁니다. 이 문단은 해당 함수들의 대체 구현이 아닙니다.

## '비슷함'과 Undo

Skip은 일반 Elo의 0.5점 무승부와 같지 않습니다.

| Match Kind | 비슷함/Skip |
| --- | --- |
| league/top | 점수는 유지, Undo 가능한 Skip 기록 |
| tie | 같은 Pair·Elo 동점 질문을 다시 강요하지 않도록 기억 |
| place | `winner=None`인 Placement 비교 기록 |
| select | `selection_skip` 저장 후 Batch 배치 재계산 |
| tune | Tie 처리로 변형 평가 갱신 |
| improve | Round/최종 검증 단계에 맞는 별도 처리 |

일반 Vote는 후보 Elo·경기 수·승수, 영향을 받은 작가·LoRA의 전적, History를 함께 변경합니다. 양쪽에 공통으로 들어간 작가·LoRA는 해당 투표의 성분 승패 통계에서 제외합니다. Undo는 이미지 A/B 위치까지 돌려주어야 합니다.

현재 Undo Stack은 메모리의 최근 30개입니다. 새 프로젝트 구현은 Event Log를 저장해 재시작 후 Undo 범위를 명시하고, 다른 사용자의 최신 Vote를 조용히 되돌리지 않도록 Revision을 검사합니다.

## 새 구현의 비교 추천

위 우선순위와 산식은 기존 복원 기준입니다. 채택한 [비교 후보 추천](19_adopted_exploration_tools.md)은 진행 중 Pair·Placement·Evolution Selection·필수 동점 해소를 우선 처리한 뒤 일반 League/Top 및 허용한 추가 비교에 적용합니다. 비교 근거 부족·상대 분포·순위 경계·최근 Pair·Skip을 정책 Version과 함께 기록합니다. Elo 차이만으로 신뢰구간을 만들지 않으며 Match Kind별 Skip·Vote·Undo 의미도 바꾸지 않습니다. 기존 Golden Fixture와 새 추천 정책 Fixture를 나눠 검증합니다.
