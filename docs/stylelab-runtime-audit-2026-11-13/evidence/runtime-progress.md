# 실제 조작 진행 기록

이 파일은 조사 중 진행 기록의 보관본입니다. 최종 판정은 상위 문서와 `final-runtime-state.json`을 기준으로 읽습니다.

- 사용자 직접 로그인 완료. In-app Browser Tab 2 = 8389, Tab 3 = 8388.
- CHS 기존 프로젝트: `e30aaf8b619a4483af488090a7e7820c` / 테스트 프로젝트. 시작 시 1세대, 2세대 자녀 6개 선별 완료. 2세대 확정 후 자녀 1개 × 3 Prompt 실제 생성. 비슷함→Undo로 A/B 여섯 이미지 복원. Keyboard Backspace는 표를 되돌리지 않았으며 버튼 Undo는 정상. B 선호 4회로 새 자녀 배치 완료·탈락, 3세대 확정. 현재 새 생성 없이 확정 대기.
- CHS 신규 조사 프로젝트: `b9c8b976bf924a839bf8bccd6b65fa6f` / 동작 비교 조사 2026-11-13. 이름·메모·낮 거리/실내 서재 두 Prompt, Anima Workflow, 작가 0, Munji_V1 LoRA 1개 범위로 생성. 프로젝트 저장은 생성하지 않았음. 2조합 × 2 Prompt 실제 이미지 4장 완료. 후보 02에 B를 선호한 1회 투표 후 기존 프로젝트로 왕복했을 때 Prompt·후보가 분리됨. Reload 후 선택 프로젝트와 네 이미지 경로가 신규 프로젝트 ID를 포함함을 확인.
- CHS Viewer: Desktop 원본 기본, Prompt 1/2→2/2 이동, 압축 전환, 닫은 뒤 Pair 유지 확인. Mobile 390×844 한 장씩/B 전환·압축 Viewer 확인. **Blind에서 큰 보기를 열면 실제 세대·조합명과 파일 이름이 노출됨**: `chs-blind-viewer-identity-leak`.
- StyleLab 시작 상태: 현재 132세대, 진행 자녀 12개, 부모 6개, 활성+진행 그림체 33. 비슷함→Backspace Undo로 같은 두 이미지 경로 복원. 기존 132세대 선별을 진행해 생존 5·탈락 7로 확정, 현재 표시 133으로 바뀜. 완료 직후 일반 리그로 자동 이동해 발생한 추가 Vote 2개는 버튼 Undo로 Pair 경로를 확인하며 모두 복원.
- StyleLab 133세대: 조사용 완전 착의 Prompt로 바꾼 뒤 1개 실제 생성 (`36308fd767.png`, 896×1152). 최하위 부모 선호 1회만으로 탈락·확정 가능. 확정 후 현재 표시 134로 바뀜.
- StyleLab 무작위 신규 조합: 조합 메뉴에서 1개 실제 생성 (`68387e10ff.png`, 896×1152). 진화와 별도로 신규 자리 찾기에 진입. 신규 조합이 지도록 기존 후보 선호 5회로 배치 완료. 이때 전체 리그/상위 30% 모드를 선택하면 신규 배치를 일시 우회하고 일반/상위 리그로 전환되며, 자동으로 돌리면 신규 배치를 재개함.
- StyleLab Blind Lightbox: `.lightbox` 실제 표시를 DOM과 Screenshot으로 확인. 빈 텍스트이며 조합명이 없었음. Dialog Role/이미지 Alt가 없어 AX Tree에는 보이지 않았으므로 화면/DOM을 함께 확인함.
- StyleLab Mobile 390×844: 나란히 이미지 각각 약153.5×255.8px, 한 장씩/A·B/고정 선호 버튼 전환 확인. CSS Viewport를 원래 1743×1244로 복원함.
- StyleLab 원래 Prompt는 페이지 이탈 저장 후 Reload로 값 일치 확인(`originalPromptPersisted=true`). 입력 직후 즉시 Reload한 최초 시도는 저장되지 않았으므로 복원 완료 근거로 사용하지 않았음. Browser 모드는 자동 Draft API가 No-op이며 Source에서 이탈 Flush가 확인됨.
- StyleLab 생성 기본 개수는 실행으로 무작위 15→1, 진화 12→1로 바뀜. Blind는 끔, 선별 모드는 자동, Mobile 비교는 나란히로 복귀함.

후속 완료: 취소 경고를 두 서비스에서 실제 확인했습니다. CHS는 GPU 미제출 계획을 취소했고, StyleLab은 삭제 확인창을 닫은 뒤 새 134세대 자녀를 한 표로 탈락·확정했습니다. StyleLab 표시 135세대·진행 자녀 0, CHS 기존 프로젝트 확정 3세대·열린 Batch 0으로 마무리했습니다. StyleLab 세 번째 새 이미지는 `f87d3557c4.png`이며 총 생성은 StyleLab 3·CHS 7장입니다. 원래 Prompt는 최종 Reload 뒤에도 복원된 것을 확인했습니다. Gallery·파일/Job 상태와 문서 정리는 상위 문서에 반영했습니다.
