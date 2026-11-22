@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Dyanphil - Offline Local Personal Search & Vault
echo   Running 100% on your laptop - 0% Cloud / Google
echo ===================================================

REM Check if server is already running on port 8000
curl.exe --noproxy "*" -s http://127.0.0.1:8000/health >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [Dyanphil] Server is already active on http://127.0.0.1:8000
    echo [Dyanphil] Opening laptop app window...
    start "" msedge --app=http://127.0.0.1:8000 2>nul || start "" http://127.0.0.1:8000
    exit /b 0
)

echo Activating backend virtual environment...
call "%~dp0backend\.venv\Scripts\activate.bat"

echo Launching laptop app window in 3 seconds...
start "" cmd /c "timeout /t 3 /nobreak >nul & (start \"\" msedge --app=http://127.0.0.1:8000 2>nul || start \"\" http://127.0.0.1:8000)"

echo Starting Dyanphil server on http://127.0.0.1:8000...
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
