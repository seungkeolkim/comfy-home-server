# 그림체 즐겨찾기

2026-11-15. 이미지 생성의 그림체 탭 통합은 `d349b15`로 커밋했고, 후속 요청으로 조합 단위 좋아요와 모아보기를 추가합니다.

## 동작

- 조합 카드 하단은 **Elo 수정 / 조합 폐기 / ☆·★** 순서이며 별표로 즐겨찾기를 추가·해제합니다. 여러 Prompt의 이미지 전체가 하나의 그림체로 묶입니다. 그림체·진화에서 연 상세 Viewer의 별표는 제목 길이와 관계없이 닫기 버튼 바로 왼쪽에 배치합니다. 선별 Viewer에는 추가하지 않습니다.
- 그림체의 **★ 즐겨찾기만 보기**는 현재 프로젝트의 모든 평가 조건·세대·상태에서 좋아요를 모읍니다. 퇴역 그림체도 포함하며 모아보기 중 표시 상태는 전체로 고정합니다. 해제하면 이전 활성·퇴역 등의 필터로 돌아갑니다. Elo·평가 횟수 정렬은 계속 사용할 수 있습니다.
- 별표는 서버 DB에 저장되어 새로고침과 다른 기기에서도 유지됩니다. 모아보기 선택은 기존 프로젝트별 Browser Session에 보관합니다. 새 조합을 실제 생성하면 새 결과가 보이도록 활성 목록으로 전환합니다.
- 좋아요는 모아보기용 표시입니다. Elo·승패·성분 선호도·진화 선발과 자동 퇴역 정책을 바꾸지 않습니다. 퇴역 뒤에도 별표는 남지만 조합을 폐기하면 함께 정리합니다.

## 구현 계약

- `PUT /api/style-projects/{projectIdentifier}/candidates/{candidateIdentifier}/favorite`, Body는 `{"isFavorite": true}` 또는 `false`입니다. Toggle 명령 대신 원하는 상태를 전송하여 같은 요청의 재시도가 두 번 뒤집히지 않게 합니다.
- Home 인증과 소유 프로젝트·생성된 조합 여부를 검사합니다. 다른 프로젝트·미제출·폐기 조합은 404, Bool이 아닌 값과 추가 필드는 422입니다. 기존 생성 Mutation Lock과 SQLite Transaction으로 폐기와 경합하지 않게 합니다.
- Generation Results의 각 조합에 `isFavorite` Bool을 추가합니다. Summary 조회에서도 같은 값을 읽으며 즐겨찾기별 추가 요청이나 이미지 파일 탐색은 하지 않습니다.
- DB Schema 19의 `style_candidate_favorites`는 조합 ID와 등록 시각만 저장합니다. 기존 18 DB는 검증한 원본 Backup 후 추가 테이블을 생성합니다. 기존 생성·점수 행과 이미지 파일은 수정하지 않습니다.
- 저장 중인 별표만 잠그고 프로젝트 이동은 허용합니다. 늦은 Polling 응답은 저장된 별표를 덮지 못하게 하며, 실패하면 기존 표시와 재시도를 유지합니다. 같은 이미지 노드와 공통 Viewer·Thumbnail Cache를 재사용합니다.

## 검증

- Python `tests/test_style_favorites.py`는 저장·해제·재전송·새 인증 Session, Elo·이력 불변, 소유·미제출·입력 검증, 퇴역 유지·조합 폐기와 18→19 Backup·전체 기존 행 보존을 검증합니다.
- Browser `tests/browser_style_favorites.cjs`는 320/390/768/1280px의 별표와 모아보기, Viewer 동기화, Reload·다른 Session, 퇴역 표시, 상태 필터 복구, 같은 이미지 노드·Scroll 보존, 저장 실패·응답 유실 재시도, 늦은 Polling, 저장 중 프로젝트 이동과 폐기를 검증합니다. 퇴역 표시 사례는 응답을 제어하고 실제 삭제는 격리 DB의 API로 수행합니다.
- 운영 검증은 읽기 전용 화면으로 수행하며 기존 그림체에 시험용 좋아요를 남기지 않습니다.
- Python 전체 **531 Passed, 1 Skipped**, JavaScript Syntax·`git diff --check`를 통과했습니다. 격리 Browser는 즐겨찾기·통합 생성·그림체·선별 UX·진화·조합 관리의 6개 시나리오가 통과했습니다.
- 운영 8388을 재기동하고 동일한 네 해상도에서 별표·모아보기·공통 Viewer를 확인했습니다. 제공 자산 8개의 Hash가 소스와 같으며 Browser 변경 요청·오류는 0건입니다. DB의 즐겨찾기는 시험 입력 없이 0개로 시작합니다.
- Schema 19, `quick_check=ok`, Foreign Key 위반 0건입니다. 기존 업무 테이블 32개의 모든 행과 이미지 739장의 Hash가 반영 전후 같습니다. 자동 Migration Backup은 Schema 18·무결성 `ok`를 확인했습니다.
- 배포 전 DB·소스 Backup은 `runtime/style-favorites-deployment-20261115-230714/`, 검증 결과는 `runtime/verification/style-favorites/`에 보관합니다. 이미지 파일은 전후 Hash로 보존을 확인했습니다. 서비스 상태는 `running / healthy`입니다.
