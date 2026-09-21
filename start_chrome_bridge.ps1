$ErrorActionPreference = "Stop"

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = Join-Path $env:USERPROFILE "linkedin-chrome-profile"
$chromePort = 9222
$bridgePort = 8765
$bridgeExe = Join-Path $PSScriptRoot "dist\chrome-bridge.exe"

if (-not (Test-Path $chrome)) {
    $chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    throw "Chrome not found. Please update the Chrome path in this script."
}
if (-not (Test-Path $bridgeExe)) {
    throw "Chrome Bridge EXE not found: $bridgeExe"
}
if (-not (Test-Path $profile)) {
    New-Item -ItemType Directory -Path $profile -Force | Out-Null
}

try {
    Invoke-RestMethod "http://127.0.0.1:$chromePort/json/version" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome CDP is already running on port $chromePort." -ForegroundColor Green
} catch {
    Write-Host "Starting dedicated Chrome..." -ForegroundColor Cyan
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-port=$chromePort",
        "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*",
        "--user-data-dir=$profile"
    )
    Start-Sleep -Seconds 3
}

try {
    Invoke-RestMethod "http://127.0.0.1:$chromePort/json/version" -TimeoutSec 5 | Out-Null
} catch {
    throw "Chrome CDP on port $chromePort did not start successfully."
}

try {
    Invoke-RestMethod "http://127.0.0.1:$bridgePort/health" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome Bridge is already running on port $bridgePort." -ForegroundColor Green
    exit 0
} catch {}

Write-Host "Starting Windows Chrome Bridge on port $bridgePort..." -ForegroundColor Cyan
Write-Host "Keep this window open while using the extractor." -ForegroundColor Yellow

$env:LOCAL_CHROME_CDP_URL = "http://127.0.0.1:$chromePort"
$env:CHROME_BRIDGE_HOST = "0.0.0.0"
$env:CHROME_BRIDGE_PORT = "$bridgePort"

& $bridgeExe
