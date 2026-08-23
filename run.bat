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

echo Starting primary TTS plugin host on http://127.0.0.1:8098...
start /b .venv\Scripts\python.exe runtime\workers\tts_host\server.py --port 8098

if exist ".venv-xtts\Scripts\python.exe" (
    echo Starting XTTS-capable TTS plugin host on http://127.0.0.1:8099...
    start /b .venv-xtts\Scripts\python.exe runtime\workers\tts_host\server.py --port 8099
) else (
    echo XTTS Romanian is not installed. Run install_xtts_worker.bat to enable its isolated plugin host.
)

echo Starting Unified Inference Daemon on ws://127.0.0.1:8765...
start /b .venv\Scripts\python.exe runtime\inference\server\main.py

echo Opening Desktop Caption Overlay...
start "" "apps\desktop-companion\overlay\index.html"

echo.
echo VoxPassport is active. Press Ctrl+C in this terminal to stop.
pause
