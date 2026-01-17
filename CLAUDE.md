# ClaudeProxyV3 - eBay Arbitrage System

> See parent `../CLAUDE.md` for overall business strategy

## Project Purpose

FastAPI proxy server that intercepts eBay listing alerts from uBuyFirst, analyzes them with AI, and returns buy/pass recommendations with profit calculations.

---

## Architecture

### Entry Points
- `POST /match_mydata` - Main analysis endpoint (uBuyFirst webhook)
- `GET /match_mydata` - Same, supports GET requests
- `GET /health` - Health check
- `GET /dashboard` - Web UI for monitoring

### Core Flow
```
uBuyFirst Alert → match_mydata endpoint
    ↓
Spam Check (blocked sellers = instant PASS)
    ↓
Category Detection (gold/silver/videogames/lego)
    ↓
Fast Extraction (weight, karat, etc.)
    ↓
Tier 1 AI Analysis (GPT-4o)
    ↓
Server-side Validation
    ↓
Tier 2 Verification (if BUY signal)
    ↓
Response with recommendation
```

---

## Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `main.py` | Core server, routes, analysis pipeline | 22K |
| `prompts.py` | AI prompts for each category | 2K |
| `database.py` | Seller profiles, pattern storage | 1K |
| `pricecharting_db.py` | Video game/LEGO price lookups | 2K |
| `ebay_poller.py` | Direct eBay API polling | 900 |
| `keepa_tracker_v2.py` | Amazon deals (moving to separate project) | 1.5K |

---

## Category Handlers

### Gold/Silver
- Extract weight (grams, dwt, oz) from title/description
- Extract purity (10K, 14K, 18K, 24K, .925, .800)
- Calculate melt value: weight × purity × spot price
- Deduct for stones, watches, non-metal components
- Max buy = 90% of melt (margin for fees/shipping)

### Video Games
- Match to PriceCharting database (117K products)
- Console detection (PS5, Switch, Xbox, etc.)
- Condition handling (CIB, Loose, Sealed)
- Max buy = 65% of market price

### LEGO
- Set number extraction
- PriceCharting lookup
- Max buy = 70% of market (higher threshold due to false positives)

---

## Seller Profiling

### Score Components (0-100)
- Username patterns: estate, thrift, liquidator = +20
- Numbers in username = +5 (casual seller)
- Short username (<8 chars) = +5
- eBay data: Individual account = +5, Business = -10
- Low feedback (<100) = +10
- Thrift/charity store name = +20

### Recommendations
- Score >= 70: HIGH PRIORITY
- Score >= 55: MEDIUM PRIORITY
- Score < 55: NORMAL

---

## Spam Detection

- Track seller appearances with timestamps
- 2+ listings in 30 seconds = spammer
- Auto-add to `blocked_sellers.json`
- Instant PASS for all future listings

---

## API Endpoints

### Analysis
- `POST/GET /match_mydata` - Main analysis

### Seller Management
- `GET /api/sellers/stats` - Seller profile statistics
- `GET /api/sellers/high-value` - High-value sellers list
- `GET /api/sellers/score?seller_id=X` - Score a seller
- `POST /api/sellers/analyze` - Analyze new seller

### Blocked Sellers
- `GET /api/blocked-sellers` - List all blocked
- `POST /api/blocked-sellers/add?seller=X` - Block seller
- `POST /api/blocked-sellers/remove?seller=X` - Unblock
- `POST /api/blocked-sellers/import` - Bulk import JSON
- `GET /api/blocked-sellers/export` - Export list

### Utilities
- `GET /health` - Health check
- `GET /stats` - Session statistics
- `GET /dashboard` - Web UI

---

## Configuration

### Environment Variables
- `ANTHROPIC_API_KEY` - For Claude models
- `OPENAI_API_KEY` - For GPT-4o
- `EBAY_APP_ID` - eBay API credentials
- `EBAY_CERT_ID`
- `KEEPA_API_KEY` - Keepa API

### Thresholds (in main.py)
```python
CATEGORY_THRESHOLDS = {
    'lego': 0.70,
    'tcg': 0.70,
    'videogames': 0.65,
    'default': 0.65,
}
```

---

## Running

```bash
cd ClaudeProxyV3
python main.py
# Server starts at http://127.0.0.1:8000
```

---

## Known Issues / Tech Debt

1. `main.py` is 22K lines - needs refactoring into modules
2. Some duplicate code between category handlers
3. Image fetching could be more efficient
4. Consider moving Keepa to separate project

---

## Recent Changes

### 2026-01-07
- Added spam detection (30s window, 2 listing threshold)
- Imported 2,076 blocked sellers
- Added freshness scoring from PostedTime
- Added seller scoring with eBay data
- Fixed datetime shadowing bug
- Fixed video game validation (category undefined)
