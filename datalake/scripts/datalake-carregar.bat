@echo off
REM ============================================================
REM  Datalake CCM -- carga completa
REM  Clique duas vezes neste arquivo para atualizar os dados.
REM  No fim, a pasta com os Excel abre sozinha.
REM ============================================================
title Datalake CCM - carregando...
cd /d C:\datalake

if not exist "C:\datalake\setup_windows.ps1" (
    echo.
    echo  ERRO: nao encontrei C:\datalake\setup_windows.ps1
    echo  Baixe o script antes de rodar este arquivo.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\datalake\setup_windows.ps1" -Run -LakeRoot "C:\datalake"
set CODIGO=%ERRORLEVEL%

echo.
echo ============================================================
if "%CODIGO%"=="0" (
    echo  CARGA CONCLUIDA. Abrindo a pasta dos arquivos...
    if exist "C:\datalake\export" start "" "C:\datalake\export"
) else (
    echo  A CARGA TERMINOU COM FALHAS. Veja as mensagens acima.
    echo  Detalhes em: C:\datalake\saida-datalake.txt
)
echo ============================================================
echo.
echo  Pressione qualquer tecla para fechar.
pause >nul
