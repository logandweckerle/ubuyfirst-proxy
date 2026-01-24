"""
eBay Race Routes - Race comparison endpoints (uBuyFirst vs Direct API)
Extracted from main.py for modularity

This module contains:
- /ebay/race/* endpoints for speed comparison testing
- /api/source-comparison/* endpoints for statistics
- Auto, Gold, Full race dashboards
- Race state variables and helper functions
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from urllib.parse import unquote_plus

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

# Create router for eBay race endpoints
router = APIRouter(tags=["ebay-race"])

# ============================================================
# MODULE-LEVEL STATE
# ============================================================

# Race tracking state
RACE_ITEMS: Dict = {}  # item_id -> {"ubuyfirst_time": datetime, "api_time": datetime, "title": str, "price": float}
RACE_RUNNING = False
RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
RACE_LOG: List = []  # List of comparison results
RACE_FEED_UBUYFIRST: List = []  # Last 30 items from uBuyFirst
RACE_FEED_API: List = []  # Last 30 items from API
RACE_DETECTED_ITEMS: Dict = {}
RACE_SEEN_IDS: set = set()  # Items seen before race started
RACE_KEYWORD_INDEX = 0

# uBuyFirst Search Presets (from KeywordsExport.csv)
UBUYFIRST_PRESETS = {
    "new_gold_search": {
        "name": "New Gold Search",
        "keywords": "14k grams,14kt grams,14k gram,14kt gram,14k scrap,14kt scrap,14k bracelet,14kt bracelet,14k lot,18k grams,18kt grams,18k gram,18k bracelet,18kt bracelet,14k ring,14k chain,14k necklace,14k watch,14k vintage,14k diamond,14k charm,585 grams,585 gram,585 scrap,750 grams,750 bracelet",
        "category_id": "162134",  # Scrap Gold (Browse API only allows 1)
        "price_min": 100,
        "price_max": 10000,
    },
    "new_gold_search_2": {
        "name": "New Gold Search 2",
        "keywords": "14k grams,14kt grams,14k gram,14kt gram,14k scrap,14kt scrap,14k bracelet,14kt bracelet,14k lot,18k grams,18kt grams,18k gram,18k bracelet,18kt bracelet,14k ring,14k chain,14k necklace,14k watch,14k vintage,14k diamond,14k charm,585 grams,585 gram,585 scrap,750 grams,750 bracelet",
        "category_id": "281",  # Jewelry (Browse API only allows 1)
        "price_min": 100,
        "price_max": 10000,
    },
    "new_silver_search": {
        "name": "New Silver Search",
        "keywords": "sterling scrap,sterling lot,sterling flatware,sterling grams,925 scrap,925 grams,sterling gorham,sterling towle,sterling bowl,sterling tea,800 silver,800 grams,800 scrap,830 silver,900 silver,900 grams,coin silver,mexican silver,sanborn",
        "category_id": "20096",  # Sterling Silver
        "price_min": 50,
        "price_max": 10000,
    },
    "new_silver_search_2": {
        "name": "New Silver Search 2",
        "keywords": "sterling scrap,sterling lot,sterling flatware,sterling grams,925 scrap,925 grams,sterling gorham,sterling towle,sterling bowl,sterling tea,800 silver,800 grams,800 scrap,830 silver,900 silver,900 grams,coin silver,mexican silver,sanborn",
        "category_id": "281",  # Jewelry
        "price_min": 50,
        "price_max": 10000,
    },
    "new_silver_search_3": {
        "name": "New Silver Search 3 (Native)",
        "keywords": "navajo sterling,native sterling,sterling turquoise,squash blossom,concho,old pawn,dead pawn,zuni,hopi,taxco,pueblo,southwestern sterling,native lot,navajo lot,925 turquoise,sterling coral,sterling jade",
        "category_id": "262025",  # Ethnic/Regional Jewelry
        "price_min": 50,
        "price_max": 10000,
    },
    "watch_search": {
        "name": "Watch Search",
        "keywords": "omega,hamilton,rolex,breitling,tag heuer,seiko,bulova,longines,tissot,cartier,patek,gruen,zodiac,elgin,waltham,wittnauer,benrus,tudor,heuer,girard,movado,citizen",
        "category_id": "14324",  # Wristwatches
        "price_min": 50,
        "price_max": 10000,
    },
    "coral_amber": {
        "name": "Coral & Amber",
        "keywords": "amber grams,baltic amber,butterscotch amber,cherry amber,egg yolk amber,natural amber,amber beads,amber necklace,amber lot,cherry red beaded,natural coral,undyed coral,no dye coral,mediterranean coral,red coral,salmon coral,momo coral,oxblood coral,angel skin coral,coral grams,coral beads,coral necklace,coral lot",
        "category_id": "281",  # Jewelry
        "price_min": 50,
        "price_max": 10000,
    },
    "costume": {
        "name": "Costume Jewelry",
        "keywords": "trifari,costume lot,jewelry lot,cameo lot,bakelite",
        "category_id": "10968",  # Costume Jewelry
        "price_min": 10,
        "price_max": 10000,
    },
    "sealed_tcg": {
        "name": "Sealed TCG",
        "keywords": "booster box,elite trainer box,etb sealed,booster case,sealed case,booster box lot,pokemon sealed lot,mtg sealed lot,tcg lot sealed,japanese booster box,premium collection box,collection box sealed,build battle stadium,ultra premium collection,one piece booster box",
        "category_id": "183454",  # Pokemon Sealed Products
        "price_min": 50,
        "price_max": 10000,
    },
    "lego": {
        "name": "Lego (New)",
        "keywords": "",  # Category-based search
        "category_id": "19006",  # Lego Complete Sets
        "price_min": 50,
        "price_max": 10000,
    },
    "video_games": {
        "name": "Video Games CIB",
        "keywords": "snes cib,super nintendo lot,snes complete,n64 cib,nintendo 64 lot,n64 complete box,nes cib,nes complete,nintendo nes lot,gamecube cib,gcn complete,gamecube lot,genesis cib,3ds complete,sega genesis lot,genesis complete,nintendo ds lot,gba cib,gameboy advance lot,gba complete,ds cib",
        "category_id": "139973",  # Video Game Complete
        "price_min": 20,
        "price_max": 10000,
    },
}

# Gold Search Keywords (all 26 from uBuyFirst "New Gold Search")
GOLD_SEARCH_KEYWORDS = [
    "14k grams", "14kt grams", "14k gram", "14kt gram",
    "14k scrap", "14kt scrap", "14k bracelet", "14kt bracelet",
    "14k lot", "18k grams", "18kt grams", "18k gram",
    "18k bracelet", "18kt bracelet", "14k ring", "14k chain",
    "14k necklace", "14k watch", "14k vintage", "14k diamond",
    "14k charm", "585 grams", "585 gram", "585 scrap",
    "750 grams", "750 bracelet",
]

# Both categories from uBuyFirst: Fine Jewelry (3360) and Scrap Gold (162134)
GOLD_SEARCH_CATEGORIES = ["3360", "162134"]

# Title keywords to EXCLUDE (from uBuyFirst FiltersExport)
BLOCKED_TITLE_KEYWORDS = [
    "plated", "plate", "tone", "over", "filled", "electroplate", "epns", "rogers",
    "silverplate", "silverplated", "silver plated", "clad", "alpaca", "nickel silver",
    "copper", "cz", "cubic zirconia", "leather", "plastic", "titanium", "tungsten",
    "premier designs", "fossil", "kendra scott", "anthropologie", "stretch", "brighton",
    "elastic", "boho", "betsey johnson", "raymond weil", "battery", "avon", "tory burch",
    "sheffield", "quartz", "joan rivers", "sarah coventry", "citizen", "invicta", "faux",
    "sexy", "moissanite", "acrylic", "rgp", "bamboo coral", "sponge coral", "14k gp",
    "cartier love", "gld", "lab grown", "lab-grown", "igi", "finish"
]

# ALL enabled uBuyFirst searches - comprehensive race configuration
ALL_SEARCHES = [
    {"name": "Sterling scrap", "keywords": ["sterling", "sterling silver", "solid silver", "925", "925 silver", "scrap silver", "sterling lot", "sterling scrap", "junk silver", "sterling flatware"], "categories": ["20081", "1", "281"], "price_min": 1, "price_max": 10000},
    {"name": "Lego", "keywords": [], "categories": ["19006"], "price_min": 50, "price_max": 10000},
    {"name": "Sealed TCG", "keywords": ["booster box", "elite trainer box", "etb sealed", "booster case", "sealed case", "pokemon sealed lot", "mtg sealed lot"], "categories": ["183454", "183453", "183456", "183452", "2536"], "price_min": 50, "price_max": 10000},
    {"name": "New Silver Search", "keywords": ["sterling scrap", "sterling lot", "sterling flatware", "sterling grams", "925 scrap", "925 grams", "sterling gorham", "sterling towle", "800 silver", "coin silver"], "categories": ["20096", "262022"], "price_min": 50, "price_max": 10000},
    {"name": "New Gold Search", "keywords": ["14k grams", "14kt grams", "14k gram", "14k scrap", "14k bracelet", "14k lot", "18k grams", "14k ring", "14k chain", "14k necklace", "585 grams", "750 grams"], "categories": ["3360", "162134"], "price_min": 100, "price_max": 10000},
    {"name": "Watch Search", "keywords": ["omega", "hamilton", "rolex", "breitling", "tag heuer", "seiko", "bulova", "longines", "pocket watch"], "categories": ["14324", "10290", "262022", "31387", "57717"], "price_min": 50, "price_max": 10000},
    {"name": "Costume", "keywords": ["trifari", "costume lot", "jewelry lot", "cameo lot", "bakelite"], "categories": ["10968"], "price_min": 10, "price_max": 10000},
    {"name": "New Gold Search 2", "keywords": ["14k grams", "14k scrap", "14k bracelet", "18k grams", "14k ring", "14k chain", "585 grams"], "categories": ["281", "262022", "10290"], "price_min": 100, "price_max": 10000},
    {"name": "New Silver Search 2", "keywords": ["sterling scrap", "sterling lot", "sterling flatware", "925 scrap", "coin silver", "mexican silver"], "categories": ["281", "2213", "39487"], "price_min": 50, "price_max": 10000},
    {"name": "New Silver Search 3", "keywords": ["navajo sterling", "native sterling", "sterling turquoise", "squash blossom", "concho", "old pawn", "zuni", "taxco"], "categories": ["262025", "110633", "20082"], "price_min": 50, "price_max": 10000},
    {"name": "Coral & Amber", "keywords": ["amber grams", "baltic amber", "butterscotch amber", "natural coral", "red coral", "salmon coral", "coral beads"], "categories": ["281", "262025", "20082"], "price_min": 50, "price_max": 10000},
    {"name": "VideoGames", "keywords": ["snes cib", "super nintendo lot", "n64 cib", "gamecube cib", "gamecube lot", "genesis cib", "gba cib"], "categories": ["139973", "139971", "54968"], "price_min": 20, "price_max": 10000},
]

FULL_RACE_INDEX = 0  # Current search index for round-robin polling

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_ebay_race)
# ============================================================

_search_ebay = None
_EBAY_POLLER_AVAILABLE = False
_EBAY_SEARCH_CONFIGS = None
_get_comparison_stats = None
_get_race_log = None
_reset_source_stats = None


def configure_ebay_race(
    search_ebay: Callable,
    EBAY_POLLER_AVAILABLE: bool,
    EBAY_SEARCH_CONFIGS: Dict,
    get_comparison_stats: Callable,
    get_race_log: Callable,
    reset_source_stats: Callable,
):
    """Configure the eBay race module with all required dependencies."""
    global _search_ebay, _EBAY_POLLER_AVAILABLE, _EBAY_SEARCH_CONFIGS
    global _get_comparison_stats, _get_race_log, _reset_source_stats

    _search_ebay = search_ebay
    _EBAY_POLLER_AVAILABLE = EBAY_POLLER_AVAILABLE
    _EBAY_SEARCH_CONFIGS = EBAY_SEARCH_CONFIGS
    _get_comparison_stats = get_comparison_stats
    _get_race_log = get_race_log
    _reset_source_stats = reset_source_stats

    logger.info("[EBAY RACE ROUTES] Module configured")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_title(title: str) -> str:
    """Normalize title for fuzzy matching - handles URL encoding from uBuyFirst"""
    # Decode URL encoding (uBuyFirst sends URL-encoded titles)
    t = unquote_plus(title)

    # Remove special chars, lowercase, remove extra spaces
    t = re.sub(r'[^a-zA-Z0-9\s]', '', t.lower())
    t = ' '.join(t.split())  # Normalize whitespace

    # Extract key identifying words (first 8 significant words)
    words = [w for w in t.split() if len(w) > 2][:8]
    return ' '.join(words)


def passes_title_filter(title: str) -> bool:
    """Check if title passes the blocked keywords filter"""
    title_lower = title.lower()
    for keyword in BLOCKED_TITLE_KEYWORDS:
        if keyword in title_lower:
            return False
    return True


def log_race_item(item_id: str, source: str, title: str, price: float, category: str = ""):
    """Log an item detection from either source"""
    global RACE_STATS, RACE_LOG, RACE_ITEMS, RACE_FEED_UBUYFIRST, RACE_FEED_API

    now = datetime.now()

    # Create normalized key for matching (title + approximate price)
    norm_title = normalize_title(title)
    # Use larger price buckets ($25) and also create adjacent buckets for fuzzy matching
    price_bucket = int(price / 25) * 25
    match_key = f"{norm_title}_{price_bucket}"
    # Also create keys for adjacent buckets (handles edge cases like $99 vs $101)
    match_key_lower = f"{norm_title}_{price_bucket - 25}"
    match_key_upper = f"{norm_title}_{price_bucket + 25}"

    # Add to live feed for side-by-side view
    feed_entry = {
        "item_id": item_id,
        "title": title[:60],
        "price": price,
        "category": category,
        "time": now.strftime("%H:%M:%S"),
        "timestamp": now.timestamp(),
        "match_key": match_key,
        "match_keys": [match_key, match_key_lower, match_key_upper],  # All possible keys
    }

    # Keys to check for fuzzy matching
    keys_to_check = {match_key, match_key_lower, match_key_upper}

    if source == "ubuyfirst":
        RACE_FEED_UBUYFIRST.insert(0, feed_entry)
        if len(RACE_FEED_UBUYFIRST) > 30:
            RACE_FEED_UBUYFIRST.pop()

        # Check if API already saw this item (by title+price match)
        for api_item in RACE_FEED_API:
            api_key = api_item.get("match_key")
            if api_key in keys_to_check and "matched" not in api_item:
                # API found it first!
                api_item["matched"] = True
                feed_entry["matched"] = True
                diff = now.timestamp() - api_item["timestamp"]
                if diff > 0:  # API was first
                    RACE_STATS["api_wins"] += 1
                    RACE_STATS["total"] += 1
                    RACE_LOG.insert(0, {
                        "title": title[:40],
                        "price": f"${price:.0f}",
                        "winner": "API",
                        "lead_seconds": round(diff, 1),
                        "time": now.strftime("%H:%M:%S"),
                    })
                    logger.info(f"[RACE] API WIN by {diff:.1f}s: {title[:40]}")
                break

    elif source == "api":
        RACE_FEED_API.insert(0, feed_entry)
        if len(RACE_FEED_API) > 30:
            RACE_FEED_API.pop()

        # Check if uBuyFirst already saw this item (fuzzy matching with adjacent price buckets)
        for ubf_item in RACE_FEED_UBUYFIRST:
            ubf_key = ubf_item.get("match_key")
            if ubf_key in keys_to_check and "matched" not in ubf_item:
                # uBuyFirst found it first!
                ubf_item["matched"] = True
                feed_entry["matched"] = True
                diff = now.timestamp() - ubf_item["timestamp"]
                if diff > 0:  # uBuyFirst was first
                    RACE_STATS["ubuyfirst_wins"] += 1
                    RACE_STATS["total"] += 1
                    RACE_LOG.insert(0, {
                        "title": title[:40],
                        "price": f"${price:.0f}",
                        "winner": "uBuyFirst",
                        "lead_seconds": round(diff, 1),
                        "time": now.strftime("%H:%M:%S"),
                    })
                    logger.info(f"[RACE] uBuyFirst WIN by {diff:.1f}s: {title[:40]}")
                break

    if len(RACE_LOG) > 50:
        RACE_LOG.pop()

    if item_id not in RACE_ITEMS:
        RACE_ITEMS[item_id] = {
            "title": title[:80],
            "price": price,
            "category": category,
            "ubuyfirst_time": None,
            "api_time": None,
            "first_source": source,
            "first_time": now,
        }

    item = RACE_ITEMS[item_id]

    if source == "ubuyfirst" and item["ubuyfirst_time"] is None:
        item["ubuyfirst_time"] = now
    elif source == "api" and item["api_time"] is None:
        item["api_time"] = now

    # Check if we now have both sources - determine winner
    if item["ubuyfirst_time"] and item["api_time"] and "winner" not in item:
        diff = (item["api_time"] - item["ubuyfirst_time"]).total_seconds()
        if abs(diff) < 1:  # Within 1 second = tie
            item["winner"] = "tie"
            RACE_STATS["ties"] += 1
        elif diff < 0:  # API was faster (negative means API came first)
            item["winner"] = "api"
            item["lead_seconds"] = abs(diff)
            RACE_STATS["api_wins"] += 1
        else:
            item["winner"] = "ubuyfirst"
            item["lead_seconds"] = diff
            RACE_STATS["ubuyfirst_wins"] += 1
        RACE_STATS["total"] += 1

        # Log the result
        RACE_LOG.insert(0, {
            "item_id": item_id,
            "title": title[:60],
            "price": price,
            "winner": item["winner"],
            "lead_seconds": item.get("lead_seconds", 0),
            "time": now.strftime("%H:%M:%S"),
        })
        if len(RACE_LOG) > 50:
            RACE_LOG.pop()


# ============================================================
# SOURCE COMPARISON ENDPOINTS
# ============================================================

@router.get("/api/source-comparison")
async def source_comparison_stats():
    """Get source comparison statistics (latency tracking for Direct API vs uBuyFirst)"""
    stats = _get_comparison_stats()
    return JSONResponse(stats)


@router.get("/api/source-comparison/races")
async def source_comparison_races():
    """Get all race events (items seen from both sources)"""
    races = _get_race_log()
    return JSONResponse({"races": races, "count": len(races)})


@router.get("/api/source-comparison/reset")
async def source_comparison_reset():
    """Reset source comparison statistics"""
    _reset_source_stats()
    return JSONResponse({"status": "reset"})


# ============================================================
# RACE ENDPOINTS
# ============================================================

@router.get("/ebay/race/auto")
async def ebay_race_auto(interval: int = 15):
    """
    Automatic race comparison dashboard.
    Polls all uBuyFirst presets and compares against items coming through /match_mydata.
    """
    global RACE_RUNNING

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>ShadowSnipe - AUTO RACE</title>
    <style>
        body {{ background: #0a0a15; color: #eee; font-family: monospace; margin: 0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #ff4444; margin-bottom: 5px; }}
        .race-bar {{ background: linear-gradient(90deg, #1a1a2e, #2d1a2e); padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 2px solid #ff4444; display: flex; gap: 15px; align-items: center; }}
        .btn {{ padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 14px; }}
        .btn-start {{ background: #4caf50; color: white; }}
        .btn-stop {{ background: #f44336; color: white; }}
        .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 15px; }}
        .stat {{ background: #16213e; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 32px; font-weight: bold; }}
        .stat-label {{ font-size: 11px; color: #888; margin-top: 5px; }}
        .ubuyfirst {{ color: #ff9800; }}
        .api {{ color: #4fc3f7; }}
        .tie {{ color: #888; }}
        .log {{ background: #0f0f1a; border: 1px solid #333; border-radius: 8px; padding: 15px; max-height: 500px; overflow-y: auto; }}
        .log-entry {{ padding: 10px; border-bottom: 1px solid #222; display: flex; align-items: center; gap: 15px; }}
        .winner-badge {{ padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; }}
        .winner-ubuyfirst {{ background: #ff9800; color: black; }}
        .winner-api {{ background: #4fc3f7; color: black; }}
        .winner-tie {{ background: #666; color: white; }}
        .presets {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 15px; }}
        .preset {{ background: #1a1a2e; padding: 8px 12px; border-radius: 4px; font-size: 11px; border-left: 3px solid #4fc3f7; }}
        .preset.active {{ border-left-color: #4caf50; background: #1a2e1a; }}
        .pulse {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>AUTO RACE - uBuyFirst vs Direct API</h1>
        <p style="color:#888;">Automatically compares items from uBuyFirst proxy vs eBay Browse API polling</p>

        <div class="race-bar">
            <button class="btn btn-start" id="startBtn" onclick="startRace()">START AUTO RACE</button>
            <button class="btn btn-stop" id="stopBtn" onclick="stopRace()" disabled>STOP</button>
            <span>Polling all presets every <strong>{interval}s</strong></span>
            <span id="status" style="margin-left:auto; color:#888;">STOPPED</span>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value api" id="apiWins">0</div>
                <div class="stat-label">API Wins</div>
            </div>
            <div class="stat">
                <div class="stat-value ubuyfirst" id="ubfWins">0</div>
                <div class="stat-label">uBuyFirst Wins</div>
            </div>
            <div class="stat">
                <div class="stat-value ubuyfirst" id="ubfTotal">0</div>
                <div class="stat-label">uBuyFirst Items</div>
            </div>
            <div class="stat">
                <div class="stat-value api" id="apiTotal">0</div>
                <div class="stat-label">API Items</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="pollCount" style="color:#4caf50;">0</div>
                <div class="stat-label">API Polls</div>
            </div>
        </div>

        <div id="matchLog" style="background:#1a2e1a; padding:10px 15px; border-radius:6px; margin-bottom:15px; border-left:3px solid #4caf50; display:none;">
            <strong style="color:#4caf50;">Match Found!</strong> <span id="matchInfo" style="color:#aaa;"></span>
        </div>

        <div style="background:#1a1a2e; padding:10px 15px; border-radius:6px; margin-bottom:15px; border-left:3px solid #ffd700; font-size:11px;">
            <strong style="color:#ffd700;">How it works:</strong> <span style="color:#aaa;">Matches items by title+price. When the same listing appears on both sides, the winner is logged. Keep both uBuyFirst and this dashboard running to compare speeds.</span>
        </div>

        <h3>Active Search Presets</h3>
        <div class="presets" id="presets"></div>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:20px;">
            <div>
                <h3 style="color:#ff9800; margin-bottom:10px;">uBuyFirst Feed <span id="ubfCount" style="font-size:14px; color:#888;">(0)</span></h3>
                <div class="log" id="ubfFeed" style="border-color:#ff9800;">
                    <div class="log-entry" style="color:#666;">Waiting for items from uBuyFirst...</div>
                </div>
            </div>
            <div>
                <h3 style="color:#4fc3f7; margin-bottom:10px;">Direct API Feed <span id="apiCount" style="font-size:14px; color:#888;">(0)</span></h3>
                <div class="log" id="apiFeed" style="border-color:#4fc3f7;">
                    <div class="log-entry" style="color:#666;">Click START to begin API polling...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let racing = false;
        let raceInterval = null;
        let pollCount = 0;
        let raceStartTime = Date.now();
        const presets = {json.dumps(list(UBUYFIRST_PRESETS.keys()))};
        const presetNames = {json.dumps({k: v["name"] for k, v in UBUYFIRST_PRESETS.items()})};
        let currentPresetIndex = 0;

        // Show presets
        const presetsDiv = document.getElementById('presets');
        presets.forEach(p => {{
            const div = document.createElement('div');
            div.className = 'preset';
            div.id = 'preset-' + p;
            div.textContent = presetNames[p];
            presetsDiv.appendChild(div);
        }});

        async function pollPreset(preset) {{
            try {{
                const response = await fetch(`/ebay/race/poll/auto?preset=${{preset}}`);
                const data = await response.json();
                return data;
            }} catch (e) {{
                console.error('Poll error:', e);
                return null;
            }}
        }}

        async function pollAllPresets() {{
            // Rotate through presets one at a time to stay within rate limits
            const preset = presets[currentPresetIndex];
            document.querySelectorAll('.preset').forEach(p => p.classList.remove('active'));
            document.getElementById('preset-' + preset).classList.add('active');

            const data = await pollPreset(preset);
            pollCount++;
            document.getElementById('pollCount').textContent = pollCount;

            currentPresetIndex = (currentPresetIndex + 1) % presets.length;

            // Update stats
            await updateStats();
        }}

        async function updateStats() {{
            try {{
                const response = await fetch('/ebay/race/stats');
                const stats = await response.json();

                document.getElementById('ubfTotal').textContent = stats.ubuyfirst_count || 0;
                document.getElementById('apiTotal').textContent = stats.api_count || 0;
                document.getElementById('apiWins').textContent = stats.api_wins || 0;
                document.getElementById('ubfWins').textContent = stats.ubuyfirst_wins || 0;

                // Show match log if there are matches
                if (stats.log && stats.log.length > 0) {{
                    const lastMatch = stats.log[0];
                    const matchLog = document.getElementById('matchLog');
                    const matchInfo = document.getElementById('matchInfo');
                    matchLog.style.display = 'block';
                    const winnerColor = lastMatch.winner === 'api' ? '#4fc3f7' : '#ff9800';
                    matchInfo.innerHTML = `<span style="color:${{winnerColor}}">${{lastMatch.winner.toUpperCase()}}</span> won by ${{lastMatch.lead_seconds.toFixed(1)}}s: ${{lastMatch.title}} (${{lastMatch.price}})`;
                }}

                // Update uBuyFirst feed
                document.getElementById('ubfCount').textContent = `(${{stats.ubuyfirst_count || 0}})`;
                const ubfFeed = document.getElementById('ubfFeed');
                if (stats.feed_ubuyfirst && stats.feed_ubuyfirst.length > 0) {{
                    ubfFeed.innerHTML = stats.feed_ubuyfirst.map(item => `
                        <div class="log-entry" style="border-left:3px solid #ff9800; padding-left:10px;">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(2)}}</span>
                            <span style="color:#ff9800; font-size:10px;">${{item.category}}</span><br>
                            <span style="color:#aaa; font-size:11px;">${{item.title}}</span>
                        </div>
                    `).join('');
                }}

                // Update API feed
                document.getElementById('apiCount').textContent = `(${{stats.api_count || 0}})`;
                const apiFeed = document.getElementById('apiFeed');
                if (stats.feed_api && stats.feed_api.length > 0) {{
                    apiFeed.innerHTML = stats.feed_api.map(item => `
                        <div class="log-entry" style="border-left:3px solid #4fc3f7; padding-left:10px;">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(2)}}</span>
                            <span style="color:#4fc3f7; font-size:10px;">${{item.category}}</span><br>
                            <span style="color:#aaa; font-size:11px;">${{item.title}}</span>
                        </div>
                    `).join('');
                }}
            }} catch (e) {{
                console.error('Stats error:', e);
            }}
        }}

        function startRace() {{
            racing = true;
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('status').textContent = 'RACING';
            document.getElementById('status').style.color = '#4caf50';
            document.getElementById('status').classList.add('pulse');

            // Clear previous data
            fetch('/ebay/race/reset');
            raceStartTime = Date.now();
            pollCount = 0;

            pollAllPresets();
            raceInterval = setInterval(pollAllPresets, {interval} * 1000 / presets.length);
        }}

        function stopRace() {{
            racing = false;
            clearInterval(raceInterval);
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('status').textContent = 'STOPPED';
            document.getElementById('status').style.color = '#888';
            document.getElementById('status').classList.remove('pulse');
            document.querySelectorAll('.preset').forEach(p => p.classList.remove('active'));
        }}

        // Poll stats every 2 seconds even when not actively polling
        setInterval(updateStats, 2000);
    </script>
</body>
</html>"""

    return HTMLResponse(html)


@router.get("/ebay/race/poll/auto")
async def ebay_race_poll_auto(preset: str = "new_gold_search"):
    """Poll a preset and log items for race comparison"""
    if preset not in UBUYFIRST_PRESETS:
        return JSONResponse({"error": "Invalid preset"}, status_code=400)

    config = UBUYFIRST_PRESETS[preset]

    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    try:
        # Use first 3 keywords only - Browse API doesn't handle long comma lists well
        keywords = config["keywords"]
        if "," in keywords:
            keyword_list = [k.strip() for k in keywords.split(",")][:3]
            keywords = " ".join(keyword_list)  # Use space-separated for OR logic

        # If no keywords (category-only search), use empty string
        if not keywords:
            keywords = ""

        listings = await _search_ebay(
            keywords=keywords,
            category_ids=[config["category_id"]],
            price_min=config["price_min"],
            price_max=config["price_max"],
            entries_per_page=20,
        )

        # Log each item as detected by API
        for listing in listings:
            log_race_item(
                item_id=listing.item_id,
                source="api",
                title=listing.title,
                price=listing.price,
                category=config["name"],
            )

        return JSONResponse({
            "status": "ok",
            "preset": preset,
            "count": len(listings),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/ebay/race/stats")
async def ebay_race_stats():
    """Get current race statistics"""
    return JSONResponse({
        "api_wins": RACE_STATS["api_wins"],
        "ubuyfirst_wins": RACE_STATS["ubuyfirst_wins"],
        "ties": RACE_STATS["ties"],
        "total": RACE_STATS["total"],
        "log": RACE_LOG[:20],
        "items_tracked": len(RACE_ITEMS),
        "feed_ubuyfirst": RACE_FEED_UBUYFIRST[:20],
        "feed_api": RACE_FEED_API[:20],
        "ubuyfirst_count": len(RACE_FEED_UBUYFIRST),
        "api_count": len(RACE_FEED_API),
    })


@router.get("/ebay/race/reset")
async def ebay_race_reset():
    """Reset race data"""
    global RACE_ITEMS, RACE_STATS, RACE_LOG, RACE_FEED_UBUYFIRST, RACE_FEED_API, RACE_SEEN_IDS

    RACE_ITEMS = {}
    RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
    RACE_LOG = []
    RACE_FEED_UBUYFIRST = []
    RACE_FEED_API = []
    RACE_SEEN_IDS = set()  # Track items seen before race to ignore them
    return JSONResponse({"status": "reset"})


# ============================================================
# GOLD RACE ENDPOINTS
# ============================================================

@router.get("/ebay/race/gold")
async def ebay_race_gold(interval: int = 10):
    """
    Focused race test for New Gold Search.
    Matches your uBuyFirst settings exactly.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>GOLD RACE - API vs uBuyFirst</title>
    <style>
        body {{ background: #0a0a15; color: #eee; font-family: monospace; margin: 0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #ffd700; margin-bottom: 5px; }}
        .config {{ background: #1a1a2e; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #ffd700; }}
        .race-bar {{ background: linear-gradient(90deg, #2e2a1a, #1a2e1a); padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 2px solid #ffd700; display: flex; gap: 15px; align-items: center; }}
        .btn {{ padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 14px; }}
        .btn-start {{ background: #ffd700; color: black; }}
        .btn-stop {{ background: #f44336; color: white; }}
        .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 15px; }}
        .stat {{ background: #16213e; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 36px; font-weight: bold; }}
        .stat-label {{ font-size: 11px; color: #888; margin-top: 5px; }}
        .ubuyfirst {{ color: #ff9800; }}
        .api {{ color: #4fc3f7; }}
        .feeds {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .feed {{ background: #0f0f1a; border: 1px solid #333; border-radius: 8px; padding: 15px; max-height: 400px; overflow-y: auto; }}
        .feed-item {{ padding: 8px; border-bottom: 1px solid #222; font-size: 12px; }}
        .feed-item.new {{ background: #1a3d1a; animation: flash 1s; }}
        @keyframes flash {{ 0%,100% {{ background: #1a3d1a; }} 50% {{ background: #2d5a2d; }} }}
        .match-alert {{ background: #2d5a2d; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 2px solid #4caf50; display: none; }}
        .current-keyword {{ background: #ffd700; color: black; padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
        .pulse {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>GOLD RACE - New Gold Search</h1>

        <div class="config">
            <strong>Matching uBuyFirst Settings:</strong><br>
            Category: <span style="color:#4fc3f7;">162134 (Scrap Gold)</span> |
            Price: <span style="color:#4caf50;">$100-$10,000</span> |
            Keywords: <span style="color:#ffd700;">Cycling through {len(GOLD_SEARCH_KEYWORDS)} phrases</span><br>
            <small style="color:#888;">Current: <span id="currentKeyword" class="current-keyword">--</span></small>
        </div>

        <div class="race-bar">
            <button class="btn btn-start" id="startBtn" onclick="startRace()">START GOLD RACE</button>
            <button class="btn btn-stop" id="stopBtn" onclick="stopRace()" disabled>STOP</button>
            <span>Polling every <strong>{interval}s</strong></span>
            <span id="status" style="margin-left:auto; color:#888; font-size:18px;">READY</span>
        </div>

        <div class="match-alert" id="matchAlert">
            <strong style="color:#4caf50;">MATCH FOUND!</strong> <span id="matchInfo"></span>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value api" id="apiWins">0</div>
                <div class="stat-label">API WINS</div>
            </div>
            <div class="stat">
                <div class="stat-value ubuyfirst" id="ubfWins">0</div>
                <div class="stat-label">uBuyFirst WINS</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color:#ffd700;" id="matches">0</div>
                <div class="stat-label">MATCHES</div>
            </div>
            <div class="stat">
                <div class="stat-value ubuyfirst" id="ubfNew">0</div>
                <div class="stat-label">uBuyFirst NEW</div>
            </div>
            <div class="stat">
                <div class="stat-value api" id="apiNew">0</div>
                <div class="stat-label">API NEW</div>
            </div>
        </div>

        <div class="feeds">
            <div>
                <h3 style="color:#ff9800;">uBuyFirst Feed (NEW items only)</h3>
                <div class="feed" id="ubfFeed">
                    <div class="feed-item" style="color:#666;">Waiting for NEW gold items from uBuyFirst...</div>
                </div>
            </div>
            <div>
                <h3 style="color:#4fc3f7;">Direct API Feed (NEW items only)</h3>
                <div class="feed" id="apiFeed">
                    <div class="feed-item" style="color:#666;">Click START to begin polling...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let racing = false;
        let raceInterval = null;
        const keywords = {json.dumps(GOLD_SEARCH_KEYWORDS)};
        let keywordIndex = 0;

        async function poll() {{
            const keyword = keywords[keywordIndex];
            document.getElementById('currentKeyword').textContent = keyword;
            keywordIndex = (keywordIndex + 1) % keywords.length;

            try {{
                const response = await fetch(`/ebay/race/gold/poll?keyword=${{encodeURIComponent(keyword)}}`);
                const data = await response.json();
                updateDisplay();
            }} catch (e) {{
                console.error('Poll error:', e);
            }}
        }}

        async function updateDisplay() {{
            try {{
                const response = await fetch('/ebay/race/stats');
                const stats = await response.json();

                document.getElementById('apiWins').textContent = stats.api_wins || 0;
                document.getElementById('ubfWins').textContent = stats.ubuyfirst_wins || 0;
                document.getElementById('matches').textContent = (stats.api_wins || 0) + (stats.ubuyfirst_wins || 0);
                document.getElementById('ubfNew').textContent = stats.ubuyfirst_count || 0;
                document.getElementById('apiNew').textContent = stats.api_count || 0;

                // Update feeds
                if (stats.feed_ubuyfirst && stats.feed_ubuyfirst.length > 0) {{
                    document.getElementById('ubfFeed').innerHTML = stats.feed_ubuyfirst.slice(0, 15).map(item => `
                        <div class="feed-item ${{item.timestamp > (Date.now()/1000 - 10) ? 'new' : ''}}">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(0)}}</span><br>
                            <span style="color:#aaa;">${{item.title}}</span>
                        </div>
                    `).join('');
                }}

                if (stats.feed_api && stats.feed_api.length > 0) {{
                    document.getElementById('apiFeed').innerHTML = stats.feed_api.slice(0, 15).map(item => `
                        <div class="feed-item ${{item.timestamp > (Date.now()/1000 - 10) ? 'new' : ''}}">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(0)}}</span><br>
                            <span style="color:#aaa;">${{item.title}}</span>
                        </div>
                    `).join('');
                }}

                // Show match alert
                if (stats.log && stats.log.length > 0) {{
                    const match = stats.log[0];
                    document.getElementById('matchAlert').style.display = 'block';
                    const color = match.winner === 'api' ? '#4fc3f7' : '#ff9800';
                    document.getElementById('matchInfo').innerHTML = `<span style="color:${{color}}">${{match.winner.toUpperCase()}}</span> won by ${{match.lead_seconds.toFixed(1)}}s - ${{match.title}}`;
                }}
            }} catch (e) {{
                console.error('Update error:', e);
            }}
        }}

        function startRace() {{
            racing = true;
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('status').textContent = 'RACING';
            document.getElementById('status').style.color = '#4caf50';
            document.getElementById('status').classList.add('pulse');

            // Reset and prime the cache
            fetch('/ebay/race/gold/prime').then(() => {{
                poll();
                raceInterval = setInterval(poll, {interval} * 1000);
            }});

            // Update display every 2 seconds
            setInterval(updateDisplay, 2000);
        }}

        function stopRace() {{
            racing = false;
            clearInterval(raceInterval);
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('status').textContent = 'STOPPED';
            document.getElementById('status').style.color = '#888';
            document.getElementById('status').classList.remove('pulse');
        }}

        // Initial display update
        updateDisplay();
    </script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/ebay/race/gold/prime")
async def ebay_race_gold_prime():
    """Prime the race by recording all current items as 'seen' so we only track NEW ones"""
    global RACE_SEEN_IDS, RACE_FEED_API, RACE_FEED_UBUYFIRST, RACE_STATS, RACE_LOG

    # Reset everything
    RACE_SEEN_IDS = set()
    RACE_FEED_API = []
    RACE_FEED_UBUYFIRST = []
    RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
    RACE_LOG = []

    # Fetch current items and mark them as seen - check ALL keywords in BOTH categories
    if _EBAY_POLLER_AVAILABLE:
        # Sample keywords to prime (checking all 26 would be too slow, but check more than before)
        sample_keywords = GOLD_SEARCH_KEYWORDS[::3]  # Every 3rd keyword = ~9 keywords
        for category in GOLD_SEARCH_CATEGORIES:  # Both 3360 and 162134
            for keyword in sample_keywords:
                try:
                    listings = await _search_ebay(
                        keywords=keyword,
                        category_ids=[category],
                        price_min=100,
                        price_max=10000,
                        entries_per_page=50,
                    )
                    for listing in listings:
                        RACE_SEEN_IDS.add(listing.item_id)
                        # Also add normalized title key
                        norm_key = normalize_title(listing.title) + f"_{int(listing.price/10)*10}"
                        RACE_SEEN_IDS.add(norm_key)
                except Exception as e:
                    logger.warning(f"[RACE PRIME] Error with {keyword}/{category}: {e}")

    logger.info(f"[RACE PRIME] Marked {len(RACE_SEEN_IDS)} existing items as seen")
    return JSONResponse({"status": "primed", "seen_count": len(RACE_SEEN_IDS)})


@router.get("/ebay/race/gold/poll")
async def ebay_race_gold_poll(keyword: str = "14k grams"):
    """Poll for gold items with a specific keyword in BOTH categories (3360 and 162134)"""
    global RACE_KEYWORD_INDEX

    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    total_found = 0
    new_count = 0

    # Search BOTH categories like uBuyFirst does
    for category in GOLD_SEARCH_CATEGORIES:
        try:
            listings = await _search_ebay(
                keywords=keyword,
                category_ids=[category],
                price_min=100,
                price_max=10000,
                entries_per_page=20,
            )
            total_found += len(listings)

            for listing in listings:
                # Check if this is a NEW item (not seen before)
                norm_key = normalize_title(listing.title) + f"_{int(listing.price/10)*10}"

                if listing.item_id not in RACE_SEEN_IDS and norm_key not in RACE_SEEN_IDS:
                    RACE_SEEN_IDS.add(listing.item_id)
                    RACE_SEEN_IDS.add(norm_key)
                    new_count += 1

                    # Log this NEW item
                    log_race_item(
                        item_id=listing.item_id,
                        source="api",
                        title=listing.title,
                        price=listing.price,
                        category=f"Gold ({category})",
                    )
                    logger.info(f"[RACE] NEW API item: {listing.title[:40]} ${listing.price:.0f}")
        except Exception as e:
            logger.warning(f"[RACE POLL] Error with {keyword}/{category}: {e}")

    return JSONResponse({
        "status": "ok",
        "keyword": keyword,
        "found": total_found,
        "new": new_count,
    })


# ============================================================
# FULL RACE ENDPOINTS
# ============================================================

@router.get("/ebay/race/full")
async def ebay_race_full(interval: int = 5):
    """
    Full race test - polls ALL enabled uBuyFirst searches.
    Matches your complete uBuyFirst configuration.
    """
    search_names = [s["name"] for s in ALL_SEARCHES]
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Full Race - All Searches</title>
    <style>
        body {{ background: #1a1a2e; color: #eee; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
        .header {{ text-align: center; margin-bottom: 20px; }}
        h1 {{ color: #ffd700; margin: 0; }}
        .stats {{ display: flex; justify-content: center; gap: 40px; margin: 20px 0; }}
        .stat {{ text-align: center; padding: 15px 25px; background: #16213e; border-radius: 10px; }}
        .stat-value {{ font-size: 36px; font-weight: bold; }}
        .api {{ color: #4fc3f7; }}
        .ubf {{ color: #ff9800; }}
        .feeds {{ display: flex; gap: 20px; margin-top: 20px; }}
        .feed {{ flex: 1; background: #16213e; border-radius: 10px; padding: 15px; max-height: 500px; overflow-y: auto; }}
        .feed h3 {{ margin-top: 0; text-align: center; }}
        .feed-item {{ padding: 8px; margin: 5px 0; background: #0f3460; border-radius: 5px; font-size: 12px; }}
        .feed-item.new {{ border-left: 3px solid #4caf50; }}
        .btn {{ padding: 12px 30px; font-size: 16px; border: none; border-radius: 5px; cursor: pointer; margin: 5px; }}
        .btn-start {{ background: #4caf50; color: white; }}
        .btn-stop {{ background: #f44336; color: white; }}
        .status {{ font-size: 24px; margin: 10px 0; }}
        .pulse {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .search-info {{ background: #0f3460; padding: 10px; border-radius: 5px; margin: 10px 0; font-size: 12px; }}
        .current {{ color: #4caf50; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>FULL RACE - All {len(ALL_SEARCHES)} Searches</h1>
        <div class="status" id="status">READY</div>
        <div class="search-info">
            Searches: {', '.join(search_names)}<br>
            <span class="current">Current: <span id="currentSearch">--</span></span>
        </div>
    </div>

    <div class="stats">
        <div class="stat">
            <div class="stat-value api" id="apiWins">0</div>
            <div>API Wins</div>
        </div>
        <div class="stat">
            <div class="stat-value ubf" id="ubfWins">0</div>
            <div>uBuyFirst Wins</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="apiNew">0</div>
            <div>API Items</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="ubfNew">0</div>
            <div>uBuyFirst Items</div>
        </div>
    </div>

    <div style="text-align: center;">
        <button class="btn btn-start" id="startBtn" onclick="startRace()">START FULL RACE</button>
        <button class="btn btn-stop" id="stopBtn" onclick="stopRace()" disabled>STOP</button>
    </div>

    <div class="feeds">
        <div class="feed">
            <h3 style="color:#ff9800;">uBuyFirst Feed</h3>
            <div id="ubfFeed"><em>Waiting for items...</em></div>
        </div>
        <div class="feed">
            <h3 style="color:#4fc3f7;">Direct API Feed</h3>
            <div id="apiFeed"><em>Press START to begin...</em></div>
        </div>
    </div>

    <script>
        let racing = false;
        let raceInterval = null;

        async function poll() {{
            try {{
                const response = await fetch('/ebay/race/full/poll');
                const data = await response.json();
                document.getElementById('currentSearch').textContent = data.search + ' - ' + data.keyword;
                updateDisplay();
            }} catch (e) {{
                console.error('Poll error:', e);
            }}
        }}

        async function updateDisplay() {{
            try {{
                const response = await fetch('/ebay/race/stats');
                const stats = await response.json();

                document.getElementById('apiWins').textContent = stats.api_wins || 0;
                document.getElementById('ubfWins').textContent = stats.ubuyfirst_wins || 0;
                document.getElementById('ubfNew').textContent = stats.ubuyfirst_count || 0;
                document.getElementById('apiNew').textContent = stats.api_count || 0;

                if (stats.feed_ubuyfirst && stats.feed_ubuyfirst.length > 0) {{
                    document.getElementById('ubfFeed').innerHTML = stats.feed_ubuyfirst.slice(0, 20).map(item => `
                        <div class="feed-item ${{item.timestamp > (Date.now()/1000 - 10) ? 'new' : ''}}">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(0)}}</span>
                            <span style="color:#666;">${{item.category.split('|')[0]}}</span><br>
                            <span style="color:#aaa;">${{decodeURIComponent(item.title.replace(/\\+/g, ' ')).substring(0, 60)}}</span>
                        </div>
                    `).join('');
                }}

                if (stats.feed_api && stats.feed_api.length > 0) {{
                    document.getElementById('apiFeed').innerHTML = stats.feed_api.slice(0, 20).map(item => `
                        <div class="feed-item ${{item.timestamp > (Date.now()/1000 - 10) ? 'new' : ''}}">
                            <span style="color:#888;">${{item.time}}</span>
                            <span style="color:#4caf50; font-weight:bold;">$${{item.price.toFixed(0)}}</span>
                            <span style="color:#666;">${{item.category}}</span><br>
                            <span style="color:#aaa;">${{item.title.substring(0, 60)}}</span>
                        </div>
                    `).join('');
                }}
            }} catch (e) {{
                console.error('Update error:', e);
            }}
        }}

        function startRace() {{
            racing = true;
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('status').textContent = 'RACING';
            document.getElementById('status').style.color = '#4caf50';
            document.getElementById('status').classList.add('pulse');

            fetch('/ebay/race/full/prime').then(() => {{
                poll();
                raceInterval = setInterval(poll, {interval} * 1000);
            }});

            setInterval(updateDisplay, 2000);
        }}

        function stopRace() {{
            racing = false;
            clearInterval(raceInterval);
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('status').textContent = 'STOPPED';
            document.getElementById('status').style.color = '#888';
            document.getElementById('status').classList.remove('pulse');
        }}

        updateDisplay();
    </script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/ebay/race/full/prime")
async def ebay_race_full_prime():
    """Prime the full race by marking existing items as seen across ALL searches"""
    global RACE_SEEN_IDS, RACE_FEED_API, RACE_FEED_UBUYFIRST, RACE_STATS, RACE_LOG, FULL_RACE_INDEX

    RACE_SEEN_IDS = set()
    RACE_FEED_API = []
    RACE_FEED_UBUYFIRST = []
    RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
    RACE_LOG = []
    FULL_RACE_INDEX = 0

    if _EBAY_POLLER_AVAILABLE:
        # Sample from each search to prime
        for search in ALL_SEARCHES:
            try:
                # Use first keyword or empty for category-only searches
                keyword = search["keywords"][0] if search["keywords"] else ""
                # Use first category
                category = search["categories"][0] if search["categories"] else None

                listings = await _search_ebay(
                    keywords=keyword,
                    category_ids=[category] if category else None,
                    price_min=search["price_min"],
                    price_max=search["price_max"],
                    entries_per_page=30,
                )
                for listing in listings:
                    RACE_SEEN_IDS.add(listing.item_id)
                    norm_key = normalize_title(listing.title) + f"_{int(listing.price/10)*10}"
                    RACE_SEEN_IDS.add(norm_key)
            except Exception as e:
                logger.warning(f"[FULL RACE PRIME] Error with {search['name']}: {e}")

    logger.info(f"[FULL RACE PRIME] Marked {len(RACE_SEEN_IDS)} existing items as seen")
    return JSONResponse({"status": "primed", "seen_count": len(RACE_SEEN_IDS), "searches": len(ALL_SEARCHES)})


@router.get("/ebay/race/full/poll")
async def ebay_race_full_poll():
    """Poll ALL searches in PARALLEL - matches how uBuyFirst works"""
    global FULL_RACE_INDEX

    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    FULL_RACE_INDEX += 1  # For keyword rotation

    async def poll_search(search):
        """Poll a single search (all its categories)"""
        keyword = ""
        if search["keywords"]:
            kw_index = FULL_RACE_INDEX % len(search["keywords"])
            keyword = search["keywords"][kw_index]

        found = 0
        new = 0

        for category in search["categories"][:2]:
            try:
                listings = await _search_ebay(
                    keywords=keyword,
                    category_ids=[category],
                    price_min=search["price_min"],
                    price_max=search["price_max"],
                    entries_per_page=20,
                )
                found += len(listings)

                for listing in listings:
                    # Apply title keyword filter (same as uBuyFirst)
                    if not passes_title_filter(listing.title):
                        continue

                    norm_key = normalize_title(listing.title) + f"_{int(listing.price/10)*10}"

                    if listing.item_id not in RACE_SEEN_IDS and norm_key not in RACE_SEEN_IDS:
                        RACE_SEEN_IDS.add(listing.item_id)
                        RACE_SEEN_IDS.add(norm_key)
                        new += 1

                        log_race_item(
                            item_id=listing.item_id,
                            source="api",
                            title=listing.title,
                            price=listing.price,
                            category=search["name"],
                        )
                        logger.info(f"[FULL RACE] NEW: {search['name']} - {listing.title[:40]} ${listing.price:.0f}")
            except Exception as e:
                logger.warning(f"[FULL RACE] Error {search['name']}/{category}: {e}")

        return {"search": search["name"], "found": found, "new": new}

    # Poll ALL searches in PARALLEL
    results = await asyncio.gather(*[poll_search(s) for s in ALL_SEARCHES])

    total_found = sum(r["found"] for r in results)
    total_new = sum(r["new"] for r in results)
    searches_polled = [r["search"] for r in results if r["found"] > 0]

    return JSONResponse({
        "status": "ok",
        "search": "ALL PARALLEL",
        "keyword": f"{len(searches_polled)} searches",
        "found": total_found,
        "new": total_new,
    })


# ============================================================
# BASIC RACE ENDPOINTS (Original)
# ============================================================

@router.get("/ebay/race")
async def ebay_race_test(
    preset: str = "new_gold_search",
    keywords: str = None,
    category_id: str = None,
    price_min: float = None,
    price_max: float = None,
    interval: int = 15,
):
    """
    Race test dashboard - detects new listings and logs timestamps
    Compare against uBuyFirst to see which detects first

    Usage: /ebay/race?preset=new_gold_search&interval=15
    """
    # Get preset config or use custom values
    config = UBUYFIRST_PRESETS.get(preset, UBUYFIRST_PRESETS["new_gold_search"])
    active_keywords = keywords if keywords else config["keywords"]
    active_category = category_id if category_id else config["category_id"]
    active_price_min = price_min if price_min else config["price_min"]
    active_price_max = price_max if price_max else config["price_max"]
    active_name = config["name"]

    # Build preset options HTML
    preset_options = ""
    for key, cfg in UBUYFIRST_PRESETS.items():
        selected = "selected" if key == preset else ""
        preset_options += f'<option value="{key}" {selected}>{cfg["name"]}</option>'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>ShadowSnipe - RACE TEST</title>
    <style>
        body {{ background: #0a0a15; color: #eee; font-family: monospace; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #ff4444; margin-bottom: 5px; }}
        .race-bar {{ background: linear-gradient(90deg, #1a1a2e, #2d1a2e); padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 2px solid #ff4444; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 15px; }}
        .stat {{ background: #16213e; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #4fc3f7; }}
        .stat-label {{ font-size: 11px; color: #888; }}
        .log {{ background: #0f0f1a; border: 1px solid #333; border-radius: 8px; padding: 15px; height: 400px; overflow-y: auto; font-size: 12px; }}
        .log-entry {{ padding: 5px 0; border-bottom: 1px solid #222; }}
        .log-entry.new {{ background: #1a3d1a; animation: flash 0.5s; }}
        @keyframes flash {{ 0%, 100% {{ background: #1a3d1a; }} 50% {{ background: #2d5a2d; }} }}
        .time {{ color: #888; }}
        .item-id {{ color: #ff9800; }}
        .title {{ color: #4fc3f7; }}
        .price {{ color: #4caf50; font-weight: bold; }}
        .controls {{ display: flex; gap: 10px; align-items: center; }}
        .btn {{ padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }}
        .btn-start {{ background: #4caf50; color: white; }}
        .btn-stop {{ background: #f44336; color: white; }}
        .pulse {{ animation: pulse 1s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .new-alert {{ position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #4caf50; color: white; padding: 30px 50px; border-radius: 10px; font-size: 24px; display: none; z-index: 1000; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>RACE TEST - API vs uBuyFirst</h1>
        <p style="color:#888;">Polling eBay API directly. Compare when items appear here vs uBuyFirst.</p>

        <div class="race-bar">
            <div class="controls">
                <select id="presetSelect" onchange="changePreset(this.value)" style="padding:8px; border-radius:4px; background:#1a1a2e; color:#fff; border:1px solid #444; font-size:14px;">
                    {preset_options}
                </select>
                <button class="btn btn-start" id="startBtn" onclick="startRace()">START RACE</button>
                <button class="btn btn-stop" id="stopBtn" onclick="stopRace()" disabled>STOP</button>
                <select id="intervalSelect" style="padding:8px; border-radius:4px; background:#1a1a2e; color:#fff; border:1px solid #444;">
                    <option value="5" {"selected" if interval == 5 else ""}>5s</option>
                    <option value="10" {"selected" if interval == 10 else ""}>10s</option>
                    <option value="15" {"selected" if interval == 15 else ""}>15s</option>
                    <option value="30" {"selected" if interval == 30 else ""}>30s</option>
                    <option value="60" {"selected" if interval == 60 else ""}>60s</option>
                </select>
                <span id="status" style="margin-left:auto; color:#888;">STOPPED</span>
            </div>
        </div>

        <div style="background:#0f1525; padding:10px 15px; border-radius:6px; margin-bottom:15px; font-size:12px; border-left:3px solid #ffd700;">
            <strong style="color:#ffd700;">{active_name}</strong><br>
            <span style="color:#888;">Category:</span> <span style="color:#4fc3f7;">{active_category}</span> |
            <span style="color:#888;">Price:</span> <span style="color:#4caf50;">${active_price_min:.0f}-${active_price_max:.0f}</span><br>
            <span style="color:#888;">Keywords:</span> <span style="color:#aaa;">{active_keywords[:150]}{'...' if len(active_keywords) > 150 else ''}</span>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="pollCount">0</div>
                <div class="stat-label">API Polls</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="newCount">0</div>
                <div class="stat-label">New Items Found</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="lastPoll">--:--:--</div>
                <div class="stat-label">Last Poll</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="avgTime">--</div>
                <div class="stat-label">Avg Response (ms)</div>
            </div>
        </div>

        <h3 style="color:#ffd700;">Detection Log (newest first)</h3>
        <div class="log" id="log">
            <div class="log-entry" style="color:#666;">Race not started. Click START RACE to begin polling.</div>
        </div>
    </div>

    <div class="new-alert" id="newAlert">NEW ITEM DETECTED!</div>

    <audio id="alertSound" preload="auto">
        <source src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1sbJJ1c3x0gHd1c3l2dnZ2d3d4eHl5e3t8fX5+f4CAgYGCgoODhISFhYWGhoeHiIiIiYmJiYqKioqLi4uLjIyMjI2NjY2Ojo6Oj4+Pj5CQkJCRkZGRkpKSkpOTk5OUlJSUlZWVlZaWlpaXl5eXmJiYmJmZmZmampqam5ubm5ycnJydnZ2dnp6enp+fn5+goKCgoaGhoaKioqKjo6OjpKSkpKWlpaWmpqamsbGxsbKysrKzs7Ozw8PDw9TU1NTV1dXV5ubm5ufn5+f4+Pj4+fn5+fr6+vr7+/v7/Pz8/P39/f3+/v7+////AA==" type="audio/wav">
    </audio>

    <script>
        let racing = false;
        let raceInterval = null;
        let pollCount = 0;
        let newCount = 0;
        let seenItems = new Set();
        let responseTimes = [];

        const keywords = "{active_keywords}";
        const categoryId = "{active_category}";
        const priceMin = {active_price_min};
        const priceMax = {active_price_max};
        let pollInterval = {interval} * 1000;

        function changePreset(preset) {{
            const interval = document.getElementById('intervalSelect').value;
            window.location.href = `/ebay/race?preset=${{preset}}&interval=${{interval}}`;
        }}

        document.getElementById('intervalSelect').addEventListener('change', function() {{
            pollInterval = parseInt(this.value) * 1000;
            if (racing) {{
                clearInterval(raceInterval);
                raceInterval = setInterval(poll, pollInterval);
            }}
        }});

        async function poll() {{
            const startTime = Date.now();
            try {{
                const response = await fetch(`/ebay/race/poll?keywords=${{encodeURIComponent(keywords)}}&category_id=${{categoryId}}&price_min=${{priceMin}}&price_max=${{priceMax}}`);
                const data = await response.json();
                const elapsed = Date.now() - startTime;
                responseTimes.push(elapsed);
                if (responseTimes.length > 20) responseTimes.shift();

                pollCount++;
                document.getElementById('pollCount').textContent = pollCount;
                document.getElementById('lastPoll').textContent = new Date().toLocaleTimeString();
                document.getElementById('avgTime').textContent = Math.round(responseTimes.reduce((a,b) => a+b, 0) / responseTimes.length);

                // Check for new items
                const log = document.getElementById('log');
                for (const item of data.items || []) {{
                    if (!seenItems.has(item.item_id)) {{
                        seenItems.add(item.item_id);
                        newCount++;
                        document.getElementById('newCount').textContent = newCount;

                        // Log the new item with thumbnail
                        const entry = document.createElement('div');
                        entry.className = 'log-entry new';
                        entry.style.cssText = 'display:flex; align-items:center; gap:10px; padding:8px;';
                        entry.innerHTML = `
                            <img src="${{item.thumbnail}}" style="width:50px; height:50px; object-fit:cover; border-radius:4px; border:1px solid #333;" onerror="this.style.display='none'">
                            <div style="flex:1; min-width:0;">
                                <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                                    <span class="time">${{new Date().toLocaleTimeString()}}</span>
                                    <span style="background:#4caf50; color:white; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:bold;">NEW</span>
                                    <span class="price">${{item.price}}</span>
                                    <span style="color:#666; font-size:10px;">${{item.condition}}</span>
                                </div>
                                <a href="${{item.url}}" target="_blank" class="title" style="display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${{item.title}}</a>
                            </div>
                            <a href="${{item.checkout_url}}" target="_blank" style="background:#ff5722; color:white; padding:8px 12px; border-radius:4px; text-decoration:none; font-weight:bold; font-size:12px; white-space:nowrap;">BUY NOW</a>
                        `;
                        log.insertBefore(entry, log.firstChild);

                        // Alert
                        showAlert();
                        playSound();
                    }}
                }}
            }} catch (e) {{
                console.error('Poll error:', e);
            }}
        }}

        function showAlert() {{
            const alert = document.getElementById('newAlert');
            alert.style.display = 'block';
            setTimeout(() => alert.style.display = 'none', 1500);
        }}

        function playSound() {{
            try {{
                document.getElementById('alertSound').play();
            }} catch (e) {{}}
        }}

        function startRace() {{
            racing = true;
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('status').textContent = 'RACING';
            document.getElementById('status').style.color = '#4caf50';
            document.getElementById('status').classList.add('pulse');
            document.getElementById('log').innerHTML = `<div class="log-entry" style="color:#4caf50;">Race started! Polling every ${{pollInterval/1000}} seconds...</div>`;

            poll(); // First poll immediately
            raceInterval = setInterval(poll, pollInterval);
        }}

        function stopRace() {{
            racing = false;
            clearInterval(raceInterval);
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('status').textContent = 'STOPPED';
            document.getElementById('status').style.color = '#888';
            document.getElementById('status').classList.remove('pulse');
        }}
    </script>
</body>
</html>"""

    return HTMLResponse(html)


@router.get("/ebay/race/poll")
async def ebay_race_poll(
    keywords: str = "14k gold scrap",
    category_id: str = "162134",
    price_min: float = 50,
    price_max: float = 5000,
):
    """API endpoint for race polling - returns JSON of current listings"""
    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    listings = await _search_ebay(
        keywords=keywords,
        category_ids=[category_id],
        price_min=price_min,
        price_max=price_max,
        entries_per_page=50,
    )

    items = []
    for listing in listings:
        item_id = listing.item_id
        items.append({
            "item_id": item_id,
            "title": listing.title,
            "price": f"${listing.price:.2f}",
            "price_raw": listing.price,
            "url": listing.view_url or f"https://www.ebay.com/itm/{item_id}",
            "checkout_url": f"https://www.ebay.com/itm/{item_id}?nordt=true&orig_cvip=true&rt=nc",
            "thumbnail": listing.thumbnail_url or listing.gallery_url or "",
            "condition": listing.condition or "",
            "seller": listing.seller_id or "",
        })

    return JSONResponse({
        "status": "ok",
        "count": len(items),
        "items": items,
        "timestamp": datetime.now().isoformat(),
    })
