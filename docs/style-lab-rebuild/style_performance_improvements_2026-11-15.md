# 스타일 구성 조회·다음 대결 성능 개선

2026-11-15. [전날 조사](style_performance_investigation_2026-11-14.md)에서 확인한 병목을 수정합니다. 기존 화면·선별 산식·170ms 선택 강조·1000ms 결과 공개는 유지합니다.

## 적용 내용

- 같은 프로젝트의 진행 중 조회는 Promise 하나로 합치고, 완료 후 2초 뒤 다음 Polling을 예약합니다. 변경 명령·프로젝트 전환에 대한 오래된 응답 차단은 유지합니다.
- 투표·Undo·비교 대상·Mode 변경 응답에 포함된 다음 Match와 Elo를 즉시 사용합니다. 성공 응답 뒤 전체 결과 재조회를 기다리지 않고, 진화 진행 표시만 뒤에서 갱신합니다. 충돌·실패 시에는 최신 상태를 다시 읽습니다.
- 결과 공개 중 다음 Pair의 모든 Prompt Preview를 미리 요청·Decode합니다. 실제 이미지 URL과 Thumbnail Cache는 기존 CHS 구현을 공유하며, 공개 중 같은 이미지 노드를 재사용합니다. Prefetch 참조는 전환 뒤 해제합니다.
- 선별·그림체·진화는 `generation-results?summary=true`를 사용합니다. Summary는 원본 `request_results` JSON을 읽지 않습니다. 생성 탭·기존 API 기본값은 실제 Prompt·설정·LoRA 상세를 제공합니다.
- Render·출력 파일·계획·소유 Job을 한 연결에서 일괄 조회하고, 조회용 Index 3개를 추가합니다. 생성 Graph·Workflow 전체를 Python으로 읽어 버리던 처리를 제거합니다. Schema Version은 18입니다.
- 목록의 준비 상태는 Output Catalog를 사용합니다. 선별은 현재·다음 Pair의 모든 Prompt 파일을 실제 확인하고, 없는 파일이 선택되면 다른 유효 Pair를 고릅니다. 생성·진화 준비/확정·삭제·미디어 접근의 실제 파일·관리 경로 검사는 유지합니다. Pair 밖의 외부 파일 삭제는 해당 파일 접근·비교 또는 Output Sync 때 확인됩니다.

## 같은 운영 데이터 복사본의 측정

같은 SQLite Snapshot(조합 44개·Render 109개·Vote 76개), Docker Image·Windows Bind Mount·읽기 전용 이미지 Mount를 사용했습니다. 큰 프로젝트의 결과는 조합 42개이며 Prompt가 3개입니다. GPU 생성과 운영 투표는 실행하지 않았습니다. localhost의 Edge Headless 결과이므로 실제 휴대전화·외부망 지연과는 다릅니다.

API는 각 3회 중앙값입니다.

| 항목 | 기존 | 개선 |
| --- | --- | --- |
| 카드 목록 조회 | 1,242ms / 292,880bytes | **114ms / 192,556bytes** |
| 전체 생성 상세 조회 | 1,233ms | **857ms** |
| 선별 조회 | 492ms | **102ms** |
| 진화 조회 | 623ms | **226ms** |

전체 생성 상세 JSON은 개선 전후 내용을 대조해 동일함을 확인했습니다.

| 첫 진입 | 기존 | 개선: 첫 이미지 / 선택 가능 |
| --- | --- | --- |
| Mobile 390px 선별 | 15초 동안 미표시 | **416ms / 555ms** |
| Mobile 390px 그림체 | 15초 동안 미표시 | **278ms** |
| Desktop 1280px 선별 | 15초 동안 미표시 | **496ms / 658ms** |
| Desktop 1280px 그림체 | 15초 동안 미표시 | **232ms** |

투표부터 다음 이미지가 준비되고 다시 선택 가능할 때까지는 **4,181ms → 1,408ms**, 약 **66% 감소**했습니다. 각 3회 중앙값이며 결과 공개 시간 1.17초를 포함합니다. 이 비교에서 정기 Polling은 양쪽 모두 멈췄고 매번 Undo로 같은 시작 상태를 복원했습니다. 첫 탭 측정은 Polling을 변경하지 않은 실제 코드입니다.

## 검증·운영 반영

- Python 전체: **518 passed, 1 skipped**. 기존 Starlette/httpx DeprecationWarning 1건.
- Browser 11개: 프로젝트·생성·Random 추가·선별·Keyboard·Mode·Elo·Undo·Prompt 변경·그림체·공통 Viewer·진화·조합 폐기.
- 회귀 검증: 목록을 2.6초 지연시켜도 첫 화면 표시, 동시 조회 3회 병합, 성공 투표 후 전체 조회 생략, 결과 공개 중 같은 이미지 노드 유지, 다음 Pair Prefetch, 변경 중 동일 프로젝트 잠금·다른 프로젝트 이동, 두 번째 Prompt 파일 유실 시 투표 거절, Pair 밖 파일 유실 시 진화 준비 거절.
- 운영 반영 전 SQLite·변경 소스 Backup을 만들었습니다. 재기동 전후 업무 Table 32개의 모든 행·실제 스타일 이미지 109개의 Hash가 동일합니다. Schema 18·무결성 정상·Foreign Key 위반 0건입니다.
- 운영 8388 재기동·Healthy·HTTP 200을 확인했습니다. 운영 Browser는 로그인 뒤 GET만 허용했습니다. 첫 Mobile 선별 이미지/선택 가능은 **544/579ms**, 그림체 **422ms**였고, Desktop 선별 **457/492ms**, 그림체 **241ms**였습니다. 운영 생성·투표·Elo·설정은 변경하지 않았습니다.
- 원시 측정·복사 DB·Browser Snapshot은 Git 제외 경로 `runtime/verification/style-performance-20261115/`에서 보관합니다.
