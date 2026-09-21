$ErrorActionPreference = "Stop"

Write-Host "=== LinkedIn Chrome Bridge - Windows EXE Builder ===" -ForegroundColor Cyan

$python = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $version = & $cmd --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) {
            $python = $cmd
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Host "未找到可用的 Python。" -ForegroundColor Yellow
    Write-Host "不想在 Windows 安装 Python 时，请使用 GitHub Actions 构建。" -ForegroundColor Yellow
    Write-Host "GitHub -> Actions -> Build Windows Chrome Bridge -> Run workflow" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using Python: $python"
& $python -m pip install --upgrade pip
& $python -m pip install -r bridge_requirements.txt
& $python -m pip install pyinstaller
& $python -m PyInstaller --onefile --clean --name chrome-bridge --collect-all playwright --collect-all pydantic --collect-all fastapi bridge_server.py

if (-not (Test-Path "dist\chrome-bridge.exe")) {
    throw "dist\chrome-bridge.exe 未生成。"
}

Write-Host "构建完成：" -ForegroundColor Green
Write-Host (Resolve-Path "dist\chrome-bridge.exe")
