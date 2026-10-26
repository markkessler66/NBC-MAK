# Desktop launcher for Personal Weather Lab.
#
# Makes sure the backend is serving, then opens the dashboard in its own
# browser window. Runs hidden, so anything that goes wrong is surfaced in a
# message box rather than on a console nobody is looking at.
param(
    [string]$Url = "http://127.0.0.1:8000",
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$task = "Personal Weather Lab"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Show-Problem([string]$message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $message, "Personal Weather Lab",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
}

function Test-Backend {
    try {
        Invoke-WebRequest "$Url/api/meta" -UseBasicParsing -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-Backend {
    $scheduled = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if ($scheduled) {
        if ($scheduled.State -ne "Running") { Start-ScheduledTask -TaskName $task }
        return
    }
    # No scheduled task on this machine: run the same resilient runner directly.
    $runner = Join-Path $root "backend\run_server.ps1"
    if (-not (Test-Path $runner)) {
        throw "Neither the '$task' scheduled task nor $runner was found."
    }
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner
    )
}

try {
    if (-not (Test-Backend)) {
        Start-Backend
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while (-not (Test-Backend)) {
            if ((Get-Date) -ge $deadline) {
                throw "The backend did not start within $TimeoutSeconds seconds. " +
                      "Check backend\data\server.log for details."
            }
            Start-Sleep -Seconds 2
        }
    }

    # Prefer an app window (no tabs or address bar) over a browser tab.
    $edge = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($edge) {
        Start-Process $edge -ArgumentList "--app=$Url", "--window-size=1600,1000"
    } else {
        Start-Process $Url
    }
} catch {
    Show-Problem $_.Exception.Message
    exit 1
}
