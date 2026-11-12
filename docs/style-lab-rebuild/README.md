# Style Lab 복원·프로젝트 확장 설계 문서

**현재 실제 연결:** `/style`에 프로젝트 설정 저장, Random 조합·여러 Prompt 이미지 생성, 작업·출력 분리, [투표·Elo·Undo](phase_four_review.md)를 연결했습니다. 사용자 진행 요청으로 [진화 1회: 부모 선정·자녀 생성·Selection·세대 확정/취소](phase_five_review.md)를 추가하며, 작은 Cycle의 사용자 확인을 기다립니다. 기존 `/style-preview`는 예시 목업입니다.

**그림체 통합:** [검토한 목업](ranking_preview_review.md)에 따라 실제 순위·Elo·전적, 조합별 여러 Prompt의 작은 이미지와 Viewer를 그림체 탭에 통합했습니다. 진화 후 퇴역·취소 조합도 필터로 조회합니다. Mobile 메뉴는 프로젝트·생성·선별·진화·그림체의 다섯 개입니다.

**사용성 보완:** [8389 비교·Elo 수정·조합 폐기·공통 Viewer·고정 선호 버튼](style_usability_review.md)을 연결합니다. 표시 이름은 파일의 세대·조합 규칙을 따르고 Mobile Viewer는 CHS의 기존 Thumbnail Cache를 사용합니다.

**이미지 표시:** [선별 카드 Fit과 Mobile Viewer 바깥 공간](style_image_fit_review.md). 이미지 비율에 맞는 카드와 위·아래 Touch로 닫을 수 있는 미리보기 여백을 적용합니다.

**자동 Placement:** [신규 조합의 자리 찾기·미확정 Elo](automatic_placement_review.md). 전체 기존 순위표와 같은 구간의 신규 조합을 비교하고, 자리를 확정한 뒤 세대 선별을 완료합니다. 진행 중인 세대의 기존 표와 Undo는 유지합니다.

**그림체 폐기:** [Elo·비교 상태와 CHS 생성 이력 정리](style_deletion_cleanup_review.md). 삭제한 조합의 요청을 제거하고 빈 작업도 지우며, 다른 조합과 공유한 작업은 남은 요청만 유지합니다.

**저장·Web 조작 재정리:** [Prompt 저장 오류와 8389 기준 사용성 재정리](style_web_usability_rework.md). 생성 후 Prompt 저장 차단과 미기록 LoRA 오판을 수정하고, 같은 조합의 새 Prompt 생성과 간결한 선별·저장 화면을 연결합니다.

**현재 우선 작업:** [진화 탭과 반복 세대 생성](generation_cycle_review.md). 생성은 세대 후보를 준비하고, 선별 뒤 확정과 다음 후보 생성을 이어갑니다. 후속 피드백으로 프로젝트 목록·현재 선택 표시와 명시적인 카드 선택을 복원했습니다. 그림체 보관·일반 생성 적용보다 이 Cycle을 먼저 사용자 확인합니다.

작성일: 2026-11-08, Asia/Seoul. 실제 설치본과 Comfy Home Server 소스를 읽어 작성했습니다.

## 목적과 확정한 방향

기존 Style Lab의 **후보 생성 → A/B 선별 → 진화 → 그림체 확보**를 Comfy Home Server 내부에 구현하고, 프로젝트별로 독립적인 취향 탐색을 할 수 있게 합니다. **Comfy Home Server에 등록된 Workflow를 생성 기준으로 사용**합니다. Anima 외에 Moss 등 추가 모델을 수용하는 구조가 필요합니다.

2026-11-09 사용자 결정에 따라 구현 방식은 **Comfy Home Server 내장**으로 확정했습니다. 이 저장소의 `docs/style-lab-rebuild/`가 문서 기준본이며 앞으로 설계·요구사항·구현 상태를 코드와 함께 관리합니다. 2026-11-10 정리 시 외부 최초 작성본의 대응 문서와 동일한 Source Snapshot이 이곳에 있음을 확인하고 중복 폴더를 휴지통으로 이동했습니다. 이후 수정은 이곳에만 반영합니다.

프로젝트 시작은 다음 세 가지를 지원합니다.

1. **새로 시작**: 등록 작가·LoRA를 선택하되 조합·투표·점수·세대는 새로 시작합니다.
2. **점수만 이어받기**: 선택한 원본에서 작가·LoRA 점수 Snapshot만 가져옵니다. 기존 조합, 이미지, 승패, 세대, 진행 중 작업은 이어받지 않습니다.
3. **현재 상태·확정 세대에서 분기**: 같은 조건의 조합·Elo·통계·계보·잠금·이미지 참조를 Snapshot으로 이어받은 새 프로젝트를 만듭니다. 이후 작업은 원본과 독립적입니다.

수동 조합·다듬기는 후순위입니다. **융합도 유지할 기능**이며 다른 기능을 만든 뒤 비율 지정·3개 이상 원본 지원으로 확장합니다. 자동 후보 조합은 선별·진화의 입력이므로 핵심 범위에 포함합니다. 기존 메뉴 `조합` 전체를 없애는 의미로 해석하지 않았습니다.

**특정 세대의 확정 시점으로 돌아가기**도 P0에 포함합니다. 확인창 하나로 이후 이미지·이력·승패·Elo 변경의 삭제를 경고하고 당시 상태를 복원합니다.

탐색은 기존 Interactive Evolution을 유지하면서 여러 계보에 부모 기회를 배정합니다. **현재 상위 N개 조합의 Prompt 재시험**도 P0입니다. 성분·가중치와 세대 번호를 유지한 채 새 Prompt로 생성하고, 시험 내부 Elo·Drop을 거쳐 새 평가 구간으로 채택할 수 있습니다.

추가로 **성분·Weight 일부 잠금, 탐색 분기, Ablation, 대표 Prompt·Seed 검증 세트, 비교 후보 추천**을 모두 채택했습니다. 잠금·분기는 P0, 진단·검증·규칙 기반 추천은 P1로 구현합니다. 상세 계약은 [19번 문서](19_adopted_exploration_tools.md)를 따릅니다.

## 문서 읽는 순서

**Phase 0 화면 검토:** Home Server의 `/style-preview`에서 예시 UI를 조작할 수 있습니다. [접속·확인 순서와 검토 항목](phase_zero_review.md)을 확인하세요. 사용자가 목업을 확인했으며, 그림체 탭의 프로젝트 선택 UI는 후속 수정으로 남깁니다. 실제 프로젝트 저장은 별도의 `/style`에 연결했습니다.

Mobile 피드백은 [21번 결정 기록](21_project_context_settings_and_fork.md)에 반영했습니다. 같은 창 전환·조합 단위 한 번 선택·STR 표시·프로젝트별 그림체를 적용하고, 글로벌/프로젝트 설정과 현재 프로젝트 맥락·Fork의 후속 범위를 정리합니다.

실제 생성 전 [22번 작업·출력 분리 결정](22_style_job_output_separation_and_project_rename.md)을 추가했습니다. 모델/프로젝트별 자동 분류와 전용 출력 루트, 세대부터 작성하는 메모, 일반 화면의 선택적 표시, 프로젝트 Rename 시 폴더·분류명 동반 변경과 수동 이동 금지를 따릅니다. 출력 형식은 기존 Workflow 설정을 유지합니다.

**설정 목업 확인 완료:** [글로벌·프로젝트 설정 화면](settings_preview_review.md)의 검토를 마쳤고 실제 DB 저장은 1단계에 연결했습니다. 프로젝트별 Prompt·성분 범위, 글로벌 기본값 적용 Preview, CHS와 같은 Workflow 옵션과 작가 Bulk 등록을 사용할 수 있습니다.

2026-11-10의 [Web UX와 세 가지 개선 요구](20_web_ux_fusion_multi_prompt_and_component_differences.md)를 반영합니다. UX 기준은 현재 localhost:8389의 Style Lab Web·Mobile입니다. 여러 Prompt의 결과를 함께 보는 일상 탐색과 성분 차이 기반 탐색 제외를 초기 설계에 반영하며, 구체적인 투표 집계·UI는 사용자와 확인합니다. 과거 단일 Prompt 탐색 설명은 이 확장과 함께 읽습니다.

구현을 시작할 때는 [함께 만드는 개발 과정](development_process.md)을 먼저 확인합니다. 기능을 작은 사용자 행동 단위로 구현하고 직접 사용한 결과를 확인한 뒤 다음 단계로 진행합니다. 아래 문서는 요구사항과 복원 근거이며, 기존 화면·저장 구조 제안을 한꺼번에 구현하라는 지시가 아닙니다.

| 문서 | 내용 |
| --- | --- |
| [01 기존 기능과 우선순위](01_current_features_and_priorities.md) | 현재 동작, 메뉴, 복원 범위 |
| [02 기존 데이터와 API](02_legacy_data_and_api_contracts.md) | State, DTO, 저장·내보내기, API |
| [03 선별·순위 알고리즘](03_selection_and_ranking_algorithms.md) | Elo, 자리 찾기, Skip, Undo, 동점 |
| [04 진화·성분 점수](04_evolution_and_component_scores.md) | 부모 선택, 변이, 생존, 작가·LoRA 점수 |
| [05 생성·Workflow 계약](05_generation_and_registered_workflows.md) | 실제 두 Workflow 차이, Seed·LoRA·NegPip |
| [06 프로젝트와 점수 이전](06_projects_and_score_transfer.md) | 이번 요구의 중심, 독립성, 초기화, Prior |
| [07 새 Domain·API 설계](07_proposed_domain_storage_and_api.md) | 테이블, 불변식, 동시성, 요청 예시 |
| [08 Home Server 내장](08_comfy_home_server_integration.md) | 확정한 내장 구조, 기존 코드 재사용, 확장 지점 |
| [09 화면·사용 흐름](09_user_interface_and_scenarios.md) | 프로젝트 중심 PC·모바일 UI |
| [10 이관·검증](10_migration_restore_and_acceptance.md) | 복원 절차, Migration, 수락 테스트 |
| [11 구현 순서](11_implementation_backlog_and_decisions.md) | P0/P1/P2, 미확정 사항, 구현 티켓 |
| [12 조사 근거](12_source_inventory_and_contract_evidence.md) | 자동 추출한 설정·함수·Workflow·State 구조 |
| [13 실제 점수 Seed](13_existing_artist_and_lora_score_snapshot.md) | 원본 State에서 계산한 작가·LoRA 점수 Snapshot |
| [14 Custom Node 의존성](14_custom_node_dependencies.md) | 등록 Anima Workflow에 필요한 설치본과 Version 근거 |
| [15 세대 되돌리기](15_generation_restore_and_deletion.md) | Checkpoint·삭제 경고·승패/Elo 복원·동시성·검증 |
| [16 탐색 정책과 다양성](16_search_strategy_and_diversity.md) | Interactive Evolution 유지, 계보별 기회, 대안의 적용 범위 |
| [17 Prompt 재시험](17_prompt_retests_and_reranking.md) | 상위 N개 고정 조합 재생성, 시험 Elo·Drop·채택 |
| [18 작업 공간·화면 목업](18_workspace_navigation_and_screen_mockups.md) | 일반 생성/스타일 구성 분리, Desktop·Mobile 화면 목록과 전환 |
| [19 채택한 탐색 보조 기능](19_adopted_exploration_tools.md) | 일부 잠금·독립 분기·Ablation·Prompt/Seed 검증·비교 추천 |
| [20 Web UX·비율 융합·여러 Prompt·성분 차이](20_web_ux_fusion_multi_prompt_and_component_differences.md) | 8389 Web·Mobile 기준, 다중 원본 융합, 일상 다중 Prompt 평가, 차이 보기·탐색 제외 |
| [21 프로젝트 맥락·설정·Fork](21_project_context_settings_and_fork.md) | Phase 0 피드백, 단일 조합 선택, STR, 프로젝트 필터, 글로벌/프로젝트 설정, 다른 프로젝트 그림체 시험·Fork |
| [22 작업·출력 분리와 프로젝트 이름 변경](22_style_job_output_separation_and_project_rename.md) | 자동 분류·세대 메모·전용 출력, 선택적 표시, 프로젝트 Rename과 이동 금지 |
| [목업 보기·편집](mockups/README.md) | 독립 HTML 미리보기, 공통 소스, 화면 Snapshot |
| [원문 Snapshot 목록](source_reference/README.md) | 복원에 필요한 원문을 코드 블록으로 보관 |

## 사실과 제안의 구분

`현재`·`기존`은 설치본의 동작입니다. `새 설계`·`제안`은 아직 구현하지 않은 요구사항입니다. 제안 API·Schema·Moss Adapter가 이미 존재한다고 해석하면 안 됩니다. 원문 Snapshot은 동작을 재검토할 때의 기준이고, 원본 README와 현재 코드가 다르면 코드가 우선합니다.

원본 Style Lab은 `VERSION = 2.0.0`이나 Web 모드·NegPip·LoRA 경고 분리 등 로컬 변경이 포함돼 있습니다. 같은 Version 문자열의 배포본만으로 이 설치본을 식별할 수 없으므로 Snapshot의 SHA-256을 함께 확인해야 합니다.

## 산출물 범위

설계·복원 근거는 **Markdown으로 읽고 옮길 수 있는 구현 자료 묶음**입니다. 설명에 더해 Style Lab의 Python·JavaScript·CSS·HTML·실행 스크립트·테스트와 현재 Workflow를 Markdown 코드 블록으로 보관했습니다. Home Server의 연동 핵심 소스와 Anima API/UI Workflow도 포함합니다. 별도 `mockups/`에는 UI 검토용 HTML·공통 소스·화면 Snapshot을 관리합니다.

원본 Python Runtime, 모델·LoRA Tensor 파일, 사용자 생성 이미지, 전체 State·투표 이력, 비밀번호·Cookie·인증 파일은 포함하지 않습니다. 따라서 문서에서 로직과 텍스트 UI를 복원할 수 있지만, 기존 이미지까지 그대로 돌려놓는 운영 Backup은 별도로 필요합니다. 본문 예제 Prompt는 설명용이며 실제 사용자 Prompt를 복제하지 않았습니다. 바이너리 아이콘은 제외하고 SVG 원문을 보관합니다.

이번 작업은 문서 작성입니다. 원본 서비스·Workflow·데이터를 변경하거나 재기동하지 않습니다.

## 검증

원문 Snapshot 63개를 Markdown에서 다시 추출해 Hash를 대조했습니다. Python Snapshot 18개는 Syntax를 확인했고, 문서 내부 링크·코드 블록·인증 정보 포함 여부도 검사했습니다. 실제 프로그램 실행이나 생성 테스트를 대신하는 검증은 아닙니다.

기본 UI 목업은 Desktop·Mobile의 9개 주요 화면을 Light/Dark에서 확인한 36개 화면 시나리오와 320px 축소 배치를 검토했습니다. 작업 공간 전환 후 입력 유지·시험 Elo·Drop/취소·채택·단일 복원 확인창도 확인했습니다. 19·20번의 추가 기능은 요구사항이며 현재 목업에는 아직 구현하지 않았습니다.
