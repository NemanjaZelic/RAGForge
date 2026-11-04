param(
    [ValidateSet('scale', 'rfc-rebuild', 'both')]
    [string]$Jobs = 'both',
    [switch]$PublishPrivate,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$Jobs = $Jobs.ToLowerInvariant()
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$supervisor = Join-Path $PSScriptRoot 'background_benchmarks.py'
$arguments = @('-B', $supervisor, '--jobs', $Jobs)
if ($PublishPrivate) { $arguments += '--publish-private' }
# Validation starts no process, changes no recipe and performs no network calls.
& $python @arguments --check
if ($LASTEXITCODE -ne 0) { throw 'Frozen benchmark validation failed.' }
if ($CheckOnly) { return }
$active = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($projectRoot) -and (
        ($Jobs -in @('scale', 'both') -and $_.CommandLine -match 'run_scale_benchmark\.py') -or
        ($Jobs -in @('rfc-rebuild', 'both') -and $_.CommandLine -match 'queue_quality_followup\.py')
    )
}
if ($active) { throw 'A selected benchmark controller is already running; inspect its existing status.' }

foreach ($path in @($python, $supervisor)) {
    if ($path.Contains('"')) { throw 'Unexpected quote in executable path.' }
}
$command = '"' + $python + '" -B "' + $supervisor + '" --jobs ' + $Jobs
if ($PublishPrivate) { $command += ' --publish-private' }
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
    ShowWindow = [uint16]0
    CreateFlags = [uint32]8
    PriorityClass = [uint32]16384
}
$launch = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $command
    CurrentDirectory = $projectRoot
    ProcessStartupInformation = $startup
}
if ($launch.ReturnValue -ne 0) { throw "Windows background launch failed: $($launch.ReturnValue)" }
$created = Get-CimInstance Win32_Process -Filter "ProcessId=$($launch.ProcessId)"
$broker = Get-CimInstance Win32_Process -Filter "ProcessId=$($created.ParentProcessId)"
if ($broker.Name -ne 'WmiPrvSE.exe') { throw 'Unexpected Windows process ancestry.' }
$receipt = [pscustomobject]@{
    launcher_pid = $launch.ProcessId
    broker_pid = $broker.ProcessId
    window_hidden = $true
    priority = 'BelowNormal, process-only'
    scheduled_task_installed = $false
    command = $command
}
$stateRoot = Join-Path $projectRoot '.cache\background-benchmarks-v1'
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateRoot 'launch.json') -Encoding utf8
$receipt | ConvertTo-Json
