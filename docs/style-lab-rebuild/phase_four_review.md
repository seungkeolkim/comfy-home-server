# 4단계: 실제 선별·Elo·Undo와 그림체 순위

2026-11-10. 사용자는 공통 성분 잠금보다 **생성 → 여러 Prompt 비교 → 투표 → 순위 확인 → Undo**의 한 흐름을 우선하도록 요청했습니다. 3B 잠금은 미루고 4A 선별·순위와 기존 여러 Prompt 화면의 실제 투표를 연결합니다. 기존 생성 확인창·조합 카드·작은 이미지·Viewer·STR 차이·사용 제외·Prompt 이름 편집은 유지합니다.

## 사용자 확인 순서

1. Home을 새로고침하고 **스타일 구성 → 프로젝트 → 선별**을 엽니다. 이미 생성한 조합을 바로 평가할 수 있습니다. 새 이미지 생성은 별도로 실행할 때만 합니다.
2. A/B의 모든 Prompt 결과를 스크롤해 보고 **A가 더 좋아요**, **B가 더 좋아요**, **비슷함** 중 하나를 선택합니다. Prompt마다 투표하지 않고 조합에 한 표만 반영합니다. 모든 Case 이미지가 준비되고 Browser에서도 로드돼야 투표가 활성화됩니다.
3. 선택하면 다음 비교가 자동으로 이어집니다. 일반 비교에서는 A/B 위치의 조합을 직접 고를 수도 있습니다. 신규 배치·필수 경계 동점 비교는 끝날 때까지 Pair 변경을 비활성으로 합니다.
4. **그림체**에서 프로젝트의 실제 순위·Elo·승패·평가 횟수·Skip을 봅니다. 순위는 그림체 탭에 통합하며 별도 탭은 추가하지 않습니다. 정렬은 Elo 높은 순 / 평가 횟수 많은 순 / 등록 순입니다. 미평가는 순위 `미평가`, Elo `—`로 표시합니다.
5. 조합 카드의 작은 이미지를 클릭해 모든 Prompt 결과를 넘겨 봅니다. 상세에도 해당 조합의 실제 전적을 표시합니다. 서로 다른 Seed 평가 조건은 나눠 보여주며 점수를 합치지 않습니다.
6. **선별 → 되돌리기**로 마지막 선택의 Elo·승패·Skip·성분 관측·신규 배치 상태와 이전 A/B 위치를 함께 복구합니다. 최근 30개를 DB에 보존하므로 서버 재시작·같은 Browser 새로고침 후에도 Undo할 수 있습니다.
7. 다른 Browser가 최신 선택을 한 경우 Undo 버튼을 비활성으로 하고 이유를 Title에 표시합니다. 다른 Browser의 최신 선택을 조용히 대신 되돌리지 않습니다. Browser 구분용 ID는 Local Storage에 보존하며 로그인 정보·Password는 저장하지 않습니다. Local Storage를 지우면 기존 Browser의 Undo 소유 식별도 바뀝니다.
8. Blind는 선별의 조합 이름과 그림체·상세의 순위·Elo를 가립니다. 기존 나란히/한 장씩, 보는 쪽 전환, 확대·이름 편집·차이 보기를 유지합니다.

이번 개입 지점은 작은 Batch를 생성하고 몇 번 선택한 뒤 실제 선호 순서와 점수·전적·Undo가 맞는지 확인하는 것입니다. 다음 기능을 일괄 추가하지 않습니다.

## 평가 규칙과 범위

- 정책 Version은 `style-arena-v1`입니다. [03 선별 원문 계약](03_selection_and_ranking_algorithms.md)과 보관한 `core.py`·`engine.py` Snapshot을 기준으로 합니다.
- 일반 League는 Elo 10000 시작, K 320, Scale 4000, Python `round`를 씁니다. 10000 대 10000에서 A 승리는 10160 / 9840이며 Prompt가 여러 개여도 경기 수는 각각 1입니다.
- League의 비슷함은 Elo·승패·경기 수를 유지하는 Skip입니다. 같은 Pair가 다시 나와도 새 Match Token을 발급하며, 방금 비교한 Pair를 가능하면 피합니다.
- 평가된 후보가 24개 미만이고 신규 후보가 둘 이상이면 신규끼리 먼저 비교합니다. 진행 중인 Placement는 중단하지 않습니다. 신규 후보 하나와 기존 Ladder를 비교하는 Placement는 Ladder 점수를 고정하고 신규 후보만 배치합니다. Ladder 바깥 간격은 480, 내부는 양옆 점수의 중간값입니다. Placement의 비슷함은 일반 Skip과 달리 배치 판단에 기록합니다. 첫 후보 하나는 원본과 같이 Elo 10000 Anchor로 배치하며 상대가 생기기 전에는 투표할 수 없습니다.
- 상위 30% 경계의 6개 이하 동점 집단을 우선 비교하고 Skip한 Pair·점수를 기억합니다. 일반 리그의 적은 경기 수 우대와 Tier 확정 후 배수도 원본 기준을 사용합니다.
- 순위는 평가됨 우선 → Elo → 승률 → 경기 수 → 생성 순 → ID입니다. `placed=True`인 신규 배치 완료 후보도 평가된 것으로 처리합니다.
- 일반 승패의 작가·LoRA 관측은 양쪽에 공통으로 포함된 성분을 제외합니다. 이 관측 통계와 Ridge 기반 성분 점수·진화 추출 확률은 별개이며 후자는 아직 연결하지 않았습니다.
- 이번에 사용하는 Match Kind는 `league`, `place`, `tie`입니다. Evolution Selection·Top Mode·Tune/Improve는 아직 생성하지 않으며 일반 Elo로 대신 처리하지 않습니다. 진화의 부모 점수 고정·자녀 Batch 배치·다음 세대 생성은 다음 구현 단위입니다.

## 저장·동시성·이미지 경계

- DB Schema 16 → 17 Migration에서 검증한 원본 SQLite Backup을 먼저 만들고 `style_voting_arenas`, `style_vote_events`, `style_voting_commands`를 추가합니다. 기존 후보·이미지를 복제하거나 기존 설정·Seed·점수를 추정해 이관하지 않습니다.
- 평가 상태는 Project/Evaluation ID별로 분리합니다. 생성 묶음이 달라도 같은 평가 조건의 완료 조합끼리는 비교하며, Seed가 달라진 평가 조건의 Elo는 섞지 않습니다. 이전 평가 조건을 선택해 그 조건 안에서 비교할 수 있습니다.
- 서버는 전체 Case의 최신 Render 완료·파일 가용 Flag·실제 파일 존재를 검사합니다. Browser도 모든 A/B 이미지 로드가 끝나기 전에는 투표하지 못하게 합니다. 실패·진행·삭제 파일을 누락한 채 남은 Case만 평가하지 않습니다.
- Vote는 현재 Match Token·평가 Revision·Operation ID를 받습니다. Undo는 같은 정보와 최신 Event ID를 검사합니다. Pair를 바꿀 때도 Revision을 갱신합니다. 이미 성공한 같은 Operation 재전송은 저장한 응답을 반환하고, 다른 Payload·오래된 상태는 409입니다.
- Vote·점수·전적·성분 관측·Undo Snapshot과 명령 응답을 하나의 Transaction으로 저장합니다. 일반 비교, Placement, 경계 동점 Skip을 같은 처리로 합치지 않습니다. Undo는 대상 Vote를 삭제하는 대신 취소 Operation을 남기고 이전 상태를 복구합니다.
- Undo해도 이후 만든 이미지·후보·일반 작업을 삭제하지 않습니다. 복구한 A/B에는 새 Token을 발급하여 과거 Token이 다시 유효해지지 않게 합니다. Undo Stack의 최근 30개 한도는 여러 번 Undo해도 늘어나지 않습니다.
- Browser는 명령 처리 중 연타·Pair 변경을 막고, 오래된 Polling 응답으로 최신 선택을 덮어쓰지 않습니다. 변경 없는 Polling은 비교 이미지 DOM과 Scroll을 유지합니다.

## 개발자 검증

- Python 전체 회귀 454 Passed / 1 Skipped. 이후 추가한 30개 Undo 한도·이미지 삭제·Schema 16 Migration을 포함해 선별·고정 생성·Random 생성 34개를 다시 통과했습니다.
- 보관한 원문의 순수 Elo·Placement 함수를 AST로 추출해 Golden 기준으로 사용했습니다. 승패·반올림, Tie 상향 경로, 최소 모순 Slot·양 끝/중간 Elo를 대조했습니다.
- 한 표의 중복 요청, 동시 상반된 Vote, 오래된 Token·Revision, 잘못된 Pair, 다른 Browser Undo, Skip의 점수 불변, 전적·성분 통계·A/B Undo, 서버 재시작·평가 조건 격리와 신규 이미지 보존을 확인했습니다.
- Playwright/Edge에서 기존 프로젝트·고정 생성·피드백·그림체 1/3/5 Prompt·Random 생성 회귀와 새 선별 사이클을 확인했습니다. 새 시나리오는 4조합 × 3Prompt = 12개 실제 임시 PNG를 만들고 투표·순위·Skip·Undo·재접속·다른 Browser·Blind·이미지 로드 실패·320/390/768/1280px을 검증했습니다. Browser JavaScript 오류는 없습니다.
- 운영 DB의 읽기 전용 온라인 Snapshot을 격리 DB로 복사해 16 → 17 Migration, 실제 생성된 6개 조합의 준비 확인, Vote·Undo·수치 복구·외래 키 무결성을 확인했습니다. 원본 DB·이미지·GPU에는 쓰지 않았습니다. 기록은 개발 worktree의 `runtime/verification/production-voting-clone/verification.json`입니다.
- 운영 반영 시에도 실제 사용자 Vote는 자동 생성하지 않습니다. 운영 Browser 검증은 이미지·버튼·초기 순위 조회까지만 합니다.


## 운영 반영과 사용자 확인 대기

- 운영 서버를 재기동했고 Container는 `running / healthy`입니다. `/style`과 `/api/session`은 HTTP 200입니다. 8389 Style Lab·Comfy 설정·모델·Workflow는 수정하지 않았습니다.
- 운영 DB는 Schema 17이며 `quick_check=ok`, Foreign Key 위반 0건입니다. 반영 전후 Job 186개, Request 3036개, 출력 DB 행 7747개, Tag 339개, Preset 3개, 프로젝트 1개, 생성 계획 4개, 후보 16개가 동일합니다. 프로젝트 설정 Hash와 기존 스타일 이미지 12장의 SHA256도 동일합니다.
- 운영 Browser에서 완료된 6개 조합·2개 Prompt·12개 이미지, 실제 투표 버튼 활성화, 미평가 순위, 정렬·Viewer·새로고침의 Match 유지와 320/390/768/1280px을 확인했습니다. JavaScript 오류와 생성·Vote·Undo POST는 0건입니다. 조회로 현재 Match가 준비된 Arena 1개만 생겼고 사용자 Vote Event·명령은 0건입니다.
- 변경 전 DB·소스·정지 직후 DB·보존 검사 기록은 `runtime/style-voting-deployment-20261110-212759/`입니다. Migration 자체도 `runtime/backups/home_server_before_style_voting_*.sqlite3`를 만들었습니다. 운영 Screenshot·Browser 기록은 `runtime/verification/style-voting-production-*`입니다.
- 이번 요청은 기능 구현이며 Commit·Push는 하지 않았습니다. 실제 사용자가 선별·순위·Undo 흐름을 확인한 뒤 수정하거나 다음 구현 단위를 정합니다.

## Commit 정리와 다음 기능 제안

사용자 요청으로 실제 투표·Elo·순위·Skip·Undo, Migration, 기존 UI 연결과 검증 문서를 함께 Commit합니다. 다음 제안은 잠금 등 부가기능보다 **평가된 조합에서 다음 세대 후보를 만들고 선별·확정하는 진화 1회**입니다. 먼저 부모 선정·자녀 수·Mutate/Crossover/Random 규칙과 평가 부족 안내를 작은 단위로 정리하고, 같은 프로젝트 Workflow·Prompt·Seed 조건으로 생성합니다. 생성 전에는 장수 확인창을 유지하며 성분 목록을 길게 보여주는 Preview를 다시 넣지 않습니다. 자녀 평가에서는 기존 부모 점수를 고정하는 Selection 계약과 세대 확정·취소·Checkpoint 저장을 연결해야 합니다. 공통 성분 잠금은 후순위로 유지합니다. 다음 제안은 구현 착수나 사용자 승인 기록이 아닙니다.
