@echo off
:: Run this on MINIPC to sync the PriceCharting database from Main PC
:: Can be scheduled with Task Scheduler to run hourly/daily

set SOURCE=\\noobdestroyer\ClaudeProxy\ClaudeProxyV3\ClaudeProxyV3
set DEST=C:\Users\logan\ubuyfirst-proxy\ClaudeProxyV3

echo ============================================
echo Syncing PriceCharting database from Main PC
echo ============================================
echo Source: %SOURCE%
echo Dest:   %DEST%
echo.

:: Check if source is accessible
if not exist "%SOURCE%\pricecharting_prices.db" (
    echo ERROR: Cannot access Main PC. Check network connection.
    echo Trying IP address instead...
    set SOURCE=\\192.168.40.3\ClaudeProxy\ClaudeProxyV3\ClaudeProxyV3
)

:: Sync only the database file (and any .db files)
robocopy "%SOURCE%" "%DEST%" pricecharting_prices.db /R:3 /W:5 /NP /NDL /NJH

if %ERRORLEVEL% LEQ 3 (
    echo.
    echo SUCCESS: Database synced!
) else (
    echo.
    echo WARNING: Sync may have had issues. Error level: %ERRORLEVEL%
)

echo.
echo Last sync: %DATE% %TIME%
