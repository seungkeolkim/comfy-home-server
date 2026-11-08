# Source Snapshot: enable-web-firewall.ps1

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\enable-web-firewall.ps1`
- Original Byte SHA-256: `407b4b9f75067b17f748eef26253390d859ef538225ee6eb5310a66a82f9cc0c`
- Snapshot Text SHA-256: `407b4b9f75067b17f748eef26253390d859ef538225ee6eb5310a66a82f9cc0c`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```powershell
#Requires -RunAsAdministrator
<#
.SYNOPSIS
Style Lab의 Embedded Python에 TCP 8389 접속만 허용합니다.
.DESCRIPTION
같은 실행 파일을 차단하는 기존 TCP Any 규칙에서는 8389만 제외합니다.
다른 Port와 UDP 차단은 유지하며, 변경 전 규칙을 JSON으로 보관합니다.
관리자 PowerShell에서 실행해야 합니다.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$applicationDirectory = [System.IO.Path]::GetFullPath($PSScriptRoot)
$pythonExecutablePath = (Resolve-Path -LiteralPath (Join-Path $applicationDirectory 'python\pythonw.exe')).Path
$firewallRuleName = 'StyleLabWeb-TCP-8389'
$remainingBlockedPorts = @('1-8388', '8390-65535')
$existingAllowRule = Get-NetFirewallRule -Name $firewallRuleName -ErrorAction SilentlyContinue

if ($existingAllowRule) {
    $existingApplicationFilter = $existingAllowRule | Get-NetFirewallApplicationFilter
    $existingPortFilter = $existingAllowRule | Get-NetFirewallPortFilter
    if ($existingAllowRule.Direction -ne 'Inbound' -or $existingAllowRule.Action -ne 'Allow' -or
        $existingApplicationFilter.Program -ine $pythonExecutablePath -or
        [string]$existingPortFilter.Protocol -notin @('TCP', '6') -or
        [string]$existingPortFilter.LocalPort -ne '8389') {
        throw '동일한 이름의 다른 Firewall 규칙이 있습니다. 자동으로 변경하지 않습니다.'
    }
}

$matchingBlockRules = @()
$enabledBlockRules = Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True
foreach ($candidateRule in $enabledBlockRules) {
    $applicationFilter = $candidateRule | Get-NetFirewallApplicationFilter
    if ($applicationFilter.Program -ine $pythonExecutablePath) {
        continue
    }
    $portFilter = $candidateRule | Get-NetFirewallPortFilter
    if ([string]$portFilter.Protocol -notin @('TCP', '6')) {
        continue
    }
    if (@($portFilter.LocalPort).Count -eq 1 -and $portFilter.LocalPort -eq 'Any') {
        $matchingBlockRules += $candidateRule
    } elseif ((@($portFilter.LocalPort) -join ',') -ne ($remainingBlockedPorts -join ',')) {
        throw "별도의 TCP 차단 규칙이 있습니다. 직접 검토해야 합니다: $($candidateRule.Name)"
    }
}

$backupDirectory = Join-Path $applicationDirectory 'data\web-server'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backupFilePath = Join-Path $backupDirectory ('firewall-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$originalRuleRecords = foreach ($matchingRule in $matchingBlockRules) {
    [ordered]@{
        Name = $matchingRule.Name
        Program = $pythonExecutablePath
        LocalPort = @('Any')
        Profile = [string]$matchingRule.Profile
    }
}
[ordered]@{
    Application = $pythonExecutablePath
    ExistingAllowRule = [bool]$existingAllowRule
    ModifiedBlockRules = @($originalRuleRecords)
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $backupFilePath -Encoding UTF8

$updatedBlockRules = @()
$createdAllowRule = $false
try {
    # 명시적인 Block은 Allow보다 우선하므로 해당 실행 파일의 8389만 예외로 둡니다.
    foreach ($matchingRule in $matchingBlockRules) {
        $matchingRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort $remainingBlockedPorts
        $updatedBlockRules += $matchingRule
    }
    if ($existingAllowRule) {
        $existingAllowRule | Enable-NetFirewallRule
    } else {
        New-NetFirewallRule -Name $firewallRuleName -DisplayName 'Style Lab Web TCP 8389' -Direction Inbound -Action Allow -Enabled True -Profile Any -Program $pythonExecutablePath -Protocol TCP -LocalPort 8389 | Out-Null
        $createdAllowRule = $true
    }
} catch {
    $setupError = $_
    foreach ($updatedRule in $updatedBlockRules) {
        $updatedRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort Any
    }
    if ($createdAllowRule) {
        Remove-NetFirewallRule -Name $firewallRuleName
    }
    throw $setupError
}

Get-NetFirewallRule -Name $firewallRuleName | Format-Table DisplayName, Enabled, Direction, Action, Profile
Write-Host 'TCP 8389 설정을 완료했습니다. 같은 네트워크의 다른 기기에서 접속을 확인해 주세요.'
Write-Host "변경 전 규칙 기록: $backupFilePath"
```
