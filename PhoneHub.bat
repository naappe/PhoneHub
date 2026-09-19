@echo off
setlocal
title PhoneHub
cd /d C:\PhoneHub

if exist "C:\PhoneHub\runtime\scrcpy\scrcpy.exe" (
    set "PATH=C:\PhoneHub\runtime\scrcpy;%PATH%"
)

echo [PhoneHub] Checking for updates...

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto launch_phonehub

set "LOCAL_CHANGES="
for /f "delims=" %%G in ('git status --porcelain 2^>nul') do set "LOCAL_CHANGES=1"
if defined LOCAL_CHANGES goto launch_phonehub

git fetch origin main >nul 2>&1
if errorlevel 1 goto launch_phonehub

git pull --ff-only origin main >nul 2>&1

:launch_phonehub
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\PhoneHub\scripts\stop_phonehub.ps1" >nul 2>&1
timeout /t 1 /nobreak >nul

adb start-server >nul 2>&1

if not exist "C:\PhoneHub\logs" mkdir "C:\PhoneHub\logs"
set "LOG=C:\PhoneHub\logs\launcher_error.log"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Run C:\PhoneHub\SETUP_PHONEHUB.bat
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PySide6 is missing.
    echo Run C:\PhoneHub\SETUP_PHONEHUB.bat
    pause
    exit /b 1
)

for /f "tokens=2 delims== " %%V in ('findstr /B /C:"APP_VERSION =" "C:\PhoneHub\app\PhoneHubCore.py" 2^>nul') do echo [PhoneHub] Launching %%~V

REM Start through cmd so Python import/startup failures are written to a persistent log.
start "PhoneHub" /min cmd /c "cd /d C:\PhoneHub\app && python PhoneHubCore.py 1>>C:\PhoneHub\logs\phonehub_stdout.log 2>>C:\PhoneHub\logs\launcher_error.log"

timeout /t 2 /nobreak >nul

REM If the UI process died immediately, show the log instead of silently returning.
tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul
if errorlevel 1 (
    echo.
    echo [ERROR] PhoneHub did not stay running.
    echo Error log:
    type "%LOG%"
    echo.
    echo Run SETUP_PHONEHUB.bat if a dependency is missing.
    pause
    exit /b 1
)

echo [PhoneHub] Started.
endlocal
exit /b 0
