---
name: check-logs
description: Check recent server logs for errors or specific patterns
allowed-tools: Bash, Read
---

# Check Server Logs

Check the running server's output for errors or issues.

## Steps:

1. **Find the active server task**: Look for background tasks running main.py

2. **Read recent output**: Get the last 100 lines from the server output file:
   ```bash
   tail -100 "C:\Users\LOGANW~1\AppData\Local\Temp\claude\C--Users-Logan-Weckerle\tasks\*.output" 2>/dev/null | head -100
   ```

3. **Check for errors**: Search for ERROR, Exception, Traceback:
   ```bash
   grep -iE "ERROR|Exception|Traceback|FAIL" <output_file> | tail -20
   ```

4. **Report findings**:
   - Number of errors found
   - Most recent error messages
   - Any patterns (same error repeating?)
   - Suggested fixes if obvious

If $ARGUMENTS is provided, search for that specific pattern in the logs.
