# Comfy Home Server

ComfyUI API에 Anima 이미지와 DaSiWa MiniMax H3 영상을 bulk로 제출하고, 집 안과 mobile에서 결과물을 확인하는 웹 앱입니다. 기획 결정사항은 [PLAN.md](PLAN.md)에 기록했습니다.

## Docker Compose 실행

앱 서버는 Docker Compose로 실행합니다. Docker Desktop의 Linux container를 사용합니다. `.env.example`을 `.env`로 복사하고 `COMFY_MANAGED_OUTPUT_DIRECTORY`를 Windows의 ComfyUI `output/from_home_server` 절대 경로로 설정하세요. `.env`는 Git에서 제외됩니다. `config.toml`의 비밀번호와 앱 설정은 그대로 사용하고, 컨테이너 안에서만 ComfyUI 주소와 output 경로를 환경변수로 바꿉니다.

```powershell
Copy-Item .env.example .env
# .env의 COMFY_MANAGED_OUTPUT_DIRECTORY를 실제 경로로 수정
.\run_compose.ps1 up
docker compose -f .\compose.yaml ps
docker compose -f .\compose.yaml logs -f home-server
# 종료
.\run_compose.ps1 down
```

`run_compose.ps1 up`은 스크립트 위치의 `compose.yaml`을 절대 경로로 지정하여 `docker compose --project-directory <프로젝트 경로> -f <compose.yaml 경로> up -d --build`를 실행합니다. Image를 build한 뒤 백그라운드로 시작하며, 명령을 생략해도 `up`으로 실행합니다. 다른 폴더에서 스크립트를 실행해도 프로젝트의 `.env`와 상대 경로를 사용합니다. `runtime/`은 없으면 준비하며, `down`은 컨테이너와 Compose network만 정리하고 DB·로그·생성물은 유지합니다.

`home_server/`, `web/`, `data/workflows/`, `config.toml`은 읽기 전용으로 mount합니다. `runtime/`과 ComfyUI의 `output/from_home_server`만 쓰기 가능하며 기존 SQLite DB와 로그를 계속 사용합니다. Python 코드 변경은 컨테이너 안의 Uvicorn reload가 감지합니다. `web/` 변경은 브라우저 새로고침으로 반영되고, workflow JSON은 작업 제출 시 다시 읽습니다. 의존성 변경은 `.\run_compose.ps1 up`, `config.toml` 변경은 `docker compose -f .\compose.yaml restart home-server`로 반영하세요.

reload 시 로그인 session이 초기화되고 제출 중인 작업이 중단될 수 있습니다.

상태는 `docker compose -f .\compose.yaml ps`, 로그는 `docker compose -f .\compose.yaml logs -f home-server`, 종료는 `.\run_compose.ps1 down`으로 관리합니다. Docker Desktop의 일반 bridge network와 `host.docker.internal:8188`로 Windows의 ComfyUI에 접속합니다.

브라우저에서 `http://localhost:8388`로 접속합니다. 설정은 프로젝트의 [config.toml](config.toml)에 있습니다. 기본 비밀번호는 설정 파일에 평문으로 저장되어 있습니다.

ComfyUI는 별도로 실행되어 있어야 합니다. 앱은 `config.toml`의 `comfy.endpoint`로 API 요청을 보내며 기존 ComfyUI의 기동 설정을 변경하지 않습니다.

## 주요 화면

- **생성:** workflow별 Prompt 입력, LoRA, 해상도 및 workflow 옵션, Batch 제출
- **작업:** 제출 한 번을 설명이 있는 상위 작업으로 묶고, 10건씩 페이지 이동하며, 하위 요청별 `prompt_id`·상태·Prompt 확인, 대기·실행 중 취소, 이력 또는 이력·결과물 삭제, 종료된 작업의 결과물 전체 폴더 이동
- **결과물:** `from_home_server`의 현재 파일을 64건씩 조회하고, 작은 이미지 preview로 확인하며, 단건·다중 폴더 이동과 이미지 삭제
- **Prompt:** Anima 태그 참조가 포함된 본문과 MiniMax 평문 편집, preset 버전 저장
- **태그 관리:** Anima Prompt에 사용할 태그 항목과 표시 그룹 생성·편집, 이름순으로 정렬된 그룹별 항목 접기·펼치기
- **LoRA 조합:** workflow별 LoRA 파일과 weight를 조합 preset으로 저장·편집·복제·삭제

LoRA 목록은 ComfyUI API에서 새로 읽습니다. Workflow별 기본 강도를 저장할 수 있으며 새 파일은 목록에서 구분됩니다.

생성 화면의 LoRA preset을 선택하면 저장된 조합이 카드로 채워집니다. 카드에서 weight를 바꾸거나 LoRA를 추가·제거하면 `수정됨`으로 표시되며, 저장된 원본은 유지됩니다. `현재 조합을 새 preset으로 저장`으로 변형을 저장할 수 있고, 원본 갱신은 `LoRA 조합` 화면의 `기존 preset 갱신`에서 수행합니다. `직접 구성`을 선택하면 preset 없이 새 조합을 만듭니다.

조합은 Anima의 STR·CLIP 또는 MiniMax의 STR·V×·A× 값을 그대로 보관하며, 개별 LoRA의 기본 강도를 바꿔도 이미 저장된 조합에는 영향을 주지 않습니다. ComfyUI 연결이 없어도 저장된 조합의 조회와 편집은 가능합니다. 찾을 수 없는 파일은 카드에 표시하고 제출 전에 확인합니다.

MiniMax H3는 `F2VA · 이 이미지로 시작`, `L2VA · 이 이미지로 끝`, `FL2VA · 같은 이미지로 시작·끝` 중 생성 방식을 선택합니다. 세 방식 모두 이미지 입력은 한 장이며, FL2VA는 그 이미지를 두 endpoint에 공통 사용합니다. `이미지 한 장` 또는 `폴더 일괄`을 선택한 뒤 서버 결과물 탐색기에서 입력을 고릅니다. 접속 단말의 파일 선택기를 열지 않습니다. 폴더는 직하위 이미지를 파일명순으로 표시하고 최대 100장을 선택할 수 있으며, 이미지마다 독립된 영상 요청을 생성합니다. 모든 입력은 같은 원본 Prompt 템플릿을 사용하고, `[TAG]` 참조가 있으면 이미지마다 독립 추첨해 치환합니다.

MiniMax에도 Anima와 같은 태그 선택 영역이 표시됩니다. 예를 들어 Prompt에 `[ACTION]`, 선택한 동작 본문에 `[CHR]`를 적으면 하위 참조까지 치환합니다. 같은 참조를 가진 여러 그룹의 선택 항목을 weight로 함께 추첨하며, 누락된 선택지와 cycle은 제출 전에 거부합니다. 미리보기는 추첨 예시를 보여주고 실제 제출할 때 다시 추첨합니다. `{a|b}`·`__name__` 같은 wildcard 문법은 그대로 유지하며, ComfyUI wildcard API를 호출하지 않습니다. 작업 이력은 원본 템플릿과 후보 Snapshot, 요청별 확정 Prompt·태그 선택 경로·`tag_seed`를 구분해 보관합니다. 태그 참조가 없는 텍스트는 기존처럼 그대로 전달합니다.

MiniMax 해상도는 첫 선택 이미지의 실제 크기(EXIF 표시 방향 반영)로 자동 입력하고, 32 단위로 보정한 제출 크기도 표시합니다. 다른 크기의 이미지가 섞이면 알려주며, 각 입력의 비율을 유지해 공통 Canvas에 검은 Pad로 맞춥니다. 너비·높이를 직접 바꾸면 이미지 선택이 바뀌어도 값을 유지하고, `첫 이미지 해상도 다시 적용`으로 자동값에 복귀합니다. 원본 파일과 독립된 임시 Snapshot을 제출 시 만들고 Batch 제출 처리가 끝나면 회수합니다. 작업 이력에는 생성 방식, 원본 출처, 실제 입력 크기와 제출 해상도를 기록합니다. [MiniMax 작업 생성 설계와 구현 기록](docs/minimax_generation_design.md)을 참고하세요.

Anima는 요청 횟수 N을 지정하면 ComfyUI에 N개의 개별 요청을 제출합니다. 각 요청은 태그 항목과 wildcard, random seed를 새로 선택하고 한 장씩 생성합니다.

Anima의 Workflow 옵션에서는 비율을 먼저 고른 뒤 해상도를 선택합니다. 기존 너비·높이 직접 입력은 비율의 `사용자 지정`에서 사용할 수 있습니다. 선택한 너비·높이는 각 요청의 설정과 작업 이력에 저장됩니다.

Anima Prompt와 Negative Prompt에는 `[SCENE]`처럼 대문자 태그 참조를 텍스트로 직접 적습니다. 참조 태그는 개별 항목이 아닌 그룹에서 설정하며 여러 그룹이 같은 참조 태그를 가질 수 있습니다. 생성 화면은 두 Prompt의 참조 태그를 가진 그룹을 모두 찾고 각 그룹의 하위 항목을 전부 표시합니다. `[SCENE]` 항목을 선택하면 그 본문에 적힌 `[CHR]` 등의 종속 참조를 가진 그룹도 나타납니다. 그룹마다 기본 펼침·접힘 상태를 지정하며 접힌 그룹도 열어서 선택할 수 있습니다. 각 참조 위치에서는 같은 참조 태그의 여러 그룹에서 체크된 항목을 하나의 후보 집합으로 묶고, 항목 하나를 기존 weight에 따라 선택합니다. 참조는 여러 단계를 거칠 수 있고 같은 태그가 두 번 나오면 각각 독립적으로 선택하므로 같은 항목이 반복될 수 있습니다. Positive와 Negative에 같은 참조를 적어도 각각 독립적으로 추첨합니다. 제출 전에 두 Prompt의 누락된 선택지와 참조 cycle을 검사하고, 모든 태그와 wildcard를 확정한 두 Prompt를 ComfyUI에 전달합니다. 미리보기와 작업 세부에는 확정된 Negative Prompt와 별도의 태그 선택 경로도 표시합니다. 요청 횟수만큼 독립적으로 추첨하므로 가능한 모든 조합을 한 번씩 생성하는 방식은 아닙니다.

Anima의 API·UI Workflow에는 ComfyUI-ppm의 `CLIP NegPip` (`CLIPNegPip`)가 LoRA Loader 뒤에 연결되어 있습니다. MODEL 출력은 sampler와 Detailer 경로로, CLIP 출력은 Positive·Negative 인코더와 Detailer 경로로 전달됩니다. [ComfyUI-ppm](https://github.com/pamparamm/ComfyUI-ppm#clipnegpip)의 Anima 지원 버전이 필요하며, 현재 로컬의 1.1.10에서 지원을 확인했습니다. 새로 생성한 이미지의 삽입 Workflow에도 이 연결이 포함됩니다.

CFG `1`에서 개념을 억제하려면 **Positive Prompt**에 `portrait, (blurry:-1), (bad anatomy:-1)`처럼 음수 가중치를 적습니다. NegPiP가 해당 token의 attention value 부호를 뒤집는 방식이며, 일반적인 Negative Prompt의 CFG 연산과는 다릅니다. 별도 Negative Prompt 입력은 그대로 유지하며 Positive로 자동 이동하거나 가중치를 변환하지 않습니다. 따라서 CFG `1`에서 별도 Negative Prompt의 내용이 반영되도록 만드는 기능은 아닙니다. 가중치에 따른 실제 효과는 모델·Prompt에 따라 달라집니다.

생성 화면과 태그 관리 화면의 그룹은 한국어 이름순으로, 그룹 안의 태그 항목은 화면 이름순으로 표시합니다. 숫자가 포함된 이름은 자연스러운 숫자 순서로 정렬합니다.

생성 화면의 각 그룹에는 현재 표시된 태그 항목을 한 번에 선택하거나 해제하는 버튼이 있습니다. 아직 Prompt 참조에서 필요하지 않아 숨겨진 항목은 일괄선택에 포함되지 않습니다.

Anima Prompt preset 버전에는 Prompt 본문과 Negative Prompt만 저장합니다. 태그 그룹과 항목은 별도 DB에서 관리하며 생성할 때 현재 정의를 사용합니다. 항목은 소속 그룹의 참조 태그를 따르므로 그룹의 참조 태그를 바꾸거나 항목을 다른 그룹으로 이동하면 다음 생성부터 적용됩니다. 제출한 작업에는 그 시점의 그룹 참조와 태그 정의, 선택 경로 및 확정 Prompt가 남으며 이후 편집의 영향을 받지 않습니다. 기존 `Anima onepiece`의 최신 상황 두 개는 Prompt 본문의 `[SCENE]` 참조, 공통 SCENE 항목과 두 CHR 선택지로 옮겼습니다.

작업 화면에서는 한 번의 제출을 하나의 작업으로 표시합니다. 펼치면 개별 요청을 확인할 수 있고, 작업 결과 보기에서는 완료된 요청의 결과를 함께 보여줍니다. 일부 요청만 완료되거나 실패하면 진행 건수와 `일부 완료` 상태가 표시됩니다.

일반 탭 이동은 탭마다 마지막 스크롤 위치를 복원하며 페이지·필터·입력과 펼친 요청·선택 상태를 유지합니다. 작업 결과를 보고 작업 탭으로 돌아와도 보던 페이지와 위치가 유지됩니다. `작업 결과 보기`·결과물의 `작업`·`생성 탭에서 복원`·Prompt/LoRA 편집 및 적용처럼 다른 내용을 구성하는 이동은 대상 화면의 상단에서 시작합니다. 스크롤·입력·펼침·선택 상태는 현재 열린 화면에서만 유지하며 브라우저 새로고침 시 초기화됩니다.

브라우저 또는 마우스의 뒤로가기·앞으로가기로 탭 이동, 작업·요청 결과 보기, 작업·결과물의 페이지 변경과 필터 해제를 되짚을 수 있습니다. History에는 탭·페이지·필터·스크롤과 펼친 작업 ID만 저장하며 이전 목록 Cache는 추가하지 않습니다. 목록은 현재 API에서 다시 조회하고 조회 후 스크롤을 복원합니다. 조회 중 사용자가 스크롤하거나 다른 곳으로 이동하면 늦은 응답이 화면 위치를 되돌리지 않습니다. 자동 Polling은 History를 추가하지 않으며, History 복원은 생성 입력 적용·제출·삭제·파일 이동을 재실행하지 않습니다.

탭·작업/요청 결과·결과물의 작업·페이지 이동·전체 보기 링크는 가운데 버튼이나 Ctrl+클릭으로 새 브라우저 탭에서 열 수 있습니다. URL에 `view`·`page`·`job_id` 또는 `request_id`를 기록하므로 URL 복사나 새로고침으로도 같은 조회 조건을 열 수 있습니다. 새 탭은 로그인 확인 후 목록을 조회하며 생성 입력과 파일 선택은 복사하지 않습니다. 생성 복원·제출·삭제·이동처럼 입력이나 데이터를 변경하는 버튼은 실행 버튼으로 유지합니다.

작업 요약에는 제출 시간·요청 설정의 비율·해상도·CFG·Steps·완료 장수·LoRA 조합을 순서대로 표시합니다. 원본 그대로 사용한 조합은 제출 당시 preset명, 직접 구성하거나 preset을 수정한 조합은 `custom`, LoRA를 사용하지 않은 작업은 `lora없음`으로 표시합니다. 기존 이력에서 preset 출처가 저장되지 않은 LoRA 조합도 `custom`으로 표시합니다. 하위 요청에는 확정 Prompt와 실제 LoRA 파일별 STR을 표시합니다. Preset명은 표시용으로만 추가 저장하며, 생성은 기존처럼 작업에 저장된 LoRA 파일 목록과 강도를 사용하므로 이후 preset 수정·삭제의 영향을 받지 않습니다. 설정이 없는 이전 이력은 비율·해상도·CFG·Steps의 해당 값을 `—`로 표시합니다.

Anima 생성 이미지에 삽입하는 UI Workflow에는 실제 요청에 선택한 LoRA 목록과 활성 상태·Model/CLIP 강도를 기록합니다. ComfyUI에서 이미지를 불러오면 LoRA Manager에 같은 구성이 복원되며, Model/CLIP 강도가 다르면 분리해서 표시합니다. CLIP 강도 `0`도 유지하며 LoRA를 선택하지 않은 요청은 빈 목록으로 기록합니다. 실행 API의 `loras.__value__` 형식과 UI Workflow의 배열 형식은 각각 구분해 저장합니다.

Anima의 두 기본 Workflow 파일은 LoRA 목록·LoRA 텍스트·trigger word 목록을 비워 둡니다. 앱의 생성 요청에서도 trigger word 상태를 비우고 입력을 빈 문자열로 고정해 Prompt에 자동으로 붙이지 않습니다. 이미지에 삽입하는 UI Workflow는 LoRA와 TriggerWord Toggle의 연결을 유지하므로 ComfyUI에서 복원 후 LoRA를 추가·제거하거나 활성 상태를 바꾸면 목록이 해당 LoRA에 맞춰 갱신됩니다. TriggerWord Toggle의 기본 활성 상태는 꺼져 있어 새 trigger word 그룹은 비활성 상태로 표시됩니다. LoRA 자체의 적용과 Model/CLIP 강도는 유지합니다.

결과물 목록의 `작업` 버튼은 catalog에서 생성 작업과 연결된 파일에 표시합니다. 누르면 작업 탭에서 해당 작업 한 건만 보여주며, `전체 작업 보기`로 필터를 해제할 수 있습니다. 앱에서 파일을 이동해도 작업·요청 연결은 유지합니다. 이력이 삭제된 파일이나 외부에서 추가되어 작업 연결이 없는 파일에는 버튼을 표시하지 않습니다.

작업 카드의 원본 `입력 Prompt`와 `입력 Negative Prompt`는 자동 줄바꿈을 포함해 합계 최대 5줄로 표시하고, 넘치는 부분은 말줄임표로 접습니다. 카드를 누르면 두 Prompt의 전체 원문이 펼쳐지고 다시 누르면 접힙니다. Prompt 영역에 Keyboard focus를 두고 Enter·Space로도 전환할 수 있으며 자동 새로고침 때 펼친 상태를 유지합니다. 카드 안 버튼·링크·checkbox와 하위 요청 조작은 상위 Prompt 접힘을 바꾸지 않습니다. `[TAG]` 참조와 줄바꿈을 포함한 원문은 보존하고, 원본이 저장되지 않은 이전 이력은 `기록 없음`으로 표시합니다. 하위 요청을 펼치면 각 요청의 확정 Prompt·Negative Prompt·양쪽 태그 선택 경로를 합계 최대 5줄로 표시합니다. 하위 요청 카드를 누르거나 해당 영역에서 Enter·Space를 누르면 전체가 펼쳐지고 다시 누르면 접힙니다. 요청마다 독립적으로 동작하며 상세 조회·자동 갱신 후에도 펼침 상태를 유지합니다. 요청 취소·결과 보기 버튼은 접힘 상태를 바꾸지 않습니다.

작업 카드의 `생성 탭에서 복원`은 상위 작업 단위로 Workflow·원본 Prompt·Negative Prompt·LoRA 파일과 강도·Workflow 옵션·요청 횟수·작업 설명을 생성 탭에 채웁니다. 자동 제출하지 않으며 태그 추첨 결과·wildcard 선택·random seed는 복원하지 않습니다.

태그는 제출 당시 체크한 항목 중 현재 존재하고 현재 Prompt 참조에서 체크 가능한 항목만 선택하며, 변경된 본문·weight·그룹 참조는 현재 정의를 사용합니다. 삭제된 항목은 되살리지 않으며 필요한 선택지가 없으면 기존 제출 검증에서 안내합니다.

Prompt·LoRA preset은 기록된 ID의 현재 구성이 제출 당시 입력과 같을 때만 선택하고, 변경·삭제된 preset은 `직접 작성`·`직접 구성`으로 복원합니다. Preset ID가 없는 이전 이력은 같은 본문의 현재 Prompt preset이 하나일 때만 연결하며, LoRA는 같은 이름의 현재 preset이 하나이고 구성도 같을 때만 연결합니다. 후보가 여러 개이거나 일치하지 않으면 직접 작성·직접 구성으로 복원합니다.

MiniMax 입력 이미지는 비워 두므로 다시 선택해야 합니다. 원본 Prompt 기록이 없는 이력은 복원할 수 없습니다.

결과물 크기는 용량 뒤에 비율·해상도로 표시합니다. 이미지는 파일의 실제 크기를 읽고, 영상은 연결된 요청의 설정값을 `(설정)`으로 표시합니다. 크기를 확인할 수 없는 파일은 `—`로 표시합니다.

생성 화면에서 선택적인 한 줄 작업 설명을 입력할 수 있으며 작업 목록에 표시됩니다. 제출·대기·실행 중인 작업은 전체 또는 하위 요청별로 취소할 수 있습니다. 취소를 접수하면 아직 전송하지 않은 요청의 제출을 중단하며, 전송 중 뒤늦게 접수된 요청도 취소 대상으로 추적합니다. 취소 버튼과 진행 건수는 접수 즉시 표시하고, ComfyUI의 실제 취소 확인은 백그라운드에서 진행합니다. 전송 실패는 자동 재시도하며 작업 카드에 실패 건수와 재시도 버튼을 표시합니다. ComfyUI에서 직접 제거되어 대기열·완료 기록에 모두 없는 요청은 일정 시간 재확인한 뒤 `중단`으로 표시합니다.

작업 목록은 요약만 자동 조회하며 하위 요청 상세는 펼칠 때, 생성 입력은 복원할 때 별도로 불러옵니다. 진행 중인 조회가 끝나기 전에 다음 Polling을 시작하지 않고, 갱신 중이나 조회 실패 시 마지막 목록을 유지합니다. 다른 탭에서는 활성 작업 수만 조회합니다. 기존 후보 Snapshot은 SQLite에 그대로 보관합니다.

작업이 종료된 뒤에는 `이력만 삭제` 또는 `이력·결과물 삭제`를 선택합니다. 후자는 작업 history에 기록된 원래 생성 위치의 결과물만 삭제합니다. 이미 이동·삭제되어 없는 파일은 로그에 남기고 건너뛰며, 이동된 파일은 유지합니다.

작업 화면의 `다중 삭제`를 누르면 각 작업 옆에 checkbox와 일괄 삭제 버튼이 나타납니다. `현재 페이지 선택`은 해당 페이지의 삭제 가능한 작업을 선택하고, `작업 전체 선택`은 현재 목록의 모든 페이지에서 삭제 가능한 작업을 한 번에 선택합니다. 작업 한 건만 표시하는 필터가 적용된 경우에는 그 필터 범위만 선택합니다. 진행 중이거나 삭제 보호된 작업은 제외됩니다. 같은 버튼을 다시 누르면 해당 범위의 선택을 해제합니다. 한 개 이상 선택하면 `선택된 이력만 삭제`와 `선택된 이력·결과물 삭제`가 활성화되고, 삭제 전 전체 선택 건수와 삭제 방식을 한 번 확인합니다. 자동 새로고침과 페이지 이동 중에도 선택을 유지하며, 작업 필터를 바꾸거나 `다중 삭제 취소`를 누르면 선택을 초기화합니다. 전체 선택 후 새로 생긴 작업은 자동으로 추가 선택하지 않습니다. 선택한 작업이 보호되거나 진행 중 상태가 되면 선택에서 제외합니다. 일부 삭제가 실패하면 성공·실패 건수를 표시하고, 여전히 삭제 가능한 실패 이력은 선택된 상태로 남깁니다.

각 작업의 `삭제 보호` 버튼으로 테스트 결과 등 보존할 작업을 보호할 수 있습니다. 설정은 SQLite에 저장되어 새로고침과 서버 재시작 후에도 유지됩니다. 보호된 작업은 `삭제 보호됨`으로 표시하고 checkbox를 비활성화하며 개별 삭제 버튼도 숨깁니다. `보호 해제` 전에는 전체 선택과 이력·결과물 삭제에서도 제외됩니다. 삭제 API는 DB 잠금 안에서 보호 상태를 다시 검사하며, 보호된 작업의 파일은 삭제하지 않습니다. 보호 설정은 생성·취소·복원 기능에는 영향을 주지 않습니다.

결과물 목록은 64건씩 페이지 이동합니다. 이미지는 최대 384px, quality 75의 WebP 썸네일로 변환하고 압축된 bytes만 메모리 LRU Cache에 보관합니다. 기본 최대 개수는 10,000개이며 원본·Bitmap·썸네일 파일은 저장하지 않습니다. 같은 이미지의 동시 조회는 변환 결과를 공유하고, 서로 다른 이미지의 변환은 동시에 최대 두 건만 수행합니다. 영상은 목록에서 파일 정보만 표시하고 `열기`를 누를 때 원본을 불러옵니다. 결과물 탭 진입 또는 수동 새로고침 때 파일 목록을 다시 읽으며, 새로고침하면 첫 페이지로 돌아갑니다.

목록 정렬은 Saver 파일명의 `yyMMdd_HHmmss_seed`에서 읽은 시각 → 숫자 seed → 전체 경로 내림차순입니다. Seed는 같은 초의 순서를 일정하게 만드는 기준이며 더 정밀한 생성 시각을 뜻하지 않습니다. 규칙 밖 파일은 목록 끝에 경로순으로 표시합니다. 목록 조회에서는 파일별 `stat()`과 파일 크기 표시를 제거했습니다. 해상도는 실제 이미지 header에서 읽고 최대 30,000개를 시간 만료 없는 LRU Cache로 재사용합니다. 같은 경로에 덮어쓴 파일의 해상도는 해당 항목이 Cache에서 퇴출되거나 서버를 재시작할 때 다시 읽습니다. 앱에서 이동한 경로의 해상도 Cache는 즉시 무효화합니다. 썸네일·원본 전송의 파일 속성 확인은 유지합니다.

`config.toml`의 `[outputs]`에서 Cache 개수와 기동 시 백그라운드 채우기를 설정합니다. 설정 변경 후 서버를 재기동하세요.

```toml
[outputs]
thumbnail_cache_max_entries = 10000
thumbnail_cache_warmup_enabled = false
```

백그라운드 채우기는 개발 중 반복 재기동 비용을 줄이도록 기본적으로 꺼져 있습니다. `true`로 켜면 기동 직후 별도 Thread에서 최신 이미지부터 최대 설정 개수까지만 채우며, 서비스 준비 완료를 기다리게 하지 않습니다. 기존 이미지 전체의 파일 정보를 탐색한 뒤 한 장씩 원본을 읽고 변환합니다. 생성 사이에 50ms씩 대기하며, 사용자가 조회한 썸네일을 백그라운드 작업 때문에 퇴출하지 않습니다. 메모리에만 보관하므로 썸네일을 SSD에 쓰지 않지만 재기동마다 원본 읽기와 CPU 변환 비용은 다시 발생합니다. 파일 존재·관리 경로·수정 시간·크기는 요청마다 확인하여 외부 삭제·이동·변경을 반영하며, 변경 없이 재시작한 경우에도 메모리 Cache는 새로 만들어집니다. [Cache 동작과 검증](docs/thumbnail_cache.md)을 참고하세요.

## 저장 위치

- Prompt, LoRA 조합, 작업 기록 SQLite, 임시 upload: 프로젝트의 `runtime/`
- 앱 로그: `runtime/logs/home_server.log` (5 MB마다 회전, 이전 로그 5개 보관). 콘솔에도 출력합니다.
- DB·파일 처리와 큰 응답의 최종 JSON 직렬화는 Worker Thread에서 수행하고, 로그 출력은 별도 Queue Listener Thread에서 처리합니다. [Event Loop 처리·동시 요청 검증](docs/event_loop_processing.md)을 참고하세요.
- Workflow 원본: 프로젝트의 `data/workflows/`
- 생성물: `config.toml`의 `comfy.output_directory` 아래 `comfy.managed_output_folder`

결과물 목록·썸네일 조회는 `OUTPUT_TIMING` 로그로 상세 시간을 기록합니다. 응답의 `X-Output-Timing-Id`와 로그의 `id`로 같은 요청을 연결합니다. `event=step`은 개별 단계, `event=summary`는 호출 수·누적 시간·최대 시간·가장 느린 경로, `event=complete`는 HTTP 응답 준비까지의 전체 시간입니다. 목록은 `catalog_filter_validation`·`catalog_count`·`catalog_page_query`, 요청 해상도가 없는 이미지의 읽기는 `image_dimensions_fallback`, 수동 파일 대조는 `catalog_sync`로 구분합니다. 썸네일은 파일 접근과 Cache hit·miss·대기를 구분합니다. `catalog_listing`, `page_enrichment`, `handler_total`, `http_dispatch`는 하위 단계를 포함하므로 모든 `total_ms`를 더하면 중복 계산됩니다. 로그 파일 쓰기는 기존 Queue Listener가 처리하며 비밀번호·Session token·Prompt 본문은 기록하지 않습니다.

결과물 조회의 병목 진단과 `is_file`, `resolve`, `walk` 비교 결과는 [성능 실험 기록](docs/performance_investigation_2026-10-14.md)에 정리했습니다.

작업 계층 DB 전환은 시작할 때 한 번 수행합니다. 기존 요청 단위 작업 기록은 초기화되지만 Prompt preset·버전과 LoRA 기본값·조합 preset, 생성물 파일은 유지됩니다.

참조 태그의 그룹 전환은 DB schema version 4에서 5로 자동 migration합니다. 변경 전에 SQLite backup API로 일관된 DB 복사본을 `runtime/backups/`에 저장하고 무결성을 확인합니다. 그룹 안의 기존 항목에서 공통 참조 태그를 옮기며 항목 ID·내용·weight와 기존 설정·작업 이력은 보존합니다. 비어 있는 기존 그룹은 참조 태그를 추론할 수 없어 비워 두므로 그룹 편집에서 설정해 주세요. 한 그룹에 서로 다른 참조 태그가 있으면 임의로 선택하지 않고 migration을 중단합니다.

DB schema version 6에서는 기존 작업과 설정을 유지하면서 작업별 삭제 보호 column을 추가합니다. 기존 작업은 보호 해제 상태로 시작하며 각 작업에서 보호를 설정할 수 있습니다.

DB schema version 9에서는 작업 공통 입력·체크한 태그 후보를 `job_inputs`에 작업당 한 번 저장하고, 개별 확정 Prompt·선택 경로·Seed·결과물 경로는 `request_results`에 요청당 한 번 저장합니다. 이전 모든 요청을 자동 Migration한 뒤 기존 Snapshot 테이블·column을 제거하며, 이후 조회는 새 구조만 사용합니다. Migration 전 백업을 `runtime/backups/`에 보관합니다. 하위 상세에서는 후보 데이터를 읽지 않고, 생성 탭 복원에서만 작업 공통 후보를 가져옵니다. [구조·Migration 검증](docs/job_request_storage_split.md)에 설명했습니다.

DB schema version 10은 기존 JSON을 그대로 유지하고 `output_files`에 결과물 경로·작업/요청 연결·파일명 시각/Seed·요청 너비/높이를 추가 백필합니다. 결과물 목록과 작업의 결과 보기는 DB index에서 정렬·pagination을 처리하며, 요청 해상도가 있으면 이미지 header를 읽지 않습니다. 종횡비는 저장된 너비/높이로 계산하며 `(설정)` 표시로 실제 최종 해상도와 구분합니다. 실제 파일 크기·최종 해상도의 DB 저장은 후속 검토입니다. [구현·백필 및 2차 검토](docs/output_metadata_improvement_plan.md)를 참고하세요.

DB schema version 11은 `output_files.is_deleted`를 추가합니다. 기존 DB는 Migration 전 `runtime/backups/`에 백업하며, 기존 작업·요청 JSON과 파일 경로·가용 상태를 보존합니다. 결과물 탭은 한 페이지에 이미지·영상을 합쳐 최대 64개를 표시합니다. 이미지 카드에서 **삭제**를 누르고 확인하면 현재 위치의 이미지 파일을 영구 삭제합니다. 이동한 이미지도 삭제할 수 있으며, 작업 이력은 유지됩니다. 삭제 보호된 작업의 이미지는 보호 해제 후 삭제할 수 있습니다. 영상의 단건 삭제는 제공하지 않습니다.

삭제한 이미지의 DB 행은 `is_deleted=1`, `is_available=0`으로 남기고 전체·작업·요청 결과 목록에서 제외합니다. 원본·썸네일 URL도 404를 반환합니다. 이미 파일이 없어도 삭제 상태를 기록하며, 삭제 실패 시 DB 변경을 되돌립니다. 수동 동기화·서버 재시작·같은 요청의 완료 재반영으로 삭제 표시를 해제하지 않으며, 외부에서 같은 경로에 파일을 다시 놓아도 자동으로 노출하지 않습니다. FS에서만 사라진 기존 파일은 `is_available=0` 상태로 구분하여 유지합니다.

결과물 탭의 **다중 선택**에서 파일별 선택, **현재 페이지 선택**, **결과물 전체 선택**, **선택된 결과물 이동**, **선택된 이미지 삭제**를 사용할 수 있습니다. 전체 선택은 현재 작업·요청 필터의 모든 페이지를 대상으로 하며, 페이지를 이동해도 선택을 유지하고 필터를 바꾸거나 다중 선택을 취소하면 선택을 초기화합니다. 영상과 삭제 보호된 결과물도 이동할 수 있습니다. 삭제는 선택한 항목 중 보호되지 않은 이미지만 대상으로 하며, 보호된 이미지의 단건 삭제 버튼은 비활성화합니다. 삭제 전 대상 이미지 개수를 확인하고 제외되는 영상·보호 항목을 안내합니다. 실제 삭제 직전에 서버가 보호 상태를 다시 검사합니다. 선택한 영상·보호 항목은 삭제 후에도 이동할 수 있도록 선택을 유지합니다.

작업 카드의 **결과물 폴더 이동**은 생성이 끝난 작업에 연결된 현재 결과물 전체를 이동합니다. 이미 다른 폴더로 옮긴 파일도 현재 경로에서 이동하며, 삭제·비가용 상태의 파일은 대상에서 제외합니다. 진행 중인 작업은 종료 후 사용할 수 있습니다. 결과물 탭의 **선택된 결과물 이동**은 선택한 파일을 같은 목적지로 이동합니다. 두 동작 모두 `from_home_server` 안의 상대 폴더를 한 번 입력하며, 원래 JSON과 작업·요청 연결을 보존하고 catalog의 현재 경로만 변경합니다. 이미 같은 폴더에 있는 파일은 건너뛰고, 동일 파일명 충돌은 덮어쓰지 않습니다. 이동·삭제 중에는 선택·페이지 이동·다른 파일 조작을 잠급니다. 일부 이동·삭제가 실패하면 성공·건너뛰기·실패 건수를 알리고, 여전히 존재하는 실패 항목의 선택을 유지하여 재시도할 수 있습니다.

생성물은 `{workflow}/{YYMMDD_HHmmss}_{seed}.{확장자}`를 기본으로 저장합니다. 예: `anima/261006_153012_123456789.png`. Anima는 `%time_%seed`, MiniMax는 `%date:yyMMdd_HHmmss%_%seed%` 예약어를 사용하며, MiniMax Saver에도 sampling과 동일한 seed 출력을 연결합니다. 시각은 ComfyUI Saver 실행 시점의 로컬 시간이고, 영상은 encoding 시작 직전입니다. Saver가 붙이는 counter나 `_audio` 접미사는 그대로 유지하며 앱에서 파일명을 후처리하지 않습니다. 작업의 결과 보기는 ComfyUI history의 실제 출력 파일명을 사용합니다. 생성 완료와 앱의 파일 이동·삭제는 DB 목록에 즉시 반영됩니다. 외부에서 추가·이동·삭제한 파일은 서버 시작 또는 결과물 화면의 새로고침 버튼으로 실제 폴더를 대조해 반영합니다. 앱이 미완료 요청을 재시작 후 자동 재제출하지 않습니다.

단건·선택한 여러 결과물·작업 전체의 `이동`은 공용 폴더 탐색기에서 목적지를 선택합니다. 탐색기의 `결과물`이 관리 폴더 루트이며, Breadcrumb과 `상위 폴더`로 루트 안에서만 이동합니다. 빈 폴더도 표시하고, 현재 위치에서 `새 폴더 만들기`를 누르면 생성한 폴더가 열립니다. `이 폴더로 이동`을 눌러야 파일 이동을 시작하며, 취소하면 파일은 이동하지 않고 이미 만든 폴더는 남습니다. 루트 자체도 목적지로 선택할 수 있습니다.

탐색·생성은 현재 폴더의 직하위 폴더만 읽고 DB 전체 동기화를 호출하지 않습니다. 새 DB schema나 추가 Mount는 필요하지 않습니다. [결과물 폴더 탐색기 설계와 구현 기록](docs/output_folder_picker_design.md)에 경로 경계와 검증 내용을 정리했습니다. 같은 탐색기를 MiniMax 서버 이미지 선택에도 사용하며, 입력 선택 모드에서는 폴더 생성 UI를 숨깁니다. 폴더 삭제는 후속 범위입니다.

## 외부 접속

앱 기본 포트는 8388입니다. 현재 구성은 HTTP와 단일 비밀번호 인증을 사용합니다. HTTP로 외부 접속하면 비밀번호와 전송 내용이 암호화되지 않습니다. 앱 설정과 ComfyUI 8188 서버 설정은 서로 독립적입니다.

## 개발 검증

API 테스트는 `python -m pytest -q`로 실행합니다. LoRA 조합의 browser 검증은 Edge와 Mock API를 사용하며 실제 GPU 생성 요청을 보내지 않습니다.

```powershell
npm install --prefix runtime/browser-check --no-package-lock --no-audit --no-fund playwright
$env:NODE_PATH = (Resolve-Path runtime/browser-check/node_modules).Path
node tests/browser_lora_presets.cjs
node tests/browser_job_deletion.cjs
node tests/browser_output_deletion.cjs
node tests/browser_job_restoration.cjs
node tests/browser_job_performance.cjs
node tests/browser_tab_navigation.cjs
```
