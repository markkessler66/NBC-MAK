# Restart the "Personal Weather Lab" service so it picks up new code.
#
# Stop-ScheduledTask on its own leaves the uvicorn child process running, which
# silently keeps serving the old modules, so the workers are killed explicitly.
param([int]$TimeoutSeconds = 120)

$task = "Personal Weather Lab"

Stop-ScheduledTask -TaskName $task
Start-Sleep -Seconds 2

Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
    Where-Object { $_.CommandLine -like "*uvicorn app.main:app*" } |
    ForEach-Object {
        Write-Host "stopping uvicorn pid $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName $task

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-RestMethod "http://127.0.0.1:8000/api/meta" -TimeoutSec 5 | Out-Null
        Write-Host "backend up"
        exit 0
    } catch {
        Start-Sleep -Seconds 4
    }
}
Write-Error "backend did not come up within $TimeoutSeconds s"
exit 1
