@echo off
REM ============================================================
REM  DIAGNOSTICO DA PAGINA  (por que o login nao passa)
REM
REM  Duplo-clique. Diz quem atende em cada porta, com que
REM  argumentos a tarefa sobe o servidor e quem esta cadastrado.
REM
REM  Existe como .bat de proposito: no PowerShell, uma linha que
REM  comeca com aspas vira texto ("Token inesperado") e nao roda
REM  nada -- e o caminho do Python tem espaco, entao as aspas sao
REM  inevitaveis. O .bat nao tem essa armadilha.
REM ============================================================
title Diagnostico da pagina de relatorios
color 0B
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

if not exist C:\datalake\diagnostico_pagina.py (
    color 0E
    echo  Nao achei C:\datalake\diagnostico_pagina.py.
    echo  Rode antes:  powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\instalar_app.ps1
    pause
    exit /b 1
)

echo.
%PY% C:\datalake\diagnostico_pagina.py
echo.
pause
