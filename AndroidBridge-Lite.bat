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

rem Self-heal the tracked runtime set. "git pull" alone does not remove
rem local working-tree edits, which can leave files from different builds mixed.
git restore --source=HEAD --worktree -- "pc\AndroidBridge-Lite.py" "pc\AndroidBridge-PhoneData.py" "pc\scrcpy-server-v4.1-llb" "pc\scrcpy-server-v4.1-llb.sha256" >nul 2>&1

rem Old builds wrote scrcpy logs that no longer describe the active runtime.
rem Remove them so stale proxy/chunk errors cannot be mistaken for current errors.
del /q "pc\scrcpy-*.log" >nul 2>&1

rem Never let an inherited scrcpy ADB override select the retired proxy.
set "ADB="
set "ANDROIDBRIDGE_REAL_ADB="

rem Remove known obsolete/generated files. Never remove user data/history.
del /q "%~dp0pc\AndroidBridge-AdbProxy.exe" "%~dp0pc\AndroidBridge-AdbProxyV2.exe" "%~dp0pc\AndroidBridge-AdbProxyV2.cs" >nul 2>&1
del /q "%~dp0pc\New Text Document.txt" >nul 2>&1
del /q "%~dp0AndroidBridge-Lite.py" "%~dp0AndroidBridge-PhoneData.py" >nul 2>&1
if exist "%~dp0__pycache__" rmdir /s /q "%~dp0__pycache__"
if exist "%~dp0pc\__pycache__" rmdir /s /q "%~dp0pc\__pycache__"

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
