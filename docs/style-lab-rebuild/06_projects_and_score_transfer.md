# 프로젝트와 점수만 이어받기

## 프로젝트 경계

예: Anima·인물 중심, Anima·배경이 있는 장면, 다른 모델·같은 소재를 별도 프로젝트로 둡니다. 프로젝트는 탐색의 단위이고 평가 조건 변경은 `EvaluationRevision`으로 구분합니다.

| 범위 | 소유 정보 |
| --- | --- |
| 공유 Catalog | 작가 Identifier, LoRA 파일 Identity, 등록 Workflow. 프로젝트 성적은 소유하지 않음 |
| Project | 이름·목적, 후보 Catalog, 탐색 규칙, 보관 결과, Archive 상태 |
| Evaluation Revision | Workflow/모델, Prompt·Negative·Seed·해상도·Sampling 조건의 불변 Snapshot |
| 프로젝트 내 평가 | 후보·생성물·Vote·순위·세대·성분 점수·LoRA 안정성 |

같은 LoRA를 두 프로젝트에서 써도 한쪽 Vote가 다른 쪽 점수를 변경하면 안 됩니다.

## 초기화 Mode

### A. `fresh`

Catalog 선택과 필요한 생성 조건은 복사할 수 있지만 후보0, Vote0, Generation1, 성분 점수0, 사용·승패0으로 시작합니다. 프로젝트 생성만으로 이미지를 자동 생성하지 않습니다.

### B. `component_scores_only`

- 작가·LoRA 성분 점수 Snapshot만 가져옵니다.
- 기존 조합 Elo, 이미지, Vote, 사용·승패, 세대, 진행 중 Selection/Job은 복사하지 않습니다.
- 원본 Project/Evaluation, 시각, 알고리즘 Version, 근거 수, 모델·Workflow 정보를 출처로 남깁니다.
- 가져온 점수와 새 프로젝트에서 검증한 점수를 구분합니다. 초기 표시는 '가져온 점수, 새 관측0'입니다.
- 원본 프로젝트가 나중에 변경돼도 복사한 점수는 바뀌지 않습니다. 실시간 참조가 아닌 불변 Snapshot입니다.

기존 이미지·후보까지 가져오는 Branch는 별도 Mode입니다. 점수만 복제하는 Mode에 섞지 않습니다.

## 점수 영속화 계약

기존 점수는 조합을 없애면 재계산할 근거를 잃으므로 `ComponentPrior`를 따로 저장합니다.

```json
{
  "component_identifier": "artist:rurudo",
  "initial_score": 120,
  "source_evidence_count": 18,
  "new_project_observation_count": 0,
  "source_project_identifier": "source-example",
  "source_evaluation_revision_identifier": "source-evaluation-example",
  "source_score_algorithm": "legacy-ridge-2.0-sweeps60",
  "transfer_strength": 1.0
}
```

수치는 예시입니다. 실제 값은13번 문서입니다. 원본 근거 수를 새 프로젝트 승수·비교 횟수로 더하면 안 됩니다. 원본 점수는 그대로 저장하고 감쇠 값은 별도 Field로 둡니다.

### Prior를 포함한 추정 제안

```text
beta0_i = transfer_strength * snapshot_score_i
objective = sum((centered_combo_elo_j - sum(weight_ji*beta_i))^2)
            + prior_strength * sum((beta_i-beta0_i)^2)
```

관측0이면 `beta=beta0`입니다. 점수를 가져온 뒤 조합이 없다는 이유로 다시0으로 만들지 않습니다. Fresh는 `beta0=0`, Prior Strength2.0, 60 Sweeps로 기존 산식에 맞춥니다. Coordinate Descent의 분자에 Prior 항을 포함하고 초기값도 `beta0`를 사용합니다.

`initial_score`, 새 관측으로 추정한 `estimated_score`, 후보 추출에 쓰는 `proposal_weight`를 구분합니다. 추출 확률을 정규화해도 저장된 원본 점수를 덮어쓰지 않습니다. 평균 기준·반올림·연산 순서는 Golden Fixture로 고정합니다.

## 다른 모델로 이전

모델·Prompt가 바뀌면 같은 점수의 의미도 달라집니다. 점수 이전은 호환성이나 품질을 증명하지 않습니다.

- 같은 조건은 Strength1을 초기값으로 쓸 수 있습니다.
- Prompt/모델이 다르면 차이를 표시하고0~1 감쇠를 명시 선택합니다.
- 새 모델에 맞지 않는 LoRA는 점수 기록을 남겨도 새 후보 추출에서 제외합니다.
- 작가 태그 미지원 모델은 Anima 문법으로 임의 변환하지 않습니다.
- 선택한 Catalog의 일부 점수만 가져올 수 있습니다. 누락·미지원 성분은 목록으로 보고합니다.

## 평가 조건 변경

이름·Memo·화면 필터는 평가 Revision을 바꾸지 않습니다. 모델·Workflow·Prompt·Negative·Seed 정책·크기·Sampler·입력 이미지·주요 후처리를 바꾸면 새 Evaluation Revision을 만듭니다.

이전 순위를 보존하고 새 Revision을 Fresh, 점수만 이전, 또는 **현재 조합의 Prompt 재시험**으로 시작합니다. 재시험은 상위 N개 성분·Weight를 그대로 복제해 새 Prompt로 생성하고, 독립 Elo로 비교·Drop합니다. 채택 전에는 활성 평가 구간을 바꾸지 않습니다. 채택해도 세대 번호가 증가하지 않으며 출발 세대와 Prompt 시험 구간을 함께 표시합니다. 상세 조건은 [17번 문서](17_prompt_retests_and_reranking.md)를 따릅니다.

다른 Revision 이미지의 비교가 필요하면 명시적 검증으로 분리해 일반 순위에 섞지 않습니다. 원본 Elo는 새 Prompt의 초기 후보 Elo로 자동 이전하지 않습니다.

## 다수 결과 확보

프로젝트마다 여러 `SavedStyle`을 저장합니다. 구조화된 성분, Workflow/Evaluation, 대표 이미지, 점수·세대·Seed 검증 결과, 이름·Memo를 저장 시점의 불변 Snapshot으로 보관합니다. 가변 Candidate ID만 참조하면 후보 수정·삭제 때 결과도 바뀌므로 충분하지 않습니다.

불변 Snapshot은 내용이 바뀌지 않는다는 의미이며 삭제 불가라는 의미는 아닙니다. [세대 되돌리기](15_generation_restore_and_deletion.md)를 실행하면 선택 시점 이후에 추가한 SavedStyle·북마크도 삭제 범위에 포함합니다. 다른 프로젝트의 독립 결과는 영향을 받지 않습니다.
