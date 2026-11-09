# 진화와 작가·LoRA 점수

아래 산식과 생존 규칙은 기존 구현의 복원 기준입니다. 새 구현에서는 [16번 문서](16_search_strategy_and_diversity.md)처럼 기본 Interactive Evolution을 유지하면서 계보별 부모 기회를 보강합니다. Prompt 변경 검증은 변이 없이 [17번 문서](17_prompt_retests_and_reranking.md)의 고정 조합 재시험을 사용합니다.

[20번의 여러 Prompt 탐색·성분 제외](20_web_ux_fusion_multi_prompt_and_component_differences.md)를 추가 반영합니다. 여러 Prompt 결과를 함께 보고 조합 단위로 한 번 선택하며 이를 부모 선정·성분 점수에 중복 없이 반영합니다. 성분 제외는 Random·Mutate·Crossover와 상속에 공통 적용하되 기존 후보·Elo를 수정하지 않습니다. 아래 기존 단일 Prompt 산식만으로 다중 결과 선별의 사용성까지 검증됐다고 판단하지 않습니다.

## 진화 후보 생성

현재 세대의 상위 S/A, 즉 평가된 후보 상위 30%를 부모로 씁니다. 진화 시작 시 Parent ID와 점수를 고정합니다. 최소 평가 수·동점 해소·진행 중 작업 조건은 `Engine._evolution_blocker`와 `start_evolution` 원문을 기준으로 하며 `MIN_RATED_FOR_EVOLUTION=10`입니다.

| 방식 | 현재 동작 |
| --- | --- |
| Mutate | 부모 A에서 작가 1~3명 교체·삭제·추가, 상속 작가 가중치 최대 ±0.3 |
| Crossover | 부모 둘의 작가 목록을 합치고 개수 범위 안에서 선택. 중복 태그는 A 쪽 상속값 우선 |
| Random | 설정 개수·가중치 범위의 새 후보 |

세 방식 비율은 1:1:1입니다. 부모는 순위에 따라 선형 가중치로 뽑아 최상위가 최하위 부모의 2배 확률입니다. 새 작가는 대략 다음 가중치로 선택합니다.

```text
preference(tag) = 2 ** (component_score(tag) / max_abs_score)
draw_weight(tag) = preference(tag) / (1 + current_parent_usage(tag))
```

기록이 없거나 전체 점수가 0이면 Preference는 1입니다. 최고는 2배, 같은 크기 음수는 0.5배입니다. 인기 작가가 모든 계보를 차지하는 것을 줄이되 낮은 점수 태그도 탐색합니다.

LoRA는 같은 진화 Mode를 따르지만 기존 `breed_loras`의 새 LoRA 선택은 Registry에서 균등 선택합니다. **작가의 점수 기반 새 태그 추출 가중치를 LoRA에도 이미 적용한다고 가정하면 안 됩니다.** LoRA 가중치 변이는 ±0.2이고, 절반 확률로 파일 교체·제거·추가를 시도합니다. 개별 LoRA 범위를 우선합니다.

작가와 LoRA를 각각 끌 수 있지만 둘 다 꺼진 후보는 막습니다. LoRA-only 탐색도 독립적인 정상 사용 사례입니다. 새 프로젝트의 '점수 이어받기'는 LoRA 점수도 제안 확률에 반영할지 명시적으로 정해야 합니다. 새 설계에서는 두 성분 모두 활용하되 탐색 하한을 유지하는 것을 권장합니다.

## 중복 방지와 생존

기존 중복 기준은 활성·퇴역 후보의 **Style 문자열**입니다. 후보 하나당 최대 30번 새 조합을 시도하고 실패하면 조합을 더 만들지 않습니다. 새 설계는 Component 순서·정밀도·Workflow/Evaluation Revision을 정규화한 Fingerprint로 중복을 판단합니다.

세대 확정은 다음 순서입니다.

1. 필요한 Selection이 끝났는지 검사합니다.
2. 부모 최하위보다 아래 Slot에 놓인 자녀는 탈락합니다.
3. 진입한 자녀 수만큼 기존 후보의 하위권을 제외하되 북마크는 보호합니다.
4. 탈락·제외 후보는 삭제하지 않고 Retired로 옮깁니다.
5. 새 상위 30%를 부모로 삼고 세대 Log·LoRA Snapshot을 저장한 뒤 Generation을 올립니다.

보호된 북마크 때문에 제거 가능한 기존 후보가 부족하면 활성 수가 정확히 고정되지 않을 수 있습니다. '언제나 동일한 개수'를 절대 불변식으로 이식하지 않습니다. 기존 수렴 신호는 최근 2세대에 살아남아 진입한 자녀가 없을 때의 안내이며 자동 Job 종료 명령이 아닙니다.

## 작가·LoRA 점수의 실제 산식

`core.artist_scores`는 Registry의 승률이 아니라 평가된 조합 Elo에 Ridge Regression을 맞춥니다. 작가·LoRA는 같은 성분 목록으로 계산합니다.

```text
row j: y_j = combo_elo_j - mean(rated_combo_elo)
prediction_j = sum(weight_ji * component_score_i)
minimize sum((y_j - prediction_j)^2) + 2.0 * sum(component_score_i^2)
```

Coordinate Descent 60 Sweeps, 출력 점수는 `round`, 사용 조합 수는 성분이 등장한 평가 조합 수입니다. Field가 적은 성분은 0 쪽으로 수축됩니다. 같이만 등장한 성분의 개별 기여는 관측만으로 정확히 식별할 수 없으므로 확정적 품질 지표로 부르면 안 됩니다.

현재는 활성·퇴역 조합을 함께 넣어 계산합니다. **조합을 삭제하고 Registry만 남겨서는 기존 점수를 유지할 수 없습니다.** 13번 문서는 실제 이 산식의 출력 Snapshot입니다.

## LoRA 안정성 기록

세대별 상위 후보에서 각 LoRA의 등장 수·평균·최소·최대 가중치와 동시 사용 Pair를 저장합니다. `LOCK_TOL=0.05`, 연속 3세대 안정 여부와 최소 5회 비교 근거 등을 함께 보아 안정성을 표시합니다. 높은 점수와 가중치 안정성은 서로 다른 정보입니다.

## 후순위 다듬기 복원 범위

- `tune`: 좁게/보통/넓게의 변형 폭, 변형당 목표 3회 비교, 상위 평가 변형의 0.10 폭 밀집 구간 평균을 0.05 단위로 추천. 합의 부족이면 기준값 유지.
- `improve`: 챔피언·Round 상태와 Jitter Schedule을 사용하고, 최종 확인은 다른 Seed 3개를 사용합니다. `tune`과 별도 구현입니다.
- 두 기능을 P2로 미뤄도 원문·데이터 Field·API 목록은 보관합니다. MVP에서 빈 기능 버튼만 노출하지 않습니다.
