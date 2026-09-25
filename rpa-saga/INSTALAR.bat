@echo off
REM Instala o RPA (uma vez). Usa o Python da maquina e o Edge do Windows.
cd /d %~dp0
python -m venv .venv || (echo ERRO: Python nao encontrado & pause & exit /b 1)
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\python -m pip install --quiet -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo Pronto. Agora abra o arquivo .env desta pasta e coloque usuario e senha.
notepad .env
pause
