@echo off
setlocal
echo ===================================================
echo   VoxPassport - XTTS Romanian Driver Setup
echo ===================================================
echo.

set "PROJECT_PYTHON=.python312\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=py -3.12"

if not exist ".venv-xtts\Scripts\python.exe" (
    echo Creating isolated XTTS-capable TTS host environment...
    %PROJECT_PYTHON% -m venv .venv-xtts
    if errorlevel 1 goto :fail
)

set "TEMP=%CD%\.setup-temp"
set "TMP=%CD%\.setup-temp"
set "PIP_CACHE_DIR=%CD%\.pip-cache"
set "HF_HOME=%CD%\.cache\huggingface"
set "TORCH_HOME=%CD%\.cache\torch"

call .venv-xtts\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo Installing the same CUDA/PyTorch generation used by VoxPassport...
call .venv-xtts\Scripts\python.exe -m pip install torch==2.13.0 torchaudio==2.11.0 torchcodec==0.13.0 --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 goto :fail

rem Coqui remains isolated because its Transformers compatibility is narrower
rem than the primary Parakeet environment. It still runs the exact same generic
rem voxpassport.tts.v1 host, on port 8099.
call .venv-xtts\Scripts\python.exe -m pip install -r runtime\workers\tts_host\requirements-xtts.txt
if errorlevel 1 goto :fail

echo.
echo XTTS driver dependencies are installed.
echo run.bat will start the XTTS-capable generic TTS host on port 8099.
echo The Romanian checkpoint downloads automatically the first time XTTS is activated.
echo Worker environment: .venv-xtts
exit /b 0

:fail
echo.
echo ERROR: XTTS Romanian driver installation failed.
exit /b 1
