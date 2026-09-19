@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "TOOLS=%~dp0runtime\platform-tools"
set "SCRCPY_DIR=%~dp0runtime\scrcpy"

where python >nul 2>&1 || (
  echo [PhoneHub Setup] Python 3 is required.
  echo Install Python once, then run this file again.
  pause
  exit /b 1
)

python -c "import PySide6" >nul 2>&1 || (
  echo [PhoneHub Setup] Installing PySide6...
  python -m pip install "PySide6>=6.8,<7" || goto :failed
)

where adb >nul 2>&1
if errorlevel 1 (
  if exist "%TOOLS%\adb.exe" (
    set "PATH=%TOOLS%;%PATH%"
  ) else (
    echo [PhoneHub Setup] Installing Android Platform Tools...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $u='https://dl.google.com/android/repository/platform-tools-latest-windows.zip'; $z=Join-Path $env:TEMP 'phonehub-platform-tools.zip'; Invoke-WebRequest $u -OutFile $z; New-Item -ItemType Directory -Force -Path '%~dp0runtime' | Out-Null; Expand-Archive -Force $z '%~dp0runtime'; Remove-Item $z -Force" || goto :failed
    set "PATH=%TOOLS%;%PATH%"
  )
)

where scrcpy >nul 2>&1
if errorlevel 1 (
  if exist "%SCRCPY_DIR%\scrcpy.exe" (
    set "PATH=%SCRCPY_DIR%;%PATH%"
  ) else (
    echo [PhoneHub Setup] scrcpy is missing.
    echo PhoneHub will open, but Screen and Camera require scrcpy.
    echo Install scrcpy once with: winget install --exact Genymobile.scrcpy
  )
)

adb start-server >nul 2>&1
echo [PhoneHub] Starting...
python -m phonehub
exit /b %errorlevel%

:failed
echo.
echo PhoneHub automatic setup failed.
pause
exit /b 1
