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
- **작업:** 앱이 제출한 `prompt_id`의 대기·실행·완료 상태와 대기 요청 취소
- **결과물:** `from_home_server`의 현재 파일 조회와 해당 폴더 내부 이동
- **Prompt:** Anima 상황 builder와 MiniMax 평문 편집, preset 버전 저장

LoRA 목록은 ComfyUI API에서 새로 읽습니다. Workflow별 기본 강도를 저장할 수 있으며 새 파일은 목록에서 구분됩니다.

MiniMax H3는 wildcard 없이 평문 Prompt 하나를 입력하고, 브라우저에서 선택한 여러 이미지나 폴더의 모든 이미지에 같은 문구를 적용합니다. Anima는 요청 횟수 N을 지정하면 ComfyUI에 N개의 개별 요청을 제출합니다. 각 요청은 상황과 wildcard, random seed를 새로 선택하고 한 장씩 생성합니다.

## 저장 위치

- Prompt, 작업 기록 SQLite, 임시 upload: 프로젝트의 `runtime/`
- 앱 로그: `runtime/logs/home_server.log` (5 MB마다 회전, 이전 로그 5개 보관). 콘솔에도 출력합니다.
- Workflow 원본: 프로젝트의 `data/workflows/`
- 생성물: `config.toml`의 `comfy.output_directory` 아래 `comfy.managed_output_folder`

생성물은 `{workflow}/{YYMMDD_HHmmss}_{seed}.{확장자}`를 기본으로 저장합니다. 예: `anima/261006_153012_123456789.png`. Anima는 `%time_%seed`, MiniMax는 `%date:yyMMdd_HHmmss%_%seed%` 예약어를 사용하며, MiniMax Saver에도 sampling과 동일한 seed 출력을 연결합니다. 시각은 ComfyUI Saver 실행 시점의 로컬 시간이고, 영상은 encoding 시작 직전입니다. Saver가 붙이는 counter나 `_audio` 접미사는 그대로 유지하며 앱에서 파일명을 후처리하지 않습니다. 작업의 결과 보기는 ComfyUI history의 실제 출력 파일명을 사용합니다. 기존 결과물도 계속 조회할 수 있으며, 목록은 앱이 열릴 때와 새로고침할 때 실제 폴더를 다시 읽습니다. 앱이 미완료 요청을 재시작 후 자동 재제출하지 않습니다.

## 외부 접속

앱 기본 포트는 8388입니다. 현재 구성은 HTTP와 단일 비밀번호 인증을 사용합니다. HTTP로 외부 접속하면 비밀번호와 전송 내용이 암호화되지 않습니다. 앱 설정과 ComfyUI 8188 서버 설정은 서로 독립적입니다.
