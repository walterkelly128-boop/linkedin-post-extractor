$ErrorActionPreference = "Stop"

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "E:\linkedin-chrome-profile"
$chromePort = 9222
$bridgePort = 8765
$bridgeExe = Join-Path $PSScriptRoot "dist\chrome-bridge.exe"

if (-not (Test-Path $chrome)) {
    $chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    throw "找不到 Chrome。请修改 start_chrome_bridge.ps1 中的 Chrome 路径。"
}
if (-not (Test-Path $bridgeExe)) {
    throw "找不到 $bridgeExe。请先从 GitHub Actions 下载 chrome-bridge-windows 工件，或运行 build_bridge.ps1。"
}
if (-not (Test-Path $profile)) {
    New-Item -ItemType Directory -Path $profile -Force | Out-Null
}

try {
    Invoke-RestMethod "http://127.0.0.1:$chromePort/json/version" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome CDP 已在 :$chromePort 运行。" -ForegroundColor Green
} catch {
    Write-Host "启动专用 Chrome..." -ForegroundColor Cyan
    Start-Process -FilePath $chrome -ArgumentList @("--remote-debugging-port=$chromePort","--remote-debugging-address=0.0.0.0","--remote-allow-origins=*","--user-data-dir=$profile")
    Start-Sleep -Seconds 3
}

try {
    Invoke-RestMethod "http://127.0.0.1:$chromePort/json/version" -TimeoutSec 5 | Out-Null
} catch {
    throw "Chrome CDP :$chromePort 没有成功启动。请检查专用 Chrome 窗口。"
}

try {
    Invoke-RestMethod "http://127.0.0.1:$bridgePort/health" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome Bridge 已经运行在 :$bridgePort。" -ForegroundColor Green
    exit 0
} catch {}

Write-Host "启动 Windows Chrome Bridge :$bridgePort ..." -ForegroundColor Cyan
Write-Host "保持此窗口运行；关闭窗口会停止 Bridge。" -ForegroundColor Yellow

$env:LOCAL_CHROME_CDP_URL = "http://127.0.0.1:$chromePort"
$env:CHROME_BRIDGE_HOST = "0.0.0.0"
$env:CHROME_BRIDGE_PORT = "$bridgePort"

& $bridgeExe
