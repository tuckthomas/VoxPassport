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
call .venv\Scripts\python.exe -m pip install torch==2.13.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
call .venv\Scripts\python.exe -m pip install -r runtime\inference\requirements.txt

echo.
echo ===================================================
echo   Installation Complete! Run run.bat to start.
echo ===================================================
pause
