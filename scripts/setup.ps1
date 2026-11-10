param(
    [string]$ModelDirectory = '',
    [ValidateSet('multilingual', 'en')]
    [string]$DocumentLanguage = 'multilingual',
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONIOENCODING = 'utf-8'
if ($Offline) {
    $env:UV_OFFLINE = '1'
    $env:PIP_NO_INDEX = '1'
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.tools\Scripts\uv.exe'))) {
        throw 'Offline setup needs the existing local tools. Run setup.cmd online once first.'
    }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Install 64-bit Python 3.13 with Add python.exe to PATH, then run setup.cmd again.'
}
& python -c "import sys,struct; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize('P') == 8 else 2)"
if ($LASTEXITCODE -ne 0) { throw 'RAGForge needs 64-bit Python 3.11 or newer (3.13 tested).' }
Write-Host 'Installing the locked local environment...'
& (Join-Path $PSScriptRoot 'dev.ps1') setup
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed.' }
$setupArgs = @('python', (Join-Path $PSScriptRoot 'setup_models.py'), '--document-language', $DocumentLanguage)
if ($ModelDirectory) { $setupArgs += @('--models-directory', $ModelDirectory) }
if ($Offline) { $setupArgs += '--offline' }
& (Join-Path $PSScriptRoot 'dev.ps1') run @setupArgs
if ($LASTEXITCODE -ne 0) { throw 'Model setup failed.' }
& (Join-Path $PSScriptRoot 'dev.ps1') run ragforge doctor
if ($LASTEXITCODE -ne 0) { throw 'Runtime checks failed.' }
$documents = Join-Path $projectRoot 'documents'
New-Item -ItemType Directory -Force -Path $documents | Out-Null
Write-Host ''
Write-Host 'Setup complete. Put PDF/TXT/MD/HTML documents into:'
Write-Host $documents
Write-Host 'Then: .\ragforge.cmd build'
Write-Host 'Optional agent integration: .\ragforge.cmd agent'
