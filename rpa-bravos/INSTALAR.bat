@echo off
REM Instala (uma vez). Usa o Python da maquina e o Edge do Windows.
cd /d %~dp0
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\python -m pip install --quiet -r requirements.txt
if not exist .env copy .env.example .env >nul
echo Preencha BRAVOS_URL e BRAVOS_USUARIO no Bloco de Notas e salve.
notepad .env
call CADASTRAR-SENHA.bat
