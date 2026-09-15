@echo off
title PhoneHub Auto Start
cd /d C:\PhoneHub

echo ==============================
echo        PHONEHUB AUTO START
echo ==============================

adb start-server >nul 2>&1

REM Open PhoneHub EXE and close this black window
start "" "C:\PhoneHub\dist\PhoneHub.exe"

exit
