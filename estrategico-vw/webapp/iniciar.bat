@echo off
REM Sobe o Consolidador Estrategico VW no Windows.
REM   iniciar.bat          -> porta 8000
REM   iniciar.bat 8080     -> porta 8080
chcp 65001 >nul
cd /d "%~dp0"

set "PORTA=%~1"
if "%PORTA%"=="" set "PORTA=8000"

REM --- localiza o Python -------------------------------------------------
set "PY="
where py >/dev/null 2>&1
if %errorlevel%==0 set "PY=py -3"
if defined PY goto :achou
where python >/dev/null 2>&1
if %errorlevel%==0 set "PY=python"
:achou
if not defined PY goto :sempython

REM --- garante a dependencia --------------------------------------------
%PY% -c "import openpyxl" >/dev/null 2>&1
if %errorlevel% neq 0 (
    echo Instalando dependencia openpyxl...
    %PY% -m pip install --quiet openpyxl
)
%PY% -c "import openpyxl" >/dev/null 2>&1
if %errorlevel% neq 0 goto :semdep

REM --- sobe o servidor ---------------------------------------------------
echo.
echo Abra o endereco "na rede" nos outros computadores.
echo Se o Windows perguntar, permita o acesso em redes privadas.
echo.
%PY% app.py --porta %PORTA%
goto :fim

:sempython
echo.
echo Python nao encontrado neste computador.
echo Instale em https://www.python.org/downloads/ e marque
echo "Add python.exe to PATH" durante a instalacao.
echo.
pause
goto :fim

:semdep
echo.
echo Nao consegui instalar o openpyxl automaticamente.
echo Rode manualmente:  %PY% -m pip install openpyxl
echo.
pause

:fim
