# StyleLab 부모 Selection 복원 명세

사용자 정정에 따라 CHS의 `full-ladder-placement-v2`를 폐기하고 설치된 StyleLab의 진화 자녀 Selection을 복원합니다. 전체 Ladder 방식은 유지할 확장이 아니라 원본 동작을 잘못 파악한 구현 오류입니다. 새 정책 식별자는 `stylelab-parent-selection-v1`입니다.

이 문서는 구현 계약과 검증 결과입니다. 수정 전 관찰은 [2026-11-13 조사 기록](../stylelab-runtime-audit-2026-11-13/README.md)에 보존합니다.

## 유지할 범위

- 프로젝트마다 후보·평가·세대·투표 상태를 분리합니다.
- 같은 조합의 여러 Prompt 이미지를 한 조합으로 평가합니다. Prompt별로 별도 Elo 표를 만드는 방식으로 바꾸지 않습니다.
- 생성 계획과 실제 이미지 생성 제출, 세대 확정과 다음 세대 생성을 각각 분리합니다. Confirm은 다음 생성 Job을 자동 제출하지 않습니다.
- 융합·다듬기는 이번 복원 범위에 포함하지 않습니다. 원본의 북마크 보호 등 이번 범위 밖 기능까지 구현 완료했다고 주장하지 않습니다.

## 진화 자녀 Selection

원본 기준은 설치본 `app/core.py`의 `selection_votes`, `selection_ranking`, `selection_next_pair`와 `app/engine.py`의 `start_evolution`, `_generation_plan`, `finish_generation`입니다.

### 부모와 첫 비교

진화 시작 시 rated 조합의 상위 `floor(N × 0.3)`를 부모로 정하고 부모 ID와 Elo를 고정합니다. 최소 rated 조합 10개, 미배치 Random newcomer 없음, 상위 30% 경계 동점 해소, 부모 2개 이상이라는 시작 조건을 유지합니다.

자녀의 Ladder는 고정한 부모만 포함하며 낮은 Elo부터 정렬합니다. 첫 비교는 최하위 부모입니다. 자녀가 이 비교에서 패배하면 `slot=0`으로 끝나고 추가 위치 탐색이나 검증을 요구하지 않습니다. 최하위 부모를 이기면 남은 부모 범위를 Binary Search합니다.

`slot`은 자녀보다 낮은 부모 수입니다. `slot=0` 자녀는 탈락 대상이고 `slot>0` 자녀는 편입 대상입니다. 전체 기존 조합 사이의 정확한 순위를 찾은 뒤 생존을 판단하는 폐기 정책을 다시 적용하지 않습니다.

### 비슷함과 추가 확인

`similar`은 tie이며 승패·경기 수를 늘리지 않습니다. 바로 위 부모를 아직 비교하지 않았다면 그 부모를 다음에 확인합니다. 서로 모순되는 선호가 있으면 각 Slot의 모순 수를 계산하고 최소 모순 Slot 집합의 lower median을 선택합니다. tie를 즉시 승리나 생존으로 처리하지 않습니다.

모든 자녀의 초기 탐색이 끝나면 부모 수를 기준으로 한 승격 경계 주변 ±3위 자녀를 추가 확인합니다. `slot=0` 자녀는 추가 확인에서 제외합니다. 부모 상대 Vote 상한은 `ceil(log2(parent_count + 1)) + 5`입니다.

자녀끼리 비교는 부모 수만큼의 상위 집합 경계를 같은 Slot의 자녀가 걸칠 때만 엽니다. 해당 Slot 집단의 미비교 Pair를 한 번씩 확인합니다. 모든 동일 Slot 집단을 대상으로 Round-robin을 수행하지 않습니다.

### 점수와 세대 확정

부모 Elo는 Selection Vote로 바꾸지 않습니다. 자녀 간 순서에는 K480 보조 Elo와 자녀끼리 대결한 승수를 사용하되, 실제 자녀 Elo는 부모 Ladder의 Slot 사이에서 계산합니다. 같은 Slot에서 자녀끼리 승수가 같으면 같은 점수를 받습니다.

최하위 부모에게 한 번 패배한 자녀는 `lowest_parent_elo - 240`을 받습니다. 이는 진화 Slot의 보간 결과입니다. 일반 Random Placement의 Ladder 밖 간격인 480과 혼동하지 않습니다.

모든 자녀 이미지와 필요한 부모 이미지가 준비되고 남은 Selection이 없어야 Confirm할 수 있습니다. Confirm은 `slot=0` 자녀를 탈락시키고 `slot>0` 자녀를 편입합니다. 편입 수만큼 기존 조합의 최하위를 제외한 뒤 전체 생존자에서 다음 상위 30% 부모를 다시 계산합니다. 생존 편입과 다음 부모로 승격은 다른 결과입니다. 원본은 북마크 `kept` 후보를 제외 대상에서 보호하므로, 해당 기능이 없는 CHS 결과를 보호 상태가 있는 원본 Pool과 완전히 같다고 주장하지 않습니다.

## Random 신규 조합은 별도 동작

일반 Random newcomer는 Evolution 자녀에 포함하지 않습니다. 기존 rated 전체 Ladder를 고정하고 중앙부터 Binary Search합니다. 내부 Slot Elo는 양옆 점수의 평균이며 Ladder 아래·위는 각각 480 간격입니다. 기준 조합이 전혀 없고 신규가 하나뿐이면 Elo10000의 anchor가 됩니다.

원본의 fresh 비교 조건도 복원합니다. 진행 중 Placement가 없고 rated 조합이 24개 미만이며 newcomer가 2개 이상이면 신규끼리 일반 Elo 한 판을 비교합니다. 승패가 정해지면 두 조합 모두 rated가 됩니다. rated 23개에서는 이 경로를 사용할 수 있고 24개부터는 전체 Ladder Placement를 사용합니다. 이미 시작한 Placement는 먼저 완료합니다.

## 생성 UI와 API

사용자가 Random 신규 추가와 진화 자녀 생성을 명시적으로 선택할 수 있어야 합니다. Pool 수나 준비 상태를 보고 한 종류의 요청을 다른 생성 방식으로 바꾸지 않습니다.

| 의도 | API | 결과 |
| --- | --- | --- |
| 무작위 신규 조합 추가 | `POST /api/style-projects/{projectIdentifier}/random-generation-plans` | 같은 현재 세대에 Random 조합 계획 생성 |
| 다음 진화 자녀 준비 | `POST /api/style-projects/{projectIdentifier}/evolution-plans` | 고정한 상위 부모로 다음 세대 계획 생성 |
| 자동 분기하던 기존 진입점 | `POST /api/style-projects/{projectIdentifier}/candidate-generation-plans` | 폐기·제거하며 호환용 자동 분기로 남기지 않음 |

두 생성 경로 모두 기존 성분 설정·중복 방지·다중 Prompt 전개와 생성 제출·재시도 흐름을 재사용합니다. 진화 준비 조건이 부족하면 그 이유를 표시하며 Random으로 바꿔 실행하지 않습니다. 기존 세대 확정 후에도 다음 생성은 별도의 사용자 동작입니다.

## 기존 저장 상태 전환

- 전환 대상은 `planned`와 `active` Batch입니다. `confirmed` 결과·확정 이력·Checkpoint와 실제 이미지 파일은 소급 변경하지 않습니다.
- 부모 ID와 고정 점수는 해당 Batch가 기록한 부모를 사용합니다. 폐기된 전체 `reference_ids`가 새 Selection의 기준 집합으로 다시 쓰이지 않아야 합니다.
- 기존 non-parent 상대 Vote는 원본 기록을 보존하고 새 Selection 점수·경기 수·다음 Pair 계산에서 제외합니다. 기존 기록을 지우거나 부모와의 Vote인 것처럼 바꾸지 않습니다. 자녀끼리의 유효 Vote와 해당 부모 상대 Vote는 유지합니다.
- 현재 match와 token을 새 정책에 맞게 처리해 다른 Browser의 이전 token으로 무효한 상대에 투표할 수 없게 합니다. Undo Snapshot을 복원할 때도 새 정책으로 재해석하여 전체 Ladder 기준이나 non-parent 대결이 돌아오지 않게 합니다.
- `planned` 상태의 아직 제출하지 않은 계획과 `active` 상태의 진행 중 선별을 구분하고, 반복 전환해도 결과가 중복 적용되지 않게 합니다. 기존 Job·렌더 결과·프로젝트·Prompt 연결은 유지합니다.

## 검증 기준

1. 부모 3개·전체 기존 10개에서 첫 상대가 최하위 부모이고, 1패 후 종료·Elo 240 차이·부모 통계 불변을 확인합니다.
2. 승리·tie·모순 Vote·경계 Slot 자녀 대결의 각 단계에서 Slot·다음 Pair·점수·경기 수를 원본 Golden 함수와 대조합니다.
3. 경계 밖 동일 Slot 자녀에게 불필요한 Round-robin을 요구하지 않는지 확인합니다.
4. 실제 생성 API가 새 정책을 저장하고 Random 요청과 진화 요청을 서로 바꾸지 않는지 확인합니다. 정책 표기가 없는 과거 fixture만 통과하는 것으로 충분하지 않습니다.
5. non-parent Vote가 있는 기존 미확정 Batch, 현재 match, Undo, 반복 Migration을 함께 검증합니다. Confirm된 결과와 파일은 바뀌지 않아야 합니다.
6. rated 23개·24개, newcomer 1개·2개, 진행 중 Placement의 조합으로 fresh 비교 경계를 확인합니다.
7. 프로젝트 전환·다중 Prompt·Undo·세대 Confirm 이후 별도 생성의 기존 계약을 유지하는지 확인합니다.

기존 [자동 Placement 기록](automatic_placement_review.md)의 테스트 수치는 폐기 정책을 당시 구현대로 검증한 결과입니다. 이 명세의 원본 동등성이나 새 구현 검증 결과로 재사용하지 않습니다.

## 구현·검증 결과

- 관련 Python 테스트 89개를 나누어 실행해 모두 통과했습니다. 실제 API의 부모 3개 기준·1표 탈락, 원본 Golden 비교, Migration·Undo·파일 보존, 프로젝트·다중 Prompt·생성·삭제 경계를 포함합니다.
- 설치된 StyleLab `core.py`와 부모 수·자녀 수·선호를 달리한 250개 경로, 3,513표를 직접 대조하여 점수·순서·다음 Pair가 일치했습니다.
- 격리 Browser 5개 시나리오가 통과했습니다. Random 응답 유실·취소·Reload, 평가 완료 Pool에 Random 추가, 다중 Prompt 수정·재생성, 직접 조합 생성, 2·3세대 확정과 4세대 준비·취소입니다. Fake Comfy가 만든 임시 PNG를 사용하며 이번 검증에서 운영 GPU 생성은 수행하지 않았습니다.
- 운영 CHS는 DB Backup 후 재시작했습니다. `running / healthy`, `/api/session` HTTP 200, 로드된 정책 `stylelab-parent-selection-v1`, fresh 기준 24를 확인했습니다.
- 반영 당시 진행 중 생성과 미확정 Batch는 모두 0개였습니다. 운영 DB 32개 테이블의 내용 Hash가 반영 전후 동일하며 `quick_check=ok`, Foreign Key 위반 0건입니다. 진행 Batch 전환은 격리 회귀 테스트에서 검증했습니다.
- Backup·전후 검증 결과: `runtime/stylelab-parent-selection-deployment-20261113-071749/`. Browser 결과: `runtime/verification/style-evolution-browser-results.json` 등입니다.
- 운영 Browser의 기존 로그인은 만료되어 로그인 후 화면 조작은 재검증하지 않았습니다. 위 Browser 시나리오는 격리 서버에서 수행한 결과입니다.
