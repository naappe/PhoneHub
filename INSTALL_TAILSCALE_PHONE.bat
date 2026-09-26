@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_TAILSCALE_PHONE.ps1"
if errorlevel 1 pause
