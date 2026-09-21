@echo off
setlocal

set PORT=9222
set PROFILE_DIR=%TEMP%\chrome-linkedin-debug
set CHROME_PATH=

:: Check common Chrome install locations
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe
)
if "%CHROME_PATH%"=="" if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
)
if "%CHROME_PATH%"=="" if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe
)

:: Fallback: try registry
if "%CHROME_PATH%"=="" (
    for /f "tokens=2*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" /ve 2^>nul') do (
        set CHROME_PATH=%%B
    )
)

if "%CHROME_PATH%"=="" (
    echo [ERROR] Google Chrome not found.
    echo Please install Chrome or set CHROME_PATH manually in this script.
    pause
    exit /b 1
)

echo ==========================================================
echo  LinkedIn Post Extractor - Chrome Debug Mode Launcher
echo ==========================================================
echo  Chrome : %CHROME_PATH%
echo  Port   : %PORT%
echo  Profile: %PROFILE_DIR%
echo ==========================================================
echo.

:: Check if port is already in use
netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo [INFO] Port %PORT% is already listening.
    echo Chrome debug mode may already be running.
    echo Verify at: http://localhost:%PORT%/json
    echo.
    pause
    exit /b 0
)

:: Create profile directory
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

echo Starting Chrome with debug port %PORT%...
echo Please log in to LinkedIn in the Chrome window that opens.
echo Keep Chrome open while using the extractor.
echo.

start "" "%CHROME_PATH%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE_DIR%" --no-first-run --no-default-browser-check https://www.linkedin.com

echo Waiting for Chrome to start...
timeout /t 3 /nobreak >nul

:: Verify port is live
curl -s --max-time 3 http://localhost:%PORT%/json >nul 2>&1
if %ERRORLEVEL%==0 (
    echo.
    echo [OK] Chrome debug port is ready!
    echo Verify at: http://localhost:%PORT%/json
) else (
    echo.
    echo [WARN] Chrome started but debug port not yet responding.
    echo Wait a few seconds then check: http://localhost:%PORT%/json
    echo.
    echo If it still fails, close ALL Chrome windows first, then retry.
)

echo.
echo ==========================================================
echo  Next steps:
echo    1. Log in to LinkedIn in the Chrome window
echo    2. Keep Chrome open
echo    3. Run: docker compose up
echo    4. POST to http://localhost:8000/extract
echo ==========================================================
pause
