# 구현 순서와 결정 기록

## 확정 요구

- Comfy Home Server 내부에 Style Lab의 핵심 탐색 기능을 구현합니다. 설계·요구사항·진행 상태는 이 저장소의 `docs/style-lab-rebuild/`에서 관리합니다.
- 생성은 Comfy Home Server 등록 Workflow를 기준으로 합니다.
- 프로젝트별 Prompt/모델 탐색을 격리하고 여러 그림체를 확보합니다.
- Fresh 또는 작가·LoRA 점수만 유지한 새 탐색을 지원합니다.
- Anima 외 Moss 등 모델 추가를 고려합니다.
- 선택한 확정 세대로 돌아가며, 확인창 하나에서 이후 이미지·이력·승패·Elo 변경의 삭제를 경고합니다.
- 수동 조합·다듬기는 후순위입니다. 융합은 유지하며 다른 기능을 만든 뒤 비율 지정·3개 이상 원본을 지원하는 새 UI부터 확인합니다.
- Interactive Evolution을 유지하고 여러 계보의 부모 기회를 보강합니다.
- 현재 상위 N개 조합을 성분·Weight 변경 없이 새 Prompt로 시험하고 시험 Elo·Drop·채택을 지원합니다. 시험만으로 세대를 올리지 않습니다.
- 성분·Weight 일부 잠금, 독립 프로젝트 분기, Ablation, 대표 Prompt·Seed 검증, 비교 후보 추천을 모두 채택합니다. [19번 문서](19_adopted_exploration_tools.md)를 구현 계약으로 사용합니다.
- 2026-11-10부터 UX 기준은 localhost:8389의 Style Lab Web·Mobile입니다. [20번 문서](20_web_ux_fusion_multi_prompt_and_component_differences.md)의 여러 Prompt 일상 탐색과 성분 차이·향후 생성 제외를 초기 설계에 반영합니다. 투표/집계·융합 산식·구체 UI는 사용자와 확인할 설계 후보입니다.

## 권장 구현 순서

실제 진행은 [development_process.md](development_process.md)의 한 단계 구현·직접 사용 확인을 따릅니다. STYLE-023/024의 아래 배치는 초기 설계·비교 단계 반영을 위한 제안이며, 미정 정책은 0단계와 해당 기능 검토에서 확정합니다.

| Ticket | 단계 | 완료 조건 |
| --- | --- | --- |
| STYLE-001 | P0: 순수 알고리즘 분리 | 기존 순위·Selection·진화 Golden Fixture 통과 |
| STYLE-002 | P0: Project/Evaluation 저장 | Project 격리, 불변 조건·Prompt/Workflow Snapshot |
| STYLE-003 | P0: 점수 Prior | Fresh/점수만 복제, 출처·관측 수·불변성 검증 |
| STYLE-004 | P0: Workflow Registry 공통화 | Home 일반 생성과 Style 경로가 같은 Adapter 사용 |
| STYLE-005 | P0: 고정 RenderPlan | Sampling Seed·Prompt 전개 고정, 새 모델별 Capabilities |
| STYLE-006 | P0: 초기 후보와 투표 | A/B·Skip·Undo·Blind·멀티탭 Idempotency |
| STYLE-023 | 초기 설계·비교 단계: 여러 Prompt 일상 탐색 | Prompt Set·Case별 Render, 결과 묶음 UI, 장수·부분 실패, 투표/집계 정책 사용자 확인 후 진화 연결 |
| STYLE-024 | 초기 비교 단계: 성분 차이·탐색 제외 | 작가/LoRA/독립 Strength 차이, Blind 보호, 프로젝트 향후 생성 제외·재허용, 세 방식 상속·잠금 검증 |
| STYLE-019 | P0: 성분·Weight 잠금 | 프로젝트/계보 정책, 고정 축·Hash·순서, 세 생성 방식 공통 검증·충돌 거부 |
| STYLE-007 | P0: 진화 | 부모 Snapshot·후보 생성·확정·퇴역·취소 |
| STYLE-017 | P0: 여러 계보 보존 | 기존 1:1:1 탐색 유지, 계보 대표 부모 기회·배정 Preview·정책 Version |
| STYLE-018 | P0: 현재 조합 Prompt 재시험 | 상위 N개 고정·고정 RenderPlan·독립 Elo·Drop 취소·채택·원본 보존 |
| STYLE-016 | P0: 특정 세대 복원 | 확정 Checkpoint, 삭제 영향 Preview·경고창 하나, 이후 이미지·이력 삭제, 당시 통계 복원 |
| STYLE-020 | P0: 탐색 분기 | 현재 안정 상태/확정 세대의 새 Project Snapshot, 독립 ID·점수·Asset·Undo 경계 |
| STYLE-008 | P0: 그림체 보관 | 프로젝트별 복수 SavedStyle, 설정·이미지 참조 보존 |
| STYLE-009 | P0: LoRA 진단 | 예상 TE 미적용과 실제 문제 분리, 모바일 반복 방지 |
| STYLE-010 | P1: Legacy Import | 원본 비변경, Dry-run, 3가지 Mode, 중복 Import 방지 |
| STYLE-021 | P1: Ablation | 고정 Baseline·단일 성분/강도 Delta, 장수 Preview, 원본 비변경·새 후보 채택 |
| STYLE-011 | P1: 대표 Prompt·Seed 검증 세트 | 기존 Seed 검증 확장, Suite Version·Case별 결과·생성 장수·평가 격리 |
| STYLE-022 | P1: 비교 후보 추천 | 필수 대결 유지 후 규칙 기반 추천, 근거·Version·최근 Pair·Skip·Blind 검증 |
| STYLE-012 | P1: 내보내기·재현 | Project Bundle, Import 미리보기, 실제 Workflow Metadata |
| STYLE-013 | P1: 모델 추가 | 실제 Moss Workflow 등록 후 Adapter 검증; 이름만 등록하지 않음 |
| STYLE-014 | P2·다른 기능 이후: 수동 조합/비율 융합 | 2개 및 3개 이상 원본, 비율 UI·합성식 확인, 성분 Preview·출처·새 후보 채택 |
| STYLE-015 | P2: Tune/Improve | 두 상태 머신을 구분해 복원 |

STYLE-013의 설계 기반은 P0부터 필요하지만, 실제 Moss 지원 완료는 해당 Workflow와 모델의 계약을 확인한 뒤 판단합니다. 임의로 다른 모델의 Node ID를 재사용하지 않습니다.

## MVP 완료의 의미

프로젝트를 만들고, 등록 Workflow에서 후보를 생성하고, 선별·진화를 반복해 복수 그림체를 저장하며, 같은 프로젝트가 재시작 후에도 이어집니다. 다른 프로젝트의 점수나 이미지를 섞지 않습니다. 후순위 기능이 없어도 이 흐름이 완결되면 MVP로 봅니다.

세대 확정부터 Checkpoint를 저장하고, [특정 세대 복원](15_generation_restore_and_deletion.md)도 MVP에 포함합니다. 나중에 기능을 붙이면서 과거 Snapshot을 추측하는 방식으로 구현하지 않습니다.

[계보 보존](16_search_strategy_and_diversity.md)과 [Prompt 재시험](17_prompt_retests_and_reranking.md)도 MVP에 포함합니다. STYLE-018은 STYLE-002/005/006의 평가 범위·RenderPlan·투표 계약을 재사용하고 세대 복원과 함께 검증합니다. 추가 Seed 검증은 P1을 유지합니다.

성분·Weight 잠금과 독립 분기도 MVP에 포함합니다. 잠금은 후보 생성·진화 전에 공통 제약을 준비하고, 분기는 세대 복원과 같은 Snapshot·Asset 참조 기반을 재사용합니다. P1은 Ablation → STYLE-011의 대표 Prompt·Seed 검증 확장 → 규칙 기반 비교 추천 순으로 구현합니다. 고급 Pairwise Preference Learning은 효과를 측정한 뒤 검토하며 즉시 필수 의존성을 추가하지 않습니다.

추가 요구의 여러 Prompt 탐색은 최종 검증만으로 대체하지 않습니다. 진화 반복 실사용 전 다중 결과 비교와 선택 정책을 확인하며, 단일 Prompt의 중간 구현 상태와 확장 완료를 구분합니다. 성분 차이·제외는 기본 비교 UX에서 검토합니다. 상세 범위·수락 기준은 20번을 따릅니다.

## 미확정 사항과 권장 기본값

| 사항 | 상태·권장값 |
| --- | --- |
| 구현 방식·문서 관리 위치 | 2026-11-09 확정. Comfy Home Server 내장, 저장소 내부 문서만 갱신 |
| Moss 정확한 모델·Workflow | 미확정. 등록 Adapter 전까지 지원 예정 상태 |
| 점수 이전 Strength | UI에서 지정. 같은 조건은 1, 다른 조건은 차이를 보이고 명시 선택 |
| 지원 출력 매체 | MVP 이미지. 다른 매체는 실제 모델 요구 확인 후 Renderer 확장 |
| LoRA 점수 기반 추출 | 기존은 작가와 차이 있음. 새 설계는 양쪽 지원을 제안하고 정책 Version 기록 |
| 평가 조건 변경 | 새 Revision 사용. Fresh/점수 이전/현재 조합 Prompt 재시험을 구분 |
| 동시 생성 수 | Home Queue 정책 재사용. Project마다 무제한 독립 Worker 생성 금지 |
| 점수 Snapshot의 기본 범위 | 선택한 Project/Evaluation 단위. 모든 Project의 합산은 명시적 선택 |
| 여러 Prompt 투표·부모 선택 | 미정. 묶음 한 번 투표를 첫 화면안으로 제안, Case별 투표·종합과 비교 후 확인 |
| 성분 차이에서 제외 | 현재 프로젝트의 향후 새 후보에 적용하는 안. 기존 후보 보존·부모 적격·잠금 충돌 UI 확인 |
| 다중 원본 비율 융합 | 구현 범위 유지·후순위. 합성식·재분배·성분 순서·범위·UI는 구현 차례에 확인 |

## 구현자가 하지 말아야 할 단순화

- `project_id`만 붙이고 전역 점수·Generation·Undo Stack을 공유하기.
- Registry만 복사하면 기존 작가 점수가 살아 있다고 가정하기.
- 모든 Match를 일반 Elo나 0.5점 무승부로 바꾸기.
- Home의 일반 Batch API가 이미 고정Seed를 보장한다고 가정하기.
- Workflow JSON을 별도 복제해 서로 다른 Adapter로 관리하기.
- Anima의 작가/NegPip 문법을 Moss에도 자동 적용하기.
- 기존 Image Saver와 Metadata 동작을 버리고 이미지 파일만 저장하기.
- Model Only에서 생긴 TE 미사용 Key를 다시 'LoRA 전체 실패'로 표시하기.
- Prompt 재시험에 기존 Evolution 생성 함수를 호출해 조합·Weight·세대를 바꾸기.
- 옛 Prompt의 Elo를 새 Prompt 평가에 자동 합산하거나 Drop을 패배로 기록하기.
- 잠금을 표시만 하고 Random/Crossover가 무시하게 하거나 고정 강도를 자동 Clamp하기.
- 분기 원본과 Candidate·Vote·가변 Snapshot을 공유하거나 원본 Undo Token을 복제하기.
- Ablation·검증 결과를 원본 Elo에 자동 합산하거나 서로 다른 Case·Seed를 한 Pair에 넣기.
- 비교 추천이 필수 Placement/Selection을 건너뛰거나 Blind에서 점수·예상 승자를 노출하기.
- 다중 Prompt 탐색을 최종 검증으로만 대체하거나 한 표를 이미지 수만큼 중복 가산하기.
- 차이 표를 원인 확정으로 표현하거나 성분 제외가 Mutate/Crossover 상속에서 무시되게 하기.
- 융합을 2개 원본으로 제한하거나 미확정 합성식으로 기존 Weight를 몰래 Clamp하기.

## 다음 작업 시작용 요청 예시

> development_process.md에서 사용자 확인을 마친 다음 한 단계만 진행한다. UX는 localhost:8389의 Style Lab Web·Mobile을 기준으로 보고 20번의 추가 요구를 반영한다. 해당 단계의 화면·사용 흐름을 검증해 직접 확인할 수 있게 전달하고, 다음 단계는 사용자 요청을 기다린다. 미정인 다중 Prompt 투표/집계·융합 산식을 임의 확정하지 않는다.
