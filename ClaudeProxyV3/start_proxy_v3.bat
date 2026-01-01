@echo off
echo ================================================
echo Claude Proxy v3 - Optimized
echo ================================================
echo.

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

echo.
echo Starting server at http://localhost:8000
echo.
echo Features active:
echo  - Async parallel image fetching
echo  - Image compression for large files (5MB limit)
echo  - Smart cache with TTL by recommendation type
echo  - Database connection pooling with WAL mode
echo  - Background spot price updates
echo  - Visual analytics dashboard
echo.

REM Auto-open browser after short delay
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

python main.py

pause
