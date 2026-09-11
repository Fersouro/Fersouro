@echo off
REM ============================================================
REM  ATUALIZAR DATALAKE  (carga + pagina de estoque)
REM
REM  Usa o projeto fixo em C:\datalake\app -- NAO baixa de novo a
REM  cada execucao (era o que trazia codigo velho do cache). Roda
REM  a carga com --keep-going (uma tabela com falha nao trava o
REM  resto) e sempre regenera a pagina.
REM
REM  Chamado pelas Tarefas Agendadas 6x/dia e por duplo-clique.
REM  Para atualizar o CODIGO do projeto, rode instalar_app.ps1.
REM ============================================================
title Atualizando o datalake...
color 0B
cd /d C:\datalake

echo.
echo  Atualizando o datalake (carga + pagina). Nao feche esta janela.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(Get-ChildItem 'C:\datalake\app' -Recurse -Filter setup_windows.ps1 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName; if (-not $s){ Write-Host 'ERRO: C:\datalake\app sem o projeto. Rode instalar_app.ps1 uma vez.' -ForegroundColor Red; exit 1 }; & $s -Run -KeepGoing -LakeRoot 'C:\datalake'"
set CODIGO=%ERRORLEVEL%

echo.
if "%CODIGO%"=="0" (
    color 0A
    echo  PRONTO. Pagina atualizada: C:\datalake\export\estoque_minimo.html
) else (
    color 0E
    echo  Terminou com aviso -- a pagina foi regenerada com o que ha no lake.
    echo  Detalhes em: C:\datalake\saida-datalake.txt
)
echo.
timeout /t 8 >nul
