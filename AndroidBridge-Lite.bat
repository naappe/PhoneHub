@echo off
setlocal
cd /d "%~dp0"

echo [AndroidBridge] Safe local launcher
echo [AndroidBridge] No Git updates or file restoration.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

where adb >nul 2>&1
if errorlevel 1 (
    echo ERROR: ADB not found.
    pause
    exit /b 1
)

where scrcpy >nul 2>&1
if errorlevel 1 (
    echo ERROR: scrcpy not found.
    pause
    exit /b 1
)

echo [AndroidBridge] Checking Python syntax...
python -m py_compile "%~dp0pc\AndroidBridge-Lite.py" "%~dp0pc\AndroidBridge-PhoneData.py"
if errorlevel 1 (
    echo ERROR: Python source verification failed.
    pause
    exit /b 1
)

echo [AndroidBridge] Starting...
python "%~dp0pc\AndroidBridge-Lite.py"

if errorlevel 1 pause
exit /b %errorlevel%
