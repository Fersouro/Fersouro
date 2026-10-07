@echo off
REM Guarda a senha do BRAVOS no cofre do Windows (nao aparece na tela).
cd /d %~dp0
.venv\Scripts\python cofre.py cadastrar
pause
