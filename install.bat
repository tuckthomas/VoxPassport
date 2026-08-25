@echo off
echo ===================================================
echo   VoxPassport — Automated Setup & Installation
echo ===================================================
echo.

set "PROJECT_PYTHON=.python312\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=py -3.12"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    %PROJECT_PYTHON% -m venv .venv
)

echo Installing runtime dependencies...
set "TEMP=%CD%\.setup-temp"
set "TMP=%CD%\.setup-temp"
set "PIP_CACHE_DIR=%CD%\.pip-cache"
set "HF_HOME=%CD%\.cache\huggingface"
set "TORCH_HOME=%CD%\.cache\torch"
set "XDG_CACHE_HOME=%CD%\.cache"
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install torch==2.13.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install -r runtime\inference\requirements.txt
if errorlevel 1 goto :error

where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js/npm was not found.
    echo Install Node.js 22 LTS, then run install.bat again.
    goto :error
)

echo Installing canonical Expo client dependencies...
call npm install --prefix apps\client --no-audit --no-fund
if errorlevel 1 goto :error

echo.
echo ===================================================
echo   Installation Complete! Run run.bat to start.
echo ===================================================
pause
exit /b 0

:error
echo.
echo ERROR: VoxPassport installation did not complete successfully.
pause
exit /b 1
