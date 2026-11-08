# 채택한 탐색 보조 기능 다섯 가지

2026-11-09 사용자 채택으로 확정한 요구사항입니다. 아래 기능은 Comfy Home Server 내장 구현 범위에 포함하며, 현재 구현된 기능으로 해석하지 않습니다. 기존 Interactive Evolution과 별도 일반 생성 공간을 유지합니다.

| 기능 | 구현 단계 | 기본 진입점 |
| --- | --- | --- |
| 작가·LoRA·Weight 일부 잠금 | P0 | 조합 상세·프로젝트 탐색 설정 |
| 현재 상태 또는 확정 세대에서 탐색 분기 | P0 | 프로젝트 홈·세대 이력 |
| 성분별 영향 확인, Ablation | P1 | 조합 상세의 `영향 확인` |
| 대표 Prompt·Seed 검증 세트 | P1 | 최종 후보·보관한 스타일 |
| 지금 비교하면 좋은 후보 추천 | P1 규칙 기반, 고급 선호 모델은 후속 실험 | 이미지 비교의 후보 선정 |

잠금과 분기를 먼저 만들고 Ablation·검증 세트·비교 추천을 연결합니다. 후순위는 구현 순서를 뜻하며 선택 기능으로 되돌리는 의미가 아닙니다. 수동 조합·융합·Tune/Improve의 기존 P2 순위는 유지합니다.

## 1. 작가·LoRA·Weight 일부 잠금

예: `LoRA A의 Model Strength 0.7, CLIP Strength 0을 고정하고 나머지 작가만 탐색`합니다. 성분을 유지하는 것과 강도를 고정하는 것을 구분합니다.

| 잠금 | 보장 |
| --- | --- |
| 성분 유지 | 작가 Identifier 또는 LoRA Identity·Hash가 모든 해당 자녀에 포함됨. Weight는 허용 범위 내 탐색 가능 |
| Weight 고정 | 성분 유지에 더해 Artist Weight 또는 LoRA Model/CLIP Strength의 선택한 축을 고정 |
| 적용 범위 | 프로젝트 공통 규칙 또는 특정 계보 규칙. 두 범위의 제약을 모두 충족 |

프로젝트 공통 잠금을 계보 규칙이 몰래 해제하거나 바꾸지 않습니다. 충돌하는 값·성분 사용 해제·개수 제한·호환성·범위 문제는 생성 전에 대상과 이유를 보여주고 해결하게 합니다. 고정값을 Registry 범위로 자동 Clamp하거나 잠금을 무시해 생성하지 않습니다. 파일 이름만 같고 Hash가 다른 LoRA도 대체 성분으로 취급하지 않습니다.

Mutate/Crossover/Random 모두 생성 계획에 고정된 Lock Policy를 적용합니다. Crossover는 자녀의 소속 계보를 먼저 정해 그 계보의 제약을 적용합니다. 잠긴 성분이 이미 부모에 있어도 중복 삽입하지 않고, 순서와 독립 Strength를 유지합니다. 고정 부분 외 성분만 개수·Weight 규칙에 따라 탐색합니다.

잠금을 바꿔도 기존 Candidate·Render·Elo를 수정하지 않습니다. 앞으로 만들 후보에 적용할 정책 Revision을 기록합니다. 기존 조합이 새 규칙을 위반하면 표시하고, 다음 부모·자녀 계획에서 적격 여부를 명시합니다. Prompt 재시험은 원본 성분을 그대로 재현하므로 최신 잠금을 소급 적용하지 않습니다.

모든 성분이 잠겨 중복 없는 후보를 목표 수만큼 만들 수 없으면 부족 수량을 표시합니다. 시도 상한을 두고 무한 재시도하거나 임의로 잠금을 풀지 않습니다.

Desktop은 조합 상세와 탐색 설정에서 각 성분 옆의 `성분 유지`·`강도 고정`을 제공합니다. Mobile은 성분 상세 Sheet에서 범위와 축을 선택합니다. 다음 세대 Preview에 잠금 목록과 적용 계보를 표시합니다.

수락 기준: 세 생성 방식에서 고정값·Model/CLIP 0·Hash·순서 보존, 충돌 사전 거부, 현재 후보 불변, 정책 Revision 기록, 모든 성분 잠금 시 유한 종료와 부족 수량 표시.

## 2. 현재 상태 또는 확정 세대에서 탐색 분기

예: 12세대의 탐색을 `수채화 방향`과 `선화 방향`으로 나눕니다. 분기는 **새 Project**이며 원본·분기와 각 분기 사이의 평가·진화·복원·삭제는 독립적입니다. 세대 복원처럼 원본의 이후 데이터를 지우지 않습니다.

새 초기화 Mode는 `branch_snapshot`입니다. Fresh 및 성분 점수만 이전과 구분합니다. 원본의 안정된 현재 상태 또는 실제 확정 Checkpoint를 선택합니다. 관련 생성·투표·복원 작업이 진행 중이면 기본 409로 거부하고 완료 또는 취소를 안내합니다. Checkpoint가 없는 과거 상태를 추측해 만들지 않습니다.

복제 항목은 평가 조건·Workflow Snapshot, 활성/퇴역 조합, 당시 Elo·승패·경기 수, 성분 Prior·통계, 계보·대표·잠금, 보관 결과·이미지 참조입니다. 원본의 현재 세대 번호 N을 출발 번호로 유지하며 다음 실제 진화는 N+1입니다. 새로운 Project/Evaluation/Generation/Candidate/Render ID를 발급하고 출처 대응표를 남깁니다. 새 대결의 Match ID도 분기에서 새로 발급하며 원본의 진행 중 Pair는 가져오지 않습니다.

기존 Vote는 새 Vote로 재생하지 않습니다. 원본 평가 근거는 읽기 전용 출처 Snapshot으로 보존하고 Elo·승패의 가져온 기준값과 분기 후 새 관측을 구분합니다. 원본 Vote·Undo Token·진행 중 Job·현재 Pair·다른 탭 Session은 복제하지 않습니다. 분기에서 Undo할 수 있는 범위는 분기 후 발생한 Vote입니다.

분기는 원본과 **동일한 평가 조건**에서 점수를 이어받습니다. 생성 창에서 Prompt·모델·Workflow 등 조건을 함께 바꿔 옛 Elo까지 넘기지 않습니다. 다른 조건은 분기 후 Prompt 재시험 또는 새 Evaluation Revision으로 평가합니다. 탐색 정책·계보 방향 변경은 이후 자녀 계획에 기록합니다.

분기 시 그 상태의 초기 Checkpoint를 새로 만듭니다. 이전 세대의 이력 표시는 출처 참고 자료이며 모든 과거 세대를 분기 안에서 복원 가능하다고 표시하지 않습니다. 이미지 Byte는 공유할 수 있지만 소유 참조는 분리합니다. 참조 확보와 Snapshot 저장을 일관되게 처리하고, 원본의 복원·삭제가 분기의 이미지·출처 Snapshot을 지우지 못하게 합니다. 분기가 참조하는 Asset이 남으면 물리 파일을 삭제하지 않습니다.

UI에는 `이 상태에서 새 프로젝트로 분기`와 `이 세대에서 분기`를 둡니다. 이름·출발 조건·가져올 수량·독립 데이터임을 확인합니다. 분기는 생성 자체를 제출하지 않으며 원본의 활성 프로젝트도 자동으로 덮어쓰지 않습니다.

수락 기준: 독립 ID와 N/N+1 번호, 원본 Vote·복원·삭제의 영향 격리, Snapshot 이후 변화 비전파, 분기 후 Vote만 Undo, 공유 Asset 보존, 진행 중 작업·오래된 Snapshot Token·중복 요청 검증.

## 3. 성분별 영향 확인, Ablation

선택한 조합의 Baseline과 `LoRA A 제외`, `작가 B 제외`, `특정 Weight만 변경`을 나란히 생성합니다. 모든 변형을 한 번에 조합하지 않고 한 변형당 한 성분 또는 한 Strength 축의 변경을 기본으로 합니다. 여러 축 변경은 명시적으로 별도 실험으로 표시합니다.

등록 Workflow·모델·공통 Prompt 내용·Sampling Seed·Steps·CFG·해상도·입력·후처리를 고정합니다. Wildcard는 공통으로 전개합니다. LoRA에 자동 부착한 Trigger처럼 성분에 종속된 입력의 변경도 Delta에 표시합니다. 같은 단어가 있다는 이유로 사용자가 직접 작성한 Prompt를 지우지 않습니다. 실제 Encode 입력과 PNG Metadata까지 차이를 추적합니다.

Baseline 재사용은 실제 RenderPlan·성분·파일 Hash가 일치하는 기존 Render를 사용자가 선택한 경우에만 허용합니다. 일치하지 않으면 Baseline도 생성하고 필요한 장수에 포함합니다. 같은 Seed가 Prompt나 Runtime 변경에도 동일 이미지를 보장한다고 표현하지 않습니다.

진단은 별도 `purpose=ablation` 평가 구간과 Experiment에 저장합니다. 일반 Elo·세대·성분 점수는 자동 변경하지 않습니다. 성분을 모두 제외한 Bare Model도 진단 Baseline으로는 허용할 수 있지만 일반 후보·부모가 되는 것은 아닙니다. 잠긴 성분을 이번 진단에서 빼려면 명시적으로 선택하며 원래 잠금 정책은 바뀌지 않습니다.

마음에 드는 변형은 `새 후보로 가져오기`로 적용합니다. 현재 조건과 잠금·호환성을 다시 확인하고 새로운 Candidate와 Elo 10000/전적0을 부여합니다. Baseline의 Elo를 그대로 물려주거나 원본 조합을 수정하지 않습니다. 성분이 전혀 없는 진단 결과는 일반 후보 제약을 통과하지 않으면 가져올 수 없습니다.

Desktop은 Baseline을 고정한 나란히 비교, Mobile은 `기준 / 변형` 전환과 선택 변형 비교를 제공합니다. 생성 전 변형 수×Seed 수, 재사용 수, 신규 생성 장수, 실행 가능한 항목을 보여줍니다. 실패한 변형만 재시도하고 제출 여부가 모호하면 Home Job/Comfy History부터 조회합니다.

수락 기준: 한 변형의 의도한 Delta만 변경, 공통 Seed·Prompt 전개, Baseline 재사용 조건·장수 계산, 원본 점수 불변, Trigger Delta와 잠금 예외 표시, 새 후보 채택 시 초기 점수와 제약 검사.

## 4. 대표 Prompt·Seed 검증 세트

기존 STYLE-011의 추가 Seed 검증을 확장합니다. `ValidationSuite`는 Version이 있는 Case 목록이며 각 Case에 이름·Positive/Negative Prompt·입력 참조를, Suite에 공통 Seed 목록과 공통 생성 조건을 둡니다. 같은 모델·Workflow와 성분을 고정하고 Case·Seed에 따른 결과를 봅니다. 다른 모델은 별도 평가 구간에서 검증합니다.

예: 인물 프로젝트의 `얼굴 확대 / 전신 / 역광`, 배경 프로젝트의 `낮 / 밤 / 실내`. 범용 점수가 아니라 프로젝트 목적에 맞는 안정성을 확인하는 도구입니다. 등록된 Case와 실제 전개 Prompt·Seed를 Run Snapshot으로 고정하며, Suite를 나중에 편집해도 과거 결과는 바뀌지 않습니다.

기본은 최종 후보 또는 보관한 스타일의 소수 선택이며 모든 후보를 자동 검증하지 않습니다. 생성 장수는 **선택 후보 수 × Case 수 × Seed 수**에서 정확히 일치해 재사용할 Render 수를 뺀 값입니다. 예: 후보3×Case3×Seed2는 재사용이 없으면18장입니다. 실행 전 장수·기존 Queue·부분 실패 처리 방식을 보여줍니다. 장수는 비용 계획이며 실행 시간·VRAM을 근거 없이 예측하지 않습니다.

결과는 후보별·Case별 Matrix로 보여주고 Mobile은 Case 선택 후 후보를 비교합니다. 성공/실패, Seed별 이미지, 사용자의 통과/보류 표시와 Memo를 기록합니다. 이미지 하나만 좋았다는 이유로 전 Case가 검증됐다고 표시하지 않습니다.

Case마다 별도 `purpose=validation` Evaluation을 만들고 후보는 새 ID로 성분을 복제합니다. Case 내부 선호 비교가 필요하면 Elo 10000/전적0에서 시작합니다. 여러 Seed를 쓰면 비교 Pair의 Case와 Seed를 일치시키고 Render 소속을 검사합니다. 원본 Elo나 다른 Case의 Elo를 합치거나 평균 내서 원래 순위로 사용하지 않습니다. 통과 표시와 비교 Elo도 구분합니다.

SavedStyle에는 원본을 바꾸지 않는 별도 검증 기록으로 Suite Version·Run·Case별 결과를 연결합니다. 새 조건에서 계속 탐색하려면 별도 재시험 또는 Evaluation을 명시적으로 채택합니다.

수락 기준: Suite Version 불변, 생성 장수와 재사용 계산, Case/Seed별 공통 전개와 비교 격리, 부분 실패와 재시도, 단일 후보의 생성·수동 검증, 원본 Elo·SavedStyle 성분 불변.

## 5. 지금 비교하면 좋은 후보 추천

목표는 불필요한 반복을 줄이고 현재 판단에 필요한 비교를 먼저 보여주는 것입니다. Genetic Algorithm이나 Elo 산식을 바로 교체하지 않습니다.

기존 Placement·Evolution Selection·필수 동점 해소와 진행 중 Pair의 우선순위를 유지합니다. 규칙 기반 추천은 그 뒤의 일반 League/Top 대결 및 명시적으로 허용한 추가 비교에 적용합니다. 필수 대결을 추천 점수가 낮다는 이유로 생략하지 않습니다. 시험·검증에서는 해당 평가 구간의 비교 규칙과 적격 후보 안에서만 선정합니다.

초기 정책은 비교 횟수 부족, 상대 후보 분포의 편중, 순위 또는 부모 선정 경계의 근접성, 최근 Pair 반복, Skip 기록을 조합합니다. 서로 다른 계보의 적격 후보에도 관측 기회를 줍니다. Elo 차이만으로 실제 불확실성이나 통계적 신뢰구간을 산출했다고 표시하지 않습니다.

각 Pair에 `비교 근거 부족`, `순위 경계 확인` 같은 이유와 정책 Version을 저장합니다. Blind에서는 이름·점수·예상 승자를 숨기고 추천 이유도 선호를 유도하지 않는 중립적인 문구만 표시합니다. 후보가 적어 반복할 수밖에 없으면 이유를 안내합니다.

상세 가중치·Cooldown은 정책값으로 Version 관리하고 재현 가능한 Random Seed·후보 집합 Snapshot을 남깁니다. 같은 Pair와 평가 Revision을 기반으로 Vote Idempotency·Undo를 처리합니다. 추천은 Pair 선정만 하며 자동 Vote·점수 가산·Skip의 의미 변경을 수행하지 않습니다.

후속 단계에서 Pairwise Preference Learning을 실험할 수 있으나 MVP/P1에 BoTorch·GP를 필수 의존성으로 추가하지 않습니다. 이 고도화의 채택 여부는 고정된 생성·비교 예산에서 확보한 SavedStyle과 비교 피로를 기준으로 검증합니다. 개념 참고는 [BoTorch 공식 Pairwise Preference BO 예제](https://botorch.org/docs/tutorials/preference_bo)이며 이 프로그램의 성능을 증명하는 자료가 아닙니다.

수락 기준: 필수 대결 우선순위 유지, 최근 Pair·Skip 처리, 같은 조건의 후보만 비교, 근거와 Version 저장, Blind 정보 보호, 후보 부족 시 유한 종료, 기존 Vote·Undo·Golden Fixture와 별도 정책 Fixture 검증.

## 저장·동시성·복원 공통 계약

잠금 Policy, 분기 Snapshot, Ablation 계획, Validation Run에는 Source Project/Evaluation/Generation/Event Sequence, 조건·성분 Hash, Timeline·상태 Revision을 기록합니다. 생성·분기·채택·Vote는 Idempotency Key를 받고 오래된 상태는409로 거부합니다. 문법·범위·호환성 오류는422 등 명확한 검증 오류로 보고합니다.

진단·검증은 전용 Evaluation의 기존 Candidate/Render/Match/Vote 구조를 재사용하고 원본 ID는 출처로만 보관합니다. 실험별 테이블에 Elo를 이중 저장하지 않습니다. 해당 Run에 묶인 실제 조건·입력·결과만으로 평가 범위를 판별할 수 있어야 합니다.

원본 세대 복원은 해당 Timeline의 잠금·계보·정책과 종속 실험·검증 Run을 Checkpoint의 Event 경계로 복원·삭제합니다. 다른 프로젝트로 만든 분기와 독립 채택 Evaluation은 연쇄 삭제하지 않습니다. Case Evaluation이 여러 개여도 소유 Run에 종속되어 있다는 점을 기록하고, 독립 채택하기 전에는 원본 복원의 삭제 Preview에 포함합니다. 공유 Suite 정의 자체는 참조 Version을 보존하며 원본의 복원 때문에 전역 삭제하지 않습니다.

실행 중 Job·늦은 Callback·Cache·공유 Asset은 [15번 문서](15_generation_restore_and_deletion.md)의 복원 잠금·Timeline 검증·참조 보호·정리 실패 재시도 규칙을 적용합니다. DB 변경과 파일 정리가 한 번에 원자적이라고 가정하지 않습니다.

## UI 배치와 현재 목업의 범위

새 상위 메뉴를 다섯 개 추가하지 않습니다. 조합 상세의 잠금·영향 확인, 프로젝트 홈/세대 이력의 분기, 보관함/최종 후보의 검증, 비교 화면의 추천으로 배치합니다. Mobile은 같은 진입점에서 한 열 상세 또는 Sheet를 사용합니다.

[18번 화면 설계](18_workspace_navigation_and_screen_mockups.md)에 추가 진입점을 연결합니다. 현재 HTML 목업은 이 다섯 기능 채택 전의 기본 작업 공간·Prompt 재시험 흐름을 보여주며, 새 잠금·분기·Ablation·검증·추천 UI를 이미 구현한 것으로 취급하지 않습니다.
