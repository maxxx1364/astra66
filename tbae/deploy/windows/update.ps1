# Pull the latest code, refresh dependencies, run the tests, restart the runner.
# The restart only happens if the tests pass, so a broken commit never
# replaces a working runner.
#   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 [-Branch main]
param([string]$Branch = "main")
$ErrorActionPreference = "Stop"
$Tbae = (Resolve-Path "$PSScriptRoot\..\..").Path
$Py = "$Tbae\.venv\Scripts\python.exe"

Set-Location $Tbae
git fetch origin $Branch
git checkout $Branch
git pull --ff-only origin $Branch
& $Py -m pip install -r requirements.txt --quiet

& $Py -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed - runner NOT restarted. Still running the previous code." -ForegroundColor Red
    exit 1
}

# the running python process holds the old code; restart the task's loop
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*-m live run*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Updated to $(git rev-parse --short HEAD); runner restarts within 10 s." -ForegroundColor Green
