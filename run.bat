@echo off
echo ===================================================
echo   Starting VoxPassport Conference Runtime
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

echo Starting Unified Inference Daemon on ws://127.0.0.1:8765...
start /b .venv\Scripts\python.exe runtime\inference\server\main.py

echo Opening Desktop Caption Overlay...
start "" "apps\desktop-companion\overlay\index.html"

echo.
echo VoxPassport is active. Press Ctrl+C in this terminal to stop.
pause
