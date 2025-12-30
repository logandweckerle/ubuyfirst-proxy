@echo off
echo ========================================
echo   Claude Proxy v2 - HOT RELOAD ENABLED
echo ========================================
echo.

REM Set your Claude API key here
set ANTHROPIC_API_KEY=set ANTHROPIC_API_KEY=YOUR_API_KEY_HERE

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

echo.
echo Starting server on http://127.0.0.1:8000
echo.
echo *** HOT RELOAD ENABLED ***
echo Just save new .py file over the old one - auto restarts!
echo No need to stop/start the proxy.
echo.
echo Dashboard: http://localhost:8000
echo Press Ctrl+C to stop
echo.

REM Open browser after 3 second delay
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

REM Run with hot reload - watches for file changes
python -m uvicorn claude_proxy_server_v2:app --host 127.0.0.1 --port 8000 --reload

pause
