# 작업 공통 입력과 개별 요청 확정 결과 분리

작업일: 2026-10-11, 브랜치: `codex/job-cancellation-performance`, SQLite Schema: **9**.

하위 요청 상세는 확정된 결과를 읽어 표시합니다. 그러나 이전 `request_details.detail_json`에는 요청마다 같은 체크 후보·입력 Prompt·LoRA·설정과 개별 확정 결과가 함께 들어 있었습니다. 한 작업에 요청이 100개면 공통 후보도 100번 저장되고 상세 응답으로 전송됐습니다.

## 저장 구조

| 테이블 | 단위·FK | 내용 |
| --- | --- | --- |
| `jobs` | 작업당 한 Row | Workflow, 설명, 요청 수, 생성 시각, 보호·취소 의도 |
| `job_inputs` | `job_id → jobs.job_id`, `ON DELETE CASCADE` | 공통 `input_json`과 별도 `selected_tags_json` |
| `job_requests` | `job_id → jobs.job_id` | 요청 순서, 상태, ComfyUI ID, 오류, 시각, Output Stem |
| `request_results` | `request_id → job_requests.request_id`, `ON DELETE CASCADE` | 요청별 `upload_id`와 `result_json` |

`input_json`에는 입력 Prompt·Negative Prompt, LoRA, 입력 설정, Preset ID·이름 등 작업 공통 입력이 들어갑니다. `selected_tags_json`에는 제출 시 체크한 후보의 정의를 한 번만 보존합니다. 같은 작업에 속한 요청의 공통 입력·후보가 다르면 신규 저장과 Migration 모두 Transaction을 되돌립니다. 실제 기존 71개 작업에서는 이 차이가 없었습니다.

`result_json`에는 확정 Prompt·Negative Prompt, 실제 선택 경로·Negative 선택 경로, Wildcard Seed, 확정 설정·Seed, 결과물 경로를 그대로 저장합니다. 입력 설정과 확정 설정은 각각 사용자가 입력한 값과 실제 제출한 값입니다. 요청별 최종 Seed 등 차이가 있으므로 확정 설정은 결과의 일부로 보존합니다. MiniMax의 서로 다른 입력 이미지 식별자는 요청별 `upload_id`에 남습니다. 접수 전 취소된 요청처럼 확정 결과가 없는 Row는 `{}`를 사용합니다.

## 탭별 조회

| 탭·기능 | API | 읽는 데이터 |
| --- | --- | --- |
| 작업 카드 | `GET /api/jobs?summary=true` | 작은 공통 입력·상태 집계·첫 요청 확정 설정. 후보 JSON 제외 |
| 작업 하위 상세 | `GET /api/jobs/{job_id}` | 공통 `inputs` 한 번과 각 요청의 `result`·식별자·상태. 후보 JSON 제외 |
| 생성 탭 복원 | `GET /api/jobs/{job_id}/inputs` | 작업 정보와 체크 후보를 포함한 공통 `inputs`. 요청 결과 제외 |
| 결과물 탭·삭제 | 기존 Output·삭제 API | 확정 결과의 `output_paths`와 JOIN한 공통·확정 설정. 후보 JSON 제외 |

`GET /api/jobs`의 전체 조회도 공통 `inputs`와 개별 `result` 형식으로 통일합니다. 요청의 기존 `detail` 응답과 복원 응답의 `requests[0].detail`은 제거했고, Web과 테스트도 새 응답 형식을 사용합니다. 평상시 조회·상태 갱신에 구형 Row를 판별하거나 구형 JSON을 읽는 호환 분기는 없습니다.

생성 탭 복원은 기존처럼 작업 단위입니다. 현재 존재하고 체크할 수 있는 태그만 적용하고, 구성 변경된 Preset은 직접 선택으로 복원합니다. MiniMax 입력 이미지를 복원하지 않는 동작과 Seed·Wildcard를 복원하지 않는 동작도 유지합니다.

## Migration과 백업

Schema 4~8의 지원되는 이전 DB는 시작 시 SQLite Backup을 먼저 만들고, 하나의 Transaction에서 모든 기존 요청의 입력과 확정 결과를 분리합니다. 이전 JSON의 알 수 없는 공통 입력·결과 필드도 그대로 옮깁니다. 요청 수와 FK를 검증한 뒤 `request_details` 테이블 또는 `job_requests.detail_json` column을 제거하고 Schema 9로 전환합니다.

공통 입력 불일치, 상세 Row 누락, 잘못된 JSON, FK 오류가 있으면 Transaction 전체를 되돌립니다. Schema 9 재시작에서는 Migration을 반복하지 않습니다. 기존 조회 호환 코드는 남기지 않고, 이전 구조를 읽는 코드는 일회성 Migration에만 있습니다.

실제 적용 전 자동 백업: `runtime/backups/home_server_before_job_request_storage_20261010T154525_956396Z.sqlite3`.

Compose의 `--reload`가 코드 변경을 감지한 재시작에서 실제 DB가 자동 전환됐습니다. 이후 서버를 잠시 중지하고 자동 백업과 실제 DB의 모든 Row를 비교한 다음 새 코드로 시작했습니다. 다른 코드·Schema로 되돌릴 때는 서버를 중지하고 해당 코드가 지원하는 DB 백업을 함께 복구해야 합니다.

## 검증 결과

- Python 테스트 **87개 통과**. 기존 Starlette/httpx Deprecation Warning 1개.
- Edge + Mock API의 Browser 테스트 **4종 통과**: LoRA, 다중 삭제·보호, 작업 복원, 대량 상세·Polling.
- Schema 6·7·8 → 9, Migration 실패 시 Rollback, 재시작, FK·Cascade, 보호 설정, 요청별 MiniMax 이미지·Seed·선택 경로 보존 검증.
- 실제 DB **71개 작업·882개 요청**의 원본 공통 입력·후보·요청별 확정 결과와 Metadata를 모두 비교. Preset·LoRA·태그 테이블도 동일. Integrity Check `ok`, FK 오류 0개.
- 실제 서버에서 이전 100개 작업 3개의 상세·복원·결과물 API를 확인. 완료 파일 4·2·3개 유지.
- 신규 요청 2개를 제출·취소해 공통 입력 1 Row와 확정 결과 2 Row 저장을 확인한 뒤 해당 테스트 작업만 정리. 이전 작업·결과물은 보존.

| 항목 | 이전 구조 | 새 구조 |
| --- | --- | --- |
| 실제 DB의 저장 JSON 총량 | 23,015,646 Bytes | 3,169,307 Bytes |
| 같은 100개 요청 작업의 상세 JSON 비교 | 약 2.51 MB | 약 193 KB |
| 실제 서버의 100개 요청 상세 응답 | — | 약 183 KB, 36~77 ms |
| 실제 서버의 복원 API | — | 약 22 KB, 25~29 ms |

저장 JSON 총량은 SQLite 값의 Byte 길이 합입니다. DB 파일 자체는 재사용 가능한 빈 페이지를 포함하므로 같은 비율로 파일 크기가 줄었다는 뜻은 아닙니다. 상세 JSON 비교는 이전 백업과 새 DB의 같은 작업을 직렬화한 크기이며, 실제 HTTP 응답은 공백 없는 JSON이므로 크기가 조금 다릅니다. 시간은 Windows Docker Desktop + bind mount 환경의 실측이며 고정 성능 보장은 아닙니다.

결과물 목록은 실제 폴더 스캔을 계속 수행합니다. 이번 작업은 공통 입력·후보의 중복 저장과 불필요한 상세 조회를 제거한 범위이며, 폴더 스캔 방식은 바꾸지 않았습니다.
