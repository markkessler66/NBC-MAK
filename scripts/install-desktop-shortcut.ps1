# Creates (or refreshes) the "Personal Weather Lab" shortcut on the desktop.
# Safe to re-run; it overwrites the existing shortcut in place.
param([string]$ShortcutName = "Personal Weather Lab")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$launcher = Join-Path $root "scripts\start-weather-lab.ps1"
$icon = Join-Path $root "assets\weather-lab.ico"
$link = Join-Path ([Environment]::GetFolderPath('Desktop')) "$ShortcutName.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$sc.WorkingDirectory = $root
$sc.IconLocation = "$icon,0"
$sc.Description = "Open the Personal Weather Lab dashboard"
$sc.WindowStyle = 7   # start minimized so the host console does not flash
$sc.Save()

Write-Host "shortcut written to $link"
