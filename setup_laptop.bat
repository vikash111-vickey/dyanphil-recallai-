@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo     Dyanphil - Laptop Installation & Setup
echo ===================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.11 or 3.12 from python.org
    pause
    exit /b 1
)

echo [1/4] Creating Python virtual environment...
if not exist "backend\.venv" (
    python -m venv backend\.venv
)

echo [2/4] Installing backend dependencies...
call "backend\.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r backend\requirements.txt

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Node.js / npm not found. Using pre-built UI if available.
) else (
    echo [3/4] Installing UI dependencies and building frontend...
    cd ui
    call npm install
    call npm run build
    cd ..
)

echo.
echo ===================================================
echo [4/4] Installation complete! Launching Dyanphil...
echo ===================================================
echo.
call start.bat
