# 실제 Browser 조작 기록

2026-11-13, 로컬 8388·8389 운영 서비스에서 수행했습니다. Source 읽기나 Fake Comfy 테스트로 실행을 대체하지 않았습니다. 사용자가 새 조사 탭에 직접 로그인한 후 조작했습니다. 처음에는 기존 Browser 세션이 도구에 노출되지 않아 로그인 화면에서 대기했으며, 로그인 이후의 결과를 아래에 기록했습니다.

## 시작 상태와 실제 실행

| 대상 | 시작 상태 | 이번 실행 | 종료 상태 |
| --- | --- | --- | --- |
| StyleLab 8389 | 표시 132세대, 진행 자녀 12개, 부모 6개, 활성+진행 33개 | 기존 선별 완료·132 확정 → 133세대 자녀 1개 생성·1표·확정 → 독립 Random 1개 생성·5표 배치 → 134세대 자녀 1개 생성·취소 경고 확인·1표·확정 | 표시 135세대, 마지막 확정 134, 진행 자녀 0, 활성 22개 |
| CHS 기존 프로젝트 | 현재 확정 1세대, 2세대 자녀 6개의 선별 완료, Prompt 3개 | 2세대 확정 → 3세대 자녀 1개 × 3 Prompt 생성 → 비슷함·Undo → B 선호 4표 → 3세대 확정 → 4세대 계획만 준비·Reload·취소 | 현재 확정 3세대, 활성 10개, 열린 Batch 0, 진행 요청 0 |
| CHS 새 조사 프로젝트 | 없음 | 새 프로젝트 저장 → 2조합 × 2 Prompt 생성 → B 선호 1표 → 기존 프로젝트 왕복·Reload | 1세대, 활성 2개, 열린 Batch 0, 진행 요청 0 |

CHS 기존 프로젝트 ID는 `e30aaf8b619a4483af488090a7e7820c`, 새 `동작 비교 조사 2026-11-13` 프로젝트는 `b9c8b976bf924a839bf8bccd6b65fa6f`입니다. 새 프로젝트는 작가 0개, Munji_V1 LoRA 1개, 낮 거리·실내 서재 두 Prompt로 구성했습니다.

**실제 새 이미지 10장:** StyleLab 3장, CHS 7장입니다. CHS는 Job 2건의 요청 7개가 모두 `completed`이며 파일 존재·크기·SHA-256을 확인했습니다. StyleLab도 새 PNG 3개의 존재·896×1152 크기·SHA-256을 확인했습니다. [실제 생성 증거](evidence/actual-generation-evidence.json)를 참조하세요. Browser에서 보이는 Cache의 `naturalWidth`는 원본 크기와 다를 수 있어 실제 파일 크기를 별도로 검사했습니다.

두 서비스의 Prompt·Seed·해상도·기존 Pool이 같지는 않습니다. 이번 실행은 이미지 품질이나 동일 조건의 선호도 Benchmark가 아니라 **UI와 상태 전환의 비교**입니다. StyleLab 생성에는 조사용 착의 Prompt를 임시 사용했고, 끝난 뒤 원래 Prompt를 다시 저장·Reload해 일치함을 확인했습니다.

## 조작별 결과

| ID | 실제 조작 | StyleLab 결과 | CHS 결과 | 근거 |
| --- | --- | --- | --- | --- |
| B01 | 현재 그림체·세대·진행 상태 확인 | 진행 132세대 자녀 12·부모 6 | 마지막 확정 1세대·2세대 자녀 6 | `stylelab-evolution-existing.png`, `chs-evolution-existing.png` |
| B02 | 그림체 선택·큰 보기·복귀 | Gallery 한 번 선택은 Side Preview. Arena Lightbox는 텍스트 없는 전체 화면 | Gallery/선별 클릭은 Modal. Prompt 1/2→2/2, 원본→Cache, 닫은 뒤 Pair 유지 | `stylelab-gallery-selected-preview`, `stylelab-blind-lightbox`, `chs-gallery-selected-viewer`, `chs-audit-viewer-desktop-prompt1` |
| B03 | 실제 신규 이미지 생성 | 진화 1장씩 두 번, Random 1장 | 기존 프로젝트 3장·새 프로젝트 4장 | `actual-generation-evidence.json` |
| B04 | A/B 선호 선택 | 선택·비선택 강조, Elo 변화와 `+0` 공개 후 다음 Pair | 서버 응답 뒤 비교 영역 교체. 이번 흐름에 동일한 Reveal 대기는 없음 | `stylelab-vote-reveal`, `chs-generation3-votes.json` |
| B05 | 비슷함→Undo | 다른 Pair로 이동한 뒤 Backspace로 원래 두 이미지·A/B 위치 복원 | Backspace로는 복원 안 됨. 버튼 Undo로 여섯 Prompt 이미지 경로가 모두 복원 | `stylelab-skip-undo-restored`, `chs-multi-prompt-undo-restored` |
| B06 | 다음 세대 후보 1개 생성 | 부모 6개 고정, 실제 896×1152 이미지 생성 | 부모 3개, Prompt 3개의 같은 조합 이미지 생성 | `stylelab-generation133-candidate-completed`, `chs-generation3-images-completed` |
| B07 | 자녀 선별 종료 | 새 자녀가 최하위 부모에게 1회 패배 후 확정 가능. 134세대도 같은 1회 종료 | 기존 순위표를 상대로 4회 패배 후 확정 가능 | `stylelab-generation133-one-vote-ready`, `stylelab-generation134-confirmed-next135`, `chs-generation3-selection-finished` |
| B08 | 확정 확인창 취소 후 승인 | 취소 시 132세대 그대로, 승인 후 표시 133 | 돌아가기 시 그대로, 승인 후 확정 2세대 | 각 확정 전후 Screenshot·`runtime-events.json` |
| B09 | 확정과 다음 생성 분리 | 확정만으로 생성하지 않음. 133·134 후보를 별도 시작 | 확정 완료 Panel에서 별도 생성·장수 확인 | `stylelab-generation132-confirmed-next133`, `chs-generation2-confirmed`, 양쪽 최종 상태 |
| B10 | Reload·화면 왕복 | 세대·원래 Prompt 저장 상태 유지. Arena Lightbox는 Screenshot/DOM으로 확인해야 했음 | 조사 프로젝트 선택·네 이미지 경로 유지. 미제출 계획 Reload 후 생성 이어하기 표시 | `chs-audit-project-reload-loaded`, `chs-planned-generation-cancel-warning` |
| B11 | 취소 경고·조건 확인 | 생성 중 취소 비활성, 완료 뒤 자녀·선별 기록 삭제 경고. 최종 삭제는 실행하지 않고 경고를 닫음 | 이미지·Job 보존 및 진행 취소 요청 안내. 미제출 4세대 계획 취소 후 확정 3세대로 복귀, 해당 계획 Job 0건 | `stylelab-generation-cancel-warning`, `chs-planned-generation-cancelled`, `final-runtime-state.json` |
| B12 | 프로젝트·여러 Prompt 분리 | 단일 탐색 상태. 대응 프로젝트 기능 없음 | 새 프로젝트 저장만으로 생성 안 됨. 두 Prompt의 같은 두 조합 비교, 다른 프로젝트 왕복 후 기존 3 Prompt·3세대 유지 | `chs-audit-project-saved`, `chs-original-project-after-audit-vote`, `chs-audit-project-reload-loaded` |
| B13 | 390×844 나란히·한 장씩 | 두 배치 모두 전환됨. 한 장씩에서는 A/B 선택과 고정 Vote Controls 표시 | 한 장씩→B 보기로 두 Prompt의 B 이미지만 표시. Viewer는 Mobile Cache 기본, Desktop 원본 기본 | `stylelab-selection-mobile`, `stylelab-single-image-mobile`, `chs-audit-comparison-mobile`, `chs-audit-viewer-mobile` |
| B14 | 평가 Pool에 Random 추가 | 조합 메뉴에서 독립 Random 1개 생성, 신규 배치 5표 후 일반 리그 복귀 | 주 생성 버튼은 Pool이 갖춰지면 진화 생성. 별도 Random 추가 버튼은 현재 화면에 없음 | `stylelab-random-placement-votes.json`, Source S08 |
| B15 | Keyboard·선별 모드 | Backspace Undo 성공. 전체 리그·상위 30%를 누르면 신규 배치를 잠시 우회, 자동으로 복귀하면 배치 재개 | 같은 Backspace 입력으로 Pair 변화 없음. 대응하는 세 모드 선택은 현재 화면에 없음 | `runtime-progress.md`, Source S06/S09, 두 선별 화면 |

위 근거 이름에 확장자가 없으면 `evidence/이름.png`와 `evidence/이름.txt`가 함께 있습니다. [Runtime Events](evidence/runtime-events.json)는 순서·URL·부가 측정값을 담습니다. 네트워크 응답 전의 일시적인 빈/기존 화면과 완료 후 관찰을 구분했습니다. 예를 들어 `chs-audit-project-reload-persisted`는 데이터 도착 전 관찰이고, 완료 증거는 `chs-audit-project-reload-loaded`입니다.

## 조작 중 수정한 관찰

- StyleLab Lightbox는 실제 화면에 존재했으나 AX Tree에는 Dialog나 이름 있는 이미지로 나오지 않았습니다. 처음 AX만 보고 열리지 않았다고 단정하지 않고 DOM의 `.lightbox`와 Screenshot으로 확인했습니다.
- 132세대 자녀 선별이 끝난 직후 StyleLab은 일반 리그로 넘어갔습니다. 반복 조작에서 추가된 일반 Vote 두 건은 각 Undo 후 이미지 Pair 경로를 대조해 모두 되돌렸습니다. 이후 반복은 현재 선별 종류를 확인하며 종료했습니다.
- StyleLab의 높은 점수 조합이 제외된 이유를 판단할 때 북마크 보호를 함께 확인했습니다. 실제 활성 22개 중 15개가 북마크돼 있어 단순 점수순 퇴역과 결과가 다를 수 있습니다.
- Prompt를 입력한 직후 바로 Reload했던 최초 복원 시도는 저장되지 않았습니다. 페이지를 이탈해 저장한 뒤 Reload한 최종 결과와 파일의 Prompt Hash 일치로 복원을 확인했습니다.

## 종료 상태와 변경 범위

[최종 Runtime 상태](evidence/final-runtime-state.json)에 현재 세대·프로젝트별 후보 수·미제출 취소 계획·진행 요청 0건을 기록했습니다. StyleLab 원래 Prompt를 복원했고, Blind는 끔·모드는 자동·Mobile 비교는 나란히로 돌렸습니다. 임시 Viewport도 두 탭 모두 기본 크기로 복원했습니다.

조사 결과 생성한 조합·이미지·투표·확정 이력과 새 프로젝트는 남겨 두었습니다. StyleLab 무작위 생성 기본 개수는 15→1, 진화 기본 개수는 12→1로 바뀌었습니다. 기존 프로젝트의 CHS 3세대·StyleLab 135세대 생성 대기 화면을 열어 두었습니다. Source 수정·서비스 재시작·Commit·Push는 하지 않았습니다.
