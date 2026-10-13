@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente nao instalado. Execute instalar.bat primeiro.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m cortaflow.main
if errorlevel 1 pause
