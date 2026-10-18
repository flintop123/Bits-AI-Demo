$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$logDirectory = Join-Path $project "artifacts\phase4"
$logFile = Join-Path $logDirectory "scheduled_mandi.log"

if (-not (Test-Path $python)) {
    throw "Python environment not found at $python"
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location $project

try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if (-not (Test-Path $dockerDesktop)) {
            throw "Docker Desktop is not available"
        }
        Start-Process $dockerDesktop
        $ready = $false
        for ($attempt = 1; $attempt -le 12; $attempt++) {
            Start-Sleep -Seconds 5
            docker info 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $ready = $true
                break
            }
        }
        if (-not $ready) {
            throw "Docker Desktop did not become ready within 60 seconds"
        }
    }

    docker start bihar-mongodb 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "MongoDB container could not be started"
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$stamp] Starting scheduled mandi collection"
    # Refresh a rolling window so late postings, corrections, and a missed
    # workstation run are recovered without creating duplicates.
    & $python run_phase4_mandi_pipeline.py --days 7 2>&1 |
        Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Daily mandi collection returned exit code $LASTEXITCODE"
    }
}
catch {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$stamp] FAILED: $($_.Exception.Message)"
    throw
}
