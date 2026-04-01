@echo off
setlocal EnableExtensions

title INFinance - Sistema Financeiro Premium

cd /d "%~dp0"

set "PROJECT_DIR=%CD%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS_FILE=%PROJECT_DIR%\requirements.txt"
set "REQ_STAMP_FILE=%VENV_DIR%\.requirements.stamp"
set "SECRET_FILE=%PROJECT_DIR%\.infinance.secret"
if not defined INFINANCE_BANNER_STYLE set "INFINANCE_BANNER_STYLE=neon"

echo ================================================================
echo.
echo  INFinance - Sistema Financeiro e Fiscal
echo  Status: Inicializando
echo  Banner: Pixel-Retro ^(%INFINANCE_BANNER_STYLE%^)
echo.
echo ================================================================
echo.

echo [INFinance] Preparando ambiente...

if not exist "%REQUIREMENTS_FILE%" (
    call :die "Arquivo requirements.txt nao encontrado em \"%PROJECT_DIR%\"."
)

if not exist "%PYTHON_EXE%" (
    echo [INFinance] Ambiente virtual nao encontrado. Criando .venv...
    where py >nul 2>&1
    if %errorlevel%==0 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            call :die "Python nao encontrado no PATH. Instale o Python 3 e rode o script novamente."
        )
        python -m venv "%VENV_DIR%"
    )
)

if not exist "%PYTHON_EXE%" (
    call :die "Nao foi possivel criar o ambiente virtual."
)

for %%F in ("%REQUIREMENTS_FILE%") do set "REQ_SIGNATURE=%%~zF__%%~tF"
set "LAST_REQ_SIGNATURE="
set "NEED_PIP_INSTALL=1"
if exist "%REQ_STAMP_FILE%" set /p LAST_REQ_SIGNATURE=<"%REQ_STAMP_FILE%"
if /I "%LAST_REQ_SIGNATURE%"=="%REQ_SIGNATURE%" set "NEED_PIP_INSTALL=0"
if /I "%INFINANCE_FORCE_PIP%"=="1" set "NEED_PIP_INSTALL=1"

if "%NEED_PIP_INSTALL%"=="1" (
    echo [INFinance] Instalando/validando dependencias...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS_FILE%"
    if errorlevel 1 (
        call :die "Falha ao instalar dependencias."
    )
    > "%REQ_STAMP_FILE%" echo %REQ_SIGNATURE%
) else (
    echo [INFinance] Dependencias inalteradas. Pulando pip install.
)

set /a INFINANCE_PORT=5000
:find_port
netstat -ano | findstr /R /C:":%INFINANCE_PORT% .*LISTENING" >nul
if not errorlevel 1 (
    set /a INFINANCE_PORT+=1
    if %INFINANCE_PORT% GTR 65535 (
        call :die "Nao foi encontrada porta disponivel."
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
    start "" "http://%INFINANCE_HOST%:%INFINANCE_PORT%/" >nul 2>&1
    if errorlevel 1 (
        echo [INFinance] Aviso: nao foi possivel abrir o navegador automaticamente.
    )
)

"%PYTHON_EXE%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [ERRO] O sistema foi encerrado com codigo %EXIT_CODE%.
    if /I not "%INFINANCE_NO_PAUSE%"=="1" (
        echo.
        echo Pressione qualquer tecla para fechar...
        pause >nul
    )
)

exit /b %EXIT_CODE%

:die
echo [ERRO] %~1
if /I not "%INFINANCE_NO_PAUSE%"=="1" (
    echo.
    echo Pressione qualquer tecla para fechar...
    pause >nul
)
exit /b 1
