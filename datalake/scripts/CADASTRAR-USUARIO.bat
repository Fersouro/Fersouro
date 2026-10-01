@echo off
REM ============================================================
REM  CADASTRAR USUARIO DA PAGINA
REM
REM  Duplo-clique: pergunta o nome, pede a senha (que nao aparece
REM  na tela) e grava em C:\datalake\usuarios.json.
REM
REM  Serve tambem para TROCAR senha: e so usar o mesmo nome.
REM  Vale na hora, sem reiniciar o servico.
REM ============================================================
title Cadastrar usuario da pagina de relatorios
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

set NOME=%1
if "%NOME%"=="" set /p NOME=  Nome de usuario (ex.: gil@tterrasul.com.br): 
if "%NOME%"=="" (
    echo  Sem nome, nada a fazer.
    pause
    exit /b 1
)

echo.
%PY% C:\datalake\servir_pagina.py --criar-usuario %NOME%
echo.
pause
