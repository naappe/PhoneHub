@echo off
setlocal
title PhoneHub

cd /d C:\PhoneHub

REM Prefer the self-contained PhoneHub scrcpy/ADB runtime when installed.
if exist "C:\PhoneHub\runtime\scrcpy\scrcpy.exe" (
    set "PATH=C:\PhoneHub\runtime\scrcpy;%PATH%"
)

echo [PhoneHub] Checking for updates...

REM Only update when this folder is a Git working tree.
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [PhoneHub] Git repository not detected. Starting installed version.
    goto launch_phonehub
)

REM Never overwrite local work. If anything is modified/untracked, skip pulling.
set "LOCAL_CHANGES="
for /f "delims=" %%G in ('git status --porcelain 2^>nul') do set "LOCAL_CHANGES=1"
if defined LOCAL_CHANGES (
    echo [PhoneHub] Local changes detected - update skipped.
    goto launch_phonehub
)

REM Check GitHub first. Network/Git failures must never stop PhoneHub from opening.
git fetch origin main >nul 2>&1
if errorlevel 1 (
    echo [PhoneHub] Could not reach GitHub - starting installed version.
    goto launch_phonehub
)

REM Fast-forward only: never create an automatic merge on this PC.
git pull --ff-only origin main >nul 2>&1
if errorlevel 1 (
    echo [PhoneHub] Update could not be applied safely - starting installed version.
    goto launch_phonehub
)

echo [PhoneHub] Update check complete.

:launch_phonehub
REM Stop only the old PhoneHub process so newly pulled code actually reloads.
REM The PowerShell helper excludes itself and leaves unrelated Python apps alone.
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\PhoneHub\scripts\stop_phonehub.ps1" >nul 2>&1
timeout /t 1 /nobreak >nul

REM Start ADB for the Tailscale remote connection mode.
adb start-server >nul 2>&1

for /f "tokens=2 delims== " %%V in ('findstr /B /C:"APP_VERSION =" "C:\PhoneHub\app\PhoneHubTailscale.py" 2^>nul') do echo [PhoneHub] Launching %%~V

REM Primary app: existing PhoneHub tools with the Tailscale IP box on Dashboard.
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "C:\PhoneHub\app\PhoneHubTailscale.py"
    goto done
)

REM If pythonw is unavailable, try normal Python.
where python >nul 2>&1
if not errorlevel 1 (
    start "" python "C:\PhoneHub\app\PhoneHubTailscale.py"
    goto done
)

REM Final fallback: keep the previous compiled PhoneHub available.
echo [PhoneHub] Python not found - opening compiled PhoneHub.
start "" "C:\PhoneHub\dist\PhoneHub.exe"

:done
endlocal
exit
