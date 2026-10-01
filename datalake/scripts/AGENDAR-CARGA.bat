@echo off
REM ============================================================
REM  AGENDAR A CARGA DE HORA EM HORA
REM
REM  Clique com o botao direito e escolha "Executar como
REM  administrador". Substitui os agendamentos antigos por uma
REM  tarefa unica que roda a cada hora, das 07:00 as 20:00.
REM ============================================================
title Datalake - agendar carga de hora em hora
color 0B
net session >nul 2>&1
if errorlevel 1 (
    color 0C
    echo.
    echo  ERRO: precisa ser executado como administrador.
    echo  Clique com o botao direito neste arquivo e escolha
    echo  "Executar como administrador".
    echo.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\datalake\agendar_carga.ps1 %*
echo.
pause
