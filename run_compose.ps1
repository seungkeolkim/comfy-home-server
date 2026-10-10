<#
.SYNOPSIS
Comfy Home Server의 Docker Compose를 시작하거나 종료합니다.
.EXAMPLE
.\run_compose.ps1 up
.EXAMPLE
.\run_compose.ps1 down
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down')]
    [string]$Action = 'up'
)

$ErrorActionPreference = 'Stop'

function Invoke-ProjectDockerCompose {
    <#
    .SYNOPSIS
    현재 작업 폴더와 무관하게 프로젝트의 Compose 파일로 지정한 명령을 실행합니다.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('up', 'down')]
        [string]$ComposeAction
    )

    $projectDirectory = $PSScriptRoot
    $composeFilePath = Join-Path $projectDirectory 'compose.yaml'
    if (-not (Test-Path -LiteralPath $composeFilePath -PathType Leaf)) {
        throw "Compose 파일을 찾을 수 없습니다: $composeFilePath"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI를 찾을 수 없습니다. Docker Desktop 설치와 PATH 설정을 확인해 주세요.'
    }

    $composeArguments = @('compose', '--project-directory', $projectDirectory, '-f', $composeFilePath)
    if ($ComposeAction -eq 'up') {
        $runtimeDirectory = Join-Path $projectDirectory 'runtime'
        New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
        $composeArguments += @('up', '-d', '--build')
    } else {
        $composeArguments += 'down'
    }

    & docker @composeArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose $ComposeAction 실행에 실패했습니다. Exit code: $LASTEXITCODE"
    }
}

Invoke-ProjectDockerCompose -ComposeAction $Action
