# 작업 경과시간

작업 카드와 하위 요청 카드의 기존 상태 Badge 아래에 `대기중`, `6분 6초 작업됨`, `N/A` 중 하나를 표시합니다. 완료·취소·실패 상태별로 다른 시간 문구나 조작부를 추가하지 않습니다.

## 저장과 계산

- Schema **13**은 `job_requests.started_at TEXT NULL`만 추가합니다. `finished_at`은 추가하지 않습니다.
- 서버가 요청의 실행을 처음 확인하면 서버 UTC 시각을 기록합니다. 이후 같은 실행 상태를 반복 조회해도 시작 시각과 `updated_at`을 매번 갱신하지 않습니다.
- 기존 완료 History 조회에서 `execution_start` Timestamp를 얻으면 실제 시작 시각으로 확정합니다. 실행 Polling 사이에 끝난 짧은 요청도 History가 있으면 시작 시각을 저장합니다. 추가 ComfyUI 조회는 하지 않습니다.
- 취소 처리 중에 실행을 처음 관찰해도 시작 시각은 기록하며 기존 취소 상태는 유지합니다. History에 시작 시각이 없으면 이미 관찰한 값을 보존하고, 실행 여부를 모르는 요청의 시작 시각은 추측하지 않습니다.
- 상위 작업은 하위 요청의 가장 이른 `started_at`을 사용합니다. 전체 경과시간이며 하위 요청별 소요시간의 합계가 아닙니다.
- 활성 상태는 기존 `submitting`, `pending`, `running`, `cancelling`입니다. 시작 시각이 있으면 활성 상태는 `서버 현재 시각 - started_at`, 종료 상태는 `updated_at - started_at`으로 계산합니다.
- 시작 시각이 없는 활성 요청은 `대기중`, 시작 기록이 없는 종료 요청과 기존 종료 이력은 `N/A`로 표시합니다.
- 시각은 offset을 명시한 UTC ISO 형식으로 저장합니다. ComfyUI의 Unix millisecond Timestamp도 UTC로 변환하며, Browser는 offset을 해석해 계산합니다. 음수 경과시간은 0초로 표시합니다.
- 작업 목록·상세 API는 `server_time`을 반환합니다. Browser 현재 시계나 timezone에 기대지 않고 서버 시각으로 계산합니다. 기존 1초 Polling 응답마다 시간 문구만 갱신하며 카드 DOM과 펼친 상세를 유지합니다.
- `updated_at`은 서버가 종료를 확인한 시각이므로 실제 종료 시각과 Polling·통신 지연만큼 차이 날 수 있습니다.

## Migration

Schema 12에서 시작하면 `runtime/backups/*_before_request_started_at_*.sqlite3` 백업을 검증한 뒤 nullable Column을 추가합니다. 기존 시작 시각은 모두 NULL로 유지하며 과거 이력을 별도로 조회해 채우지 않습니다. 작업·요청·분류·입력/결과 JSON과 실제 파일은 그대로 유지합니다.

Schema 12 코드로 복귀해야 한다면 서버를 중지하고 현재 DB를 추가 백업한 뒤 다음 Transaction으로 시작 시각 Column만 제거합니다. 실행 전 실제 `PRAGMA user_version`이 13인지 확인해야 합니다. 현재 Schema 14에서는 먼저 [즐겨찾기 Rollback](request_favorites.md)으로 Schema 13으로 전환해야 합니다.

```sql
BEGIN IMMEDIATE;
ALTER TABLE job_requests DROP COLUMN started_at;
PRAGMA user_version = 12;
COMMIT;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

## 검증

- `tests/test_request_started_at.py`: Migration·백업·시각 보존, 실행/완료/실패/취소·짧은 요청, 취소 경합, 요약/상세 집계, UTC 및 추가 조회 여부.
- `tests/browser_job_elapsed_time.cjs`: Desktop/Mobile, 서로 다른 timezone offset과 잘못된 Browser 시계, 대기중/N/A, 상위/하위 시간 증가·종료 고정, Polling DOM 및 상세 조회 보존.

모든 검증은 임시 DB·Fake ComfyClient 또는 Mock API에서 수행하며 운영 DB와 실행 중인 ComfyUI 작업에는 접근하지 않습니다.
