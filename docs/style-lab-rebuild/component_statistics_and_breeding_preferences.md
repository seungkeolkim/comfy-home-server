# 프로젝트별 작가·LoRA 통계와 진화 선택 보정

2026-11-15. 원본 StyleLab 8389의 실제 `/api/artists`, `/api/loras`, `app/core.py:artist_scores`, `artist_preference`, `app/engine.py:list_artists`, `list_loras`, 일반 Vote 처리와 Browser 조합 목록을 확인했습니다. 원본은 승률이 높아도 기여 점수가 음수일 수 있어 둘을 별도로 표시합니다. LoRA 목록의 점수도 작가와 같은 Ridge Regression 결과이며, 원본의 새 LoRA 선택은 균등입니다.

## 화면

8388의 **프로젝트 설정 → 작가 · LoRA**에서 각 성분의 선호도, 승패, 승률, 평가 조합 수를 표시합니다. Desktop은 이름 오른쪽, Mobile은 이름 아래에 배치하며 STR 최소·최대 입력은 기존 행에 둡니다. 작가와 LoRA는 별도로 등록 순·선호도·승률·승수 정렬을 지원합니다. 통계 새로고침은 설정 저장이나 이미지 생성을 실행하지 않습니다.

화면은 현재 프로젝트의 현재 Evaluation만 읽습니다. 다른 프로젝트나 이전 Prompt·Workflow 조건의 통계는 섞지 않습니다. 통계 응답이 늦거나 정렬을 바꾸더라도 미저장 설정을 보존하며, 단순 통계 갱신은 입력 Focus·Scroll·Form을 교체하지 않습니다. 새 프로젝트 생성 화면과 글로벌 설정에는 기존 프로젝트의 성적을 표시하지 않습니다.

## 통계의 의미

- **선호도:** 현재 조건의 평가된 활성·퇴역 조합 Elo에서 평균을 빼고 STR을 설명 변수로 사용하는 Ridge 기여 점수입니다. 원본과 같은 Ridge 계수 2.0, Coordinate Descent 60회, 정수 반올림을 사용합니다. 관측이 없으면 `—`, 관측은 있지만 평균 수준이면 `0`입니다.
- **평가 조합:** 성분이 들어간 평가 조합의 수입니다. Prompt 수나 Render 재시도로 중복 계산하지 않습니다.
- **승패·승률:** 원본과 같은 일반 대결(`league`, `top`, `tie`)에서 한쪽에만 들어간 성분에 한 번 기록합니다. 양쪽 공통 성분은 STR이 달라도 제외합니다. `similar`, Placement, 진화 Batch 비교는 이 직접 승패에 포함하지 않지만, 이들이 결정한 최종 Elo는 선호도에 반영됩니다.
- 진행 중 진화 자녀·취소·삭제 조합은 선호도 학습에서 제외합니다. 확정 후 활성·퇴역으로 남은 자녀는 다음 계산에 포함됩니다.
- 승패는 기존 유효 Vote Event에서 읽으며 Undo된 Vote와 삭제·취소 조합이 참여한 대결은 제외합니다. 새로운 집계 테이블이나 과거 데이터 변경은 없습니다. Elo를 수동 수정하면 선호도는 달라지지만 직접 승패는 달라지지 않습니다.

기여 점수는 관측된 조합 내 상대 추정치입니다. 늘 함께 쓰인 성분의 독립적인 품질을 확정하는 값으로 해석하지 않습니다.

## 다음 세대

새 세대의 정책은 `style-evolution-v2`, 성분 선호 정책은 `ridge-60-component-preference-v1`입니다. 작가와 LoRA 각각 현재 프로젝트에서 사용할 수 있는 성분끼리 정규화합니다.

```text
preference(component) = 2 ** (score(component) / max_abs_score_of_same_kind)
draw_weight(component) = preference(component) / (1 + parent_usage(component))
```

기록이 없거나 같은 종류의 점수가 모두 0이면 선호 보정은 1배입니다. 선호 보정은 0.5~2배이며 부모 Pool에서 많이 사용한 성분에는 별도 사용량 보정을 적용합니다. 낮은 점수 성분을 자동 제외하지 않습니다.

Mutate의 새 성분 교체·추가와 진화 Random의 새 성분 선택에 두 종류 모두 같은 보정을 사용합니다. 상속된 성분·Crossover 구성·부모의 상위 30% 선정·Mutate/Crossover/Random의 1:1:1 확률은 유지합니다. 성분의 STR 자체를 점수만큼 올리지 않으며 기존 개수·STR 범위·성분 제외·독립 CLIP 값은 그대로 적용합니다. 초기 Random 생성에는 새 선호 보정을 적용하지 않습니다.

새 계획의 `selection`에는 정책 Version, 실제 계산 점수, 선택 보정 배수, 부모별 성분 사용량과 기존 Selection Seed를 기록합니다. 이미 만들어진 계획·후보·이미지·Elo는 다시 추첨하거나 수정하지 않습니다.

## 연결과 검증

`GET /api/style-projects/{project_id}/component-statistics`는 현재 Evaluation을 기본으로 읽습니다. `evaluationIdentifier`를 명시할 경우 같은 프로젝트 소유 조건인지 검증합니다. 하나의 읽기 Transaction에서 후보·Arena·Vote를 조회하며 Arena 생성, Revision 갱신, Render·이미지 순회는 하지 않습니다. 설정 화면에서만 전용 API를 읽고 진행 중 요청을 합치므로 선별·그림체의 기존 Polling에 Ridge 계산을 추가하지 않습니다.

Python 검증은 원본 함수 Golden 비교, 종류별 정규화, 실제 추첨 분포와 낮은 점수 성분의 탐색, STR 범위, 프로젝트·조건 격리, Undo, 공통 성분 제외, 실제 조합 폐기, 표시와 생성 계획의 점수·배수 일치를 포함합니다. Browser는 실제 임시 PNG와 Vote를 사용하는 격리 서버에서 320/390/768/1280px, 통계 표시·정렬·프로젝트 전환·늦은 응답 중 미저장 입력과 Focus 보존을 확인합니다. 운영에서는 생성·투표·설정 변경 없이 조회와 화면만 검증합니다.

기존 선별 Browser 회귀에서 Mode·Vote 충돌 응답 뒤 이미지 배치 버튼이 잠긴 채 남는 경우를 확인했습니다. 접수되지 않은 요청은 비교 Markup을 다시 반영해 버튼을 복구하며, 공통 교체 함수가 이미지 Node를 재사용하므로 같은 이미지의 Decode와 표시는 유지합니다.

검증 결과: Python 전체 527 Passed / 1 Skipped. Browser는 프로젝트 설정·진화 Cycle·선별 UX·Pool 수량·성분 통계의 다섯 시나리오를 통과했습니다. GPU 생성과 Vote는 격리 Fake Comfy 서버에서만 실행했습니다.

운영 반영 시 `runtime/style-component-statistics-deployment-20261115-045720/`에 DB·기존 소스를 Backup하고 CHS를 재기동했습니다. Schema 18, 업무 테이블 32개 전체 행, 스타일 이미지 379장의 Hash가 반영 전후 동일했고 FK 오류는 0건입니다. 운영 세 프로젝트의 조회와 실제 20개 성분 표시를 320/390/768/1280px에서 확인했습니다. API 조회 중앙값은 51.21ms, Browser 변경 API·오류는 0건이며 서버는 `running / healthy`입니다.
