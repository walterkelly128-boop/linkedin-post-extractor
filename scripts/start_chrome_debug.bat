@echo off
:: ============================================================
:: start_chrome_debug.bat
:: Launches Google Chrome with remote debugging enabled on port 9222.
:: This allows the LinkedIn Post Extractor to connect via CDP
:: and reuse your existing LinkedIn login session.
::
:: USAGE: Double-click this file, or run from command prompt.
:: ============================================================

setlocal

set PORT=9222
set PROFILE_DIR=%TEMP%\chrome-linkedin-debug

:: Try to find Chrome in common installation paths
set CHROME_PATH=
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe
) else if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
)

if "%CHROME_PATH%"=="" (
    echo [ERROR] Google Chrome not found in standard locations.
    echo Please install Chrome or update the path in this script.
    pause
    exit /b 1
)

echo ============================================================
echo  LinkedIn Post Extractor — Chrome Debug Launcher
echo ============================================================
echo  Chrome  : %CHROME_PATH%
echo  Port    : %PORT%
echo  Profile : %PROFILE_DIR%
echo ============================================================
echo.
echo  Chrome will open. Please:
echo    1. Log in to LinkedIn in the browser window
echo    2. Keep this Chrome window open while using the extractor
echo.
echo  To verify the debug port is active, visit:
echo    http://localhost:%PORT%/json
echo ============================================================
echo.

:: Launch Chrome with remote debugging
:: Using a separate profile dir to avoid conflicts with your main Chrome
start "" "%CHROME_PATH%" ^
    --remote-debugging-port=%PORT% ^
    --user-data-dir="%PROFILE_DIR%" ^
    --no-first-run ^
    --no-default-browser-check ^
    https://www.linkedin.com

echo Chrome launched. You can close this window.
echo (Keep the Chrome window with LinkedIn open!)
timeout /t 3 >nul
