# 프로젝트 Fork와 세대별 설정 Snapshot

2026-11-17 사용자 결정과 실제 구현을 정리합니다. 06·19·21번의 후보·이미지·Elo까지 공유하는 옛 분기안은 이 계약으로 대체합니다.

## 사용 흐름

프로젝트 카드의 **Fork**를 누르고 출발 세대와 새 이름을 선택합니다. 기본은 설정만 복사하며 **선호도 Score·승패도 가져오기**를 켜면 작가 태그·LoRA의 ±Score와 누적 승패도 복사합니다. 여기서 Score는 성분 선호도이며 조합 Elo가 아닙니다.

어느 세대에서 출발하더라도 새 프로젝트는 **0세대, 이미지 없음**으로 시작합니다. 첫 생성은 세대001이며 기존 그림체 화면에서 직접 시작합니다. 이미지·조합·조합 Elo·Vote·현재 대결·CHS 작업·출력 폴더·LoRA 조합 등록본·즐겨찾기는 복사하지 않습니다. 새 Project/Evaluation ID와 독립 출력 경로를 발급합니다.

원본의 저장하지 않은 화면 초안은 복사하지 않습니다. Fork 완료 후 새 프로젝트 설정을 열며 다른 프로젝트의 초안은 보존합니다. 카드에는 원본 이름과 출발 세대를 표시합니다.

## 세대별 저장 시점

- 새 프로젝트를 만들면 생성 전 설정을 0세대 Snapshot으로 저장합니다.
- 프로젝트 설정 저장 때 현재 세대의 Snapshot을 같은 Transaction에서 갱신합니다. Prompt·이름·Seed·생성 조건·작가/LoRA 사용 여부·개수·STR 범위를 포함합니다. STR 고정값은 기존처럼 최소=최대로 표현합니다.
- 첫 생성 제출 시 현재 세대가 1로 바뀌고 1세대 Snapshot을 만듭니다. 계획 미리보기만으로는 0세대를 끝내지 않습니다.
- 세대 확정 때 해당 세대 설정과 성분 Score·승패를 함께 저장합니다. 첫 진화 제출 전에도 부모 세대의 Checkpoint에서 저장합니다.
- 같은 프로젝트·같은 세대는 마지막으로 저장한 상태 하나를 유지합니다. 내용이 바뀌면 Snapshot Revision을 올립니다. 다음 세대로 진행한 후에는 지난 세대의 마지막 저장 상태를 유지합니다.

Fork 선택지에는 실제 저장된 세대와 마지막 저장 시각을 표시합니다. 현재 세대는 마지막 설정 저장·세대 확정 시점의 상태입니다. 개별 Vote마다 별도 설정 버전을 추가하는 기능은 아닙니다. 기존 프로젝트에 기록되지 않은 0세대나 중간 세대를 추측해 만들지 않습니다.

설정 변경과 Snapshot 저장은 함께 성공하거나 함께 Rollback합니다. 기존의 이미지·복원을 위한 불변 `style_generation_checkpoints`와는 별개의 문서이며, 옛 Checkpoint를 다시 조회해 최신 설정 Snapshot을 덮어쓰지 않습니다.

## 복사 범위

| 정보 | 설정만 | 선호도·승패 포함 |
| --- | --- | --- |
| Prompt 이름·본문·Negative, Seed·해상도·Steps·CFG·Workflow 선택 | 복사 | 복사 |
| 작가/LoRA 사용 여부·개수·STR 범위 | 복사 | 복사 |
| 작가/LoRA ±선호도 Score | 0부터 | Snapshot 기준값 복사 |
| 작가/LoRA 승·패·비교 횟수 | 0부터 | Snapshot 기준값 복사 |
| 조합·이미지·조합 Elo·Vote·세대 이력·CHS 작업 | 새로 시작 | 새로 시작 |

성분 Score는 기존 Ridge 산식으로 계산합니다. Fork 기준 Score는 독립적인 Prior로 보관하고 **표시 Score = 가져온 Score + 새 프로젝트에서 계산한 Score**로 사용합니다. 승패도 가져온 기준값과 새 관측을 구분해 합산합니다. 설정 카드에는 이전 Score·승패와 새 비교 횟수를 표시합니다. 원본이 바뀌거나 이미지가 삭제돼도 이미 복사한 기준값은 바뀌지 않습니다.

다시 Fork할 때는 그 시점의 합계만 한 번 복사합니다. 원본 Vote를 새 Vote로 만들지 않고, Undo는 새 프로젝트에서 발생한 Vote만 대상으로 합니다. 새 조합은 기존 초기 Elo 10000·전적0으로 시작합니다.

이후 진화 추첨에는 합산된 성분 Score를 사용하며 기존 종류별 선택 보정 0.5~2배를 유지합니다. 사용 제외·개수·STR 범위·0.05 배수·LoRA CLIP 1 정책은 그대로 적용합니다. 첫 Random 조합은 기존 초기 추첨 정책을 사용합니다.

Snapshot에는 Workflow Identifier·모델 Identifier·API/UI Hash만 저장합니다. 거대한 Workflow Graph나 이미지 참조는 넣지 않습니다. 새 프로젝트는 선택한 CHS 등록 Workflow를 새로 고정하므로 과거 Graph를 실행하는 복원 기능과 구분합니다.

## 실제 저장·API

Schema 21에서 다음 테이블을 추가합니다.

- `style_project_generation_snapshots`: Project/Evaluation·세대, Snapshot ID·Revision·JSON·Hash, 생성·갱신 시각, 선택적 원본 Checkpoint ID. `(project_id, generation_number)`는 유일합니다.
- `style_project_forks`: 대상 Project, 원본 Project 이름/ID·Evaluation·세대·Snapshot ID/Hash, 통계 복사 여부와 독립 성분 기준값 JSON, Operation ID·요청 Hash·생성 시각.

Schema 20 DB는 먼저 검증된 자동 Backup을 만들고 Migration합니다. 기존 Checkpoint에서 빠진 과거 세대를 추출하고 현재 저장 설정을 현재 세대에 반영합니다. 기존 후보·점수·Vote·작업·파일을 수정하지 않습니다. Timeline이 없던 평가에는 실제 생성 이력을 기준으로 초기 번호를 채웁니다.

`GET /api/style-projects/{project_id}/fork-options`는 저장된 Snapshot 목록과 요약·Revision을 반환합니다. `POST /api/style-projects/{project_id}/forks`는 다음 값을 받습니다.

```json
{
  "name": "새 탐색 프로젝트",
  "sourceSnapshotIdentifier": "선택한 Snapshot ID",
  "expectedSnapshotRevision": 3,
  "includeComponentStatistics": false,
  "operationIdentifier": "재시도에도 유지하는 고유 요청 ID"
}
```

Home의 인증을 공유합니다. 다른 프로젝트 Snapshot은 404, 오래된 Revision·손상된 Snapshot은 409로 거부합니다. 같은 Operation ID와 같은 내용의 재전송은 같은 프로젝트를 반환하고, 다른 내용은 409입니다. 설정·출처·기준값·대상 0세대 Snapshot을 하나의 Transaction에서 생성합니다. 생성 Job이나 GPU 요청은 제출하지 않습니다.

## 검증

`tests/test_style_project_forks.py`는 0세대·지난 세대·현재 세대 설정 저장, Score/승패 복사 선택, 독립 이미지·Elo, 재 Fork, 원본 삭제 격리, 동시 재시도, 오래된 Revision, 인증, 저장 Rollback, 자동 Snapshot과 Migration을 검증합니다.

`tests/browser_style_project_forks.cjs`는 별도 Fixture 서버에서 320·390·768·1280px 화면, 설정 초안 보존, 설정만/통계 포함/0세대 Fork, 완료 응답 유실 후 재시도와 자동 생성·투표 요청이 없음을 확인합니다. 운영 프로젝트에 검증용 Fork나 이미지를 만들지 않습니다.

2026-11-17 검증: Python 전체 577 Passed·1 Skipped, Fork 전용 15개를 포함합니다. 네 화면 폭의 Browser 검증과 JavaScript Syntax·Diff 검사를 통과했습니다. 운영 DB 복사본은 기존 34개 테이블의 업무 행을 보존했고, 누락됐던 Timeline 한 행만 실제 생성 이력으로 초기화했습니다. 과거 설정 Snapshot 35개를 추출했으며 `quick_check`와 Foreign Key 검사를 통과했습니다.
