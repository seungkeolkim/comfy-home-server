# 진화 1회: 부모 선정 → 자녀 생성 → Selection → 세대 확정

2026-11-11. 사용자 요청으로 투표·Elo·Undo 다음에 **진화 한 Cycle**을 연결합니다. 공통 성분 잠금 등 보조 기능보다 현재 프로젝트에서 다음 세대를 만들고 평가하는 행동을 우선합니다. 기존 여러 Prompt 비교·조합 카드·Viewer·Blind·STR 차이 화면은 유지합니다. 사용자 사용성 확인은 아직 받지 않았습니다.

## 사용자 확인 순서

1. `/style`에서 프로젝트를 열고 조합을 생성·선별합니다. 다음 세대는 **평가 완료 10개 이상**, 생성·배치 미완료 조합 없음, 상위 30% 경계 동점 해소, 현재 생성·취소 작업 없음이 필요합니다. 부족한 수와 이유를 화면에 표시합니다. 최소 평가 수를 임의로 낮추지 않습니다.
2. **이미지 생성 / 선별 / 그림체**에 있는 다음 세대 Panel에서 자녀 수를 정하고 **다음 세대 이미지 생성**을 누릅니다. 기본 6개, 1~32개입니다. 같은 프로젝트의 Workflow·Sampling Seed·해상도·Steps·CFG·Negative와 여러 Prompt를 사용합니다.
3. 성분 목록 없이 `자녀 조합 수 × Prompt 수 = 실제 장수`와 **확인 / 취소**만 표시합니다. 확인 전에는 GPU Job을 만들지 않습니다. 중복 공간이 부족하면 실제 준비 수를 알립니다. 확인창 취소는 준비 Batch도 취소합니다. 준비 중 Browser를 닫았으면 **자녀 이미지 생성**으로 이어가거나 취소할 수 있습니다.
4. 생성이 끝난 자녀부터 선별합니다. 모든 Prompt를 함께 보고 조합 단위로 한 표를 줍니다. **부모의 Elo·승패·경기 수·Skip은 고정**하고 자녀만 배치합니다. `비슷함`도 자녀 배치에 반영하며 일반 League Skip과 의미가 다릅니다. 같은 Browser의 최신 선택은 Undo할 수 있습니다.
5. 모든 자녀 이미지와 필요한 Selection이 끝나면 **N세대로 확정**을 누릅니다. 최하위 부모 아래로 배치된 자녀는 탈락하고, 진입한 자녀 수만큼 기존 하위 조합을 가능한 범위에서 퇴역시킵니다. 세대가 올라가고 다음 부모와 Checkpoint를 기록합니다. 확정은 이번 진화의 Undo 경계입니다.
6. **그림체 → 표시**에서 활성·진화 중 / 퇴역 / 취소 / 전체를 봅니다. 조합별 작은 이미지와 Viewer를 유지하며 퇴역·취소 이미지를 지우지 않습니다. 현재 활성 순위에 퇴역·취소 조합을 섞지 않습니다.
7. **이번 진화 취소**는 부모 세대의 평가 상태·A/B 위치로 돌아갑니다. 자녀 조합은 선별에서 제외하고 실제 이미지와 작업·선택 기록은 보존합니다. 생성 중인 자녀 Job에만 취소 의도를 전달합니다. 새 Match Token으로 과거 투표 재사용을 막습니다.

이번 개입 지점은 자녀를 2~6개 정도 만들어 **부모 선택·자녀 다양성·Selection 질문 수·확정/취소의 이해도**를 확인하는 것입니다. 다음 기능을 일괄 추가하지 않습니다.

## 생성·선별 규칙

- [04 원본 진화 계약](04_evolution_and_component_scores.md), [03 Selection 계약](03_selection_and_ranking_algorithms.md), 보관한 `core.py`·`engine.py`를 기준으로 합니다. Policy는 `style-evolution-v1`입니다.
- 현재 평가 구간의 평가된 활성 상위 `floor(N × 0.3)`을 부모로 고정합니다. 부모 추출 확률은 순위에 따라 선형으로 2배~1배입니다. Crossover의 부모 둘은 다르게 뽑습니다.
- Mutate / Crossover / Random은 각각 **1/3 확률**입니다. 작은 Batch에서 실제 개수가 정확히 1:1:1일 필요는 없습니다. 실제 Mode·부모 ID·선택 Seed·시도 수를 저장합니다.
- Mutate는 작가 STR ±0.3와 1~3회 구성 변경, LoRA STR ±0.2와 절반 확률의 구성 변경을 사용합니다. Crossover는 부모 성분을 합치되 중복은 첫 부모 값을 우선합니다. 모든 방식에 프로젝트의 사용 여부·최소/최대 개수·성분별 STR 범위를 적용합니다. LoRA-only도 지원합니다.
- 작가의 새 추출은 활성·퇴역 조합 Elo의 Ridge 기여도(60 Sweeps, Prior 2.0)와 부모 사용량을 반영합니다. 새 LoRA는 원본처럼 균등 선택합니다. 이 차이를 이미 같은 추천 정책으로 구현했다고 안내하지 않습니다. 관측 기여도는 원인·품질의 확정 지표가 아닙니다.
- 명시적인 독립 `clip_strength=0`을 상속하며 Model STR과 같았던 CLIP은 새 Model STR을 따릅니다. 부모의 파일 Identity가 확인된 LoRA는 계획 시 현재 SHA256을 다시 대조합니다.
- 기존 활성·퇴역·취소·미제출 조합과 새 자녀를 정규화한 Fingerprint로 중복 검사합니다. 최대 `요청 수 × 30`번 시도하며 실제 수가 부족할 수 있습니다. 작가·LoRA가 모두 비어 있는 진화 자녀는 만들지 않습니다.
- 부모가 실제 생성에 사용한 공통 Prompt 전개를 재사용합니다. Wildcard를 새로 전개하지 않습니다. 부모들의 실제 전개가 다르면 계획을 거부합니다. Prompt 표시 이름은 내용 비교에서 제외합니다.
- Selection은 최하위 부모부터 이진 배치 → 필요할 때 승격 경계 주변 추가 확인 → 같은 Slot의 자녀 경계 대결 순서입니다. 부모 Ladder 점수 고정, 보조 K 480, 간격 480, 위쪽 간격 240의 원본 산식을 유지합니다. Skip-only로 배치한 자녀도 `placed`로 평가 완료를 표시합니다.
- 최하위 부모 아래 Slot 0의 자녀는 탈락합니다. 자녀가 진입한 수만큼 기존 하위 조합을 퇴역시키되 자녀를 다시 제거하지 않습니다. 자녀 진입 수가 기존 조합 수보다 많으면 기존 조합 전체를 퇴역시켜도 활성 수가 늘 수 있습니다. 항상 같은 개수라고 보장하지 않습니다.

## 저장·충돌·작업 경계

- DB 17 → 18 Migration 전에 무결성을 검증한 원본 Backup을 만듭니다. 기존 7열 `style_candidates`와 실제 이미지·설정·Vote를 바꾸지 않고 Membership을 1세대 활성으로 Backfill합니다.
- `style_evolution_timelines`, `style_evolution_batches`, `style_candidate_memberships`, `style_generation_checkpoints`, `style_evolution_commands`를 추가합니다. 세대는 Project/Evaluation별로 분리하며 기존 계획은 1세대로 해석합니다.
- API는 `GET .../evolution`, `POST .../evolution-plans`, `POST .../evolution-batches/{id}/confirm|cancel`입니다. 실제 Job 제출·감시·부분 실패 재시도는 기존 Generation API를 재사용합니다.
- 계획은 Project Revision·Voting Revision·부모/점수를 고정합니다. 제출 전 Revision이 바뀌면 계획을 취소하고 다시 준비해야 합니다. 한 평가 구간에 준비·진행 Batch 하나만 허용합니다. 준비 중 일반 투표는 가능하지만 그 결과가 바뀌면 준비한 계획은 낡은 것으로 처리합니다.
- 준비·진행 Batch가 있으면 일반 조합 추가와 프로젝트 설정 변경·Rename을 막습니다. 진화 종료 후에는 다시 사용할 수 있습니다. 성분 제외·Prompt 이름 변경도 프로젝트 설정 변경이므로 이번 진화를 먼저 마쳐야 합니다. 생성 도중 설정을 바꿔 일부 자녀만 다른 조건으로 만들지 않습니다.
- 첫 자녀 제출 시 부모 세대 Checkpoint를 저장하고 Undo 경계를 시작합니다. Selection Vote·Skip·Undo는 기존 영속 Event와 Transaction을 사용합니다. 확정·취소는 Revision·Operation ID·Payload Hash를 검사하며 재전송은 저장된 응답을 반환합니다.
- 확정 시 목표 세대 Checkpoint에는 프로젝트 설정·평가 계약·Arena·Membership·생성 계획·Render·파일 SHA256/크기·Vote/명령 경계·Batch 결과가 들어갑니다. 이전 세대 Checkpoint에 이후 자녀를 넣지 않습니다. **Checkpoint 저장만 구현했으며 특정 세대로 복원하는 API·삭제 동작은 아직 없습니다.**
- 확정·취소한 진화의 재시도와 이전 세대에서 준비한 미제출 일반 계획은 거부합니다. 활성 진화의 실패·취소 Render만 기존 재시도로 제출할 수 있으며 성공·미확인 Render는 자동 복제하지 않습니다.
- Job 메모·파일 Stem·PNG Metadata에 실제 세대를 사용합니다. 예: `세대002-02 이미지 생성`, `세대002-조합01-Prompt01-<Render ID>.png`. 모델/프로젝트 관리 분류·출력 루트와 기존 Workflow 확장자는 유지합니다. 세대 확정 뒤 일반 조합 추가도 현재 세대를 사용합니다.
- 취소된 Batch의 늦은 완료가 활성 선별에 들어오지 않게 Membership을 검사합니다. 생성 파일은 해당 취소 기록에서 조회할 수 있습니다. 일반 생성 Job에 취소를 전달하지 않습니다.

## 이번 범위 밖

공통 성분 잠금, 북마크 보호, 계보별 부모 기회 보강, LoRA 장기 안정성 표시, 수렴 알림, 특정 세대 복원, Prompt 재시험, Fork, 다른 모델 Adapter, 융합은 후속입니다. 채택한 요구사항에서 제거하지 않았으며 이번 기본 진화 Cycle 완료와 구분합니다.

## 개발자 검증

- 원본 순수 Selection 함수를 AST로 추출하고 승리·패배·Tie를 섞은 30개 경로에서 Slot·다음 대결·점수·경계 순서를 비교했습니다.
- 격리 API·DB·실제 임시 PNG로 부모 고정, Selection Undo, 생존·탈락·퇴역, 확정/취소 멱등성, 동시 계획, 생성 중 취소, 계획 후 오래된 투표, 설정 충돌, 이전 계획 재사용 거부, Schema 17 Backup·외래 키, Checkpoint 파일 Hash·세대 경계를 검증했습니다.
- Browser에서 실제 10조합 × 3Prompt의 초기 생성·투표·동점 해소 → 자녀 3개 × 3Prompt 생성 → Selection·Undo·새로고침 → 2세대 확정 → 퇴역 Viewer → 다음 진화 취소를 확인했습니다. 320/390/768/1280px에서 가로 넘침과 JavaScript 오류가 없습니다. 확인창에서 성분 목록을 표시하지 않으며 취소 시 Job을 만들지 않았습니다.
- Python 전체 **466 Passed / 1 Skipped**입니다. 마지막 세대 표시·준비 Batch 취소 보강 후 관련 37개 테스트도 통과했습니다. 기존 프로젝트·고정 생성·피드백·그림체·Random 생성·투표와 새 진화까지 Browser 시나리오 7개를 통과했습니다. 운영 데이터에 자동 Vote·이미지 생성은 하지 않았습니다.

## 운영 반영

- CHS를 재기동했고 `running / healthy`입니다. `/style`, `/api/session`, 새 JavaScript는 HTTP 200입니다. 8389 Style Lab·ComfyUI 설정·모델·등록 Workflow는 변경하지 않았습니다.
- 운영 DB Schema 18, `quick_check=ok`, Foreign Key 위반 0건입니다. 반영 전후 기존 업무 테이블 19개의 행 수·내용 Hash가 같고, 기존 스타일 이미지 **20장 SHA256**도 같습니다. Job 187개, Request 3044개, 출력 행 7755개, 작가/태그 행 339개, Preset 3개, 프로젝트 1개, 계획 4개, 후보 16개, Vote Event 5개·명령 5개를 보존했습니다.
- 운영 실제 10개 조합·2개 Prompt·20개 이미지와 Viewer, 퇴역 필터, 320/390/768/1280px을 조회로 검증했습니다. Browser JavaScript 오류·생성/Vote/세대 처리 POST는 0건입니다. 기존 10개 중 평가된 조합은 6개이므로 남은 4개 선별을 안내하며 다음 세대 버튼은 비활성입니다. 운영 조합에 임의 점수를 넣지 않았습니다.
- 실제 운영 DB의 격리 복사본에도 17→18 Migration과 Membership 16개 Backfill을 검증했습니다. 원본 Vote·후보·Job 수는 동일합니다.
- 변경 전 소스·온라인/정지 DB·수량·Hash 기록은 `runtime/style-evolution-deployment-20261111-001152/`입니다. Migration 자체의 원본 Backup도 `runtime/backups/home_server_before_style_evolution_*.sqlite3`에 남습니다. 운영 Browser 기록은 `runtime/verification/style-evolution-production-browser-results.json`, 격리 진화 Browser 기록은 개발 worktree의 `runtime/verification/style-evolution-browser-results.json`입니다.
- 이번 작업은 기능 구현 요청이며 Commit·Push는 하지 않았습니다. 브랜치는 `feature/style-exploration-projects`, 기준 HEAD는 `0148dee`이며 변경사항을 사용자 확인용으로 남겼습니다. 사용자께서 자녀 생성·선별·확정/취소 흐름을 확인한 뒤 수정하거나 다음 단위를 정합니다.

## Commit 정리

2026-11-11 사용자 요청으로 진화 Cycle의 코드·UI·Migration·테스트와 관련 문서를 함께 Commit합니다. 기존 개발자 검증 기록을 유지하며 Push는 하지 않습니다. 이번 Commit 요청은 후속 기능의 구현 승인이나 사용자 사용성 확인 완료로 해석하지 않습니다.
