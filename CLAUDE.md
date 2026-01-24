# Logan's Arbitrage Business - Master Context

## Business Overview

Online arbitrage operation focused on identifying underpriced items and reselling for profit. Two main channels:

1. **eBay Arbitrage** (ClaudeProxyV3) - Primary focus
   - Precious metals: Gold jewelry, sterling silver
   - Collectibles: Video games, LEGO, Pokemon/TCG

2. **Amazon Deals** (KeepaTracker) - Secondary
   - Price drop monitoring via Keepa API
   - Brand-specific tracking for flip opportunities

---

## Core Strategy

### Target Seller Profiles (HIGH VALUE)
These seller types frequently misprice items:
- **Estate sellers** - Keywords: estate, inherited, grandma, attic, downsizing
- **Thrift/charity stores** - Goodwill, Salvation Army, hospice
- **Casual individuals** - Short usernames, low feedback, no store
- **Liquidators** - Moving sales, storage unit finds

### Avoid These Sellers (LOW VALUE)
- **Professional dealers** - jewelry, coin, pawn shops
- **Business accounts with stores** - Know market pricing
- **High-volume sellers** - 1000+ feedback, established stores
- **Spammers** - Multiple listings in <30 seconds = auto-block

### Blocked Seller System
- 2,076+ blocked sellers (unified list)
- Auto-detection: 2+ listings in 30 seconds = blocked
- Instant PASS for all blocked sellers (no AI cost)
- File: `blocked_sellers.json`

---

## Profit Thresholds

### eBay Categories
| Category | Buy Threshold | Notes |
|----------|---------------|-------|
| Gold/Silver | Melt value calculation | Weight × purity × spot price |
| Video Games | 65% of market | PriceCharting verification |
| LEGO | 70% of market | Fewer false positives |
| Pokemon/TCG | 70% of market | Variant/language issues |

### Decision Flow
1. **BUY** - Clear profit margin, high confidence
2. **RESEARCH** - Potential but needs manual verification
3. **PASS** - No profit or high risk

---

## Technical Architecture

### Data Sources
- **uBuyFirst** - Real-time eBay listing alerts (webhook)
- **eBay Browse API** - Direct polling for gold/silver
- **PriceCharting** - Video game/LEGO market prices (117K products)
- **Keepa API** - Amazon price history and deals

### AI Pipeline
- **Tier 1**: GPT-4o/GPT-4o-mini for initial analysis
- **Tier 2**: Verification for BUY signals (prevents false positives)
- **Server-side validation**: Math checks, seller profiling, threshold enforcement

### Key Databases
- `pricecharting_prices.db` - 117,592 products with market values
- `arbitrage_data.db` - Historical listings and patterns
- `purchase_history.db` - Items actually purchased (for learning)
- `blocked_sellers.json` - Unified block list

---

## Listing Enhancements

Data extracted from each listing:
- **Freshness score** - Minutes since posted (newer = better)
- **Seller score** - 0-100 based on seller profile analysis
- **Best offer flag** - Negotiation opportunity
- **Sold time check** - Skip already-sold items

---

## Important Context

### What Works
- Estate sellers with gold jewelry (often no weight listed = opportunity)
- Thrift stores dumping donated items
- Individual sellers who don't know spot prices
- Items with scale photos showing weight

### What Doesn't Work
- Diamond/gemstone jewelry (too much value in stones)
- Professional coin/jewelry dealers
- Items priced at retail
- Watches (complex valuation)

### Current Focus
- Primary: Gold and sterling silver by weight
- Secondary: Video games with PriceCharting matches
- Exploring: LEGO sets, Pokemon cards

---

## Project Structure

```
ClaudeProxy/
├── CLAUDE.md                  ← This file (master context)
├── ClaudeProxyV3/             ← eBay arbitrage system (port 8000)
│   ├── main.py                ← Core proxy server
│   ├── utils/                 ← Utility modules
│   │   ├── extraction.py      ← Weight/karat extraction
│   │   ├── spam_detection.py  ← Seller spam blocking
│   │   └── constants.py       ← Thresholds, config
│   ├── database.py            ← Seller profiles, patterns
│   ├── prompts.py             ← AI prompts by category
│   ├── pricecharting_db.py    ← Video game pricing
│   ├── ebay_poller.py         ← Direct eBay API polling
│   └── blocked_sellers.json   ← Unified block list
│
└── KeepaTracker/              ← Amazon deals system (port 8001)
    ├── CLAUDE.md              ← Project documentation
    ├── main.py                ← FastAPI server
    ├── keepa_tracker.py       ← Keepa API client
    ├── keepa_dashboard.html   ← Web UI
    └── requirements.txt       ← Python dependencies
```

---

## Session Notes

Use this section to capture insights from each session:

### 2026-01-07
- Implemented seller spam detection (auto-block after 2 listings in 30s)
- Imported 2,076 blocked sellers from uBuyFirst + manual list
- Added listing enhancements: freshness scoring, seller scoring, best offer flag
- Fixed datetime shadowing bug and video game validation bug
- Added item deduplication (10-min window prevents re-evaluation)
- Added Crown Trifari + Rhinestone premium rule for costume jewelry
- Refactored main.py into utils/ modules (extraction, spam_detection, constants)
- Separated KeepaTracker into standalone project (port 8001)
