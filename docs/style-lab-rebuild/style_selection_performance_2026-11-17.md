2026-11-17. 세대가 쌓인 프로젝트에서 선별을 늦추던 Checkpoint 조회·SQLite 잠금·후보 조회를 줄였습니다. Elo 산식, 승패, Undo, 선별 Mode, 다중 Prompt의 선택 단위는 유지합니다.

28세대 운영 DB의 일관된 복사본을 사용하고 같은 Docker Image·Windows Bind Mount·읽기 전용 이미지 Mount로 비교했습니다. 서비스 호출은 세 번의 중앙값이며 Browser·외부망 전송·의도된 170 ms 강조와 1,000 ms 결과 공개 시간은 포함하지 않습니다. 격리 DB에서만 Vote·과거 29세대 선별 복원·Checkpoint 생성을 수행했습니다.

| 측정 | 기존 | 개선 |
| --- | ---: | ---: |
| 28세대 결과 목록 Summary | 595 ms | 314 ms |
| 28세대 선별 조회 | 312 ms | 155 ms |
| 28세대 진화 상태 조회 | 4,050 ms | 244 ms |
| 과거 자녀 선별 상태의 Vote | 404 ms | 254 ms |
| 진화 조회와 겹친 Vote, 단건 실험 | 4,374 ms | 262 ms |
| 위 Vote의 BEGIN IMMEDIATE 대기 | 3,964 ms | 0.75 ms |
| 같은 402개 이미지로 두 번째 Checkpoint 저장 | 8,242 ms | 4,648 ms |

1. `style_generation_checkpoints(evaluation_id,generation_number,created_at)` Covering Index를 추가했습니다. 목록에서 큰 `snapshot_json` 뒤의 시각을 읽느라 과거 Snapshot 본문 약 91 MB를 따라가던 I/O를 피합니다. 기존 Checkpoint JSON·Hash·저장 시각은 수정하지 않습니다.

2. 선별·진화 GET은 먼저 `BEGIN` Read Transaction으로 같은 Snapshot을 읽습니다. 새 완료 후보·유실 파일·구버전 선별 상태처럼 저장이 필요할 때는 읽기 연결을 Rollback·종료하고, 새로운 `BEGIN IMMEDIATE`에서 최신 데이터를 다시 읽어 반영합니다. Read Transaction을 직접 Write로 승격하지 않습니다. Vote·Undo 등 변경 명령은 기존 Revision·Operation ID 검증과 원자적 Write Transaction을 유지합니다.

3. 진행 중 진화 계획도 바깥 조회와 같은 연결을 사용합니다. 바깥 Read Lock을 유지한 채 새 연결로 계획을 읽으면, 대기 중 Writer의 Commit과 교착할 수 있기 때문입니다. 조회 연결과 Vote 연결은 명시적으로 종료합니다. SQLite는 기존 `journal_mode=delete`, `synchronous=FULL`을 유지하며 짧은 Read Transaction도 Writer의 Commit을 잠시 지연시킬 수 있습니다.

4. 선별 후보와 Render에 같은 활성 소속 조건을 적용했습니다. 퇴역·취소 Render를 매번 함께 읽지 않고, 준비에 필요한 Prompt Case만 계획별로 한 번 조회합니다. 프로젝트·평가 후보 Index, 삭제 명령 Partial Index, 평가별 Vote·Batch Index도 추가했습니다. 결원 보충의 `include_retired=True`는 계속 퇴역 후보를 포함합니다. 비교할 현재·다음 Pair의 모든 Prompt 파일과 관리 경로는 계속 확인합니다.

5. 같은 프로젝트의 중복 진화 조회를 Promise 하나로 병합합니다. 새 변경 명령 이전의 응답은 기존 Sequence 검증으로 버립니다. 비교 계획의 중첩 순회와 투표 결과의 Candidate별 `find`를 Set·Map 조회로 바꿨습니다. Browser 상태·서버 응답 형식은 유지합니다.

6. 리그 순위 가중치는 정렬과 Binary Search로 기존 공동 순위를 계산합니다. Slot별 최소 비용의 중복 `min()`과 자녀별 Vote 재순회를 제거했습니다. 원본 StyleLab Golden 비교와 동점·Skip·Undo 검증으로 결과가 같은지 확인합니다. 필요한 동점 자녀 Pair 집합은 계속 생성하며 선별 정책을 바꾸지 않습니다.

7. `style_checkpoint_file_hashes`는 파일 경로·크기·mtime/ctime·Device/Inode 식별 정보와 SHA-256만 보관합니다. 파일의 현재 존재·식별 정보는 계속 검사하고, 신규·변경된 파일만 Chunk로 읽습니다. 서버 재시작 뒤에도 Cache를 재사용합니다. Hash 도중 파일이 바뀌면 저장을 Rollback합니다. 기존 이미지 내용이나 Thumbnail Cache 설정은 바꾸지 않습니다.

처음 Cache를 채울 때는 모든 기존 파일의 Hash가 필요합니다. 같은 402개 이미지의 첫 저장은 기존 8.29초·개선 8.40초였고, 두 번째 저장부터 원본 재독을 생략했습니다. 파일 경계·존재·Metadata 검사와 Checkpoint 전체 저장 비용은 남습니다. 불변 Snapshot의 누적 보관 형식도 그대로이므로 장기 DB 저장 공간 증가까지 없애는 변경은 아닙니다.

Schema는 21 → 22입니다. 기존 자동 Migration Backup 이후 Index와 빈 Hash Cache Table을 추가합니다. 프로젝트·평가·후보·이미지·Vote·Undo·기존 Checkpoint의 행을 수정하는 Data Migration은 없습니다.

검증은 실제 SQLite의 Writer 예약 잠금 중 조회 완료, 변경 없는 GET의 무쓰기, 같은 연결에서의 진화 계획 조회, Covering Index 사용, 재시작 후 Hash 재사용, 변경·유실·Hash 중 변경 감지, 기존 Schema 21의 평가·Checkpoint 보존을 포함합니다. Browser에서는 선별·Elo·Undo·Mode·프로젝트 전환·진화 생성/확정/취소와 중복 조회 병합을 확인합니다.

Python 전체는 **596 passed, 1 skipped**이며 기존 Starlette/httpx DeprecationWarning 1건이 있습니다. 선별 UX와 여러 세대의 진화 Browser 검증은 320·390·768·1280px에서 통과했습니다. 변경 JavaScript의 Syntax Check와 `git diff --check`도 통과했습니다.

원시 측정·프로파일·격리 DB·운영 반영 자료는 Git 제외 경로 `runtime/verification/style-selection-performance-20261117/`에 있습니다. `baseline`, `optimized-final`의 측정 DB는 진단용 Vote와 Checkpoint를 포함하므로 운영 복원에 사용하지 않습니다.
