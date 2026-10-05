# Comfy Home Server

ComfyUI API에 Anima 이미지와 DaSiWa MiniMax H3 영상을 bulk로 제출하고, 집 안과 mobile에서 결과물을 확인하는 웹 앱입니다. 기획 결정사항은 [PLAN.md](PLAN.md)에 기록했습니다.

## 시작

Python 3.11 이상에서 실행합니다.

```powershell
python -m pip install -r requirements.txt
python -m home_server
```

브라우저에서 `http://localhost:8388`로 접속합니다. 설정은 프로젝트의 [config.toml](config.toml)에 있습니다. 기본 비밀번호는 설정 파일에 평문으로 저장되어 있습니다.

ComfyUI는 별도로 실행되어 있어야 합니다. 앱은 `config.toml`의 `comfy.endpoint`로 API 요청을 보내며 기존 ComfyUI의 기동 설정을 변경하지 않습니다.

## 주요 화면

- **생성:** workflow 선택, Prompt와 상황 checkbox, LoRA, 해상도 및 workflow 옵션, Batch 제출
- **작업:** 앱이 제출한 `prompt_id`의 대기·실행·완료 상태와 대기 요청 취소
- **결과물:** `from_home_server`의 현재 파일 조회와 해당 폴더 내부 이동
- **Prompt:** 상황 builder와 preset 버전 저장

LoRA 목록은 ComfyUI API에서 새로 읽습니다. Workflow별 기본 강도를 저장할 수 있으며 새 파일은 목록에서 구분됩니다.

MiniMax H3는 브라우저에서 여러 이미지를 선택하거나 폴더를 선택해 제출합니다. Anima는 요청 수와 workflow 내부 batch size를 지정할 수 있습니다.

## 저장 위치

- Prompt, 작업 기록 SQLite, 임시 upload: 프로젝트의 `runtime/`
- Workflow 원본: 프로젝트의 `data/workflows/`
- 생성물: `config.toml`의 `comfy.output_directory` 아래 `comfy.managed_output_folder`

생성물은 `{workflow}/{YYYY-MM-DD}/{batch_id}/{request_id}.{확장자}` 규칙으로 저장합니다. Saver node가 단일 결과물에 추가한 접미사는 완료 후 앱이 제거합니다. 결과물 목록은 앱이 열릴 때와 새로고침할 때 실제 폴더를 다시 읽습니다. 앱이 미완료 요청을 재시작 후 자동 재제출하지 않습니다.

## 외부 접속

앱 기본 포트는 8388입니다. 현재 구성은 HTTP와 단일 비밀번호 인증을 사용합니다. HTTP로 외부 접속하면 비밀번호와 전송 내용이 암호화되지 않습니다. 앱 설정과 ComfyUI 8188 서버 설정은 서로 독립적입니다.
