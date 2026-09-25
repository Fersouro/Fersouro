@echo off
REM Roda o RPA: login -> Garantia Volkswagen -> SAGA -> SAGA2 - VH47 -> Lista de arquivos
REM Para tambem baixar os PDFs:  RODAR.bat --baixar
cd /d %~dp0
if not exist .venv\Scripts\python.exe (echo Rode INSTALAR.bat primeiro. & pause & exit /b 1)
.venv\Scripts\python saga_rpa.py %*
echo.
pause
