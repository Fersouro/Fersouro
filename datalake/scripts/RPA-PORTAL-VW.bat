@echo off
REM ============================================================
REM  RPA PORTAL REDE VW
REM
REM  Faz login no Portal Rede VW e entra no usuario do .env.
REM  Print da tela em C:\datalake\logs\rpa\. Para ver o navegador
REM  trabalhando, rode:  RPA-PORTAL-VW.bat --visivel
REM
REM  Usuario, senha e usuario-alvo ficam em C:\datalake\.env:
REM    RPA_PORTALVW_USUARIO / RPA_PORTALVW_SENHA / RPA_PORTALVW_ALVO
REM ============================================================
title RPA Portal Rede VW
cd /d C:\datalake

set PY=
for %%P in ("C:\Program Files\Python312\python.exe" "C:\Program Files\Python311\python.exe") do (
    if exist %%P set PY=%%P
)
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set PY="%%P"
)
if not defined PY (
    color 0C
    echo  ERRO: nao achei o Python nesta maquina.
    pause
    exit /b 1
)

if not exist C:\datalake\rpa_portal_vw.py (
    color 0E
    echo  Nao achei C:\datalake\rpa_portal_vw.py.
    echo  Rode antes:  powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_app.ps1
    pause
    exit /b 1
)

REM primeira vez: instala o Playwright (usa o Edge do Windows, sem baixar navegador)
%PY% -c "import playwright, yaml, dotenv" 2>nul || %PY% -m pip install --user --quiet playwright pyyaml python-dotenv

echo.
%PY% C:\datalake\rpa_portal_vw.py %*
set RC=%ERRORLEVEL%
echo.
if "%RPA_SEM_PAUSA%"=="" pause
exit /b %RC%
