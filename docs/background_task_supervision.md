# Background Task 공통 감시와 복구

2026-11-22 기준입니다. `home_server/background_tasks.py`의 `BackgroundTaskSupervisor`가 서버 수명주기에 맞춰 다음 네 Task를 관리합니다.

| 식별자 | 역할 | 정상 대기 |
|---|---|---|
| `comfy-submission-worker` | 일반·즐겨찾기·스타일 생성의 단일 FIFO 제출 | 빈 Queue에서 무기한 대기 |
| `request-monitor` | ComfyUI 실행·완료 확인과 CHS 이력 갱신 | 1초 간격 |
| `cancellation-monitor` | 개별·작업 취소 전달과 재시도 | Event 또는 1초 간격 |
| `resource-monitor` | CPU·RAM·GPU 공통 Snapshot 수집 | 2초 간격 |

영상 변환 Worker·Scheduler, 로그 QueueListener 및 일회성 Cache Warmup Thread는 이번 관리 대상에 포함하지 않습니다.

## 장애 감지와 재시작

- 종료 Callback으로 Task 종료를 즉시 통보받습니다. 예상하지 못한 정상 반환·예외·취소를 모두 복구 대상으로 취급합니다.
- 재시작 대기 시간은 연속 실패 시 `1 → 2 → 5 → 10 → 30초`로 늘어나고 최대 30초로 제한합니다. 60초 이상 실제 단계 진행이 있었던 실행 뒤에는 연속 실패 횟수를 초기화합니다.
- 1초 간격으로 단계 진행 제한도 확인합니다. 제출 준비·Wildcard 확장·입력 업로드·LoRA 조회·Prompt 제출은 300초, DB 기록·일반 상태 조회는 180초, 접수 대조는 90초, 리소스 수집·주기 대기는 15초입니다. 요청 개수나 GPU 생성 완료 시간을 기준으로 정체를 판단하지 않습니다.
- 제한을 넘으면 `stalled`로 기록하고 이전 Task를 한 번 취소합니다. **이전 실행이 실제 종료되기 전에는 교체 Task를 시작하지 않습니다.** 취소를 무시하거나 DB Thread가 끝나지 않는 실행은 `stalled`로 남으며 중복 실행하지 않습니다.
- `complete_thread_call()`은 Task 취소가 실행 중 Thread를 죽이지 못하는 점을 보완합니다. 제출·접수 기록·상태 갱신 IO는 실제 Thread가 끝난 뒤 취소를 전달하므로 늦은 Commit과 복구 Task의 쓰기가 겹치지 않습니다.
- 통신 실패처럼 기존 루프에서 처리하는 업무 오류는 해당 루프에서 계속 처리합니다. Supervisor는 Task 종료나 진행 정체를 복구합니다.

## 제출 Worker 복구 경계

Queue, 현재 Batch, 다음 요청 Index, 현재 요청의 전송 여부·접수 ID·확정 입력은 Task 바깥의 `SubmissionWorker`·`SubmissionBatch`에 유지합니다. 같은 작업의 남은 요청을 처리한 뒤 다음 작업으로 넘어갑니다. GPU 실행 완료는 기다리지 않습니다.

1. `/prompt` 전송 전 종료: 동일 요청을 다시 준비합니다. 파일·Workflow·LoRA·스타일 Render의 사용 가능 여부와 DB 취소 상태를 다시 검증합니다.
2. 접수 ID가 이미 DB에 저장됨: 기존 ID를 유지하고 다음 요청으로 넘어갑니다.
3. 응답은 받았지만 DB에 저장되지 않음: 보관한 ID와 확정 입력을 저장합니다. 요청이 수동 삭제·중단된 경우 기존 개별 취소 경로로 해당 Prompt만 취소합니다.
4. `/prompt` 전송 중 응답 유실: `/queue`와 최근 `/history?max_items=200`의 `extra_data.extra_pnginfo.home_server_request.request_id`를 대조합니다. 접수 ID 하나가 확인되면 연결을 복구합니다. 없거나, 대조 실패·다중 접수로 확정할 수 없으면 해당 요청만 `stopped`로 남기고 자동 재제출하지 않습니다. 조회 범위 밖의 부재를 미접수 증거로 사용하지 않습니다.
5. 대기 중인 입력 Snapshot은 참조가 남아 있는 동안 보존합니다. 복구 완료 뒤 기존 정리 경로를 사용합니다.

Supervisor의 Backoff 중에도 살아 있는 Queue는 새 요청을 즉시 접수합니다. 서버 종료·Supervisor 중단 시에는 DB 저장 전에 503으로 거절합니다. DB 저장 직후 종료되는 경합에서는 새 요청을 `stopped`로 기록하고 임시 입력을 정리하므로 `submitting` 기록만 방치하지 않습니다. 세 제출 경로에 동일하게 적용됩니다.

## 정상 종료와 서버 재시작

종료 시 재시작 Gate를 먼저 닫고 네 Task가 실제 종료될 때까지 기다립니다. 이후 제출 Queue의 미확인·미전송 요청은 기존 정책대로 `stopped` 처리합니다. 이미 접수된 `pending`·`running` 요청은 Prompt ID를 보존합니다.

Memory Queue의 영속 복원은 구현하지 않습니다. 서버 프로세스 전체를 재시작하면 미제출 요청은 자동 재생하지 않습니다. 프로세스 종료는 기존 Docker `restart: unless-stopped`가 처리합니다. Event loop 전체 정지는 내부 Supervisor의 복구 범위 밖이며, 기존 Docker HTTP Healthcheck는 개별 Task 생존을 판정하지 않습니다.

## 상태 조회

인증된 `GET /api/background-tasks`에서 `Cache-Control: no-store` 응답으로 다음 정보를 조회합니다.

- Supervisor 실행 여부
- Task 식별자·역할·생존 여부·현재 단계·`running/idle/recovering/stalled/stopped` 상태
- 시작·마지막 진행 시각, 진행 정체 시간, 재시작 횟수, 연속 실패 횟수, 다음 재시작까지 남은 시간, 마지막 오류
- 제출 접수 가능 여부, 대기 Batch 수, 현재 Job·Request ID와 다음 요청 Index(0부터 시작)

현재 UI·DB Schema·기존 업무 API 응답은 변경하지 않습니다. 로그의 `Background Task 시작/종료/정체/복구 대기`와 `ComfyUI 접수 복구`에서도 동일한 운영 사건을 확인할 수 있습니다.

## 검증

`tests/test_background_tasks.py`와 `tests/test_background_task_integration.py`는 Backoff·정상 반환·예외·강제 취소·장애 격리·Idle 오탐 방지·정체 복구·Thread 종료 대기·정상 종료·네 Task 실제 복구를 검증합니다. 제출 전 재준비, 접수 응답 유실의 연결 복구, 미확인 요청의 중단, FIFO·중복 방지, 수동 중단 후 개별 취소, 접수 기록 Commit 경합과 DB 저장/Queue 접수 사이 종료도 검증합니다.

기존 `tests/test_submission_worker.py`는 100+100 제출 순서, 입력·LoRA·Workflow·Render 유실, 대기 취소·삭제, 공유 입력 정리 및 서버 재시작 보존을 계속 검증합니다. 실제 GPU 생성 요청은 테스트에서 사용하지 않습니다.

전체 Python 회귀 결과는 **633 passed, 1 skipped**입니다. 기존 Starlette/httpx DeprecationWarning 1건이 있습니다. 격리 서버의 실제 Browser에서 이미지 생성과 여러 세대의 선별·Undo·확정·취소 Cycle도 320·390·768·1280px에서 통과했습니다. 원시 결과·반영 전 DB Backup·소스 및 데이터 보존 Manifest는 Git 제외 경로 `runtime/verification/background-task-supervisor-20261122/`에 보관합니다.
