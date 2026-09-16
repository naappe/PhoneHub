@echo off
setlocal
title PhoneHub

cd /d C:\PhoneHub

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
REM Close old PhoneHub tools/windows.
taskkill /IM PhoneHub.exe /F >nul 2>&1
taskkill /IM scrcpy.exe /F >nul 2>&1
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM pythonw.exe /F >nul 2>&1

REM Start ADB for the existing legacy connection mode.
adb start-server >nul 2>&1

REM Always launch the installed PhoneHub, even if update checking failed/skipped.
start "" "C:\PhoneHub\dist\PhoneHub.exe"

endlocal
exit
