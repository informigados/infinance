@echo off
setlocal EnableExtensions

title INFinance - Sistema Financeiro Premium

cd /d "%~dp0"

set "PROJECT_DIR=%CD%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS_FILE=%PROJECT_DIR%\requirements.txt"
set "SECRET_FILE=%PROJECT_DIR%\.infinance.secret"

echo ================================================================
echo.
echo   IIIII  N   N  FFFFF  IIIII  N   N    A    N   N   CCCC  EEEEE
echo     I    NN  N  F        I    NN  N   A A   NN  N  C      E
echo     I    N N N  FFFF     I    N N N  AAAAA  N N N  C      EEEE
echo     I    N  NN  F        I    N  NN  A   A  N  NN  C      E
echo   IIIII  N   N  F      IIIII  N   N  A   A  N   N   CCCC  EEEEE
echo.
echo  Sistema Financeiro e Fiscal
echo  Status: Inicializando
echo.
echo ================================================================
echo.

echo [INFinance] Preparando ambiente...

if not exist "%REQUIREMENTS_FILE%" (
    echo [ERRO] Arquivo requirements.txt nao encontrado em "%PROJECT_DIR%".
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [INFinance] Ambiente virtual nao encontrado. Criando .venv...
    where py >nul 2>&1
    if %errorlevel%==0 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo [ERRO] Python nao encontrado no PATH.
            echo [ERRO] Instale o Python 3 e rode o script novamente.
            exit /b 1
        )
        python -m venv "%VENV_DIR%"
    )
)

if not exist "%PYTHON_EXE%" (
    echo [ERRO] Nao foi possivel criar o ambiente virtual.
    exit /b 1
)

echo [INFinance] Instalando/validando dependencias...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS_FILE%"
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias.
    exit /b 1
)

set /a INFINANCE_PORT=5000
:find_port
netstat -ano | findstr /R /C:":%INFINANCE_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    set /a INFINANCE_PORT+=1
    if %INFINANCE_PORT% GTR 65535 (
        echo [ERRO] Nao foi encontrada porta disponivel.
        exit /b 1
    )
    goto :find_port
)

set "INFINANCE_HOST=127.0.0.1"
set "INFINANCE_DEBUG=0"

if not defined INFINANCE_SECRET_KEY (
    if not exist "%SECRET_FILE%" (
        powershell -NoProfile -Command "[Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')" > "%SECRET_FILE%"
    )
    set /p INFINANCE_SECRET_KEY=<"%SECRET_FILE%"
)

echo [INFinance] Porta disponivel encontrada: %INFINANCE_PORT%
echo [INFinance] Abrindo em http://%INFINANCE_HOST%:%INFINANCE_PORT%/

if /I not "%INFINANCE_NO_BROWSER%"=="1" (
    start "" "http://%INFINANCE_HOST%:%INFINANCE_PORT%/"
)

"%PYTHON_EXE%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [ERRO] O sistema foi encerrado com codigo %EXIT_CODE%.
)

exit /b %EXIT_CODE%
