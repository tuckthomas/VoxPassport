@echo off
echo ===================================================
echo   Starting LiveTranslator Conference Runtime
echo ===================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo Starting Unified Inference Daemon on ws://127.0.0.1:8765...
start /b python runtime\inference\server\main.py

echo Opening Desktop Caption Overlay...
start "" "apps\desktop-companion\overlay\index.html"

echo.
echo LiveTranslator is active. Press Ctrl+C in this terminal to stop.
pause
