@echo off
setlocal
cd /d "%~dp0"

echo [AndroidBridge] Checking GitHub updates...
git pull --ff-only >nul 2>&1
if errorlevel 1 (
    echo [AndroidBridge] Update skipped - using current local version.
) else (
    echo [AndroidBridge] Up to date.
)

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    pause
    exit /b 1
)

where adb >nul 2>&1
if errorlevel 1 (
    echo ADB was not found in PATH.
    pause
    exit /b 1
)

where scrcpy >nul 2>&1
if errorlevel 1 (
    echo scrcpy was not found in PATH.
    pause
    exit /b 1
)

python "%~dp0pc\AndroidBridge-Lite.py"
exit /b %errorlevel%
