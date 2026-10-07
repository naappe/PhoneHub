@chcp 65001 >nul
@echo off
setlocal
cd /d "%~dp0"

echo [Samsung Secure] 正在检查 GitHub 更新...
git pull --ff-only >nul 2>&1
if errorlevel 1 (
    echo [Samsung Secure] 更新已跳过 - 使用当前本地版本。
) else (
    echo [Samsung Secure] 已是最新版本。
)

rem Self-heal the tracked runtime set. "git pull" alone does not remove
rem local working-tree edits, which can leave files from different builds mixed.
git restore --source=HEAD --worktree -- "pc\AndroidBridge-Lite.py" "pc\AndroidBridge-PhoneData.py" "pc\scrcpy-server-v4.1-llb" "pc\scrcpy-server-v4.1-llb.sha256" "tools\cleanup-stale-startups.ps1" "tools\ensure-fast-scrcpy.ps1" >nul 2>&1

rem Old builds wrote scrcpy logs that no longer describe the active runtime.
rem Remove them so stale proxy/chunk errors cannot be mistaken for current errors.
del /q "pc\scrcpy-*.log" >nul 2>&1

rem Never let an inherited scrcpy ADB override select the retired proxy.
set "ADB="
set "ANDROIDBRIDGE_REAL_ADB="

rem Remove only abandoned AndroidBridge scrcpy startup uploads from earlier
rem runs. This script never disconnects or kills the ADB server.
if exist "%~dp0tools\cleanup-stale-startups.ps1" (
    for /f %%i in ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\cleanup-stale-startups.ps1" 2^>nul') do (
        if not "%%i"=="0" echo [Samsung Secure] 已清理 %%i 个过期媒体启动进程。
    )
)

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

rem Normal Screen/Camera/Audio use the official compact scrcpy v3.3.4
rem runtime because its server is ~91 KB instead of v4.1's ~734 KB.
rem The existing v4.1 installation remains the automatic compatibility
rem fallback and continues to power NIGHT CAMERA / Low Light Boost.
if exist "%~dp0tools\ensure-fast-scrcpy.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ensure-fast-scrcpy.ps1" >nul
    if errorlevel 1 (
        echo [Samsung Secure] 快速媒体引擎不可用 - 使用标准 scrcpy。
    ) else (
        echo [Samsung Secure] 快速媒体引擎已就绪。
    )
)

echo [Samsung Secure] 正在验证 Python 源代码...
python -m py_compile "%~dp0pc\AndroidBridge-Lite.py" "%~dp0pc\AndroidBridge-PhoneData.py"
if errorlevel 1 (
    echo [Samsung Secure] 源代码验证失败。
    pause
    exit /b 1
)

for /f %%i in ('git rev-parse --short HEAD 2^>nul') do echo [Samsung Secure] GitHub 版本： %%i
echo [Samsung Secure] 正在启动已验证的运行环境...

python "%~dp0pc\AndroidBridge-Lite.py"
exit /b %errorlevel%
