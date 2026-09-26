@echo off
REM Debitos em aberto e erros nos fechamentos (.xls da pasta planilhas). So leitura.
cd /d %~dp0
.venv\Scripts\python -m pip install --quiet -r requirements.txt
.venv\Scripts\python debitos.py %*
echo.
pause
