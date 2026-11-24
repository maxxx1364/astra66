# TBAE live system - one-time setup on Windows Server.
# Run in an elevated PowerShell from the repository's tbae folder:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
#
# What it does:
#   1. creates .venv and installs requirements
#   2. creates C:\tbae (config, secrets, database, logs) outside the repo
#   3. registers a scheduled task "TBAE-Live" that starts at boot, runs whether
#      or not anyone is logged in, and restarts after a failure
# It does NOT install Python, Git or MetaTrader 5 (see docs\WINDOWS.md).

$ErrorActionPreference = "Stop"
$Tbae = (Resolve-Path "$PSScriptRoot\..\..").Path
$Home_ = "C:\tbae"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found. Install Python 3.12 (64-bit) with 'Add to PATH' first."
}

Write-Host "== venv + requirements =="
if (-not (Test-Path "$Tbae\.venv")) { python -m venv "$Tbae\.venv" }
& "$Tbae\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Tbae\.venv\Scripts\python.exe" -m pip install -r "$Tbae\requirements.txt"

Write-Host "== C:\tbae =="
New-Item -ItemType Directory -Force -Path $Home_, "$Home_\logs" | Out-Null
if (-not (Test-Path "$Home_\live.json")) {
    & "$Tbae\.venv\Scripts\python.exe" -m live default-config | Out-File -Encoding utf8 "$Home_\live.json"
    # keep the database outside the repository
    (Get-Content "$Home_\live.json") -replace '"db_path": "data/live.sqlite3"', '"db_path": "C:/tbae/live.sqlite3"' |
        Set-Content -Encoding utf8 "$Home_\live.json"
}
if (-not (Test-Path "$Home_\live.env")) {
    @"
# KEY=VALUE, one per line. Not needed for scanning or paper trading.
# TABDEAL_API_KEY=
# TABDEAL_API_SECRET=
# TBAE_LIVE_TRADING=yes     <- only after paper results have been reviewed
"@ | Out-File -Encoding utf8 "$Home_\live.env"
}
# secrets file: Administrators and SYSTEM only
icacls "$Home_\live.env" /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null

Write-Host "== scheduled task TBAE-Live =="
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Tbae\deploy\windows\run.ps1`"" `
    -WorkingDirectory $Tbae
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "TBAE-Live" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "TBAE-Live"

Write-Host ""
Write-Host "Done. Dashboard: http://127.0.0.1:8100 (open it inside the server via RDP)."
Write-Host "Logs:      C:\tbae\logs\live.log"
Write-Host "Config:    C:\tbae\live.json      Secrets: C:\tbae\live.env"
Write-Host "Update:    powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1"
