# StyleLab와 CHS 실제 사용 비교

> **정책 해석 정정 · 조사 기록 보존:** 사용자께서 전체 Ladder를 사용한 CHS 선별은 StyleLab 동작을 잘못 파악한 구현 오류라고 명확히 하셨습니다. 이를 의도적 확장으로 보던 해석과 `full-ladder-placement-v2` 정책은 폐기합니다. 후속 결정은 [StyleLab 부모 Selection 복원 명세](../style-lab-rebuild/stylelab_parent_selection.md)를 따릅니다. 아래 실행 결과·수치·Screenshot은 수정 전 조사 시점의 기록이며, 복원 구현의 검증·배포 결과가 아닙니다.

조사 기준: CHS `feature/style-exploration-projects` / `3dbbb87`, 설치된 StyleLab의 8389 Browser 모드.

**조사 상태: 완료.** 사용자 로그인 후 두 운영 서비스에서 직접 생성·선별·세대 확정·프로젝트 전환·Mobile·Viewer를 조작했습니다. 실제 새 이미지 10장(StyleLab 3·CHS 7)을 파일과 저장 상태로 확인했습니다. 이 조사 단계에서는 앱 코드를 변경하지 않았습니다.

핵심 결과는 **Blind 확대 시 조합명 노출**, **Gallery에서 이미지보다 앞서는 과도한 조작 영역**, **원본을 잘못 구현한 자녀 선별**, **독립 Random 추가·선별 모드·선택 결과 피드백·Keyboard 조작의 차이**입니다. 프로젝트와 여러 Prompt 비교는 실제로 동작했습니다. 사용자 정정에 따라 부모만 대상으로 하는 Selection과 독립 Random 생성 경로를 복원하는 것이 확정된 후속 작업입니다. Blind·Gallery·선별 UX 개선은 별도 후속 항목으로 유지합니다.

사용자는 두 서비스를 실제로 눌러 비교하고, 차이·문제·후속 작업을 새 폴더에 정리하도록 요청했습니다. 기존 데이터 변경과 로컬 이미지 생성도 허용했습니다. 이번 작업은 조사와 문서화이며, 새 기능 구현이나 운영 데이터 초기화가 목적은 아닙니다.

## 범위

- 최소 Cycle: 후보 이미지 생성 → 그림체 선별 → 세대 확정 → 다음 후보 이미지 생성.
- 유지할 CHS 확장: 독립 프로젝트 관리와 동일 조합의 여러 Prompt 이미지 생성·비교.
- 이번 최소 구현에서 제외: 융합, 다듬기. 해당 메뉴 부재를 최소 기능의 결함으로 집계하지 않습니다.
- 유지할 사용자 확장, 원본 복원이 필요한 구현 오류, 재현 결함, UI 차이를 구분합니다. 전체 Ladder 선별은 유지할 확장이 아닙니다. 기존 문서의 전체 P0 목록을 이번 최소 기능 범위로 자동 확대하지 않습니다.

## 자료

| 문서 | 내용 |
| --- | --- |
| [먼저 읽기: 재현한 문제와 차이](04-runtime-findings.md) | 실제 Screenshot·수치·동작을 근거로 한 결론 |
| [해야 할 작업](03-action-plan.md) | P0/P1과 대상 파일·완료 조건 제안 |
| [확정된 선별 복원 명세](../style-lab-rebuild/stylelab_parent_selection.md) | 부모 Selection, Random 분리, 기존 미확정 Batch 전환 계약 |
| [실제 Browser 조작 기록](02-browser-walkthrough.md) | 실행한 15개 항목, 데이터 변경 범위와 종료 상태 |
| [Source 비교](01-source-comparison.md) | 현재 파일에서 확인한 동작과 차이, 근거 위치 |
| [Source Inventory](evidence/source-inventory.json) | 조사 시점 Commit과 설치본·CHS 주요 파일 SHA-256 |
| [실제 생성 증거](evidence/actual-generation-evidence.json) | 실제 이미지 파일·크기·SHA-256, CHS Job·Request·Prompt ID |
| [종료 상태](evidence/final-runtime-state.json) | 세대·후보·진행 요청·원래 Prompt 복원 확인 |
| [검증 요약](evidence/verification-summary.json) | 문서 링크·Screenshot 근거·Source 21개·실제 이미지 10개 Hash 재검증 |
| [완료 감사](05-completion-audit.md) | 원래 요청의 각 요구사항과 완료 근거 |

## 완료 조건

1. 8388과 8389에서 실제 이미지 생성이 완료된 증거를 확보합니다. Fake Comfy나 이전 테스트 결과로 대체하지 않습니다.
2. 같은 최소 Cycle을 두 서비스에서 직접 수행합니다. 다음 후보는 가능한 1개로 제한합니다.
3. 선호 선택, 비슷함, Undo, 선별 종료, 세대 확정, 다음 생성, Refresh 후 상태를 확인합니다.
4. 프로젝트 전환과 여러 Prompt를 사용하는 CHS 확장을 별도 확인합니다.
5. 각 차이에 실제 조작 근거 또는 Source 근거를 표시하고, 문제의 영향과 해야 할 작업을 연결합니다.
6. 현재 남은 생성 작업과 변경된 데이터 범위를 기록하고 문서 링크·근거 파일을 검증합니다.

각 조건의 결과는 완료 감사에 기록했습니다. 이미지 품질의 우열, 모든 기능의 완전한 동등성, 배포 바이너리 전체의 복원 완료를 주장하는 조사는 아닙니다. 사용자 제작 8389 Web 모드와 현재 설치 Source가 실제 비교 기준이며, Desktop 앱을 동시에 실행하지 않았습니다.

## 조사 종료 시 남겨 둔 상태

- CHS 기존 프로젝트는 3세대 확정, 새 조사 프로젝트는 1세대·두 Prompt·두 조합으로 남겼습니다. 이번 생성 Job 2건은 완료됐고 조사한 두 프로젝트의 진행 요청은 0건입니다.
- StyleLab은 132·133·134세대를 확정해 현재 135세대 생성 대기입니다. 새 Random 조합도 배치를 마쳤습니다. 원래 Prompt를 복원했고, 무작위/진화 생성 기본 개수는 1개로 남겼습니다.
- Source 수정·서비스 재시작·Commit·Push는 하지 않았습니다. 생성물과 조사 투표·세대 이력은 남겨 두었습니다.
