@echo off
setlocal

pushd "%~dp0" || exit /b 1

set "VENV_DIR=%CD%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REINSTALL=0"
set "SETUP_ONLY=0"

if /I "%~1"=="--reinstall" set "REINSTALL=1"
if /I "%~1"=="--setup-only" set "SETUP_ONLY=1"

if not exist "%VENV_PYTHON%" (
    echo [MyGitClient] Creating Python environment...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.12 -m venv "%VENV_DIR%"
    ) else (
        python -m venv "%VENV_DIR%"
    )
    if errorlevel 1 goto :failed
    set "REINSTALL=1"
)

if "%REINSTALL%"=="0" (
    "%VENV_PYTHON%" -c "import mygitclient, PySide6" >nul 2>nul
    if errorlevel 1 set "REINSTALL=1"
)

if "%REINSTALL%"=="1" (
    echo [MyGitClient] Installing application dependencies...
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :failed
)

if "%SETUP_ONLY%"=="1" (
    echo [MyGitClient] Environment is ready.
    popd
    exit /b 0
)

echo [MyGitClient] Starting...
"%VENV_PYTHON%" -m mygitclient
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%

:failed
echo.
echo [MyGitClient] Setup failed. Python 3.12 or newer and network access are required.
pause
popd
exit /b 1
