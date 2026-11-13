# 조사 시점 Source에서 확인한 차이

> **정책 해석 정정 · 역사 기록:** 전체 Ladder 선별을 의도적 확장으로 보던 판단은 폐기했습니다. 사용자 정정에 따라 StyleLab을 잘못 이해한 구현 오류로 분류하며, 후속 구현은 [부모 Selection 복원 명세](../style-lab-rebuild/stylelab_parent_selection.md)를 따릅니다. 아래 Source 위치와 비교 수치는 `3dbbb87` 조사 시점의 근거로 보존합니다.

이 문서는 조사 시점 파일을 읽은 결과입니다. 실제 Browser 결과와 문제 판정은 [조작 기록](02-browser-walkthrough.md)과 [재현한 문제·차이](04-runtime-findings.md)에 구분했습니다. 줄 번호는 [Inventory](evidence/source-inventory.json)에 기록한 파일 기준이며, 후속 변경된 Source의 줄 번호나 실행 결과를 뜻하지 않습니다.

설치본 루트는 `C:/Users/azzib/Desktop/ComfyUI/StyleLab/Anima-Style-Lab-2.0`입니다. 아래 `SL/`은 이 경로, `CHS/`는 이 저장소 루트를 뜻합니다.

## S01. 8389는 별도 평가 Engine을 만든 서비스가 아닙니다

`SL/web_server.py:94`의 `BrowserBridge`는 `app/bridge.py`의 `App`을 상속합니다. `post()`는 Browser에서 수행할 수 없는 Desktop 파일 동작을 분기하고, 대부분의 동작은 `super().post()`로 기존 Engine에 전달합니다. 따라서 8389 화면의 설명만 모사하기보다 `app/engine.py`와 `app/core.py`의 상태 전환을 함께 비교해야 합니다.

조사 시 `web_browser/js/pages/evolution.js`와 `web/js/pages/evolution.js`, `web_browser/js/pages/arena.js`와 `web/js/pages/arena.js`는 각각 SHA-256이 같았습니다. 이 두 화면은 제공된 Desktop용 JS와 Browser용 JS가 동일합니다. 다른 모든 파일이나 배포 바이너리가 동일하다는 증거는 아닙니다.

## S02. 진화 비교의 기준 집합이 다릅니다

| 항목 | 8389 설치본 | CHS |
| --- | --- | --- |
| 부모 | 시작 시점 상위 30% | 시작 시점 상위 30% |
| 자녀 배치 Ladder | 고정한 부모 집합 | 고정한 전체 기존 활성 집합 |
| 낮은 자녀 | 최하위 부모 아래면 탈락 위치에 배치 | 전체 순위표에서 위치를 찾은 뒤 부모 진입 경계로 생존 판정 |
| 자녀끼리 비교 | 승격 경계를 가르는 동일 Slot 위주 | 전체 Ladder의 같은 Slot 비교까지 사용 |

근거: `SL/app/core.py:1047,1141,1224`, `SL/app/engine.py:1700,1731`; `CHS/home_server/style_evolution.py:284`, `CHS/home_server/style_evolution_selection.py:6,15,104`.

영향: 자녀가 1개여도 상대 후보와 필요한 투표 횟수, 중간 평가 상태가 원본과 달라질 수 있습니다. 동일한 부모 정책이라는 설명만으로 동일한 선별을 복제했다고 볼 수 없습니다.

분류: **원본 오해에 따른 구현 오류**. 기존 `docs/style-lab-rebuild/automatic_placement_review.md`의 의도적 보강이라는 해석은 사용자 정정으로 폐기했습니다. 전체 Ladder 정책을 선택 가능한 확장으로 남기지 않고, 부모만 대상으로 최하위 부모부터 비교하는 StyleLab Selection을 복원합니다. 일반 Random newcomer의 전체 Ladder Placement는 별도 동작으로 유지합니다.

합성 입력으로 조사 당시 두 Source 함수를 실행한 결과도 [Trace](evidence/selection-policy-trace.json)에 남겼습니다. 기존 10개·부모 3개·모든 기준보다 낮은 자녀 1개에서 설치본은 최하위 부모와 **1회** 비교하고 종료했고, CHS는 전체 Ladder에서 **4회** 비교했습니다. 이는 Browser나 GPU를 사용한 결과가 아니며, 실제 프로젝트에서 항상 같은 횟수라는 의미도 아닙니다. `evidence/compare_selection_policies.py`는 당시 비교 절차의 기록입니다. 이후 Source가 바뀐 작업 트리에서 재실행한 결과를 이 과거 Trace와 같은 증거로 취급하지 않습니다.

## S03. 세대 취소의 데이터 효과가 다릅니다

- 설치본 `SL/app/engine.py:1610`은 자녀 이미지·조합·해당 Batch 선별 기록을 제거하고 Undo를 비웁니다. 생성 중이면 먼저 중지하도록 거절합니다.
- CHS `CHS/home_server/style_evolution.py:416`은 이전 Arena 상태를 복원하고 자녀를 `cancelled`로 보존합니다. 진행 중인 생성에는 취소를 요청합니다. 이미 생성된 이미지와 Job을 원본처럼 제거하지 않습니다.

영향: 같은 취소 버튼 뒤에 그림체·작업 목록에서 보이는 결과와 저장 공간이 다릅니다. 두 제품의 취소를 같은 동작이라고 설명하면 사용자가 결과를 예상하기 어렵습니다.

분류: **데이터 보존 정책 차이**. 실제 최종 삭제를 실행하지 않아도 확인창·취소 거절·보존 상태는 Browser에서 조사할 수 있습니다. 불가역 삭제 검증은 별도로 구분합니다.

## S04. 세대 번호의 의미가 다릅니다

- 설치본 `SL/app/engine.py:1750`은 현재 `selection.generation`을 확정 이력에 넣고 그 값을 1 증가시킵니다. 진화 화면의 `현재 N세대`는 이 값을 표시합니다.
- CHS `CHS/home_server/style_evolution.py:284,407`은 `sourceGeneration`과 `targetGeneration=source+1`을 나누고, 확정 시 현재 번호를 Target으로 저장합니다.

영향: 화면에 같은 `현재 N세대`가 있어도 생성 중인 세대인지 마지막 확정 세대인지 의미가 다를 수 있습니다. 번호만 비교한 Screenshot으로 상태가 같다고 판단하면 안 됩니다.

분류: **표시·도메인 용어 차이**. Source에서 확인한 구조이며 실제 표시 순서를 Cycle 조작으로 확인해야 합니다.

## S05. 확정과 다음 생성의 결합은 현재 CHS에서 제거됐습니다

기준 Commit `3dbbb87`의 `CHS/web/style-preview/style-evolution.js`는 선별 완료 시 세대 확정만 제공하고, 확정 후 별도의 후보 생성 버튼과 장수 확인창을 사용합니다. 과거의 `confirm-next` 연속 실행 함수와 Session 복원도 제거됐습니다.

설치본 `SL/web_browser/js/pages/evolution.js:117,128`도 시작과 확정을 별도 API로 처리합니다. 따라서 과거의 결합 문제를 현재도 남아 있는 차이로 보고하지 않습니다. 운영 Browser에서 실제 반영 상태는 추가 확인합니다.

## S06. 선별 모드와 선택 직후 피드백이 다릅니다

설치본 `SL/web_browser/js/pages/arena.js:14,20,25,154`에는 자동·전체 리그·상위 30% 모드 선택, 선택 직후 1초간의 기존 Pair·선택 결과·Elo 변화 표시가 있습니다. Blind에서도 선택 후 숨긴 정보를 잠시 보여 줍니다.

현재 CHS `web/style-preview/style-comparison.js:44`와 `style-voting.js`는 Blind·조합 차이·다중 Prompt A/B·Undo를 제공하고, Vote 응답 후 비교 영역을 다시 Render합니다. 해당 두 파일에는 위 세 가지 선별 모드 선택이나 원본의 Reveal 대기 흐름이 없습니다.

영향: 자동 Pair가 바뀌는 이유와 한 번의 선택이 미친 영향을 파악하는 경험이 다릅니다. 실제 클릭 시 판정 후 화면 변화·Scroll·Blind 공개 범위를 확인해야 합니다.

분류: **선별 UX·선택권 차이**. 세 가지 모드를 모두 최소 구현에 포함할지는 완료 조건과 함께 결정해야 합니다.

## S07. 이미지 탐색 방식이 다릅니다

설치본 Arena의 `syncZoom()`과 이미지 클릭 Lightbox는 A/B 확대·이동과 큰 보기를 제공합니다. CHS의 현재 다중 Prompt 비교는 각 이미지를 누르면 별도의 공통 Viewer를 열고, 같은 조합 안에서 Prompt를 이전·다음으로 이동합니다. 두 방식은 같은 기능이 아닙니다.

또한 설치본 그림체·진화는 조밀한 Gallery와 선택한 조합의 Preview를 연결합니다. CHS는 조합 카드 하나에 여러 Prompt Thumbnail과 관리 버튼을 붙입니다. 다중 Prompt 때문에 필요한 차이와 이미지 크기·한 화면 정보량 문제를 구분해 실측해야 합니다.

분류: **UI 구조·확장 방식 차이**. Source만으로 사용성이 더 좋거나 나쁘다고 단정하지 않습니다.

## S08. 무작위 신규 조합을 추가하는 생성 경로가 다릅니다

설치본 `SL/web_browser/js/pages/library.js:252,392`의 만들기는 `/api/generate/random`을 호출합니다. `SL/app/engine.py:489`의 `start_random()`은 기존 평가 Pool 수에 따라 진화로 전환하지 않습니다. 별도 진화 화면의 `/api/evolution/start`와 구분됩니다. 새로 만든 무작위 조합도 선별의 신규 배치로 들어갑니다.

CHS `CHS/home_server/style_evolution.py:188`의 `prepare_candidate_generation()`은 Pool이 부족하면 Random 초기 계획을 만들고, `canPrepare`이면 진화 계획을 만듭니다. Pool이 최소 개수 이상인데 미배치·동점 등 Blocker가 있으면 주 후보 생성 요청은 거절합니다. `web/style-preview/style-evolution.js`는 이에 맞춰 주 버튼을 초기 후보/다음 세대 후보로 바꿉니다. 별도 Random API 구현이 있다는 사실과 현재 주 화면에서 자유롭게 같은 행동에 접근할 수 있다는 주장은 구분해야 합니다.

영향: 이미 평가한 Pool에 독립적인 신규 조합을 추가해 탐색하고 싶은 사용자의 진입점이 원본과 다릅니다. 진화의 Random 자녀가 일부 포함된다는 것만으로 무작위 신규 조합 추가가 동일하게 복제되지는 않습니다.

분류: **원본 복원이 필요한 생성 행동·진입점 차이**. 후속 결정은 Random `/random-generation-plans`와 진화 `/evolution-plans`를 화면과 API에서 명시적으로 분리하는 것입니다. Pool 상태에 따라 생성 방식을 바꾸던 `/candidate-generation-plans`는 폐기합니다. 기존 조작 기록은 이 복원 전 상태의 관찰로 남깁니다.

## S09. 선별의 Keyboard 조작이 다릅니다

설치본 `SL/web_browser/js/pages/arena.js:277`의 `onKey()`는 좌우 방향키와 Numpad 4/6으로 선호를 고르고, Enter로 비슷함, Backspace로 Undo를 실행합니다.

현재 CHS의 `web/style-preview` JS에서는 이에 대응하는 선별 Keyboard Handler를 찾지 못했습니다. 공통 Viewer `web/image-preview.js`의 이전/다음 방향키는 사진 탐색이며 선별 Vote 단축키와 다릅니다. 다른 전역 Handler의 영향까지 배제한 실제 결론은 Browser에서 입력·Dialog·Focus 상태와 함께 검증해야 합니다.

영향: Desktop에서 반복적인 선별을 수행하는 조작 수와 속도가 다를 수 있습니다. 여러 Prompt를 다 확인하지 않은 채 표가 입력되거나 Form의 Enter와 충돌하지 않도록 복제 범위를 정해야 합니다.

분류: **반복 조작 UX 차이**. 화면 버튼의 존재만 확인한 테스트로 Keyboard 동등성을 주장할 수 없습니다.

## S10. 북마크 보호 때문에 기존 조합 퇴역 결과도 달라질 수 있습니다

설치본 `SL/app/engine.py:1731`의 `removable`은 자녀가 아니면서 `kept`가 아닌 조합만 포함합니다. 실제 조사 종료 상태에서는 활성 22개 중 북마크 15개가 있었습니다. 132세대 확정 때 점수가 높은 기존 부모가 제외 목록으로 간 것만 보고 낮은 점수부터 퇴역시키는 코드가 고장 났다고 판단하면 안 됩니다. 북마크로 보호된 조합은 제거 후보에서 빠집니다.

CHS `CHS/home_server/style_evolution.py:386`의 퇴역 후보 계산에는 대응하는 북마크 보호가 없습니다. 현재 CHS에는 해당 보관 기능 자체가 연결되지 않았습니다. 이는 원본의 상태를 그대로 이관하거나 퇴역 결과를 비교할 때의 계약 차이이며, 이번 최소 Cycle을 검증하려고 북마크 전체를 추가 구현해야 한다는 의미는 아닙니다.

## S11. 진화 종료 안내는 제외한 기능으로 이어집니다

설치본 `SL/web_browser/js/pages/evolution.js:47`의 `endRule()`과 Engine의 수렴 판정은 연속 전멸 세대를 셉니다. 실제로 133·134세대 자녀가 모두 탈락하자 `전멸 세대 2 / 2`와 융합·다듬기 안내가 활성화됐습니다. 진화 시작 자체는 계속 가능합니다.

융합·다듬기는 이번 최소 복제 범위에서 제외했으므로 이 두 메뉴·알고리즘을 CHS에 추가하는 것을 선행 과제로 잡지 않습니다. 원본의 종료 안내를 그대로 복사해 미구현 화면으로 보내는 흐름도 만들지 않아야 합니다.
