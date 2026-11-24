# Export the current verified dashboard snapshot without updating MongoDB.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("weekly", "monthly")]
    [string]$Frequency,
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) {
    $PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python executable not found: $PythonExe"
}
$Snapshot = Join-Path $Root "docs\data\dashboard_snapshot.json"
$Export = Join-Path $PSScriptRoot "export_mandi_period_report.py"
$OutputDir = Join-Path $Root "artifacts\period_reports"
[void][System.IO.Directory]::CreateDirectory($OutputDir)
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfff'Z'")
$Output = Join-Path $OutputDir "mandi_${Frequency}_$Stamp.csv"
& $PythonExe $Export --snapshot $Snapshot --frequency $Frequency --output $Output
exit $LASTEXITCODE
