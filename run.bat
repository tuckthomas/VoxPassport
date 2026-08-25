@echo off
echo ===================================================
echo   Starting VoxPassport
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

where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js/npm was not found.
    echo Install Node.js 22 LTS, then run install.bat again.
    pause
    exit /b 1
)

if not exist "apps\client\node_modules" (
    echo Expo client dependencies are missing.
    echo Run install.bat first.
    pause
    exit /b 1
)

echo Starting integrated inference/native-audio daemon on port 8766...
echo Local TTS workers will be launched on demand by the runtime-profile supervisor.
start "VoxPassport Runtime" /b .venv\Scripts\python.exe -m runtime.inference.server.integrated_main

 echo Starting canonical Expo web client on port 8081...
start "VoxPassport Expo" cmd /k "cd /d %CD%\apps\client && npm run web -- --port 8081"

 echo.
echo Runtime API: http://127.0.0.1:8766
echo Expo client: http://127.0.0.1:8081
echo.
echo Opening the Expo client...
timeout /t 4 /nobreak >nul
start "" http://127.0.0.1:8081

echo VoxPassport is running. Close the Expo window and press Ctrl+C here to stop local development.
pause
