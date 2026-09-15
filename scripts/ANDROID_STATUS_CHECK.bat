@echo off
title PhoneHub Android Status Check
cd /d C:\PhoneHub
powershell -ExecutionPolicy Bypass -File "C:\PhoneHub\scripts\ANDROID_STATUS_CHECK.ps1"
