@echo off
setlocal

set PORT=9222
set PROFILE=%TEMP%\chrome-linkedin-debug

echo ==================================================
echo  LinkedIn Extractor - Launch Chrome Debug Mode
echo ==================================================
echo.

:: Hardcode the path check to avoid variable quoting issues
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set EXE=C:\Program Files\Google\Chrome\Application\chrome.exe
    goto LAUNCH
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set EXE=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
    goto LAUNCH
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
    goto LAUNCH
)

echo [ERROR] Chrome not found!
echo Please install Google Chrome first.
pause
exit /b 1

:LAUNCH
echo Chrome: %EXE%
echo Port  : %PORT%
echo.

if not exist "%PROFILE%" mkdir "%PROFILE%"

echo Starting Chrome... Please log in to LinkedIn.
echo Keep this Chrome window open while using the extractor.
echo.

start "" "%EXE%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check https://www.linkedin.com

timeout /t 5 /nobreak >nul

echo ==================================================
echo  Chrome launched!
echo  Verify debug port: http://localhost:%PORT%/json
echo ==================================================
pause
