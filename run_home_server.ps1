param(
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$virtualEnvironmentDirectory = Join-Path $projectDirectory '.venv'
$virtualEnvironmentPython = Join-Path $virtualEnvironmentDirectory 'Scripts\python.exe'
$requirementsPath = Join-Path $projectDirectory 'requirements.txt'
$requirementsStampPath = Join-Path $virtualEnvironmentDirectory 'requirements.sha256'

if (-not (Test-Path -LiteralPath $virtualEnvironmentPython)) {
    & python -m venv $virtualEnvironmentDirectory
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 가상환경을 만들지 못했습니다.'
    }
}

$currentRequirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
$installedRequirementsHash = if (Test-Path -LiteralPath $requirementsStampPath) {
    (Get-Content -LiteralPath $requirementsStampPath -Raw).Trim()
} else {
    $null
}

if ($currentRequirementsHash -ne $installedRequirementsHash) {
    & $virtualEnvironmentPython -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 의존성을 설치하지 못했습니다.'
    }
    Set-Content -LiteralPath $requirementsStampPath -Value $currentRequirementsHash -Encoding ascii
}

Push-Location -LiteralPath $projectDirectory
try {
    $serverArguments = @('-m', 'home_server')
    if (-not $NoReload) {
        $serverArguments += '--reload'
    }

    & $virtualEnvironmentPython @serverArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Comfy Home Server가 오류로 종료되었습니다.'
    }
} finally {
    Pop-Location
}
