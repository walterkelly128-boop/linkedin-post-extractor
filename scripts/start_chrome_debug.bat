@echo off
:: ============================================================
:: start_chrome_debug.bat
:: 以调试模式启动 Google Chrome（端口 9222）
:: 双击运行即可，脚本会自动查找 Chrome 路径
:: ============================================================

setlocal EnableDelayedExpansion

set PORT=9222
set PROFILE_DIR=%TEMP%\chrome-linkedin-debug

echo ============================================================
echo  LinkedIn Post Extractor ^| Chrome 调试模式启动器
echo ============================================================

:: ---- 1. 查找 Chrome 路径 ----
set CHROME_PATH=

:: 按优先级逐个检测
for %%P in (
    "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
    "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
    "%PROGRAMW6432%\Google\Chrome\Application\chrome.exe"
) do (
    if exist %%P (
        if "!CHROME_PATH!"=="" set CHROME_PATH=%%~P
    )
)

:: 从注册表查找
if "!CHROME_PATH!"=="" (
    for /f "tokens=2*" %%A in (
        'reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" /ve 2^>nul'
    ) do set CHROME_PATH=%%B
)

if "!CHROME_PATH!"=="" (
    echo.
    echo [错误] 未找到 Google Chrome！
    echo 请确认 Chrome 已安装，或手动修改本脚本中的 CHROME_PATH。
    echo.
    pause
    exit /b 1
)

echo  Chrome : !CHROME_PATH!
echo  端口   : %PORT%
echo  Profile: %PROFILE_DIR%
echo ============================================================

:: ---- 2. 检查端口是否已被占用 ----
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo.
    echo [提示] 端口 %PORT% 已在监听，Chrome 可能已在调试模式运行。
    echo 请访问 http://localhost:%PORT%/json 确认。
    echo.
    pause
    exit /b 0
)

:: ---- 3. 创建 Profile 目录 ----
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

:: ---- 4. 启动 Chrome ----
echo.
echo 正在启动 Chrome...
echo 启动后请在浏览器中登录 LinkedIn，然后回来继续操作。
echo.

start "" "!CHROME_PATH!" ^
    --remote-debugging-port=%PORT% ^
    --user-data-dir="%PROFILE_DIR%" ^
    --no-first-run ^
    --no-default-browser-check ^
    --disable-extensions ^
    https://www.linkedin.com

:: ---- 5. 等待并验证 ----
echo 等待 Chrome 启动（最多 15 秒）...
set /a WAIT=0
:WAIT_LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=2
curl -s http://localhost:%PORT%/json >nul 2>&1
if %ERRORLEVEL%==0 (
    echo.
    echo [成功] Chrome 调试端口已就绪！
    echo 验证地址: http://localhost:%PORT%/json
    echo.
    echo 现在可以运行提取器：
    echo   docker compose up
    echo   或：python -m src.main --url "LinkedIn帖子URL"
    echo.
    goto DONE
)
if %WAIT% LSS 15 goto WAIT_LOOP

echo.
echo [警告] Chrome 已启动但调试端口未响应。
echo 请手动访问 http://localhost:%PORT%/json 确认是否正常。
echo.

:DONE
echo ============================================================
pause
