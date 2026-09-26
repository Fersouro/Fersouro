@echo off
REM Portal Rede x Drive: quantos fechamentos o mes tem e quais faltam. So leitura.
cd /d %~dp0
.venv\Scripts\python comparar_mes.py %*
echo.
pause
