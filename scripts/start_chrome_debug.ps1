# ============================================================
# start_chrome_debug.ps1
# 以调试模式启动 Google Chrome（端口 9222）
# 在 PowerShell 中右键"以管理员身份运行"，或直接双击
# ============================================================

$Port = 9222
$ProfileDir = "$env:TEMP\chrome-linkedin-debug"
$LinkedInUrl = "https://www.linkedin.com"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " LinkedIn Post Extractor | Chrome 调试模式启动器" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---- 1. 查找 Chrome 路径 ----
$ChromeCandidates = @(
    "$env:PROGRAMFILES\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
)

# 也从注册表查找
try {
    $regPath = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" -ErrorAction Stop)."(Default)"
    if ($regPath) { $ChromeCandidates = @($regPath) + $ChromeCandidates }
} catch {}

$ChromePath = $ChromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ChromePath) {
    Write-Host "`n[错误] 未找到 Google Chrome！" -ForegroundColor Red
    Write-Host "请确认 Chrome 已安装。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host " Chrome : $ChromePath" -ForegroundColor Green
Write-Host " 端口   : $Port"
Write-Host " Profile: $ProfileDir"
Write-Host "============================================================"

# ---- 2. 检查端口是否已在使用 ----
$portInUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "`n[提示] 端口 $Port 已在监听，Chrome 调试模式可能已启动。" -ForegroundColor Yellow
    Write-Host "验证: http://localhost:$Port/json"
    Read-Host "按 Enter 退出"
    exit 0
}

# ---- 3. 创建 Profile 目录 ----
if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
}

# ---- 4. 启动 Chrome ----
Write-Host "`n正在启动 Chrome..." -ForegroundColor Yellow
$args = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=`"$ProfileDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    $LinkedInUrl
)

Start-Process -FilePath $ChromePath -ArgumentList $args

# ---- 5. 等待并验证端口 ----
Write-Host "等待 Chrome 启动（最多 20 秒）..."
$waited = 0
$success = $false
while ($waited -lt 20) {
    Start-Sleep -Seconds 2
    $waited += 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$Port/json" -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $success = $true
            break
        }
    } catch {}
    Write-Host "  等待中... ($waited 秒)" -ForegroundColor Gray
}

Write-Host ""
if ($success) {
    Write-Host "[成功] Chrome 调试端口已就绪！" -ForegroundColor Green
    Write-Host ""
    Write-Host "下一步：" -ForegroundColor Cyan
    Write-Host "  1. 在已打开的 Chrome 窗口中登录 LinkedIn"
    Write-Host "  2. 运行：docker compose up"
    Write-Host "  3. 或：python -m src.main --url `"LinkedIn帖子URL`""
    Write-Host ""
    Write-Host "验证地址: http://localhost:$Port/json" -ForegroundColor DarkGray
} else {
    Write-Host "[警告] Chrome 已启动但调试端口未响应。" -ForegroundColor Yellow
    Write-Host "可能原因："
    Write-Host "  - Chrome 之前已有实例在运行（未使用调试端口）"
    Write-Host "  - 解决方法：关闭所有 Chrome 窗口，再运行此脚本"
    Write-Host ""
    Write-Host "手动验证: http://localhost:$Port/json"
}

Write-Host "============================================================" -ForegroundColor Cyan
Read-Host "按 Enter 退出"
