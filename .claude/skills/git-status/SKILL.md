---
name: git-status
description: Quick git status showing modified files and recent commits
allowed-tools: Bash
---

# Git Status

Show current git status and recent history:

## Run these commands:

```bash
cd "C:\Users\Logan Weckerle\Documents\ClaudeProxy\ClaudeProxyV3"

echo "=== Modified Files ==="
git status --short

echo ""
echo "=== Recent Commits ==="
git log --oneline -5

echo ""
echo "=== Unpushed Commits ==="
git log origin/main..HEAD --oneline 2>/dev/null || echo "(up to date)"
```

## Report:
- List modified/untracked files
- Show last 5 commits
- Indicate if there are unpushed changes
