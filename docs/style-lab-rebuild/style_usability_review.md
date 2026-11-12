# 그림체 관리·표시 이름·공통 Viewer·고정 선별 버튼 개선

2026-11-11. 사용자 요청으로 localhost:8389의 실제 Style Lab을 조회하고 현재 `/style`의 관리·Viewer 동작을 보완합니다. 이번 구현은 Commit하지 않고 사용자 확인용으로 반영합니다.

## 8389에서 직접 확인한 차이

인증 후 `/api/status`, `/api/combos`를 조회하고 Browser에서 그림체 상세, Elo 수정 Dialog, 다중 선택 삭제 경고, Mobile 선별을 확인했습니다. Elo 저장·삭제·투표 요청은 보내지 않았습니다. Browser에서 차단·기록한 상태 변경 요청은 0건입니다. 동작의 세부 규칙은 현재 서비스의 `web_browser/js/pages/styles.js`, `arena.js`, `ui.js`, `app/bridge.py`, `engine.py`와 대조했습니다.

| 항목 | 8389의 동작 | 이번 CHS 반영 |
| --- | --- | --- |
| Elo 수정 | 상세 Elo 바로 옆에서 값 입력·저장, 승패 유지, Undo 초기화 | 카드·선별에서 수정, 여러 조합을 선택해 같은 값 적용, Enter 저장 |
| 진화 중 수동 Elo | 명시적 부모 수정은 고정 Ladder 기준도 갱신 | 부모 기준과 자녀 배치를 다시 계산, 자녀 직접 보정량도 후속 Vote에서 보존 |
| 삭제 | 선택한 조합·이미지 영구 삭제 확인, 다중 선택·선별 한쪽/양쪽 삭제 | 조합의 모든 Prompt·이전 재시도 이미지 폐기, 단건·다중·선별 한쪽/양쪽 진입점 |
| 관리 중 보호 | 진행 중 진화에 쓰는 조합은 삭제 제한 | 준비·진행 Batch를 먼저 끝낸 뒤 폐기. CHS Job 삭제 보호도 적용 |
| 이미지 상세 | 그림체를 고르고 원본·Elo 등 관련 동작 사용 | CHS 기존 Viewer의 소스·닫기·Focus·방향키 처리를 공통 사용, 조합 안의 Prompt만 이동 |
| Mobile 원본 | 원본 진입점 제공 | CHS와 같은 801px 기준: Mobile은 Thumbnail Cache Preview, Desktop은 원본 기본, 같은 창에서 원본 토글 |
| 선호 선택 버튼 | Mobile 한 장씩 보기에서 하단 A/B 버튼 제공 | Desktop/Mobile·나란히/한 장씩 모두 Scroll과 무관하게 하단 고정 |

부활·북마크·메모·다듬기 등 8389의 다른 기능 전체를 이번 요청만으로 일괄 구현하지 않습니다. 기존 채택 요구사항과 후속 단계는 유지합니다.

## 표시 이름과 파일 규칙

- `조합 A · N번째 생성` 표시는 제거하고 **`세대001-조합01`**을 카드·선별·Viewer·생성 결과에 공통 사용합니다. A/B는 현재 화면의 왼쪽·오른쪽 위치에만 사용합니다. 여러 Prompt는 Case 이름으로 구분합니다.
- [22번 결정](22_style_job_output_separation_and_project_rename.md)의 파일 규칙을 유지합니다. 새 파일 예시는 `세대002-조합03-Prompt02-<Render ID>.png`입니다. 확장자는 등록 Workflow 설정을 따릅니다.
- 새 조합 번호는 프로젝트의 같은 세대 안에서 생성 묶음을 넘어 이어집니다. 준비·취소·폐기한 번호도 다시 배정하지 않아 번호가 건너뛸 수 있습니다. 작업 메모의 생성 회차는 세대마다 `01`부터 시작하며 조합 번호와 구분합니다.
- 기존 계획·파일은 재작성하거나 Rename하지 않습니다. 과거 계획에 새 표시 Field가 없으면 당시 세대·계획 내부 조합 번호로 표시합니다. 과거 서로 다른 생성 묶음에 같은 파일 Prefix가 있으면 그 Prefix는 유지하며 실제 Render ID가 파일을 구분합니다.
- 새 조합의 `combinationNumber`, `displayName`은 불변 Plan JSON에 저장합니다. 기존 SQL 후보 ID·Component Fingerprint·실제 파일 경로는 표시 이름에 의존하지 않습니다.

## Elo 수정과 조합 폐기

- Elo는 조합 단위이며 모든 Prompt 결과에 같은 점수를 표시합니다. 직접 수정은 승패·경기 수·Skip을 유지하고 `placed`를 설정합니다. 0~1,000,000의 정수 값을 받습니다. 기존 Match·Placement·Undo는 재설정하고 최신 순위와 다음 비교를 준비합니다.
- 일반 Vote는 부모 Elo를 바꾸지 않습니다. **명시적 수동 수정만 예외**로 고정 부모 기준점을 바꾸며 기존 Selection 이력으로 자녀 점수를 다시 계산합니다. 수동 자녀 점수는 계산 점수와의 보정량으로 보존합니다. 진화를 취소해도 사용자가 직접 고친 기존 조합의 Elo는 유지합니다.
- 여러 평가 조건의 Elo를 한 번에 섞지 않습니다. 같은 평가 구간의 선택 조합을 단건 또는 일괄 수정·폐기합니다. 오래된 Revision·다른 프로젝트 ID·중복 대상·같은 Operation ID의 다른 요청을 거부합니다.
- `조합 폐기`는 8389의 영구 삭제 동작을 기준으로 합니다. 확인창에 모든 Prompt와 이전 재시도 이미지가 함께 사라지고 Undo할 수 없음을 안내합니다. 생성·취소 중인 조합, 준비·진행 진화의 조합, 삭제 보호된 Job의 조합은 폐기하지 않습니다.
- **2026-11-12 변경:** [폐기 후 잔여 정리](style_deletion_cleanup_review.md)에 따라 해당 조합의 CHS 요청·결과·Catalog·Render를 제거하고 빈 작업도 삭제합니다. 공유 작업은 다른 조합의 요청만 유지합니다. 현재 Elo·Placement·비교 캐시를 정리하며, 불변 Plan/Event/Checkpoint와 재생성 방지용 Membership 삭제 표시는 유지합니다. 폐기 조합을 실패 Render 재시도로 다시 만들지 않습니다.
- 기존 `style_voting_commands`에 확인한 폐기 의도·대상·진행 상태를 먼저 저장합니다. CHS의 기존 Output Catalog 삭제·경로/보호 검사·Cache 무효화를 재사용합니다. 일부 파일 삭제가 실패하면 완료로 처리하지 않고 `남은 이미지 폐기 다시 시도`를 표시합니다. 응답 유실·재전송·서버 재시작에도 같은 대상으로 이어갑니다.
- DB Schema는 18을 유지하며 새로운 삭제 DB·파일 휴지통·Cache를 만들지 않습니다. 이미지의 실제 삭제 전 DB 준비가 실패하면 파일을 지우지 않습니다. 이미 일부 파일을 지운 뒤의 실패는 영속 명령으로 남기고 이어서 완료합니다.
- Checkpoint에 들어 있는 이미지를 사용자가 영구 폐기할 수 있습니다. 후속 세대 복원 구현에서는 실제 Asset 유무를 확인하고 누락을 안내해야 하며, Checkpoint의 옛 경로만으로 폐기한 이미지를 복원했다고 처리하지 않습니다.

## CHS 코드 재사용과 화면 동작

- 기존 `web/app.js`의 이미지 소스 선택·열기·정리·Load/Error 안내, Dialog의 닫기·Escape·바깥 클릭·방향키 처리를 `web/image-preview.js`로 분리합니다. 일반 CHS 이미지·영상과 스타일 구성에서 같은 코드를 사용합니다. 기존 일반 결과물의 탐색 범위·영상 재생·삭제·Focus 정책은 유지합니다.
- 이미지 주소는 기존 `/api/outputs/preview/...`와 `/media/...`를 사용합니다. Thumbnail Cache의 크기·개수·Warmup 설정을 바꾸거나 별도 Cache를 만들지 않습니다. Mobile에서 원본 토글 전에는 Viewer도 압축 Preview를 요청합니다. Prompt를 옮겨도 보기 모드는 유지합니다.
- 외부 상태 변경 Polling은 열린 이미지 소스를 교체하지 않고 사진 식별 정보만 갱신합니다. 다른 화면에서 조합이 폐기되면 Viewer를 닫습니다. 마지막 Prompt에서 이동 버튼이 비활성화돼도 Focus를 창 안에 유지하여 방향키로 돌아갈 수 있습니다.
- **2026-11-12 Viewer 간소화:** Viewer에는 조합 이름·Prompt 이름·현재 순서와 닫기·이전/다음·원본 보기·원본 새 탭만 둡니다. 순위·Elo·전적·Elo 수정·조합 폐기는 Viewer에서 제거하고 카드와 선별의 관리 기능으로 제공합니다. 남는 화면 높이를 이미지에 배정하고 보기 버튼은 Desktop 한 줄, 좁은 Mobile 두 줄로 배치합니다. Blind에서는 식별 정보를 가립니다.
- 선호 버튼은 Viewport 하단에 고정하고 Mobile 메뉴의 실제 높이 위에 배치합니다. ResizeObserver로 높이를 반영해 메뉴·마지막 이미지·Toast와 겹치지 않게 합니다.

## 개발자 검증

- Python 전체 476 Passed / 1 Skipped. 수동 Elo 0·승패 유지·멱등성·동시 요청·다른 프로젝트 거부, 진화 중 부모 기준 갱신·자녀 보정 유지·취소, 전체 Prompt 삭제·Cache 접근 차단·다른 조합/Job 보존, 삭제 보호·오래된 Revision·DB 거부·부분 파일 실패 복구·네이밍/세대별 Job 회차를 검증했습니다.
- 1/3/5 Prompt 카드·Viewer, 기존 설정·생성·Random·선별·Undo·진화와 새 관리 시나리오를 Browser로 검증했습니다. 새 시나리오는 단건·일괄 Elo, Enter 저장, 삭제 취소·실제 조합 폐기·선별 양쪽 폐기, Mobile Preview/원본 토글, Desktop 원본 기본, 320/390/768/1280px의 상단·중간·끝 Scroll에서 버튼 고정을 확인합니다.
- 기존 CHS Browser 회귀 16개: 이미지·영상 Preview, Output 삭제/이동, Job 복원·다중 삭제·메모·경과 시간·Polling·Prompt 접기, LoRA Preset, MiniMax 생성, Prompt/Tag 관리, 자원 조회·탭 이동. 공유 Script를 불러오도록 Mock 정적 자산 목록을 갱신했고 기존 기능 동작을 검증했습니다.
- 운영 Style Lab의 로그인·조회·Dialog 확인 외에 이미지 생성·투표·점수 저장·삭제는 실행하지 않았습니다. CHS의 변경 기능은 격리 DB·임시 PNG·Fake Comfy로 검증하며 운영 검증은 조회와 Dialog 취소만 사용합니다.

## 운영 반영

- 2026-11-11, `feature/style-exploration-projects`의 `ca447d9` 위에 미Commit 변경으로 반영했습니다. Push하지 않았습니다.
- Backup: `runtime/style-usability-deployment-20261111-014304/`. 변경 전 소스, 온라인·서버 정지 후 SQLite Backup, 32개 업무 테이블 및 스타일 이미지 Hash를 `manifest.json`에 보관했습니다. 진행 중 CHS 요청과 ComfyUI Queue가 없음을 확인한 뒤 서버를 정지·반영·재기동했습니다.
- 반영 후 Schema 18, SQLite `quick_check=ok`, Foreign Key 오류 0, 기존 업무 테이블 32개 전체의 행 수·내용 Hash 동일, 기존 스타일 이미지 28장 Hash 동일을 확인했습니다. Job 188개, Request 3,052개, 스타일 Vote 15건을 보존했습니다.
- CHS 8388은 Docker `healthy`, `/api/session` HTTP 200입니다. 기존 Style Lab 8389 `/health`도 HTTP 200이며 해당 서비스는 재기동하지 않았습니다.
- 운영 Browser에서 Desktop 원본의 실제 이미지 Load, Mobile Preview Load·원본 전환, Elo 수정창 취소·조합 폐기창 취소, 320/390/768/1280px의 상단·중간·끝 Scroll에서 버튼 고정을 확인했습니다. 로그인 외 상태 변경 요청 0건, JavaScript 오류 0건입니다. 운영 점수·투표·이미지를 시험용으로 바꾸지 않았습니다.
- 검증 자료: `runtime/verification/style-usability-production-browser.json`, 같은 Prefix의 Desktop/Mobile Screenshot. 마지막 공통 Viewer 변경 뒤 기존 CHS 이미지·영상 Browser 회귀도 다시 통과했습니다.
- 사용자 실제 사용성 확인을 위한 반영이며 후속 기능은 이번 범위에 포함하지 않습니다.

## Commit 정리

2026-11-11 사용자 요청으로 이번 사용성 수정의 코드·테스트·문서를 함께 Commit합니다. 기존 Python·Browser·운영 보존 검증 기록을 유지하고 Commit 전 Diff 검사를 수행했습니다. Push는 하지 않습니다. 다음 작업은 문서상 5단계인 그림체의 불변 Snapshot 보관과 일반 생성에 명시적으로 가져오기를 추천하며, 별도 진행 요청 전에는 구현하지 않습니다.
