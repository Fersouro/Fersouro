@echo off
REM Mapeia a janela aberta do BRAVOS (nomes dos campos/botoes). So le.
cd /d %~dp0
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install --quiet pywinauto keyring python-dotenv
.venv\Scripts\python inspecionar.py
pause
