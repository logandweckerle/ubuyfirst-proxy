"""
eBay Routes - eBay API endpoints and race comparison
Extracted from main.py for modularity

This module contains:
- /ebay/* endpoints for eBay API interaction
- Race comparison logic (uBuyFirst vs Direct API)
- Gold/Silver dashboard endpoints
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

# Create router for eBay endpoints
router = APIRouter(prefix="/ebay", tags=["ebay"])

# ============================================================
# MODULE-LEVEL STATE (initialized here, configured via configure_ebay)
# ============================================================

# Race tracking state
RACE_DETECTED_ITEMS: Dict = {}
RACE_ITEMS: Dict = {}  # item_id -> {"ubuyfirst_time": datetime, "api_time": datetime, "title": str, "price": float}
RACE_RUNNING = False
RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
RACE_LOG: List = []  # List of comparison results
RACE_FEED_UBUYFIRST: List = []  # Last 30 items from uBuyFirst
RACE_FEED_API: List = []  # Last 30 items from API

# API Analysis Mode - when enabled, API listings get full analysis (not just race logging)
API_ANALYSIS_ENABLED = True  # Always enabled - Direct API should analyze and alert

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

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_ebay)
# ============================================================

# eBay poller functions (from ebay_poller.py)
_search_ebay = None
_ebay_get_stats = None
_ebay_start_polling = None
_ebay_stop_polling = None
_ebay_clear_seen = None
_get_item_description = None
_get_item_details = None
_browse_api_available = None
_EBAY_SEARCH_CONFIGS = None
_analyze_listing_callback = None  # Callback for full AI analysis

# Other dependencies
_get_spot_prices = None
_send_discord_alert = None
_EBAY_POLLER_AVAILABLE = False


def configure_ebay(
    # eBay poller functions
    search_ebay: Callable,
    ebay_get_stats: Callable,
    ebay_start_polling: Callable,
    ebay_stop_polling: Callable,
    ebay_clear_seen: Callable,
    get_item_description: Callable,
    get_item_details: Callable,
    browse_api_available: Callable,
    EBAY_SEARCH_CONFIGS: Dict,
    # Other dependencies
    get_spot_prices: Callable,
    send_discord_alert: Callable,
    EBAY_POLLER_AVAILABLE: bool,
    analyze_listing_callback: Callable = None,  # Callback for full AI analysis
):
    """Configure the eBay module with all required dependencies."""
    global _search_ebay, _ebay_get_stats, _ebay_start_polling, _ebay_stop_polling
    global _ebay_clear_seen, _get_item_description, _get_item_details
    global _browse_api_available, _EBAY_SEARCH_CONFIGS
    global _get_spot_prices, _send_discord_alert, _EBAY_POLLER_AVAILABLE
    global _analyze_listing_callback

    _search_ebay = search_ebay
    _ebay_get_stats = ebay_get_stats
    _ebay_start_polling = ebay_start_polling
    _ebay_stop_polling = ebay_stop_polling
    _ebay_clear_seen = ebay_clear_seen
    _get_item_description = get_item_description
    _get_item_details = get_item_details
    _browse_api_available = browse_api_available
    _EBAY_SEARCH_CONFIGS = EBAY_SEARCH_CONFIGS
    _get_spot_prices = get_spot_prices
    _send_discord_alert = send_discord_alert
    _EBAY_POLLER_AVAILABLE = EBAY_POLLER_AVAILABLE
    _analyze_listing_callback = analyze_listing_callback

    logger.info("[EBAY ROUTES] Module configured")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_title(title: str) -> str:
    """Normalize title for comparison (lowercase, remove punctuation, etc.)"""
    title = title.lower()
    title = re.sub(r'[^\w\s]', '', title)
    title = ' '.join(title.split())
    return title


def log_race_item(item_id: str, source: str, title: str, price: float, category: str = ""):
    """
    Log an item for race comparison.
    Called by both uBuyFirst webhook and API poller.
    """
    global RACE_STATS, RACE_LOG, RACE_FEED_UBUYFIRST, RACE_FEED_API, RACE_ITEMS

    now = datetime.now()
    normalized = normalize_title(title)

    feed_entry = {
        "item_id": item_id,
        "title": title[:60],
        "price": price,
        "time": now.isoformat(),
        "category": category,
    }

    # Add to appropriate feed (for live dashboard)
    if source == "uBuyFirst":
        RACE_FEED_UBUYFIRST.insert(0, feed_entry)
        if len(RACE_FEED_UBUYFIRST) > 30:
            RACE_FEED_UBUYFIRST.pop()

        # Check if API already saw this (by normalized title match)
        for api_item in RACE_FEED_API:
            if normalize_title(api_item["title"]) == normalized:
                # API saw it first!
                api_time = datetime.fromisoformat(api_item["time"])
                delta = (now - api_time).total_seconds()
                if delta > 0 and delta < 300:  # Within 5 minutes
                    RACE_STATS["api_wins"] += 1
                    RACE_STATS["total"] += 1
                    RACE_LOG.insert(0, {
                        "title": title[:50],
                        "winner": "API",
                        "delta_seconds": round(delta, 1),
                        "time": now.isoformat(),
                    })
                break
    else:  # API source
        RACE_FEED_API.insert(0, feed_entry)
        if len(RACE_FEED_API) > 30:
            RACE_FEED_API.pop()

        # Check if uBuyFirst already saw this
        for ubf_item in RACE_FEED_UBUYFIRST:
            if normalize_title(ubf_item["title"]) == normalized:
                # uBuyFirst saw it first!
                ubf_time = datetime.fromisoformat(ubf_item["time"])
                delta = (now - ubf_time).total_seconds()
                if delta > 0 and delta < 300:
                    RACE_STATS["ubuyfirst_wins"] += 1
                    RACE_STATS["total"] += 1
                    RACE_LOG.insert(0, {
                        "title": title[:50],
                        "winner": "uBuyFirst",
                        "delta_seconds": round(delta, 1),
                        "time": now.isoformat(),
                    })
                break

    # Trim race log
    if len(RACE_LOG) > 50:
        RACE_LOG.pop()

    # Also track by item_id for exact matches
    if item_id not in RACE_ITEMS:
        RACE_ITEMS[item_id] = {
            "title": title,
            "price": price,
            "ubuyfirst_time": None,
            "api_time": None,
        }

    item = RACE_ITEMS[item_id]
    if source == "uBuyFirst":
        item["ubuyfirst_time"] = now
    else:
        item["api_time"] = now

    # If both sources have seen it, calculate winner
    if item["ubuyfirst_time"] and item["api_time"]:
        delta = (item["ubuyfirst_time"] - item["api_time"]).total_seconds()
        if abs(delta) < 2:
            RACE_STATS["ties"] += 1
        elif delta > 0:
            RACE_STATS["api_wins"] += 1
        else:
            RACE_STATS["ubuyfirst_wins"] += 1
        RACE_STATS["total"] += 1

        RACE_LOG.insert(0, {
            "item_id": item_id,
            "title": title[:50],
            "winner": "TIE" if abs(delta) < 2 else ("API" if delta > 0 else "uBuyFirst"),
            "delta_seconds": round(abs(delta), 1),
            "time": now.isoformat(),
        })
        if len(RACE_LOG) > 50:
            RACE_LOG.pop()


async def race_callback(listing: Any):
    """Callback for eBay poller to log items for race comparison"""
    try:
        item_id = listing.item_id
        title = listing.title
        price = listing.price
        category = getattr(listing, 'category', '')

        log_race_item(item_id, "API", title, price, category)
        logger.info(f"[RACE] API found: {title[:40]}... @ ${price}")
    except Exception as e:
        logger.warning(f"[RACE] Callback error: {e}")
        import traceback
        logger.warning(f"[RACE] Traceback: {traceback.format_exc()}")


# ============================================================
# EBAY ENDPOINTS
# ============================================================

@router.get("/stats")
async def ebay_stats():
    """Get eBay API usage statistics"""
    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    stats = _ebay_get_stats()
    return JSONResponse({
        "status": "ok",
        "stats": stats,
        "categories_configured": list(_EBAY_SEARCH_CONFIGS.keys()) if _EBAY_POLLER_AVAILABLE else [],
    })


@router.get("/search")
async def ebay_search_endpoint(
    keywords: str = "14k gold scrap",
    category: str = None,
    price_min: float = 50,
    price_max: float = 5000,
    limit: int = 25,
):
    """
    Test eBay Finding API search

    Example: /ebay/search?keywords=14k+gold+scrap&price_min=100&limit=10
    """
    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    category_ids = None
    if category and category in _EBAY_SEARCH_CONFIGS:
        category_ids = _EBAY_SEARCH_CONFIGS[category]["category_ids"]

    listings = await _search_ebay(
        keywords=keywords,
        category_ids=category_ids,
        price_min=price_min,
        price_max=price_max,
        entries_per_page=min(limit, 100),
    )

    return JSONResponse({
        "status": "ok",
        "count": len(listings),
        "keywords": keywords,
        "listings": [l.to_dict() for l in listings],
        "api_stats": _ebay_get_stats(),
    })


@router.get("/gold")
async def ebay_gold_dashboard(
    keywords: str = "14k gold scrap",
    price_min: float = 50,
    price_max: float = 5000,
    limit: int = 50,
):
    """
    Gold listings dashboard - shows eBay gold listings with thumbnails and quick links

    Usage: /ebay/gold?keywords=14k+gold+scrap&price_min=100&limit=25
    """
    if not _EBAY_POLLER_AVAILABLE:
        return HTMLResponse("<h1>eBay Poller Not Available</h1><p>Check EBAY_APP_ID in .env</p>")

    # Fetch listings from eBay
    category_ids = _EBAY_SEARCH_CONFIGS.get("gold", {}).get("category_ids", [])
    listings = await _search_ebay(
        keywords=keywords,
        category_ids=category_ids,
        price_min=price_min,
        price_max=price_max,
        entries_per_page=min(limit, 100),
    )

    # Get spot prices for display
    prices = _get_spot_prices()
    gold_oz = prices.get('gold_oz', 0)

    stats = _ebay_get_stats()

    # Build HTML
    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Gold Listings - eBay API</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #ffd700; }}
        .stats {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; }}
        .card {{ background: #16213e; border-radius: 8px; overflow: hidden; }}
        .card img {{ width: 100%; height: 200px; object-fit: contain; background: #0f0f23; }}
        .card-body {{ padding: 15px; }}
        .card-title {{ font-size: 14px; color: #eee; margin-bottom: 10px; height: 40px; overflow: hidden; }}
        .card-price {{ font-size: 24px; color: #4ade80; font-weight: bold; }}
        .card-links {{ margin-top: 10px; }}
        .card-links a {{ color: #60a5fa; text-decoration: none; margin-right: 15px; }}
        .card-links a:hover {{ text-decoration: underline; }}
        .no-image {{ background: #333; height: 200px; display: flex; align-items: center; justify-content: center; color: #666; }}
    </style>
</head>
<body>
    <h1>🪙 Gold Listings Dashboard</h1>
    <div class="stats">
        <strong>Spot Price:</strong> ${gold_oz:.2f}/oz |
        <strong>Keywords:</strong> {keywords} |
        <strong>Found:</strong> {len(listings)} listings |
        <strong>API Calls:</strong> {stats.get('total_calls', 0)}
    </div>
    <div class="grid">
'''

    for listing in listings:
        img_url = getattr(listing, 'image_url', '') or ''
        title = listing.title[:80] if listing.title else 'No title'
        price = listing.price
        item_url = getattr(listing, 'view_url', '') or f"https://www.ebay.com/itm/{listing.item_id}"

        img_html = f'<img src="{img_url}" alt="listing">' if img_url else '<div class="no-image">No Image</div>'

        html += f'''
        <div class="card">
            {img_html}
            <div class="card-body">
                <div class="card-title">{title}</div>
                <div class="card-price">${price:.2f}</div>
                <div class="card-links">
                    <a href="{item_url}" target="_blank">View on eBay</a>
                </div>
            </div>
        </div>
'''

    html += '''
    </div>
</body>
</html>
'''
    return HTMLResponse(html)


@router.get("/silver")
async def ebay_silver_dashboard(
    keywords: str = "sterling silver scrap",
    price_min: float = 30,
    price_max: float = 5000,
    limit: int = 50,
):
    """
    Silver listings dashboard - shows eBay silver listings with thumbnails

    Usage: /ebay/silver?keywords=sterling+scrap&price_min=50&limit=25
    """
    if not _EBAY_POLLER_AVAILABLE:
        return HTMLResponse("<h1>eBay Poller Not Available</h1><p>Check EBAY_APP_ID in .env</p>")

    # Fetch listings from eBay
    category_ids = _EBAY_SEARCH_CONFIGS.get("silver", {}).get("category_ids", [])
    listings = await _search_ebay(
        keywords=keywords,
        category_ids=category_ids,
        price_min=price_min,
        price_max=price_max,
        entries_per_page=min(limit, 100),
    )

    # Get spot prices
    prices = _get_spot_prices()
    silver_oz = prices.get('silver_oz', 0)

    stats = _ebay_get_stats()

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Silver Listings - eBay API</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #c0c0c0; }}
        .stats {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; }}
        .card {{ background: #16213e; border-radius: 8px; overflow: hidden; }}
        .card img {{ width: 100%; height: 200px; object-fit: contain; background: #0f0f23; }}
        .card-body {{ padding: 15px; }}
        .card-title {{ font-size: 14px; color: #eee; margin-bottom: 10px; height: 40px; overflow: hidden; }}
        .card-price {{ font-size: 24px; color: #4ade80; font-weight: bold; }}
        .card-links {{ margin-top: 10px; }}
        .card-links a {{ color: #60a5fa; text-decoration: none; margin-right: 15px; }}
    </style>
</head>
<body>
    <h1>🥈 Silver Listings Dashboard</h1>
    <div class="stats">
        <strong>Spot Price:</strong> ${silver_oz:.2f}/oz |
        <strong>Keywords:</strong> {keywords} |
        <strong>Found:</strong> {len(listings)} listings |
        <strong>API Calls:</strong> {stats.get('total_calls', 0)}
    </div>
    <div class="grid">
'''

    for listing in listings:
        img_url = getattr(listing, 'image_url', '') or ''
        title = listing.title[:80] if listing.title else 'No title'
        price = listing.price
        item_url = getattr(listing, 'view_url', '') or f"https://www.ebay.com/itm/{listing.item_id}"

        img_html = f'<img src="{img_url}" alt="listing">' if img_url else '<div style="background:#333;height:200px;display:flex;align-items:center;justify-content:center;color:#666;">No Image</div>'

        html += f'''
        <div class="card">
            {img_html}
            <div class="card-body">
                <div class="card-title">{title}</div>
                <div class="card-price">${price:.2f}</div>
                <div class="card-links">
                    <a href="{item_url}" target="_blank">View on eBay</a>
                </div>
            </div>
        </div>
'''

    html += '''
    </div>
</body>
</html>
'''
    return HTMLResponse(html)


# ============================================================
# RACE COMPARISON ENDPOINTS
# ============================================================

@router.get("/race/stats")
async def ebay_race_stats():
    """Get race comparison statistics"""
    return JSONResponse({
        "api_wins": RACE_STATS["api_wins"],
        "ubuyfirst_wins": RACE_STATS["ubuyfirst_wins"],
        "ties": RACE_STATS["ties"],
        "total": RACE_STATS["total"],
        "recent_races": RACE_LOG[:20],
        "feed_ubuyfirst": RACE_FEED_UBUYFIRST[:10],
        "feed_api": RACE_FEED_API[:10],
    })


@router.get("/race/reset")
async def ebay_race_reset():
    """Reset race statistics"""
    global RACE_STATS, RACE_LOG, RACE_ITEMS, RACE_FEED_UBUYFIRST, RACE_FEED_API
    RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
    RACE_LOG.clear()
    RACE_ITEMS.clear()
    RACE_FEED_UBUYFIRST.clear()
    RACE_FEED_API.clear()
    return JSONResponse({"status": "ok", "message": "Race stats reset"})


# ============================================================
# POLLING CONTROL ENDPOINTS
# ============================================================

@router.post("/poll/start")
async def ebay_poll_start(categories: str = "gold", race_mode: bool = False):
    """
    Start background polling for categories

    Example: /ebay/poll/start?categories=gold,silver&race_mode=true
    """
    global RACE_STATS, RACE_LOG, RACE_FEED_UBUYFIRST, RACE_FEED_API

    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    cat_list = [c.strip() for c in categories.split(",")]
    valid_cats = [c for c in cat_list if c in _EBAY_SEARCH_CONFIGS]

    if not valid_cats:
        return JSONResponse({
            "error": f"No valid categories. Available: {list(_EBAY_SEARCH_CONFIGS.keys())}"
        }, status_code=400)

    # For race mode, stop existing polling first so we can attach the callback
    if race_mode:
        # Stop existing polls to attach callback to fresh tasks
        await _ebay_stop_polling(valid_cats)
        await asyncio.sleep(0.5)  # Brief pause for cleanup
        _ebay_clear_seen()
        # Clear the race tracking data
        RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
        RACE_LOG.clear()
        RACE_FEED_UBUYFIRST.clear()
        RACE_FEED_API.clear()
        logger.info("[RACE] Cleared race data for fresh start")

    # Start polling in background - with race callback if race_mode, otherwise analyze callback
    if race_mode:
        callback = race_callback
    elif _analyze_listing_callback:
        callback = _analyze_listing_callback  # Full AI analysis for each new listing
    else:
        callback = None
    asyncio.create_task(_ebay_start_polling(valid_cats, callback=callback))

    return JSONResponse({
        "status": "ok",
        "message": f"Started polling for: {valid_cats}" + (" (RACE MODE)" if race_mode else ""),
        "race_mode": race_mode,
        "available_categories": list(_EBAY_SEARCH_CONFIGS.keys()),
    })


@router.post("/poll/stop")
async def ebay_poll_stop(categories: str = None):
    """Stop background polling"""
    if not _EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    cat_list = None
    if categories:
        cat_list = [c.strip() for c in categories.split(",")]

    await _ebay_stop_polling(cat_list)

    return JSONResponse({
        "status": "ok",
        "message": f"Stopped polling for: {cat_list or 'all'}",
    })


# ============================================================
# ANALYSIS CONTROL ENDPOINTS
# ============================================================

@router.post("/analysis/start")
async def ebay_analysis_start():
    """
    Enable API analysis mode.
    When enabled, listings from the direct eBay API will be fully analyzed
    and broadcast to WebSocket clients (same as uBuyFirst).
    """
    global API_ANALYSIS_ENABLED
    API_ANALYSIS_ENABLED = True
    logger.info("[API] Analysis mode ENABLED - API listings will be analyzed and broadcast")
    return JSONResponse({
        "status": "ok",
        "message": "API analysis enabled - listings will be analyzed and broadcast",
        "api_analysis_enabled": True,
    })


@router.post("/analysis/stop")
async def ebay_analysis_stop():
    """
    Disable API analysis mode.
    API listings will still be logged for race comparison, but not analyzed.
    """
    global API_ANALYSIS_ENABLED
    API_ANALYSIS_ENABLED = False
    logger.info("[API] Analysis mode DISABLED - API listings will only be race-logged")
    return JSONResponse({
        "status": "ok",
        "message": "API analysis disabled - listings will only be race-logged",
        "api_analysis_enabled": False,
    })


@router.get("/analysis/status")
async def ebay_analysis_status():
    """Check if API analysis mode is enabled"""
    return JSONResponse({
        "api_analysis_enabled": API_ANALYSIS_ENABLED,
        "description": "When enabled, API listings are fully analyzed and broadcast to dashboard",
    })
