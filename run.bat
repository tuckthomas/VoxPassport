@echo off
echo ===================================================
echo   Starting VoxPassport Runtime
echo ===================================================
echo.

set "TEMP=%CD%\.setup-temp"
set "TMP=%CD%\.setup-temp"
set "HF_HOME=%CD%\.cache\huggingface"
set "TORCH_HOME=%CD%\.cache\torch"
set "XDG_CACHE_HOME=%CD%\.cache"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Project-local Python environment was not found.
    echo Run install.bat first.
    pause
    exit /b 1
)

echo Starting integrated inference/native-audio daemon...
echo Local TTS workers will be launched on demand by the runtime-profile supervisor.
start /b .venv\Scripts\python.exe -m runtime.inference.server.integrated_main

echo.
echo VoxPassport runtime is active at http://127.0.0.1:8766.
echo Launch the Expo client separately during migration/development.
echo Press Ctrl+C in this terminal to stop.
pause
