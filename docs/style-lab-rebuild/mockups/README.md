# 스타일 작업 공간 목업

실제 서비스와 분리한 UI 검토 자료입니다. 네트워크 요청·DB 변경·이미지 생성·파일 삭제를 실행하지 않습니다.

## 보기

- [Desktop Web](style-workspace-desktop.html)
- [Mobile Web](style-workspace-mobile.html)
- [화면 목록과 전환 설계](../18_workspace_navigation_and_screen_mockups.md)

HTML은 각자 독립적으로 동작하는 Fragment입니다. 대화의 미리보기와 일반 Browser에서 사용할 수 있으며, 문서 Hosting 환경에 따라 HTML 열기를 제한하면 파일을 Browser에서 직접 여세요. Mobile 목업을 독립 Browser에서 열 때는 개발자 도구의 Mobile Viewport를 사용하세요. 대화 미리보기는 호스트의 Viewport 설정을 사용합니다.

비교 화면에서 시작합니다. 상단 `일반 생성 / 스타일 구성`, 왼쪽 메뉴 또는 Mobile 하단 메뉴를 눌러 이동합니다. Prompt 시험은 상위 N개 생성 → 시험 이미지 비교 → Drop/취소 → 채택 흐름을 확인할 수 있습니다. 목록·비교·순위·투표 등 모든 값은 예시입니다. 새 프로젝트·성분 관리·Job 상세는 화면 진입점과 요약을 보여줍니다.

## 편집

| 파일 | 역할 |
| --- | --- |
| `workspace-shell.html` | 두 작업 공간의 공통 외곽 구조 |
| `workspace-preview.css` | 제품 전용 스타일, 기기별 배치, Light/Dark |
| `workspace-preview.js` | 예시 상태, 화면 전환, 입력 보존, 시험·Drop·Elo 예시 |
| `build_mockup_previews.py` | 공통 소스로 Desktop·Mobile Fragment 재생성 |
| `style-workspace-desktop.html` | 생성한 Desktop 미리보기 |
| `style-workspace-mobile.html` | 생성한 Mobile 미리보기 |
| `screenshots/` | Browser 검토용 화면 Snapshot |

이 폴더에서 `python -X utf8 build_mockup_previews.py`를 실행합니다. 생성한 두 HTML도 함께 관리해 Python 없이 바로 볼 수 있게 합니다. 목업 코드와 Style Lab 복원용 `source_reference/`는 별개입니다. Snapshot 원문은 UI 수정에 맞춰 갱신하지 않습니다.

## 화면 Snapshot

| 화면 | Desktop | Mobile |
| --- | --- | --- |
| 이미지 비교 | [보기](screenshots/desktop-comparison.png) | [보기](screenshots/mobile-comparison.png) |
| 프로젝트 목록 | [보기](screenshots/desktop-projects.png) | [보기](screenshots/mobile-projects.png) |
| Prompt 시험 결과 | [보기](screenshots/desktop-prompt-trial.png) | [보기](screenshots/mobile-prompt-trial.png) |
| 세대 복원 확인 | [보기](screenshots/desktop-restore-dialog.png) | [보기](screenshots/mobile-restore-dialog.png) |
