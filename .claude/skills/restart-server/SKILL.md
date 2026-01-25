---
name: restart-server
description: Stop any running server and restart it, then verify health
allowed-tools: Bash, TaskStop, Read
---

# Restart Server

Restart the ClaudeProxyV3 FastAPI server:

1. **Stop existing server**: Find and stop any running background task that's running main.py (use TaskStop if there's a running task, or kill the process)

2. **Start new server**:
   ```bash
   cd "C:\Users\Logan Weckerle\Documents\ClaudeProxy\ClaudeProxyV3\ClaudeProxyV3" && python main.py
   ```
   Run this in the background.

3. **Wait and verify**: After 5 seconds, check health:
   ```bash
   curl -s http://localhost:8000/health
   ```

4. **Report status**: Tell me if server started successfully or if there were errors.

If there are import errors or startup failures, show me the relevant error from the logs.
