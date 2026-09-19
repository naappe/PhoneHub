@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found.
  pause
  exit /b 1
)

python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo Installing PySide6...
  python -m pip install "PySide6>=6.8,<7"
  if errorlevel 1 (
    echo Could not install PySide6.
    pause
    exit /b 1
  )
)

python -m phonehub
endlocal
