# 작업 분류

2026-10-19. 구현 브랜치: `feat/job-history-folders`. 작업 분류 도입 Schema: **12**. 현재 Schema **13**의 추가 변경은 [작업 경과시간](job_elapsed_time.md)을 참고하세요.

## 화면과 동작

- PC는 왼쪽 분류 트리, 오른쪽 기존 작업 카드 목록을 사용합니다. 모바일은 상단의 현재 경로를 누르면 분류 패널을 펼칩니다.
- `전체 작업`은 전체 조회, `미분류`은 소속 없는 작업 조회입니다. 시스템 항목은 생성 깊이에 포함하지 않으며 수정·삭제할 수 없습니다.
- 사용자 분류는 최대 3단계입니다. 분류 옆 숫자와 상위 분류 목록은 모든 하위 분류의 작업을 포함합니다.
- `＋ 새 분류`는 현재 위치 아래에 생성합니다. 3단계에서는 생성 버튼이 비활성화됩니다. 현재 분류 옆 `⋯`에서 이름·위치 변경과 삭제를 제공합니다.
- 분류 이름은 앞뒤 공백을 제거한 한 줄 1~80자입니다. 경로 구분자·줄바꿈·NUL을 허용하지 않습니다. 같은 부모 아래에서는 대소문자 구분 없이 중복을 거부합니다(SQLite NOCASE 기준).
- 분류 이동 시 자신·자식 아래로 이동할 수 없으며, 모든 하위 분류를 포함해 최대 3단계인지 다시 검증합니다.
- 작업당 소속은 하나입니다. 작업 카드의 분류 경로를 누르면 단건 이동, `선택` 모드에서는 페이지 간 선택을 유지하며 다중 이동합니다. 전체 선택은 현재 분류·설명 검색·특정 작업 필터에 맞는 전체 페이지를 대상으로 합니다.
- 진행 중·삭제 보호 작업도 선택과 분류 변경이 가능합니다. 삭제 버튼은 선택된 작업 중 실제 삭제 가능한 수만 표시·처리하며 기존 보호 및 활성 상태 검증을 유지합니다.
- 분류 삭제 확인창에 하위 분류·작업 수를 표시합니다. 삭제한 분류 및 모든 하위 분류의 작업은 미분류로 이동합니다. 작업 이력·입력 Snapshot·개별 요청·실제 결과물은 보존합니다.
- 설명 검색은 현재 분류 범위에 적용하며 `%`, `_`도 일반 문자로 취급합니다. 다른 분류 조회 시 검색은 초기화하며 페이지 이동·탭 이동·Browser 뒤로/앞으로는 분류·검색 조건을 유지합니다.
- 작업 카드에 현재 가용 결과물 최대 3개의 Thumbnail을 표시합니다. 기존 이미지/영상 Thumbnail Cache를 사용하고 원본이나 영상 미리보기를 미리 다운로드하지 않습니다. 클릭하면 해당 작업 범위의 기존 미리보기를 열어 이전·다음 이동과 삭제를 제공합니다.
- 생성 화면의 `작업 분류`는 기본 미분류이며 제출 후 입력을 유지합니다. 작업 복원 시 현재 소속을 사용합니다. 실제 결과물 저장 경로를 지정하는 기능과 독립적입니다.
- 다른 접속에서 현재 분류가 삭제되면 다음 조회에서 미분류로 복귀합니다. Polling은 편집 Dialog 입력과 분류 트리 펼침 상태를 덮어쓰지 않습니다.

화면에서는 작업 정리를 `분류 변경`, 실제 저장 위치 변경을 `파일 이동`으로 구분합니다. 기존 API·DB 식별자 `folder_id`와 테이블 이름은 유지하며, 이 용어 변경으로 데이터 Migration을 추가하지 않습니다.

## 결과물의 작업 분류 조회

- 결과물 화면 상단의 `작업 분류`에서 `📋 전체 결과물`, `📥 미분류`, 기존 `📁 작업 분류 경로`를 선택합니다. 상위 분류는 모든 하위 분류의 결과물을 포함합니다.
- 실제 파일 경로와 무관하게 작업의 현재 소속으로 조회합니다. 작업 분류 변경은 다음 조회에 반영되며, 파일 이동 후에도 같은 작업 분류로 조회됩니다.
- 미분류에는 소속 없는 작업의 결과물과 외부 추가·이력 삭제로 작업 연결이 없는 파일도 포함됩니다. 선택한 분류가 삭제되면 다음 조회에서 미분류로 전환합니다.
- 페이지 이동·탭 이동·Browser History·URL 복사·새로고침에서 분류 조건을 유지합니다. 분류를 바꾸면 첫 페이지로 이동하고 기존 선택은 초기화합니다.
- 결과물 전체 선택과 미리보기의 이전·다음 이동도 현재 분류 범위에 적용합니다. 기존 단일 작업·요청 결과 보기는 유지하며, 분류 선택으로 조회 범위를 바꿀 수 있습니다.
- `GET /api/outputs`, `/api/outputs/selection-candidates`, `/api/outputs/deletion-candidates`, `/api/outputs/{output_id}/neighbors`에 optional `folder_id`를 지원합니다. 빈 값은 전체, `unassigned`는 미분류입니다. 없는 분류는 404를 반환합니다.
- 기존 분류·소속 테이블과 결과물 Catalog의 작업 연결을 사용하며 추가 Schema Migration이나 실제 파일 변경은 필요하지 않습니다.

`tests/test_output_job_folders.py`와 `tests/browser_output_job_folders.cjs`에서 하위 분류·미분류·영상·보호 결과물·페이지 경계·전체 선택·미리보기·소속/파일 이동·이력/분류 삭제 및 Desktop/Mobile History 복원을 검증합니다.

## 저장소와 API

- `job_folders(folder_id, name, parent_id)`: ID 기반 트리, 부모 삭제는 하위 분류에 Cascade 적용.
- `job_folder_assignments(job_id, folder_id)`: 작업당 최대 한 행. 행이 없으면 미분류. 작업·분류 삭제 시 소속 행만 Cascade 삭제.
- 기존 `jobs`, 공통 입력·요청·결과 Catalog 테이블의 column과 JSON은 변경하지 않습니다.
- Schema 11에서 시작할 때 `runtime/backups/*_before_job_folders_*.sqlite3` 백업을 검증한 뒤 Schema 12로 전환합니다.
- 분류 편집·하위 삭제·일괄 이동은 `BEGIN IMMEDIATE` Transaction에서 검증과 변경을 수행합니다. 하나라도 없는 작업이면 일부 작업만 이동하지 않습니다. 제출 시 소속 지정도 작업 저장과 같은 Transaction입니다.
- 분류 조회·작업 목록·선택 후보는 DB만 읽습니다. 동기 API는 JSONResponse 직렬화까지 Worker에서 처리합니다.

| API | 용도 |
| --- | --- |
| `GET /api/job-folders` | 트리·경로·하위 포함 작업 수 |
| `POST /api/job-folders` | 이름·부모로 생성 |
| `PUT /api/job-folders/{folder_id}` | 이름·부모 변경 |
| `DELETE /api/job-folders/{folder_id}` | 하위 삭제 및 미분류 이동 |
| `POST /api/jobs/folder` | `job_ids`, nullable `folder_id`로 일괄 이동 |
| `GET /api/jobs/selection-candidates` | 현재 범위의 전체 ID 및 삭제 가능한 ID |
| `GET /api/jobs` | `folder_id`, `search` 추가; `folder_id=unassigned`는 미분류 |
| `POST /api/batches` | optional `folder_id`로 제출 시 소속 지정 |

## Rollback

아래 SQL은 Schema 12 기준입니다. Schema 13에서는 먼저 [작업 경과시간의 Rollback](job_elapsed_time.md)으로 시작 시각 Column만 제거해 Schema 12로 전환해야 합니다.

이전 코드는 Schema 12를 읽지 않으므로 코드만 되돌리면 서버가 기동되지 않습니다. 서버를 중지하고 **현재 DB도 추가 백업한 뒤** 다음 Transaction으로 분류 정보만 제거하면 기존 Schema 11 코드로 복귀할 수 있습니다. 이 방식은 시험 사용 중 새로 제출한 작업과 결과물도 보존합니다. 실제 DB 경로는 `runtime/` 아래 운영 DB를 확인해서 사용합니다.

```sql
-- PRAGMA user_version이 12인지 먼저 확인한 뒤, 중지된 서버의 DB에서 실행합니다.
BEGIN IMMEDIATE;
DROP TABLE job_folder_assignments;
DROP TABLE job_folders;
PRAGMA user_version = 11;
COMMIT;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

분류 분류도 보존해야 한다면 위 Transaction 전 백업을 유지합니다. Migration 직전 백업 전체 복원은 그 이후 생성한 작업 이력을 잃을 수 있으므로, 단순 UI Rollback에는 위의 분류 테이블만 제거하는 방법을 사용합니다. 이 문서의 Rollback은 검증용 임시 DB에서만 시험했으며 운영 DB에는 실행하지 않았습니다.

## 검증

- API/DB: 3단계·하위 깊이·순환·중복, 재시작, Schema 11 백업, 분류 전용 Rollback, 하위 삭제 시 기존 작업·JSON·결과 Catalog·실제 파일 보존, 보호·활성 작업 이동, 원자적 실패, 조회·검색·전체 선택 범위.
- 실제 격리 HTTP 서버와 Edge Desktop/Mobile: 분류 탐색, 검색·페이지·탭·History 보존, 생성 입력 유지, Thumbnail 및 작업 범위 미리보기, 다중·보호·실행 중 이동, 생성·이름·부모 변경, 삭제 및 다른 접속의 삭제 복구.
- 기존 설명 편집, Prompt 접기, 작업 복원, 작업·결과물 삭제, 미리보기와 탭 탐색 회귀 검증.

Mobile 검증은 실제 휴대전화가 아닌 390px Viewport/Touch Emulation입니다. Browser 검증은 운영 DB와 분리된 임시 서버를 사용합니다.
