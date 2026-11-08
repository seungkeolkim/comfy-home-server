# Source Snapshot: run.bat

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\run.bat`
- Original Byte SHA-256: `ddda1701dd548e40b4b1f7a2b8604224554f6939aec8759aa137d7853fca262f`
- Snapshot Text SHA-256: `100c175b4ef23fcf3a2df47b062a4f9030d054d9c3cc00ad425168fcfb78d568`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```bat
@echo off
cd /d "%~dp0"
rem python\ is the embedded Python: shipped in the release zip, made by _dev\setup_python.bat in a source checkout.
if not exist "python\pythonw.exe" (echo python\ is missing: run _dev\setup_python.bat first. & pause & exit /b 1)
start "" "python\pythonw.exe" "%~dp0main.py"
exit /b
```
