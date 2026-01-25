# MiniPC Database Sync Setup

Sync the PriceCharting database from Main PC (noobdestroyer) to minipc.

## Step 1: Create Share on Main PC (one-time)

**On Main PC**, right-click `setup_share.bat` → Run as Administrator

Or manually:
1. Right-click `C:\Users\Logan Weckerle\Documents\ClaudeProxy`
2. Properties → Sharing → Advanced Sharing
3. Check "Share this folder"
4. Share name: `ClaudeProxy`
5. Permissions → Add → Everyone → Read

**Test from minipc:**
```
dir \\noobdestroyer\ClaudeProxy
```

---

## Step 2: Copy sync script to minipc

Copy `sync_pricecharting.bat` to the minipc:
```
C:\Users\logan\ubuyfirst-proxy\sync_pricecharting.bat
```

**Test it manually first:**
```
cd C:\Users\logan\ubuyfirst-proxy
sync_pricecharting.bat
```

---

## Step 3: Schedule Auto-Sync (on minipc)

**Option A: Task Scheduler GUI**
1. Open Task Scheduler
2. Create Basic Task → Name: "Sync PriceCharting DB"
3. Trigger: Daily (or your preference)
4. Action: Start a program
5. Program: `C:\Users\logan\ubuyfirst-proxy\sync_pricecharting.bat`
6. Finish

**Option B: Command line (run as Admin on minipc)**
```powershell
schtasks /create /tn "Sync PriceCharting DB" /tr "C:\Users\logan\ubuyfirst-proxy\sync_pricecharting.bat" /sc hourly /st 00:00
```

---

## Network Details

| PC | Hostname | IP |
|----|----------|-----|
| Main PC | noobdestroyer | 192.168.40.3 |
| minipc | ? | ? |

**Share path:** `\\noobdestroyer\ClaudeProxy`

**Database location:**
- Main PC: `C:\Users\Logan Weckerle\Documents\ClaudeProxy\ClaudeProxyV3\ClaudeProxyV3\pricecharting_prices.db`
- minipc: `C:\Users\logan\ubuyfirst-proxy\ClaudeProxyV3\pricecharting_prices.db`

---

## Troubleshooting

**"Network path not found"**
- Make sure Main PC is on and awake
- Try IP instead: `\\192.168.40.3\ClaudeProxy`
- Check Windows Firewall allows File Sharing

**"Access denied"**
- Re-run `setup_share.bat` as Administrator
- Check share permissions include Everyone or your user

**Database locked during sync**
- Stop the collectibles service before syncing
- Or schedule sync during off-hours
