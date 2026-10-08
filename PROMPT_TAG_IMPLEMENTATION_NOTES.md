# Anima Prompt 태그 구현 메모

> 이 문서는 구현 중 결정을 보존하기 위한 임시 문서입니다. 정식 문서에 반영한 뒤 브랜치 머지 전에 삭제합니다.

## 현재 결정

- Anima Prompt preset에는 `prompt`와 `negative` 텍스트만 저장합니다. Prompt 본문에 적힌 `[SCENE]` 같은 참조가 태그 조합의 시작점입니다.
- 태그 항목은 안정적인 ID, 참조 key, 화면 이름, 본문, 선택 weight, 소속 표시 그룹을 갖습니다. 항목 본문에서도 `[CHR]`, `[TWOCHR]`처럼 다른 태그를 참조할 수 있습니다.
- 생성 화면은 Prompt 본문의 참조 key에 해당하는 선택지만 보여줍니다. 사용자가 항목을 선택하면 그 본문에서 필요한 하위 참조 key의 선택지를 이어서 보여줍니다.
- 동일 key에 대해 선택된 항목은 공통 후보 집합으로 취급합니다. 각 참조 위치에서 weight에 따라 독립적으로 추첨하므로 동일 항목이 여러 번 선택될 수 있습니다.
- 미리보기와 제출은 Prompt에서 도달 가능한 모든 후보 경로의 누락과 cycle을 검사합니다. 태그 치환 뒤 기존 wildcard를 요청별로 확정하고, 확정 Prompt만 ComfyUI에 전달합니다.
- 표시 그룹은 생성 화면과 태그 관리 화면을 정리하며 두 화면 모두 그룹별 접기·펼치기를 제공합니다. 기본 펼침·접힘 상태를 저장하고 각 화면에서 사용자가 바꾼 상태는 독립적으로 유지합니다. 그룹은 이름순, 그룹 안의 항목은 화면 이름순으로 표시하며 그룹은 선택 의미와 무관합니다.
- 생성 화면에서는 그룹에 현재 표시된 항목을 일괄선택하거나 일괄해제할 수 있습니다. 아직 필요하지 않아 숨겨진 참조 key의 항목에는 적용하지 않습니다.
- Prompt preset은 태그 선택이나 태그 내용 snapshot을 보관하지 않습니다. 생성할 때 현재 태그 정의를 사용합니다. 제출한 작업 이력에는 사용한 정의, 선택 경로, 확정 Prompt를 보관합니다.
- MiniMax H3는 평문 Prompt 방식을 유지합니다.

## 데이터와 백업

- 작업 브랜치: `feat/anima-prompt-template-graph`.
- 작업 전 백업: `runtime/backups/prompt_template_graph_20261008_193308/`.
- 기존 Prompt 정리 전 백업: `runtime/backups/onepiece_tag_conversion_20261008_212835/`.
- Prompt 본문 참조 방식으로 전환하기 전 백업: `runtime/backups/literal_prompt_refs_20261008_215203/`.
- `Anima onepiece` 최신 내용만 Prompt preset v1로 남겼습니다. Prompt 본문에 `[SCENE]`을 넣고, 공유 장면 문구는 SCENE 항목 하나, 캐릭터 구성은 CHR 항목 두 개로 옮겼습니다. 다른 Prompt preset과 이전 버전은 백업 후 제거했습니다.
- 활성 DB schema는 v4입니다. 태그 테이블에는 조합 시작점 전용 컬럼이 없습니다. 작업 이력과 LoRA 데이터는 유지했습니다.

## 추후 label 설계

- 태그는 여러 label을 가질 수 있어야 하므로 label과 태그 항목은 many-to-many 관계가 적합합니다.
- 태그에서 label을 제거할 때 연결만 삭제하며 태그 본문은 유지합니다. label 자체 삭제도 태그 항목을 삭제하지 않아야 합니다.
- 표시 그룹과 label은 별도 개념입니다. label 필터의 AND/OR 정책은 기능 추가 시 결정합니다.
