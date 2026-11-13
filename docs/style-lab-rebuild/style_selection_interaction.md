# 선별 진행 사용성 개선

2026-11-13 조사 후속 항목 중 선택 결과 피드백·Keyboard·선별 Mode를 구현합니다. 선행 조건인 [부모 Selection 복원](stylelab_parent_selection.md)과 독립 Random 생성은 `9c26f4b`에 반영했습니다. Blind Viewer와 Gallery 개편은 이번 기능의 선행 조건이 아니며 별도 항목으로 남습니다.

## 선택 결과

- A/B 또는 비슷함을 선택하면 모든 Prompt의 같은 조합에 선택 강조를 적용합니다. 약 170ms 후 서버에 저장하며, 처리 중 중복 선택과 Mode 변경을 막습니다.
- 서버가 투표를 승인하면 방금 비교한 Pair를 1초 동안 유지합니다. 기존 조합은 투표 후 Elo와 변화량을 표시하며 변화가 없으면 `+0`을 표시합니다. 미배치 Random과 진행 중 진화 자녀는 `평가 중`으로 표시합니다.
- Blind가 켜진 상태에서도 승인 직후 1초 동안 해당 Pair의 정보를 공개합니다. 다음 Pair에서는 다시 가리며 Blind 설정 자체는 바꾸지 않습니다. 저장 실패 시 성공한 결과로 공개하지 않습니다.
- 프로젝트·Prompt 평가 조건을 바꾸면 이전 투표의 공개 화면이 새 대상에 덮어씌워지지 않습니다. 여러 Prompt는 같은 조합의 한 표로 처리합니다.
- 선택 처리 중 화면을 이동할 수 있습니다. 같은 프로젝트의 생성·세대 확정/취소·Elo 수정·조합 폐기는 처리가 끝난 뒤 실행하도록 안내하며, 이미지 탐색과 목록 선택은 계속 사용할 수 있습니다.

## Keyboard

| Key | 동작 |
| --- | --- |
| `←`, `Numpad4` | A 선호 |
| `→`, `Numpad6` | B 선호 |
| `Enter` | 비슷함 |
| `Backspace` | 마지막 선택 Undo |

투표 버튼이 활성화된 경우에만 단축키를 적용합니다. 입력칸·Select·ContentEditable·IME·Key repeat·Modifier 조합과 열린 Dialog/Viewer에서는 가로채지 않습니다. Button에 Focus한 상태의 `Enter`는 해당 Button의 기본 동작을 유지합니다.

## 선별 Mode

| Mode | 비교 대상 |
| --- | --- |
| 자동 | 진행 중 Random Placement·신규끼리 비교와 진화 자녀 Selection을 이어갑니다. |
| 전체 리그 | 평가를 마친 기존 조합끼리 비교합니다. 신규 배치와 진화 자녀 선별은 일시 중단합니다. |
| 상위 30% | 평가를 마친 기존 조합의 상위 30%끼리 비교합니다. 대상이 두 개 미만이면 상위 두 조합을 사용합니다. |

모든 Mode에서 상위 30%의 경계 동점 질문은 진화 Selection·일반 리그보다 우선합니다. 자동 Mode의 신규 배치는 경계 동점보다 먼저 이어갑니다. 진행 중 진화 자녀는 수동 리그 대상에서 제외합니다. 자동으로 돌아오면 기존 Placement와 자녀 Selection 기록을 이어갑니다.

Mode는 프로젝트의 평가 조건별로 저장합니다. `POST /api/style-projects/{projectIdentifier}/selection-mode`는 현재 Revision을 검증하고 다음 Match Token을 새로 발급하며, Vote나 Undo 이력을 추가하지 않습니다. 이미 처리한 Operation ID는 같은 응답을 반환합니다.

Undo는 현재 Mode 설정을 유지하며 직전 투표의 원래 Pair를 복원합니다. 그 Pair에 다시 투표한 뒤부터 현재 Mode로 다음 비교를 선택합니다. 수동 리그에서 부모 Elo가 바뀌어도 이미 시작한 진화의 고정 부모 기준점은 바뀌지 않습니다. 진화 취소는 자녀 선별을 취소하며 기존 조합의 일반 리그 투표 결과·성분 통계·Mode를 보존합니다.

세대 확정 가능 여부는 실제 남은 자녀 Selection으로 계산합니다. 수동 리그로 전환해도 미완료 자녀 선별을 건너뛰어 확정할 수 없습니다. 자동에서 자녀 선별이 끝나면 CHS의 명시적인 세대 확인 단계를 유지합니다. 원본 StyleLab이 자동으로 일반 리그에 돌아가는 부분과는 의도적으로 다르며, 추가 일반 평가는 전체 리그·상위 30%로 전환해 진행할 수 있습니다.

## 검증·운영 반영

- 전체 `test_style*.py` 102개가 통과했습니다. 신규 12개는 Mode 저장·평가 조건 격리·멱등/Revision 충돌·상위 30% 범위·자녀 제외·Undo·일반 투표의 확정/취소 보존을 검증합니다.
- 격리 Browser에서 기존 선별 Cycle과 진화 Cycle이 통과했습니다. 다중 Prompt 한 표·다른 Browser의 Undo 제한·오래된 Token 거절·2/3세대 확정·4세대 준비/취소·응답 유실/Reload를 포함합니다.
- 신규 `browser_style_selection_ux.cjs`는 같은 Pair의 선택 강조/Reveal·Blind 재가림·Elo `+0`·Keyboard와 Focus/Viewer/IME 방어·Mode 변경/Reload/오류 복구·공개 도중 프로젝트 전환을 검증합니다. 투표 응답을 보류한 상태에서 같은 프로젝트의 생성·Elo 수정·폐기를 막고 다른 프로젝트의 관리 Dialog는 열 수 있는지도 확인했습니다.
- 320·390·768·1280px 폭에서 가로 넘침이 없고 Mobile 모드 버튼 세 개가 한 줄 전체 폭에 겹침 없이 표시됨을 확인했습니다. Desktop·Mobile Screenshot을 직접 검토했습니다.
- Browser는 Fake Comfy의 실제 임시 PNG와 격리 DB를 사용했습니다. 운영 GPU 생성을 검증한 결과는 아닙니다. 결과 JSON과 Screenshot은 `runtime/verification/style-selection-ux-browser-results.json`, `style-selection-feedback-desktop.png`, `style-selection-feedback-mobile.png`에 보관합니다.
- 운영은 진행 요청·미확정 Batch 모두 0개인 상태에서 DB Backup 후 재시작했습니다. 서비스 `running / healthy`, `/api/session` HTTP 200, 새 Mode API의 OpenAPI 등록, 변경한 화면 자산 6개의 제공 Hash 일치를 확인했습니다. 로그인 후 운영 화면 조작은 격리 Browser 검증으로 대체했으며 운영 투표·GPU 생성은 실행하지 않았습니다.
- 운영 DB 32개 업무 테이블의 내용 Hash가 반영 전후 동일합니다. `quick_check=ok`, Foreign Key 위반은 0건입니다. Backup과 검증 결과는 `runtime/style-selection-interaction-deployment-20261113-125845/`에 보관합니다.
