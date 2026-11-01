param(
    [ValidateSet('setup', 'check', 'run')]
    [string]$Action = 'check',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunArguments
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.cache\python'
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache\pip'
$env:TEMP = Join-Path $projectRoot '.cache\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$uvPath = Join-Path $projectRoot '.tools\Scripts\uv.exe'

function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

if ($Action -eq 'setup') {
    if (-not (Test-Path -LiteralPath $uvPath)) {
        python -m venv (Join-Path $projectRoot '.tools')
        Assert-Exit 'Create tools environment'
        & (Join-Path $projectRoot '.tools\Scripts\python.exe') -m pip install --disable-pip-version-check 'uv==0.13.6'
        Assert-Exit 'Install uv'
    }
    & $uvPath sync --locked
    Assert-Exit 'Sync development environment'
} else {
    if (-not (Test-Path -LiteralPath $uvPath)) {
        throw 'Run scripts/dev.ps1 setup first.'
    }
    if ($Action -eq 'run') {
        if (-not $RunArguments) { throw 'Specify a command after run.' }
        & $uvPath run --locked --offline --no-sync @RunArguments
        Assert-Exit 'Run command'
    } else {
        & $uvPath run --locked --offline --no-sync pytest
        Assert-Exit 'Tests'
        & $uvPath run --locked --offline --no-sync ruff check .
        Assert-Exit 'Lint'
        & $uvPath run --locked --offline --no-sync ruff format --check .
        Assert-Exit 'Format'
        & $uvPath run --locked --offline --no-sync mypy
        Assert-Exit 'Types'
        & $uvPath run --locked --offline --no-sync python scripts/export_schemas.py --check
        Assert-Exit 'Schemas'
    }
}
