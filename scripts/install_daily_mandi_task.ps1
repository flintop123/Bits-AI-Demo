param(
    [string]$DailyTime = "06:30"
)

$ErrorActionPreference = "Stop"
$taskName = "BiharAgriculture-DailyMandiIngestion"
$runner = Join-Path $PSScriptRoot "run_daily_mandi.ps1"

if (-not (Test-Path $runner)) {
    throw "Daily runner not found at $runner"
}

try {
    [void][datetime]::ParseExact($DailyTime, "HH:mm", $null)
}
catch {
    throw "DailyTime must use 24-hour HH:mm format, for example 06:30"
}

$taskCommand = (
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' +
    $runner + '"'
)

schtasks.exe /Create /F /SC DAILY /TN $taskName /TR $taskCommand /ST $DailyTime
if ($LASTEXITCODE -ne 0) {
    throw "Windows Task Scheduler did not create the task"
}

Write-Host "Scheduled task created: $taskName"
Write-Host "Daily time: $DailyTime"
Write-Host "Runner: $runner"
Write-Host "Inspect with: schtasks /Query /TN `"$taskName`" /V /FO LIST"
