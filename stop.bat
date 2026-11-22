@echo off
setlocal
echo Stopping Dyanphil server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    echo Terminating process tree %%a...
    taskkill /F /T /PID %%a >nul 2>&1
)
echo Server stopped.
