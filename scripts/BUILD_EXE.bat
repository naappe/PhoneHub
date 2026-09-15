@echo off
title Build PhoneHub EXE
cd /d C:\PhoneHub
powershell -ExecutionPolicy Bypass -File "C:\PhoneHub\scripts\BUILD_EXE.ps1"
pause
