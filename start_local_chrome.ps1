$ErrorActionPreference = "Stop"

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    throw "Chrome not found."
}

$profile = Join-Path $PSScriptRoot "linkedin-chrome-profile"

try {
    Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome CDP already running on 9222." -ForegroundColor Green
} catch {
    Write-Host "Starting dedicated Chrome..." -ForegroundColor Cyan
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-port=9222",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--user-data-dir=$profile"
    )
    Start-Sleep -Seconds 3
}

try {
    Invoke-RestMethod "http://127.0.0.1:9222/json/version" -TimeoutSec 5 | Out-Null
} catch {
    throw "Chrome CDP did not start on port 9222."
}

Write-Host ""
Write-Host "Windows 专用 Chrome 已启动。" -ForegroundColor Green
Write-Host "如果第一次使用，请在这个 Chrome 窗口登录 LinkedIn。" -ForegroundColor Yellow
Write-Host ""
Write-Host "接下来运行 Docker：" -ForegroundColor Cyan
Write-Host "docker compose up -d --build" -ForegroundColor White
Write-Host "然后打开 http://127.0.0.1:8766" -ForegroundColor Green
