# Service Split Guide: Precious Metals vs Collectibles

## Overview

Split ClaudeProxyV3 into two separate services:

| Service | Machine | Port | Categories |
|---------|---------|------|------------|
| **Precious Metals** | Main PC | 8000 | Gold, Silver, Watch, Platinum, Palladium |
| **Collectibles** | minipc | 8000 | Videogames, LEGO, TCG, Textbooks |

---

## Why Split?

- **Speed**: Precious metals items sell in seconds. Dedicated service = no resource contention
- **Simplicity**: Each service is smaller, easier to maintain
- **Reliability**: If one crashes, the other keeps running

---

## Architecture

```
uBuyFirst Extension
       │
       ├── Alias: "gold", "silver", "watch", "platinum", "palladium"
       │          └──────> Main PC (Precious Metals Service)
       │                   http://YOUR_MAIN_PC_IP:8000/match_mydata
       │
       └── Alias: "videogames", "lego", "tcg", "textbook"
                  └──────> minipc (Collectibles Service)
                           http://MINIPC_IP:8000/match_mydata
```

---

## What Each Service Needs

### PRECIOUS METALS SERVICE (Main PC)

**Agents (keep these):**
```
agents/
├── __init__.py     (modify - remove collectibles)
├── base.py         (keep - shared base class)
├── gold.py         (keep)
├── silver.py       (keep)
├── watch.py        (keep)
├── platinum.py     (keep)
├── palladium.py    (keep)
├── pens.py         (keep - some are gold)
├── knives.py       (DELETE)
├── industrial.py   (DELETE)
├── allen_bradley.py (DELETE)
├── videogames.py   (DELETE)
├── lego.py         (DELETE)
├── tcg.py          (DELETE)
├── textbook.py     (DELETE)
├── costume.py      (DELETE or keep - your choice)
└── coral_amber.py  (DELETE or keep - your choice)
```

**Precious Metals Specific Files (keep):**
```
ClaudeProxyV3/
├── spot_prices.py       (KEEP - fetches gold/silver prices)
├── utils/
│   └── extraction.py    (KEEP - weight/karat extraction)
```

**Routes (keep these):**
```
routes/
├── analysis.py          (KEEP - main /match_mydata endpoint)
├── ebay.py              (KEEP - eBay API for gold/silver searches)
├── sellers.py           (KEEP - seller profiling)
├── dashboard.py         (KEEP - web UI)
├── pricecharting.py     (DELETE - not needed)
├── keepa.py             (DELETE - not needed)
```

**Files to DELETE from Precious Metals:**
- `pricecharting_db.py` - Not needed
- `pricecharting_prices.db` - Not needed (4.7GB saved!)
- `bricklink_api.py` - Not needed
- All collectibles agents

---

### COLLECTIBLES SERVICE (minipc)

**Agents (keep these):**
```
agents/
├── __init__.py     (modify - remove precious metals)
├── base.py         (keep - shared base class)
├── videogames.py   (keep)
├── lego.py         (keep)
├── tcg.py          (keep)
├── textbook.py     (keep)
├── gold.py         (DELETE)
├── silver.py       (DELETE)
├── watch.py        (DELETE)
├── platinum.py     (DELETE)
├── palladium.py    (DELETE)
```

**Collectibles Specific Files (keep):**
```
ClaudeProxyV3/
├── pricecharting_db.py      (KEEP - database lookups)
├── pricecharting_prices.db  (KEEP - 117K products, 4.7GB)
├── bricklink_api.py         (KEEP - LEGO API)
```

**Routes (keep these):**
```
routes/
├── analysis.py          (KEEP - main /match_mydata endpoint)
├── pricecharting.py     (KEEP - PC database endpoints)
├── sellers.py           (KEEP - seller profiling)
├── dashboard.py         (KEEP - web UI)
├── ebay.py              (DELETE or simplify - not needed for collectibles)
```

**Files to DELETE from Collectibles:**
- `spot_prices.py` - Not needed
- `utils/extraction.py` - Weight/karat not needed
- All precious metals agents

---

## Shared Files (BOTH services need these)

These files are identical on both machines:

```
SHARED (copy to both):
├── pipeline/
│   ├── orchestrator.py      (main analysis logic)
│   ├── instant_pass.py      (rule-based quick decisions)
│   ├── fast_pass.py         (fast extraction checks)
│   ├── pre_checks.py        (spam, dedup, sold checks)
│   ├── tier1.py             (first AI pass)
│   ├── tier2.py             (verification AI pass)
│   ├── validation.py        (result validation)
│   ├── request_parser.py    (parse incoming requests)
│   ├── response_builder.py  (format responses)
│   └── listing_enrichment.py (add seller data, freshness)
│
├── services/
│   ├── app_state.py         (session tracking)
│   ├── clients.py           (API clients)
│   ├── deduplication.py     (prevent duplicate processing)
│   ├── error_handler.py     (error handling)
│   └── item_tracking.py     (track sold items)
│
├── utils/
│   ├── spam_detection.py    (blocked sellers)
│   ├── seller_scoring.py    (score sellers 0-100)
│   ├── discord.py           (Discord alerts)
│   └── constants.py         (shared constants)
│
├── templates/
│   └── renderers.py         (HTML rendering)
│
├── config.py                (API keys, settings)
├── database.py              (SQLite database)
├── smart_cache.py           (result caching)
├── blocked_sellers.json     (2,076+ blocked sellers)
└── main.py                  (FastAPI server)
```

---

## Step-by-Step Setup for minipc

### Step 1: Copy the entire project

```bash
# On minipc, clone or copy the repo
git clone https://github.com/logandweckerle/ubuyfirst-proxy.git
cd ubuyfirst-proxy
```

### Step 2: Delete precious metals files

```bash
# Delete precious metals agents
rm agents/gold.py
rm agents/silver.py
rm agents/watch.py
rm agents/platinum.py
rm agents/palladium.py
rm agents/pens.py
rm agents/coral_amber.py
rm agents/costume.py
rm agents/knives.py
rm agents/industrial.py
rm agents/allen_bradley.py

# Delete precious metals utils
rm ClaudeProxyV3/spot_prices.py

# Delete eBay poller (not needed for collectibles)
rm ClaudeProxyV3/ebay_poller.py
```

### Step 3: Modify agents/__init__.py

Remove precious metals from category detection. Edit `agents/__init__.py`:

**BEFORE (categories list):**
```python
CATEGORY_KEYWORDS = {
    'gold': ['gold', '14k', '18k', '10k', '24k', ...],
    'silver': ['sterling', '925', 'silver', ...],
    'watch': ['watch', 'rolex', 'omega', ...],
    'platinum': ['platinum', 'pt950', ...],
    'palladium': ['palladium', ...],
    'videogames': ['nintendo', 'playstation', 'xbox', ...],
    'lego': ['lego', ...],
    'tcg': ['pokemon', 'magic', 'yugioh', ...],
    'textbook': ['textbook', 'isbn', ...],
}
```

**AFTER (collectibles only):**
```python
CATEGORY_KEYWORDS = {
    'videogames': ['nintendo', 'playstation', 'xbox', ...],
    'lego': ['lego', ...],
    'tcg': ['pokemon', 'magic', 'yugioh', ...],
    'textbook': ['textbook', 'isbn', ...],
}
```

### Step 4: Modify main.py

Remove precious metals imports and routes:

```python
# DELETE these imports:
# from spot_prices import ...
# from ebay_poller import ...

# DELETE these route includes:
# app.include_router(ebay_router)
# app.include_router(ebay_race_router)
```

### Step 5: Copy the PriceCharting database

Make sure you have `pricecharting_prices.db` (4.7GB) on the minipc:
```bash
# Copy from main PC if needed
scp user@mainpc:/path/to/pricecharting_prices.db ./ClaudeProxyV3/
```

### Step 6: Set up environment

```bash
# Create .env file with API keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
EBAY_APP_ID=...
EBAY_CERT_ID=...
```

### Step 7: Test the service

```bash
cd ClaudeProxyV3
python main.py
# Should start on http://0.0.0.0:8000

# Test with curl
curl -X POST http://localhost:8000/match_mydata \
  -H "Content-Type: application/json" \
  -d '{"Title": "Pokemon Scarlet Violet Booster Box Sealed", "TotalPrice": "120", "response_type": "json"}'
```

---

## uBuyFirst Configuration

Configure uBuyFirst to route to the correct service:

### Precious Metals Aliases → Main PC
```
Alias: gold       → http://YOUR_MAIN_PC_IP:8000/match_mydata
Alias: silver     → http://YOUR_MAIN_PC_IP:8000/match_mydata
Alias: watch      → http://YOUR_MAIN_PC_IP:8000/match_mydata
Alias: platinum   → http://YOUR_MAIN_PC_IP:8000/match_mydata
Alias: palladium  → http://YOUR_MAIN_PC_IP:8000/match_mydata
```

### Collectibles Aliases → minipc
```
Alias: videogames → http://MINIPC_IP:8000/match_mydata
Alias: lego       → http://MINIPC_IP:8000/match_mydata
Alias: tcg        → http://MINIPC_IP:8000/match_mydata
Alias: textbook   → http://MINIPC_IP:8000/match_mydata
```

---

## Keeping Services in Sync

### Shared files to sync periodically:
1. `blocked_sellers.json` - Block list (sync both directions)
2. `database.py` schema changes
3. `pipeline/*` improvements
4. `utils/*` improvements

### Service-specific (don't sync):
- Precious metals: `spot_prices.py`, `extraction.py`, metal agents
- Collectibles: `pricecharting_db.py`, collectibles agents

### Recommended sync strategy:
```bash
# On minipc, pull shared changes from main repo
git pull origin main

# Then re-apply collectibles-specific changes
# (keep a branch for minipc-specific mods)
```

---

## Quick Reference: What Goes Where

| File/Folder | Main PC | minipc | Notes |
|-------------|---------|--------|-------|
| `agents/gold.py` | KEEP | DELETE | |
| `agents/silver.py` | KEEP | DELETE | |
| `agents/watch.py` | KEEP | DELETE | |
| `agents/videogames.py` | DELETE | KEEP | |
| `agents/lego.py` | DELETE | KEEP | |
| `agents/tcg.py` | DELETE | KEEP | |
| `spot_prices.py` | KEEP | DELETE | Fetches metal prices |
| `pricecharting_db.py` | DELETE | KEEP | Database lookups |
| `pricecharting_prices.db` | DELETE | KEEP | 4.7GB database |
| `pipeline/*` | KEEP | KEEP | Shared |
| `utils/spam_detection.py` | KEEP | KEEP | Shared |
| `blocked_sellers.json` | KEEP | KEEP | Sync between both |

---

## Troubleshooting

### "Category not detected"
- Check `agents/__init__.py` has the correct categories
- Make sure the Alias in uBuyFirst matches a supported category

### "PriceCharting database not found"
- Copy `pricecharting_prices.db` to `ClaudeProxyV3/` folder
- Check the path in `pricecharting_db.py`

### "Spot prices not updating"
- Only needed on Main PC (precious metals)
- Check `spot_prices.py` is present and Yahoo Finance is reachable

### "Blocked sellers not working"
- Make sure `blocked_sellers.json` is in the correct folder
- Sync between both services periodically

---

## Summary

1. **Main PC** = Precious metals (gold, silver, watch, platinum, palladium)
   - Needs: spot_prices.py, extraction.py, metal agents
   - Doesn't need: PriceCharting database

2. **minipc** = Collectibles (videogames, LEGO, TCG, textbooks)
   - Needs: pricecharting_db.py, pricecharting_prices.db, collectibles agents
   - Doesn't need: spot prices, weight extraction

3. **Both need**: pipeline/*, utils/spam_detection.py, blocked_sellers.json, main.py, config.py

4. **uBuyFirst**: Route aliases to correct IP addresses
