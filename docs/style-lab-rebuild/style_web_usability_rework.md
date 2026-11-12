# Prompt 저장 오류와 8389 기준 Web 사용성 재정리

2026-11-11. 기준 Commit `2cab3d1`. 새 기능 추가보다 저장 신뢰성과 기존 Style Lab Web의 편한 조작을 우선합니다. 원본 설치 위치는 `C:/Users/azzib/Desktop/ComfyUI/StyleLab/Anima-Style-Lab-2.0`입니다.

## 확인한 문제

- 서버가 이미지가 있는 프로젝트의 Prompt·해상도 등 변경을 HTTP 409로 거부했습니다. UI는 편집과 저장을 허용하면서 후속 기능 안내를 표시했습니다. 격리 Browser에서 2개 Prompt의 실제 임시 PNG를 만든 뒤 세 번째 Prompt 저장 시 기존 409를 재현했습니다.
- Frontend는 글로벌 `availableComponents`에 설치 LoRA 항목이 없으면 사용 불가로 판단했습니다. 명시적인 `false`와 미기록 상태를 구분하지 않아 저장 요청 전에 막히는 경우도 재현했습니다.
- 8389의 `web_browser/js/pages/settings.js`, `arena.js`, `evolution.js`, `styles.js`와 인증된 실제 Browser 화면을 비교했습니다. 8389는 짧은 저장 완료 표시와 이미지 중심 선별을 사용하지만, 8388은 구현 범위 Banner·진화 Panel·설명이 조작 앞에 쌓였습니다.
- 390px 운영 비교에서 첫 선별 이미지 위치는 8389 약 300px, 변경 전 8388 약 1,249px였습니다. 그림체 첫 이미지는 변경 전 8388 약 1,376px였습니다. 해당 데이터·Viewport의 Snapshot이며 고정 성능 수치가 아닙니다. 로그인 외 상태 변경 요청은 차단했습니다.

## 저장과 생성 조건

- 생성 여부와 관계없이 유효한 Prompt 추가·수정·삭제, Negative Prompt, 해상도·Sampling 조건을 저장합니다. 이름 변경과 Prompt 변경도 기존 관리 Rename 경로에서 한 요청으로 처리합니다.
- 기존 Plan·Render·이미지·Vote·Elo는 소급 변경하지 않습니다. 실제 조건이 달라지면 불변 Evaluation을 새로 만들고 현재 세대 번호를 이어갑니다. 표시 이름만 변경하면 기존 Evaluation을 유지합니다.
- 이전 조건의 순위·승패는 그대로 조회하고 새 조건의 점수와 섞지 않습니다. 저장 자체로 GPU 생성을 실행하지 않습니다.
- 하단에 저장 버튼과 `미저장 변경 / 저장 중 / 저장됨 / 저장 실패`를 고정합니다. 실패·충돌도 같은 위치에서 표시하며, 충돌일 때만 최신 설정 조회 버튼을 보여 줍니다. 실패한 초안·요청 ID는 기존 Session Storage에 유지합니다.
- 글로벌 사용 불가는 명시적인 `false`일 때 적용합니다. 설치 목록에 있지만 아직 별도 값이 없는 성분을 저장 차단 사유로 사용하지 않습니다.
- 준비·진행 중 진화와 충돌하는 변경은 계속 거부하되 저장 성공으로 표시하지 않고 입력을 유지합니다.

## 같은 조합으로 새 Prompt 확인

- 새 조건에 아직 생성물이 없으면 생성 화면에 **같은 조합으로 다시 그리기**를 제공합니다. 최근 이전 조건의 활성 조합을 Elo 순으로 최대 32개 고릅니다. 실제 수와 전체 Prompt 장수로 기존 확인창을 사용합니다.
- `/prompt-regeneration-plans`는 원본 ID의 프로젝트·평가 조건·상태·Revision을 검사하고 성분·순서·STR·독립 CLIP을 그대로 복사합니다. 변경한 추첨 범위를 원본 조합에 소급 적용하지 않습니다. 파일 Identity가 있는 LoRA는 현재 파일을 다시 대조합니다.
- 기존 CHS Plan·Preflight·Submit·감시·부분 실패 재시도·출력 분리·네이밍을 재사용합니다. Random·Mutate·Crossover를 호출하지 않습니다. 동일 Operation 재요청과 확인 취소는 같은 계획을 재사용합니다.
- 새 조건은 별도 평가를 시작하고 원본 결과도 계속 조회합니다. 이는 [17번](17_prompt_retests_and_reranking.md)의 고정 조합 생성 부분이며 독립 Trial의 Drop/Undo·보관·채택 전체가 구현됐다는 의미는 아닙니다.

## 화면 재정리

- `/style`에서 구현 범위 Banner·Phase 표시·Sidebar 설명을 제거하고 생성·진화 진입점을 둡니다. 예시 목업 `/style-preview`의 구분은 유지합니다.
- 선별은 이미지와 고정 선호 버튼을 중심에 둡니다. 진행 중 진화가 없으면 선별·그림체에 진화 Panel을 표시하지 않습니다. 다음 세대 생성은 생성·진화 화면에서 실행합니다. 진행 Batch의 확정·취소는 선별에서도 유지합니다.
- 직접 Pair 선택·양쪽 폐기는 펼침 영역에 두고 Elo·단건 폐기는 선별 이미지 아래와 카드에서 제공합니다. 2026-11-12부터 확대 Viewer는 사진 정보와 보기 기능만 표시합니다. 펼침 상태는 Pair 변경·Polling 뒤에도 유지합니다. 모든 Prompt를 세로 Scroll하는 방식도 유지합니다.
- 정상 Vote의 반복 저장 Toast와 상시 알고리즘 설명을 제거합니다. 이미지 Load 실패·저장 실패·Undo·생성 상태는 계속 표시합니다.
- 프로젝트 설정은 Prompt부터 편집하며 기존 Workflow·작가/LoRA 입력을 재사용합니다. 정적 설명을 줄이고 입력 결과·오류·작가 Bulk 등록 결과는 유지합니다. Viewer·Thumbnail Cache는 기존 CHS 공통 코드를 그대로 사용합니다. 선별 이미지도 Desktop은 원본, Mobile은 Cache Preview로 표시합니다.

## 검증과 운영

- Python 전체 480 Passed / 1 Skipped. 생성 뒤 세 번째 Prompt 저장·DB 재조회, 기존 Plan·파일 Hash·점수 보존, 이름+Prompt 동시 저장·폴더 이동, 고정 조합의 전체 Prompt 생성, STR/CLIP 보존·Revision·원본 검증을 추가했습니다.
- 새 Browser 검증은 2→3 Prompt 저장·Refresh·새 Session 조회, 409 실패 후 입력 유지·재저장, 4개 Prompt 전체 생성, 원본 보존, 320/390/768/1280px 저장 버튼과 첫 화면의 비교 이미지를 확인합니다. 기존 프로젝트·생성·피드백·그림체·Random·Vote/Undo·진화·관리 회귀도 함께 확인합니다.
- 반영 전 DB·소스·스타일 이미지 Hash를 Backup하고 재기동 뒤 조회로 대조합니다. 운영 데이터에 시험 Vote·점수·Prompt 변경을 넣지 않습니다. 반영 결과는 아래에 기록합니다. Commit·Push는 별도 요청을 기다립니다.

## 운영 반영 결과

- `feature/style-exploration-projects`, HEAD `2cab3d1` 위의 미Commit 변경으로 반영했습니다. Backup은 `runtime/style-web-workflow-deployment-20261111-023357/`에 소스·온라인/정지 SQLite·Hash Manifest로 보관했습니다.
- 반영 후 Schema 18, `quick_check=ok`, Foreign Key 오류 0, 기존 32개 업무 테이블의 내용 Hash 동일, 반영 직전 존재한 스타일 이미지 14장 Hash 동일을 확인했습니다. 사용자께서 반영 전까지 변경한 운영 상태를 기준으로 보존했습니다.
- CHS 8388 `healthy`, `/api/session` HTTP 200입니다. 기존 Style Lab 8389도 `/health` HTTP 200이며 변경·재기동하지 않았습니다.
- 운영 Browser는 현재 프로젝트 설정의 실제 입력 검사를 통과하고, 저장하지 않은 세 번째 Prompt를 Refresh 후 유지하는지 확인한 뒤 Browser 안에서만 되돌렸습니다. 서버 Prompt·Elo·이미지·Vote 변경 요청 0건, JavaScript 오류 0건입니다.
- 현재 실제 이미지로 Desktop 원본·Mobile Cache, Viewer 원본 전환, Elo/폐기 Dialog 취소, 고정 선호 버튼과 저장 버튼을 확인했습니다. 390px의 첫 비교 이미지는 약 390px 위치에 표시됩니다. `runtime/verification/style-workflow-production-browser.json`과 Screenshot에 기록했습니다.
- 스타일 Browser 시나리오 9개가 통과했습니다. Desktop 선별 원본 연결을 보강한 뒤 새 Prompt 검증과 Vote/Undo도 다시 통과했습니다. 마지막 가독성 정리 뒤 새 API 테스트 4개도 다시 통과했습니다.

## Commit 정리

2026-11-11 사용자 요청으로 Prompt 저장 수정·고정 조합 재생성·Web 화면 정리와 관련 테스트·문서를 함께 Commit합니다. 기존 검증 기록을 확인하고 Commit 전 Diff 검사를 통과했습니다. Push는 하지 않으며 후속 기능 구현은 별도 요청을 기다립니다.
