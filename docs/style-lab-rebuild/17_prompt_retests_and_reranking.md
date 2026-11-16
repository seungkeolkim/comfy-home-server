# 현재 조합의 Prompt 재시험과 순위 재평가

2026-11-11 구현 갱신: [Prompt 저장·Web 사용성 수정](style_web_usability_rework.md)으로 생성 후 새 Prompt 저장과 이전 활성 조합의 고정 재생성을 연결합니다. 새 조건은 별도 Evaluation으로 평가하고 이전 조건은 보존합니다. 아래의 독립 Trial Drop/Undo·보관·채택 전체는 후속 범위입니다.

새 프로그램의 **P0 요구사항**입니다. 현재 Style Lab에 이미 구현된 기능은 아닙니다. Prompt를 바꾼 뒤 다음 세대를 만들면 성분이나 Weight도 달라지는 문제를 해결합니다.

2026-11-10의 [여러 Prompt 일상 탐색](20_web_ux_fusion_multi_prompt_and_component_differences.md)에 맞춰 재시험 대상을 새 Prompt Set으로 확장합니다. Set의 일부 Case 수정·추가·삭제도 새 평가 계약으로 고정하고, 원본 조합의 성분·Weight를 모든 Case에 그대로 사용합니다. 아래 단일 Prompt 예시는 Case가 하나인 경우로 읽습니다. 원본/Trial 간 점수 비혼합 원칙을 유지하고 같은 Set 결과를 함께 보며 조합 단위로 한 번 선택합니다.

## 사용자 흐름

예: 현재 `12세대`의 상위 `10개` 조합을 새 Prompt로 생성하고, 시험 안에서 다시 비교해 일부를 Drop합니다. 결과를 채택해도 조합의 성분·Weight와 출발 세대는 그대로입니다. 그 뒤 실제 진화를 실행할 때 다음 세대를 만듭니다.

1. 현재 그림체 목록에서 **다른 Prompt로 시험**을 누릅니다.
2. 상위 N개와 기준 순위·선택 대상을 확인하고 새 Positive Prompt를 입력합니다. Negative도 필요할 때 명시적으로 수정합니다.
3. 조합과 생성 조건의 유지 내역을 확인하고 생성합니다.
4. 새 Prompt 이미지끼리 비교해 시험 내부 Elo를 쌓고, 원하지 않는 조합은 Drop합니다.
5. **시험으로 보관**, **시험 폐기**, **새 Prompt와 남은 조합 채택** 중 선택합니다.

기존 Prompt와 이미지·점수는 시험을 열거나 Drop하는 것만으로 바뀌지 않습니다. 원본과 새 결과를 나란히 볼 수 있지만 원본 평가와 Trial 평가 이미지를 하나의 Elo 대결로 섞지 않습니다. 다중 Prompt Trial에서는 A/B 양쪽의 동일 Case를 대응시킨 결과 묶음을 선택한 정책에 따라 평가합니다.

## 대상을 고정하는 규칙

생성 시점의 활성 평가 Pool에서 평가된 활성 후보를 현재 순위와 고정 Tie-break 순서로 정렬해 상위 N개를 Snapshot으로 선택합니다. 순위는 현재 세대에 도달한 Pool 기준이며, 현 세대에서 태어난 자녀만으로 제한하지 않습니다. 미평가 후보는 직접 선택할 때 별도 표시합니다. 향후 수동 선택을 확장하더라도 실제 대상 ID를 확정하고 보여줘야 합니다.

- N은 1 이상입니다. 가능한 후보 수보다 크면 입력을 수정하도록 안내하며 몰래 줄이지 않습니다.
- 1개 시험은 생성·보관할 수 있습니다. Elo 비교에는 성공한 활성 후보가 2개 이상 필요합니다.
- 순위가 나중에 바뀌어도 이미 선택한 대상은 자동 교체하지 않습니다.
- 시험 범위의 순위를 **시험한 N개 중 순위**로 표시합니다. 전체 Pool 순위로 부르지 않습니다.

후보별 작가·LoRA Identity와 Hash, 순서, STR, Trigger 적용 정책을 그대로 복제합니다. 현재 Registry 범위가 바뀌었어도 STR을 다시 뽑거나 Clamp하지 않습니다. 2026-11-17 [CLIP 고정 정책](lora_clip_strength_policy.md)에 따라 새 Prompt 생성은 CLIP 1이며 과거 원본은 유지합니다. 파일이 없어졌거나 바뀌면 재현 불가를 안내하고 생성 전에 해결하게 합니다.

Mutate/Crossover/Random과 새 조합 추출을 호출하지 않습니다. Candidate ID는 새 평가 범위에 맞게 발급하되 성분 Fingerprint는 원본과 같아야 합니다. Generation 번호를 올리지 않습니다.

## 생성 조건과 Seed

기본 변경 항목은 Prompt뿐입니다. Workflow Revision·모델·Sampling Seed·Steps·CFG·Sampler·Scheduler·해상도·입력 이미지·후처리는 원본 RenderPlan을 유지합니다. 시험 전 변경 내역을 보여줍니다. 다른 생성 설정도 바꾸려면 사용자가 명시적으로 선택하고 시험 조건 Snapshot에 기록합니다.

Sampling Seed는 기본적으로 원래 비교에 사용한 공통 Seed를 재사용합니다. 원본 Seed가 서로 다르면 이를 표시하고 공통 Seed를 선택하게 합니다. 몰래 같은 Seed였다고 취급하지 않습니다. 동일 Seed도 Prompt 변경에 따른 구도·Noise 해석 변화나 Runtime 차이까지 제거하지는 않습니다.

Wildcard·무작위 Tag는 새 Prompt에서 공통 내용으로 한 번 전개하고 모든 시험 후보에 공유합니다. 여러 Seed를 지원하면 Seed별 공통 전개를 저장합니다. 후보별 Style 삽입 부분만 다르고, Prompt 전개를 요청마다 다시 뽑지 않습니다. 실제 Encode 입력과 Metadata를 함께 보존합니다.

Home의 현재 일반 Anima 제출 경로는 `settings.seed`만으로 고정 Sampling Seed를 보장하지 않습니다. [05번 문서](05_generation_and_registered_workflows.md)의 고정 RenderPlan 경로로 제출하고, 생성 직전 Graph의 Seed와 전개 Prompt까지 검증합니다.

## 시험 내부 Elo와 Drop

새 Prompt는 다른 평가 조건이므로 각 시험 후보는 Elo **10000**, 승패·경기 수 **0**으로 시작합니다. 기존 Elo와 순위는 참고 정보로만 표시합니다. 작가·LoRA 통계도 새 시험의 관측을 원본에 누적하지 않습니다. 성분 Prior를 쓰려면 출처와 이전 Strength를 별도로 선택하게 하며, 후보 Elo의 암묵적 이전에 사용하지 않습니다.

A/B·Blind·Skip·Undo는 기존 계약을 사용하되 Trial/Evaluation 범위 안에서만 처리합니다. 시험 초기에는 모든 후보가 미평가이므로 신규 후보끼리 비교할 수 있어야 합니다. 기존 부모가 있는 Evolution Placement를 그대로 호출하지 않습니다. 2~23개 규모도 처리하고, 작은 N 때문에 24개를 채우도록 요구하지 않습니다.

**Drop은 해당 시험에서 제외하는 동작**입니다. 새 Pair·순위·부모 대상에서 제외하고 이유·시점을 기록합니다. 패배나 Elo 감점을 인위적으로 추가하지 않으며 이미 발생한 Vote는 남깁니다. 남은 후보의 Elo를 탈락 후보와의 Vote를 뺀 채 임의로 재계산하지 않습니다. 제외 전 대결을 Undo할 때도 양쪽 통계는 일관되게 갱신합니다.

채택 전에는 **Drop 취소**가 가능합니다. 원본 후보·이미지·북마크와 다른 시험에는 영향이 없습니다. Drop은 이미지 삭제가 아니며, 이미지 영구 삭제는 실제 참조와 영향을 확인하는 별도 동작입니다.

## 결과 채택과 다음 진화

시험은 같은 Project 안에 별도 Evaluation Revision을 만들지만 처음에는 비활성 Trial 상태입니다. 원본 Revision과 조건·이미지·순위를 덮어쓰지 않습니다.

| 동작 | 결과 |
| --- | --- |
| 시험으로 보관 | 다시 열어 평가 가능. 활성 탐색은 원본 유지 |
| 시험 폐기 | 비교·생성 대상에서 닫음. 데이터는 보관 정책에 따르며 영구 삭제와 구분 |
| 새 Prompt와 남은 조합 채택 | 시험 Revision을 활성 탐색으로 승격. 성공한 미제외 후보와 시험 Elo·이미지 유지 |

채택은 별도 Evolution이 아닙니다. 화면에는 `12세대 / Prompt 시험 B`처럼 출발 세대와 조건 구간을 함께 표시합니다. 다음 실제 진화는 13세대이며 새 Revision의 Generation ID를 사용합니다. 원본 Revision은 이전 조건의 기록으로 남습니다.

채택하지 않은 후보와 시험하지 않은 원본 후보는 새 순위에 자동 합류하지 않습니다. 추가하려면 같은 시험 조건으로 고정 조합을 추가 생성하고 평가해야 합니다. 원래 순위를 새 Prompt 순위로 가져오지 않습니다.

1개만 남아도 그림체 저장은 가능하지만 다음 진화는 별도의 최소 평가·부모 수 조건을 충족해야 합니다. 기본 최소 평가 수 10과 2개 이상 부모 등 정책을 사전 검증해 부족하면 추가 재시험 대상을 안내합니다. 부족분을 임의 변이로 만들어 채택을 완료하지 않습니다.

## 저장과 API 계약안

Elo를 Trial 테이블과 Candidate 테이블에 이중 저장하지 않습니다.

| Entity | 주요 정보 |
| --- | --- |
| `style_prompt_retest_sessions` | trial_id, project_id, source_evaluation_id, source_generation_id, source_event_sequence, source_timeline_revision, trial_evaluation_id, source_active_state_revision, 새 조건 Snapshot, status |
| `style_prompt_retest_entries` | trial_id, source_candidate_id, trial_candidate_id, source_component_fingerprint, source_rank, 제외 상태·사유 |

실제 조합·Elo·승패는 Trial Evaluation의 기존 `style_candidates`, Render는 `style_candidate_renders`, 비교는 `style_matches`와 `style_vote_events`에 저장합니다. 성분 Fingerprint는 조건 Hash와 분리합니다. Trial 후보·Render·Match가 같은 Project와 Trial Evaluation 소속인지 검증합니다. 원본 Generation ID는 출처 참조이며 다른 Evaluation의 Generation에 새 후보를 직접 매달지 않습니다. Trial Evaluation에 출발 번호를 갖는 시험용 Generation 레코드를 둡니다.

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/style-projects/{project_id}/prompt-retests` | 원본 대상·조건 Snapshot 고정, Trial 생성 |
| GET | `.../prompt-retests/{trial_id}` | 상태·대상·시험 순위 |
| POST | `.../prompt-retests/{trial_id}/renders` | 고정 조합 생성·실패 항목 재시도 |
| POST | `.../prompt-retests/{trial_id}/candidates/{candidate_id}/drop` | 시험에서 제외 |
| POST | `.../prompt-retests/{trial_id}/candidates/{candidate_id}/reinstate` | 채택 전 제외 취소 |
| POST | `.../prompt-retests/{trial_id}/adopt` | 조건·유지 대상 검증 후 활성 Revision 변경 |
| POST | `.../prompt-retests/{trial_id}/discard` | 시험 종료, 영구 삭제와 구분 |

투표·Undo는 기존 API에 `evaluation_revision_id`와 `trial_id`를 넣어 범위를 검증합니다. 생성·제외·채택도 Idempotency Key와 Revision Token을 검증합니다. 실패한 Render만 재시도하고 완료 여부가 모호하면 Home Job/Comfy History를 먼저 조회합니다.

원본에서 평가를 계속할 수는 있지만 Trial 대상 Snapshot은 바뀌지 않습니다. 채택 시 생성 당시의 활성 Revision과 상태 Revision을 비교합니다. 원본이 변경됐으면 409와 차이를 보여주고 현재 상태를 확인한 새 채택 요청을 받아야 합니다. 오래된 탭이 활성 탐색을 조용히 교체하지 않게 합니다. Callback도 Trial과 Timeline Token을 검사합니다.

## 세대 복원과 데이터 보존

채택 전 Trial은 원본 평가 Timeline에 속하는 종속 작업입니다. 원본 Checkpoint로 돌아갈 때 그 경계 이후 생성된 Trial의 이미지·이력·승패·Elo도 삭제 Preview와 경고 수량에 포함합니다. 같은 세대 번호에서 만들었더라도 Event Sequence가 이후이면 포함합니다.

Checkpoint 전에 존재한 Trial에 이후 평가·Drop 변경이 있다면 Trial도 당시 상태로 복원합니다. 따라서 Checkpoint에는 종속 Trial 상태와 Asset 참조가 포함되어야 합니다. 폐기했지만 보관 중인 Trial도 예외가 아닙니다.

명시적으로 **채택한 Revision은 독립 평가 구간**입니다. 원본을 복원해도 이를 연쇄 삭제하지 않습니다. 과거 Checkpoint에서는 Trial이었다고 해도 현재 독립 채택 구간이면 다시 비활성 Trial로 되돌리지 않습니다. 출처 Snapshot은 원본 삭제 후에도 해석할 수 있게 보존하고 공유 Asset은 유효 참조를 확인합니다. 복원 Preview에서 독립 채택 구간의 보존 사실을 표시합니다. 상세 삭제 계약은 [15번 문서](15_generation_restore_and_deletion.md)를 따릅니다.

## 수락 기준

- 상위 N개 선택 Snapshot이 고정되고 성분·순서·모든 Weight와 Strength가 원본과 같습니다.
- 생성 시 Mutate/Crossover/Random 호출과 원본 Generation 증가가 없습니다.
- Sampling Seed와 전개 Prompt가 고정되고 등록 Workflow Adapter를 사용합니다.
- 새 Elo는 10000/전적0이며 시험 Vote·Drop·Undo가 원본 통계를 바꾸지 않습니다.
- N=1 생성과 N=2 비교가 동작하고 실패·제외 후보는 새 Pair에 들어가지 않습니다.
- Drop이 가짜 패배를 만들지 않고 취소 가능하며 원본·다른 Trial을 보존합니다.
- 채택은 성공한 미제외 조합만 활성화하고 원본·미시험 후보의 옛 Elo를 섞지 않습니다.
- 세대 번호를 올리지 않고 출발 세대·Trial 조건을 표시합니다. 진화 조건 부족을 숨기지 않습니다.
- 중복 요청은 한 번만 처리하고 오래된 Token은 409입니다. 다른 탭 상태도 보존합니다.
- 세대 복원 시 종속 Trial을 Event 경계대로 복원·삭제하고 독립 채택 Revision과 공유 Asset은 보존합니다.
