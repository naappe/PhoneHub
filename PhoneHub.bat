@echo off
title PhoneHub

REM Close old PhoneHub tools/windows
taskkill /IM PhoneHub.exe /F >nul 2>&1
taskkill /IM scrcpy.exe /F >nul 2>&1
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM pythonw.exe /F >nul 2>&1

REM Start ADB clean
adb start-server >nul 2>&1

REM Open only main PhoneHub app
cd /d C:\PhoneHub
start "" "C:\PhoneHub\dist\PhoneHub.exe"

exit
