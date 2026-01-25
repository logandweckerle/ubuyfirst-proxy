@echo off
:: Run this as Administrator on Main PC (noobdestroyer)
:: Creates a network share for the ClaudeProxy folder

echo Creating network share...
net share ClaudeProxy="C:\Users\Logan Weckerle\Documents\ClaudeProxy" /GRANT:Everyone,READ

echo.
echo Share created! Access from minipc using:
echo   \\noobdestroyer\ClaudeProxy
echo   or
echo   \\192.168.40.3\ClaudeProxy
echo.
pause
