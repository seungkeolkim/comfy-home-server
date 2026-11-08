# Comfy Home Server 내장 구현

## 확정한 구성

2026-11-09 사용자 결정에 따라 Comfy Home Server 내부에 구현합니다. Home Server를 생성 기반으로 쓰고 탐색 Domain을 독립 Module로 분리합니다. 기존 거대한 Engine을 `application.py`에 붙이지 않고 계산·저장·Adapter·UI를 나눕니다.

```text
Style UI → StyleProjectService → Ranking/Evolution 계산
                         ├── ProjectRepository
                         └── RenderPlan → Home 제출 Service
                                           └── 등록 Workflow Adapter → ComfyUI
```

| 항목 | 내장 구현 방침 |
| --- | --- |
| Workflow 일치 | 일반 생성과 같은 Registry/Adapter 사용 |
| Job·Output·인증 | 기존 기능 재사용 |
| UI | 기존 화면에 Style 탐색 기능 추가 |
| 평가 Domain | 계산·저장·제출 책임을 Module로 분리 |
| 운영 | Home Server의 기존 Port와 서비스 수명주기에 통합 |

## 재사용할 실제 코드

| Source | 재사용·확장 |
| --- | --- |
| `home_server/workflows.py` | 등록 Template, API/UI 복제, Anima LoRA·NegPip, Metadata |
| `store_batch_requests` | Job/Request 사전 저장, 입력 Snapshot |
| `_submit_requests` | ComfyUI 제출. 고정Seed·Project 소속 보강 필요 |
| `_monitor_requests`, `_refresh_requests_before_restore` | Browser와 무관한 추적. Render 완료 연결 추가 |
| `ComfyClient` | Queue, History, Submit, 소유ID Cancel |
| `Database`, `OutputCatalog` | 요청·출력 등록·경로 보호·기존 Job 연결 |
| `tag_builder.resolve_anima_prompts` | Positive/Negative Tag 전개. 평가에서는 결과를 고정 |
| LoRA Profiles/Presets | Model/CLIP 등의 Weight 저장. Project 점수와 별개 |
| `request_favorites` | 확정 설정 재사용의 참고. SavedStyle과 동일 Entity는 아님 |

## 단순 호출만으로 해결되지 않는 지점

1. `WORKFLOW_FILES`, `/api/batches` 검증, 제출 Branch가 현재 Anima/MiniMax 중심입니다.
2. `_submit_requests`는 Anima 이외를 MiniMax로 처리합니다. Moss를 이름만 추가하면 안 됩니다.
3. `_history_output_paths`의 Saver ID는 Anima13/나머지2568로 고정됩니다. Adapter의 Output Binding이 필요합니다.
4. 일반 Anima 제출은 Sampling Seed를 난수로 바꿉니다. 비교용 고정 RenderPlan을 추가해야 합니다.
5. `prepare_anima`는 Model/Sampler/Scheduler 모두를 settings로 바꾸는 범용 함수가 아닙니다. 미구현 기능을 UI에 노출하지 않습니다.
6. Home의 Job Folder는 출력 정리 기능으로, 평가·점수·세대 경계를 가진 Style Project를 대신하지 못합니다.
7. Output Sync는 Catalog를 갱신하는 명시적 동작입니다. 일반 화면 조회마다 전체 파일을 다시 탐색하지 않습니다.

## Module 구성안

```text
home_server/style_exploration/
  project_service.py
  project_repository.py
  evaluation_contracts.py
  ranking_algorithms.py
  evolution_algorithms.py
  component_score_estimator.py
  candidate_generation_service.py
  legacy_style_lab_importer.py
```

제안 파일명이며 필요한 시점에 나눕니다. Workflow Registry를 Style 전용으로 복제하지 않고 일반 생성과 공통 위치에서 사용합니다.

## 문서와 구현 상태 관리

설계·요구사항은 이 저장소의 `docs/style-lab-rebuild/`에서 관리합니다. 별도 앱은 현재 구현 범위에 포함하지 않습니다. 저장소 외부의 최초 문서 폴더를 병행 갱신하지 않습니다.

기능 구현 시 해당 요구사항·API·수락 기준과 실제 구현 상태를 같은 변경에서 갱신합니다. 원문 Snapshot은 조사 시점의 복원 근거로 보존하고, 새 코드에 맞춘다는 이유로 덮어쓰지 않습니다. 현재 `/api/batches`만으로 고정 RenderPlan 등 모든 요건을 만족한다고 가정하지 않습니다.

## 이번 작업의 범위

문서 작성에서는 Home Runtime DB 변경, Compose 재기동, 실제 생성, 의존성 추가, Migration을 하지 않습니다. 구현 시점의 Schema와 서비스 상태는 다시 확인해야 합니다.
