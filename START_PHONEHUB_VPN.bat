@echo off
setlocal
cd /d C:\PhoneHub
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\PhoneHub\vpn\PhoneHubVPN.ps1" %*
endlocal
