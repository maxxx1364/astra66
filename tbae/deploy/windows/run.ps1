# Started by the "TBAE-Live" scheduled task.  Loads C:\tbae\live.env into the
# process environment, then runs the live system and restarts it if it exits.
$ErrorActionPreference = "Continue"
$Tbae = (Resolve-Path "$PSScriptRoot\..\..").Path
$Home_ = "C:\tbae"
$Log = "$Home_\logs\live.log"

if (Test-Path "$Home_\live.env") {
    foreach ($line in Get-Content "$Home_\live.env") {
        $l = $line.Trim()
        if ($l -and -not $l.StartsWith("#") -and $l.Contains("=")) {
            $k, $v = $l.Split("=", 2)
            [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
        }
    }
}

Set-Location $Tbae
while ($true) {
    # rotate the log at ~20 MB
    if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 20MB) {
        Move-Item -Force $Log "$Log.1"
    }
    "$(Get-Date -Format s) starting live runner" | Out-File -Append -Encoding utf8 $Log
    & "$Tbae\.venv\Scripts\python.exe" -m live run --config "$Home_\live.json" `
        --dashboard --host 127.0.0.1 --port 8100 *>> $Log
    "$(Get-Date -Format s) runner exited with code $LASTEXITCODE; restarting in 10 s" |
        Out-File -Append -Encoding utf8 $Log
    Start-Sleep -Seconds 10
}
