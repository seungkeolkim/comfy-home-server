# 대량 작업 취소·조회 성능 개선

- 작업일: 2026-10-10
- 브랜치: `codex/job-cancellation-performance`
- 기준 테스트 입력: 작업 `820f0bd49c29`의 Prompt, Negative Prompt, 태그 후보, LoRA, Workflow 옵션
- 실행 환경: Windows Docker Desktop / Compose, Windows bind mount의 SQLite·관리 이미지 폴더
- 기존 진단: [탭별 성능 점검](performance_investigation_2026-10-10.md)

## 탭별 변경

| 관련 탭 | 변경 | 결과 |
| --- | --- | --- |
| 작업 | 제출 중인 요청까지 DB에 작업 취소 의도 기록 | ComfyUI 취소 완료를 기다리지 않고 접수 결과를 반환하며 추가 제출 중단 |
| 작업 | 전송 직전 재확인, 늦게 반환된 접수 ID의 취소 추적 | 취소 시점의 네트워크 전송 경합에서도 남은 제출이 계속 쌓이지 않음 |
| 작업 | 요약 목록과 하위 요청 상세 조회 분리 | Polling에서 후보 Snapshot과 모든 하위 요청을 반복 전송하지 않음 |
| 작업 | 완료 후 다음 Polling 예약, 변경된 목록만 렌더링 | 1초보다 느린 응답도 반영하며 갱신·조회 실패 시 마지막 목록 유지 |
| 작업 | 취소 접수·진행 건수·전송 실패·재시도 버튼 표시 | 클릭 직후 처리 중 표시, 통신 실패는 간격을 두고 자동 재시도 |
| 작업 → 생성 | 첫 요청의 원본 입력을 별도 조회하여 작업 단위 복원 | 후보 Snapshot·Preset 판별·원본 옵션·MiniMax 이미지 초기화 계약 유지 |
| 결과물 | 파일 조회·삭제를 Thread에서 처리하고 이미지 크기 재사용 | 동기 I/O가 Event loop를 막는 문제 완화, 파일 속성 변경 시 크기 재조회 |
| 공통: 다른 탭 | 활성 작업 수만 조회, 초기 로딩에서 결과물 조회 제외 | 생성·태그 관리 등을 볼 때 큰 작업 목록이나 결과물 목록을 불필요하게 조회하지 않음 |
| 공통: 서버 감시 | 작은 상태 필드만 조회, 제한된 동시 history 읽기, 묶음 DB 갱신 | 불필요한 Snapshot parsing·개별 commit 감소, 1000개 초과 활성 요청도 감시 대상에 포함 |

## 취소 흐름과 확인 기준

1. 취소 API는 DB transaction으로 `submitting`·`pending`·`running`을 `cancelling`으로 바꾸고 작업의 `cancellation_requested`를 기록합니다.
2. 제출 loop는 준비 전과 ComfyUI 전송 직전에 취소를 다시 확인합니다. 아직 보내지 않은 요청은 `cancelled`로 기록합니다.
3. 이미 전송 중이었다면 늦게 반환된 prompt ID를 저장하되 상태는 `cancelling`으로 유지합니다. 백그라운드 취소 처리 대상에 포함합니다.
4. ComfyUI 상태 요약에서 선택한 대기 ID를 찾고 `POST /queue`의 `delete` 배열로 해당 ID만 제거합니다. 실행으로 넘어간 ID는 다시 조회한 뒤 지정 ID 취소 API로 처리합니다. 전역 queue 삭제나 전역 interrupt는 사용하지 않습니다.
5. 완료·중단 history를 확인하여 상태와 원래 결과 경로를 반영합니다. 이미 정상 완료된 결과를 취소로 덮어쓰지 않습니다.

**취소 접수 시간과 취소 완료 확인 시간은 다릅니다.** 대기열 삭제 후 history가 남지 않는 요청은 queue·history에 계속 없는지 약 15초 재확인한 뒤 취소 완료로 표시합니다. 이 동안 UI에는 취소 진행 상태를 표시하며 이미 제거된 대기 요청을 다시 제출하지 않습니다.

일반 `pending`·`running` 요청이 queue·history에서 사라지면 성공적으로 조회한 상태에서 약 30초 재확인하고 `stopped`로 기록합니다. 연결 실패·history 조회 실패는 유실 판단에 사용하지 않습니다. 앱 재시작이나 제출 응답 실패로 접수 여부를 알 수 없는 요청도 취소 완료로 단정하지 않고 확인 불가 중단으로 남깁니다.

ComfyUI에서 직접 대기열만 삭제하는 동작은 앱의 취소 의도를 기록하지 않습니다. 앱에 아직 남은 제출도 중단하려면 앱의 작업 취소를 사용해야 합니다.

### 실제 ComfyUI 점검에서 발견한 추가 병목

초기 구현에서 설치된 ComfyUI의 `/api/jobs/cancel` 묶음 API를 사용했지만, 실제 200개 테스트에서 15초 ReadTimeout이 반복됐습니다. 해당 ComfyUI 구현은 각 ID마다 `get_current_queue()`로 전체 대기열을 Deep copy합니다. 따라서 ID 수와 대기열 크기가 모두 커질 때 부담이 증가합니다.

최종 구현은 대기 ID만 `/queue`에서 직접 제거한 뒤 실행 ID만 지정 취소합니다. ComfyUI 소스나 기동 설정을 변경하지 않고 앱의 통신 방식으로 해결했습니다. 상태 조회도 큰 Workflow를 포함하는 `/queue` 대신 `/api/jobs?status=pending,in_progress` 요약을 사용하며, 이 API가 없는 구형 서버에서는 기존 queue 조회로 대체합니다.

## SQLite schema 8

- `jobs.cancellation_requested`: 재시작 후에도 남는 작업 단위 취소 의도
- `job_requests`: 요청 식별자·상태·시각·오류 등 자주 바뀌는 작은 데이터
- `request_details`: 원본 Prompt·후보 Snapshot·LoRA·옵션·resolved 데이터 등 큰 JSON
- `request_details.request_id`는 하위 요청의 FK이며, 하위 요청 삭제 시 `ON DELETE CASCADE`로 함께 삭제

큰 JSON과 상태가 같은 SQLite row에 있으면 상태만 바꾸어도 큰 데이터 페이지의 읽기·쓰기가 발생할 수 있었습니다. 테이블 분리 후 상태 집계·취소·감시가 큰 Snapshot을 반복 읽거나 다시 쓰지 않도록 했습니다. 후보 Snapshot을 제거하거나 내용을 줄인 것은 아닙니다.

Migration은 transaction 안에서 기존 JSON을 그대로 옮깁니다. 구형 DB를 옮기기 전 SQLite backup API로 백업하고 integrity check를 확인합니다. 실제 runtime에는 다음 백업이 있습니다.

- 작업 시작 전 schema 6: `runtime/database_backups/before_job_cancellation_refactor_20261010_230133.sqlite3`
- 큰 JSON 분리 직전 schema 7: `runtime/backups/home_server_before_request_details_20261010T143053_519501Z.sqlite3`

현재 schema 8 DB는 이전 main 코드의 지원 버전 밖입니다. 이전 코드로 되돌릴 때는 서버를 중지하고 그 코드가 지원하는 schema 6 백업을 함께 복구해야 합니다. 백업 이후 새 작업을 생성했다면 그 이력도 별도로 보존해야 합니다.

## API 변경

| 용도 | API | 응답 |
| --- | --- | --- |
| 목록 Polling | `GET /api/jobs?summary=true` | 상태 집계·카드 공통 입력. 전체 하위 요청·후보 Snapshot 제외 |
| 다른 탭의 작업 수 | `GET /api/jobs/activity` | `active_count` |
| 펼친 작업 상세 | `GET /api/jobs/{job_id}` | 하위 요청 전체와 원본·resolved 상세 |
| 작업 단위 복원 | `GET /api/jobs/{job_id}/inputs` | 작업 정보와 첫 요청의 원본 Snapshot |
| 작업 취소 접수 | `POST /api/jobs/{job_id}/cancel` | `status: cancelling`, `requested_count` |

`summary`를 지정하지 않은 기존 `/api/jobs`의 전체 상세 응답은 호환성을 위해 유지합니다. 기존 작업 취소 응답의 `cancelled_count`·`failed_count`는 최종 처리 건수였지만, 새 응답의 `requested_count`는 비동기 취소 접수 대상 수입니다. 실제 성공·진행·전송 실패 건수는 이후 작업 상태로 확인합니다.

## 실제 대량 요청 측정

최종 구현으로 원본 작업의 입력을 사용하여 실제 ComfyUI에 다음 시나리오를 실행했습니다.

- 100개 작업 제출 직후 취소: 하위 요청 100개 모두 취소
- 별도 대조 작업 1개: 정상 완료, 다른 작업 취소의 영향 없음
- 100개씩 두 작업을 동시에 제출하고 접수가 끝난 뒤 취소: 각각 100개 모두 취소
- 테스트 작업 4건과 하위 요청 301건을 모두 삭제하고, 대조 작업에서 생성된 이미지 1개도 이력·파일 삭제 API로 정리
- 앞선 구현 단계의 테스트 이력·생성 파일도 모두 정리

| 관련 탭 | 측정 항목 | 개선 전 진단 | schema 8 최종 실제 테스트 |
| --- | --- | --- | --- |
| 작업 | 목록 응답 크기 | 약 8.65 MB | 13,209 bytes, 약 13.2 KB |
| 작업 | 목록 HTTP 응답 | 약 6,286.9 ms | 100.2 / 99.7 / 103.0 ms |
| 작업 | 전체 취소 접수 응답 | 기존 API가 하위 취소 전송을 순차 대기 | 59.0 / 57.8 / 63.3 ms |
| 공통 (특정 탭 없음) | Session HTTP 응답 | 약 4,630 ms | 22.8 / 26.0 / 23.7 ms |

이전 진단과 최종 테스트의 데이터·동시 부하는 완전히 같지 않으며 고정된 Benchmark는 아닙니다. 최종 수치는 동시 200개 요청을 포함한 실행 중 실제 앱에 `127.0.0.1`로 보낸 HTTP 요청입니다. 취소 접수 응답 시간은 15초 재확인을 포함한 최종 취소 완료 시간이 아닙니다.

## 회귀 검증과 보존 확인

- Python: 79 passed, 기존 Starlette/httpx DeprecationWarning 1건
- Browser: LoRA·태그/작업, 다중 삭제·보호, 생성 탭 복원, 느린 Polling·대량 요청 UI의 4개 suite 통과
- JavaScript syntax 및 Git whitespace 검사 통과
- 느린 응답 1,500 ms에서도 목록 반영, 동일 목록 DOM 유지, 목록 조회 동시 수 최대 1개 확인
- 닫힌 작업은 하위 카드 100개를 만들지 않고 펼칠 때 상세 조회
- 삭제 후 남은 작업 표시 및 조회 실패 시 마지막 목록 유지
- 취소 중 접수 응답이 늦게 도착하는 경합, 전송 오류·재시도, 재시작 시 확인 불가 상태 검증
- 파일 정보 읽기가 지연되는 동안에도 Session 응답, 이미지 변경 시 크기 cache 갱신 확인
- 삭제 보호·경로 경계·이동된 파일 보존·현재 태그에 따른 복원·Preset 변경 판별·MiniMax 이미지 초기화 유지

실제 DB를 작업 전 백업과 비교하여 **기존 작업 68건의 ID·설정·삭제 보호와 하위 요청 582건의 detail JSON이 동일**함을 확인했습니다. SQLite integrity check는 `ok`, FK 오류는 없으며 테스트 정리 후 앱 활성 요청과 ComfyUI queue는 모두 0개였습니다.

원본 실측 기록과 실행 스크립트는 Git에서 제외되는 `runtime/verification/`에 있습니다. 비밀번호·Prompt 본문을 결과 기록에 출력하지 않았습니다.

## 별도로 확인한 로컬 접속 환경

`127.0.0.1:8388`은 정상 응답했습니다. Windows의 `localhost`는 `::1`을 먼저 선택하며, 현재 Docker 접속 경로에서 `::1:8388` 연결이 Timeout으로 끝난 뒤 IPv4로 넘어가는 지연을 별도로 관찰했습니다. Python HTTP 검사에서는 약 10초 추가 대기였습니다. 이 수치는 위 앱 API의 처리 시간과 분리해야 하며, 로컬 성능 비교에는 `127.0.0.1`을 사용했습니다. 이 작업에서 IPv6·방화벽 설정은 변경하지 않았습니다.
