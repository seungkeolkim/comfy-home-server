# Source Snapshot: run-web.ps1

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\run-web.ps1`
- Original Byte SHA-256: `7b3d33b6e0d7c188255bb2db80ff8d165978cb05b4ad98a2f311b38c09e620da`
- Snapshot Text SHA-256: `7b3d33b6e0d7c188255bb2db80ff8d165978cb05b4ad98a2f311b38c09e620da`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```powershell
<#
.SYNOPSIS
Style Lab Web을 현재 창 또는 독립된 Background 프로세스로 실행합니다.
.DESCRIPTION
기본 실행은 Ctrl+C로 종료할 수 있습니다. Background 실행은 Windows WMI를
통해 현재 사용자 Session에서 시작하므로 호출한 Terminal 종료와 분리됩니다.
#>
param(
    [int]$Port = 8389,
    [string]$BindAddress = '0.0.0.0',
    [switch]$SetPassword,
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$styleLabPythonPath = Join-Path $PSScriptRoot 'python\python.exe'
$styleLabServerPath = Join-Path $PSScriptRoot 'web_server.py'
if ($SetPassword) {
    & $styleLabPythonPath -B $styleLabServerPath --set-password
} elseif ($Background) {
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw 'Port는 1부터 65535까지 지정할 수 있습니다.'
    }
    if ($BindAddress -match '["\s]') {
        throw 'BindAddress에는 공백이나 따옴표를 사용할 수 없습니다.'
    }
    $existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($existingListener) {
        throw "Port $Port 에 이미 실행 중인 서버가 있습니다. 기존 프로세스를 확인해 주세요."
    }
    $backgroundPythonPath = Join-Path $PSScriptRoot 'python\pythonw.exe'
    $backgroundCommandLine = '"' + $backgroundPythonPath + '" -B -X utf8 "' + $styleLabServerPath + '" --host ' + $BindAddress + ' --port ' + $Port
    $processCreationResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $backgroundCommandLine
        CurrentDirectory = $PSScriptRoot
    }
    if ($processCreationResult.ReturnValue -ne 0) {
        throw "Background 실행에 실패했습니다. Windows 오류 코드: $($processCreationResult.ReturnValue)"
    }
    $backgroundProcessIdentifier = [int]$processCreationResult.ProcessId
    $serverReady = $false
    for ($startupAttempt = 0; $startupAttempt -lt 40; $startupAttempt++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-Process -Id $backgroundProcessIdentifier -ErrorAction SilentlyContinue)) {
            throw '서버가 시작 도중 종료되었습니다. data/web-server/server.log를 확인해 주세요.'
        }
        $serverListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($serverListener.OwningProcess -contains $backgroundProcessIdentifier) {
            $serverReady = $true
            break
        }
    }
    if (-not $serverReady) {
        throw '서버 시작을 아직 확인하지 못했습니다. data/web-server/server.log를 확인해 주세요.'
    }
    Write-Host "Style Lab Web: http://127.0.0.1:$Port (PID $backgroundProcessIdentifier)"
    exit 0
} else {
    & $styleLabPythonPath -B $styleLabServerPath --host $BindAddress --port $Port
}
exit $LASTEXITCODE
```
