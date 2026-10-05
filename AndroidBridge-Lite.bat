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

rem Self-heal the tracked application file. "git pull" alone does not remove
rem local working-tree edits, which can leave an older experimental build active.
git restore --source=HEAD --worktree -- "pc\AndroidBridge-Lite.py" >nul 2>&1

rem Never let an inherited scrcpy ADB override select the retired proxy.
set "ADB="
set "ANDROIDBRIDGE_REAL_ADB="

rem Remove the old generated proxy executable if it still exists locally.
if exist "%~dp0pc\AndroidBridge-AdbProxy.exe" del /q "%~dp0pc\AndroidBridge-AdbProxy.exe" >nul 2>&1

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
