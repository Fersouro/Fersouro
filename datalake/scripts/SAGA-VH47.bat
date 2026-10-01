@echo off
REM ============================================================
REM  SAGA2 - VH47  ->  PDFs  ->  PLANILHA DE GARANTIA
REM
REM  Duplo-clique. Abre o navegador no Portal Rede VW; se pedir,
REM  faca o login (fica guardado para as proximas vezes). A RPA
REM  segue sozinha: GARANTIA VOLKSWAGEN > SAGA > Lista de arquivos
REM  (SAGA2 - VH47), baixa so os relatorios ainda nao processados,
REM  le SG e valor total e lanca na planilha.
REM
REM  Opcoes (rodando pelo prompt):
REM    SAGA-VH47.bat --so-listar          mostra o que falta, nao baixa
REM    SAGA-VH47.bat --status             o que ja foi processado / deu erro
REM    SAGA-VH47.bat --testar-pdf X.pdf   so le o PDF e mostra (nao grava)
REM    SAGA-VH47.bat --importar PASTA     PDFs baixados a mao
REM
REM  Configuracao em C:\datalake\.env:
REM    SAGA_DN=<DN da concessionaria>   SAGA_PLANILHA=<caminho do .xlsx>
REM  Log, PDFs e controle: C:\datalake\rpa\saga_vh47\
REM ============================================================
title SAGA2 - VH47
cd /d C:\datalake

set PROJ=
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$p=(Get-ChildItem 'C:\datalake\app' -Recurse -Filter pyproject.toml -ErrorAction SilentlyContinue | Select-Object -First 1).DirectoryName; if ($p) { $p }"`) do set PROJ=%%P
if not defined PROJ (
    color 0C
    echo  ERRO: C:\datalake\app sem o projeto. Rode instalar_app.ps1 uma vez.
    pause
    exit /b 1
)
set PY="%PROJ%\.venv\Scripts\python.exe"
if not exist %PY% (
    color 0C
    echo  ERRO: nao achei %PY%. Rode ATUALIZAR.bat uma vez (cria o ambiente).
    pause
    exit /b 1
)

REM primeira vez: instala navegador-automacao e leitor de PDF no ambiente do datalake
%PY% -c "import playwright, pypdf" 2>nul || %PY% -m pip install --quiet -e "%PROJ%[rpa]"

echo.
%PY% -m datalake.rpa.saga_vh47 %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (color 0A & echo  PRONTO.) else if "%RC%"=="2" (color 0E & echo  Terminou, mas algum arquivo deu erro -- veja acima e rode --status.) else (color 0C & echo  FALHOU -- veja a mensagem acima.)
echo.
if "%RPA_SEM_PAUSA%"=="" pause
exit /b %RC%
