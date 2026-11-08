# 기존 데이터와 API 계약

## 저장 구조

| 경로·객체 | 역할 |
| --- | --- |
| `data/state.json` | Schema 2. Registry, 활성·퇴역 조합, 투표, 설정, 세대 상태 |
| `state.json.bak` | 기동 시 정상적으로 읽은 State의 직전 사본 |
| `data/images/*.png` | 실제 생성물. ComfyUI Prompt Metadata가 남아 있는 원본 |
| `data/thumbs` | 재생성 가능한 Thumbnail Cache |
| `data/workflow.json` | 선택적인 API Workflow. 있으면 내장 Workflow보다 우선 |
| `data/lora_warnings.log` | 적용 안내·오류의 상세 기록 |
| `data/web-server` | Web 인증·운영 정보. 프로젝트 Export와 분리 |

`core.load_state`는 JSON 검증·구버전 Upgrade·정상 원본 Backup을 수행합니다. `core.write_state`는 임시 파일 작성 → Flush/fsync → `os.replace`로 저장하고 Windows 파일 잠금 시 재시도합니다. 읽기만 하려는 조사 도구가 `Engine`을 생성하면 Backup 등 부수 효과가 생길 수 있으므로 JSON을 직접 읽어야 합니다.

## 기존 주요 Entity

| Entity | 주요 Field와 의미 |
| --- | --- |
| Artist Registry | `tag`, `count`, `arena_matches`, `arena_wins` |
| LoRA Registry | 위 통계, `tag=lora:<파일>`, 개별 범위, Trigger, 후보·Base·호환성 정보, `load_failed`, `load_notice` |
| Combination | `id`, `style`, `elo`, `matches`, `wins`, `placed`, `image_file`, `seed`, `created`, `generation`; 선택적으로 `kept`, `memo`, `excluded` |
| Selection | `generation`, `candidate_ids`, `batch_id`, `parent_ids`, `parent_scores`, `retired`, `log` |
| History | 최신 항목이 앞. `arena`, `place_vote`, `selection_vote`, `selection_skip` 등 종류별 구조가 다름 |
| Placement | 신규 후보가 기존 Ladder에서 찾는 자리와 비교 기록 |
| Tune / Improve | 별개 평가 State Machine. 동일 기능으로 합치지 않음 |
| LoRA History | 세대별 상위 조합의 LoRA 범위·평균·공존 빈도 Snapshot |
| LoRA Loading Notice | 최근 생성의 성분별 Key 수·오류·Log 절단 여부·사용 파일 목록 |

선택적 Field와 실제 관측 구조는 [자동 추출 근거](12_source_inventory_and_contract_evidence.md)에 있습니다. `free_results`, `merged`, `tune` 등은 기본 State 또는 특정 작업에서 추가될 수 있습니다. Field 존재만으로 기능 사용 여부를 단정하지 않습니다.

## 표현 규칙

기존 `style`은 `1.2::artist:rurudo ::, 0.7::lora:example.safetensors ::` 같은 문자열입니다. 작가·LoRA가 같은 문자열에 들어가지만 LoRA는 Prompt 글자가 아니라 Workflow Loader의 가중치입니다. 새 구현은 구조화된 Component 목록을 기본 저장소로 삼고, 기존 문자열은 Import/Export 형식으로 지원하는 편이 안전합니다.

작가 점수는 별도 영구 점수가 아닙니다. `core.artist_scores(active + retired)`로 계산합니다. 활성 조합만 이관하면 퇴역 조합이 제공하던 점수 근거를 잃습니다.

## 기존 API의 의미

Bridge 응답은 `{ "ok": true, "data": ... }` 또는 `{ "ok": false, "error": ... }`입니다. 세부 경로·Handler는 12번 문서의 자동 생성 API 표와 Bridge 원문을 기준으로 합니다.

| 그룹 | 대표 요청 |
| --- | --- |
| 조회 | `GET /api/status?since=...`, `/api/match`, `/api/combos`, `/api/artists`, `/api/loras` |
| 투표 | `POST /api/vote {side}`, `/api/skip`, `/api/undo` |
| 생성 | `/api/generate/random`, `/api/generate/custom`, `/api/generate/free` |
| 진화 | `/api/evolution/start`, `/api/evolution/finish`, `/api/evolution/cancel` |
| 목록 관리 | `/api/combos/keep`, `/memo`, `/delete`, `/revive`, `/elo`, `/purge` |
| 설정 | `/api/settings {changes}`, `/api/connection`, `/api/job/stop` |
| 후순위 | `/api/combos/merge`, `/api/merge/*`, `/api/tune/*`, `/api/improve/*` |
| 데이터 | Web의 `/api/data/export`, `/api/data/import`는 파일 다운로드·업로드 |
| 적용 진단 | `GET /api/loras/loading` |

Web은 로그인 Session과 CSRF를 추가하고 이미지도 인증합니다. 투표·Skip에는 `expected_match={kind,a,b}`를 보내 현재 대결과 다르면 409로 거부합니다. 다만 별도 Match Revision은 없으므로 새 설계에서는 같은 Pair가 다시 나타나는 경우까지 식별할 Token을 도입합니다.

## Export와 복원의 경계

기존 Engine Export는 `state.json`과 `images/*.png`를 ZIP에 넣습니다. Workflow·코드·모델·인증은 포함하지 않습니다. Import는 프로젝트 추가가 아니라 현재 데이터 전체 교체입니다. 새 프로그램에 이 동작을 그대로 이식하면 프로젝트 분리가 무너집니다.

현재 조사 문서는 전체 사용자 State와 PNG를 복제하지 않았습니다. 실제 데이터까지 이관하려면 별도의 Backup을 읽어 명시적 Migration으로 가져와야 합니다. 문서의 13번 점수 Seed는 그 Backup을 대신하지 않습니다.
