@echo off
echo ================================================
echo Claude Proxy v3 - Optimized
echo ================================================
echo.

REM Check if httpx is installed
python -c "import httpx" 2>nul
if errorlevel 1 (
    echo Installing httpx for async image fetching...
    pip install httpx
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
echo Optimizations active:
echo  - Async parallel image fetching
echo  - Smart cache with TTL by recommendation type
echo  - Database connection pooling with WAL mode
echo  - Background spot price updates
echo.

python main.py

pause
