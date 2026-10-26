# Personal Weather Lab — resilient backend runner.
# Launched by the "Personal Weather Lab" scheduled task at logon; restarts
# uvicorn automatically if it ever exits, and logs to backend/data/server.log.

$backend = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $backend
$python = Join-Path $backend ".venv\Scripts\python.exe"
$dataDir = Join-Path $backend "data"
$log = Join-Path $dataDir "server.log"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

while ($true) {
    # Simple log rotation: keep one 10 MB generation.
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) {
        Move-Item -Force $log "$log.old"
    }
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $log "[$ts] starting uvicorn"
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 *>> $log
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $log "[$ts] uvicorn exited (code $LASTEXITCODE); restarting in 5 s"
    Start-Sleep -Seconds 5
}
