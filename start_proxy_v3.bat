@echo off
echo ================================================
echo   ShadowSnipe - Stealth Arbitrage Detection
echo ================================================
echo.

REM Change to the script's directory (CRITICAL for .env loading)
cd /d "%~dp0"

REM Check if python-dotenv is installed
python -c "import dotenv" 2>nul
if errorlevel 1 (
    echo Installing python-dotenv for .env file support...
    pip install python-dotenv
)

REM Check if httpx is installed
python -c "import httpx" 2>nul
if errorlevel 1 (
    echo Installing httpx for async image fetching...
    pip install httpx
)

REM Check if Pillow is installed (for image compression)
python -c "from PIL import Image" 2>nul
if errorlevel 1 (
    echo Installing Pillow for image compression...
    pip install Pillow
)

REM Check if yfinance is installed  
python -c "import yfinance" 2>nul
if errorlevel 1 (
    echo Installing yfinance for spot prices...
    pip install yfinance
)

REM Check if requests is installed (for deals dashboard)
python -c "import requests" 2>nul
if errorlevel 1 (
    echo Installing requests for deals dashboard...
    pip install requests
)

echo.
echo Initializing at http://localhost:8000
echo.
echo Systems online:
echo  - Async parallel image analysis
echo  - AI-powered deal detection
echo  - Smart cache with adaptive TTL
echo  - Real-time spot price tracking
echo  - Discord snipe alerts
echo  - ShadowSnipe desktop app
echo.

REM Auto-open browser after short delay
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

REM Launch Deals Dashboard in separate window after proxy starts
start "" cmd /c "timeout /t 4 /nobreak >nul && python deals_dashboard.py"

REM Start the proxy server (this blocks until stopped)
python main.py

pause
