@echo off
REM Busca no datalake as NFs das O.S. do relatorio mais recente. So leitura.
cd /d %~dp0
.venv\Scripts\python -m pip install --quiet -r requirements.txt
.venv\Scripts\python nf_linx.py
echo.
pause
