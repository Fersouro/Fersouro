@echo off
REM ============================================================
REM  ATUALIZAR DATALAKE
REM  Clique duas vezes para puxar os dados novos do banco e
REM  gerar os Excel atualizados em C:\datalake\export
REM ============================================================
title Atualizando o datalake...
color 0B
cd /d C:\datalake

echo.
echo  ============================================================
echo   ATUALIZANDO O DATALAKE
echo   Isso conecta no banco e regenera os relatorios.
echo   Leva alguns minutos. Nao feche esta janela.
echo  ============================================================
echo.

if not exist "C:\datalake\setup_windows.ps1" (
    color 0C
    echo  ERRO: nao encontrei C:\datalake\setup_windows.ps1
    echo  O script de apoio nao esta na pasta. Sem ele nao da para rodar.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\datalake\setup_windows.ps1" -Run -LakeRoot "C:\datalake"
set CODIGO=%ERRORLEVEL%

echo.
echo  ============================================================
if "%CODIGO%"=="0" (
    color 0A
    echo   PRONTO. Dados atualizados.
    echo   Os Excel estao em C:\datalake\export -- abrindo a pasta...
    if exist "C:\datalake\export" start "" "C:\datalake\export"
) else (
    color 0C
    echo   A ATUALIZACAO TERMINOU COM PROBLEMA. Veja as mensagens acima.
    echo   Detalhes em: C:\datalake\saida-datalake.txt
)
echo  ============================================================
echo.
echo   Pode fechar esta janela ou apertar uma tecla.
pause >nul
