# Comfy Home Server

ComfyUI API에 Anima 이미지와 DaSiWa MiniMax H3 영상을 bulk로 제출하고, 집 안과 mobile에서 결과물을 확인하는 웹 앱입니다. 기획 결정사항은 [PLAN.md](PLAN.md)에 기록했습니다.

## Docker Compose 실행

Docker Desktop의 Linux container를 사용합니다. `.env.example`을 `.env`로 복사하고 `COMFY_MANAGED_OUTPUT_DIRECTORY`를 Windows의 ComfyUI `output/from_home_server` 절대 경로로 설정하세요. `.env`는 Git에서 제외됩니다. `config.toml`의 비밀번호와 로컬 실행 설정은 그대로 사용하고, 컨테이너 안에서만 ComfyUI 주소와 output 경로를 환경변수로 바꿉니다.

```powershell
Copy-Item .env.example .env
# .env의 COMFY_MANAGED_OUTPUT_DIRECTORY를 실제 경로로 수정
docker compose up -d --build
docker compose ps
docker compose logs -f home-server
```

`home_server/`, `web/`, `data/workflows/`, `config.toml`은 읽기 전용으로 mount합니다. `runtime/`과 ComfyUI의 `output/from_home_server`만 쓰기 가능하며 기존 SQLite DB와 로그를 계속 사용합니다. Python 코드 변경은 컨테이너 안의 Uvicorn reload가 감지합니다. `web/` 변경은 브라우저 새로고침으로 반영되고, workflow JSON은 작업 제출 시 다시 읽습니다. 의존성 변경은 `docker compose up -d --build`, `config.toml` 변경은 `docker compose restart home-server`로 반영하세요.

reload 시 로그인 session이 초기화되고 제출 중인 작업이 중단될 수 있습니다.

상태는 `docker compose ps`, 로그는 `docker compose logs -f home-server`, 종료는 `docker compose down`으로 관리합니다. Docker Desktop의 일반 bridge network와 `host.docker.internal:8188`로 Windows의 ComfyUI에 접속합니다.

## Python 직접 실행

Python 3.11 이상에서 실행합니다.

PowerShell에서 다음 스크립트를 실행하면 `.venv`를 만들고 의존성을 설치한 뒤 서버를 시작합니다. 이후 `requirements.txt`가 변경되면 다음 실행 때 의존성을 다시 설치합니다.

```powershell
.\run_home_server.ps1
```

기본 실행은 `home_server/`의 Python 코드가 변경될 때 서버를 자동 재시작합니다. 자동 재시작 없이 실행하려면 `.\run_home_server.ps1 -NoReload`를 사용합니다. 수동 실행은 `python -m pip install -r requirements.txt` 후 `python -m home_server` 또는 `python -m home_server --reload`로 가능합니다. `web/` 파일은 브라우저를 새로고침하면 반영되고, workflow JSON은 요청할 때 다시 읽습니다. `config.toml` 변경 사항은 서버를 직접 재시작해야 합니다.

자동 재시작 시 로그인 session이 초기화되며 제출 중인 작업이 중단될 수 있습니다. 상시 실행에는 `-NoReload`를 사용하세요.

브라우저에서 `http://localhost:8388`로 접속합니다. 설정은 프로젝트의 [config.toml](config.toml)에 있습니다. 기본 비밀번호는 설정 파일에 평문으로 저장되어 있습니다.

ComfyUI는 별도로 실행되어 있어야 합니다. 앱은 `config.toml`의 `comfy.endpoint`로 API 요청을 보내며 기존 ComfyUI의 기동 설정을 변경하지 않습니다.

## 주요 화면

- **생성:** workflow별 Prompt 입력, LoRA, 해상도 및 workflow 옵션, Batch 제출
- **작업:** 제출 한 번을 설명이 있는 상위 작업으로 묶고, 10건씩 페이지 이동하며, 하위 요청별 `prompt_id`·상태·Prompt 확인, 대기·실행 중 취소, 이력 또는 이력·결과물 삭제
- **결과물:** `from_home_server`의 현재 파일을 24건씩 조회하고, 작은 이미지 preview로 확인하며, 폴더 내부 이동
- **Prompt:** Anima 태그 참조가 포함된 본문과 MiniMax 평문 편집, preset 버전 저장
- **태그 관리:** Anima Prompt에 사용할 태그 항목과 표시 그룹 생성·편집, 이름순으로 정렬된 그룹별 항목 접기·펼치기
- **LoRA 조합:** workflow별 LoRA 파일과 weight를 조합 preset으로 저장·편집·복제·삭제

LoRA 목록은 ComfyUI API에서 새로 읽습니다. Workflow별 기본 강도를 저장할 수 있으며 새 파일은 목록에서 구분됩니다.

생성 화면의 LoRA preset을 선택하면 저장된 조합이 카드로 채워집니다. 카드에서 weight를 바꾸거나 LoRA를 추가·제거하면 `수정됨`으로 표시되며, 저장된 원본은 유지됩니다. `현재 조합을 새 preset으로 저장`으로 변형을 저장할 수 있고, 원본 갱신은 `LoRA 조합` 화면의 `기존 preset 갱신`에서 수행합니다. `직접 구성`을 선택하면 preset 없이 새 조합을 만듭니다.

조합은 Anima의 STR·CLIP 또는 MiniMax의 STR·V×·A× 값을 그대로 보관하며, 개별 LoRA의 기본 강도를 바꿔도 이미 저장된 조합에는 영향을 주지 않습니다. ComfyUI 연결이 없어도 저장된 조합의 조회와 편집은 가능합니다. 찾을 수 없는 파일은 카드에 표시하고 제출 전에 확인합니다.

MiniMax H3는 wildcard 없이 평문 Prompt 하나를 입력하고, 브라우저에서 선택한 여러 이미지나 폴더의 모든 이미지에 같은 문구를 적용합니다. Anima는 요청 횟수 N을 지정하면 ComfyUI에 N개의 개별 요청을 제출합니다. 각 요청은 태그 항목과 wildcard, random seed를 새로 선택하고 한 장씩 생성합니다.

Anima의 Workflow 옵션에서는 비율을 먼저 고른 뒤 해상도를 선택합니다. 기존 너비·높이 직접 입력은 비율의 `사용자 지정`에서 사용할 수 있습니다. 선택한 너비·높이는 각 요청의 설정과 작업 이력에 저장됩니다.

Anima Prompt에는 `[SCENE]`처럼 대문자 태그 참조를 텍스트로 직접 적습니다. 생성 화면은 Prompt의 참조에 필요한 태그 항목만 그룹별로 표시합니다. `[SCENE]` 항목을 선택하면 그 본문에 적힌 `[CHR]` 등의 종속 참조가 나타납니다. 그룹마다 기본 펼침·접힘 상태를 지정하며 접힌 그룹도 열어서 선택할 수 있습니다. 각 참조 위치에서는 체크된 동일 태그의 항목 하나를 weight에 따라 선택합니다. 참조는 여러 단계를 거칠 수 있고 같은 태그가 두 번 나오면 각각 독립적으로 선택하므로 같은 항목이 반복될 수 있습니다. 제출 전에 누락된 선택지와 참조 cycle을 검사하고, 모든 태그와 wildcard를 확정한 Prompt를 ComfyUI에 전달합니다. 요청 횟수만큼 독립적으로 추첨하므로 가능한 모든 조합을 한 번씩 생성하는 방식은 아닙니다.

생성 화면과 태그 관리 화면의 그룹은 한국어 이름순으로, 그룹 안의 태그 항목은 화면 이름순으로 표시합니다. 숫자가 포함된 이름은 자연스러운 숫자 순서로 정렬합니다.

Anima Prompt preset 버전에는 Prompt 본문과 Negative Prompt만 저장합니다. 태그 항목은 별도 DB에서 관리하며 생성할 때 현재 정의를 사용합니다. 제출한 작업에는 그 시점의 태그 정의, 선택 경로와 확정 Prompt가 남습니다. 기존 `Anima onepiece`의 최신 상황 두 개는 Prompt 본문의 `[SCENE]` 참조, 공통 SCENE 항목과 두 CHR 선택지로 옮겼습니다.

작업 화면에서는 한 번의 제출을 하나의 작업으로 표시합니다. 펼치면 개별 요청을 확인할 수 있고, 작업 결과 보기에서는 완료된 요청의 결과를 함께 보여줍니다. 일부 요청만 완료되거나 실패하면 진행 건수와 `일부 완료` 상태가 표시됩니다.

작업 요약에는 제출 시간·요청 설정의 비율·해상도·완료 장수를 순서대로 표시하고, 하위 요청에는 확정 Prompt와 선택한 LoRA 이름을 표시합니다. 설정이 없는 이전 이력은 비율과 해상도를 `—`로 표시합니다.

결과물 목록의 `작업` 버튼은 원래 생성 경로와 이력이 일치하는 파일에만 표시합니다. 누르면 작업 탭에서 해당 작업 한 건만 보여주며, `전체 작업 보기`로 필터를 해제할 수 있습니다. 이력이 삭제되거나 파일이 원래 위치에서 이동된 경우에는 버튼을 표시하지 않습니다.

결과물 크기는 용량 뒤에 비율·해상도로 표시합니다. 이미지는 파일의 실제 크기를 읽고, 영상은 연결된 요청의 설정값을 `(설정)`으로 표시합니다. 크기를 확인할 수 없는 파일은 `—`로 표시합니다.

생성 화면에서 선택적인 한 줄 작업 설명을 입력할 수 있으며 작업 목록에 표시됩니다. 대기·실행 중인 작업은 전체 또는 하위 요청별로 취소할 수 있습니다. 작업이 종료된 뒤에는 `이력만 삭제` 또는 `이력·결과물 삭제`를 선택합니다. 후자는 작업 history에 기록된 원래 생성 위치의 결과물만 삭제합니다. 이미 이동·삭제되어 없는 파일은 로그에 남기고 건너뛰며, 이동된 파일은 유지합니다.

결과물 목록은 24건씩 페이지 이동합니다. 이미지는 요청할 때 메모리에서 최대 384px WebP preview로 변환하며 별도 thumbnail 파일을 저장하지 않습니다. 영상은 목록에서 파일 정보만 표시하고 `열기`를 누를 때 원본을 불러옵니다. 결과물 탭 진입 또는 수동 새로고침 때 파일 목록을 다시 읽으며, 새로고침하면 첫 페이지로 돌아갑니다.

## 저장 위치

- Prompt, LoRA 조합, 작업 기록 SQLite, 임시 upload: 프로젝트의 `runtime/`
- 앱 로그: `runtime/logs/home_server.log` (5 MB마다 회전, 이전 로그 5개 보관). 콘솔에도 출력합니다.
- Workflow 원본: 프로젝트의 `data/workflows/`
- 생성물: `config.toml`의 `comfy.output_directory` 아래 `comfy.managed_output_folder`

작업 계층 DB 전환은 시작할 때 한 번 수행합니다. 기존 요청 단위 작업 기록은 초기화되지만 Prompt preset·버전과 LoRA 기본값·조합 preset, 생성물 파일은 유지됩니다.

생성물은 `{workflow}/{YYMMDD_HHmmss}_{seed}.{확장자}`를 기본으로 저장합니다. 예: `anima/261006_153012_123456789.png`. Anima는 `%time_%seed`, MiniMax는 `%date:yyMMdd_HHmmss%_%seed%` 예약어를 사용하며, MiniMax Saver에도 sampling과 동일한 seed 출력을 연결합니다. 시각은 ComfyUI Saver 실행 시점의 로컬 시간이고, 영상은 encoding 시작 직전입니다. Saver가 붙이는 counter나 `_audio` 접미사는 그대로 유지하며 앱에서 파일명을 후처리하지 않습니다. 작업의 결과 보기는 ComfyUI history의 실제 출력 파일명을 사용합니다. 기존 결과물도 계속 조회할 수 있으며, 목록은 앱이 열릴 때와 새로고침할 때 실제 폴더를 다시 읽습니다. 앱이 미완료 요청을 재시작 후 자동 재제출하지 않습니다.

## 외부 접속

앱 기본 포트는 8388입니다. 현재 구성은 HTTP와 단일 비밀번호 인증을 사용합니다. HTTP로 외부 접속하면 비밀번호와 전송 내용이 암호화되지 않습니다. 앱 설정과 ComfyUI 8188 서버 설정은 서로 독립적입니다.

## 개발 검증

API 테스트는 `python -m pytest -q`로 실행합니다. LoRA 조합의 browser 검증은 Edge와 Mock API를 사용하며 실제 GPU 생성 요청을 보내지 않습니다.

```powershell
npm install --prefix runtime/browser-check --no-package-lock --no-audit --no-fund playwright
$env:NODE_PATH = (Resolve-Path runtime/browser-check/node_modules).Path
node tests/browser_lora_presets.cjs
```
