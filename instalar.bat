@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo CortaFlow AI - instalacao para Windows
echo ========================================

where winget >nul 2>nul
if errorlevel 1 (
  echo ERRO: o WinGet nao foi encontrado.
  echo Atualize o App Installer pela Microsoft Store e tente novamente.
  pause
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 echo AVISO: Git nao esta instalado. Ele so e necessario para clonar o repositorio.

py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo Instalando CPython 3.11 x64...
  winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto :erro
)

py -3.11 -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,11) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
  echo ERRO: e necessario Python 3.11 de 64 bits.
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Instalando FFmpeg Essentials...
  winget install --id Gyan.FFmpeg.Essentials -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto :erro
)

if not exist "scripts\setup_windows.ps1" (
  echo ERRO: arquivo scripts\setup_windows.ps1 nao encontrado.
  echo Execute este BAT na pasta raiz completa do projeto.
  pause
  exit /b 1
)

echo.
echo Criando ambiente virtual e instalando o CortaFlow e suas dependencias...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
if errorlevel 1 goto :erro

echo.
echo Instalacao concluida. Iniciando o CortaFlow AI...
"%~dp0.venv\Scripts\python.exe" -m cortaflow.main
if errorlevel 1 goto :erro
exit /b 0

:erro
echo.
echo A instalacao ou inicializacao falhou. Confira a mensagem acima e a secao Solucao de problemas no README.md.
pause
exit /b 1
