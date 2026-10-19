# 영상 Thumbnail·저용량 미리보기·Cache 설계

작성일: 2026-10-19

상태: **기본 범위를 구현했습니다.** 설계문서를 `5cc6b36`으로 먼저 커밋한 뒤 개발했습니다. 현재 구현·설정·실측과 검증 범위는 13장에 기록합니다. 실제 Android/iOS 기기 검증은 남아 있습니다.

설계 당시 코드 기준 Commit: `d7a4087` (`feat: collapse request prompts and tag paths`).

추가 합의: 신규 하위 요청의 영상 생성 완료와 서버 기동 시 미변환 영상 탐색도 자동 변환의 접수 경로에 포함합니다. 기동 때 정리만 하고 클릭을 기다리던 초기 설계는 아래 내용으로 대체합니다. Thread 수명·실패 재시도 수치는 구현 제안입니다.

최종 보완: **저용량 영상은 모든 원본 영상을 대상으로 개수 제한 없이 보관**하고, **영상 정지 Thumbnail만 기존 이미지와 같은 개수 설정**을 사용합니다. 미리보기는 우선 12fps로 시작하며, 출력 설정 변경만으로 완성된 영상을 재변환하지 않습니다. 사용자 클릭에 대한 대기·변환 중·실패 안내는 Toast로 제공합니다. 이 정책은 초기의 영상 Entry LRU·Profile 변경 자동 재변환 제안을 대체합니다.

## 1. 목적과 확정한 방향

결과물 탭에서 영상 내용을 확인할 때 수십 MB의 원본 대신 작은 미리보기를 전송합니다.

- 목록에서는 영상의 정지 Thumbnail을 표시하고, 클릭하면 저용량 영상을 Dialog에서 재생합니다.
- 기존 `열기` 버튼은 원본 재생용으로 유지합니다.
- 저용량 영상은 **신규 영상 생성 완료·기동 시 미변환 영상 채우기·사용자 미리보기 요청**에서 공통 Queue에 접수합니다. 먼저 생성된 구간부터 재생하는 것을 목표로 합니다.
- **팝업을 닫거나 다음 영상으로 넘어가도 Queue에 접수한 변환은 끝까지 처리합니다.** 재생 연결 종료는 변환 취소가 아닙니다.
- 완성된 파생 파일은 디스크 Cache에 보관하여 다음 접속과 서버 재기동 후에도 재사용합니다.
- 저용량 영상은 모든 원본을 대상으로 보관하며 개수·총 bytes·TTL에 따른 자동 퇴출을 하지 않습니다. 영상 정지 Thumbnail은 별도 LRU로 관리하고 기존 `thumbnail_cache_max_entries` 값을 동일하게 사용합니다.
- 기존 미리보기는 fps·해상도·Codec 등의 설정 변경만으로 삭제하거나 재변환하지 않습니다. 전체 삭제·재변환은 사용자의 명시적 요청으로 수행합니다.
- 여러 Worker thread가 Queue를 처리하고, 각 Worker가 FFmpeg 프로세스를 실행합니다. Worker 수와 Encoder thread 수는 `config.toml`에서 제어합니다.
- 원본 수동 삭제로 남은 Cache는 서버 기동 시 백그라운드로 정리합니다.
- 기동 정리 뒤에는 사용 가능한 모든 원본 영상 중 미변환 영상을 백그라운드로 채웁니다. 이미 완성된 미리보기는 설정 차이를 비교하지 않고 재사용합니다.
- 부분 변환 상태를 DB에 저장하거나 중간부터 이어서 변환하지 않습니다.

최초의 추가 이미지 파일 미생성·메모리 Cache 제안은 이후 논의한 **별도 Cache 폴더 보관과 기동 시 정리** 방향으로 변경합니다. 원본 결과물 폴더에는 파생 파일을 추가하지 않고 Cache 전용 폴더에 영상 정지 Thumbnail과 저용량 영상을 둡니다. 기존 일반 이미지 Thumbnail의 메모리 Cache 정책은 이번 범위에서 변경하지 않습니다.

## 2. 현재 구현과 연결 지점

| 위치 | 현재 동작과 변경 지점 |
|---|---|
| `web/app.js`의 `renderOutputsList()` | 영상은 `영상 · 열기로 재생` 문구만 표시합니다. Thumbnail과 재생 Dialog를 연결합니다. |
| `web/index.html`, `web/app.css` | 기존 Grid·Dialog 기반에 모바일 영상 Dialog와 Focus 복귀를 추가합니다. |
| `home_server/application.py`의 `output_preview()` | 현재 이미지 확장자만 허용합니다. 영상의 정지 WebP 제공을 연결합니다. |
| `home_server/thumbnail_cache.py` | 최대 384px WebP bytes의 개수 제한 메모리 LRU와 중복 생성 공유, 최대 두 건 변환을 제공합니다. 일반 이미지 경로는 유지합니다. |
| `home_server/output_catalog.py` | 현재 경로·`output_id`·가용성·삭제 표시를 Cache 검증과 정리에 재사용합니다. |
| `home_server/configuration.py` | `[outputs]`에 영상 Worker·변환·Cache 설정을 추가합니다. |
| `HomeServer`, FastAPI Lifespan | 시작 시 Catalog 동기화 후 Cache Manager·Worker·정리/채우기를 시작하고 종료 때 회수합니다. |
| `_refresh_requests()`, `Database.apply_request_states()` | 실제 반영된 완료 상태를 반환할 때 Catalog 등록도 끝납니다. Commit 후 완료된 하위 요청의 영상별 접수를 연결합니다. |
| `Dockerfile` | FFmpeg 설치 단계가 없습니다. FFmpeg·ffprobe와 필요한 Encoder 지원을 추가·확인합니다. |
| `compose.yaml`, `.gitignore` | 쓰기 가능한 영속 `runtime/` Mount가 있고 Git 추적에서 제외됩니다. 이 아래에 Cache를 두므로 추가 Mount는 필요하지 않습니다. |

현재 영상 확장자는 `.mp4`, `.webm`, `.mkv`, `.mov`입니다. 확장자와 내부 Codec 지원은 구분하고 실제 decoding 실패도 처리합니다. 기존 DB 기반 목록 정렬·필터·Pagination을 유지하며 일반 목록 조회에서 전체 FS 탐색을 다시 하지 않습니다.

## 3. 화면 동작

1. 목록은 Lazy loading으로 정지 Thumbnail만 요청합니다. 목록 진입이나 정지 Frame 추출 때문에 영상 전체 변환을 시작하지 않습니다.
2. Thumbnail에 재생 아이콘과 접근성 이름을 표시합니다. 클릭하면 Dialog를 열고 미리보기를 요청합니다.
3. 완료 파일이 있으면 바로 재생합니다. 없으면 클릭에 대한 `미리보기 변환 대기 중입니다.` 또는 `미리보기 변환 중입니다.` Toast를 표시하고 첫 Fragment가 준비되면 재생을 시도합니다.
4. 닫기·Escape·미리보기 바깥 영역 클릭/터치·다른 영상 선택·탭 이동 시 기존 Video element의 재생·다운로드 연결만 해제합니다. Queue와 진행 중 변환은 유지합니다. Dialog 내부 여백·영상 조작·Toast Action은 바깥 클릭으로 취급하지 않고 내부에서 시작한 Drag가 바깥에서 끝나도 닫지 않습니다.
5. 다시 열면 기존 Task나 완성된 Cache를 재사용합니다.

- Dialog에 재생 제어·닫기·`원본 열기`를 제공합니다. 모바일 자동 재생이 제한되면 재생 버튼을 제공합니다.
- 음성이 있는 원본에는 저용량 음성을 포함하는 안을 제안합니다. 자동 재생 시 음소거와 수동 재생 정책은 실제 모바일에서 확인합니다.
- 다중 선택 Checkbox와 기존 이동·삭제 버튼 클릭이 미리보기를 열지 않게 합니다.
- 닫을 때 원래 Thumbnail로 Focus를 돌리고 목록 페이지·필터·스크롤 위치를 유지합니다.
- 늦게 도착한 이전 영상의 상태 응답이 새 Dialog를 덮어쓰지 않도록 조회 Revision을 구분합니다.
- 대기·변환 중·Queue 포화·실패 안내는 클릭에 대한 Toast로 제공합니다. 카드의 상태 Badge나 별도의 실패 화면을 추가하지 않습니다. 자동 재시도 대기는 `미리보기 변환에 실패해 재시도를 기다리고 있습니다.`, 최종 실패는 `미리보기 변환에 실패했습니다.`처럼 구분합니다. 최종 실패 Toast에는 명시적 재시도 Action을 제공할 수 있습니다.
- 백그라운드 변환마다 Toast를 띄우거나 상태 Polling 때 같은 Toast를 반복하지 않습니다. 현재 사용자가 연 영상의 상태 전이만 안내하고, 다른 영상으로 이동하거나 닫은 뒤 이전 작업의 Toast를 띄우지 않습니다. 실패 때문에 원본 재생이나 작업 성공 상태를 바꾸지 않습니다.

## 4. 변환 Profile과 용량

**Frame rate는 우선 최대 12fps로 구현하여 실제 결과를 보고 판단하기로 했습니다.** 나머지 수치는 초기 제안이며 Benchmark와 화질 확인 후 기본값을 확정합니다. 이후 설정을 바꾸더라도 이미 완성된 미리보기에는 소급 적용하지 않습니다.

| 항목 | 제안 |
|---|---|
| 정지 Thumbnail | 첫 표시 Frame, 긴 변 최대 384px, WebP quality 75 |
| 미리보기 크기 | 긴 변 최대 640px, 비율 유지, 원본보다 확대하지 않음 |
| Frame rate | 원본보다 늘리지 않고 최대 12fps로 시작, 사용자 결과 확인 후 조정 가능 |
| 영상 | H.264, `yuv420p`, 빠른 CPU Preset 우선 검토 |
| 영상 bitrate | 목표 300kbps, 품질·Peak 제한은 실측 후 결정 |
| 음성 | 원본에 있을 때 AAC 48kbps, 없으면 새 Track을 만들지 않음 |
| 길이 | 전체 길이 유지, 임의 앞부분 자르기·배속 없음 |
| 출력 | fragmented MP4, 영상 시간 기준 약 0.5~1초 Fragment와 대응하는 Keyframe 간격 |

회전 Metadata를 반영하고 Encoder가 요구하는 짝수 크기로 보정합니다. 정지 Thumbnail은 별도 짧은 추출로 만들고 전체 영상 변환을 기다리지 않습니다.

근사식은 `길이(초) × (영상 kbps + 음성 kbps) / 8 / 1000 = MB`입니다. 아래는 300+48kbps 가정의 **계산값이며 실측값이나 엄격한 크기 상한이 아닙니다.** MP4 부가 정보·Bitrate 변동에 따라 달라집니다.

| 길이/개수 | 예상 압축 데이터 용량 |
|---|---|
| 5초 | 약 0.22MB |
| 10초 | 약 0.44MB |
| 30초 | 약 1.31MB |
| 10초 영상 1,000개 | 약 440MB |

변환 속도가 재생보다 빠르거나 브라우저가 미리 Buffering하면 닫기 전에 전체 변환·다운로드가 끝날 수 있습니다. 이미 전송한 bytes는 회수할 수 없으며, 시청한 초만큼만 정확히 전송하는 계약은 아닙니다.

## 5. Queue와 동시 접속

서버 Lifespan에 속한 단일 `VideoPreviewCache` Manager를 제안합니다. HTTP 요청이나 Dialog 수명에 종속시키지 않습니다.

- Task Key는 원본 식별자·원본 파일 버전입니다. 출력 설정은 Key에 넣지 않습니다. 같은 Key의 대기/변환 중 요청은 하나의 Task를 공유하고 Session마다 별도 변환하지 않습니다. 생성 설정은 최초 접수 시 Snapshot으로 고정합니다.
- 서로 다른 Key는 우선순위 Queue에서 여러 Worker가 처리합니다. 기본 순서는 사용자 클릭, 신규 생성 완료, 기동 채우기이며 같은 등급은 FIFO입니다. 오래 대기한 낮은 등급도 처리되도록 Aging을 적용하는 안을 제안합니다. 화면을 닫아도 접수한 대기 작업을 제거하지 않습니다.
- 기동 후보가 이미 대기 중일 때 사용자가 클릭하면 기존 Task의 우선순위만 올립니다. 진행 중 FFmpeg를 선점하거나 같은 Key를 다시 실행하지 않습니다.
- Worker별로 FFmpeg 한 개를 실행합니다. Lock을 잡은 채 decoding·encoding·Streaming을 하지 않습니다.
- 같은 영상의 정지 Thumbnail 추출도 중복 요청을 공유하지만 전체 영상 변환과 Task 종류는 구분합니다.
- 일반 이미지 Thumbnail 자원 제한과 영상 변환 자원 제한을 분리합니다. 영상 정지 Thumbnail과 전체 변환 사이의 배분은 목록 지연 측정 후 정합니다.
- Queue에 상한을 두고 사용자 요청이 가득 찬 Queue에 새로 접수되지 못하면 429와 재시도 안내를 반환합니다. 자동 접수는 공간이 생길 때 이어서 시도하며 조용히 버리지 않습니다. 이미 접수한 작업은 임의 퇴출하지 않습니다.
- 전용 Worker를 사용하고 Event Loop·일반 API Thread pool에서 긴 변환을 동기적으로 기다리지 않습니다.

일시 상태는 `queued → converting → ready`이며, 재시도 가능한 실패는 `retry_wait → queued`, 최종 실패는 `failed`입니다. Manager가 실행 상태를 관리하고 작업 이력 DB에 새 요청이나 부분 변환 상태를 저장하지 않습니다. 완료 Cache는 디스크에서 재발견합니다. 재시작 때 메모리 Queue를 복구하지 않고 기동 채우기에서 미완료 원본을 다시 발견합니다. 실패 횟수·최종 실패 여부의 작은 Metadata는 10장의 정책으로 보존하며 부분 영상 복구 정보와 구분합니다.

기본 배포는 단일 앱 프로세스와 여러 Worker thread입니다. ASGI 프로세스 여러 개나 서버 여러 대가 같은 Cache를 공유하려면 Queue 공유와 프로세스 간 중복 방지를 별도로 설계해야 합니다. 프로세스 내부 Lock만으로 전역 동시 실행 제한을 보장하지 않습니다.

### 5.1. 신규 생성 완료에서 자동 접수

- 상위 작업 전체 완료를 기다리지 않고 **하위 요청 하나가 완료될 때마다**, 그 요청의 실제 영상 결과물 각각을 접수합니다. 한 요청에 영상이 여러 개면 파일별 Task를 만듭니다.
- 현재 `_refresh_requests()`가 `apply_request_states()`에서 반환받은 실제 완료 전이만 사용합니다. DB Transaction과 Catalog 등록이 Commit된 뒤 최신 `output_id`를 조회해 접수하고, DB Lock 안에서 FFmpeg를 실행하지 않습니다.
- 정상/재시작 후 완료 감지에 동일한 접수 함수를 사용합니다. 이미지 결과물은 영상 Queue에 넣지 않습니다. 후속 완료 진입점을 추가하면 같은 Commit 후 접수 경로를 연결합니다.
- 접수 실패가 원본 생성 성공을 실패로 되돌리거나 다음 ComfyUI 상태 감시를 막지 않아야 합니다.
- Queue 포화 시 상태 감시를 빈자리 대기로 막지 않습니다. Manager에 재탐색 필요 신호를 합쳐 남기고 공간 확보 시 Catalog를 페이지 단위로 재확인합니다. 영상마다 무제한 Thread/Task를 만들지 않으며 Cache Hit·진행 중 Key·재시도 제외 Key는 건너뜁니다. Commit 직후 서버가 종료된 누락은 기동 채우기에서 회수합니다.

### 5.2. 기동 시 미변환 영상 채우기

1. 기존 Catalog 동기화와 이전 Cache 정리를 수행한 뒤 별도 Producer가 현재 사용 가능한 영상을 최신 순으로 페이지 조회합니다. 원본 트리를 다시 재귀 탐색하거나 전체 후보를 한꺼번에 RAM에 올리지 않습니다.
2. 파일을 읽기/접수하기 직전에 현재 원본 버전·완료 Cache·기존 Task·실패 제한을 재확인합니다. 새 요청이 이미 채웠거나 Queue에 넣은 항목은 재사용합니다.
3. Cache가 없는 현재 버전의 후보를 공통 Queue의 낮은 우선순위로 넣습니다. Queue가 가득 차면 중단 가능한 대기로 기다리다 이어서 접수합니다.
4. 모든 후보의 접수/건너뛰기 처리가 끝나면 Producer는 종료합니다. Queue 용량은 동시 대기량만 제한하며 전체 미변환 영상의 탐색 범위를 제한하지 않습니다. Producer 종료는 모든 변환의 완료를 뜻하지 않으며 접수된 Task는 Worker가 계속 처리합니다.

**저용량 영상에는 보관 개수 제한을 두지 않으므로 모든 미변환 원본이 대상입니다.** 완료된 영상은 자동 퇴출하지 않습니다. 정지 Thumbnail의 LRU 한도나 퇴출 여부가 저용량 영상의 생성·유지·재생을 제한하지 않게 합니다. Thumbnail이 없어도 완료된 저용량 영상은 그대로 재생하고 필요한 정지 Thumbnail만 다시 추출합니다.

기동 시 완료 여부는 최종 파일·완료 Metadata의 존재와 최소 구조 확인으로 판단합니다. 현재 인코딩 설정과 과거 설정을 대조하거나 기존 미리보기 전체를 ffprobe/decoding/Hash 검사하지 않습니다. 원본 실제 삭제·교체 검사는 별도 원본 정합성 확인이며 출력 설정 변경과 구분합니다.

### 5.3. Thread와 Scheduler의 종료 시점

| 실행 주체 | 수명과 종료 시점 |
|---|---|
| 기동 정리/채우기 Producer thread | 한 번 정리·전체 후보 탐색·접수를 마치면 종료합니다. Queue 포화 시에는 중단 가능한 대기로 기다리며 누락 없이 이어갑니다. 서버 종료 Stop 신호에는 접수를 멈춥니다. |
| 영상 변환 Worker thread | 서버 Lifespan 동안 유지합니다. Queue가 비면 Condition/Event로 대기하며 새 영상 완료·클릭·재시도 작업을 받습니다. Queue가 비었다는 이유로 종료하지 않습니다. |
| 재시도/재탐색 Scheduler | 서버 Lifespan 동안 유지합니다. 다음 재시도 시각·빈자리·재탐색 신호·종료 신호를 기다리며 Busy polling하지 않습니다. 별도 Thread 또는 비동기 Task로 구현할 수 있습니다. |
| Worker가 실행한 FFmpeg 프로세스 | 영상 한 건의 성공/실패/Timeout/원본 무효화 때 종료·회수합니다. 재시도 시 새 프로세스를 실행합니다. |

서버 종료 순서는 신규 접수 차단 → Producer/Scheduler Stop → 대기 중 Task 접수 중지 → 실행 중 변환의 제한 시간 대기 → 남은 FFmpeg 종료·회수 → Worker join입니다. 재시작 때 대기/중단 영상은 기동 채우기로 다시 찾습니다. Python thread를 강제로 죽이는 방식은 사용하지 않습니다.

## 6. `config.toml` 설정안

Worker 수와 Encoder thread 수를 설정으로 제어하고 Frame rate를 최대 12fps로 시작합니다. 아래 설정은 현재 Parser와 `config.toml`에 반영했으며 기본값도 예시와 같습니다. 완료본에는 출력 설정 변경을 소급 적용하지 않습니다.

```toml
[outputs]
# 기존 이미지 Thumbnail 설정은 유지합니다.
thumbnail_cache_max_entries = 10000
thumbnail_cache_warmup_enabled = true

# 장비별 변환 병렬도를 조정합니다.
video_preview_worker_count = 4
video_preview_encoder_threads = 2

# 신규 생성 완료와 기동 시 누락분을 자동으로 접수합니다.
video_preview_on_completion_enabled = true
video_preview_warmup_enabled = true

# 최초 실행을 포함한 시도 상한과 지연 재시도 설정 제안입니다.
video_preview_retry_max_attempts = 3
video_preview_retry_initial_delay_seconds = 10
video_preview_retry_max_delay_seconds = 60

# 초기 Profile과 Queue 운영 설정 제안입니다. 저용량 영상 보관 개수 제한은 없습니다.
video_preview_queue_max_entries = 256
video_preview_max_dimension = 640
video_preview_frame_rate = 12
video_preview_video_bitrate_kbps = 300
video_preview_audio_bitrate_kbps = 48
video_preview_timeout_seconds = 300
video_preview_shutdown_timeout_seconds = 10
```

- `*_enabled`는 `bool`, 나머지는 `bool`을 제외한 양의 정수로 검증합니다. 자동 접수 두 설정은 기본 On이고 최대 재시도 지연은 초기 지연보다 작지 않아야 합니다. 변경은 서버 재시작 시 적용합니다.
- Encoder thread 수는 프로세스 전체 CPU 수의 엄격한 상한이 아닙니다. Decoder·Filter 병렬도도 구현에서 제한·측정합니다.
- Worker가 늘면 원본 decoding 메모리·IO도 증가합니다. 압축 Cache 용량으로 변환 중 RAM을 추정하지 않습니다.
- `thumbnail_cache_max_entries`를 일반 이미지 메모리 LRU와 영상 정지 Thumbnail 디스크 LRU의 동일한 개수 상한으로 사용합니다. 현재 예시는 각각 최대 10,000개이며 하나의 합산 Pool로 바꾸지 않습니다. 별도 영상 Thumbnail 개수 설정을 추가하지 않습니다.
- 저용량 영상은 개수 제한·LRU·총 bytes 제한·TTL을 적용하지 않습니다. 초기 제안의 `video_preview_cache_max_entries`는 제거합니다. Thumbnail 퇴출 시 저용량 영상이나 원본 Metadata를 함께 삭제하지 않습니다.
- Worker·재시도 같은 운영 설정뿐 아니라 fps·해상도 등의 출력 설정 변경도 완료 파일을 재변환하는 조건이 아닙니다. 새로 시작하는 변환에만 현재 설정을 적용합니다. `video_preview_frame_rate = 12`로 시작합니다.
- 기동 시 정리와 영상 채우기는 별도 단계입니다. 정리는 항상 수행하고 영상 채우기는 전용 `video_preview_warmup_enabled`로 제어합니다. 기존 이미지 Warmup 설정과 독립적입니다.

## 7. 디스크 저장과 완료 확정

기존 영속 Mount 아래 `runtime/cache/media/`를 제안합니다. 원본 결과물 폴더·Workflow·Git에는 저장하지 않습니다.

```text
runtime/cache/media/
  previews/
    <source_identifier>/
      source.json
      preview.mp4
      preview.partial.mp4    # 변환 중에만 존재
  thumbnails/
    <source_identifier>/
      source.json
      poster.webp
```

- 저장 식별자는 서버가 원본 식별자·원본 파일 버전에서 생성합니다. 출력 설정을 경로/Key에 넣지 않고 사용자 입력 경로를 파일명으로 직접 사용하지 않습니다.
- 미리보기의 `source.json`에는 `output_id`, 관리 상대 경로, `mtime_ns`, 원본 크기, 생성 당시 인코딩 설정 Snapshot과 완료 정보를 기록합니다. Snapshot은 진단용이며 현재 설정과 비교해 재변환하지 않습니다. Thumbnail Metadata는 독립적으로 원본 연결과 최근 사용 시각을 기록합니다. 절대 경로·Prompt·인증 정보는 저장할 필요가 없습니다.
- 기본 연결은 `output_id`이고 현재 원본 위치는 DB의 최신 `relative_path`로 조회합니다. 생성 당시 `original_relative_path`로 파일을 찾지 않습니다.
- Codec·해상도·fps·음성·인코딩 설정이 바뀌어도 완성된 미리보기는 재사용합니다. 사용자가 명시적으로 전체 삭제·재변환을 요청할 때만 기존 완료본을 새 설정으로 교체하는 운영 작업을 수행합니다. 자동 일괄 Migration이나 관리 화면의 전체 재변환 기능은 이번 범위에 추가하지 않습니다.
- 수정 시각과 크기가 모두 동일한 외부 교체는 감지하지 못할 수 있습니다. 초기 설계에 전체 원본 Hash 계산은 포함하지 않습니다.
- 변환 중에는 임시 파일에 bytes를 누적합니다. 정상 종료·출력 확인·현재 원본 버전 재검사 후 같은 파일시스템에서 `preview.mp4`로 Atomic rename합니다. Metadata도 임시 파일과 rename으로 갱신합니다.
- Thumbnail과 저용량 영상은 독립적으로 완료/부재 상태를 가질 수 있습니다. Thumbnail 존재 여부로 영상 완료를 판단하지 않고 최종 영상 파일과 유효한 완료 Metadata를 사용합니다.
- 파일 확정과 Metadata 기록 사이에 종료된 경우도 기동 시 검증·정리합니다. 미완성 파일은 정상 Cache Hit로 제공하지 않습니다.
- 실패 시 임시 파일을 제거하고 상태·원인 분류·시도 횟수·다음 재시도 시각 또는 최종 실패 여부를 기록합니다. 10장의 상한 있는 자동 재시도와 명시적 재시도를 적용합니다.
- Cache에 decoded Bitmap이나 원본 bytes를 보관하지 않고 완료 영상 전체를 사용자마다 RAM에 복제하지 않습니다.
- LRU는 정지 Thumbnail에만 적용하며 추출/전송 중인 Thumbnail은 건너뛰고 사용 종료 후 재검사합니다. 활성 Thumbnail 때문에 제한을 일시 초과할 수 있습니다. 퇴출 대상은 `thumbnails/` 아래 해당 파생 파일뿐이며 `previews/`는 건드리지 않습니다. Thumbnail 최근 사용 시각은 Chunk마다 쓰지 않고 묶어서 저장하는 안을 검토합니다.

## 8. 변환 중 재생과 API 제안

아래 이름은 연결 책임을 구체화한 제안이며 기존 API 계약이 아닙니다.

| 용도 | API 제안 | 계약 |
|---|---|---|
| 정지 Thumbnail | 기존 `GET /api/outputs/preview/{relative_path}` 확장 | 영상도 WebP를 반환하고 기존 이미지 계약은 유지합니다. |
| 접수/재사용 | `POST /api/outputs/{output_id}/video-preview` | 원본 검증 후 Cache 또는 공유 Task를 반환합니다. |
| 상태 | `GET /api/outputs/{output_id}/video-preview` | 일시 상태·진행 정보·현재 버전의 재생 URL을 반환합니다. |
| 저용량 재생 | `GET /api/outputs/{output_id}/video-preview/stream` | Cache 버전을 고정해 진행 중 Fragment 또는 완료 파일을 제공합니다. |
| 원본 재생 | 기존 `GET /media/{relative_path}` | 원본 제공 계약을 유지합니다. |

- 모두 기존 Session 인증·관리 Root 경계·삭제 여부·현재 원본 존재와 속성을 확인합니다. Cache ID를 알아도 인증과 경로 검증을 우회할 수 없습니다.
- Manager는 화면 연결과 독립적으로 파일을 끝까지 씁니다. 각 Streaming 요청은 자기 읽기 위치에서 완성된 Fragment를 읽습니다. 느린 사용자 한 명이 FFmpeg 출력 수집·다른 사용자 재생을 막지 않아야 합니다.
- 응답마다 원본 버전을 고정하고 확정 전에도 원본을 재검사합니다. 하나의 응답에 서로 다른 버전의 bytes를 섞지 않습니다.
- 완료 파일은 `video/mp4`, ETag·HTTP Range를 지원합니다. 진행 중 응답은 종료 위치가 고정된 일반 파일 응답과 구분합니다.
- 진행 중 아직 생성되지 않은 구간으로의 탐색은 초기 범위에서 지원하지 않고 완료 후 전체 탐색을 허용합니다.
- 닫기·연결 끊김은 읽기만 중지합니다. 변환 취소 API·시청자 수 기반 중단·부분 변환 이어받기는 만들지 않습니다.

**선행 검증:** H.264/AAC fragmented MP4 직접 점진 재생을 Desktop·Android·iOS에서 확인합니다. Fragment 간격만으로 모바일 재생을 보장하지 않습니다. 초기 Range 요청·첫 Frame 지연·재생 중 종료를 검증하고 필요하면 Media Source Extensions 연결을 검토합니다. Growing file을 기존 `FileResponse`로 주는 것만으로 변환 중 재생이 구현되었다고 판단하지 않습니다.

HLS/DASH·여러 화질 자동 전환·구간별 저장/재개·GPU Encoder 자동 선택은 기본 범위에서 제외합니다. 선행 검증으로 재생 방식이 바뀌면 이 문서의 계약부터 갱신합니다.

## 9. 이동·삭제·변경과 기동 시 정리

| 상황 | 처리 원칙 |
|---|---|
| 앱 내 이동 | DB의 최신 현재 경로를 따릅니다. 같은 `output_id`·파일 버전이면 Cache를 재사용하고 참조를 갱신합니다. |
| 변환 중 이동 | 시작 전/확정 전 최신 경로와 버전을 확인합니다. OS의 열린 파일 이동 제약으로 이동 실패 시 기존 API 실패 정책을 유지하고 불일치 Cache를 확정하지 않습니다. |
| 원본 실제 삭제 | Thumbnail·미리보기·대기 작업을 무효화합니다. 원본 소멸 시 실행 중 변환도 중지할 수 있으며 화면 닫기에 따른 취소와 구분합니다. |
| 이력만 삭제, 원본 유지 | 작업 연결 제거만으로 Cache를 지우지 않고 실제 원본 가용성을 기준으로 합니다. |
| 실행 중 수동 삭제 | 다음 접근에서 제공을 막고 정리합니다. 수동 Catalog 동기화 후에도 백그라운드 정리를 요청합니다. |
| 외부 변경 | 원본 수정 시각·크기가 바뀌어 실제 파일이 교체되면 오래된 파생 파일을 무효화합니다. 출력 설정만 바뀐 경우와 구분합니다. |
| 인코딩 설정 변경 | 기존 완료 미리보기는 유지하고 신규 변환에만 새 설정을 적용합니다. 기동 때 설정 차이를 검사해 삭제/재생성하지 않습니다. |
| 외부 이동 | 기존 Catalog의 식별 정책을 따릅니다. 새 `output_id`로 등록되면 새 Cache를 만들며 내용 Hash로 추적하지 않습니다. |
| Thumbnail LRU 퇴출/수동 삭제 | 정지 Thumbnail만 필요할 때 다시 생성하며 완료 영상은 유지합니다. |
| 저용량 영상 수동 삭제 | 원본·DB 이력에 영향 없이 기동 채우기 또는 다음 미리보기 요청에서 재생성합니다. |
| 사용자가 전체 삭제·재변환 요청 | 명시적 운영 작업으로 새 설정을 적용합니다. 기동 때 자동으로 수행하지 않습니다. |

기동 시 순서:

1. 기존 원본 Catalog 동기화를 마친 뒤 Lifespan에서 Cache 정리를 백그라운드로 시작합니다. 추가 전체 원본 탐색은 하지 않습니다.
2. 이전 실행의 임시 파일·불완전 Metadata·잘못된 Entry를 정리합니다.
3. 각 Entry의 `output_id`를 DB의 최신 경로에 연결하고 실제 원본 존재·버전을 확인합니다.
4. 삭제/부재 원본·실제 교체된 원본의 불필요한 파생 파일을 정리합니다. 두 저장 영역의 해당 Thumbnail과 저용량 영상을 모두 제거하되 인코딩 설정이 다르다는 이유로 삭제하지 않습니다.
5. 정지 Thumbnail에만 개수 제한을 적용하고 처리·보류·실패 개수를 기록합니다. 정리 자체는 변환하지 않고, 이후 5.2장의 기동 채우기가 전체 미변환 영상을 접수합니다.

- 서비스 준비 완료는 새 Cache 정리를 기다리지 않습니다. **기존 Catalog 시작 동기화는 현재 동작대로 완료를 기다리므로 전체 기동이 비동기화되는 것은 아닙니다.**
- 실제 삭제 직전 원본·최신 Entry·실행 중 Task를 재검사합니다. 이번 실행에서 새로 만든 임시 파일을 찌꺼기로 삭제하지 않습니다.
- 원본 Root 마운트·권한·IO 오류는 실제 파일 부재와 구분합니다. 접근이 불확실하면 삭제를 보류합니다. Catalog의 부재 표시만으로 일괄 삭제하지 않습니다.
- 삭제는 검증된 Cache Root 안에서만 수행하고 symlink/junction을 따라 다른 폴더를 삭제하지 않습니다.
- Cache 정리 때문에 `output_files.is_deleted`를 세우거나 생성 이력을 지우지 않습니다. 실제 원본 상태는 기존 Catalog 계약으로 관리합니다.
- 실행 중 정리는 Cache 접근과 수동 동기화에서 연결합니다. 별도 주기적 전체 정리 Schedule은 후속 필요성을 보고 정합니다.

## 10. 종료·실패 정책

- 정상 종료 시 신규 접수를 막고 Worker에 종료를 알립니다. 실행 중 작업은 제한 시간 안에서 회수하고 초과 시 자식 FFmpeg를 종료합니다. 대기 Queue 전체 소진을 무제한 기다리지 않습니다.
- 앱 종료·원본 무효화·변환 Timeout·IO 오류는 끝까지 완료 원칙의 예외입니다. 사용자 화면 닫기는 예외가 아닙니다.
- 강제 종료 찌꺼기는 다음 기동에서 제거합니다. Queue·부분 구간·진행률을 DB에 복구 저장하지 않습니다.
- 디스크 부족·Codec/Encoder 부재는 재시도 불가 또는 환경 복구 대기로 분류합니다. 원본·작업 성공 상태를 보존하고 자동으로 대용량 원본을 재생하지 않습니다.
- Worker 실패가 다음 Queue 처리를 막지 않도록 Task 등록·Handle·임시 파일을 정리합니다.

### 10.1. 실패 후 Queue 재등록

즉시 재등록하는 무한 반복 대신 **오류 분류와 상한을 둔 지연 재시도**를 제안합니다.

| 실패 종류 | 자동 처리 |
|---|---|
| 일시적 파일 잠금·원본 접근 지연·일시적 IO·설정된 변환 Timeout | 원본이 유효하면 지연 후 재시도합니다. Timeout도 횟수 상한을 적용합니다. |
| 영상 손상·지원하지 않는 Codec·잘못된 Encoder 옵션 | 자동 재시도하지 않고 최종 실패로 남깁니다. |
| FFmpeg 부재·권한 부족·디스크 부족 | 같은 환경에서 반복 실행하지 않고 환경 복구 후 명시적 재시도를 기다립니다. |
| 원본 실제 삭제·삭제 표시 | Task를 무효화하고 재등록하지 않습니다. |
| 서버 종료로 인한 중단 | 변환 실패 횟수에 넣지 않고 다음 기동 채우기에서 새로 처리합니다. |
| 분류되지 않은 프로세스 오류 | 보수적으로 상한 있는 지연 재시도를 적용하고 최종 실패를 기록합니다. |

- 초기 제안은 **최초 1회 + 자동 재시도 최대 2회, 총 3회**입니다. 예시 설정의 지연은 10초, 20초이며 `min(초기 지연 × 2^(재시도 순번-1), 최대 지연)`을 사용합니다. 동시 실패가 몰리지 않게 작은 Jitter를 적용할 수 있습니다.
- 실패 후 FFmpeg·임시 파일을 회수하고 Worker를 반환합니다. Worker가 재시도 시간을 `sleep`하며 Slot을 점유하지 않고 Scheduler가 예정 시각 이후 공통 Queue에 다시 접수합니다. 재등록은 새로운 시도이며 같은 Key를 동시에 실행하지 않습니다.
- 재시도 시 우선순위와 Queue 한도를 지킵니다. 대기 중 사용자 클릭은 동일 Task를 공유하고 우선순위만 올리며, 클릭 횟수로 Backoff나 시도 상한을 초기화하지 않습니다.
- 미리보기의 `source.json`에 원본 파일 버전별 시도 횟수·오류 분류·다음 시각·최종 실패 여부만 작게 저장합니다. **부분 변환 진행도·Frame 위치·중간 영상 복구 정보는 저장하지 않습니다.**
- 재시작 후에도 같은 버전의 최종 실패는 기동 채우기에서 건너뜁니다. 남은 자동 시도가 있고 예정 시각이 남았으면 해당 시각 이후 접수합니다. 실패 Metadata가 없는 신규 원본은 최초 실행으로 처리합니다.
- 원본 파일이 교체되면 새 Key의 시도 횟수를 사용합니다. 출력 설정 변경만으로 실패 상한을 초기화하지 않습니다. 사용자가 실패 Toast의 명시적 재시도를 누르면 현재 원본 버전의 실패 제한을 재설정하고 현재 설정으로 시도하되 기존 완료본과 진행 중 작업은 다시 변환하지 않습니다.
- 실패 Metadata는 최신 원본 버전당 한 개로 보관합니다. Thumbnail 퇴출로 `previews/` 아래 실패 기록까지 없어져 무한 재시도가 재개되지 않게 합니다.
- 오류 메시지 문자열 하나만으로 영구/일시 실패를 단정하지 않고 종료 코드·발생 단계·OS 오류를 함께 분류합니다. 분류 규칙과 횟수·지연 기본값은 구현 시 검증합니다.

## 11. 성능과 기능 검증

### Benchmark

아래는 설계 당시 측정 계획입니다. 현재 Windows 장비의 실제 변환 시간·압축 크기·메모리 샘플링 결과는 13장에 기록합니다. 다른 장비·영상에 동일한 성능을 보장하지 않습니다.

- 실제 해상도·길이·Codec·음성 유무가 다른 대표 원본을 선택합니다.
- Queue 대기, Probe/원본 확인, 첫 Fragment 생성, 브라우저 첫 재생, 전체 변환 완료, Cache Hit 첫 재생을 각각 측정합니다.
- Worker 1/2/4개와 Encoder thread 수를 비교하여 처리량·개별 지연·CPU·최대 RSS·IO·완성 파일 크기를 기록합니다.
- ComfyUI 생성과 동시 실행 시 간섭, 이미지 Thumbnail·로그인·취소 등 일반 API 지연도 확인합니다.
- Task/Cache 식별자로 Queue·변환·전송 로그를 연결하고 전체 생성 bytes와 실제 전송 bytes를 구분합니다. 인증 정보·Prompt는 로그에 넣지 않습니다.

### 기능 검증

- 정지 Frame·크기·회전·Codec·손상 파일·실패 UI와 원본 대비 길이·비율·fps·음성 동기를 확인합니다.
- 신규 하위 요청마다 DB Commit 후 영상이 접수되고 상위 작업 완료를 기다리지 않는지, 여러 영상·이미지 혼합·중복 감지·Queue 포화 후 누락 회수를 확인합니다.
- 기동 채우기의 Catalog 페이지 조회·최신 순·모든 미변환 원본 접수·완료본 재사용·원본 변경 직전 재검사·Producer 종료·Foreground 우선순위와 Aging을 확인합니다. Queue 한도보다 원본이 많아도 모두 접수되는지 검사합니다.
- 같은 Key는 단일 변환, 다른 Key는 설정한 Worker 수 이내 실행, Queue 포화와 실패 후 자동/명시적 재시도를 검증합니다.
- 일시/영구 오류 분류·Backoff·총 시도 상한·재시작 후 실패 제한 유지·Scheduler 대기 중 Worker 미점유·클릭으로 상한 우회 방지를 확인합니다.
- Queue가 비어도 Worker가 대기하다 신규 완료를 처리하고, 기동 Producer 종료 뒤에도 Worker/Scheduler가 살아 있으며 서버 종료 때 모두 회수되는지 확인합니다.
- 대기 중/변환 중/재생 직후 닫아도 완료되고 다음 접속·재기동 후 Cache Hit인지 확인합니다.
- 느린/종료된 재생 연결이 다른 사용자와 Cache 확정을 막지 않는지 확인합니다.
- 완료 Range·ETag·인증과 변환 중 초기 재생·탐색 제한을 실제 Desktop·Android·iOS에서 검증합니다.
- 페이지당 64개 목록은 정지 Thumbnail만 조회하고 전체 영상을 일괄 변환하지 않는지 확인합니다.
- 이동·수동 삭제·이력만 삭제·원본 교체·삭제 보호·마운트 실패·정리/신규 생성 경합을 검증합니다. 영상 단건 삭제 기능 추가 자체는 이번 범위가 아닙니다.
- 정상/강제 종료·중간 파일·Metadata 확정 중 종료·디스크 부족 후 원본 보존과 재생성을 확인합니다.
- 영상 Thumbnail에만 기존 이미지와 같은 개수 상한/LRU가 적용되고 저용량 영상 수는 제한되지 않는지, Thumbnail 퇴출 후에도 영상/실패 Metadata가 유지되는지 검사합니다.
- fps·해상도·Codec·Worker 수 변경 후 기동해도 완료본의 파일/수정 시각이 유지되고 신규 변환만 새 설정을 쓰는지 확인합니다. 기동 때 기존 미리보기 전체를 Probe/decoding하지 않는지 검사합니다.
- 클릭 시 대기/변환 중/실패 Toast, 늦은 응답 무시, 반복 Toast 방지, 카드 상태 Badge 미추가와 실제 12fps 결과를 확인합니다. 설정 누락/잘못된 타입/음수/0을 검사합니다.
- 결과물 목록과 Git에 파생 파일이 섞이지 않고 새 Cache 정리가 서비스 준비를 막지 않는지 확인합니다.

## 12. 설계 당시 구현 순서

1. FFmpeg/ffprobe 의존성, 대표 원본 Benchmark와 모바일 점진 재생 Prototype을 검증합니다.
2. 12fps로 실제 결과를 확인하고 나머지 Profile·Worker 기본값과 직접 Streaming/MSE 연결 방식을 확정합니다. 이후 출력 설정 변경을 기존 완료본에 소급하지 않습니다.
3. 영상 정지 Thumbnail·전용 Manager/Queue·디스크 완료 확정·상태/재생 API를 구현합니다.
4. 신규 하위 요청 완료 접수, 기동/수동 동기화 정리, 기동 누락 채우기, 지연 재시도, 이동/삭제 무효화와 종료 회수를 연결합니다.
5. Thumbnail/Dialog를 연결하고 다중 접속·모바일·일반 API 회귀를 검증합니다.
6. 실제 API·확정 설정·측정값·구현 상태를 이 문서와 README에 갱신합니다.

모든 원본의 저용량 영상 보관·정지 Thumbnail만 이미지와 동일 개수 제한·설정 변경 시 완료본 유지·클릭 시 Toast·닫기 후 계속 변환·신규 완료/기동 누락 자동 접수 방향을 구현했습니다. 실제 값과 남은 기기 검증은 아래 기록을 따릅니다.

## 13. 구현과 검증 기록

### 구성과 확정한 동작

- `home_server/video_encoding.py`: FFmpeg/ffprobe 실행, 최대 640px·12fps H.264 baseline/AAC 48kbps, Decoder/Encoder 각 설정 Thread 수와 Filter 1개, WebP 정지 Frame 추출을 담당합니다. 영상 출력은 stdout에서 임시 파일로 바로 누적하며 전체 원본/결과를 RAM에 보관하지 않습니다.
- `home_server/video_preview_cache.py`: 영속 영상·독립 Thumbnail LRU·중복 Task 공유·Queue·Worker·기동 Producer·지연 재시도와 정리를 담당합니다. 원본 ID와 stat 버전으로 식별하고 현재 출력 설정을 Key나 완료본 재검사에 사용하지 않습니다.
- `runtime/cache/media/previews/`에는 모든 저용량 영상과 완료/실패 Metadata, `thumbnails/`에는 별도 개수 제한 WebP를 저장합니다. Thumbnail 퇴출은 영상·실패 Metadata에 영향을 주지 않습니다.
- 완료 영상 API는 `POST/GET /api/outputs/{output_id}/video-preview`, 재생은 `GET .../stream?version={identifier}`이며 명시적 재시도는 POST의 `{"retry": true}`입니다. 완료 파일은 Range·ETag를 지원하고 진행 중에는 Cache를 쓰지 않는 점진 응답을 제공합니다.
- 현재 연결은 native Video element와 fragmented MP4입니다. MSE/HLS 추가 없이 Edge에서 완료 전 재생을 확인했습니다. 재생 Dialog는 최대 750ms 간격으로 상태를 순차 조회하고 상태 전이 때만 Toast를 표시합니다. 음성은 보관하되 자동 재생은 음소거 상태로 시작하며 Controls에서 해제할 수 있습니다.
- 기본 Worker 4개, 각 Encoder/Decoder 2 threads, Queue 대기 한도 256개, 변환 Timeout 300초입니다. Thumbnail 추출은 별도 동시 2건·최대 30초이고 일반 이미지 변환 Slot과 분리합니다.
- 우선순위는 클릭 0·신규 완료 1·기동 채우기 2이며 `접수 monotonic 시각 + 우선순위 × 30초`가 작은 순서로 처리해 오래된 낮은 등급도 실행합니다. 진행 중 작업은 선점하지 않습니다.
- 일시 오류는 최초 포함 총 3회, 10초·20초 지연으로 재시도합니다. Scheduler가 대기하므로 Worker를 점유하지 않습니다. 현재 Jitter는 사용하지 않습니다. 실패 Metadata 저장 자체가 불가능하면 실행 중 메모리에도 최종 실패를 보관해 같은 실행에서 자동 재탐색이 무한 재시도하지 않게 합니다.
- 정상 종료 시 10초까지 완료를 기다린 뒤 남은 FFmpeg를 중지합니다. Probe 최대 15초를 고려해 최대 16초의 추가 회수 대기에서 Producer/Scheduler/Worker를 join합니다. 화면 닫기는 이 종료 신호를 보내지 않습니다.
- 영상 신규 완료는 `apply_request_states()` Commit 이후 접수합니다. 기동 Producer는 전체 미변환 원본 접수 후 끝나고 Worker/Scheduler는 서버 수명 동안 유지됩니다. 서버 종료로 중단된 작업은 다음 기동에서 처음부터 처리합니다.
- 원본 삭제·교체·현재 경로 이동을 재검사하고 Cache 정리는 원본·작업 DB를 수정하지 않습니다. 원본 Root 부재/권한 오류는 삭제로 일괄 처리하지 않습니다. Windows의 긴 `\\?\` 경로 접두어는 Root 경계 비교 전에 정규화하며 링크 경계 검증은 유지합니다.
- DB schema 변경은 없습니다. `Dockerfile`에 FFmpeg/ffprobe 의존성을 추가하며 추가 Mount는 사용하지 않습니다.

### 현재 장비 실측

운영 Catalog에 있는 실제 영상 2개를 읽기만 하고, 별도 `runtime/verification/video-benchmark-*/`에 결과를 기록했습니다. 원본·작업 상태·정식 Cache는 Benchmark에서 수정하지 않았습니다. Windows FFmpeg 9.0 계열에서 현재 640px/12fps/300+48kbps 설정으로 측정했습니다.

| 측정 | 결과 |
|---|---|
| 원본 크기 | 25,727,810 / 28,358,315 bytes |
| 미리보기 크기 | 약 468,248~469,043 bytes, 약 0.47MB |
| 개별 전체 변환 | 약 2.13~2.38초 |
| 2개 순차 처리 총 시간 | 약 4.61초 |
| 2개 병렬 처리 총 시간 | 약 2.36초 |
| 첫 1KB 이상 출력까지 | 약 184~272ms, 재생 첫 Frame 시간과는 다름 |
| FFmpeg 메모리 최대 샘플 | 순차 약 133MiB, 2건 병렬 합계 약 258MiB |

20ms 간격 RSS/Working Set 샘플링이며 절대 최대 메모리 보장이 아닙니다. Worker 수 4 설정도 측정했지만 원본이 2개여서 실제 동시 실행은 최대 2개였습니다. 4개 동시 실행의 처리량·메모리는 이번 측정으로 판단하지 않습니다. CPU 사용률·실제 모바일 네트워크 첫 재생 지연과 Linux Container에서의 속도는 이 표에 포함하지 않습니다.

### 검증 결과와 한계

- Python 전체 검사: **247 passed, 1 skipped**. 기존 Starlette TestClient 의존성 Deprecation warning 1개가 있으며 새 Worker의 Thread 예외는 없습니다.
- `tests/test_video_preview_cache.py`: 실제 무음/음성 FFmpeg 출력과 WebP, 인증·Range·ETag·원본 삭제, Queue 한도보다 많은 기동 후보, 중복/병렬 제한, 독립 Thumbnail 퇴출, 설정 변경/재기동/이동 후 완료본 보존, Root 부재, 재시도 상한/재기동, Reader 종료 후 완료, Thread 회수, 상위 작업 완료 전 신규 하위 요청 접수를 확인했습니다.
- `tests/browser_video_previews.cjs`: 운영 데이터와 분리한 실제 HTTP 서버·실제 Codec·느린 입력 읽기로 Edge 1280px/390px에서 **변환 중 첫 재생**, 빠른 닫기 후 변환 계속/완료, 실패 Toast 재시도, 완료본 재생, Escape·Focus·선택 Checkbox 분리와 원본 미요청을 확인했습니다. 작은 Thumbnail이 모두 실제로 로딩되는지도 검사합니다.
- 기존 LoRA/작업/태그 화면, 결과물 폴더 이동·삭제·보호와 Desktop/Mobile 탭·History 회귀를 확인했습니다. `node --check`, Python compile, `git diff --check`를 수행했습니다.
- FFmpeg가 포함된 Docker 이미지를 빌드하고 서비스를 재기동했습니다. 서비스 `healthy`, 운영 영상 2개의 기동 자동 변환 완료, 정지 WebP와 저용량 영상 HTTP 200·Range HTTP 206을 확인했습니다. Linux Container의 실제 완료 파일은 473,367 / 471,552 bytes이고 Thumbnail은 16,242 / 19,092 bytes였습니다. 원본·작업 이력은 변경하지 않았습니다.
- 390px 검사는 Windows Edge의 Mobile emulation입니다. **실제 Android/iOS·Safari 기기에서는 아직 확인하지 않았습니다.** Codec 지원과 모바일 네트워크 조건은 사용자 기기에서 확인해야 합니다. 정상 미리보기 재생 실패 시 Toast와 원본 열기를 제공하며 자동 원본 다운로드는 하지 않습니다.

구현 이후 코드 변경으로 검사 결과가 달라지면 이 기록도 갱신합니다.

## 참고

- [기존 이미지 Thumbnail Cache 구현 기록](thumbnail_cache.md)
- [결과물 Catalog·Metadata 구현 기록](output_metadata_improvement_plan.md)
- [FFmpeg Fragmentation](https://ffmpeg.org/ffmpeg-formats.html#Fragmentation)
- [FFmpeg 진행 정보와 Benchmark](https://ffmpeg.org/ffmpeg.html)
- [Starlette StreamingResponse·FileResponse](https://starlette.dev/responses/)
- [HTML video와 브라우저 로딩 정책](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/video)
