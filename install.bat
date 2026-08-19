@echo off
echo ===================================================
echo   LiveTranslator — Automated Setup & Installation
echo ===================================================
echo.

if not exist ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing runtime dependencies...
pip install -r runtime\inference\requirements.txt

echo.
echo ===================================================
echo   Installation Complete! Run run.bat to start.
echo ===================================================
pause
