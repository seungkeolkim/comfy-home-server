# Source Snapshot: README_WEB.md

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\README_WEB.md`
- Original Byte SHA-256: `cf15c2d5dd5594382714ffbaee628d07b8a96a2dfda5bb26dfbfee5cdae6c9fc`
- Snapshot Text SHA-256: `cf15c2d5dd5594382714ffbaee628d07b8a96a2dfda5bb26dfbfee5cdae6c9fc`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

````markdown
# Style Lab Web

기존 Style Lab의 Engine과 `data/`를 그대로 사용하는 Browser용 실행 모드입니다.
PC와 모바일에서 실제 이미지, 작가·LoRA, 조합, 순위, 투표, 진화, 융합, 다듬기를 관리합니다.

## 실행과 접속

```powershell
.\run-web.ps1
```

Terminal 종료와 무관하게 실행하려면 `./run-web.ps1 -Background`를 사용합니다.
Windows 로그인 시 자동 실행하는 설정은 추가하지 않습니다.

- 기본 접속: `http://127.0.0.1:8389`
- 같은 네트워크에서는 서버 PC의 IP와 Port 8389로 접속합니다.
- 기본 Listen 주소는 `0.0.0.0`입니다. 공유기 설정은 변경하지 않습니다.
- Desktop 앱과 웹 서버는 같은 데이터를 동시에 열 수 없습니다. 먼저 켠 쪽만 실행됩니다.
- 여러 Browser는 하나의 웹 서버에 접속해 같은 데이터를 사용합니다. 비교 대상이 바뀐 오래된 투표는 거부됩니다.

현재 서버 PC의 LAN 주소는 `http://192.168.0.8:8389`입니다. IP가 바뀌면 주소도 바뀝니다.
Windows Firewall의 해당 `pythonw.exe` Public TCP/UDP 규칙이 현재 Allow인 것을 확인했습니다.
향후 Firewall에서 차단된 경우에만 관리자 PowerShell에서 다음 명령을 실행합니다.

```powershell
& 'C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\enable-web-firewall.ps1'
```

이 스크립트는 해당 실행 파일의 TCP 8389만 허용하고, 기존 TCP 차단에서는 8389만 제외합니다.
다른 Port와 UDP 차단은 유지합니다. 변경 전 규칙은 `data/web-server/firewall-before-*.json`에 기록합니다.
공유기 Port Forwarding이나 인터넷 공개 설정은 별도로 변경하지 않습니다.
실행 창에서 켠 서버는 `Ctrl+C`로 종료합니다.

첫 실행에서 접속 비밀번호를 생성합니다. 원문은 `data/web-server/initial-password.txt`에,
PBKDF2 Hash는 `data/web-server/authentication.json`에 저장합니다. 이 파일들은 웹으로 제공하지 않습니다.

비밀번호를 직접 변경하려면 웹 서버를 종료하고 다음 명령을 사용한 뒤 다시 실행합니다.

```powershell
.\run-web.ps1 -SetPassword
```

Session은 12시간 후 만료되며 서버 재시작 시 모두 무효화됩니다.
HTTPS Reverse Proxy를 쓰는 경우 `web_server.py --secure-cookie`로 Secure Cookie를 사용합니다.
서버를 다른 프로그램에서 관리할 때는 작업 유무를 확인하고 종료해야 합니다.

## 기존 데이터와 Workflow

- 실제 데이터는 기존 `data/state.json`, `data/images`, `data/thumbs`를 사용합니다.
- `data/workflow.json`의 Custom NegPip Workflow를 사용합니다.
- CFG, Steps, Seed, 크기, Sampler, Scheduler는 기존 Engine 설정을 따릅니다.
- Custom Workflow에서 모델·Text Encoder·VAE는 Workflow에 지정된 파일을 사용합니다.
- CFG 1에서는 일반 Negative Prompt가 효과를 내지 않습니다. Positive의 `(blurry:-1)` 등으로 NegPip을 사용합니다.
- ZIP Export는 Browser 다운로드, Import는 파일 선택과 확인 후 업로드로 동작합니다.
- 서버 PC의 파일 탐색기 열기와 Windows 파일 Drag는 Browser 모드에서 실행하지 않습니다.
- 이미지·API·Export·Import에는 로그인 인증을 적용하고 변경 요청은 CSRF Token과 Origin을 확인합니다.

## LoRA 적용 기록

Model Only 설정에서 발생하는 Text Encoder 미사용 Key는 반복 Warning Toast로 표시하지 않습니다.
조합 화면의 LoRA 영역에서 **LoRA 적용 기록**을 펼치면 최근 생성의 구성요소별 안내를 볼 수 있습니다.
모델·미확인 Key 누락과 Shape/Patch 오류는 계속 경고하고, 같은 종류의 조합 경고는 반복하지 않습니다.
여러 LoRA를 함께 쓴 기록은 원인 파일을 특정하지 않습니다. Log가 잘리면 전체 정상으로 판정하지 않습니다.
상세 기록은 `data/lora_warnings.log`에 남으며 모바일 알림은 동시에 최대 2개 표시됩니다.

검증 명령: `./python/python.exe -B -X utf8 -m unittest discover -s tests_web -p "test_*.py" -v`

## 파일과 로그

- `web_server.py`: HTTP Server, 인증, Engine API, 파일 다운로드·업로드
- `web_browser/`: Browser용 UI. 기존 `web/` Desktop 파일은 유지합니다.
- `app/data_access.py`: 두 실행 모드의 데이터 접근 Mutex
- `data/web-server/server.log`: 서버 수명주기와 오류
- `data/web-server/server.json`: 실행 중인 서버 PID, Listen 주소와 Port
- `data/backups/before-web-*.zip`: 웹 모드 적용 전 코드·상태·Workflow 백업
````
