# 관리자: 수동 DB 백업·복원과 읽기 전용 진단

## 진입과 범위

리소스 모니터링을 펼친 뒤 `VRAM 비우기` 옆의 `⚙ 관리자`를 선택합니다. Desktop·Mobile 모두 같은 위치이며, 일반 메뉴에는 항목을 추가하지 않습니다. URL은 `?view=administration`이며 기존 로그인 Session과 동일 출처 검증을 적용합니다. 별도 관리자 계정이나 권한 체계는 추가하지 않습니다.

이번 기능은 다음으로 한정합니다.

- 운영 DB의 수동 백업, 목록 조회, 한 줄 200자 설명 생성·수정
- 현재 서버와 같은 Schema version인 백업의 DB 복원
- 확인 후 백업 영구 삭제
- 백업·복원·삭제·설명 변경의 실행 이력
- DB와 현재 파일의 연결 진단 및 저장 공간 현황 조회

휴지통, 다운로드, Scheduler/cron, 주기적 백업, 복원 직전 자동 백업, 자동 정리, 진단 결과의 자동 수정은 추가하지 않습니다. 기존 Migration·태그 Import의 변경 전 백업 정책은 유지하고, 해당 파일도 기존 백업으로 조회합니다.

## 데이터 경계와 Schema

| 위치 | 역할 | 복원 시 동작 |
| --- | --- | --- |
| `runtime/home_server.sqlite3` | Prompt·태그·LoRA 설정·작업·결과물 Catalog·분류·즐겨찾기 Snapshot을 보관하는 운영 DB | 선택한 백업으로 복원 |
| `runtime/administration.sqlite3` | 백업 설명·파일 연결·관리자 실행 이력 | 유지 |
| `runtime/backups/` | 운영 DB의 백업 파일 | 유지. 삭제 요청 때 선택한 파일만 제거 |
| 관리 결과물 폴더 | 생성 이미지·영상 원본 | 유지 |
| `runtime/favorite_inputs/`, `runtime/uploads/`, `runtime/cache/` | 입력 파일과 파생 Cache | 유지 |

운영 DB Schema는 14이며 이번 작업으로 Migration하지 않습니다. `DATABASE_SCHEMA_VERSION`이 서버가 지원하는 version입니다.

관리용 DB는 다른 SQLite 파일이며 운영 DB의 테이블에 FK를 만들지 않습니다.

| 테이블 | 주요 필드 |
| --- | --- |
| `database_backups` | `backup_id`, 고유한 `file_name`, `description`, `created_at`, `source=manual/existing`, `deleted_at` |
| `administration_history` | `operation_id`, `action`, `backup_id`, `file_name`, 당시 `description`, `started_at`, `finished_at`, `status`, `error_message` |

파일을 삭제하면 `deleted_at`을 남겨 목록에서 제외합니다. 이는 삭제 이력을 위한 Metadata이며 파일 보관이나 복구 기능이 아닙니다. 설명 변경은 운영 DB와 백업 파일을 수정하지 않습니다. 기존 파일은 최초 발견 시 파일 수정 시각을 백업 시각으로 표시하며, 과거의 실제 생성 사유·시각을 추측하지 않습니다.

관리용 DB와 백업 폴더는 기존 Compose의 `runtime/` Bind mount 안에 있으므로 별도 mount나 서비스가 필요하지 않습니다. 관리자 작업 시작 시 이력을 먼저 기록하고 완료·실패를 갱신합니다. 재기동 시 끝나지 않은 이력은 성공으로 추정하지 않고 `interrupted`로 표시합니다.

## 백업·복원

백업은 SQLite backup API로 운영 DB만 복사합니다. 목록 조회에서는 `PRAGMA user_version`만 읽어 현재 서버 Schema와 비교합니다. 전체 무결성 검사를 실행하거나 `Schema 일치`를 무결성 보증으로 표현하지 않습니다. 누락·손상·경로 오류가 있는 백업은 복원 불가로 표시하고 삭제는 가능합니다.

복원 버튼은 Schema가 같을 때만 활성화됩니다. 확인창에서 현재 DB를 필요한 만큼 백업했는지 묻고, 이후 변경 사항과 미저장 화면 입력이 사라짐을 안내합니다. 서버는 `backup_confirmed=true`도 검증합니다. 파일을 직접 변경했을 수 있으므로 복원 직전 Schema를 다시 읽습니다.

복원 중 처리 순서:

1. 새 API·미디어 Metadata 요청과 작업 상태·취소 감시의 진입을 막습니다. Session 상태 확인은 허용합니다.
2. 이미 진행 중인 HTTP·감시 작업이 끝나기를 최대 30초 기다립니다.
3. 현재 DB에 진행 중인 생성·제출·취소 작업이나 살아 있는 제출 Task가 있으면 복원을 거절합니다. ComfyUI 작업을 중단하거나 다시 실행하지 않습니다.
4. 선택한 백업을 Memory DB에 읽고, 백업 당시의 `submitting/pending/running/cancelling` 요청은 `stopped`로 표시합니다. 과거 Prompt ID에 대한 감시·취소가 재개되지 않도록 하기 위한 처리이며 백업 원본은 유지합니다.
5. SQLite backup API로 운영 DB 내용을 복원합니다. 파일을 `unlink/replace`하지 않으므로 다른 SQLite 연결과 Windows Handle을 유지할 수 있습니다.
6. 관리용 DB에 결과를 기록하고 요청 진입을 다시 허용합니다. 현재 브라우저는 관리자 화면을 다시 읽어 복원 전의 화면 Cache를 비웁니다. 로그인 Cookie는 유지합니다.

작업 실패는 이력에 남기며 복원 전 자동 백업은 만들지 않습니다. Schema가 다른 DB를 Migration하거나 부분 복원하는 기능은 없습니다. SQLite backup API의 동작은 [SQLite 공식 문서](https://www.sqlite.org/backup.html)를 따릅니다.

## 진단과 저장 공간

두 기능 모두 사용자가 버튼을 눌렀을 때만 실행하며 DB·실제 파일·Catalog를 수정하지 않습니다. Symlink와 Windows Junction은 따라가지 않습니다. 접근 오류가 있으면 일부 결과가 누락될 수 있음을 표시합니다.

데이터 연결 진단은 다음을 구분하고 경로는 항목당 처음 100개까지 표시합니다.

- DB에 있으나 현재 파일이 없는 결과물
- 현재 파일은 있으나 DB에 등록되지 않은 결과물
- DB에서 삭제 처리됐으나 현재 파일이 있는 결과물
- 즐겨찾기에 연결됐으나 현재 파일이 없는 입력
- 현재 즐겨찾기에서 사용하지 않는 보관 입력

파일 이동·삭제는 되돌리지 않으므로 DB 복원 후 차이가 생길 수 있습니다. 미등록 파일은 복원 시 자동 등록하지 않습니다. 기존 서버 재시작·결과물 수동 새로고침의 Catalog 동기화 동작은 별개로 유지됩니다.

저장 공간은 운영 DB·관리용 DB·백업·결과물·Preview cache·임시 입력·즐겨찾기 입력·로그·기타 runtime을 나누어 파일 크기 합계와 개수를 표시합니다. DB의 WAL·SHM·Journal 파일이 있으면 해당 DB 사용량에 포함합니다. 디스크의 전체·여유 공간도 표시하며 같은 디스크의 여유 공간은 항목끼리 공유합니다. 크기는 파일의 논리 크기 합계이며 삭제 가능 용량이나 실제 할당 용량을 뜻하지 않습니다.

## API

| Method | 경로 | 용도 |
| --- | --- | --- |
| GET | `/api/administration/backups` | 백업 목록과 Schema 호환 여부 |
| POST | `/api/administration/backups` | `{description}` 수동 백업 |
| PATCH | `/api/administration/backups/{backup_id}/description` | `{description}` 설명 변경 |
| DELETE | `/api/administration/backups/{backup_id}` | `{confirmed:true}` 즉시 삭제 |
| POST | `/api/administration/backups/{backup_id}/restore` | `{backup_confirmed:true}` DB 복원 |
| GET | `/api/administration/history?page=1` | 한 페이지 25건의 실행 이력 |
| POST | `/api/administration/diagnostics` | 읽기 전용 연결 진단 |
| POST | `/api/administration/storage` | 읽기 전용 용량 조회 |

## 검증

`tests/test_administration.py`는 임시 DB에서 인증, 백업·복원, 별도 관리 이력 유지, 파일 보존, Schema 불일치, 확인 누락, 설명 검증, 경로 경계, 활성 작업 거절, 과거 활성 상태 중단, 손상·누락 백업, 읽기 전용 진단, 복원 경합, 재시작 이력을 검증합니다.

`tests/browser_administration.cjs`는 독립 API와 Mock ComfyUI를 사용하는 서버에서 Desktop 1280px와 Mobile 390/320px의 진입 위치, 생성·설명 편집, XSS escaping, 삭제·복원 확인 취소, 실제 복원과 이력 유지, 진단·용량 조회, Back/Forward와 가로 넘침을 확인합니다. 운영 DB나 실제 GPU에는 요청하지 않습니다.
