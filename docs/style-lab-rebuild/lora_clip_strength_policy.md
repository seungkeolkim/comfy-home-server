# 스타일 탐색의 CLIP 1 고정

2026-11-17. 사용자 재확인에 따라 스타일 구성에서 생성하는 LoRA는 **CLIP 1을 고정하고 STR만 조절**합니다. 기존 문서의 CLIP·STR 연동 설명보다 이 정책을 우선합니다.

## 적용

- 초기 Random, Mutate·Crossover·Random 자녀, 수동 생성 계획, 기존 조합의 새 Prompt 생성 모두 새 후보에 `clip_strength: 1.0`을 명시합니다. 작가 태그에는 CLIP 필드를 추가하지 않습니다.
- 프로젝트 범위와 0.05 배수 STR 규칙, 성분 선호도 보정, 사용 개수·제외 정책은 그대로 유지합니다. 부모 원본은 수정하지 않습니다.
- 실제 제출 직전과 CHS LoRA 조합 등록은 `style_lora_strength_policy.py`의 같은 변환을 사용합니다. STR 0.6은 `strength: 0.6`, `clipStrength: 1.0`으로 전달됩니다. 생략·0·다른 CLIP을 가진 과거 입력도 앞으로 생성하거나 새로 등록할 때는 CLIP 1입니다.
- 실패한 과거 계획을 다시 제출해도 앞으로 생성하는 이미지의 CLIP은 1입니다. 이미 생성한 이미지·기존 Candidate/Plan Snapshot·Elo·승패·투표는 소급 수정하지 않습니다. 과거 값과 다른 조건의 이미지를 같은 점수로 비교할 때는 별도 평가가 필요합니다.
- 새 CHS 등록은 원본 LoRA 파일명·STR을 사용하고 CLIP 1을 저장합니다. 이미 등록한 preset을 같은 등록 명령으로 다시 요청하면 기존 독립 Snapshot과 사용자 편집을 유지합니다. 등록 해제 뒤 새로 등록하면 새 CLIP 정책을 적용합니다.
- 일반 생성의 직접 LoRA 설정·수동 preset·공통 `prepare_anima` Adapter는 기존 독립 CLIP 기능을 유지합니다. 스타일에서 새로 등록한 preset은 일반 생성에서도 저장한 CLIP 1을 전달합니다.

## 기록과 구현

- Random 정책은 `initial-random-v3`, 진화 정책은 `style-evolution-v4`입니다. 모든 새 Plan의 Selection에 `loraStrengthPolicy: style-lora-fixed-clip-v1`, `loraClipStrength: 1.0`을 기록합니다.
- 중복 검사는 과거 Snapshot을 다시 쓰지 않습니다. 과거 CLIP 생략은 당시 의미인 STR 연동으로 해석하고, 새 후보는 명시적인 CLIP 1로 비교합니다.
- DB Schema 변경이나 데이터 Migration은 없습니다. 기존 CHS 등록본도 일괄 변경하지 않습니다.

## 검증 범위

- CLIP 생략·0·0.6·1 입력별로 Plan·실제 제출 Workflow·요청 Metadata·등록본·일반 생성 Workflow를 확인합니다.
- 진화 세 Mode의 CLIP 1과 0.05 STR, 부모 원본 보존, 새 Prompt 재생성·실패 재시도, 과거 Snapshot 등록 시 원본 보존을 확인합니다.
- 일반 생성의 독립 CLIP 0·다른 값 보존은 기존 Workflow·LoRA preset 테스트로 검증합니다.
- 관련 Python 테스트 **105 Passed**. 격리 Browser에서도 320·390·768·1280px에서 등록·해제·모아보기·일반 생성 적용·원본 이동을 통과했고 Browser 오류는 0건입니다.
