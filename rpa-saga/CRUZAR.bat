@echo off
REM Cruza o PDF mais novo (saida\pdfs) com os .xls da pasta planilhas. So leitura.
cd /d %~dp0
.venv\Scripts\python -m pip install --quiet -r requirements.txt
.venv\Scripts\python cruzar.py %*
echo.
pause
