# Prompt별 Seed 입력·랜덤·변경 확정

2026-11-17. 프로젝트 설정의 각 Positive Prompt 아래에 `Seed 입력 → 랜덤 → 변경 확정`을 한 행으로 배치합니다.

## 저장 동작

- 직접 입력과 랜덤 버튼은 해당 Prompt의 Seed 입력 초안만 바꿉니다. 프로젝트 설정 저장을 누르더라도 아직 확정하지 않은 Seed는 적용하지 않습니다.
- 저장된 Prompt의 **변경 확정**은 그 Seed만 즉시 서버에 저장합니다. 다른 Prompt·메모·LoRA/작가 범위 등 미저장 초안은 보존합니다. Seed 입력 중 Enter도 같은 확정 동작입니다.
- 프로젝트를 아직 만들지 않았거나 새 Prompt를 추가하는 중이면 확정한 Seed를 프로젝트 초안에 넣습니다. 프로젝트 설정을 저장할 때 해당 Prompt와 함께 영속화합니다.
- 입력값과 응답 유실 시 재시도할 Operation ID는 탭의 Session Storage에 유지합니다. 다른 프로젝트·Prompt의 입력과 섞이지 않습니다.
- Seed 확정은 이미지를 생성하지 않습니다. 준비·진행 중인 진화는 기존 설정 저장 정책처럼 확정·취소한 뒤 변경합니다.

범위는 0~18446744073709551615의 정수입니다. **0도 고정 Seed**이며 랜덤 표시가 아닙니다. 랜덤 버튼은 Web Crypto로 새 64bit 정수를 입력하고, 생성마다 자동으로 바꾸지 않습니다. JavaScript 정밀도 밖의 값은 십진 문자열로 전달합니다.

기존 프로젝트 공통 Seed는 **기본 Seed**로 이름을 바꿉니다. 개별 Seed가 없는 Prompt는 이 값을 사용합니다. 기본값을 편집하면 미지정 Prompt의 표시도 함께 바뀌며, 이미 개별 지정한 Prompt는 유지합니다.

## 생성·이력·Fork

같은 Prompt에서는 모든 조합이 같은 확정 Seed를 사용합니다. Prompt마다 다른 Seed를 지정할 수 있으며, Wildcard·Tag 전개와 실제 Sampler Graph·Metadata·RenderPlan에 해당 값을 기록합니다. CHS Job의 공통 입력 구조는 유지하고 요청별 확정 조건은 기존 RenderPlan·Request Result에 저장합니다.

자녀 생성도 Prompt별 Seed를 유지합니다. 서로 다른 Seed를 쓰는 결과 묶음은 그림체·선별의 조건 목록에 `Prompt별 Seed`로 표시해 공통 Seed 하나로 오인하지 않게 합니다.

Seed 확정은 기존 공통 Seed 변경과 같은 방식으로 새 Evaluation Revision을 만듭니다. 기존 이미지·Elo·Vote는 원래 평가 구간에 보존하고 새 조건의 점수와 섞지 않습니다. 이전에 준비한 생성 계획은 Revision 검사로 거부하며, 기존 실패 계획의 재시도는 당시 고정된 Seed를 사용합니다.

프로젝트 설정 저장·Seed 개별 확정 때 현재 세대의 설정 Snapshot도 같은 Transaction에서 갱신합니다. Fork 시 Prompt별 Seed도 설정과 함께 복사합니다. 과거 계획·설정·Snapshot에 개별 Seed가 없으면 당시 공통 Seed를 사용합니다. 개별 Seed가 없던 프로젝트를 일반 저장하는 것만으로 새 평가 조건을 만들지 않습니다.

## API와 검증

`PromptCase.seed`는 선택적인 정수이며, 생략/`null`이면 프로젝트 기본값을 사용합니다. 기존 JSON 설정을 확장하며 Schema 21의 테이블 구조는 바꾸지 않습니다.

`PUT /api/style-projects/{project_id}/prompt-cases/{case_id}/seed`는 `seed`, `expectedRevision`, `operationIdentifier`를 받습니다. 서버에 저장된 해당 프로젝트의 Prompt만 수정하고 기존 프로젝트 검증·설정 저장·Snapshot·멱등 처리를 재사용합니다. 다른 설정 필드를 함께 넣으면 거부합니다. Home 인증을 공유하고 없는 소유 대상은 404, 오래된 Revision은 409로 처리합니다.

`tests/test_style_prompt_seeds.py`는 개별 저장·정수 범위·0/최대값·Graph/Metadata·실패 재시도·재생성·자녀 생성·옛 계획 호환·Fork·Snapshot Rollback을 검증합니다. `tests/browser_style_prompt_seeds.cjs`는 320·390·768·1280px 화면에서 확정 전 미적용·초안 보존·응답 유실 재시도·Enter·신규 Prompt와 서버 영속화를 확인합니다.

2026-11-17 검증: 전체 Python 테스트 589 Passed·1 Skipped, 네 화면 폭의 Browser 검증과 변경 JavaScript Syntax·Diff 검사를 통과했습니다. Seed 저장만으로 생성·투표 요청이 발생하지 않음을 확인했습니다.
