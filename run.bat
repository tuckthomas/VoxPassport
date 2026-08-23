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

if exist ".venv-xtts\Scripts\python.exe" (
    echo Starting optional XTTS Romanian worker on http://127.0.0.1:8098...
    start /b .venv-xtts\Scripts\python.exe runtime\workers\xtts_romanian\server.py
) else (
    echo XTTS Romanian worker is not installed. Run install_xtts_worker.bat to enable it.
)

echo Starting Unified Inference Daemon on ws://127.0.0.1:8765...
start /b .venv\Scripts\python.exe runtime\inference\server\xtts_main.py

echo Opening Desktop Caption Overlay...
start "" "apps\desktop-companion\overlay\index.html"

echo.
echo VoxPassport is active. Press Ctrl+C in this terminal to stop.
pause
