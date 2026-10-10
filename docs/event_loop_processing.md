# Event Loop의 동기 처리 분리

작업일: 2026-10-11. 브랜치: `codex/job-cancellation-performance`.

작업 공통 입력과 확정 결과를 [Schema 9](job_request_storage_split.md)로 분리한 뒤에도 일부 API의 최종 JSON 직렬화, 태그·Preset DB 호출, 제출 전 검증, 파일 처리와 로그 출력은 Event Loop에서 실행됐습니다. FastAPI의 일반 `def` API도 Dictionary를 반환하면 최종 응답 변환이 Endpoint 실행 뒤에 일어나므로, Worker에서 `JSONResponse`를 완성해 반환하도록 바꿨습니다.

## 탭별 처리

| 탭·기능 | Worker로 옮긴 처리 | Event Loop에 남는 처리 |
| --- | --- | --- |
| 작업 목록·상세·복원 | DB 조회, JSON 해석, 응답 구성, 최종 JSON·UTF-8 변환 | 작업 목록의 명시적 상태 갱신을 비동기로 기다림 |
| 태그·Prompt Preset·LoRA Preset | DB 조회·저장·삭제, 최종 JSON 직렬화 | 요청 접수·응답 전송 |
| 생성 미리보기 | 선택 후보 조회, Recursive 태그 검증·추첨, 최종 JSON 직렬화 | ComfyUI Wildcard HTTP 통신 |
| 작업 제출 | 태그 검증, Workflow 파일 로드, 업로드 파일 존재 확인, 요청 구성·DB 저장 | ComfyUI 조회, 제출 Task 시작 |
| LoRA 목록·기본 강도 | DB 조회·저장, 목록의 최종 JSON 직렬화 | ComfyUI 모델 목록 HTTP 통신 |
| 결과물 목록·삭제·이동 | 폴더·이미지 처리, DB 조회·삭제, 파일 이동, 최종 JSON 직렬화 | 응답 전송 |
| 입력 이미지·Media | 임시 파일 읽기·쓰기·탐색·정리, Media 경로 확인 | FileResponse 전송, ComfyUI 이미지 업로드 HTTP 통신 |
| ComfyUI 제출·감시·취소 | 전송 JSON 직렬화, History JSON 해석, Queue JSON 해석·ID 목록 구성 | HTTP 통신, 상태·취소 Task의 작은 제어 처리 |
| 앱 로그 | Console·회전 파일 출력·Flush는 Queue Listener Thread | 로그 Record를 Queue에 넣음 |

작업 목록은 조회와 최종 직렬화를 같은 Worker 호출 안에서 완료합니다. DB만 사용하는 API는 FastAPI Thread Pool에서 실행하는 `def` Endpoint로 구성하고, 최종 `JSONResponse`까지 그 안에서 생성합니다. 외부 HTTP 통신을 사용하는 API는 `async`를 유지하면서 DB·파일·JSON 처리만 `asyncio.to_thread`로 분리합니다. 기존 응답 필드와 HTTP 상태 코드는 유지하며, 생성 API의 `201`도 명시적으로 보존합니다.

작업 취소는 `list_active_requests(job_id=...)`로 해당 작업의 최대 100개 요청만 조회합니다. 다른 모든 작업의 활성 요청을 가져와 Event Loop에서 거르는 처리를 제거했습니다. 감시 Task의 전체 활성 요청 조회와 명시적 `limit` 동작은 유지합니다.

미리보기·제출의 태그 정의도 체크한 항목만 `tag_entries JOIN tag_groups`로 한 번에 읽습니다. 전체 태그·그룹을 따로 가져와 조립하는 비용을 제거하고, 병렬 편집 중 서로 다른 시점의 그룹·항목 정의가 섞이지 않게 했습니다. 사용자의 선택 순서와 기존 항목 필드는 보존하며, 선택하지 않은 후보는 조회하지 않습니다.

MiniMax 업로드 파일은 Worker에서 Bytes로 읽은 후 비동기 HTTP 전송에 전달합니다. 전송 중 Main Thread에서 파일을 읽지 않지만 입력 파일 크기만큼 임시 메모리를 사용합니다. 앱의 기존 50 MB 입력 제한은 그대로 적용됩니다.

로그는 QueueHandler → QueueListener → Console·RotatingFileHandler 순서입니다. 종료 시 제출·감시 Task를 정리한 다음 Queue를 모두 비우고 Handler를 닫습니다. Queue를 비우는 대기도 Worker에서 수행합니다. 기존 경로·5 MB 회전·이전 파일 5개 보관 방식은 유지합니다.

## 검증

- Python 테스트 **113개 통과**, 기존 Starlette/httpx Deprecation Warning 1개.
- 12개 조회 API의 최종 JSON 직렬화를 강제로 지연시켜도 Session과 100개 요청 취소 접수가 합계 1초 이내에 완료되는지 검증.
- 느린 DB 조회 6종과 생성 미리보기·제출의 태그 검증 중에도 Session·취소 접수 확인.
- 느린 로그 파일 쓰기가 취소 응답을 막지 않고 종료 시 로그가 모두 남는지 확인.
- ComfyUI 요청 직렬화, History·Queue 해석, 이미지 파일 읽기가 Event Loop 밖에서 실행되는지 확인. JSON 본문·Content-Type·지정 ID 취소 계약 보존.
- 태그 정의의 단일 JOIN, 체크한 항목만 조회, 선택 순서 보존, 빈 선택·200개 제한에서 불필요한 DB 조회 생략 검증.
- 기존 인증·태그·Preset·업로드·결과물 경로 보호·삭제 보호·Migration·대량 취소 테스트 통과.

### 실제 Compose 서버의 동시 요청

실제 서버에 신규 100개 작업 하나를 제출하고, 다음 조회를 **8개 Worker에서 총 32번** 수행하는 동안 Session과 취소 API를 호출했습니다.

- 최대 50개 작업의 전체 상세·요약 목록
- 기존 100개 작업 3개의 상세
- 작업 공통 입력·태그 목록·실제 결과물 폴더 조회

| 측정 항목 | 실제 결과 |
| --- | --- |
| 부하 중 Session 응답 9회 | 3.7~53.9 ms |
| 부하 중 100개 작업 취소 접수 | 181.1 ms |
| 신규 요청 최종 상태 | 100개 모두 취소 |
| 테스트 정리 | 해당 신규 작업·요청만 삭제, 생성 파일 0개 |
| 기존 작업·요청 | 71개 작업·882개 요청 Metadata 동일 |

SQLite Integrity Check는 `ok`, FK 오류는 0개였습니다. 측정은 Windows Docker Desktop·bind mount·실제 ComfyUI 환경에서 수행했습니다. JSON 지연 테스트는 실행 위치와 Event Loop 응답성을 검증하는 테스트이고, 실제 측정값은 고정 성능 보장이 아닙니다.

Event Loop에는 비동기 I/O, 인증·Session, 작은 취소 응답, Task 제어가 남습니다. Thread Pool로 옮겨도 CPU·GIL·디스크·SQLite Lock 같은 공유 자원의 경합까지 사라지지는 않습니다. 이번 변경은 큰 데이터 변환과 동기 I/O가 Event Loop를 직접 점유하는 경로를 제거한 것입니다. Web의 DOM 렌더링이나 Worker Process 구조는 변경하지 않았으며 DB Schema도 9를 유지합니다.
