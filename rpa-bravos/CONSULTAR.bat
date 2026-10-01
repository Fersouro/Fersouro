@echo off
REM Consulta NFs por SG no BRAVOS.  Ex.:  CONSULTAR.bat 210238 214074
cd /d %~dp0
if not exist .venv\Scripts\python.exe (echo Rode INSTALAR.bat primeiro. & pause & exit /b 1)
.venv\Scripts\python bravos_nf.py %*
echo.
pause
