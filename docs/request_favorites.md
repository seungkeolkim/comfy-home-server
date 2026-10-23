# 요청 즐겨찾기

2026-10-24. 구현 브랜치: `feat/request-favorites`. Schema **14**.

## 화면과 저장 단위

- 결과물 카드의 `☆`를 누르면 해당 **하위 요청 한 건**을 저장합니다. 같은 요청이 결과물을 여러 개 만들었어도 즐겨찾기는 하나이며 연결된 결과물의 별표가 함께 바뀝니다.
- 결과물 탭의 **작업 분류 아래 `즐겨찾기만` Switch**로 조회합니다. 기본값은 꺼짐이며 Mobile 하단 메뉴는 기존 6개를 유지합니다.
- 작업 분류와 즐겨찾기 조건을 함께 적용합니다. 상위 분류는 하위 분류까지 포함하며, 페이지 이동·탭 이동·Browser 뒤로/앞으로·새로고침에서도 조건을 유지합니다. URL은 `favorites=1`로 공유할 수 있습니다.
- 즐겨찾기 목록은 요청당 대표 결과물을 하나 표시합니다. 미리보기의 이전/다음은 그 요청에 연결된 결과물 안에서 이동합니다. 즐겨찾기 조회에는 파일 다중 선택·파일 이동·파일 삭제 버튼을 표시하지 않습니다. 일반 결과물 조회의 기존 동작을 사용합니다.
- **생성 정보**에서 원본/확정 Positive·Negative Prompt, 당시 선택한 태그 후보와 실제 선택 경로, Seed, 해상도, LoRA를 확인합니다.

## Snapshot과 분류

`request_favorites`는 원본 `job_inputs`와 `request_results`를 독립 JSON으로 보관합니다. 원본 Prompt, 체크된 태그 후보의 ID·참조·이름·본문·weight, 실제 확정 Prompt·태그 선택 경로·Seed·Workflow 설정·LoRA를 저장합니다. 현재 태그를 편집·삭제해도 Snapshot은 바뀌지 않습니다.

`source_request_id`는 요청당 하나의 즐겨찾기만 허용하며 원본 요청 삭제에 종속되지 않습니다. `source_job_id`만 현재 작업에 연결하고 `ON DELETE SET NULL`을 사용합니다. 따라서 분류는 원본 작업의 **현재 분류**를 따르고, 원본 이력이 삭제되면 **미분류**로 조회됩니다. 즐겨찾기에 별도 분류 편집 기능은 추가하지 않습니다.

`favorite_output_links`는 `output_id`로 현재 결과물을 연결합니다. 파일을 이동해도 연결을 유지하며, 원본 이력 삭제 후에도 결과물의 별표는 유지합니다. 결과물 파일을 삭제하면 다른 연결 파일을 대표 이미지로 선택하고, 전부 사라져도 **결과물 파일 없음 · 생성 설정은 보관됨**으로 표시합니다. 즐겨찾기는 결과물 파일의 백업은 아닙니다. 즐겨찾기 해제는 Snapshot과 전용 입력 복사본만 제거하며 원본 이력·결과물은 삭제하지 않습니다.

MiniMax는 저장 시 원본 서버 입력 이미지를 현재 Catalog 경로에서 읽고 `runtime/favorite_inputs/`에 별도 복사합니다. 이미지 형식·관리 경로·50 MB 제한을 검증하며, 원본 입력을 찾을 수 없으면 저장을 거절합니다. 과거 일회성 Upload처럼 원본 입력이 이미 사라진 요청은 완전 복원이 불가능하므로 즐겨찾기로 저장할 수 없습니다. 제출할 때 전용 복사본을 다시 임시 Upload로 복사하여, 접수 직후 즐겨찾기를 해제해도 해당 요청은 실행할 수 있게 합니다.

MiniMax의 기존 요청 결과에는 Seed가 없을 수 있어 Catalog의 실제 생성 파일명 Seed를 우선 사용합니다. unsigned 64-bit Seed가 Browser에서 반올림되지 않도록 즐겨찾기 상세 API는 decimal 문자열로 전달하고, 서버에서 정확한 정수로 변환합니다.

## 복원과 제출

**생성 그대로 복원**이 기본 동작입니다. 확정 Positive·Negative Prompt를 생성 화면에 채우고 태그·wildcard 추첨을 건너뜁니다. 당시 LoRA와 확정 설정, 고정 Seed, MiniMax 보관 입력을 적용하며 요청 수는 **1건**으로 고정합니다.

**원본으로 변형**은 원본 Prompt와 **보관된 태그 후보**를 채웁니다. 생성 화면에 Snapshot 후보 Checkbox를 별도로 표시하며 현재 전역 태그 DB를 변경하지 않습니다. 후보를 선택·해제할 수 있고 제출 시 태그·wildcard를 다시 추첨합니다. 생성 Seed는 이 모드에서도 고정합니다.

두 방식 모두 생성 화면으로 이동만 하며 **작업 제출**을 눌러야 새 작업을 접수합니다. 복원 패널에서 모드를 바꿀 수 있고 **복원 해제** 또는 Workflow 변경으로 고정 복원 상태를 종료합니다. 복원 중 조합 미리보기는 비활성화합니다. 원본 복원은 보관 후보를 사용하므로 일반 미리보기의 현재 태그 DB 조회와 의미가 다릅니다.

저장된 LoRA를 현재 ComfyUI에서 찾을 수 없으면 제출을 거절하여 누락된 조합으로 실행하지 않습니다. Workflow 파일·Model·LoRA 파일 내용·실행 환경이 달라지면 같은 Prompt·Seed라도 결과가 같다고 보장할 수 없습니다.

## API

| Method | 경로 | 동작 |
| --- | --- | --- |
| PUT | `/api/outputs/{output_id}/favorite` | 해당 요청 저장. 재호출은 기존 즐겨찾기 반환 |
| GET | `/api/favorites` | `page`, `page_size`, `folder_id`, `job_id`, `request_id`로 조회 |
| GET | `/api/favorites/{favorite_id}` | 원본·확정 Snapshot 상세 |
| DELETE | `/api/favorites/{favorite_id}` | 즐겨찾기만 해제 |
| POST | `/api/favorites/{favorite_id}/batches` | `restore_mode=exact/source`, 고정 Seed·단건 제출 |

즐겨찾기 목록은 한 페이지 최대 64건이며 API의 `page_size` 상한은 100입니다. 목록에서는 Snapshot JSON·원본 이미지 전체를 읽지 않고 DB metadata만 조회합니다. 일반 결과물 목록에는 index로 연결한 `favorite_id`를 추가하며 기존 Catalog 정렬·pagination을 유지합니다.

## Migration과 Rollback

Schema 13 DB는 서버 시작 시 SQLite backup API로 `runtime/backups/*_before_request_favorites_*.sqlite3` 백업을 만들고 무결성을 확인한 뒤 두 테이블과 index를 추가합니다. 기존 작업·요청·분류·시각·JSON·결과물 파일은 보존하고 즐겨찾기는 빈 상태로 시작합니다. 운영 DB의 전환은 새 코드를 실행할 때 이뤄집니다.

Schema 13 코드로 돌아가려면 서버를 중지하고 현재 DB를 추가 백업한 뒤, 실제 `PRAGMA user_version`이 14인지 확인하여 다음 Transaction을 적용합니다. **즐겨찾기 설정은 제거되며 새로 생성한 작업과 결과물은 유지됩니다.**

```sql
BEGIN IMMEDIATE;
DROP TABLE favorite_output_links;
DROP TABLE request_favorites;
PRAGMA user_version = 13;
COMMIT;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

보관 입력 파일은 이 SQL로 삭제하지 않습니다. Rollback 후에는 `runtime/favorite_inputs/`를 별도 보관하거나 필요 여부를 확인한 뒤 정리할 수 있습니다. 이전 시작 시각·작업 분류 기능까지 되돌릴 때는 먼저 이 단계로 Schema 13으로 전환합니다.

## 검증

- `tests/test_request_favorites.py`: 요청 중복 방지, 분류 교집합, 이동·이력 삭제·파일 삭제 후 보관, 원본 후보와 확정 입력의 복원, 단건 고정, unsigned Seed, MiniMax 입력 복사·고정 Seed, Migration 백업.
- `tests/browser_request_favorites.cjs`: 실제 임시 DB·API와 Edge의 1280/390/320px 화면에서 별표 연동, 분류·History·탭·Reload 유지, 요청 내 미리보기, 상세 정보, 보관 후보 Checkbox, 자동 제출 없는 복원, 실제 단건 제출, 이력 삭제 후 미분류 이동·해제. MiniMax의 과거 작업 입력 선택 정보가 현재 선택으로 재검증되지 않고 보관 이미지로 제출되는지도 확인합니다.
- 기존 결과물 분류·삭제/이동·미리보기·탭 탐색·작업 복원·MiniMax 입력 선택 Browser 검증도 수행합니다.

검증은 임시 DB·Fake ComfyClient를 사용합니다. 운영 DB와 실행 중인 ComfyUI 작업은 변경하지 않습니다.
