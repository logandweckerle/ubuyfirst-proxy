"""
Claude Proxy Server v2 for uBuyFirst
Enhanced with Detailed Reasoning Dashboard for debugging and optimization

New Features:
- Click-through detail view for each listing
- Full input data display
- Category detection reasoning
- Calculation breakdown
- Raw AI response (debug mode)
- Flagging system for problem listings
- Export functionality
- SQLite database for persistent storage and analytics
- Auto-updating gold/silver spot prices
"""

import os
import sys
import json
import logging
import uuid
import sqlite3
import base64
import urllib.request
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
import anthropic
import uvicorn

# Try to import yfinance for spot prices
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[SPOT] yfinance not installed. Run: pip install yfinance")

# ============================================================
# SPOT PRICE SYSTEM
# ============================================================

SPOT_PRICES = {
    "gold_oz": 2650.00,  # Default fallback
    "silver_oz": 30.00,   # Default fallback
    "gold_gram": 85.20,
    "silver_gram": 0.96,
    "last_updated": None,
    "source": "default",
    # Karat rates (calculated from spot)
    "10K": 35.53,
    "14K": 49.67,
    "18K": 63.90,
    "22K": 78.13,
    "24K": 85.20,
    "sterling": 0.89,
}

def fetch_spot_prices():
    """Fetch current gold and silver spot prices"""
    global SPOT_PRICES
    
    print("\n" + "=" * 60)
    print("[SPOT] Fetching current spot prices...")
    print("=" * 60)
    
    # Method 1: Yahoo Finance (most reliable)
    if YFINANCE_AVAILABLE:
        try:
            print("[SPOT] Trying Yahoo Finance...")
            gold = yf.Ticker("GC=F")
            silver = yf.Ticker("SI=F")
            
            # Get last price
            gold_price = gold.fast_info.get('lastPrice', None)
            silver_price = silver.fast_info.get('lastPrice', None)
            
            if gold_price and silver_price and gold_price > 1000:  # Sanity check
                SPOT_PRICES["gold_oz"] = gold_price
                SPOT_PRICES["silver_oz"] = silver_price
                SPOT_PRICES["source"] = "Yahoo Finance"
                SPOT_PRICES["last_updated"] = datetime.now().isoformat()
                
                # Calculate per-gram rates
                update_gram_rates()
                
                print(f"[SPOT] ✓ SUCCESS - Gold: ${gold_price:.2f}/oz, Silver: ${silver_price:.2f}/oz")
                return True
        except Exception as e:
            print(f"[SPOT] Yahoo Finance failed: {e}")
    
    # Method 2: Metals.live API (free, no key)
    try:
        print("[SPOT] Trying Metals.live API...")
        req = urllib.request.Request(
            "https://api.metals.live/v1/spot",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if item.get('gold'):
                        SPOT_PRICES["gold_oz"] = float(item['gold'])
                    if item.get('silver'):
                        SPOT_PRICES["silver_oz"] = float(item['silver'])
                
                SPOT_PRICES["source"] = "Metals.live"
                SPOT_PRICES["last_updated"] = datetime.now().isoformat()
                update_gram_rates()
                print(f"[SPOT] ✓ SUCCESS - Gold: ${SPOT_PRICES['gold_oz']:.2f}/oz, Silver: ${SPOT_PRICES['silver_oz']:.2f}/oz")
                return True
    except Exception as e:
        print(f"[SPOT] Metals.live failed: {e}")
    
    # Method 3: Direct scrape from a reliable source
    try:
        print("[SPOT] Trying direct fetch...")
        req = urllib.request.Request(
            "https://www.goldapi.io/api/XAU/USD",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        # This might not work without API key, but worth trying
    except Exception as e:
        print(f"[SPOT] Direct fetch failed: {e}")
    
    print("[SPOT] ⚠ Using default/cached prices")
    return False

def update_gram_rates():
    """Update per-gram and karat rates from spot price"""
    global SPOT_PRICES
    
    gold_oz = SPOT_PRICES["gold_oz"]
    silver_oz = SPOT_PRICES["silver_oz"]
    
    # Convert to per-gram (31.1035 grams per troy ounce)
    gold_gram = gold_oz / 31.1035
    silver_gram = silver_oz / 31.1035
    
    SPOT_PRICES["gold_gram"] = gold_gram
    SPOT_PRICES["silver_gram"] = silver_gram
    
    # Update karat rates
    SPOT_PRICES["10K"] = gold_gram * 0.417
    SPOT_PRICES["14K"] = gold_gram * 0.583
    SPOT_PRICES["18K"] = gold_gram * 0.750
    SPOT_PRICES["22K"] = gold_gram * 0.917
    SPOT_PRICES["24K"] = gold_gram * 0.999
    
    # Sterling silver (92.5% pure)
    SPOT_PRICES["sterling"] = silver_gram * 0.925
    
    print(f"[SPOT] Rates updated:")
    print(f"  Gold: ${gold_gram:.2f}/g | 10K: ${SPOT_PRICES['10K']:.2f} | 14K: ${SPOT_PRICES['14K']:.2f} | 18K: ${SPOT_PRICES['18K']:.2f}")
    print(f"  Silver: ${silver_gram:.2f}/g | Sterling: ${SPOT_PRICES['sterling']:.2f}/g")

def get_dynamic_gold_prompt():
    """Generate gold prompt with current spot prices"""
    rates = SPOT_PRICES
    return f'''
Analyze this gold listing using Expected Value (EV) scoring and return JSON.

=== CRITICAL: CHECK IMAGES FIRST ===
LOOK AT THE IMAGES! If you see:
- A SCALE showing weight → USE THAT EXACT WEIGHT (most reliable!)
- Hallmarks/stamps → Note the karat
- Size reference → Helps estimate if no scale
- Condition issues → Factor into risk

SCALE PHOTOS OVERRIDE ALL ESTIMATES. If image shows "2.1g" on scale, use 2.1g, NOT your estimate!

=== CURRENT GOLD PRICING (spot ${rates["gold_oz"]:.2f}/oz) ===
- 10K (41.7%): ${rates["10K"]:.2f}/gram melt
- 14K (58.3%): ${rates["14K"]:.2f}/gram melt  
- 18K (75.0%): ${rates["18K"]:.2f}/gram melt
- 22K (91.7%): ${rates["22K"]:.2f}/gram melt
- 24K (99.9%): ${rates["24K"]:.2f}/gram melt

=== PRICING MODEL ===
- meltvalue = weight × karat rate (raw gold value)
- maxBuy = melt × 0.90 (maximum purchase price - 10% margin)
- sellPrice = melt × 0.96 (what we sell for)
- Profit = sellPrice - TotalPrice (if buying at listing price)
- If Profit < 0, it's a PASS (or make Best Offer at maxBuy)

=== BEST OFFER STRATEGY ===
If listing is overpriced but close, recommend making offer at maxBuy price.
Check if listing mentions "Best Offer" or "OBO" or "Or Best Offer".

=== WEIGHT ESTIMATION KNOWLEDGE BASE ===

** WATCHES **
| Type | Floor | Expected | Ceiling |
| Ladies 14K case only (GF/plated band) | 2.5g | 3g | 4g |
| Ladies case + few solid links | 4.5g | 5g | 6g |
| Mens typical 14K case | 7g | 9g | 12g |
| NOTE: Movement + glass = ~3g (NOT gold, deduct if total weight given) |

** CHAINS & BRACELETS **
| Type | Floor | Expected | Ceiling |
| Herringbone 4mm 7" | 4g | 5g | 6g |
| HOLLOW chains | -50% to -70% (much lighter) |

** RINGS **
| Type | Floor | Expected | Ceiling |
| Plain band thin | 1g | 2g | 3g |
| Class ring mens | 8g | 11g | 15g |

** BRACELETS **
| Type | Floor | Expected | Ceiling |
| Standard 7" link | 8g | 12g | 18g |
| Charm bracelet | 10g | 18g | 30g |

=== STONE DEDUCTIONS ===
| Accent/chip | 0.1-0.2g | Small gem | 0.3-0.5g | Large gem | 0.5-1.5g |

=== RISK FLAGS ===
HIGH: Cuban, Figaro, Franco chains, "Hip-hop" style
LOW: Vintage, Class rings, Known makers (Tiffany, Cartier)

=== CALCULATION PROCESS ===
1. IDENTIFY: Karat, item type, stated weight, stones, risk factors
2. CALCULATE:
   - Melt = Weight × Karat Rate
   - maxBuy = Melt × 0.90 (our max purchase price)
   - sellPrice = Melt × 0.96 (what we sell for)
   - Profit = sellPrice - TotalPrice
3. DECIDE:
   - BUY: Profit > $30 AND acceptable risk
   - PASS: Profit < $0 (suggest Best Offer if has OBO)

=== REASONING FORMAT ===
"DETECTION: [karat], [item type], [weight] | CALC: [weight]g × $[rate] = $[melt], maxBuy (×0.90) = $[max], sellPrice (×0.96) = $[sell], Price $[price] | PROFIT: $[sell - price] | DECISION: [BUY/PASS] [rationale]"

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (use PASS if Profit < 0)
- verified: "Yes"/"No"/"Unknown"
- karat: "10K"/"14K"/"18K"/"22K"/"24K"/"NA"
- itemtype: "Chain"/"Bracelet"/"Ring"/"Watch"/"Earrings"/"Pendant"/"Scrap"/"Plated"
- weight: like "5.5g" or "9g est" or "NA"
- meltvalue: raw melt value = weight × karat rate
- maxBuy: meltvalue × 0.90 (max purchase price)
- sellPrice: meltvalue × 0.96 (what we sell for)
- Margin: sellPrice MINUS TotalPrice
- pricepergram: TotalPrice / weight
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"/"NA"
- reasoning: Calculation summary

CRITICAL: If Margin is negative, Recommendation MUST be "PASS"
'''

def get_dynamic_silver_prompt():
    """Generate silver prompt with current spot prices"""
    rates = SPOT_PRICES
    return f'''
Analyze this silver/sterling listing and return JSON.

=== CHECK IMAGES FIRST ===
- A SCALE showing weight → USE THAT EXACT WEIGHT
- "Weighted" or "Reinforced" stamps → Apply 20% silver rule
- Plated indicators (EPNS, Rogers, Silver Plate) → PASS immediately

=== PRICING (spot ${rates["silver_oz"]:.2f}/oz = ${rates["silver_gram"]:.2f}/gram) ===
- Sterling melt rate: ${rates["sterling"]:.2f}/gram (92.5% pure)
- Target: 75% of melt value
- meltvalue = weight × ${rates["sterling"]:.2f} (solid sterling)
- meltvalue = weight × 0.20 × ${rates["sterling"]:.2f} (weighted items)
- maxBuy = meltvalue × 0.75
- Profit = maxBuy - TotalPrice

=== ITEM TYPE RULES ===
SOLID STERLING (100%): Flatware, bowls, trays, jewelry
WEIGHTED (20% silver): Large candlesticks, salt shakers, compotes

=== REASONING FORMAT ===
"DETECTION: [what found] | CALC: [weight]g × ${rates["sterling"]:.2f} = $[melt], ×0.75 = $[maxBuy], Price $[price] | PROFIT: $[maxBuy - price] | DECISION: [BUY/PASS]"

=== JSON KEYS ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (PASS if Profit < 0)
- verified: "Yes"/"No"/"Unknown"
- itemtype: "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Plated"
- weight: grams like "450g" or "NA"
- pricepergram: like "0.44" or "NA"
- meltvalue: weight × ${rates["sterling"]:.2f}
- maxBuy: meltvalue × 0.75
- Margin: maxBuy - TotalPrice
- confidence: "High"/"Medium"/"Low"
- reasoning: Include DETECTION | CALC | PROFIT | DECISION

CRITICAL: If Margin is negative, Recommendation MUST be "PASS"
OUTPUT ONLY THE JSON.
'''

def start_spot_price_updater():
    """Start background thread to update spot prices every 12 hours"""
    def updater():
        while True:
            fetch_spot_prices()
            # Sleep for 12 hours (43200 seconds)
            time.sleep(43200)
    
    thread = threading.Thread(target=updater, daemon=True)
    thread.start()
    print("[SPOT] Background updater started (refreshes every 12 hours)")

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# ============================================================
# DATABASE SETUP
# ============================================================
DB_PATH = Path(__file__).parent / "arbitrage_data.db"
print(f"[STARTUP] Database path: {DB_PATH}")

def init_database():
    """Initialize SQLite database with all tables"""
    print(f"[DB INIT] Creating/opening database at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Main listings table - stores every listing we analyze
    c.execute('''
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            title TEXT,
            total_price REAL,
            category TEXT,
            recommendation TEXT,
            margin TEXT,
            confidence TEXT,
            reasoning TEXT,
            
            -- Category-specific data stored as JSON
            analysis_json TEXT,
            input_json TEXT,
            raw_ai_response TEXT,
            
            -- User decisions (filled in later)
            user_action TEXT,
            actual_paid REAL,
            sold_price REAL,
            actual_profit REAL,
            notes TEXT,
            
            -- Metadata
            ebay_item_id TEXT,
            seller_name TEXT,
            category_reasons TEXT
        )
    ''')
    
    # Outcomes table - track what actually happened
    c.execute('''
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT,
            decision_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            ai_said TEXT,
            user_did TEXT,
            outcome TEXT,
            profit_loss REAL,
            notes TEXT,
            FOREIGN KEY (listing_id) REFERENCES listings(id)
        )
    ''')
    
    # Daily stats table - aggregate metrics
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_analyzed INTEGER DEFAULT 0,
            buy_count INTEGER DEFAULT 0,
            pass_count INTEGER DEFAULT 0,
            research_count INTEGER DEFAULT 0,
            total_bought INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            api_cost REAL DEFAULT 0
        )
    ''')
    
    # Keywords performance - track which keywords lead to profits
    c.execute('''
        CREATE TABLE IF NOT EXISTS keyword_performance (
            keyword TEXT PRIMARY KEY,
            times_seen INTEGER DEFAULT 0,
            times_bought INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            avg_margin REAL DEFAULT 0,
            last_seen DATETIME
        )
    ''')
    
    # Seller tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS sellers (
            seller_name TEXT PRIMARY KEY,
            times_seen INTEGER DEFAULT 0,
            times_bought INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            avg_deal_quality REAL DEFAULT 0,
            last_seen DATETIME,
            notes TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"[DB INIT] ✓ Database initialized at {DB_PATH}")
    print(f"[DB INIT] ✓ Database file exists: {DB_PATH.exists()}")

def save_listing_to_db(listing_data: dict):
    """Save a listing analysis to the database"""
    print(f"\n{'='*50}")
    print(f"[DB] ATTEMPTING TO SAVE TO DATABASE")
    print(f"[DB] Database path: {DB_PATH}")
    print(f"[DB] File exists: {DB_PATH.exists()}")
    print(f"{'='*50}")
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        
        listing_id = listing_data.get('id')
        title = listing_data.get('title', 'No title')
        print(f"[DB] Listing ID: {listing_id}")
        print(f"[DB] Title: {title[:50]}")
        
        c.execute('''
            INSERT OR REPLACE INTO listings 
            (id, timestamp, title, total_price, category, recommendation, 
             margin, confidence, reasoning, analysis_json, input_json, 
             raw_ai_response, category_reasons)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            listing_data.get('id'),
            listing_data.get('timestamp'),
            listing_data.get('title'),
            listing_data.get('total_price'),
            listing_data.get('category'),
            listing_data.get('recommendation'),
            listing_data.get('margin'),
            listing_data.get('confidence'),
            listing_data.get('reasoning'),
            json.dumps(listing_data.get('parsed_response', {})),
            json.dumps(listing_data.get('input_data', {})),
            listing_data.get('raw_response'),
            json.dumps(listing_data.get('category_reasons', []))
        ))
        
        # Update daily stats
        today = datetime.now().strftime('%Y-%m-%d')
        rec = listing_data.get('recommendation', 'RESEARCH')
        
        c.execute('''
            INSERT INTO daily_stats (date, total_analyzed, buy_count, pass_count, research_count, api_cost)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_analyzed = total_analyzed + 1,
                buy_count = buy_count + ?,
                pass_count = pass_count + ?,
                research_count = research_count + ?,
                api_cost = api_cost + ?
        ''', (
            today,
            1 if rec == 'BUY' else 0,
            1 if rec == 'PASS' else 0,
            1 if rec == 'RESEARCH' else 0,
            COST_PER_CALL,
            1 if rec == 'BUY' else 0,
            1 if rec == 'PASS' else 0,
            1 if rec == 'RESEARCH' else 0,
            COST_PER_CALL
        ))
        
        conn.commit()
        
        # Verify save worked
        c.execute('SELECT COUNT(*) FROM listings')
        count = c.fetchone()[0]
        print(f"[DB] ✓ SAVE SUCCESSFUL! Total listings in DB: {count}")
        
        conn.close()
    except Exception as e:
        print(f"[DB] ✗ ERROR SAVING: {e}")
        import traceback
        traceback.print_exc()

def record_outcome(listing_id: str, user_did: str, actual_paid: float = None, 
                   sold_price: float = None, notes: str = None):
    """Record what the user actually did with a listing"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        
        # Get the AI recommendation for this listing
        c.execute('SELECT recommendation FROM listings WHERE id = ?', (listing_id,))
        row = c.fetchone()
        ai_said = row[0] if row else 'UNKNOWN'
        
        # Calculate profit if we have the numbers
        profit_loss = None
        if actual_paid and sold_price:
            profit_loss = sold_price - actual_paid
        
        # Determine outcome
        outcome = 'PENDING'
        if profit_loss is not None:
            outcome = 'WIN' if profit_loss > 0 else 'LOSS'
        
        # Insert outcome record
        c.execute('''
            INSERT INTO outcomes (listing_id, ai_said, user_did, outcome, profit_loss, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (listing_id, ai_said, user_did, outcome, profit_loss, notes))
        
        # Update the listing record
        c.execute('''
            UPDATE listings 
            SET user_action = ?, actual_paid = ?, sold_price = ?, actual_profit = ?, notes = ?
            WHERE id = ?
        ''', (user_did, actual_paid, sold_price, profit_loss, notes, listing_id))
        
        # Update daily stats if bought
        if user_did == 'BOUGHT' and profit_loss:
            today = datetime.now().strftime('%Y-%m-%d')
            c.execute('''
                UPDATE daily_stats 
                SET total_bought = total_bought + 1, total_profit = total_profit + ?
                WHERE date = ?
            ''', (profit_loss, today))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Outcome recording error: {e}")
        return False

def get_analytics():
    """Get comprehensive analytics from the database"""
    print(f"\n{'='*60}")
    print(f"[ANALYTICS] FUNCTION CALLED")
    print(f"[ANALYTICS] DB_PATH = {DB_PATH}")
    print(f"[ANALYTICS] File exists: {DB_PATH.exists()}")
    print(f"{'='*60}")
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        analytics = {}
        
        # Overall stats
        c.execute('SELECT COUNT(*) as total FROM listings')
        row = c.fetchone()
        analytics['total_listings'] = row['total'] if row else 0
        print(f"[ANALYTICS] Query result - total_listings: {analytics['total_listings']}")
        
        c.execute('SELECT COUNT(*) as total FROM listings WHERE recommendation = "BUY"')
        row = c.fetchone()
        analytics['total_buys'] = row['total'] if row else 0
        print(f"[ANALYTICS] Query result - total_buys: {analytics['total_buys']}")
        
        c.execute('SELECT COUNT(*) as total FROM listings WHERE recommendation = "PASS"')
        row = c.fetchone()
        analytics['total_passes'] = row['total'] if row else 0
        print(f"[ANALYTICS] Query result - total_passes: {analytics['total_passes']}")
        
        c.execute('SELECT COUNT(*) as total FROM outcomes WHERE user_did = "BOUGHT"')
        row = c.fetchone()
        analytics['actual_purchases'] = row['total'] if row else 0
        
        c.execute('SELECT SUM(profit_loss) as total FROM outcomes WHERE outcome = "WIN"')
        row = c.fetchone()
        analytics['total_profit'] = row['total'] if row and row['total'] else 0
        
        # AI Accuracy
        analytics['ai_accuracy'] = 'N/A'
        
        # By category
        c.execute('''
            SELECT category, 
                   COUNT(*) as count,
                   SUM(CASE WHEN recommendation = "BUY" THEN 1 ELSE 0 END) as buys
            FROM listings 
            GROUP BY category
        ''')
        analytics['by_category'] = [dict(row) for row in c.fetchall()]
        print(f"[ANALYTICS] Categories found: {len(analytics['by_category'])}")
        
        # Last 7 days trend
        c.execute('''
            SELECT date, total_analyzed, buy_count, pass_count, total_profit, api_cost
            FROM daily_stats 
            ORDER BY date DESC 
            LIMIT 7
        ''')
        analytics['daily_trend'] = [dict(row) for row in c.fetchall()]
        print(f"[ANALYTICS] Daily trend days: {len(analytics['daily_trend'])}")
        
        # Recent listings
        c.execute('''
            SELECT id, timestamp, title, category, recommendation, margin
            FROM listings 
            ORDER BY timestamp DESC 
            LIMIT 20
        ''')
        analytics['recent'] = [dict(row) for row in c.fetchall()]
        print(f"[ANALYTICS] Recent listings: {len(analytics['recent'])}")
        
        # Top wins
        analytics['top_wins'] = []
        
        conn.close()
        
        print(f"[ANALYTICS] FINAL RESULT:")
        print(f"  total_listings: {analytics['total_listings']}")
        print(f"  total_buys: {analytics['total_buys']}")
        print(f"  total_passes: {analytics['total_passes']}")
        print(f"  categories: {len(analytics['by_category'])}")
        print(f"  recent: {len(analytics['recent'])}")
        print(f"{'='*60}\n")
        
        return analytics
    except Exception as e:
        print(f"[ANALYTICS] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return {"total_listings": 0, "total_buys": 0, "total_passes": 0, "actual_purchases": 0, "total_profit": 0, "ai_accuracy": "N/A", "by_category": [], "daily_trend": [], "recent": [], "top_wins": []}

# Initialize database on startup
init_database()

# ============================================================
# TOGGLE STATE - Controls whether API calls are made
# ============================================================
ENABLED = False  # Starts OFF - no API costs until you enable it
DEBUG_MODE = False  # Shows raw AI responses

# Enhanced stats tracking with full listing details
STATS = {
    "total_requests": 0,
    "api_calls": 0,
    "skipped": 0,
    "buy_count": 0,
    "pass_count": 0,
    "research_count": 0,
    "listings": {}  # Full listing details keyed by ID
}

COST_PER_CALL = 0.001  # Haiku 3.5 with images (~$0.001/call)

# ============================================================
# CONFIGURATION
# ============================================================
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
MODEL = "claude-3-5-haiku-20241022"
HOST = "127.0.0.1"
PORT = 8000  # Same port as AI Fields endpoint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# BUSINESS CONTEXT
# ============================================================
BUSINESS_CONTEXT = """
# Logan's eBay Arbitrage Business - Analysis Context

You are analyzing eBay listings for a precious metals arbitrage business.
Your job is to quickly evaluate listings and return structured JSON for the uBuyFirst software.

## SILVER BUYING RULES
- Target: 75% of melt value or under (MAX ceiling)
- Sweet spot: 50-60% of melt = excellent deal
- Current spot: ~$30/oz = $0.96/gram pure, $0.89/gram sterling (.925)
- 75% max = $0.67/gram for sterling

### Silver Item Types
- Flatware (spoons, forks, knives, serving): 100% solid silver weight
- Hollowware (bowls, trays, platters): 100% solid
- Weighted (candlesticks, candelabras): ONLY 20% is actual silver!
- Jewelry: PASS (different market)

### Sterling Detection - REQUIRED markers
VALID: "Sterling", "Sterling Silver", "925", ".925" in Title/BaseMetal/Metal/MetalPurity
KNOWN MAKERS (add confidence): Gorham, Wallace, Reed & Barton, Towle, Tiffany, Kirk, Georg Jensen, International

### INSTANT PASS - Plated/Not Silver
- Rogers, 1847 Rogers, Community, Holmes & Edwards = PLATED
- "Silver Plate", "EPNS", "Silverplate", "Nickel Silver", "German Silver" = NOT STERLING
- "Stainless", "18/10", "18/8" = NOT SILVER

### Weight Estimation (if not stated)
- Teaspoon: 20g
- Tablespoon/Fork: 45g
- Knife (hollow handle): 15g silver only
- Serving piece: 60g

## GOLD BUYING RULES
- Target: 90% of melt value (hard ceiling)
- Quick filter: Auto-PASS anything over $100/gram
- Current spot: ~$4,350/oz

### Karat Values (at $4,350/oz)
- 24K: $139.86/g melt, $125.87 max (90%)
- 18K: $104.90/g melt, $94.41 max
- 14K: $81.82/g melt, $73.64 max
- 10K: $58.32/g melt, $52.49 max

### Gold Detection - REQUIRED
VALID KARAT: 10K, 14K, 18K, 22K, 24K, or European (417, 585, 750, 916, 999)
INSTANT PASS: "Gold Filled", "GF", "Gold Plated", "GP", "HGE", "RGP", "Vermeil", "Gold Tone", "Brass"

### Fake Risk Assessment
HIGH RISK (avoid at high values): chains, rope, herringbone, simple bands, Cuban links
LOW RISK (safer): vintage with stones, signed pieces, class rings, dental gold

## LEGO BUYING RULES
- Sealed/new sets ONLY
- $30 minimum profit threshold
- REJECT: Mega Bloks, Lepin, Cobi, King (knockoffs), bulk bricks, used/opened

## IMPORTANT: REASONING FORMAT
Your "reasoning" field MUST include these sections separated by | (pipe):
DETECTION: [what category markers you found] | CALC: [show your math] | DECISION: [why BUY/PASS/RESEARCH]

Example reasoning:
"DETECTION: Found 14K in title, weight 5.2g stated | CALC: 5.2g x $81.82 = $425 melt, x0.90 = $383 max, list $290 = +$93 margin | DECISION: BUY positive margin low risk"

## OUTPUT FORMAT
Return ONLY valid JSON with these exact keys (no spaces in keys):
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- Additional fields depend on category (see specific prompts)
"""

# ============================================================
# CATEGORY-SPECIFIC PROMPTS
# ============================================================

SILVER_PROMPT = """
Analyze this silver/sterling listing and return JSON.

=== CHECK IMAGES FIRST ===
LOOK AT THE IMAGES! If you see:
- A SCALE showing weight → USE THAT EXACT WEIGHT
- Hallmarks (Sterling, 925, maker marks) → Verify authenticity
- "Weighted" or "Reinforced" stamps → Apply 20% silver rule
- Plated indicators (EPNS, Rogers, Silver Plate, Silverplate, WM Rogers) → PASS immediately

SCALE PHOTOS OVERRIDE ALL ESTIMATES.

=== PRICING (spot ~$30/oz = $0.96/gram) ===
- Sterling melt rate: $0.89/gram (after refining)
- Target: 75% of melt value (hard ceiling for buying)
- meltvalue = weight × $0.89 (solid sterling)
- meltvalue = weight × 0.20 × $0.89 (weighted items - only 20% is silver)
- maxBuy = meltvalue × 0.75
- Profit = maxBuy - TotalPrice (positive = good, negative = PASS)

=== ITEM TYPE RULES ===
SOLID STERLING (100% of weight is silver):
- Flatware (forks, spoons, knives with no stainless blade)
- Bowls, trays, plates
- Jewelry
- Candlesticks (small/solid only)

WEIGHTED ITEMS (only 20% is silver):
- Candlesticks (large, cement-filled)
- Salt/pepper shakers
- Compotes with loaded bases
- Items marked "Weighted" or "Reinforced"
- Any item that feels heavier than it looks

KNIFE RULE:
- Sterling handle with stainless blade = deduct blade weight
- Typical blade = 20-30g per knife
- Or estimate handle only at 25-35g each

=== CONFIDENCE ADJUSTMENTS ===
| Factor | Adjustment |
| Weight stated | +25% |
| Known maker (Gorham, Towle, Wallace, Reed & Barton, International) | +10% |
| Sterling/925 visible in photos | +10% |
| "Weighted" marked | +10% (know what you're buying) |
| No weight stated | -15% |
| Pattern lookup needed | -10% |
| Mixed lot unclear | -20% |

=== REASONING FORMAT (REQUIRED) ===
Your reasoning MUST follow this format:
"DETECTION: [what you found - sterling marks, maker, type] | CALC: [weight]g × $0.89 = $[melt], ×0.75 = $[maxBuy], Price $[price] | PROFIT: $[maxBuy - price] | DECISION: [BUY/PASS/RESEARCH] [why]"

=== DECISION RULES ===
- BUY: Profit > $20 AND confidence is Medium or High
- RESEARCH: Profit is borderline ($0-20) OR weight uncertain
- PASS: Profit < $0 OR plated OR not sterling

=== EXAMPLES ===

Example 1 - Good flatware deal:
{"Qualify":"Yes","Recommendation":"BUY","verified":"Yes","itemtype":"Flatware","weight":"450g","pricepergram":"0.44","meltvalue":"401","maxBuy":"300","Margin":"+100","confidence":"High","reasoning":"DETECTION: Sterling marked Gorham flatware set | CALC: 450g × $0.89 = $401 melt, ×0.75 = $300 maxBuy, Price $200 | PROFIT: +$100 | DECISION: BUY excellent margin known maker"}

Example 2 - Weighted candlesticks:
{"Qualify":"Yes","Recommendation":"BUY","verified":"Yes","itemtype":"Weighted","weight":"800g total","pricepergram":"0.31","meltvalue":"142","maxBuy":"107","Margin":"+57","confidence":"Medium","reasoning":"DETECTION: Sterling weighted candlesticks pair | CALC: 800g × 0.20 = 160g silver × $0.89 = $142 melt, ×0.75 = $107 maxBuy, Price $50 | PROFIT: +$57 | DECISION: BUY accounting for weighted"}

Example 3 - Overpriced PASS:
{"Qualify":"No","Recommendation":"PASS","verified":"Yes","itemtype":"Flatware","weight":"375g","pricepergram":"2.07","meltvalue":"334","maxBuy":"250","Margin":"-525","confidence":"High","reasoning":"DETECTION: .925 Sterling State House pattern | CALC: 375g × $0.89 = $334 melt, ×0.75 = $250 maxBuy, Price $775 | PROFIT: -$525 | DECISION: PASS significant overprice"}

Example 4 - Plated (not silver):
{"Qualify":"No","Recommendation":"PASS","verified":"No","itemtype":"Plated","weight":"NA","pricepergram":"NA","meltvalue":"0","maxBuy":"0","Margin":"NA","confidence":"High","reasoning":"DETECTION: WM Rogers silverplate, not sterling | CALC: No silver value | DECISION: PASS not sterling silver"}

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- verified: "Yes"/"No"/"Unknown"
- itemtype: "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Plated"/"NotSilver"
- weight: grams like "450g" or estimate "200g est" or "NA"
- pricepergram: listing price / weight, like "0.44" or "NA"
- meltvalue: weight × $0.89 (or ×0.20×$0.89 for weighted), like "401"
- maxBuy: meltvalue × 0.75, like "300"
- Margin: maxBuy - TotalPrice, like "+100" or "-525"
- confidence: "High"/"Medium"/"Low"
- reasoning: MUST include DETECTION | CALC | PROFIT | DECISION

CRITICAL: If Margin is negative, Recommendation MUST be "PASS"

OUTPUT ONLY THE JSON. NOTHING ELSE.
"""

GOLD_PROMPT = """
Analyze this gold listing using Expected Value (EV) scoring and return JSON.

=== CRITICAL: CHECK IMAGES FIRST ===
LOOK AT THE IMAGES! If you see:
- A SCALE showing weight → USE THAT EXACT WEIGHT (most reliable!)
- Hallmarks/stamps → Note the karat
- Size reference → Helps estimate if no scale
- Condition issues → Factor into risk

SCALE PHOTOS OVERRIDE ALL ESTIMATES. If image shows "2.1g" on scale, use 2.1g, NOT your estimate!

=== CURRENT GOLD PRICING (spot ~$4,500/oz) ===
- 10K (41.7%): $60.34/gram melt
- 14K (58.3%): $84.44/gram melt  
- 18K (75.0%): $108.52/gram melt
- 22K (91.7%): $132.68/gram melt
- 24K (99.9%): $144.55/gram melt

=== PRICING MODEL ===
- meltvalue = weight × karat rate (raw gold value)
- maxBuy = melt × 0.90 (maximum purchase price - 10% margin)
- sellPrice = melt × 0.96 (what we sell for)
- Profit = sellPrice - TotalPrice (if buying at listing price)
- If Profit < 0, it's a PASS (or make Best Offer at maxBuy)

=== BEST OFFER STRATEGY ===
If listing is overpriced but close, recommend making offer at maxBuy price.
Check if listing mentions "Best Offer" or "OBO" or "Or Best Offer".

=== EV SCORING SYSTEM ===
We use Expected Value to evaluate uncertain deals:
- Calculate FLOOR (worst case), EXPECTED, and CEILING (best case) weights
- If FLOOR case breaks even or small loss, and CEILING has good profit = +EV = BUY
- Max acceptable loss on floor case: ~$50-100

=== WEIGHT ESTIMATION KNOWLEDGE BASE ===

** WATCHES **
| Type | Floor | Expected | Ceiling |
| Ladies 14K case only (GF/plated band) | 2.5g | 3g | 4g |
| Ladies case + few solid links | 4.5g | 5g | 6g |
| Ladies full solid gold band | 25g | 30g | 40g |
| Mens typical 14K case | 7g | 9g | 12g |
| Mens Bulova Accutron SOLID | 16g | 17g | 19g |
| NOTE: Movement + glass = ~3g (NOT gold, deduct if total weight given) |

** CHAINS & BRACELETS **
| Type | Floor | Expected | Ceiling |
| Flat herringbone 2mm 7" | 2g | 2.5g | 3g |
| Herringbone 4mm 7" | 4g | 5g | 6g |
| Herringbone 8mm 20" | 15g | 17g | 20g |
| Omega/Mariner style | +20% | +25% | +30% | (heavier than standard) |
| Custom/Specialty links | +20% | +25% | +30% |
| HOLLOW chains | -50% | -60% | -70% | (much lighter) |
| Semi-hollow | -20% | -25% | -30% |

** EARRINGS **
| Type | Floor | Expected | Ceiling |
| Pierced studs | 0.5g | 1g | 2g |
| Pierced dangles | 1g | 2g | 4g |
| Pierced hoops | 1g | 3g | 6g |
| Clip-back (any style) | +1.5g | +2g | +2.5g | (heavier mechanism) |
| WARNING: Hoops can have resin inside - deduct if suspected |

** RINGS **
| Type | Floor | Expected | Ceiling |
| Plain band thin | 1g | 2g | 3g |
| Plain band wide | 3g | 4g | 6g |
| Class ring womens | 5g | 6g | 8g |
| Class ring mens | 8g | 11g | 15g |
| Ring with small stones | deduct 0.5-1g for stones |
| Ring with large center stone | deduct 1-3g for stones |

** BRACELETS **
| Type | Floor | Expected | Ceiling |
| Standard 7" link | 8g | 12g | 18g |
| Wide vintage bracelet | 15g | 22g | 35g |
| Tennis bracelet | (mostly stones - estimate gold at 30-50% of weight) |
| Bangle thin | 4g | 6g | 10g |
| Bangle wide/heavy | 10g | 15g | 25g |
| Charm bracelet | 10g | 18g | 30g | (depends on charm count) |

** PENDANTS **
| Type | Floor | Expected | Ceiling |
| Small pendant | 0.5g | 1g | 2g |
| Medium pendant | 2g | 3g | 5g |
| Large pendant | 4g | 6g | 10g |

** KARAT DENSITY ADJUSTMENT **
18K items weigh MORE than 14K of same size (denser gold):
- 10K = baseline
- 14K = +10-15% vs 10K
- 18K = +20-25% vs 10K

=== STONE DEDUCTIONS ===
| Stone Type | Per Stone Deduction |
| Accent/chip/melee | 0.1-0.2g |
| Small gemstone | 0.3-0.5g |
| Large gemstone/diamond | 0.5-1.5g |
| Jade cabochon | 0.3-0.5g |

=== RISK FLAGS ===
HIGH FAKE RISK (deduct from confidence):
- Cuban, Figaro, Franco chains
- "Hip-hop" style
- Too-good-to-be-true pricing

MODERATE RISK:
- Milor brand
- "Mesh" construction
- Hoops (possible resin)

LOW RISK (add to confidence):
- Vintage/antique pieces
- Class rings
- Known makers (Tiffany, Cartier, James Avery, David Yurman)
- Scrap/broken lots
- Dental gold

=== CALCULATION PROCESS ===

1. IDENTIFY: Karat, item type, stated weight (if any), stones, risk factors
2. ESTIMATE RANGE: Use knowledge base for Floor/Expected/Ceiling weights
3. APPLY DEDUCTIONS: Stones, movement (watches), hollow construction
4. CALCULATE:
   - Melt = Weight × Karat Rate
   - maxBuy = Melt × 0.90 (our max purchase price)
   - sellPrice = Melt × 0.96 (what we sell for)
   - Profit = sellPrice - TotalPrice
5. DECIDE:
   - BUY: Profit > $30 AND acceptable risk
   - PASS: Profit < $0 (suggest Best Offer if has OBO)
   - RESEARCH: Only if weight very uncertain

=== CONFIDENCE SCORING ===
Start at 60%, adjust:
| Factor | Adjustment |
| Weight explicitly stated | +25% |
| Weight in DWT | +20% |
| Clear karat stamp | +5% |
| Vintage/antique | +5% |
| Known maker | +5% |
| Scrap lot | +5% |
| High-risk chain style | -15% |
| Major stones (uncertainty) | -10% |
| No weight + hard to estimate | -15% |
| Milor/Mesh/Resin flags | -10% |

Final confidence caps at 95%.

=== REASONING FORMAT (REQUIRED) ===

Your reasoning MUST show the calculation:

"DETECTION: [karat], [item type], [weight] | CALC: [weight]g × $[rate] = $[melt], maxBuy (×0.90) = $[max], sellPrice (×0.96) = $[sell], Price $[price] | PROFIT: $[sell - price] | DECISION: [BUY/PASS] [rationale]"

=== EXAMPLES ===

Example 1 - Good deal, BUY:
{"Qualify":"Yes","Recommendation":"BUY","verified":"Yes","karat":"14K","itemtype":"Bracelet","weight":"5.5g","meltvalue":"464","maxBuy":"418","sellPrice":"446","Margin":"+38","pricepergram":"74.18","confidence":"High","fakerisk":"Low","reasoning":"DETECTION: 14K bracelet, 5.5g stated | CALC: 5.5g × $84.44 = $464 melt, maxBuy (×0.90) = $418, sellPrice (×0.96) = $446, Price $408 | PROFIT: +$38 | DECISION: BUY solid margin"}

Example 2 - Overpriced, PASS with offer suggestion:
{"Qualify":"No","Recommendation":"PASS","verified":"Yes","karat":"14K","itemtype":"Bracelet","weight":"81.4g","meltvalue":"6870","maxBuy":"6183","sellPrice":"6595","Margin":"-404","pricepergram":"85.99","confidence":"High","fakerisk":"Low","reasoning":"DETECTION: 14K charm bracelet, 81.4g verified | CALC: 81.4g × $84.44 = $6870 melt, maxBuy (×0.90) = $6183, sellPrice (×0.96) = $6595, Price $6999 | PROFIT: -$404 | DECISION: PASS overpriced - make Best Offer at $6183"}

Example 3 - Plated/Not gold:
{"Qualify":"No","Recommendation":"PASS","verified":"No","karat":"NA","itemtype":"Plated","weight":"NA","meltvalue":"0","maxBuy":"0","sellPrice":"0","Margin":"NA","pricepergram":"NA","confidence":"High","fakerisk":"NA","reasoning":"DETECTION: Gold filled GF marked not solid gold | CALC: No gold value | DECISION: PASS not solid gold"}

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (use PASS if Profit < 0, not RESEARCH)
- verified: "Yes"/"No"/"Unknown"
- karat: "10K"/"14K"/"18K"/"22K"/"24K"/"NA"
- itemtype: "Chain"/"Bracelet"/"Ring"/"Watch"/"Earrings"/"Pendant"/"Scrap"/"Plated"/"Jewelry"
- weight: stated weight like "5.5g" or estimate like "9g est" or "NA"
- meltvalue: raw melt value = weight × karat rate
- maxBuy: meltvalue × 0.90 (max purchase price)
- sellPrice: meltvalue × 0.96 (what we sell for)
- Margin: sellPrice MINUS TotalPrice. Positive = profit, Negative = loss
- pricepergram: TotalPrice divided by weight
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"/"NA"
- reasoning: Calculation summary

CRITICAL RULES:
1. If Margin is negative, Recommendation MUST be "PASS"
2. Never use "RESEARCH" for negative margin - use PASS
3. If PASS and listing has Best Offer, suggest offering at maxBuy price

CRITICAL: You MUST include meltvalue in every response. Calculate it as: weight × karat_rate
Example: 9.2g × $84.44 = $777 → meltvalue:"777"

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

LEGO_PROMPT = """
Analyze this LEGO listing and return JSON.

RULES:
- Sealed/new sets ONLY
- REJECT knockoffs: Mega Bloks, Lepin, Cobi, King, SY, Decool, Bela
- REJECT: bulk bricks, used/opened, incomplete
- ACCEPT: sealed sets, sealed lots

REASONING FORMAT (REQUIRED):
Your reasoning field MUST follow this format with | separators:
"DETECTION: [LEGO markers, condition, set info] | CONCERNS: [any red flags or none] | DECISION: [rationale]"

OUTPUT RULES:
Return ONLY a single line JSON object.
No markdown. No code blocks. No explanation before or after.

EXAMPLE OUTPUT:
{"Qualify":"Yes","Retired":"Unknown","SetCount":"3","reasoning":"DETECTION: Sealed lot, 3 LEGO sets visible, original packaging | CONCERNS: None, appears genuine | DECISION: QUALIFY for price check"}

JSON KEYS:
- Qualify: "Yes" or "No"
- Retired: "Yes" or "No" or "Unknown"
- SetCount: number as string like "1" or "3"
- reasoning: MUST include DETECTION | CONCERNS | DECISION sections

OUTPUT ONLY THE JSON. NOTHING ELSE.
"""

TCG_PROMPT = """
Analyze this TCG (Trading Card Game) sealed product listing and return JSON.

=== PRODUCT TYPES ===
- Booster Box: 36 packs, highest value
- ETB (Elite Trainer Box): 9 packs + accessories
- Booster Bundle: 6 packs
- Collection Box: Various pack counts + promo
- Booster Pack: Single pack
- Case: Multiple booster boxes (usually 6)

=== BUYING RULES ===
- Target: 65% of market price or under
- Must be SEALED/NEW condition
- English language preferred (Japanese secondary)
- Focus on Pokemon, Yu-Gi-Oh, Magic: The Gathering

=== INSTANT PASS ===
- Opened/used products
- Loose packs from boxes
- Resealed (look for red flags)
- Foreign languages (except Japanese)
- Bulk cards/singles

=== HIGH VALUE SETS (Pokemon) ===
Vintage WOTC (1999-2003): Base Set, Jungle, Fossil, Team Rocket, Neo series
- Base Set Unlimited Box: ~$25,000 market
- Skyridge Box: ~$55,000 market
- Neo Destiny Box: ~$17,000 market

Modern Hits:
- Evolving Skies: ~$300/box
- Hidden Fates ETB: ~$120
- Champion's Path ETB: ~$80
- Celebrations products: Check specific item

=== FAKE/REPACK WARNING SIGNS ===
- Price too good to be true
- Stock photos only
- New seller, no history
- "Mystery" or "repack" in title
- Damaged or missing shrink wrap

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [product type], [set name], [condition], [language] | CONCERNS: [red flags or none] | CALC: Market ~$[X], 65% = $[Y], list $[Z] = [margin] | DECISION: [BUY/PASS/RESEARCH] [rationale]"

=== JSON KEYS ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- producttype: "BoosterBox"/"ETB"/"Bundle"/"CollectionBox"/"Pack"/"Case"/"Other"
- setname: name of the set or "Unknown"
- tcgbrand: "Pokemon"/"YuGiOh"/"MTG"/"Other"
- condition: "Sealed"/"Opened"/"Unknown"
- language: "English"/"Japanese"/"Other"
- marketprice: estimated market value or "Unknown"
- maxBuy: 65% of market price or "NA"
- Margin: maxBuy - TotalPrice or "NA"
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"
- reasoning: MUST show DETECTION | CONCERNS | CALC | DECISION

EXAMPLE:
{"Qualify":"Yes","Recommendation":"BUY","producttype":"BoosterBox","setname":"Evolving Skies","tcgbrand":"Pokemon","condition":"Sealed","language":"English","marketprice":"300","maxBuy":"195","Margin":"+45","confidence":"High","fakerisk":"Low","reasoning":"DETECTION: Pokemon Booster Box, Evolving Skies, sealed, English | CONCERNS: None, reputable seller | CALC: Market ~$300, 65% = $195, list $150 = +$45 margin | DECISION: BUY strong margin on popular set"}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

# ============================================================
# FASTAPI SERVER
# ============================================================

app = FastAPI(title="Claude Proxy v2 for uBuyFirst")
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    title = data.get("Title", "").lower()
    reasons = []
    
    # Check alias first (most reliable)
    if "gold" in alias:
        reasons.append(f"Alias contains 'gold': {data.get('Alias', '')}")
        return "gold", reasons
    elif "silver" in alias or "sterling" in alias:
        reasons.append(f"Alias contains silver/sterling: {data.get('Alias', '')}")
        return "silver", reasons
    elif "lego" in alias:
        reasons.append(f"Alias contains 'lego': {data.get('Alias', '')}")
        return "lego", reasons
    elif "tcg" in alias or "pokemon" in alias or "sealed" in alias:
        reasons.append(f"Alias contains TCG keywords: {data.get('Alias', '')}")
        return "tcg", reasons
    
    # Fall back to title keywords
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "karat", "gold"]
    silver_keywords = ["sterling", "925", ".925"]
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "magic the gathering", "mtg booster", "sealed case", "tcg"]
    
    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    
    # IMPORTANT: If BOTH sterling AND gold karat appear, treat as SILVER
    # Items like "Sterling Silver 18K Gold Accent" are primarily silver with gold trim
    if silver_matches and gold_matches:
        reasons.append(f"Title contains BOTH sterling ({silver_matches}) AND gold ({gold_matches}) - treating as SILVER (gold is accent)")
        return "silver", reasons
    
    if gold_matches:
        reasons.append(f"Title contains gold keywords: {gold_matches}")
        return "gold", reasons
    elif silver_matches:
        reasons.append(f"Title contains silver keywords: {silver_matches}")
        return "silver", reasons
    elif lego_matches:
        reasons.append(f"Title contains LEGO keywords: {lego_matches}")
        return "lego", reasons
    elif tcg_matches:
        reasons.append(f"Title contains TCG keywords: {tcg_matches}")
        return "tcg", reasons
    
    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons

def get_category_prompt(category: str) -> str:
    """Get the appropriate prompt for a category, using dynamic spot prices for gold/silver"""
    if category == "gold":
        return get_dynamic_gold_prompt()
    elif category == "silver":
        return get_dynamic_silver_prompt()
    elif category == "lego":
        return LEGO_PROMPT
    elif category == "tcg":
        return TCG_PROMPT
    else:
        return get_dynamic_silver_prompt()

def format_listing_data(data: dict) -> str:
    lines = ["LISTING DATA:"]
    for key, value in data.items():
        if value:
            lines.append(f"- {key}: {value}")
    
    # Log the price being sent
    total_price = data.get('TotalPrice', data.get('ItemPrice', 'NOT FOUND'))
    print(f"[FORMAT] TotalPrice being sent to AI: {total_price}")
    
    return "\n".join(lines)

def sanitize_json_response(text: str) -> str:
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    text = text.replace("```json", "").replace("```", "")
    
    replacements = {
        "'": "'", "'": "'", """: '"', """: '"',
        "–": "-", "—": "-", "×": "x", "…": "...", "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = " ".join(text.split())
    return text.strip()

def parse_reasoning(reasoning: str) -> dict:
    """Parse the structured reasoning into components"""
    parts = {"detection": "", "calc": "", "decision": "", "concerns": "", "raw": reasoning}
    
    if "|" in reasoning:
        sections = reasoning.split("|")
        for section in sections:
            section = section.strip()
            upper = section.upper()
            if upper.startswith("DETECTION:"):
                parts["detection"] = section[10:].strip()
            elif upper.startswith("CALC:"):
                parts["calc"] = section[5:].strip()
            elif upper.startswith("DECISION:"):
                parts["decision"] = section[9:].strip()
            elif upper.startswith("CONCERNS:"):
                parts["concerns"] = section[9:].strip()
    
    return parts

# ============================================================
# MAIN ANALYSIS ENDPOINT - WITH IMAGE SUPPORT
# ============================================================

# Cache to prevent double API calls (uBuyFirst calls twice per click)
RESULT_CACHE = {}  # {title_hash: {"result": ..., "timestamp": ..., "html": ...}}
CACHE_TTL_SECONDS = 10  # Cache results for 10 seconds

@app.post("/match_mydata")
@app.get("/match_mydata")
async def analyze_listing(request: Request):
    print("=" * 60)
    print("[match_mydata] Endpoint called - FULL ANALYSIS")
    print("=" * 60)
    
    try:
        data = {}
        images = []  # Will extract images from JSON
        
        # Method 1: Query parameters (GET requests)
        query_data = dict(request.query_params)
        if query_data:
            data = query_data
            print(f"[match_mydata] Got {len(data)} fields from query params")
        
        # Read body for POST requests
        body = b""
        if not data:
            try:
                body = await request.body()
                print(f"[match_mydata] Body length: {len(body)} bytes")
            except Exception as e:
                print(f"[match_mydata] Failed to read body: {e}")
        
        # Method 2: JSON body (POST JSON) - THIS IS WHERE IMAGES COME FROM
        if not data and body:
            try:
                json_data = json.loads(body)
                if isinstance(json_data, dict):
                    data = json_data
                    print(f"[match_mydata] Got {len(data)} fields from JSON body")
                    print(f"[match_mydata] Keys: {list(data.keys())[:15]}")
            except Exception as e:
                print(f"[match_mydata] JSON parse failed: {e}")
                    
        # CHECK CACHE FIRST - prevent double API calls
        title = data.get('Title', '')
        total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))
        cache_key = f"{title}_{total_price}"
        
        if cache_key in RESULT_CACHE:
            cached = RESULT_CACHE[cache_key]
            age = (datetime.now() - cached['timestamp']).total_seconds()
            if age < CACHE_TTL_SECONDS:
                print(f"[CACHE HIT] Returning cached result (age: {age:.1f}s)")
                STATS["total_requests"] += 1  # Count request but not API call
                return HTMLResponse(content=cached['html'])
            else:
                print(f"[CACHE EXPIRED] Age {age:.1f}s > {CACHE_TTL_SECONDS}s")
                del RESULT_CACHE[cache_key]
        
        # Continue with image extraction
        if data and 'images' in data and data['images']:
            raw_images = data['images']
            print(f"[match_mydata] Found 'images' field, type: {type(raw_images)}")
            
            # DEBUG: See what's actually in the images
            if isinstance(raw_images, list) and len(raw_images) > 0:
                first_img = raw_images[0]
                print(f"[match_mydata] First image type: {type(first_img)}")
                if isinstance(first_img, str):
                    print(f"[match_mydata] First image starts with: {first_img[:60]}...")
            
            # Process images - they're URLs that need to be fetched
            if isinstance(raw_images, list):
                for img_url in raw_images[:5]:  # Limit to 5 images
                    if isinstance(img_url, str) and img_url.startswith("http"):
                        # FETCH the image from URL
                        try:
                            print(f"[match_mydata] Fetching image: {img_url[:60]}...")
                            req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=5) as resp:
                                img_data = base64.b64encode(resp.read()).decode('utf-8')
                                content_type = resp.headers.get('Content-Type', 'image/jpeg')
                                if ';' in content_type:
                                    content_type = content_type.split(';')[0]
                                images.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": content_type,
                                        "data": img_data
                                    }
                                })
                                print(f"[match_mydata] ✓ Fetched image, size: {len(img_data)} chars")
                        except Exception as e:
                            print(f"[match_mydata] ✗ Image fetch error: {e}")
                    
                    elif isinstance(img_url, str) and img_url.startswith("data:"):
                        # Already base64 data URL
                        try:
                            header, base64_data = img_url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            images.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_data
                                }
                            })
                        except Exception as e:
                            print(f"[match_mydata] Data URL parse error: {e}")
            
            print(f"[match_mydata] Extracted {len(images)} images!")
        
        # Method 3: URL-encoded body
        if not data and body:
            try:
                parsed = parse_qs(body.decode('utf-8', errors='ignore'))
                if parsed:
                    data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
                    print(f"[match_mydata] Got {len(data)} fields from URL-encoded body")
            except Exception as e:
                print(f"[match_mydata] URL-encoded parse failed: {e}")
        
        title = data.get('Title', 'No title')[:80]
        listing_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))
        
        print(f"[match_mydata] Title: {title[:50]}")
        print(f"[match_mydata] Price: ${total_price}")
        print(f"[match_mydata] Images: {len(images)}")
        
        STATS["total_requests"] += 1
        
        # Store basic listing info
        listing_record = {
            "id": listing_id,
            "timestamp": timestamp,
            "title": title,
            "total_price": total_price,
            "input_data": {k: v for k, v in data.items() if k != 'images'},  # Don't store huge image data
            "category": None,
            "category_reasons": [],
            "raw_response": None,
            "parsed_response": None,
            "reasoning_parts": {},
            "recommendation": "RESEARCH",
            "flagged": False,
            "notes": ""
        }
        
        if not ENABLED:
            print(f"[match_mydata] DISABLED - Returning placeholder")
            STATS["skipped"] += 1
            STATS["research_count"] += 1
            
            disabled_data = {
                "Qualify": "No", "Recommendation": "RESEARCH",
                "reasoning": "DETECTION: Proxy disabled | CALC: NA | DECISION: Enable at localhost:8000",
                "verified": "Unknown", "itemtype": "Unknown", "weight": "NA",
                "Margin": "NA", "maxBuy": "NA", "meltvalue": "NA",
                "karat": "NA", "pricepergram": "NA", "fakerisk": "NA", "confidence": "Low"
            }
            html_response = render_gold_html(disabled_data)
            return HTMLResponse(content=html_response)
        
        STATS["api_calls"] += 1
        
        # Detect category
        category, category_reasons = detect_category(data)
        listing_record["category"] = category
        listing_record["category_reasons"] = category_reasons
        print(f"[match_mydata] Category: {category}")
        
        # Get the appropriate prompt
        category_prompt = get_category_prompt(category)
        listing_text = format_listing_data(data)
        user_message = f"{category_prompt}\n\n{listing_text}"
        
        # Build message content - text + images if present
        if images:
            message_content = [{"type": "text", "text": user_message}]
            for img in images[:5]:  # Limit to 5 images
                message_content.append(img)
            print(f"[match_mydata] Sending {len(images)} images to Claude!")
        else:
            message_content = user_message
            print(f"[match_mydata] No images - text only")
        
        # Call Claude API
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=BUSINESS_CONTEXT,
            messages=[{"role": "user", "content": message_content}]
        )
        
        raw_response = response.content[0].text.strip()
        listing_record["raw_response"] = raw_response
        
        response_text = sanitize_json_response(raw_response)
        print(f"[match_mydata] Response: {response_text[:100]}...")
        
        try:
            result = json.loads(response_text)
            listing_record["parsed_response"] = result
            
            if 'reasoning' in result:
                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')
                listing_record["reasoning_parts"] = parse_reasoning(result['reasoning'])
            
            recommendation = result.get('Recommendation', 'RESEARCH')
            listing_record["recommendation"] = recommendation
            listing_record["margin"] = result.get('Margin', 'NA')
            listing_record["confidence"] = result.get('confidence', 'NA')
            listing_record["reasoning"] = result.get('reasoning', '')
            
            if recommendation == "BUY":
                STATS["buy_count"] += 1
            elif recommendation == "PASS":
                STATS["pass_count"] += 1
            else:
                STATS["research_count"] += 1
            
            STATS["listings"][listing_id] = listing_record
            _trim_listings()
            
            # Save to database
            save_listing_to_db(listing_record)
            
            # Add price to result for display
            result['listingPrice'] = total_price
            
            print(f"[match_mydata] Result: {recommendation}")
            html_response = render_result_html(result, category)
            
            # Cache the result to prevent double API calls
            cache_key = f"{title}_{total_price}"
            RESULT_CACHE[cache_key] = {
                "result": result,
                "html": html_response,
                "timestamp": datetime.now()
            }
            print(f"[CACHE STORE] Cached result for: {cache_key[:50]}...")
            
            return HTMLResponse(content=html_response)
            
        except json.JSONDecodeError as e:
            print(f"[match_mydata] JSON parse error: {e}")
            listing_record["notes"] = f"Parse error: {e}"
            listing_record["flagged"] = True
            STATS["listings"][listing_id] = listing_record
            _trim_listings()
            
            error_data = {
                "Qualify": "No", "Recommendation": "RESEARCH",
                "reasoning": f"DETECTION: Parse error | CALC: NA | DECISION: Manual review needed",
                "karat": "NA", "weight": "NA", "maxBuy": "NA", "meltvalue": "NA",
                "itemtype": "NA", "pricepergram": "NA", "fakerisk": "NA",
                "Margin": "NA", "confidence": "Low"
            }
            html_response = render_result_html(error_data, category)
            return HTMLResponse(content=html_response)
            
    except Exception as e:
        print(f"[match_mydata] ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        error_data = {
            "Qualify": "No", "Recommendation": "RESEARCH",
            "reasoning": f"DETECTION: Error | CALC: NA | DECISION: {str(e)[:50]}",
            "karat": "NA", "weight": "NA", "maxBuy": "NA", "meltvalue": "NA",
            "itemtype": "NA", "pricepergram": "NA", "fakerisk": "NA",
            "Margin": "NA", "confidence": "Low"
        }
        html_response = render_gold_html(error_data)
        return HTMLResponse(content=html_response)

def _trim_listings():
    """Keep only last 100 listings"""
    if len(STATS["listings"]) > 100:
        sorted_ids = sorted(STATS["listings"].keys(), key=lambda x: STATS["listings"][x]["timestamp"])
        for old_id in sorted_ids[:-100]:
            del STATS["listings"][old_id]

def render_gold_html(result: dict) -> str:
    """Render gold analysis result as HTML for uBuyFirst display"""
    recommendation = result.get('Recommendation', '--')
    reasoning = result.get('reasoning', 'Awaiting analysis...')
    karat = result.get('karat', '--')
    weight = result.get('weight', '--')
    meltvalue = result.get('meltvalue', '--')
    maxBuy = result.get('maxBuy', '--')
    sellPrice = result.get('sellPrice', '--')
    itemtype = result.get('itemtype', '--')
    fakerisk = result.get('fakerisk', '--')
    listingPrice = result.get('listingPrice', '--')
    
    # Clean up listingPrice - remove any existing $ signs
    if isinstance(listingPrice, str):
        listingPrice = listingPrice.replace('$', '').replace(',', '')
    
    # Calculate sellPrice if not provided (melt × 0.96)
    try:
        melt_num = float(str(meltvalue).replace('$', '').replace(',', ''))
        if sellPrice == '--' or sellPrice is None:
            sellPrice = int(melt_num * 0.96)
        # Calculate maxBuy if wrong (should be melt × 0.90)
        if maxBuy == '--' or maxBuy is None:
            maxBuy = int(melt_num * 0.90)
    except:
        pass
    
    # Calculate CORRECT profit: sellPrice - listingPrice
    offer_suggestion = ""
    try:
        price_num = float(str(listingPrice).replace('$', '').replace(',', ''))
        sell_num = float(str(sellPrice).replace('$', '').replace(',', ''))
        max_num = float(str(maxBuy).replace('$', '').replace(',', ''))
        profit = sell_num - price_num
        
        if profit >= 0:
            margin = f"+${profit:.0f} profit"
            margin_class = 'margin-positive'
        else:
            margin = f"-${abs(profit):.0f} loss"
            margin_class = 'margin-negative'
            # Override recommendation if margin is negative
            if recommendation in ['BUY', 'RESEARCH']:
                recommendation = 'PASS'
            # Suggest Best Offer at maxBuy
            offer_suggestion = f"<div style='background:#fff3cd;padding:10px;border-radius:8px;margin-top:10px;font-weight:bold;color:#856404;'>💰 Make Best Offer: ${max_num:.0f}</div>"
    except:
        margin = result.get('Margin', '--')
        margin_class = 'margin-positive' if margin and '+' in str(margin) else 'margin-negative'
    
    # Determine card class
    if recommendation == 'BUY':
        card_class = 'buy'
    elif recommendation == 'PASS':
        card_class = 'pass'
    else:
        card_class = 'research'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; }}
.result-card.buy {{ background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); border: 3px solid #28a745; }}
.result-card.pass {{ background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); border: 3px solid #dc3545; }}
.result-card.research {{ background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%); border: 3px solid #ffc107; }}
.status {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
.result-card.buy .status {{ color: #155724; }}
.result-card.pass .status {{ color: #721c24; }}
.result-card.research .status {{ color: #856404; }}
.margin-display {{ font-size: 28px; font-weight: bold; margin-bottom: 10px; }}
.margin-positive {{ color: #155724; }}
.margin-negative {{ color: #721c24; }}
.price-row {{ display: flex; justify-content: center; gap: 20px; margin-bottom: 15px; padding: 10px; background: rgba(255,255,255,0.5); border-radius: 8px; flex-wrap: wrap; }}
.price-item {{ text-align: center; min-width: 80px; }}
.price-label {{ font-size: 10px; color: #666; text-transform: uppercase; }}
.price-value {{ font-size: 18px; font-weight: bold; color: #333; }}
.price-value.max {{ color: #28a745; }}
.price-value.sell {{ color: #17a2b8; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 18px; font-weight: bold; color: #333; }}
</style>
</head>
<body>
<div class="container">
<div class="result-card {card_class}">
<div class="status">{recommendation}</div>
<div class="margin-display {margin_class}">{margin}</div>
<div class="price-row">
<div class="price-item">
<div class="price-label">List Price</div>
<div class="price-value">${listingPrice}</div>
</div>
<div class="price-item">
<div class="price-label">Max Buy (90%)</div>
<div class="price-value max">${maxBuy}</div>
</div>
<div class="price-item">
<div class="price-label">Sell Price (96%)</div>
<div class="price-value sell">${sellPrice}</div>
</div>
<div class="price-item">
<div class="price-label">Melt Value</div>
<div class="price-value">${meltvalue}</div>
</div>
</div>
{offer_suggestion}
<div class="reason">{reasoning}</div>
<div class="info-grid">
<div class="info-box">
<div class="info-label">Karat</div>
<div class="info-value">{karat}</div>
</div>
<div class="info-box">
<div class="info-label">Weight</div>
<div class="info-value">{weight}</div>
</div>
<div class="info-box">
<div class="info-label">Type</div>
<div class="info-value">{itemtype}</div>
</div>
<div class="info-box">
<div class="info-label">Risk</div>
<div class="info-value">{fakerisk}</div>
</div>
</div>
</div>
</div>
</body>
</html>'''
    return html

def render_silver_html(result: dict) -> str:
    """Render silver analysis result as HTML"""
    recommendation = result.get('Recommendation', '--')
    reasoning = result.get('reasoning', 'Awaiting analysis...')
    itemtype = result.get('itemtype', '--')
    weight = result.get('weight', '--')
    meltvalue = result.get('meltvalue', '--')
    maxBuy = result.get('maxBuy', '--')
    confidence = result.get('confidence', '--')
    listingPrice = result.get('listingPrice', '--')
    
    # Clean up listingPrice - remove any existing $ signs
    if isinstance(listingPrice, str):
        listingPrice = listingPrice.replace('$', '').replace(',', '')
    
    # Calculate CORRECT margin: maxBuy - listingPrice (positive = profit)
    offer_suggestion = ""
    try:
        price_num = float(str(listingPrice).replace('$', '').replace(',', ''))
        max_num = float(str(maxBuy).replace('$', '').replace(',', ''))
        profit = max_num - price_num
        if profit >= 0:
            margin = f"+${profit:.0f} profit"
            margin_class = 'margin-positive'
        else:
            margin = f"-${abs(profit):.0f} loss"
            margin_class = 'margin-negative'
            # Override recommendation if margin is negative
            if recommendation in ['BUY', 'RESEARCH']:
                recommendation = 'PASS'
            # Suggest Best Offer at maxBuy
            offer_suggestion = f"<div style='background:#fff3cd;padding:10px;border-radius:8px;margin-top:10px;font-weight:bold;color:#856404;'>💰 Make Best Offer: ${max_num:.0f}</div>"
    except:
        margin = result.get('Margin', '--')
        margin_class = 'margin-positive' if margin and '+' in str(margin) else 'margin-negative'
    
    if recommendation == 'BUY':
        card_class = 'buy'
    elif recommendation == 'PASS':
        card_class = 'pass'
    else:
        card_class = 'research'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; }}
.result-card.buy {{ background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); border: 3px solid #28a745; }}
.result-card.pass {{ background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); border: 3px solid #dc3545; }}
.result-card.research {{ background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%); border: 3px solid #ffc107; }}
.status {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
.result-card.buy .status {{ color: #155724; }}
.result-card.pass .status {{ color: #721c24; }}
.result-card.research .status {{ color: #856404; }}
.margin-display {{ font-size: 28px; font-weight: bold; margin-bottom: 10px; }}
.margin-positive {{ color: #155724; }}
.margin-negative {{ color: #721c24; }}
.price-row {{ display: flex; justify-content: center; gap: 30px; margin-bottom: 15px; padding: 10px; background: rgba(255,255,255,0.5); border-radius: 8px; }}
.price-item {{ text-align: center; }}
.price-label {{ font-size: 11px; color: #666; text-transform: uppercase; }}
.price-value {{ font-size: 20px; font-weight: bold; color: #333; }}
.price-value.max {{ color: #28a745; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 18px; font-weight: bold; color: #333; }}
</style>
</head>
<body>
<div class="container">
<div class="result-card {card_class}">
<div class="status">{recommendation}</div>
<div class="margin-display {margin_class}">{margin}</div>
<div class="price-row">
<div class="price-item">
<div class="price-label">Listing Price</div>
<div class="price-value">${listingPrice}</div>
</div>
<div class="price-item">
<div class="price-label">Max Buy (75%)</div>
<div class="price-value max">${maxBuy}</div>
</div>
<div class="price-item">
<div class="price-label">Melt Value</div>
<div class="price-value">${meltvalue}</div>
</div>
</div>
{offer_suggestion}
<div class="reason">{reasoning}</div>
<div class="info-grid">
<div class="info-box">
<div class="info-label">Type</div>
<div class="info-value">{itemtype}</div>
</div>
<div class="info-box">
<div class="info-label">Weight</div>
<div class="info-value">{weight}</div>
</div>
<div class="info-box">
<div class="info-label">Confidence</div>
<div class="info-value">{confidence}</div>
</div>
</div>
</div>
</div>
</body>
</html>'''
    return html

def render_lego_html(result: dict) -> str:
    """Render LEGO analysis result as HTML"""
    qualify = result.get('Qualify', '--')
    retired = result.get('Retired', '--')
    setcount = result.get('SetCount', '--')
    reasoning = result.get('reasoning', 'Awaiting analysis...')
    
    card_class = 'buy' if qualify == 'Yes' else 'pass'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; }}
.result-card.buy {{ background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); border: 3px solid #28a745; }}
.result-card.pass {{ background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); border: 3px solid #dc3545; }}
.status {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
.result-card.buy .status {{ color: #155724; }}
.result-card.pass .status {{ color: #721c24; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 18px; font-weight: bold; color: #333; }}
</style>
</head>
<body>
<div class="container">
<div class="result-card {card_class}">
<div class="status">{'QUALIFY' if qualify == 'Yes' else 'PASS'}</div>
<div class="reason">{reasoning}</div>
<div class="info-grid">
<div class="info-box">
<div class="info-label">Qualify</div>
<div class="info-value">{qualify}</div>
</div>
<div class="info-box">
<div class="info-label">Retired</div>
<div class="info-value">{retired}</div>
</div>
<div class="info-box">
<div class="info-label">Set Count</div>
<div class="info-value">{setcount}</div>
</div>
</div>
</div>
</div>
</body>
</html>'''
    return html

def render_tcg_html(result: dict) -> str:
    """Render TCG analysis result as HTML"""
    recommendation = result.get('Recommendation', '--')
    margin = result.get('Margin', '--')
    reasoning = result.get('reasoning', 'Awaiting analysis...')
    producttype = result.get('producttype', '--')
    setname = result.get('setname', '--')
    tcgbrand = result.get('tcgbrand', '--')
    marketprice = result.get('marketprice', '--')
    maxBuy = result.get('maxBuy', '--')
    fakerisk = result.get('fakerisk', '--')
    
    if recommendation == 'BUY':
        card_class = 'buy'
    elif recommendation == 'PASS':
        card_class = 'pass'
    else:
        card_class = 'research'
    
    margin_class = 'margin-positive' if margin and '+' in str(margin) else 'margin-negative'
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; }}
.result-card.buy {{ background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); border: 3px solid #28a745; }}
.result-card.pass {{ background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); border: 3px solid #dc3545; }}
.result-card.research {{ background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%); border: 3px solid #ffc107; }}
.status {{ font-size: 36px; font-weight: bold; margin-bottom: 5px; }}
.result-card.buy .status {{ color: #155724; }}
.result-card.pass .status {{ color: #721c24; }}
.result-card.research .status {{ color: #856404; }}
.margin-display {{ font-size: 28px; font-weight: bold; margin-bottom: 10px; }}
.margin-positive {{ color: #155724; }}
.margin-negative {{ color: #721c24; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 18px; font-weight: bold; color: #333; }}
</style>
</head>
<body>
<div class="container">
<div class="result-card {card_class}">
<div class="status">{recommendation}</div>
<div class="margin-display {margin_class}">{margin}</div>
<div class="reason">{reasoning}</div>
<div class="info-grid">
<div class="info-box">
<div class="info-label">Brand</div>
<div class="info-value">{tcgbrand}</div>
</div>
<div class="info-box">
<div class="info-label">Type</div>
<div class="info-value">{producttype}</div>
</div>
<div class="info-box">
<div class="info-label">Set</div>
<div class="info-value">{setname}</div>
</div>
<div class="info-box">
<div class="info-label">Market Price</div>
<div class="info-value">${marketprice}</div>
</div>
<div class="info-box">
<div class="info-label">Max Buy</div>
<div class="info-value">${maxBuy}</div>
</div>
<div class="info-box">
<div class="info-label">Fake Risk</div>
<div class="info-value">{fakerisk}</div>
</div>
</div>
</div>
</div>
</body>
</html>'''
    return html

def render_result_html(result: dict, category: str) -> str:
    """Route to the appropriate HTML renderer based on category"""
    if category == "gold":
        return render_gold_html(result)
    elif category == "silver":
        return render_silver_html(result)
    elif category == "lego":
        return render_lego_html(result)
    elif category == "tcg":
        return render_tcg_html(result)
    else:
        return render_gold_html(result)  # Default to gold format

# ============================================================
# DASHBOARD
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    status = "ENABLED" if ENABLED else "DISABLED"
    status_class = "enabled" if ENABLED else "disabled"
    button_text = "Turn OFF" if ENABLED else "Turn ON"
    debug_status = "ON" if DEBUG_MODE else "OFF"
    
    # Extract spot prices for display
    spot_gold_oz = SPOT_PRICES.get('gold_oz', 0)
    spot_silver_oz = SPOT_PRICES.get('silver_oz', 0)
    spot_10k = SPOT_PRICES.get('10K', 0)
    spot_14k = SPOT_PRICES.get('14K', 0)
    spot_18k = SPOT_PRICES.get('18K', 0)
    spot_sterling = SPOT_PRICES.get('sterling', 0)
    spot_source = SPOT_PRICES.get('source', 'default')
    spot_updated = SPOT_PRICES.get('last_updated', '')
    spot_updated_display = spot_updated[:19] if spot_updated else 'Using defaults'
    
    # Build recent listings HTML
    recent_html = ""
    sorted_listings = sorted(STATS["listings"].values(), key=lambda x: x["timestamp"], reverse=True)[:20]
    
    if sorted_listings:
        for listing in sorted_listings:
            rec = listing["recommendation"]
            rec_class = rec.lower()
            title = listing["title"][:60]
            reasoning = listing.get("reasoning_parts", {}).get("decision", listing.get("parsed_response", {}).get("reasoning", "")[:60])
            lid = listing["id"]
            flagged = "⚠️ " if listing.get("flagged") else ""
            
            recent_html += f'''
            <a href="/detail/{lid}" class="listing-item">
                <span class="listing-rec {rec_class}">{rec}</span>
                <span class="listing-title">{flagged}{title}</span>
                <span class="listing-reason">{reasoning[:50]}...</span>
                <span class="listing-arrow">→</span>
            </a>'''
    else:
        recent_html = '<div class="no-listings">No listings analyzed yet. Enable the proxy and click a listing in uBuyFirst.</div>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>uBuyFirst AI Analyzer</title>
        <meta http-equiv="refresh" content="5">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: #0f0f1a;
                min-height: 100vh;
                color: #e0e0e0;
            }}
            
            /* Header */
            .header {{
                background: linear-gradient(135deg, #1a1a2e 0%, #0f0f1a 100%);
                border-bottom: 1px solid rgba(255,255,255,0.1);
                padding: 20px 40px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .logo {{
                display: flex;
                align-items: center;
                gap: 12px;
            }}
            .logo-icon {{
                width: 40px;
                height: 40px;
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border-radius: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
            }}
            .logo-text {{
                font-size: 20px;
                font-weight: 700;
                color: #fff;
            }}
            .logo-text span {{
                background: linear-gradient(135deg, #6366f1, #a855f7);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            .header-links {{
                display: flex;
                gap: 20px;
            }}
            .header-link {{
                color: #888;
                text-decoration: none;
                font-size: 14px;
                font-weight: 500;
                padding: 8px 16px;
                border-radius: 8px;
                transition: all 0.2s;
            }}
            .header-link:hover {{
                color: #fff;
                background: rgba(255,255,255,0.1);
            }}
            
            /* Main Container */
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                padding: 30px 40px;
            }}
            
            /* Status Bar */
            .status-bar {{
                display: flex;
                gap: 16px;
                margin-bottom: 24px;
            }}
            .status-pill {{
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 10px 20px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 50px;
                font-size: 13px;
                font-weight: 500;
            }}
            .status-dot {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                animation: pulse 2s infinite;
            }}
            .status-dot.active {{ background: #22c55e; box-shadow: 0 0 10px #22c55e; }}
            .status-dot.inactive {{ background: #ef4444; animation: none; }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
            
            /* Spot Prices Section */
            .spot-section {{
                background: linear-gradient(135deg, rgba(34,197,94,0.1) 0%, rgba(16,185,129,0.05) 100%);
                border: 1px solid rgba(34,197,94,0.2);
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 24px;
            }}
            .spot-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }}
            .spot-title {{
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 16px;
                font-weight: 600;
                color: #22c55e;
            }}
            .spot-title svg {{
                width: 20px;
                height: 20px;
            }}
            .spot-refresh {{
                background: rgba(34,197,94,0.2);
                color: #22c55e;
                border: 1px solid rgba(34,197,94,0.3);
                padding: 8px 16px;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }}
            .spot-refresh:hover {{
                background: rgba(34,197,94,0.3);
            }}
            .spot-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
                gap: 16px;
            }}
            .spot-card {{
                background: rgba(0,0,0,0.3);
                border-radius: 12px;
                padding: 16px;
                text-align: center;
            }}
            .spot-card.main {{
                background: linear-gradient(135deg, rgba(34,197,94,0.2) 0%, rgba(16,185,129,0.1) 100%);
                border: 1px solid rgba(34,197,94,0.3);
            }}
            .spot-label {{
                font-size: 11px;
                font-weight: 600;
                color: #888;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 6px;
            }}
            .spot-value {{
                font-size: 22px;
                font-weight: 700;
                color: #22c55e;
            }}
            .spot-card:not(.main) .spot-value {{
                font-size: 18px;
                color: #10b981;
            }}
            .spot-meta {{
                font-size: 11px;
                color: #666;
                margin-top: 16px;
                text-align: right;
            }}
            
            /* Control Cards */
            .controls-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px;
                margin-bottom: 24px;
            }}
            .control-card {{
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 24px;
                transition: all 0.2s;
            }}
            .control-card:hover {{
                background: rgba(255,255,255,0.05);
                border-color: rgba(255,255,255,0.12);
            }}
            .control-label {{
                font-size: 12px;
                font-weight: 600;
                color: #666;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 12px;
            }}
            .control-value {{
                font-size: 28px;
                font-weight: 700;
                margin-bottom: 16px;
            }}
            .control-value.enabled {{ color: #22c55e; }}
            .control-value.disabled {{ color: #ef4444; }}
            .control-value.cost {{ color: #f59e0b; }}
            .control-value.info {{ color: #6366f1; }}
            .btn {{
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                border: none;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
            }}
            .btn-primary {{
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                color: white;
            }}
            .btn-primary:hover {{ opacity: 0.9; transform: translateY(-1px); }}
            .btn-secondary {{
                background: rgba(255,255,255,0.1);
                color: #fff;
                border: 1px solid rgba(255,255,255,0.2);
            }}
            .btn-secondary:hover {{ background: rgba(255,255,255,0.15); }}
            
            /* Stats Row */
            .stats-row {{
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 16px;
                margin-bottom: 24px;
            }}
            .stat-card {{
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 20px;
                text-align: center;
            }}
            .stat-value {{
                font-size: 32px;
                font-weight: 700;
                color: #fff;
            }}
            .stat-value.buy {{ color: #22c55e; }}
            .stat-value.pass {{ color: #ef4444; }}
            .stat-value.research {{ color: #f59e0b; }}
            .stat-value.api {{ color: #6366f1; }}
            .stat-label {{
                font-size: 11px;
                font-weight: 600;
                color: #666;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-top: 8px;
            }}
            
            /* Listings Section */
            .listings-section {{
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                overflow: hidden;
            }}
            .section-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 20px 24px;
                border-bottom: 1px solid rgba(255,255,255,0.08);
            }}
            .section-title {{
                font-size: 14px;
                font-weight: 600;
                color: #fff;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .section-title svg {{
                width: 18px;
                height: 18px;
                color: #6366f1;
            }}
            .export-link {{
                font-size: 12px;
                color: #6366f1;
                text-decoration: none;
                font-weight: 500;
            }}
            .export-link:hover {{ text-decoration: underline; }}
            
            .listing-item {{
                display: flex;
                align-items: center;
                padding: 16px 24px;
                gap: 16px;
                text-decoration: none;
                color: inherit;
                border-bottom: 1px solid rgba(255,255,255,0.05);
                transition: background 0.2s;
            }}
            .listing-item:hover {{ background: rgba(255,255,255,0.03); }}
            .listing-item:last-child {{ border-bottom: none; }}
            
            .listing-rec {{
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
                min-width: 80px;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .listing-rec.buy {{ 
                background: rgba(34,197,94,0.15); 
                color: #22c55e;
                border: 1px solid rgba(34,197,94,0.3);
            }}
            .listing-rec.pass {{ 
                background: rgba(239,68,68,0.15); 
                color: #ef4444;
                border: 1px solid rgba(239,68,68,0.3);
            }}
            .listing-rec.research {{ 
                background: rgba(245,158,11,0.15); 
                color: #f59e0b;
                border: 1px solid rgba(245,158,11,0.3);
            }}
            .listing-title {{
                flex: 1;
                font-size: 14px;
                color: #e0e0e0;
                font-weight: 500;
            }}
            .listing-reason {{
                font-size: 12px;
                color: #666;
                max-width: 300px;
            }}
            .listing-arrow {{
                color: #444;
                font-size: 18px;
            }}
            .no-listings {{
                padding: 60px;
                text-align: center;
                color: #666;
            }}
            .no-listings-icon {{
                font-size: 48px;
                margin-bottom: 16px;
            }}
            
            /* Footer */
            .footer {{
                text-align: center;
                padding: 30px;
                color: #444;
                font-size: 12px;
            }}
            
            /* Responsive */
            @media (max-width: 768px) {{
                .stats-row {{ grid-template-columns: repeat(3, 1fr); }}
                .header {{ padding: 15px 20px; }}
                .container {{ padding: 20px; }}
            }}
        </style>
    </head>
    <body>
        <header class="header">
            <div class="logo">
                <div class="logo-icon">⚡</div>
                <div class="logo-text"><span>uBuyFirst</span> AI Analyzer</div>
            </div>
            <div class="header-links">
                <a href="/analytics" class="header-link">📊 Analytics</a>
                <a href="/export" class="header-link">📥 Export</a>
            </div>
        </header>
        
        <div class="container">
            <!-- Status Pills -->
            <div class="status-bar">
                <div class="status-pill">
                    <div class="status-dot {'active' if ENABLED else 'inactive'}"></div>
                    <span>Proxy {'Active' if ENABLED else 'Inactive'}</span>
                </div>
                <div class="status-pill">
                    <span>Model: {MODEL.split('/')[-1]}</span>
                </div>
                <div class="status-pill">
                    <span>Session Cost: ${STATS["api_calls"] * COST_PER_CALL:.3f}</span>
                </div>
            </div>
            
            <!-- Spot Prices -->
            <div class="spot-section">
                <div class="spot-header">
                    <div class="spot-title">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        Live Metal Prices
                    </div>
                    <button class="spot-refresh" onclick="refreshSpot()">🔄 Refresh Prices</button>
                </div>
                <div class="spot-grid">
                    <div class="spot-card main">
                        <div class="spot-label">Gold Spot</div>
                        <div class="spot-value" id="gold-oz">${spot_gold_oz:.2f}</div>
                        <div class="spot-label" style="margin-top:4px; margin-bottom:0;">/troy oz</div>
                    </div>
                    <div class="spot-card main">
                        <div class="spot-label">Silver Spot</div>
                        <div class="spot-value" id="silver-oz">${spot_silver_oz:.2f}</div>
                        <div class="spot-label" style="margin-top:4px; margin-bottom:0;">/troy oz</div>
                    </div>
                    <div class="spot-card">
                        <div class="spot-label">10K Gold</div>
                        <div class="spot-value">${spot_10k:.2f}/g</div>
                    </div>
                    <div class="spot-card">
                        <div class="spot-label">14K Gold</div>
                        <div class="spot-value">${spot_14k:.2f}/g</div>
                    </div>
                    <div class="spot-card">
                        <div class="spot-label">18K Gold</div>
                        <div class="spot-value">${spot_18k:.2f}/g</div>
                    </div>
                    <div class="spot-card">
                        <div class="spot-label">Sterling</div>
                        <div class="spot-value">${spot_sterling:.2f}/g</div>
                    </div>
                </div>
                <div class="spot-meta">Source: {spot_source} • Last updated: {spot_updated_display}</div>
            </div>
            
            <script>
            async function refreshSpot(silent = false) {{
                const btn = document.querySelector('.spot-refresh');
                if (!silent) {{
                    btn.textContent = '⏳ Updating...';
                    btn.disabled = true;
                }}
                try {{
                    // If manual click (not silent), force refresh. If auto (silent), let server decide.
                    const url = silent ? '/api/refresh-spot' : '/api/refresh-spot?force=true';
                    const resp = await fetch(url);
                    const data = await resp.json();
                    if (data.success) {{
                        // Update all spot prices
                        document.getElementById('gold-oz').textContent = '$' + data.gold_oz.toFixed(2);
                        document.getElementById('silver-oz').textContent = '$' + data.silver_oz.toFixed(2);
                        
                        // Update karat rates if elements exist
                        const rates = {{
                            '10k': (data.gold_oz / 31.1035 * 0.417).toFixed(2),
                            '14k': (data.gold_oz / 31.1035 * 0.583).toFixed(2),
                            '18k': (data.gold_oz / 31.1035 * 0.750).toFixed(2),
                            'sterling': (data.silver_oz / 31.1035 * 0.925).toFixed(2)
                        }};
                        
                        // Update the karat display cards
                        document.querySelectorAll('.spot-card').forEach(card => {{
                            const label = card.querySelector('.spot-label')?.textContent?.toLowerCase() || '';
                            const valueEl = card.querySelector('.spot-value');
                            if (label.includes('10k') && valueEl) valueEl.textContent = '$' + rates['10k'] + '/g';
                            if (label.includes('14k') && valueEl) valueEl.textContent = '$' + rates['14k'] + '/g';
                            if (label.includes('18k') && valueEl) valueEl.textContent = '$' + rates['18k'] + '/g';
                            if (label.includes('sterling') && valueEl) valueEl.textContent = '$' + rates['sterling'] + '/g';
                        }});
                        
                        if (!silent) {{
                            btn.textContent = '✅ Updated!';
                            setTimeout(() => {{ btn.textContent = '🔄 Refresh Prices'; btn.disabled = false; }}, 2000);
                        }}
                    }} else if (!silent) {{
                        btn.textContent = '❌ Failed';
                        setTimeout(() => {{ btn.textContent = '🔄 Refresh Prices'; btn.disabled = false; }}, 2000);
                    }}
                }} catch(e) {{
                    if (!silent) {{
                        btn.textContent = '❌ Error';
                        setTimeout(() => {{ btn.textContent = '🔄 Refresh Prices'; btn.disabled = false; }}, 2000);
                    }}
                }}
            }}
            
            // Auto-refresh prices on page load (silently in background)
            document.addEventListener('DOMContentLoaded', () => {{
                // Small delay to let page render first, then fetch fresh prices
                setTimeout(() => refreshSpot(true), 500);
            }});
            </script>
            
            <!-- Control Cards -->
            <div class="controls-grid">
                <div class="control-card">
                    <div class="control-label">Proxy Status</div>
                    <div class="control-value {status_class}">{status}</div>
                    <form action="/toggle" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-primary">{button_text}</button>
                    </form>
                </div>
                <div class="control-card">
                    <div class="control-label">Debug Mode</div>
                    <div class="control-value" style="color: {'#22c55e' if DEBUG_MODE else '#666'};">{debug_status}</div>
                    <form action="/toggle-debug" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-secondary">Toggle Debug</button>
                    </form>
                </div>
                <div class="control-card">
                    <div class="control-label">Est. Session Cost</div>
                    <div class="control-value cost">${STATS["api_calls"] * COST_PER_CALL:.3f}</div>
                    <form action="/reset-stats" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-secondary">Reset Stats</button>
                    </form>
                </div>
                <div class="control-card">
                    <div class="control-label">Quick Actions</div>
                    <div class="control-value info">📊</div>
                    <a href="/analytics" class="btn btn-primary">View Analytics</a>
                </div>
            </div>
            
            <!-- Stats Row -->
            <div class="stats-row">
                <div class="stat-card">
                    <div class="stat-value">{STATS["total_requests"]}</div>
                    <div class="stat-label">Requests</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value api">{STATS["api_calls"]}</div>
                    <div class="stat-label">API Calls</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value buy">{STATS["buy_count"]}</div>
                    <div class="stat-label">Buy</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value pass">{STATS["pass_count"]}</div>
                    <div class="stat-label">Pass</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value research">{STATS["research_count"]}</div>
                    <div class="stat-label">Research</div>
                </div>
            </div>
            
            <!-- Listings Section -->
            <div class="listings-section">
                <div class="section-header">
                    <div class="section-title">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
                        Recent Listings
                    </div>
                    <a href="/export" class="export-link">Export JSON →</a>
                </div>
                {recent_html if recent_html and 'no-listings' not in recent_html else '<div class="no-listings"><div class="no-listings-icon">📦</div><div>No listings analyzed yet</div><div style="margin-top:8px;font-size:12px;">Enable the proxy and click a listing in uBuyFirst to get started</div></div>'}
            </div>
            
            <div class="footer">
                uBuyFirst AI Analyzer • Model: {MODEL} • Port: {PORT}
            </div>
        </div>
    </body>
    </html>
    """

# ============================================================
# DETAIL VIEW
# ============================================================

@app.get("/detail/{listing_id}", response_class=HTMLResponse)
async def listing_detail(listing_id: str):
    listing = STATS["listings"].get(listing_id)
    
    if not listing:
        return HTMLResponse(content="<h1>Listing not found</h1><a href='/'>Back to Dashboard</a>", status_code=404)
    
    rec = listing["recommendation"]
    rec_class = rec.lower()
    title = listing["title"]
    timestamp = listing["timestamp"]
    category = listing.get("category", "unknown")
    category_reasons = listing.get("category_reasons", [])
    
    # Input data formatted
    input_html = ""
    for key, value in listing.get("input_data", {}).items():
        if value:
            val_str = str(value)[:200]
            input_html += f'<div class="data-row"><span class="data-key">{key}</span><span class="data-value">{val_str}</span></div>'
    
    # Reasoning parts
    parts = listing.get("reasoning_parts", {})
    detection = parts.get("detection", "Not parsed")
    calc = parts.get("calc", "Not parsed")
    decision = parts.get("decision", "Not parsed")
    concerns = parts.get("concerns", "")
    raw_reasoning = parts.get("raw", "")
    
    # Parsed response
    parsed = listing.get("parsed_response", {})
    parsed_html = ""
    for key, value in parsed.items():
        if key != "reasoning":
            parsed_html += f'<div class="data-row"><span class="data-key">{key}</span><span class="data-value">{value}</span></div>'
    
    # Raw response
    raw_response = listing.get("raw_response", "No raw response captured")
    
    # Notes / flagged
    notes = listing.get("notes", "")
    flagged = listing.get("flagged", False)
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Listing Detail - {listing_id}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
                padding: 20px;
            }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            .back-link {{ color: #17a2b8; text-decoration: none; font-size: 14px; }}
            .back-link:hover {{ text-decoration: underline; }}
            
            .header {{ margin: 20px 0 30px; }}
            .header h1 {{ font-size: 20px; margin-bottom: 10px; }}
            .header .meta {{ color: #888; font-size: 12px; }}
            
            .rec-badge {{
                display: inline-block;
                padding: 8px 20px;
                border-radius: 6px;
                font-size: 18px;
                font-weight: bold;
                margin: 15px 0;
            }}
            .rec-badge.buy {{ background: #28a74533; color: #28a745; border: 2px solid #28a745; }}
            .rec-badge.pass {{ background: #dc354533; color: #dc3545; border: 2px solid #dc3545; }}
            .rec-badge.research {{ background: #ffc10733; color: #ffc107; border: 2px solid #ffc107; }}
            
            .section {{
                background: #1f1f3a;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
            }}
            .section-title {{
                font-size: 14px;
                color: #e94560;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 15px;
                padding-bottom: 10px;
                border-bottom: 1px solid #333;
            }}
            
            .reasoning-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
            @media (max-width: 768px) {{ .reasoning-grid {{ grid-template-columns: 1fr; }} }}
            
            .reasoning-box {{
                background: #2a2a4a;
                border-radius: 8px;
                padding: 15px;
            }}
            .reasoning-box.full {{ grid-column: 1 / -1; }}
            .reasoning-label {{
                font-size: 11px;
                color: #888;
                text-transform: uppercase;
                margin-bottom: 8px;
            }}
            .reasoning-value {{
                font-size: 14px;
                line-height: 1.6;
                color: #ddd;
            }}
            .reasoning-value.highlight {{ color: #28a745; font-weight: bold; }}
            .reasoning-value.calc {{ font-family: monospace; color: #17a2b8; }}
            
            .data-row {{
                display: flex;
                padding: 8px 0;
                border-bottom: 1px solid #2a2a4a;
            }}
            .data-row:last-child {{ border-bottom: none; }}
            .data-key {{
                color: #888;
                min-width: 140px;
                font-size: 12px;
            }}
            .data-value {{
                color: #ddd;
                font-size: 13px;
                word-break: break-word;
            }}
            
            .raw-response {{
                background: #0d0d1a;
                border-radius: 8px;
                padding: 15px;
                font-family: monospace;
                font-size: 12px;
                white-space: pre-wrap;
                word-break: break-all;
                color: #888;
                max-height: 200px;
                overflow-y: auto;
            }}
            
            .flag-badge {{
                background: #ffc107;
                color: #000;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            
            .actions {{
                display: flex;
                gap: 10px;
                margin-top: 20px;
            }}
            .action-btn {{
                padding: 10px 20px;
                border-radius: 6px;
                border: none;
                cursor: pointer;
                font-size: 13px;
            }}
            .action-btn.flag {{ background: #ffc107; color: #000; }}
            .action-btn.copy {{ background: #17a2b8; color: #fff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">← Back to Dashboard</a>
            
            <div class="header">
                <h1>{title}</h1>
                <div class="meta">
                    ID: {listing_id} | Category: {category.upper()} | {timestamp}
                    {' <span class="flag-badge">FLAGGED</span>' if flagged else ''}
                </div>
                <div class="rec-badge {rec_class}">{rec}</div>
            </div>
            
            <div class="section">
                <div class="section-title">🧠 AI Reasoning Breakdown</div>
                <div class="reasoning-grid">
                    <div class="reasoning-box">
                        <div class="reasoning-label">Detection (What AI Found)</div>
                        <div class="reasoning-value">{detection or 'Not structured'}</div>
                    </div>
                    <div class="reasoning-box">
                        <div class="reasoning-label">Calculation</div>
                        <div class="reasoning-value calc">{calc or 'Not structured'}</div>
                    </div>
                    <div class="reasoning-box full">
                        <div class="reasoning-label">Decision Rationale</div>
                        <div class="reasoning-value highlight">{decision or concerns or 'Not structured'}</div>
                    </div>
                    <div class="reasoning-box full">
                        <div class="reasoning-label">Full Reasoning (Raw)</div>
                        <div class="reasoning-value">{raw_reasoning}</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📊 Parsed Response Values</div>
                {parsed_html or '<div class="data-row"><span class="data-value">No parsed data</span></div>'}
            </div>
            
            <div class="section">
                <div class="section-title">🔍 Category Detection</div>
                <div class="data-row">
                    <span class="data-key">Detected Category</span>
                    <span class="data-value">{category.upper()}</span>
                </div>
                <div class="data-row">
                    <span class="data-key">Reasons</span>
                    <span class="data-value">{' | '.join(category_reasons) if category_reasons else 'Default'}</span>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📥 Input Data Received</div>
                {input_html or '<div class="data-row"><span class="data-value">No input data</span></div>'}
            </div>
            
            <div class="section">
                <div class="section-title">🔧 Raw AI Response (Debug)</div>
                <div class="raw-response">{raw_response}</div>
            </div>
            
            {f'<div class="section"><div class="section-title">📝 Notes</div><div class="reasoning-value">{notes}</div></div>' if notes else ''}
            
            <div class="actions">
                <form action="/flag/{listing_id}" method="post">
                    <button type="submit" class="action-btn flag">{'Unflag' if flagged else 'Flag for Review'}</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

# ============================================================
# UTILITY ENDPOINTS
# ============================================================

@app.post("/toggle")
async def toggle():
    global ENABLED
    ENABLED = not ENABLED
    return RedirectResponse(url="/", status_code=303)

@app.post("/toggle-debug")
async def toggle_debug():
    global DEBUG_MODE
    DEBUG_MODE = not DEBUG_MODE
    return RedirectResponse(url="/", status_code=303)

@app.post("/reset-stats")
async def reset_stats():
    global STATS
    STATS = {
        "total_requests": 0, "api_calls": 0, "skipped": 0,
        "buy_count": 0, "pass_count": 0, "research_count": 0,
        "listings": {}
    }
    return RedirectResponse(url="/", status_code=303)

@app.post("/flag/{listing_id}")
async def flag_listing(listing_id: str):
    if listing_id in STATS["listings"]:
        STATS["listings"][listing_id]["flagged"] = not STATS["listings"][listing_id].get("flagged", False)
    return RedirectResponse(url=f"/detail/{listing_id}", status_code=303)

@app.get("/export")
async def export_data():
    return Response(
        content=json.dumps(STATS, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=proxy_data.json"}
    )

@app.get("/health")
async def health():
    return {"status": "ok", "enabled": ENABLED, "debug": DEBUG_MODE}

@app.get("/db-test")
async def db_test():
    """Debug endpoint to check database status"""
    result = {
        "db_path": str(DB_PATH),
        "file_exists": DB_PATH.exists(),
        "listings_count": 0,
        "daily_stats_count": 0,
        "recent_listings": [],
        "error": None
    }
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM listings')
        result["listings_count"] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM daily_stats')
        result["daily_stats_count"] = c.fetchone()[0]
        
        c.execute('SELECT id, title, recommendation, timestamp FROM listings ORDER BY timestamp DESC LIMIT 5')
        result["recent_listings"] = [{"id": r[0], "title": r[1], "rec": r[2], "time": r[3]} for r in c.fetchall()]
        
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    
    return result

# ============================================================
# ANALYTICS ENDPOINTS
# ============================================================

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_dashboard():
    """Display comprehensive analytics dashboard"""
    print("\n" + "="*60)
    print("[ANALYTICS PAGE] Loading analytics dashboard...")
    print("="*60)
    
    analytics = get_analytics()
    
    # Extract spot prices for use in f-string
    spot_gold_oz = SPOT_PRICES.get('gold_oz', 0)
    spot_silver_oz = SPOT_PRICES.get('silver_oz', 0)
    spot_10k = SPOT_PRICES.get('10K', 0)
    spot_14k = SPOT_PRICES.get('14K', 0)
    spot_18k = SPOT_PRICES.get('18K', 0)
    spot_sterling = SPOT_PRICES.get('sterling', 0)
    spot_source = SPOT_PRICES.get('source', 'default')
    spot_updated = SPOT_PRICES.get('last_updated', '')
    spot_updated_display = spot_updated[:19] if spot_updated else 'Using defaults'
    
    print(f"[ANALYTICS PAGE] Spot prices: Gold ${spot_gold_oz:.2f}/oz, Silver ${spot_silver_oz:.2f}/oz")
    
    print(f"[ANALYTICS PAGE] Got analytics data:")
    print(f"  - total_listings: {analytics.get('total_listings', 'MISSING')}")
    print(f"  - total_buys: {analytics.get('total_buys', 'MISSING')}")
    print(f"  - by_category count: {len(analytics.get('by_category', []))}")
    print(f"  - recent count: {len(analytics.get('recent', []))}")
    
    # Build category breakdown HTML
    category_rows = ""
    for cat in analytics.get('by_category', []):
        category_rows += f"""
        <tr>
            <td>{cat.get('category', 'Unknown')}</td>
            <td>{cat.get('count', 0)}</td>
            <td>{cat.get('buys', 0)}</td>
            <td>{round(cat.get('buys', 0) / max(cat.get('count', 1), 1) * 100, 1)}%</td>
        </tr>
        """
    
    # Build daily trend rows
    daily_rows = ""
    for day in analytics.get('daily_trend', []):
        daily_rows += f"""
        <tr>
            <td>{day.get('date', '')}</td>
            <td>{day.get('total_analyzed', 0)}</td>
            <td style="color: green;">{day.get('buy_count', 0)}</td>
            <td style="color: red;">{day.get('pass_count', 0)}</td>
            <td>${day.get('total_profit', 0):.2f}</td>
            <td>${day.get('api_cost', 0):.4f}</td>
        </tr>
        """
    
    # Build recent listings rows
    recent_rows = ""
    for listing in analytics.get('recent', [])[:15]:
        rec = listing.get('recommendation', 'RESEARCH')
        color = '#28a745' if rec == 'BUY' else '#dc3545' if rec == 'PASS' else '#ffc107'
        recent_rows += f"""
        <tr>
            <td><a href="/detail/{listing.get('id', '')}">{listing.get('title', 'No title')[:50]}...</a></td>
            <td>{listing.get('category', '')}</td>
            <td style="color: {color}; font-weight: bold;">{rec}</td>
            <td>{listing.get('margin', 'NA')}</td>
        </tr>
        """
    
    # Build top wins rows
    wins_rows = ""
    for win in analytics.get('top_wins', []):
        wins_rows += f"""
        <tr>
            <td>{win.get('title', '')[:40]}...</td>
            <td>{win.get('category', '')}</td>
            <td>${win.get('actual_paid', 0):.2f}</td>
            <td style="color: green; font-weight: bold;">+${win.get('profit_loss', 0):.2f}</td>
        </tr>
        """
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Analytics Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        h1, h2 {{ color: #00d9ff; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: #16213e; padding: 20px; border-radius: 10px; text-align: center; }}
        .stat-value {{ font-size: 36px; font-weight: bold; color: #00d9ff; }}
        .stat-label {{ color: #888; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; background: #16213e; border-radius: 10px; overflow: hidden; }}
        th {{ background: #0f3460; color: #00d9ff; padding: 12px; text-align: left; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #0f3460; }}
        tr:hover {{ background: #1a1a4e; }}
        a {{ color: #00d9ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .back-link {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #0f3460; border-radius: 5px; }}
        .section {{ margin-bottom: 40px; }}
        .spot-banner {{ background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); padding: 20px; border-radius: 10px; margin-bottom: 30px; }}
        .spot-title {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .spot-title h2 {{ margin: 0; color: #ffd700; }}
        .refresh-btn {{ background: #ffd700; color: #1a472a; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; font-weight: bold; }}
        .refresh-btn:hover {{ background: #ffed4a; }}
        .spot-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }}
        .spot-item {{ background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; text-align: center; }}
        .spot-metal {{ font-size: 14px; color: #aaa; }}
        .spot-price {{ font-size: 24px; font-weight: bold; color: #ffd700; }}
        .spot-rate {{ font-size: 12px; color: #888; margin-top: 5px; }}
        .spot-updated {{ text-align: right; font-size: 11px; color: #666; margin-top: 10px; }}
    </style>
</head>
<body>
    <a href="/" class="back-link">← Back to Dashboard</a>
    <h1>📊 Analytics Dashboard</h1>
    
    <!-- Spot Price Banner -->
    <div class="spot-banner">
        <div class="spot-title">
            <h2>💰 Live Spot Prices</h2>
            <button class="refresh-btn" onclick="refreshSpot()">🔄 Refresh Prices</button>
        </div>
        <div class="spot-grid">
            <div class="spot-item">
                <div class="spot-metal">GOLD</div>
                <div class="spot-price" id="gold-price">${spot_gold_oz:.2f}</div>
                <div class="spot-rate">per troy oz</div>
            </div>
            <div class="spot-item">
                <div class="spot-metal">SILVER</div>
                <div class="spot-price" id="silver-price">${spot_silver_oz:.2f}</div>
                <div class="spot-rate">per troy oz</div>
            </div>
            <div class="spot-item">
                <div class="spot-metal">10K Gold</div>
                <div class="spot-price" style="font-size: 18px;">${spot_10k:.2f}/g</div>
            </div>
            <div class="spot-item">
                <div class="spot-metal">14K Gold</div>
                <div class="spot-price" style="font-size: 18px;">${spot_14k:.2f}/g</div>
            </div>
            <div class="spot-item">
                <div class="spot-metal">18K Gold</div>
                <div class="spot-price" style="font-size: 18px;">${spot_18k:.2f}/g</div>
            </div>
            <div class="spot-item">
                <div class="spot-metal">Sterling</div>
                <div class="spot-price" style="font-size: 18px;">${spot_sterling:.2f}/g</div>
            </div>
        </div>
        <div class="spot-updated">
            Source: {spot_source} | Updated: {spot_updated_display}
        </div>
    </div>
    
    <script>
    async function refreshSpot(silent = false) {{
        const btn = document.querySelector('.refresh-btn');
        if (!silent) {{
            btn.textContent = '⏳ Updating...';
            btn.disabled = true;
        }}
        try {{
            const url = silent ? '/api/refresh-spot' : '/api/refresh-spot?force=true';
            const resp = await fetch(url);
            const data = await resp.json();
            if (data.success) {{
                document.getElementById('gold-price').textContent = '$' + data.gold_oz.toFixed(2);
                document.getElementById('silver-price').textContent = '$' + data.silver_oz.toFixed(2);
                if (!silent) {{
                    btn.textContent = '✓ Updated!';
                    setTimeout(() => location.reload(), 1000);
                }}
            }} else if (!silent) {{
                btn.textContent = '❌ Failed';
            }}
        }} catch(e) {{
            if (!silent) btn.textContent = '❌ Error';
        }}
        if (!silent) setTimeout(() => {{ btn.textContent = '🔄 Refresh Prices'; btn.disabled = false; }}, 3000);
    }}
    
    // Auto-refresh on page load
    document.addEventListener('DOMContentLoaded', () => setTimeout(() => refreshSpot(true), 500));
    </script>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{analytics.get('total_listings', 0)}</div>
            <div class="stat-label">Total Analyzed</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #28a745;">{analytics.get('total_buys', 0)}</div>
            <div class="stat-label">BUY Recommendations</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #dc3545;">{analytics.get('total_passes', 0)}</div>
            <div class="stat-label">PASS Recommendations</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{analytics.get('actual_purchases', 0)}</div>
            <div class="stat-label">Actual Purchases</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #28a745;">${analytics.get('total_profit', 0):.2f}</div>
            <div class="stat-label">Total Profit</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{analytics.get('ai_accuracy', 'N/A')}{'%' if isinstance(analytics.get('ai_accuracy'), (int, float)) else ''}</div>
            <div class="stat-label">AI Accuracy</div>
        </div>
    </div>
    
    <div class="section">
        <h2>📅 Daily Trend (Last 7 Days)</h2>
        <table>
            <tr>
                <th>Date</th>
                <th>Analyzed</th>
                <th>BUYs</th>
                <th>PASSes</th>
                <th>Profit</th>
                <th>API Cost</th>
            </tr>
            {daily_rows if daily_rows else '<tr><td colspan="6">No data yet</td></tr>'}
        </table>
    </div>
    
    <div class="section">
        <h2>📁 By Category</h2>
        <table>
            <tr>
                <th>Category</th>
                <th>Total</th>
                <th>BUYs</th>
                <th>BUY Rate</th>
            </tr>
            {category_rows if category_rows else '<tr><td colspan="4">No data yet</td></tr>'}
        </table>
    </div>
    
    <div class="section">
        <h2>🏆 Top Wins</h2>
        <table>
            <tr>
                <th>Title</th>
                <th>Category</th>
                <th>Paid</th>
                <th>Profit</th>
            </tr>
            {wins_rows if wins_rows else '<tr><td colspan="4">No outcomes recorded yet</td></tr>'}
        </table>
    </div>
    
    <div class="section">
        <h2>🕐 Recent Listings</h2>
        <table>
            <tr>
                <th>Title</th>
                <th>Category</th>
                <th>Recommendation</th>
                <th>Margin</th>
            </tr>
            {recent_rows if recent_rows else '<tr><td colspan="4">No listings yet</td></tr>'}
        </table>
    </div>
    
    <div class="section">
        <h2>📤 Export Data</h2>
        <p><a href="/export-db" class="back-link">Download Full Database (CSV)</a></p>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html)

@app.get("/export-db")
async def export_database():
    """Export full database as CSV"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute('SELECT * FROM listings ORDER BY timestamp DESC')
        rows = c.fetchall()
        columns = [description[0] for description in c.description]
        conn.close()
        
        # Build CSV
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=arbitrage_data_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    except Exception as e:
        return {"error": str(e)}

@app.post("/outcome/{listing_id}")
async def record_listing_outcome(listing_id: str, request: Request):
    """Record what actually happened with a listing"""
    try:
        data = await request.json()
        user_did = data.get('action')  # BOUGHT, PASSED, SKIPPED
        actual_paid = data.get('paid')
        sold_price = data.get('sold')
        notes = data.get('notes')
        
        success = record_outcome(listing_id, user_did, actual_paid, sold_price, notes)
        return {"success": success, "listing_id": listing_id}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/analytics")
async def api_analytics():
    """Return analytics as JSON for programmatic access"""
    return get_analytics()

@app.get("/api/listings")
async def api_listings(limit: int = 100, category: str = None, recommendation: str = None):
    """Query listings with filters"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        query = "SELECT * FROM listings WHERE 1=1"
        params = []
        
        if category:
            query += " AND category = ?"
            params.append(category)
        if recommendation:
            query += " AND recommendation = ?"
            params.append(recommendation)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        c.execute(query, params)
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return {"listings": rows, "count": len(rows)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/spot-prices")
async def api_spot_prices():
    """Return current spot prices"""
    return {
        "gold_oz": SPOT_PRICES.get("gold_oz", 0),
        "silver_oz": SPOT_PRICES.get("silver_oz", 0),
        "gold_gram": SPOT_PRICES.get("gold_gram", 0),
        "silver_gram": SPOT_PRICES.get("silver_gram", 0),
        "10K": SPOT_PRICES.get("10K", 0),
        "14K": SPOT_PRICES.get("14K", 0),
        "18K": SPOT_PRICES.get("18K", 0),
        "22K": SPOT_PRICES.get("22K", 0),
        "24K": SPOT_PRICES.get("24K", 0),
        "sterling": SPOT_PRICES.get("sterling", 0),
        "source": SPOT_PRICES.get("source", "default"),
        "last_updated": SPOT_PRICES.get("last_updated")
    }

@app.get("/api/refresh-spot")
async def refresh_spot_prices(force: bool = False):
    """Refresh spot prices - only fetches from Yahoo if stale (>1 hour) unless forced"""
    last_updated = SPOT_PRICES.get("last_updated")
    
    # Check if prices are stale (over 1 hour old)
    is_stale = True
    if last_updated and not force:
        try:
            last_time = datetime.fromisoformat(last_updated)
            age_minutes = (datetime.now() - last_time).total_seconds() / 60
            is_stale = age_minutes > 60  # More than 1 hour old
            if not is_stale:
                print(f"[SPOT] Prices are fresh ({age_minutes:.1f} min old), skipping fetch")
        except:
            is_stale = True
    
    success = True
    if is_stale or force:
        print(f"\n[API] Fetching fresh spot prices (force={force}, stale={is_stale})...")
        success = fetch_spot_prices()
    
    return {
        "success": success,
        "gold_oz": SPOT_PRICES.get("gold_oz", 0),
        "silver_oz": SPOT_PRICES.get("silver_oz", 0),
        "source": SPOT_PRICES.get("source", "default"),
        "last_updated": SPOT_PRICES.get("last_updated"),
        "was_stale": is_stale
    }

# OpenAI-compatible endpoints (unchanged from v1)
@app.get("/v1/models")
async def list_models():
    return Response(content=json.dumps({
        "object": "list",
        "data": [{"id": "gpt-4o", "object": "model", "owned_by": "openai"}]
    }), media_type="application/json")

@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    """
    OpenAI-compatible endpoint - DISABLED to prevent double API calls.
    Analysis happens via match_mydata which shows in the template.
    This just returns a placeholder for the AI columns.
    """
    print("=" * 60)
    print("[/v1/chat/completions] SKIPPED - Using match_mydata instead")
    print("[/v1/chat/completions] (Prevents double API charges)")
    print("=" * 60)
    
    # Return minimal response for AI columns - real analysis is in template
    placeholder_json = json.dumps({
        "Qualify": "Yes",
        "Recommendation": "SEE TEMPLATE",
        "reasoning": "Analysis shown in template panel - API call skipped to prevent double charges",
        "verified": "See Template",
        "karat": "See Template",
        "itemtype": "See Template", 
        "weight": "See Template",
        "meltvalue": "See Template",
        "maxBuy": "See Template",
        "Margin": "See Template",
        "pricepergram": "NA",
        "fakerisk": "NA",
        "confidence": "See Template"
    }, separators=(',', ':'))
    
    return Response(content=json.dumps({
        "id": "chatcmpl-proxy-skip",
        "object": "chat.completion",
        "created": 0,
        "model": "claude-proxy-skip",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": placeholder_json},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }), media_type="application/json")
if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║         Claude Proxy v2 - Reasoning Dashboard                     ║
╠══════════════════════════════════════════════════════════════════╣
║  Dashboard: http://{HOST}:{PORT}                                    ║
║  Analytics: http://{HOST}:{PORT}/analytics                          ║
║  Endpoint:  http://{HOST}:{PORT}/match_mydata                       ║
║  Model:     {MODEL}                              ║
║                                                                  ║
║  NEW IN V2:                                                      ║
║  • Live spot prices (auto-updates every 12 hours)               ║
║  • Click-through detail view for each listing                    ║
║  • Structured reasoning: DETECTION | CALC | DECISION             ║
║  • Best Offer suggestions for overpriced listings                ║
║  • Full input data display                                       ║
║  • Export all data as JSON                                       ║
║                                                                  ║
║  Starts DISABLED (no API costs until you turn it on)             ║
║  Press Ctrl+C to stop                                            ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    # Fetch spot prices on startup
    print("\n" + "=" * 60)
    print("INITIALIZING SPOT PRICES...")
    print("=" * 60)
    fetch_spot_prices()
    
    # Start background updater (every 12 hours)
    start_spot_price_updater()
    
    print("\n" + "=" * 60)
    print("SERVER STARTING...")
    print("=" * 60 + "\n")
    
    uvicorn.run(app, host=HOST, port=PORT)
