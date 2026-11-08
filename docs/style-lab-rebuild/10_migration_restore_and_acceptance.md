# 복원·이관·수락 검증

## 이 문서 묶음에서 기존 로직 복원

1. [원문 목록](source_reference/README.md)에서 파일별 Source 경로와 코드 블록을 확인합니다.
2. 새 빈 작업 폴더에 Python/JS/CSS/HTML을 해당 상대 경로로 복원합니다. 운영 폴더에 바로 덮어쓰지 않습니다.
3. 원문은 UTF-8, LF, 마지막 줄바꿈으로 정규화한 Snapshot입니다. `Snapshot Text SHA-256`으로 추출 결과를 확인합니다. 원본 Byte Hash는 원래 파일 식별용입니다.
4. 내장 Python 전체나 모델을 포함한 배포 Package는 아닙니다. 필요한 Runtime·라이브러리를 별도 준비합니다. `runtime_inventory.md`에 관측한 Distribution 목록을 보관합니다.
5. Web은 Bottle·Pillow와 기존 Engine, Desktop은 추가로 pywebview/WebView2·Windows 통합 코드가 필요합니다. 새 독립 앱이 Desktop 방식을 그대로 채택할 필요는 없습니다.
6. 사용자 이미지까지 복원하려면 별도 State+PNG Backup이 필요합니다. 인증 파일은 이관하지 말고 새 환경에서 설정합니다.

복원용 Source에는 테스트도 포함합니다. 구동 전에 임시 데이터에서 다음을 실행합니다.

```powershell
./python/python.exe -B -X utf8 -m unittest discover -s tests_web -p "test_*.py" -v
```

상대 Runtime 경로는 준비한 환경에 맞춥니다. 현재 포함된 테스트는 Web 계약·경고 분리에 집중되어 있으며, 모든 순위·진화 알고리즘을 검증하는 완전한 Suite는 아닙니다. 아래 Golden Fixture를 추가해야 합니다.

## 기존 데이터 이관 Mode

| Mode | 가져오는 것 | 주의 |
| --- | --- | --- |
| `legacy_project_full` | 작가·LoRA, 활성·퇴역 후보, 이미지, Vote, 세대 기록 | 하나의 Legacy Project로 격리. 과거 조건을 정확히 알 수 없으면 Unknown 표시 |
| `catalog_only` | 선택한 작가·LoRA 등록 정보 | 점수·사용·승패는 초기화 |
| `component_scores_only` | Registry Identity와 계산된 점수 Snapshot | 조합·이미지·Vote·세대를 가져오지 않음 |

기존 전역 State에 서로 다른 Prompt/모델에서 만든 후보가 섞였을 수 있습니다. 원본에 기록되지 않은 평가 조건을 추측해 새 Evaluation을 만들어 넣지 않습니다. 알려진 현재 설정은 `현재 설정 Snapshot`이며 모든 과거 이미지의 설정을 증명하지 않습니다. PNG에 남아 있는 Workflow와 Seed는 별도 근거로 이용할 수 있습니다.

## 안전한 Migration 절차

1. 원본을 읽기 전용으로 취급하고 State 파일 Hash·Schema·이미지 목록을 기록합니다.
2. Dry-run으로 누락 PNG, 중복 ID, 알 수 없는 History 종류, 오래된 Schema를 보고합니다.
3. Legacy ID → 새 UUID, 이미지 → Output ID 대응표를 생성합니다. 원본 ID를 삭제하지 않습니다.
4. 새 프로젝트와 필요한 Evaluation Snapshot을 트랜잭션으로 생성합니다.
5. 선택 Mode에 맞게 데이터를 변환하고 수·점수·참조 무결성을 대조합니다.
6. 완료 후 원본을 삭제하지 않습니다. 같은 Import를 다시 실행해 중복 생성하지 않도록 Source Hash/Import ID를 기록합니다.

원본 `core.load_state`를 이관 도구에서 무심코 호출하면 원본 옆 Backup을 생성할 수 있습니다. 이관 도구는 원본을 직접 읽거나 별도 사본에서 Upgrade합니다.

## 필수 수락 테스트

### 프로젝트와 점수

- 두 Project가 같은 작가·LoRA를 쓰더라도 한쪽 Vote·Undo·Reset·진화가 다른 쪽에 영향을 주지 않습니다.
- Fresh는 후보0/Vote0/세대1/성분점수0, 점수 복제는 후보0/Vote0/세대1/성분Prior 유지입니다.
- 점수 원본을 뒤에서 변경해도 복제한 Prior는 변하지 않습니다.
- 확정 Checkpoint 복원 시 이후 이미지·이력·승패·Elo 변경과 이후 보관 결과를 삭제하고 기존 후보도 당시 통계로 돌아갑니다.
- 복원 취소·중복 요청·오래된 Token·공유 이미지·파일 삭제 실패는 [15번 문서](15_generation_restore_and_deletion.md)의 기준으로 검증합니다.
- 모델을 바꾸면 새 Revision이 생기고 기존 이미지·Elo와 섞이지 않습니다.
- 없는 LoRA, 이름이 같지만 Hash가 바뀐 LoRA, 미지원 Artist Component를 구분합니다.

### 알고리즘 Golden Fixture

- 10000 대 10000의 일반 Vote 결과는 10160/9840입니다.
- 24개 전 신규 Pair 평가, 그 이후 Placement, S/A 경계 동점 6개 이하/초과를 검증합니다.
- 모순 Vote, 여러 자녀의 동일 Slot, Skip, Undo, 세대 취소를 검증합니다.
- 부모 Score는 진화 비교 중 고정됩니다. 자녀 승격 수·북마크 보호·퇴역 사유를 대조합니다.
- 기존 Ridge 60 Sweeps 결과와 새 Engine의 Fresh 결과가 일치합니다. Prior 모드는 데이터0에서도 가져온 점수가 남습니다.
- LoRA-only 후보 생성·진화가 정상 동작하고, 동시 Registry On/Off 설정을 지킵니다.

### 생성과 Workflow 동일성

- 같은 RenderPlan을 일반 생성과 Style 경로에 넣으면 승인된 동적 Field 외 API Graph가 같습니다.
- 고정 Sampling Seed가 `_submit_requests`에서 난수로 바뀌지 않습니다. Tag/Wildcard 전개도 고정됩니다.
- Positive/Negative 실제 Encode 입력, Model/LoRA→NegPip 순서, Model/CLIP 강도0을 대조합니다.
- API JSON뿐 아니라 PNG의 UI Metadata도 같은 설정을 보존합니다.
- Moss가 미등록이면 명확히 거부하며 MiniMax Branch로 처리하지 않습니다.
- 새 Output은 Home Catalog에 한 번만 등록됩니다. Browser를 닫아도 완료 추적이 계속됩니다.

### Prompt 재시험과 여러 계보

- 상위 N개 Snapshot과 성분·순서·Model/CLIP Weight가 유지되고 변이·교차·세대 증가는 없습니다.
- Trial Elo 10000/전적0에서 비교하며 원본 Vote·통계·이미지가 보존됩니다.
- N=1 생성, N=2 비교, Drop/취소/Undo, 실패 항목만 재시도를 검증합니다.
- Drop이 가짜 패배를 만들지 않고 채택 시 성공한 미제외 후보만 이어집니다.
- 미시험 후보의 기존 Elo가 새 Prompt 순위에 합류하지 않습니다. 채택 뒤 진화 최소 조건도 별도로 검사합니다.
- 오래된 채택 Token은 409이고 세대 복원은 종속 Trial과 독립 채택 Revision을 구분합니다.
- 전체 상위 30% 밖의 계보 대표도 배정된 부모 기회를 얻으며 예산 부족을 표시합니다.
- 세부 수락 기준은 [16번](16_search_strategy_and_diversity.md)·[17번 문서](17_prompt_retests_and_reranking.md)를 따릅니다.

### 동시성·복구·모바일

- 동일 Vote를 두 번 보내도 한 번만 반영됩니다. 오래된 Match Token은 409입니다.
- Project별 작업 취소가 다른 Project/일반 생성의 Queue를 중단하지 않습니다.
- 재시작·접속 단절 뒤 제출 여부가 모호한 요청을 자동 재제출하지 않습니다.
- 두 이미지가 준비되기 전 Vote 불가, 키 연타 방지, 화면 위치와 A/B ID 일치, Blind 유지.
- 모바일 Pair/Single 비교, 적용 기록 펼치기, Toast 2개 제한, 가로 넘침을 확인합니다.

## 이번 문서 작성에서 수행하지 않은 것

새 프로그램 구현·DB Migration·추가 생성·서비스 재기동·GPU 모델 로드를 수행하지 않았습니다. 문서 검증은 원문 Snapshot의 Hash와 Markdown 내부 연결, 현재 코드와의 계약 대조로 제한합니다.
