@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0AUTO_BOOTSTRAP_PHONE.ps1"
