# 특정 세대로 돌아가기와 이후 데이터 삭제

새 프로그램의 **P0 요구사항**입니다. 현재 Style Lab에 이미 구현된 기능은 아닙니다. 기존 '이번 세대 취소', 개별 Vote Undo, 점수 Reset과 구분합니다.

[20번 확장](20_web_ux_fusion_multi_prompt_and_component_differences.md)에 따라 Checkpoint에는 Prompt Set·Case·투표/집계 정책, 성분 제외 정책과 각 후보의 모든 Case Render 참조를 포함합니다. 삭제 Preview는 후보 수와 이미지 수를 구분하고 이후의 융합 출처·결과·Case별 생성물도 Event 경계대로 처리합니다. 독립 분기·채택 구간과 공유 Asset 보호 원칙은 유지합니다.

## 돌아갈 시점

기본 대상은 **선택한 세대가 확정된 직후의 Checkpoint**입니다. '5세대로 돌아가기'는 5세대 확정 당시 후보·점수·승패·부모 목록을 복원하는 의미입니다. 5세대 자체의 이미지와 결과는 유지하고 다음 생성은 6세대입니다.

- 확정되지 않은 세대는 대상으로 선택할 수 없습니다. 진행 중 세대 취소는 별도 기능입니다.
- 필요하면 최초 탐색 전의 '초기 상태·0세대' Checkpoint를 제공합니다.
- `project_id + evaluation_revision_id + checkpoint_id`로 식별합니다. 세대 번호만으로 식별하지 않습니다.
- 세대 목록은 평가 구간별로 구분합니다. 다른 프로젝트·평가 구간을 함께 삭제하지 않습니다.
- 과거 Import에 Checkpoint가 없으면 정확히 복원할 수 있다고 표시하지 않습니다.

## 경고창 하나로 확인

세대 이력에서 '이 세대로 돌아가기'를 누르면 삭제 영향을 계산한 뒤 **확인창 하나**를 띄웁니다. 범위가 바뀌지 않았다면 확인창을 중복해서 띄우지 않습니다.

### 문구

> **5세대로 돌아가시겠습니까?**
>
> 5세대 확정 시점 이후에 생성된 세대의 이미지와 이력, 승패 기록, Elo 변경 사항은 모두 삭제되고, 선택한 세대 당시의 상태로 돌아갑니다.
>
> 이후에 보관하거나 북마크한 그림체도 삭제 대상에 포함됩니다. 삭제된 데이터는 이 기능으로 되돌릴 수 없습니다.
>
> 삭제 예정: 세대 7개 · 이미지 84장 · 비교 이력 320개

버튼: `취소` / **`이후 데이터 삭제 후 5세대로 돌아가기`**.

숫자는 실제 Preview에서 계산하며 위 수치는 예시입니다. 프로젝트 이름·평가 조건·목표 세대를 함께 표시합니다. 취소 시 변경은 없고 실행 중에는 버튼을 비활성화합니다. 다른 탭에서 변경돼 Preview가 오래됐으면 삭제하지 않고 새 영향을 보여준 뒤 다시 확인받습니다.

## 삭제·복원 범위

단순히 `generation > 5`인 후보를 삭제하면 안 됩니다. 1세대 후보도 5세대 이후 Vote로 Elo·승패가 바뀌었을 수 있으므로 **Checkpoint 이후 변경 전체**를 되돌립니다.

| 대상 | 처리 |
| --- | --- |
| 선택 시점의 활성·퇴역 후보와 이미지 | 당시 상태와 참조를 복원 |
| 이후 세대·후보·변형·추가 Render | 해당 평가 구간에서 삭제 |
| 이후 이미지·Thumbnail·Preview Cache | 삭제 대상 참조 제거, 미참조 파일 삭제 |
| 이후 Vote·Skip·비교·다듬기 이력 | Checkpoint의 Event Sequence 이후 삭제 |
| 기존 후보의 이후 승패·경기 수·Elo | 0이 아니라 당시 값으로 복원 |
| 작가·LoRA 통계·점수·Usage | 당시 Registry 통계·Prior·후보를 기준으로 복원·재계산 |
| 부모·고정 점수·세대·LoRA 안정성 기록 | 당시 값 복원, 이후 기록 삭제 |
| 이후 북마크·SavedStyle·Memo 변경 | 당시 상태 복원, 이후 신규 보관 결과 삭제 |
| 현재 Match·Undo Stack·이전 응답 | 폐기하고 Timeline Revision 갱신 |
| 이후 Checkpoint | 삭제. 지운 미래 상태로 다시 갈 수 없게 함 |
| 채택 전 Prompt Trial | 경계 이후 생성분 삭제, 기존 Trial의 이후 Vote·Drop·Render 변경은 당시 상태로 복원 |
| 잠금·계보·비교 추천 정책 | 해당 평가 구간의 적용 Revision을 당시 상태로 복원 |
| 종속 Ablation·Validation Run | Case Evaluation·진단 Render·검증 기록까지 Event 경계로 복원·삭제 |

Prompt 재시험도 세대 번호 대신 Event 경계로 처리합니다. Checkpoint에는 당시 종속 Trial 상태와 Asset 참조를 포함합니다. 폐기 후 보관 중인 Trial도 삭제 영향에 포함합니다. 확인창에 이후 Trial 이미지·비교 이력 수를 함께 표시합니다.

명시적으로 채택해 독립한 Evaluation Revision은 원본 평가 구간 복원의 연쇄 삭제 대상이 아닙니다. 과거 Checkpoint에서 Trial 상태였더라도 현재 독립 채택 구간이면 되돌려 비활성 Trial로 만들지 않습니다. Preview에 보존 사실을 표시하고 유효한 공유 Asset 참조를 보호합니다. 이 경계와 채택의 출처 Snapshot은 [17번 문서](17_prompt_retests_and_reranking.md)를 따릅니다.

북마크 보호는 이 명시적인 복원 삭제의 예외가 아니며 경고창에서 안내합니다. 다른 프로젝트의 독립 결과는 보존합니다. 같은 물리 이미지를 다른 프로젝트가 참조하면 이 프로젝트의 참조만 제거하고 공용 파일을 삭제하지 않습니다. 화면의 삭제 이미지 수와 실제 미참조 물리 파일 삭제 수를 구분합니다.

공유 Catalog 자체, 모델·LoRA 파일, 외부로 이미 내보낸 독립 파일은 삭제 범위가 아닙니다.

[독립 탐색 분기](19_adopted_exploration_tools.md)는 새 Project이므로 원본 복원의 삭제 대상이 아닙니다. 원본 이후에 만들어졌어도 분기의 출처 Snapshot·점수·이미지 참조를 보존합니다. 검증 Suite의 공유 정의와 불변 Version도 전역 삭제하지 않고, 이 평가 구간의 종속 Run·참조를 Event 경계로 처리합니다. 이 보존 범위를 Preview에 명시합니다.

## Checkpoint가 저장해야 할 것

세대 확정 트랜잭션에서 다음을 일관되게 저장합니다.

1. Project/Evaluation/Generation, 평가 조건과 알고리즘 Version.
2. 확정 경계 `event_sequence`와 다음 세대 번호.
3. 활성·퇴역 후보, 성분 구성, Elo·승패·경기 수, 보호·Memo 상태.
4. 작가·LoRA 통계·Prior, 부모 ID/점수, 세대 Log와 안정성 Snapshot.
5. 당시 Render·Output·SavedStyle·이미지 참조 Manifest.
6. 무결성 Hash와 Timeline Revision.
7. 당시 잠금·계보·추천 정책 Revision, 종속 진단·검증 Run/Case 상태와 Asset 참조.

완전한 논리 Snapshot 또는 검증된 Event Replay로 구현합니다. 현재 점수만 저장하거나 가변 객체를 얕게 참조하는 것으로는 부족합니다. 복원 가능한 Checkpoint가 참조하는 이미지는 평상시 Cleanup에서도 보호합니다.

## API·동시성 계약안

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/style-projects/{project_id}/generations/{generation_id}/restore-preview` | 대상·삭제 영향·확인 Token 계산, 비변경 |
| POST | `/api/style-projects/{project_id}/generations/{generation_id}/restore` | 확인 후 복원·삭제 |
| GET | `/api/style-projects/{project_id}/restore-operations/{operation_id}` | 복원·파일 정리 상태 |

실행 요청에 `evaluation_revision_id`, `checkpoint_id`, `expected_timeline_revision`, `confirmation_token`, `idempotency_key`를 포함합니다. Token은 서버가 계산한 대상·삭제 계획에 묶습니다. 요청으로 받은 파일 경로를 그대로 삭제하지 않습니다.

- 관련 생성·평가·다듬기가 진행 중이면 기본적으로 409로 거부하고 완료 또는 취소를 안내합니다.
- 해당 평가 구간을 잠그고 Vote·새 생성·세대 확정을 차단합니다. 다른 프로젝트 작업은 중단하지 않습니다.
- 이전 Timeline Revision의 늦은 완료 Callback이 삭제 데이터를 다시 붙이지 못하게 합니다.
- 같은 Idempotency Key는 같은 Operation 결과를 반환하며 중복 삭제하지 않습니다.
- 세대 번호를 다시 쓰더라도 Generation/Render/Match ID와 Token은 새로 발급합니다.

## DB와 파일 정리

DB 트랜잭션만으로 파일 삭제까지 원자적으로 처리할 수 없습니다. 복원 Operation과 삭제 Manifest를 영속화하고 중단 후 이어서 처리합니다.

1. Checkpoint·Asset 존재·소유 범위·Preview Revision을 검증합니다.
2. 삭제 계획과 복원 상태를 확정합니다. 임시 이동이 필요해도 사용자용 숨겨진 복원 이력으로 유지하지 않습니다.
3. 목표 DB 상태로 복원하고 이후 이력·Checkpoint·참조를 삭제합니다.
4. 공용 참조를 확인한 뒤 미참조 이미지·Cache를 삭제합니다.
5. 삭제 실패는 '정리 중/정리 실패'로 남겨 재시도하고, 완료했다고 안내하지 않습니다.

최소 운영 기록에는 목표 Checkpoint·처리 상태·삭제 수량만 남길 수 있습니다. 삭제한 Vote·이미지·미래 Snapshot을 복사해 보관하지 않습니다. 일반 Undo로 복원 삭제를 취소할 수 없습니다.

## 수락 기준

- 1세대 후보의 Elo가 8세대에서 바뀌었어도 5세대 복원 시 **5세대 당시** 점수·승패가 됩니다.
- 이후 이미지·Vote·Skip·후보·보관 결과·LoRA 기록·Checkpoint가 남지 않습니다.
- 선택 세대 이미지와 당시 보관 결과는 유지하고 다음 세대 번호가 정확합니다.
- 취소는 변경0, 중복 요청은 한 번만 처리, 오래된 Token은409입니다.
- 다른 프로젝트·평가 구간과 공유 Asset의 유효 참조를 보존합니다.
- 중단·재시작·파일 잠금 후 정리를 재개하고 불완전 상태를 표시합니다.
- 이전 Checkpoint가 필요한 이미지를 실수로 삭제하지 않습니다.
- Checkpoint 없는 Import의 과거 상태를 추측해 복원하지 않습니다.
- 종속 Prompt Trial의 이후 변경·이미지를 삭제·복원하며, 독립 채택 Revision을 연쇄 삭제하거나 비활성화하지 않습니다.
- 독립 분기 Project·공유 Suite Version을 보존하고, 종속 Ablation/Validation과 정책 Revision은 Event 경계대로 복원·삭제합니다.
