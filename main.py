"""

Claude Proxy Server v3 - Optimized

Enhanced with async image fetching, smart caching, and connection pooling



Optimizations:

1. Async parallel image fetching (httpx) - 2-4 seconds faster per listing

2. Database connection pooling with WAL mode - faster writes

3. Smart cache with different TTLs for BUY vs PASS results

4. Modular code structure for maintainability

5. Background workers for spot price updates and cache cleanup

6. Training data capture for Tier override analysis

"""



import os

import sys

import re

import csv

import json

import uuid

import asyncio

import logging

import traceback

import sqlite3

import time as _time  # FIX: Added at top level for background tasks

import importlib  # FIX: Added for hot_reload function

from io import StringIO

from datetime import datetime

from urllib.parse import parse_qs, quote as url_quote

import urllib.parse  # FIX: Explicit import for URL encoding

from typing import Dict, Any, Optional, List

# Import price corrections checker
try:
    from screenshot_extractor import check_price_correction, log_price_correction
except ImportError:
    check_price_correction = None
    log_price_correction = None

from pathlib import Path
from contextlib import asynccontextmanager



from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse

import anthropic

import uvicorn

import httpx  # FIX: Moved import to top level

# Import from utils package
from utils import (
    CATEGORY_THRESHOLDS,
    get_category_threshold,
    check_seller_spam,
    add_blocked_seller,
    remove_blocked_seller,
    clear_blocked_sellers,
    import_blocked_sellers,
    get_blocked_sellers,
    get_blocked_count,
    save_blocked_sellers,
    BLOCKED_SELLERS,
    SELLER_SPAM_WINDOW,
    SELLER_SPAM_THRESHOLD,
    # Rate constants
    GOLD_SELL_RATE,
    GOLD_MAX_BUY_RATE,
    SILVER_SELL_RATE,
    SILVER_MAX_BUY_RATE,
    NATIVE_MAX_MELT_MULTIPLIER,
    # Discord
    send_discord_alert as utils_send_discord_alert,
    DISCORD_SENT_ALERTS,
    # Validation
    normalize_tcg_lego_keys as utils_normalize_tcg_lego_keys,
    parse_price as utils_parse_price,
    calculate_margin as utils_calculate_margin,
    check_lego_condition,
    LEGO_PASS_TERMS,
    LEGO_KNOCKOFF_TERMS,
)
# Source comparison logging (Direct API vs uBuyFirst speed comparison)
from utils.source_comparison import log_listing_received, get_comparison_stats, get_race_log, reset_stats as reset_source_stats

# Tier 2 verification module
from pipeline.tier2 import (
    configure_tier2,
    background_sonnet_verify,
    tier2_reanalyze,
    tier2_reanalyze_openai,
)

# Validation module (margin calculations, weight validation)
from pipeline.validation import (
    configure_validation,
    validate_and_fix_margin,
)

# Analysis route module (main /match_mydata endpoint)
from routes.analysis import router as analysis_router, configure_analysis
from routes.ebay import router as ebay_router, configure_ebay, log_race_item as ebay_log_race_item
from routes.pricecharting import router as pricecharting_router, configure_pricecharting
from routes.sellers import router as sellers_router, configure_sellers
from routes.dashboard import router as dashboard_router, configure_dashboard
from routes.keepa import router as keepa_router, configure_keepa
from routes.ebay_race import (
    router as ebay_race_router,
    configure_ebay_race,
    UBUYFIRST_PRESETS as RACE_PRESETS,
    log_race_item,
    RACE_STATS,
    RACE_FEED_API,
    RACE_FEED_UBUYFIRST,
)

# Training data log path

TRAINING_LOG_PATH = Path("training_overrides.jsonl")



# Purchase log - records items user actually bought

PURCHASE_LOG_PATH = Path("purchases.jsonl")


# ============================================================

# PRE-COMPILED REGEX PATTERNS (Performance optimization)

# ============================================================

# Weight extraction patterns

WEIGHT_PATTERNS = [
    re.compile(r'(\d*\.?\d+)\s*(?:gram|grams|gr)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*g\b', re.IGNORECASE),  # Handles .8g, 0.8g, 8g
    re.compile(r'(\d*\.?\d+)\s*(?:dwt|DWT)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*(?:ozt|oz\.t|troy\s*oz)\b', re.IGNORECASE),  # Troy oz = 31.1g
    re.compile(r'(\d*\.?\d+)\s*oz\b', re.IGNORECASE),  # Plain oz = 28.35g (avoirdupois)
]

# Fractional oz patterns (e.g., "1/2 oz", "1/4 oz", "1/10 oz")
FRACTION_OZT_PATTERN = re.compile(r'(\d+)/(\d+)\s*(?:ozt|oz\.t|troy\s*oz)\b', re.IGNORECASE)  # Troy
FRACTION_OZ_PATTERN = re.compile(r'(\d+)/(\d+)\s*oz\b', re.IGNORECASE)  # Plain oz



# Karat extraction patterns (pattern, karat_value)

KARAT_PATTERNS = [

    (re.compile(r'\b24\s*k(?:t|arat)?\b', re.IGNORECASE), 24),

    (re.compile(r'\b22\s*k(?:t|arat)?\b', re.IGNORECASE), 22),

    (re.compile(r'\b18\s*k(?:t|arat)?\b', re.IGNORECASE), 18),

    (re.compile(r'\b14\s*k(?:t|arat)?\b', re.IGNORECASE), 14),

    (re.compile(r'\b10\s*k(?:t|arat)?\b', re.IGNORECASE), 10),

    (re.compile(r'\b9\s*k(?:t|arat)?\b', re.IGNORECASE), 9),

    (re.compile(r'\b999\b'), 24),

    (re.compile(r'\b916\b'), 22),

    (re.compile(r'\b750\b'), 18),

    (re.compile(r'\b585\b'), 14),

    (re.compile(r'\b417\b'), 10),

    (re.compile(r'\b375\b'), 9),

]






# Import our optimized modules

from config import (

    HOST, PORT, CLAUDE_API_KEY, MODEL_FAST, MODEL_FULL,

    COST_PER_CALL_HAIKU, COST_PER_CALL_SONNET, CACHE, SPOT_PRICES, DB_PATH,

    EBAY_APP_ID, EBAY_CERT_ID, DISCORD_WEBHOOK_URL, TIER2_ENABLED, TIER2_MIN_MARGIN,

    IMAGES, INSTANT_PASS_KEYWORDS, INSTANT_PASS_PRICE_THRESHOLDS,

    TIER2_PROVIDER, OPENAI_API_KEY, OPENAI_TIER2_MODEL, COST_PER_CALL_OPENAI,

    COST_PER_CALL_GPT4O, COST_PER_CALL_GPT4O_MINI,

    PARALLEL_MODE, SKIP_TIER2_FOR_HOT

)

from database import (

    db, save_listing, log_incoming_listing, update_pattern_outcome,

    get_analytics, get_pattern_analytics, extract_title_keywords, get_db_debug_info,

    # Seller profiling
    get_seller_profile, get_all_seller_profiles, get_high_value_sellers,
    get_seller_profile_stats, analyze_new_seller, populate_seller_profiles_from_purchases,
    calculate_seller_score, save_seller_profile

)

from smart_cache import cache, start_cache_cleanup

from image_fetcher import fetch_images_parallel, process_image_list

from spot_prices import fetch_spot_prices, start_spot_updates, get_spot_prices

from user_price_db import lookup_price as lookup_user_price, get_stats as get_user_price_stats

# Legacy prompts import (being replaced by agents)

from prompts import get_category_prompt, get_business_context, get_system_context, get_gold_prompt, get_silver_prompt

# New agent-based architecture

from agents import detect_category, get_agent, AGENTS


def get_agent_prompt(category: str) -> str:
    """Get prompt from agent if available, otherwise fall back to prompts.py"""
    agent_class = get_agent(category)
    if agent_class:
        # Instantiate the agent and use its prompt
        agent = agent_class()
        business = get_business_context()
        return f"{business}\n\n{agent.get_prompt()}"
    # Fallback to legacy prompts.py
    return get_system_context(category)


# Fast extraction for instant server-side calculations (no AI needed)

try:

    from fast_extract import fast_extract_gold, fast_extract_silver, FastExtractResult

    FAST_EXTRACT_AVAILABLE = True

    print("[FAST] Fast extraction module loaded - instant gold/silver calculations")

except ImportError as e:

    FAST_EXTRACT_AVAILABLE = False

    print(f"[FAST] Fast extraction not available: {e}")



# httpx imported for eBay API and Discord webhooks (already available)



# PriceCharting Database Integration for TCG and LEGO

try:

    from pricecharting_db import (

        lookup_product as pc_lookup, 

        get_db_stats as pc_get_stats,

        refresh_database as pc_refresh,

        start_background_refresh as pc_start_refresh

    )

    PRICECHARTING_AVAILABLE = True

    print("[PC] PriceCharting database module loaded")

except ImportError as e:

    PRICECHARTING_AVAILABLE = False

    print(f"[PC] PriceCharting database not available: {e}")

    print("[PC]   To enable: place pricecharting_db.py in this folder")

# Configure PriceCharting routes module
if PRICECHARTING_AVAILABLE:
    configure_pricecharting(
        pc_lookup=pc_lookup,
        pc_get_stats=pc_get_stats,
        pc_refresh=pc_refresh,
        PRICECHARTING_AVAILABLE=PRICECHARTING_AVAILABLE,
    )

# Configure Sellers routes module
configure_sellers(
    get_all_seller_profiles=get_all_seller_profiles,
    get_seller_profile_stats=get_seller_profile_stats,
    get_high_value_sellers=get_high_value_sellers,
    calculate_seller_score=calculate_seller_score,
    analyze_new_seller=analyze_new_seller,
    populate_seller_profiles_from_purchases=populate_seller_profiles_from_purchases,
    get_seller_profile=get_seller_profile,
    BLOCKED_SELLERS=BLOCKED_SELLERS,
    save_blocked_sellers=save_blocked_sellers,
    SELLER_SPAM_WINDOW=SELLER_SPAM_WINDOW,
    SELLER_SPAM_THRESHOLD=SELLER_SPAM_THRESHOLD,
)

# Bricklink API for Designer Program sets (910xxx)

try:

    from bricklink_api import lookup_set as bricklink_lookup, is_available as bricklink_available

    BRICKLINK_AVAILABLE = bricklink_available()

    if BRICKLINK_AVAILABLE:

        print("[BRICKLINK] API configured for Designer Program sets")

    else:

        print("[BRICKLINK] API not configured (add credentials to .env)")

except Exception as e:

    BRICKLINK_AVAILABLE = False

    print(f"[BRICKLINK] Module not available: {e}")



# ============================================================

# LOGGING SETUP

# ============================================================

logging.basicConfig(

    level=logging.INFO,

    format='%(asctime)s [%(levelname)s] %(message)s',

    datefmt='%H:%M:%S'

)

logger = logging.getLogger(__name__)




# ============================================================
# LIFESPAN (replaces deprecated on_event handlers)
# ============================================================

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Modern lifespan handler replacing deprecated on_event"""
    # === STARTUP ===
    global IN_FLIGHT_LOCK

    logger.info("=" * 60)
    logger.info("Claude Proxy v3 - Optimized Starting...")
    logger.info("=" * 60)

    # FIX: Initialize asyncio Lock here (not at module level) to avoid loop issues
    IN_FLIGHT_LOCK = asyncio.Lock()
    logger.info("[INIT] Asyncio Lock initialized")

    # FIX: Create shared HTTP client for connection pooling
    app_instance.state.http_client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)
    )
    logger.info("[INIT] HTTP client pool initialized")

    # Import DEV_MODE setting
    from config import DEV_MODE

    # Clear cache on startup in dev mode to avoid stale data issues
    if DEV_MODE:
        cleared = cache.clear()
        logger.info(f"[DEV_MODE] Cleared cache on startup ({cleared} entries)")
        logger.info("[DEV_MODE] Short cache TTLs active (30-60 seconds)")

    # Force initial spot price fetch
    logger.info("Fetching initial spot prices...")
    fetch_spot_prices()

    # Log current prices to verify
    prices = get_spot_prices()
    logger.info(f"Gold: ${prices.get('gold_oz', 0):.2f}/oz | Silver: ${prices.get('silver_oz', 0):.2f}/oz | Source: {prices.get('source', 'unknown')}")

    # Start background spot price updates (every 15 minutes)
    start_spot_updates(interval_minutes=15)

    # Start cache cleanup (every 60 seconds)
    start_cache_cleanup(interval=60)

    # Log database path
    logger.info(f"[DB] Database path: {db.path}")
    db_info = get_db_debug_info()
    logger.info(f"[DB] Listings: {db_info.get('listings_count', 0)} | Patterns: {db_info.get('keyword_patterns_count', 0)}")

    # Initialize PriceCharting database
    if PRICECHARTING_AVAILABLE:
        try:
            stats = pc_get_stats()
            if stats.get('total_products', 0) > 0:
                logger.info(f"[PC] Database loaded: {stats['total_products']:,} products")
                for cat, count in stats.get('by_category', {}).items():
                    logger.info(f"[PC]   {cat}: {count:,}")
            else:
                logger.info("[PC] Database empty - run refresh to download prices")
                logger.info("[PC] Visit http://localhost:8000/pc/refresh to download")

            # Start background refresh (every 24 hours)
            pc_start_refresh(24)  # positional arg to avoid keyword issues
        except Exception as e:
            logger.error(f"[PC] Initialization error: {e}")

    # Start Keepa deals monitor
    # DISABLED: Using dedicated KeepaTracker project on port 8001 instead
    # This prevents duplicate token consumption from same API key
    KEEPA_MONITOR_ENABLED = False  # Set to True to enable Keepa in ClaudeProxyV3
    if KEEPA_AVAILABLE and KEEPA_MONITOR_ENABLED:
        try:
            asyncio.create_task(start_deals_monitor(
                csv_path="asin-tracker-tasks-export.csv",
                check_interval=300,  # 5 minutes
                enable_analysis=True,  # Full analysis with flip scoring
                min_flip_score=50,  # Only alert if score >= 50
                enable_brand_monitoring=True,  # Check deals from tracked brands
            ))
            logger.info("[KEEPA] Deals monitor auto-started (every 5 min, analysis enabled)")
        except Exception as e:
            logger.error(f"[KEEPA] Failed to start monitor: {e}")
    elif KEEPA_AVAILABLE:
        logger.info("[KEEPA] Monitor DISABLED - using dedicated KeepaTracker on port 8001")

    # Auto-start eBay poller with FULL ANALYSIS (analyzes + alerts, also tracks for race comparison)
    if EBAY_POLLER_AVAILABLE and EBAY_POLLER_ENABLED:
        try:
            # Start polling for gold and silver with analysis callback
            poll_categories = ["gold", "silver"]
            asyncio.create_task(ebay_start_polling(poll_categories, callback=race_callback))
            logger.info(f"[API] eBay Direct API poller auto-started for: {poll_categories} (full analysis + Discord alerts)")
        except Exception as e:
            logger.error(f"[API] Failed to start eBay poller: {e}")

    logger.info(f"Server ready at http://{HOST}:{PORT}")
    logger.info("=" * 60)

    yield  # App runs here

    # === SHUTDOWN ===
    # Stop Keepa monitor
    if KEEPA_AVAILABLE:
        try:
            await stop_monitor()
            logger.info("[SHUTDOWN] Keepa monitor stopped")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Error stopping Keepa monitor: {e}")

    # FIX: Close HTTP client pool
    if hasattr(app_instance.state, 'http_client'):
        await app_instance.state.http_client.aclose()
        logger.info("[SHUTDOWN] HTTP client pool closed")

# ============================================================

# FASTAPI APP

# ============================================================

app = FastAPI(
    title="Claude Proxy v3 - Optimized",
    description="eBay arbitrage analyzer with async image fetching and smart caching",
    lifespan=lifespan
)

# Favicon route to prevent 404 errors
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Include analysis router (main /match_mydata endpoint)
# NOTE: Router included but routes won't work until configure_analysis() is called
app.include_router(analysis_router)
app.include_router(ebay_router)
app.include_router(pricecharting_router)
app.include_router(sellers_router)
app.include_router(dashboard_router)
app.include_router(keepa_router)
app.include_router(ebay_race_router)

# Claude client - using AsyncAnthropic for parallel request processing

client = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)



# OpenAI client - used for ALL Tier 1 analysis (GPT-4o-mini) and Tier 2 verification

openai_client = None

if OPENAI_API_KEY:

    try:

        from openai import AsyncOpenAI

        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        print(f"[INIT] OpenAI client initialized (GPT-4o-mini for ALL Tier 1, {OPENAI_TIER2_MODEL} for Tier 2)")

    except ImportError:

        print("[INIT] WARNING: openai package not installed. Run: pip install openai")

        print("[INIT] All categories will fall back to Haiku")



# Model selection for Tier 1 (category-aware)

# Gold/Silver: GPT-4o (smarter, better at weight estimation and scale reading)

# Other categories: GPT-4o-mini (cheaper, still good for TCG/LEGO/videogames)

TIER1_MODEL_GOLD_SILVER = "gpt-4o-mini"  # Mini for Tier 1 (cheaper), Tier 2 uses gpt-4o for verification

TIER1_MODEL_DEFAULT = "gpt-4o-mini"  # Mini for other categories

TIER1_MODEL_FALLBACK = MODEL_FAST   # Haiku fallback if OpenAI fails



# ============================================================

# STATE MANAGEMENT

# ============================================================

ENABLED = True  # Start enabled for testing

DEBUG_MODE = False

QUEUE_MODE = False  # Queue mode OFF - auto-analyze immediately

# eBay Direct API Poller toggle - set to False to disable
EBAY_POLLER_ENABLED = True  # RE-ENABLED - using unified adapter with proper image fetching



# Queue for manual review mode

LISTING_QUEUE: Dict[str, Dict] = {}



# In-flight request tracking - prevents duplicate processing

# Key: (title, price) -> asyncio.Event that signals when processing is complete

IN_FLIGHT: Dict[str, asyncio.Event] = {}

IN_FLIGHT_RESULTS: Dict[str, tuple] = {}  # (result, html)

IN_FLIGHT_LOCK = None  # FIX: Initialize in startup_event to avoid loop issues



# Concurrency controls - allow parallel processing

# Semaphore limits concurrent AI API calls to prevent rate limiting

MAX_CONCURRENT_AI_CALLS = 10  # Allow 10 parallel AI calls

AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI_CALLS)



# Stats tracking

STATS = {

    "total_requests": 0,

    "api_calls": 0,

    "skipped": 0,

    "buy_count": 0,

    "pass_count": 0,

    "research_count": 0,

    "cache_hits": 0,

    "session_cost": 0.0,

    "session_start": datetime.now().isoformat(),

    "listings": {}  # Recent listings for dashboard

}

# ============================================================
# OPENAI HOURLY BUDGET LIMITER
# ============================================================
OPENAI_HOURLY_BUDGET = 10.0  # Max $10/hour spend on OpenAI
OPENAI_HOURLY_TRACKER = {
    "hour_start": datetime.now(),
    "hour_cost": 0.0,
    "calls_this_hour": 0,
    "budget_exceeded_count": 0,
}

def check_openai_budget(estimated_cost: float = 0.02) -> bool:
    """
    Check if we're within hourly OpenAI budget.
    Returns True if OK to proceed, False if budget exceeded.
    """
    global OPENAI_HOURLY_TRACKER

    now = datetime.now()
    hour_elapsed = (now - OPENAI_HOURLY_TRACKER["hour_start"]).total_seconds() / 3600

    # Reset counter if new hour
    if hour_elapsed >= 1.0:
        logger.info(f"[BUDGET] Hour reset - spent ${OPENAI_HOURLY_TRACKER['hour_cost']:.2f} in {OPENAI_HOURLY_TRACKER['calls_this_hour']} calls")
        OPENAI_HOURLY_TRACKER["hour_start"] = now
        OPENAI_HOURLY_TRACKER["hour_cost"] = 0.0
        OPENAI_HOURLY_TRACKER["calls_this_hour"] = 0

    # Check if adding this call would exceed budget
    if OPENAI_HOURLY_TRACKER["hour_cost"] + estimated_cost > OPENAI_HOURLY_BUDGET:
        OPENAI_HOURLY_TRACKER["budget_exceeded_count"] += 1
        remaining_mins = int((1.0 - hour_elapsed) * 60)
        logger.warning(f"[BUDGET] EXCEEDED: ${OPENAI_HOURLY_TRACKER['hour_cost']:.2f}/${OPENAI_HOURLY_BUDGET:.2f} - skipping AI call ({remaining_mins}min until reset)")
        return False

    return True

def record_openai_cost(cost: float):
    """Record an OpenAI API call cost."""
    global OPENAI_HOURLY_TRACKER
    OPENAI_HOURLY_TRACKER["hour_cost"] += cost
    OPENAI_HOURLY_TRACKER["calls_this_hour"] += 1

def get_openai_budget_status() -> dict:
    """Get current budget status for dashboard."""
    now = datetime.now()
    hour_elapsed = (now - OPENAI_HOURLY_TRACKER["hour_start"]).total_seconds() / 3600
    remaining_mins = max(0, int((1.0 - hour_elapsed) * 60))

    return {
        "hourly_budget": OPENAI_HOURLY_BUDGET,
        "hour_cost": OPENAI_HOURLY_TRACKER["hour_cost"],
        "remaining": OPENAI_HOURLY_BUDGET - OPENAI_HOURLY_TRACKER["hour_cost"],
        "calls_this_hour": OPENAI_HOURLY_TRACKER["calls_this_hour"],
        "minutes_until_reset": remaining_mins,
        "budget_exceeded_count": OPENAI_HOURLY_TRACKER["budget_exceeded_count"],
    }


# NOTE: Spam detection functions imported from utils.spam_detection

# ============================================================
# CONFIGURE PIPELINE MODULES
# ============================================================
# Configure validation module with rate constants
configure_validation(
    get_spot_prices=get_spot_prices,
    spot_prices=SPOT_PRICES,
    gold_sell_rate=GOLD_SELL_RATE,
    gold_max_buy_rate=GOLD_MAX_BUY_RATE,
    silver_sell_rate=SILVER_SELL_RATE,
    silver_max_buy_rate=SILVER_MAX_BUY_RATE,
)


# ============================================================
# RECENTLY EVALUATED ITEMS - prevents duplicate processing
# ============================================================
RECENTLY_EVALUATED: Dict[str, Dict] = {}  # {item_key: {'timestamp': float, 'result': dict}}
RECENTLY_EVALUATED_WINDOW = 600  # 10 minutes - don't re-evaluate same item within this window

def get_evaluated_item_key(title: str, price) -> str:
    """Create a unique key for an item based on title and price."""
    # Normalize title: lowercase, strip whitespace, replace + with space
    normalized = title[:80].lower().strip().replace('+', ' ').replace('%20', ' ')
    # Convert price to float if it's a string
    try:
        price_float = float(str(price).replace('$', '').replace(',', '').strip())
    except (ValueError, TypeError):
        price_float = 0.0
    return f"{normalized}_{price_float:.2f}"

def check_recently_evaluated(title: str, price) -> Optional[Dict]:
    """
    Check if item was recently evaluated.
    Returns cached result if found, None otherwise.
    """
    import time as _time_module
    current_time = _time_module.time()
    item_key = get_evaluated_item_key(title, price)

    # Clean expired entries
    expired = [k for k, v in RECENTLY_EVALUATED.items()
               if current_time - v['timestamp'] > RECENTLY_EVALUATED_WINDOW]
    for k in expired:
        del RECENTLY_EVALUATED[k]

    # Check if this item was recently evaluated
    if item_key in RECENTLY_EVALUATED:
        cached = RECENTLY_EVALUATED[item_key]
        age = current_time - cached['timestamp']
        logger.info(f"[DEDUP] Found recent evaluation ({age:.0f}s ago): {title[:40]}...")
        return cached['result']

    return None

def mark_as_evaluated(title: str, price, result: Dict):
    """Mark an item as evaluated with its result."""
    import time as _time_module
    item_key = get_evaluated_item_key(title, price)
    RECENTLY_EVALUATED[item_key] = {
        'timestamp': _time_module.time(),
        'result': result
    }


# ============================================================

# EBAY API LOOKUP

# ============================================================

async def lookup_ebay_item(title: str, price: float = None) -> Optional[str]:

    """

    Look up an eBay item by title using the Finding API.

    Matches exact title and list price (not including shipping).

    Returns the viewItemURL if found, None otherwise.

    """

    if not EBAY_APP_ID:

        logger.debug("[EBAY] No App ID configured, skipping lookup")

        return None

    

    try:

        search_title = title.strip()

        

        api_url = "https://svcs.ebay.com/services/search/FindingService/v1"

        params = {

            "OPERATION-NAME": "findItemsByKeywords",

            "SERVICE-VERSION": "1.0.0",

            "SECURITY-APPNAME": EBAY_APP_ID,

            "RESPONSE-DATA-FORMAT": "JSON",

            "REST-PAYLOAD": "",

            "keywords": search_title,

            "paginationInput.entriesPerPage": "3",

            "sortOrder": "StartTimeNewest"

        }

        

        # FIX: Use shared HTTP client if available (connection pooling)

        if hasattr(app, 'state') and hasattr(app.state, 'http_client'):

            response = await app.state.http_client.get(api_url, params=params, timeout=5.0)

        else:

            async with httpx.AsyncClient(timeout=5.0) as http_client:

                response = await http_client.get(api_url, params=params)

        

        if response.status_code != 200:

            logger.warning(f"[EBAY] API returned {response.status_code}")

            return None

        

        data = response.json()

        search_result = data.get("findItemsByKeywordsResponse", [{}])[0]

        

        if search_result.get("ack", [None])[0] != "Success":

            return None

        

        items = search_result.get("searchResult", [{}])[0].get("item", [])

        if not items:

            return None

        

        # Find best match by title and list price
        from urllib.parse import unquote

        for item in items:

            item_title = item.get("title", [""])[0]

            view_url = item.get("viewItemURL", [None])[0]

            item_id = item.get("itemId", [None])[0]

            

            # Get list price (item price, not including shipping)

            selling_status = item.get("sellingStatus", [{}])[0]

            current_price = selling_status.get("currentPrice", [{}])[0]

            list_price = float(current_price.get("__value__", "0"))

            
            # Normalize titles for comparison (handle URL encoding from uBuyFirst)
            search_title_clean = unquote(title.replace('+', ' ')).strip().lower()
            item_title_clean = item_title.strip().lower()
            
            # Check title match (exact or contained)
            title_match = (search_title_clean == item_title_clean or 
                          search_title_clean in item_title_clean or
                          item_title_clean in search_title_clean)

            if not title_match:

                continue

            

            # FIX: Check price match only if price is provided (within $0.02)

            if price is not None:

                if abs(list_price - price) < 0.02:

                    logger.info(f"[EBAY] [PASS] …EXACT: {item_id} @ ${list_price:.2f}")

                    return view_url

                

                # Title matched but price didn't - still return it

                logger.info(f"[EBAY] [PASS] …Title match: {item_id} @ ${list_price:.2f}")

                return view_url

            

            # No exact match - return first result

            logger.info(f"[EBAY] No exact match, using first result")

            return items[0].get("viewItemURL", [None])[0]

            

    except Exception as e:

        logger.error(f"[EBAY] Lookup error: {e}")

        return None




async def lookup_ebay_item_by_seller(title: str, seller_name: str, price: float = None) -> Optional[str]:
    """
    Look up an eBay item by seller name, title, and price.
    Uses Browse API (direct API) with seller filter - more reliable than Finding API.
    Returns the direct item URL (ebay.com/itm/ITEM_ID) if found, None otherwise.
    """
    if not seller_name:
        logger.debug("[EBAY] No seller name provided, falling back to title lookup")
        return await lookup_ebay_item(title, price)

    try:
        from urllib.parse import unquote
        from ebay_poller import get_oauth_token, browse_api_available, BROWSE_API_URL

        # Clean up seller name and title (remove URL encoding)
        clean_seller = unquote(seller_name.replace('+', ' ')).strip().lower()
        clean_title = unquote(title.replace('+', ' ')).strip()

        logger.info(f"[EBAY] Looking up item by seller '{clean_seller}': {clean_title[:50]}...")

        # TRY BROWSE API FIRST (more reliable - Finding API often returns 500)
        if browse_api_available():
            token = await get_oauth_token()
            if token:
                logger.info(f"[EBAY] Using Browse API with seller filter...")

                # Build filter with seller filter - format: sellers:{seller_id}
                filters = [
                    "buyingOptions:{FIXED_PRICE}",
                    "itemLocationCountry:US",
                    f"sellers:{{{clean_seller}}}"
                ]

                # Add price filter if price is known (wider range for better matching)
                if price and price > 0:
                    price_min = price * 0.85
                    price_max = price * 1.15
                    filters.append(f"price:[{price_min:.2f}..{price_max:.2f}],priceCurrency:USD")

                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                }

                # Use first few words of title as keywords
                keywords = ' '.join(clean_title.split()[:6])

                params = {
                    "q": keywords,
                    "sort": "newlyListed",
                    "limit": "25",
                    "filter": ",".join(filters),
                }

                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(BROWSE_API_URL, headers=headers, params=params)

                        if response.status_code == 200:
                            data = response.json()
                            items = data.get("itemSummaries", [])

                            if items:
                                logger.info(f"[EBAY] Browse API found {len(items)} items from seller '{clean_seller}'")

                                # Find exact or best title/price match
                                clean_title_lower = clean_title.lower()
                                best_match = None
                                best_score = 0

                                for item in items:
                                    item_title = item.get("title", "")
                                    item_id = item.get("itemId", "")
                                    item_url = item.get("itemWebUrl", "")

                                    # Get price
                                    item_price = 0
                                    price_info = item.get("price", {})
                                    try:
                                        item_price = float(price_info.get("value", 0))
                                    except:
                                        pass

                                    # Calculate title similarity score
                                    item_title_lower = item_title.lower()
                                    title_words = set(clean_title_lower.split())
                                    item_words = set(item_title_lower.split())
                                    word_overlap = len(title_words & item_words)
                                    score = word_overlap

                                    # Boost score for exact price match
                                    if price and item_price > 0:
                                        price_diff = abs(item_price - price)
                                        if price_diff < 1.0:  # Exact price match
                                            score += 10
                                        elif price_diff < price * 0.05:  # Within 5%
                                            score += 5

                                    if score > best_score:
                                        best_score = score
                                        best_match = {
                                            "id": item_id,
                                            "url": item_url,
                                            "title": item_title,
                                            "price": item_price
                                        }

                                if best_match:
                                    logger.info(f"[EBAY] MATCH via Browse API: {best_match['id']} @ ${best_match['price']:.2f} - {best_match['title'][:50]}")
                                    return best_match["url"]
                            else:
                                logger.info(f"[EBAY] Browse API: No items found for seller '{clean_seller}' with keywords")
                        else:
                            logger.warning(f"[EBAY] Browse API returned {response.status_code}")

                except Exception as e:
                    logger.warning(f"[EBAY] Browse API error: {e}")

        # FALLBACK: Try Finding API (often returns 500 but worth trying)
        if EBAY_APP_ID:
            logger.debug("[EBAY] Trying Finding API as fallback...")
            api_url = "https://svcs.ebay.com/services/search/FindingService/v1"
            params = {
                "OPERATION-NAME": "findItemsAdvanced",
                "SERVICE-VERSION": "1.0.0",
                "SECURITY-APPNAME": EBAY_APP_ID,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "keywords": clean_title[:80],
                "itemFilter(0).name": "Seller",
                "itemFilter(0).value": clean_seller,
                "paginationInput.entriesPerPage": "10",
                "sortOrder": "StartTimeNewest"
            }

            try:
                async with httpx.AsyncClient(timeout=5.0) as http_client:
                    response = await http_client.get(api_url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    search_result = data.get("findItemsAdvancedResponse", [{}])[0]

                    if search_result.get("ack", [None])[0] == "Success":
                        items = search_result.get("searchResult", [{}])[0].get("item", [])
                        if items:
                            logger.info(f"[EBAY] Finding API found {len(items)} items from seller")
                            first_url = items[0].get("viewItemURL", [None])[0]
                            first_id = items[0].get("itemId", [None])[0]
                            if first_url:
                                logger.info(f"[EBAY] MATCH via Finding API: {first_id}")
                                return first_url
                else:
                    logger.debug(f"[EBAY] Finding API returned {response.status_code}")
            except Exception as e:
                logger.debug(f"[EBAY] Finding API error: {e}")

        return None

    except Exception as e:
        logger.error(f"[EBAY] Seller lookup error: {e}")
        return None



def get_ebay_search_url(title: str) -> str:

    """Fallback: Generate eBay search URL from title"""

    search_title = title.replace('+', ' ')[:80]

    encoded_title = urllib.parse.quote(search_title)

    return f"https://www.ebay.com/sch/i.html?_nkw={encoded_title}"





# ============================================================

# INSTANT PASS - Rule-Based (No AI Cost)

# ============================================================

def extract_weight_from_title(title: str) -> tuple:
    """
    Extract weight from title if explicitly stated.
    Returns (weight_grams, source) or (None, None) if not found.

    ONLY extracts clearly stated weights like "2.5g", "2.5 grams", "1/2 oz"
    Does NOT estimate - that's for AI to do.

    Conversions:
    - ozt (troy oz) = 31.1 grams (used for precious metals)
    - oz (avoirdupois) = 28.35 grams (standard oz)
    - dwt (pennyweight) = 1.555 grams

    Uses pre-compiled patterns for performance.
    """
    title_lower = title.lower()

    # Check for fractional troy oz first (e.g., "1/2 ozt", "1/4 troy oz")
    frac_ozt_match = FRACTION_OZT_PATTERN.search(title_lower)
    if frac_ozt_match:
        numerator = float(frac_ozt_match.group(1))
        denominator = float(frac_ozt_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            grams = oz_value * 31.1  # Troy oz
            return grams, "stated"

    # Check for fractional plain oz (e.g., "1/2 oz", "1/4 oz")
    frac_oz_match = FRACTION_OZ_PATTERN.search(title_lower)
    if frac_oz_match:
        numerator = float(frac_oz_match.group(1))
        denominator = float(frac_oz_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            # For precious metals (silver/gold coins/bullion), use troy oz (31.1g)
            # Check for silver/gold indicators in title
            is_precious_metal = any(kw in title_lower for kw in [
                '.999', '.925', '.900', '.800', 'silver', 'gold', 'platinum',
                'bullion', 'coin', 'bar', 'round', 'eagle', 'maple', 'libertad',
                'krugerrand', 'philharmonic', 'britannia', 'panda', 'kookaburra',
                'lunar', 'koala', 'kangaroo', 'buffalo', 'proof'
            ])
            if is_precious_metal:
                grams = oz_value * 31.1  # Troy oz for precious metals
            else:
                grams = oz_value * 28.35  # Avoirdupois oz for non-precious
            return grams, "stated"

    # Use pre-compiled patterns (ordered by specificity)
    for pattern in WEIGHT_PATTERNS:
        match = pattern.search(title_lower)
        if match:
            weight = float(match.group(1))
            matched_text = match.group(0).lower()

            # Convert to grams based on the MATCHED unit
            if 'dwt' in matched_text:
                weight *= 1.555  # pennyweight to grams
            elif 'ozt' in matched_text or 'oz.t' in matched_text or 'troy' in matched_text:
                weight *= 31.1  # troy oz to grams
            elif 'oz' in matched_text:
                weight *= 28.35  # avoirdupois oz to grams
            # 'g', 'gram', 'grams', 'gr' are already in grams

            return weight, "stated"

    return None, None





def extract_karat_from_title(title: str) -> int:

    """

    Extract karat from title. Returns karat number or None.

    Uses pre-compiled KARAT_PATTERNS for performance.

    """

    title_lower = title.lower()

    

    # Use pre-compiled patterns

    for pattern, karat in KARAT_PATTERNS:

        if pattern.search(title_lower):

            return karat

    

    return None





def check_instant_pass(title: str, price: any, category: str, data: dict) -> tuple:

    """

    Check if listing should be instantly passed without AI analysis.



    Returns:

        (reason, "PASS") if instant pass

        None if AI analysis needed

    """

    title_lower = title.lower()



    try:

        price_float = float(str(price).replace('$', '').replace(',', ''))

    except:

        price_float = 0



    # ============================================================

    # KEYWORD-BASED INSTANT PASS (All categories)

    # ============================================================

    for keyword in INSTANT_PASS_KEYWORDS:

        if keyword in title_lower:

            return (f"Title contains '{keyword}'", "PASS")


    # ============================================================
    # WEIGHTED STERLING CHECK (Title + Description)
    # "Sterling weighted" = cement/pitch filled, minimal actual silver
    # ============================================================
    if category == 'silver':
        description = str(data.get('description', '')).lower()
        combined_text = f"{title_lower} {description}"

        # Check for explicit "weighted" or "sterling weighted"
        if 'sterling weighted' in combined_text or 'weighted sterling' in combined_text:
            return ("WEIGHTED STERLING - cement/pitch filled, minimal silver content", "PASS")

        # Check for "weighted" in description even if not in title
        if 'weighted' in description and 'weighted' not in title_lower:
            return ("Description says WEIGHTED - cement/pitch filled, minimal silver content", "PASS")

        # Candlesticks are ALWAYS weighted unless explicitly solid
        if ('candlestick' in title_lower or 'candelabra' in title_lower) and 'solid' not in combined_text:
            # Don't instant pass, but flag for reduced weight calculation
            logger.info(f"[WEIGHTED] Candlestick detected - will apply weighted reduction")


    # ============================================================

    # GOLD/SILVER: Price vs Stated Weight Check

    # Only if weight is EXPLICITLY STATED in title

    # SKIP if item likely has non-metal weight (stones, pearls, etc.)

    # ============================================================

    if category in ['gold', 'silver']:

        stated_weight, weight_source = extract_weight_from_title(title)



        if stated_weight and weight_source == "stated":

            # CRITICAL: Skip instant pass for items where stated weight includes non-metal

            # These need AI analysis to properly deduct stone/pearl/component weight

            non_metal_indicators = [

                'pearl', 'diamond', 'stone', 'turquoise', 'jade', 'coral', 'opal',

                'amethyst', 'ruby', 'sapphire', 'emerald', 'garnet', 'onyx', 'topaz',

                'watch', 'movement', 'crystal',  # Watches have movement weight

                'cord', 'leather', 'silk', 'rubber', 'fabric',  # Cord necklaces

                'murano', 'glass', 'millefiori',  # Glass pendants

                'bead', 'beaded',  # Beaded jewelry is mostly beads

                'gemstone', 'gem', 'cttw', 'ctw',  # Gemstone indicators

                'cameo',  # Cameos are shell/coral/stone - deduct 3-5g for typical cameo

            ]



            has_non_metal = any(indicator in title_lower for indicator in non_metal_indicators)



            if has_non_metal:

                # Don't instant pass - let AI analyze and deduct properly

                logger.info(f"[INSTANT] Skipping weight check - title contains non-metal indicators: {title[:60]}...")

            else:

                spots = get_spot_prices()



                if category == 'gold':

                    karat = extract_karat_from_title(title)

                    if karat:

                        # Get rate for this karat

                        karat_key = f"{karat}K"

                        rate = spots.get(karat_key, spots.get('14K', 50))



                        melt_value = stated_weight * rate

                        max_buy = melt_value * 0.95  # 95% of melt



                        # If listing price > 95% of melt, check for best offer before instant PASS

                        if price_float > max_buy:

                            margin = max_buy - price_float

                            gap_percent = ((price_float - max_buy) / price_float) * 100 if price_float > 0 else 100

                            accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']



                            # If best offer available and within 10%, let AI analyze so we can suggest offer

                            if accepts_offers and gap_percent <= 10:

                                logger.info(f"[INSTANT] Skipping PASS - has best offer, gap only {gap_percent:.1f}%: {stated_weight}g {karat}K @ ${price_float:.0f}")

                                # Don't return - let AI process and best offer logic handle it

                            else:

                                logger.info(f"[INSTANT] PASS - overpriced: {stated_weight}g {karat}K @ ${price_float:.0f}")

                                return (f"OVERPRICED: {stated_weight}g {karat}K = ${melt_value:.0f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f} = ${margin:.0f} loss", "PASS")



                        # Don't instant BUY - let AI verify authenticity

                        logger.info(f"[INSTANT] Weight check OK: {stated_weight}g {karat}K @ ${price_float:.0f} - margin ${max_buy - price_float:.0f}")



                elif category == 'silver':

                    # Sterling silver

                    rate = spots.get('sterling', 0.89)

                    melt_value = stated_weight * rate

                    max_buy = melt_value * 0.75  # 75% of melt for silver



                    # Check for Native American jewelry (gets looser restrictions)

                    native_keywords = ['navajo', 'native american', 'zuni', 'hopi', 'squash blossom',

                                      'southwestern', 'turquoise', 'concho', 'old pawn']

                    is_native = any(kw in title_lower for kw in native_keywords)



                    if price_float > max_buy:

                        margin = max_buy - price_float

                        gap_percent = ((price_float - max_buy) / price_float) * 100 if price_float > 0 else 100

                        accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']



                        # Native American: allow 20% gap (collector value)

                        # Regular with best offer: allow 10% gap

                        max_gap = 20 if is_native else 10



                        if (accepts_offers or is_native) and gap_percent <= max_gap:

                            if is_native:

                                logger.info(f"[INSTANT] Skipping PASS - Native American jewelry, gap {gap_percent:.1f}%: {stated_weight}g @ ${price_float:.0f}")

                            else:

                                logger.info(f"[INSTANT] Skipping PASS - has best offer, gap only {gap_percent:.1f}%: {stated_weight}g @ ${price_float:.0f}")

                            # Don't return - let AI process

                        else:

                            logger.info(f"[INSTANT] PASS - silver overpriced: {stated_weight}g @ ${price_float:.0f}")

                            return (f"OVERPRICED: {stated_weight}g sterling = ${melt_value:.2f} melt, listing ${price_float:.0f} = loss", "PASS")



    # ============================================================

    # PRICE SANITY CHECK

    # ============================================================

    # Ultra-high prices unlikely to be arbitrage opportunities

    if price_float > 10000 and category in ['gold', 'silver']:

        return (f"Price ${price_float:.0f} too high for arbitrage", "PASS")



    # No instant pass - needs AI analysis

    return None





# ============================================================

# TRAINING DATA LOGGER

# ============================================================

def log_training_override(

    title: str,

    price: float,

    category: str,

    tier1_result: Dict,

    tier2_result: Dict,

    override_type: str,

    listing_data: Dict = None

):

    """

    Log Tier 1 -> Tier 2 override events for training analysis.

    

    Creates a JSONL file with:

    - Input context (title, price, category, listing data)

    - Tier 1 output (what Tier1 said)

    - Tier 2 output (what Sonnet corrected to)

    - Override reason

    

    This data can be used to:

    1. Identify patterns where Haiku fails

    2. Create fine-tuning examples

    3. Improve prompts based on common errors

    """

    try:

        training_record = {

            "timestamp": datetime.utcnow().isoformat(),

            "override_type": override_type,  # "BUY_TO_PASS", "BUY_TO_RESEARCH", "RESEARCH_TO_PASS", etc.

            

            # Input context

            "input": {

                "title": title,

                "price": price,

                "category": category,

                "listing_fields": {k: v for k, v in (listing_data or {}).items() 

                                  if k not in ['images', 'system_prompt', 'display_template']}

            },

            

            # Tier 1 (Haiku) output - what was WRONG

            "tier1_output": {

                "recommendation": tier1_result.get('Recommendation', 'Unknown'),

                "profit": tier1_result.get('Profit', tier1_result.get('Margin', 'N/A')),

                "confidence": tier1_result.get('confidence', 'N/A'),

                "reasoning": tier1_result.get('reasoning', '')[:500],

                "weight": tier1_result.get('goldweight', tier1_result.get('weight', 'N/A')),

                "market_price": tier1_result.get('marketprice', tier1_result.get('meltvalue', 'N/A')),

                "max_buy": tier1_result.get('maxBuy', 'N/A'),

            },

            

            # Tier 2 (Sonnet) output - what was CORRECT

            "tier2_output": {

                "recommendation": tier2_result.get('Recommendation', 'Unknown'),

                "profit": tier2_result.get('Profit', tier2_result.get('Margin', 'N/A')),

                "confidence": tier2_result.get('confidence', 'N/A'),

                "reasoning": tier2_result.get('reasoning', '')[:500],

                "tier2_reason": tier2_result.get('tier2_reason', ''),

                "tier2_override": tier2_result.get('tier2_override', False),

            },

            

            # Analysis of what went wrong

            "error_analysis": {

                "tier1_rec": tier1_result.get('Recommendation'),

                "tier2_rec": tier2_result.get('Recommendation'),

                "sanity_override": tier2_result.get('tier2_sanity_override', ''),

                "weight_correction": tier2_result.get('tier2_weight_correction', ''),

            }

        }

        

        # Append to JSONL file

        with open(TRAINING_LOG_PATH, 'a', encoding='utf-8') as f:

            f.write(json.dumps(training_record, ensure_ascii=False) + '\n')

        

        logger.info(f"[TRAINING] Logged override: {override_type} for '{title[:40]}...'")

        

    except Exception as e:

        logger.error(f"[TRAINING] Error logging override: {e}")





# ============================================================
# DISCORD WEBHOOK (Wrapper for utils.discord)
# ============================================================
# NOTE: Discord functionality moved to utils/discord.py
# This wrapper maintains backward compatibility with existing code

async def send_discord_alert(
    title: str,
    price: float,
    recommendation: str,
    category: str,
    profit: float = None,
    margin: str = None,
    reasoning: str = None,
    ebay_url: str = None,
    image_url: str = None,
    confidence: str = None,
    extra_data: dict = None,
    seller_info: dict = None,
    listing_info: dict = None
):
    """Wrapper for utils.discord.send_discord_alert - passes webhook URL automatically"""
    return await utils_send_discord_alert(
        webhook_url=DISCORD_WEBHOOK_URL,
        title=title,
        price=price,
        recommendation=recommendation,
        category=category,
        profit=profit,
        margin=margin,
        reasoning=reasoning,
        ebay_url=ebay_url,
        image_url=image_url,
        confidence=confidence,
        extra_data=extra_data,
        enable_tts=True,
        server_port=8000,
        seller_info=seller_info,
        listing_info=listing_info
    )





# ============================================================
# CONFIGURE TIER 2 MODULE
# ============================================================
# This must be after all helper functions are defined
configure_tier2(
    tier2_enabled=TIER2_ENABLED,
    tier2_provider=TIER2_PROVIDER,
    model_full=MODEL_FULL,
    openai_tier2_model=OPENAI_TIER2_MODEL,
    discord_webhook_url=DISCORD_WEBHOOK_URL,
    anthropic_client=client,
    openai_client=openai_client,
    stats=STATS,
    cost_per_call_sonnet=COST_PER_CALL_SONNET,
    cost_per_call_openai=COST_PER_CALL_OPENAI,
    cost_per_call_gpt4o=COST_PER_CALL_GPT4O,
    resize_for_tier2=IMAGES.resize_for_tier2,
    process_image_list=process_image_list,
    get_agent_prompt=get_agent_prompt,
    send_discord_alert=send_discord_alert,
    log_training_override=log_training_override,
    get_spot_prices=get_spot_prices,
    check_openai_budget=check_openai_budget,
    record_openai_cost=record_openai_cost,
    validate_and_fix_margin=validate_and_fix_margin,
)


# ============================================================

# STARTUP EVENTS

# ============================================================

# STARTUP EVENT MOVED TO LIFESPAN HANDLER ABOVE



# SHUTDOWN EVENT MOVED TO LIFESPAN HANDLER ABOVE



# ============================================================

# HELPER FUNCTIONS

# ============================================================

def format_listing_data(data: dict) -> str:

    """Format listing data for AI prompt"""

    lines = ["LISTING DATA:"]

    for key, value in data.items():

        if value and key != 'images':

            lines.append(f"- {key}: {value}")

    return "\n".join(lines)





def sanitize_json_response(text: str) -> str:

    """Clean up AI response for JSON parsing"""

    if text.startswith("```"):

        lines = text.split("\n")

        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    text = text.replace("```json", "").replace("```", "")

    

    replacements = {

        "'": "'", "'": "'", """: '"', """: '"',

        "x ": "-", "x ƒÆ’‚[PASS] ¢": "->", "x ¢": "x", "x ": "...", "\u00a0": " ",

    }

    for old, new in replacements.items():

        text = text.replace(old, new)



    # Try to extract JSON object if there's extra text before/after

    if text and '{' in text:

        start = text.find('{')

        end = text.rfind('}') + 1

        if start < end:

            text = text[start:end]



    # Try to parse - if it works, return as-is

    try:

        json.loads(text)

        return text.strip()

    except:

        # Only do aggressive ASCII cleanup if JSON parse fails

        text = text.encode('ascii', 'ignore').decode('ascii')

        text = " ".join(text.split())

        return text.strip()





def parse_reasoning(reasoning: str) -> dict:

    """Parse structured reasoning into components"""

    parts = {"detection": "", "calc": "", "decision": "", "concerns": "", "profit": "", "raw": reasoning}

    

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

            elif upper.startswith("PROFIT:"):

                parts["profit"] = section[7:].strip()

    

    return parts





def _trim_listings():

    """Keep only last 100 listings in memory"""

    if len(STATS["listings"]) > 100:

        sorted_ids = sorted(STATS["listings"].keys(), key=lambda x: STATS["listings"][x]["timestamp"])

        for old_id in sorted_ids[:-100]:

            del STATS["listings"][old_id]





def create_openai_response(result: dict) -> dict:

    """

    Wrap analysis result in OpenAI chat completion format.

    This is REQUIRED for uBuyFirst columns to populate.

    uBuyFirst parses this JSON and extracts fields for AI columns.

    """

    # Convert result dict to JSON string (this is what goes in 'content')

    content_json = json.dumps(result)

    

    return {

        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",

        "object": "chat.completion",

        "created": int(datetime.now().timestamp()),

        "model": MODEL_FAST,

        "choices": [{

            "index": 0,

            "message": {

                "role": "assistant",

                "content": content_json

            },

            "finish_reason": "stop"

        }],

        "usage": {

            "prompt_tokens": 100,

            "completion_tokens": 50,

            "total_tokens": 150

        }

    }





# ============================================================

# PRICECHARTING INTEGRATION FUNCTIONS

# ============================================================



def get_pricecharting_context(title: str, total_price: float, category: str, upc: str = None, quantity: int = 1, condition: str = None) -> tuple:

    """

    Get PriceCharting data for TCG/LEGO/Video Games listings

    Tries UPC first (most accurate), then falls back to title search.

    Handles multi-quantity listings by calculating per-item price.

    Handles multi-set LEGO lots by looking up each set and summing values.

    Applies language discounts for Korean/Japanese products.

    Uses condition to select appropriate price tier (new/cib/loose).

    Returns: (pc_result dict, context_string for prompt)

    """

    if not PRICECHARTING_AVAILABLE:

        return None, ""

    

    if category not in ["tcg", "lego", "videogames"]:

        return None, ""

    

    title_lower = title.lower()

    

    # === MULTI-SET LEGO LOT DETECTION ===

    # Look for multiple set numbers in the title (e.g., "40803 and 40804" or "75192, 75252")

    if category == "lego":

        # Find all 4-6 digit numbers that look like LEGO set numbers
        # Include 910xxx Bricklink Designer Program sets

        set_numbers = re.findall(r'\b((?:4|5|6|7|8)\d{4}|91\d{4})\b', title)

        # Remove duplicates while preserving order

        set_numbers = list(dict.fromkeys(set_numbers))

        

        if len(set_numbers) >= 2:

            logger.info(f"[PC] MULTI-SET LOT DETECTED: {set_numbers}")

            

            # Look up each set

            total_market = 0

            set_details = []

            all_found = True

            

            for set_num in set_numbers:

                # Try Bricklink first for ALL sets, then fall back to PriceCharting
                set_result = None
                if BRICKLINK_AVAILABLE:
                    logger.info(f"[BRICKLINK] Looking up set {set_num}")
                    bl_result = bricklink_lookup(set_num, listing_price=0, condition="new")
                    if bl_result and bl_result.get('found') and bl_result.get('market_price', 0) > 0:
                        set_result = {
                            'found': True,
                            'product_name': bl_result.get('name', f'Set {set_num}'),
                            'market_price': bl_result.get('market_price', 0),
                            'buy_target': bl_result.get('buy_target', 0),
                            'source': 'bricklink'
                        }

                # Fall back to PriceCharting if Bricklink didn't find it
                if not set_result:
                    set_result = pc_lookup(f"LEGO {set_num}", category="lego", listing_price=0)

                if set_result and set_result.get('found') and set_result.get('market_price', 0) > 0:

                    market = set_result.get('market_price', 0)

                    name = set_result.get('product_name', f'Set {set_num}')

                    total_market += market

                    set_details.append({

                        'set_number': set_num,

                        'name': name,

                        'market_price': market

                    })

                    logger.info(f"[PC]   Set {set_num}: {name} = ${market:.0f}")

                else:

                    logger.warning(f"[PC]   Set {set_num}: NOT FOUND")

                    all_found = False

            

            if set_details:

                # Calculate combined values using category threshold
                threshold = get_category_threshold('lego')
                total_buy_target = total_market * threshold

                total_margin = total_buy_target - total_price

                

                # Build combined result

                combined_result = {

                    'found': True,

                    'product_name': f"LOT: {', '.join([d['name'][:30] for d in set_details])}",

                    'market_price': total_market,

                    'buy_target': total_buy_target,

                    'margin': total_margin,

                    'confidence': 'High' if all_found else 'Medium',

                    'multi_set': True,

                    'set_count': len(set_details),

                    'set_details': set_details,

                    'all_sets_found': all_found

                }

                

                # Build context string

                set_breakdown = "\n".join([f"  - {d['set_number']}: {d['name']} = ${d['market_price']:.0f}" for d in set_details])

                if not all_found:

                    set_breakdown += f"\n  - {len(set_numbers) - len(set_details)} set(s) NOT FOUND in database"

                

                context = f"""

=== PRICECHARTING DATA (MULTI-SET LOT) ===

Sets Found: {len(set_details)}/{len(set_numbers)}

{set_breakdown}



COMBINED VALUES:

Total Market Value: ${total_market:.0f}

Max Buy ({int(threshold*100)}%): ${total_buy_target:.0f}

Listing Price: ${total_price:.0f}

Combined Margin: ${total_margin:+.0f}



{"NOTE: Not all sets found - be conservative with pricing" if not all_found else "All sets verified in database"}

=== END PRICECHARTING DATA ===

"""

                logger.info(f"[PC] MULTI-SET TOTAL: ${total_market:.0f} market, ${total_buy_target:.0f} max buy, ${total_margin:+.0f} margin")

                return combined_result, context

            else:

                # No sets found

                logger.warning(f"[PC] Multi-set lot but NO sets found in database")

                return None, f"""

=== PRICECHARTING DATA ===

MULTI-SET LOT DETECTED: {set_numbers}

WARNING: None of these sets found in database.

Manual pricing research required.

=== END ===

"""

    

    # Handle quantity - calculate per-item price

    quantity = max(1, quantity)  # Ensure at least 1

    per_item_price = total_price / quantity

    

    if quantity > 1:

        logger.info(f"[PC] Multi-quantity listing: {quantity}x @ ${total_price:.2f} total = ${per_item_price:.2f} each")

    

    # === LANGUAGE DETECTION FOR TCG ===

    title_lower = title.lower()

    detected_language = "english"  # Default

    language_discount = 1.0  # No discount for English

    

    if category == "tcg":

        # === UNSUPPORTED TCG BRANDS - Skip PriceCharting lookup ===

        # These brands are not in our pricing database

        unsupported_tcg = ['marvel', 'upper deck', 'dc', 'dragon ball', 'dbz', 'naruto', 'my hero academia', 

                          'weiss schwarz', 'cardfight vanguard', 'flesh and blood', 'metazoo', 'star wars',

                          'digimon', 'union arena', 'grand archive', 'sorcery']

        if any(brand in title_lower for brand in unsupported_tcg):

            detected_brand = next((b for b in unsupported_tcg if b in title_lower), 'unknown')

            logger.info(f"[PC] UNSUPPORTED TCG: {detected_brand.upper()} - skipping PriceCharting lookup")

            return None, f"""

=== UNSUPPORTED TCG BRAND ===

Detected: {detected_brand.upper()}

This brand is NOT in our pricing database.

You must manually research pricing on eBay sold listings.

=== END ===

"""

        

        if any(word in title_lower for word in ['korean', 'korea', 'kor ', ' kor']):

            detected_language = "korean"

            language_discount = 0.25  # Korean = 25% of English value (very aggressive - Korean is cheap!)

            logger.info(f"[PC] KOREAN detected - applying 75% discount (Korean products sell for ~25% of English)")

        elif any(word in title_lower for word in ['japanese', 'japan', 'jpn', ' jp ', 'japanese version']):

            detected_language = "japanese"

            language_discount = 0.45  # Japanese = 45% of English value

            logger.info(f"[PC] JAPANESE detected - applying 55% discount")

        elif any(word in title_lower for word in ['chinese', 'china', 'simplified', 'traditional']):

            detected_language = "chinese"

            language_discount = 0.20  # Chinese = 20% of English value (lowest demand)

            logger.info(f"[PC] CHINESE detected - applying 80% discount")

    

    try:

        # Map our category names to PC database categories

        pc_category = category

        if category == "tcg":

            # Will auto-detect pokemon/mtg/yugioh from title

            pc_category = None  

        

        # === FOR KOREAN/JAPANESE: Try to match regional set names first ===

        search_title = title

        if category == "tcg" and detected_language in ["korean", "japanese"]:

            # Map English set names to Japanese/Korean equivalents

            set_name_map = {

                'evolving skies': 'eevee heroes',

                'fusion strike': 'fusion arts',

                'brilliant stars': 'star birth',

                'lost origin': 'lost abyss',

                'silver tempest': 'paradigm trigger',

                'crown zenith': 'vstar universe',

                'obsidian flames': 'ruler of the black flame',

                'paldea evolved': 'snow hazard clay burst',

                '151': '151',  # Same name

                'paradox rift': 'ancient roar future flash',

                'temporal forces': 'wild force cyber judge',

            }

            

            title_lower = title.lower()

            for eng_name, jp_name in set_name_map.items():

                if eng_name in title_lower and jp_name not in title_lower:

                    # Replace English name with Japanese name for better matching

                    search_title = title_lower.replace(eng_name, jp_name)

                    logger.info(f"[PC] Remapped set name: '{eng_name}' ƒÆ’‚[PASS] ¢[PASS] ¢'{jp_name}' for {detected_language} search")

                    break

        

        # Use per-item price for margin calculation
        # Check for Bricklink Designer Program sets (910xxx) first
        pc_result = None
        bricklink_used = False

        if category == "lego" and BRICKLINK_AVAILABLE:
            # Extract set number from title - try ALL set numbers, not just Designer Program
            # Common LEGO set number patterns: 4-6 digits
            set_match = re.search(r'\b(\d{4,6})\b', title)
            if set_match:
                set_num = set_match.group(1)
                # Validate it looks like a real LEGO set number (not a year like 2023)
                is_year = 1990 <= int(set_num) <= 2030
                is_valid_set = len(set_num) >= 4 and not is_year

                if is_valid_set:
                    logger.info(f"[BRICKLINK] Attempting lookup for set #{set_num}")
                    bl_result = bricklink_lookup(set_num, listing_price=per_item_price, condition=condition or "new")
                    if bl_result and bl_result.get('found') and bl_result.get('market_price', 0) > 0:
                        pc_result = {
                            'found': True,
                            'product_name': f"{bl_result.get('name', '')} #{set_num}",
                            'product_id': set_num,
                            'console_name': 'Bricklink',
                            'category': 'lego',
                            'market_price': bl_result.get('market_price', 0),
                            'buy_target': bl_result.get('buy_target', 0),
                            'margin': bl_result.get('profit', 0),
                            'confidence': bl_result.get('confidence', 'Medium'),
                            'source': 'bricklink',
                            'new_price': bl_result.get('market_price', 0),
                            'cib_price': bl_result.get('market_price', 0) * 0.85,
                            'loose_price': bl_result.get('market_price', 0) * 0.70,
                        }
                        bricklink_used = True
                        logger.info(f"[BRICKLINK] Found: {pc_result['product_name']} @ ${pc_result['market_price']:.2f}")
                    else:
                        logger.info(f"[BRICKLINK] No data for #{set_num}, falling back to PriceCharting")

        # Fall back to PriceCharting if Bricklink didn't find it
        if not pc_result:
            pc_result = pc_lookup(search_title, category=pc_category, listing_price=per_item_price, upc=upc)

        

        # === CONDITION-BASED PRICING (Critical for Video Games!) ===

        # PriceCharting returns: new_price, cib_price, loose_price

        # We must use the correct price based on the eBay listing condition

        if pc_result and pc_result.get('found') and condition:

            condition_lower = str(condition).lower()

            new_price = pc_result.get('new_price', 0) or 0

            cib_price = pc_result.get('cib_price', 0) or 0

            loose_price = pc_result.get('loose_price', 0) or 0

            original_market = pc_result.get('market_price', 0)

            

            # Determine which price tier to use based on condition

            # eBay condition values: New, Like New, Very Good, Good, Acceptable, For Parts

            condition_price = None

            condition_tier = None

            

            if any(term in condition_lower for term in ['new', 'sealed', 'factory sealed', 'brand new', 'unopened']):

                # New/Sealed items - use new price

                condition_price = new_price if new_price > 0 else cib_price

                condition_tier = 'New'

            elif any(term in condition_lower for term in ['like new', 'complete', 'cib', 'mint', 'excellent']):

                # Complete/CIB items - use CIB price

                condition_price = cib_price if cib_price > 0 else loose_price

                condition_tier = 'CIB'

            elif any(term in condition_lower for term in ['very good', 'good', 'acceptable', 'used', 'loose', 'cart', 'disc only']):

                # Used/Loose items - use loose price

                condition_price = loose_price if loose_price > 0 else cib_price

                condition_tier = 'Loose'

            else:

                # Unknown condition - use the most conservative (lowest) available price

                if loose_price > 0:

                    condition_price = loose_price

                    condition_tier = 'Loose (default)'

                elif cib_price > 0:

                    condition_price = cib_price

                    condition_tier = 'CIB (default)'

                else:

                    condition_price = new_price

                    condition_tier = 'New (default)'

            

            # Only update if we determined a condition-appropriate price

            if condition_price and condition_price > 0:

                old_market = pc_result.get('market_price', 0)
                cat_threshold = get_category_threshold(category)

                pc_result['market_price'] = condition_price

                pc_result['buy_target'] = condition_price * cat_threshold

                pc_result['margin'] = pc_result['buy_target'] - per_item_price

                pc_result['condition_tier'] = condition_tier

                pc_result['price_breakdown'] = f"New: ${new_price:.0f} | CIB: ${cib_price:.0f} | Loose: ${loose_price:.0f}"

                

                if old_market != condition_price:

                    logger.info(f"[PC] CONDITION ADJUSTMENT: '{condition}' [PASS] ¢¢{condition_tier} pricing")

                    logger.info(f"[PC] Price: ${old_market:.0f} (default) [PASS] ¢¢${condition_price:.0f} ({condition_tier})")


                # === CONDITION ARBITRAGE DETECTION (Video Games) ===
                # Flag when sealed items have large premium over CIB - possible mispricing
                if category == 'videogames' and condition_tier == 'New' and new_price > 0 and cib_price > 0:
                    sealed_premium_pct = ((new_price - cib_price) / cib_price) * 100 if cib_price > 0 else 0
                    # If sealed is 40%+ more than CIB and listing is under sealed price, flag it
                    if sealed_premium_pct >= 40 and per_item_price < new_price * 0.75:
                        pc_result['condition_arbitrage'] = True
                        pc_result['sealed_premium'] = sealed_premium_pct
                        logger.warning(f"[PC] CONDITION ARBITRAGE: Sealed {sealed_premium_pct:.0f}% over CIB!")
                        logger.warning(f"[PC] Sealed: ${new_price:.0f} vs CIB: ${cib_price:.0f} - List: ${per_item_price:.0f}")
                        logger.warning(f"[PC] >>> POSSIBLE MISPRICED SEALED - CHECK PHOTOS! <<<")

        # === LEGO SET NUMBER VALIDATION ===

        # Verify that returned product actually matches the set number in title

        if category == "lego" and pc_result and pc_result.get('found'):

            # Extract set number from title (5-digit numbers like 75187, 75192, etc.)

            title_set_match = re.search(r'\b(7\d{4}|1\d{4}|4\d{4}|6\d{4})\b', title)

            if title_set_match:

                title_set_number = title_set_match.group(1)

                product_name = str(pc_result.get('product_name', '')).lower()

                

                # Check if the returned product contains our set number

                if title_set_number not in product_name:

                    logger.warning(f"[PC] LEGO MISMATCH: Title has set #{title_set_number}, but PC returned '{product_name}'")

                    logger.warning(f"[PC] REJECTING PC result - wrong set matched!")

                    

                    # Return no match instead of wrong data

                    pc_result = {

                        'found': False,

                        'error': f'PC returned wrong set (wanted {title_set_number})',

                        'market_price': None,

                        'buy_target': None,

                        'margin': None,

                    }

                else:

                    logger.info(f"[PC] LEGO set #{title_set_number} validated in product name")

            

            # === LEGO PRICE SANITY CHECK ===

            # Most LEGO sets are under $500. Only UCS sets go higher.

            # If PC returns >$1000 but listing is under $300, it's probably a wrong match

            if pc_result.get('found') and pc_result.get('market_price'):

                pc_market = pc_result.get('market_price', 0)

                

                # Known expensive keywords (UCS, Ultimate, etc.)

                is_known_expensive = any(term in title_lower for term in ['ucs', 'ultimate collector', '10179', '10221', '75192', '75252', '75313', '10276'])

                

                if pc_market > 1000 and per_item_price < 300 and not is_known_expensive:

                    logger.warning(f"[PC] LEGO PRICE SANITY FAIL: PC says ${pc_market:.0f} but listing is ${per_item_price:.0f}")

                    logger.warning(f"[PC] This looks like a wrong match - rejecting")

                    pc_result = {

                        'found': False,

                        'error': f'Price mismatch (PC=${pc_market:.0f}, list=${per_item_price:.0f})',

                        'market_price': None,

                        'buy_target': None,

                        'margin': None,

                    }

        

        # Add quantity info to result

        if pc_result:

            pc_result['quantity'] = quantity

            pc_result['total_price'] = total_price

            pc_result['per_item_price'] = per_item_price

            pc_result['detected_language'] = detected_language

            pc_result['language_discount'] = language_discount

            

        # === VIDEO GAME MATCH VALIDATION ===

        # Verify that returned product actually matches the game title

        if category == "videogames" and pc_result and pc_result.get('found'):

            product_name = str(pc_result.get('product_name', '')).lower()

            # Decode URL encoding and replace + with space
            search_title_clean = title_lower.replace('+', ' ').replace('%20', ' ')

            # Remove common junk from the search title for comparison
            junk_patterns = [

                r'\bcomplete\b', r'\bcib\b', r'\bauthentic\b', r'\bsealed\b', r'\bmint\b',

                r'\bgreat\b', r'\bgood\b', r'\bexcellent\b', r'\bcondition\b',

                r'\bnintendo\b', r'\bds\b', r'\b3ds\b', r'\bswitch\b', r'\bps[1-5]\b',

                r'\bplaystation\b', r'\bxbox\b', r'\bsega\b', r'\bgenesis\b',

                r'\bnes\b', r'\bsnes\b', r'\bgamecube\b', r'\bwii\b', r'\bn64\b',

                r'\d{4}',  # Years like 2011

            ]

            for pattern in junk_patterns:

                search_title_clean = re.sub(pattern, ' ', search_title_clean)

            search_title_clean = ' '.join(search_title_clean.split()).strip()

            

            # Get significant words (3+ chars) from the cleaned search title
            # Also strip punctuation like brackets [], parens (), etc.
            import string
            punct_table = str.maketrans('', '', string.punctuation + '[](){}')

            search_words = set(
                word.translate(punct_table)
                for word in search_title_clean.split()
                if len(word.translate(punct_table)) >= 3
            )
            product_words = set(
                word.translate(punct_table)
                for word in product_name.split()
                if len(word.translate(punct_table)) >= 3
            )

            

            # === CRITICAL: Check for VARIANT MISMATCH ===

            # If PC result has important words NOT in the title, it's likely wrong variant

            # Example: Title "Mighty Morphin Power Rangers" but PC returns "...The Movie" version

            variant_keywords = {
                'movie', 'deluxe', 'special', 'edition', 'gold', 'platinum', 'limited',
                'collectors', 'collector', 'goty', 'definitive', 'ultimate', 'complete',
                'anthology', 'trilogy', 'collection', 'remastered', 'remake', 'hd',
                'anniversary', 'classic', 'original', 'enhanced', 'expanded', 'directors',
                # Premium/special editions
                'premium', 'steelbook', 'launch', 'day', 'pre-order', 'preorder',
                # Version variants (Ultra, Plus, etc.)
                'ultra', 'plus', 'pro', 'turbo', 'super', 'hyper', 'mega', 'dual',
                # Budget re-releases (often MORE valuable due to rarity)
                'player', 'choice', 'players', 'greatest', 'hits', 'selects', 'essentials',
                'favorites', 'classics', 'budget', 'best'
            }

            

            # Words in PC result but NOT in title

            extra_words = product_words - search_words

            # Check if any extra words are variant indicators

            variant_mismatch = extra_words & variant_keywords

            

            if variant_mismatch:

                logger.warning(f"[PC] ️ VARIANT MISMATCH DETECTED!")

                logger.warning(f"[PC] Title: '{search_title_clean}'")

                logger.warning(f"[PC] PC returned: '{product_name}'")

                logger.warning(f"[PC] Extra variant words in PC result: {variant_mismatch}")

                logger.warning(f"[PC] REJECTING - likely wrong game variant (e.g., 'The Movie' vs regular)")

                

                # Reject this match - it's the wrong variant

                pc_result = {

                    'found': False,

                    'error': f'Variant mismatch - PC has "{variant_mismatch}" not in title',

                    'market_price': None,

                    'buy_target': None,

                    'margin': None,

                    'rejected_product': product_name,

                    'rejected_reason': f'Title missing variant keywords: {variant_mismatch}'

                }

            else:

                # Calculate match ratio for remaining validation

                if search_words:

                    matching = search_words & product_words

                    match_ratio = len(matching) / len(search_words)

                    

                    logger.info(f"[PC] Video game validation: '{search_title_clean}' vs '{product_name}'")

                    logger.info(f"[PC] Matching words: {matching} ({match_ratio:.0%})")

                    

                    if match_ratio < 0.2 and len(search_words) >= 3:

                        # Only reject if VERY low match (under 20%) - likely completely wrong game

                        logger.warning(f"[PC] VIDEO GAME VERY LOW MATCH: Only {match_ratio:.0%} word match")

                        logger.warning(f"[PC] Title words: {search_words}")

                        logger.warning(f"[PC] PC words: {product_words}")

                        logger.info(f"[PC] Keeping result but flagging low confidence")

                        # Don't reject - just flag as lower confidence

                        if pc_result:

                            pc_result['confidence'] = 'Medium'

                            pc_result['match_warning'] = f'Low word match ({match_ratio:.0%})'

                    else:

                        logger.info(f"[PC] Video game match validated: {product_name}")

            

            # === VIDEO GAME PLATFORM VALIDATION ===
            # Ensure the PC result matches the platform in the listing title
            if pc_result.get('found') and pc_result.get('console_name'):
                pc_console = pc_result.get('console_name', '').lower()

                # Platform detection from listing title
                platform_patterns = {
                    '3ds': ['3ds', 'nintendo 3ds'],
                    'ds': ['nintendo ds'],
                    'switch': ['switch', 'nintendo switch'],
                    'wii u': ['wii u', 'wiiu'],
                    'wii': ['wii'],
                    'gamecube': ['gamecube', 'gc', 'game cube'],
                    'n64': ['n64', 'nintendo 64'],
                    'snes': ['snes', 'super nintendo'],
                    'nes': ['nes'],
                    'xbox 360': ['xbox 360', 'xbox360', 'x360'],
                    'xbox one': ['xbox one', 'xbone', 'xb1'],
                    'xbox': ['xbox'],
                    'playstation 3': ['ps3', 'playstation 3'],
                    'playstation 4': ['ps4', 'playstation 4'],
                    'playstation 5': ['ps5', 'playstation 5'],
                    'playstation 2': ['ps2', 'playstation 2'],
                    'playstation': ['ps1', 'playstation', 'psx'],
                    'psp': ['psp'],
                    'vita': ['vita', 'ps vita'],
                    'genesis': ['genesis', 'mega drive'],
                    'dreamcast': ['dreamcast'],
                    'saturn': ['saturn'],
                }

                detected_platform = None
                for pc_platform, keywords in platform_patterns.items():
                    for kw in keywords:
                        if kw in title_lower:
                            detected_platform = pc_platform
                            break
                    if detected_platform:
                        break

                # Check if platforms match
                if detected_platform:
                    # Normalize PC console name for comparison
                    pc_console_normalized = pc_console.replace('nintendo', '').strip()

                    # Check if PC console contains the detected platform
                    platform_matches = (
                        detected_platform in pc_console or
                        pc_console in detected_platform or
                        (detected_platform == '3ds' and '3ds' in pc_console) or
                        (detected_platform == 'ds' and 'ds' in pc_console and '3ds' not in pc_console) or
                        (detected_platform == 'wii' and 'wii' in pc_console and 'wii u' not in pc_console) or
                        (detected_platform == 'xbox' and 'xbox' in pc_console) or
                        (detected_platform == 'gamecube' and 'gamecube' in pc_console)
                    )

                    if not platform_matches:
                        logger.warning(f"[PC] PLATFORM MISMATCH: Title says '{detected_platform}' but PC has '{pc_console}'")
                        logger.warning(f"[PC] Rejecting match to avoid cross-platform price confusion")
                        pc_result = {
                            'found': False,
                            'error': f'Platform mismatch: title={detected_platform}, PC={pc_console}',
                            'market_price': None,
                            'buy_target': None,
                            'margin': None,
                            'rejected_product': pc_result.get('product_name'),
                            'rejected_reason': f'Platform mismatch: {detected_platform} vs {pc_console}'
                        }

            # === VIDEO GAME PRICE SANITY CHECK ===
            # Most games are under $200. Only rare titles go higher.
            if pc_result.get('found') and pc_result.get('market_price'):
                pc_market = pc_result.get('market_price', 0)

                # If PC returns >$500 but listing is under $100, probably wrong match
                if pc_market > 500 and per_item_price < 100:
                    logger.warning(f"[PC] VIDEO GAME PRICE SANITY FAIL: PC says ${pc_market:.0f} but listing is ${per_item_price:.0f}")
                    logger.warning(f"[PC] This looks like a wrong match - rejecting")
                    pc_result = {
                        'found': False,
                        'error': f'Price mismatch (PC=${pc_market:.0f}, list=${per_item_price:.0f})',
                        'market_price': None,
                        'buy_target': None,
                        'margin': None,
                    }

        

        # Re-add quantity info if we validated successfully

        if pc_result and 'quantity' not in pc_result:

            pc_result['quantity'] = quantity

            pc_result['total_price'] = total_price

            pc_result['per_item_price'] = per_item_price

            pc_result['detected_language'] = detected_language

            pc_result['language_discount'] = language_discount

            

            # === APPLY LANGUAGE DISCOUNT TO PRICES ===

            if detected_language != "english" and pc_result.get('found') and pc_result.get('market_price'):

                original_market = pc_result['market_price']

                adjusted_market = original_market * language_discount
                cat_threshold = get_category_threshold(category)

                pc_result['market_price'] = adjusted_market

                pc_result['buy_target'] = adjusted_market * cat_threshold

                pc_result['margin'] = pc_result['buy_target'] - per_item_price

                lang_upper = detected_language.upper() if detected_language else "UNKNOWN"

                logger.info(f"[PC] Language adjustment: ${original_market:.0f} English -> ${adjusted_market:.0f} {lang_upper}")

            

            # Recalculate total margin if we have a match

            if pc_result.get('found') and pc_result.get('margin') is not None:

                per_item_margin = pc_result['margin']

                pc_result['total_margin'] = per_item_margin * quantity

        

        # Check if we got a valid result

        if pc_result and pc_result.get('found') and pc_result.get('market_price'):

            market_price = pc_result.get('market_price', 0)

            buy_target = pc_result.get('buy_target', 0)

            margin = pc_result.get('margin', 0)

            confidence = pc_result.get('confidence', 'Unknown')

            product_name = pc_result.get('product_name', 'Unknown')

            

            # Language adjustment note

            lang_note = ""

            if detected_language != "english":

                lang_note = f"\nLANGUAGE: {detected_language.upper() if detected_language else 'UNKNOWN'} - Price adjusted to {language_discount*100:.0f}% of English value"

            

            # Build quantity-aware context

            # Add condition tier note

            condition_note = ""

            if pc_result.get('condition_tier'):

                condition_note = f"\nCONDITION: Using {pc_result['condition_tier']} pricing"

                if pc_result.get('price_breakdown'):

                    condition_note += f" ({pc_result['price_breakdown']})"

            

            if quantity > 1:

                total_margin = margin * quantity

                context = f"""

=== PRICECHARTING DATA (USE THIS FOR PRICING) ===

Matched Product: {product_name}

Category: {pc_result.get('category', category).upper()}

Console: {pc_result.get('console_name', 'N/A')}{lang_note}{condition_note}

QUANTITY: {quantity} items

Market Price (each): ${market_price:,.2f}

Buy Target (65% each): ${buy_target:,.2f}

Listing Price (total): ${total_price:,.2f}

Per-Item Price: ${per_item_price:,.2f}

Margin (per item): ${margin:,.2f}

TOTAL MARGIN: ${total_margin:,.2f}

Match Confidence: {confidence}

Source: PriceCharting Database

=== END PRICECHARTING DATA ===



IMPORTANT: This is a {quantity}-item lot. Use PER-ITEM margin for decision.

If per-item margin is NEGATIVE, recommendation MUST be PASS.

If match confidence is Low, recommend RESEARCH instead of BUY.

"""

            else:

                context = f"""

=== PRICECHARTING DATA (USE THIS FOR PRICING) ===

Matched Product: {product_name}

Category: {pc_result.get('category', category).upper()}

Console: {pc_result.get('console_name', 'N/A')}{lang_note}{condition_note}

Market Price: ${market_price:,.2f}

Buy Target (65%): ${buy_target:,.2f}

Listing Price: ${total_price:,.2f}

Margin: ${margin:,.2f}

Match Confidence: {confidence}

Source: PriceCharting Database

=== END PRICECHARTING DATA ===



IMPORTANT: Use the market price above for your calculations. 

If margin is NEGATIVE, recommendation MUST be PASS.

If match confidence is Low, recommend RESEARCH instead of BUY.

"""

            lang_suffix = f" [{detected_language.upper()}]" if detected_language != "english" else ""

            if quantity > 1:

                logger.info(f"[PC] Found: {product_name}{lang_suffix} @ ${market_price:,.0f} x{quantity} = ${market_price * quantity:,.0f} total (conf: {confidence})")

            else:

                logger.info(f"[PC] Found: {product_name}{lang_suffix} @ ${market_price:,.0f} (conf: {confidence})")

            return pc_result, context

        else:

            error_msg = pc_result.get('error', 'No match found') if pc_result else 'Lookup failed'

            logger.info(f"[PC] No match for: {title[:50]}... ({error_msg})")

            return None, f"""

=== NO PRICECHARTING MATCH ===

Product not found in price database: {error_msg}

Use your knowledge to estimate value, or recommend RESEARCH for verification.

=== END ===

"""

    except Exception as e:

        logger.error(f"[PC] Lookup error: {e}")

        return None, ""





# NOTE: normalize_tcg_lego_keys moved to utils/validation.py
# Wrapper for backward compatibility
def normalize_tcg_lego_keys(result: dict, category: str) -> dict:
    """Wrapper for utils.validation.normalize_tcg_lego_keys"""
    return utils_normalize_tcg_lego_keys(result, category)





def validate_tcg_lego_result(result: dict, pc_result: dict, total_price: float, category: str, title: str = "") -> dict:

    """

    Server-side validation for TCG/LEGO results

    Override AI calculations with PriceCharting data

    """

    # First normalize keys (AI sometimes returns wrong case/spacing)

    result = normalize_tcg_lego_keys(result, category)

    

    # === LEGO CONDITION CHECK - SERVER OVERRIDE ===

    # Force PASS for opened/no-box LEGO even if AI says BUY

    if category == 'lego':

        reasoning_text = str(result.get('reasoning', '')).lower()

        title_lower = title.lower() if title else ""

        check_text = f"{title_lower} {reasoning_text}"

        # Terms that indicate NOT sealed/new - INSTANT PASS

        lego_pass_terms = [

            'no box', 'missing box', 'without box', 'box only',

            'open box', 'opened', 'box opened',

            'used', 'played with', 'pre-owned', 'previously owned',

            'built', 'assembled', 'displayed', 'complete build',

            'incomplete', 'partial', 'missing pieces', 'missing parts',

            'bulk', 'loose', 'bricks only', 'parts only',

            'damaged box', 'box damage', 'crushed', 'dented', 'torn',

            'minifigures only', 'minifig lot', 'figures only',

            'bags only', 'sealed bags', 'numbered bags'  # Bags without box = not complete

        ]

        # KNOCKOFF/FAKE LEGO DETECTION - these are NOT real LEGO
        lego_knockoff_terms = [
            'alt of lego', 'alternative of lego', 'generic bricks', 'generic blocks',
            'compatible with lego', 'lego compatible', 'building blocks',
            'mould king', 'lepin', 'bela', 'lele', 'decool', 'sy blocks',
            'king blocks', 'lion king', 'xinlexin', 'lari', 'nuogao',
            'not lego', 'non-lego', 'third party', '3rd party bricks',
            'clone', 'knockoff', 'replica blocks', 'off-brand'
        ]

        for knockoff_term in lego_knockoff_terms:
            if knockoff_term in check_text:
                logger.warning(f"[LEGO] KNOCKOFF DETECTED: '{knockoff_term}' in title - INSTANT PASS")
                result['Recommendation'] = 'PASS'
                result['Qualify'] = 'No'
                result['reasoning'] = f"SERVER OVERRIDE: FAKE/KNOCKOFF LEGO detected ('{knockoff_term}') - NOT authentic LEGO - PASS"
                return result

        

        # Check both title and reasoning for pass terms
        for term in lego_pass_terms:

            if term in check_text:

                # Check if it's actually missing box (not just mentioning it exists)

                if term in ['sealed bags', 'numbered bags', 'bags only']:

                    # Only PASS if there's NO box mentioned positively

                    if 'with box' not in check_text and 'box included' not in check_text and 'complete' not in check_text:

                        logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected - bags without box")

                        result['Recommendation'] = 'PASS'

                        result['Qualify'] = 'No'

                        result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' = not factory sealed with box - PASS"

                        return result

                elif term == 'missing box' or term == 'no box':

                    logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected in listing")

                    result['Recommendation'] = 'PASS'

                    result['Qualify'] = 'No'

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' - we only buy sealed with box - PASS"

                    return result

                else:

                    logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected - not sealed/new")

                    result['Recommendation'] = 'PASS'

                    result['Qualify'] = 'No'

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' = not sealed - PASS"

                    return result

    

    # === REASONING VS FIELD CONSISTENCY CHECK ===

    # AI sometimes calculates correctly in reasoning but puts wrong value in Profit field

    reasoning_text = str(result.get('reasoning', '')).lower()

    

    # Look for margin patterns in reasoning: "+$101 margin", "= +$101", "$101 margin"

    margin_patterns = [

        r'[=\s]\+?\$?(\d+(?:\.\d+)?)\s*margin',      # "= $101 margin" or "+$101 margin"

        r'margin[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "margin: $101" or "margin $101"

        r'profit[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "profit: $101"

        r'\+\$(\d+(?:\.\d+)?)\s*(?:margin|profit)',   # "+$101 margin"

    ]

    

    reasoning_margin = None

    for pattern in margin_patterns:

        match = re.search(pattern, reasoning_text)

        if match:

            reasoning_margin = float(match.group(1))

            break

    

    # If NO PriceCharting match, be conservative - don't trust AI pricing

    if not pc_result or not pc_result.get('found') or not pc_result.get('market_price'):

        ai_rec = result.get('Recommendation', 'RESEARCH')

        # Without verified pricing, downgrade BUY to RESEARCH

        if ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: No PriceCharting match - verify pricing manually before buying"

            result['pcMatch'] = 'No'

            logger.info(f"[PC] Override: BUY->RESEARCH (no PC match, unverified pricing)")


        # For expensive LEGO/TCG items without PC match, upgrade PASS to RESEARCH
        # These could be valuable items not in database (new sets, rare items)
        elif ai_rec == 'PASS' and category in ['lego', 'tcg'] and total_price >= 75:

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Expensive {category.upper()} (${total_price:.0f}) not in database - verify value manually"

            result['pcMatch'] = 'No'

            logger.warning(f"[PC] Override: PASS->RESEARCH (expensive {category} ${total_price:.0f} not in database)")



        # If we found margin in reasoning, use that instead of NA

        if reasoning_margin is not None:

            margin_display = f"+{int(reasoning_margin)}" if reasoning_margin >= 0 else str(int(reasoning_margin))

            result['Profit'] = margin_display

            result['Margin'] = margin_display

            logger.info(f"[PC] Using reasoning margin ${reasoning_margin:.0f} (no PC data)")

        else:

            # Clear AI's potentially wrong profit/margin values when no PC data

            result['Profit'] = 'NA'

            result['Margin'] = 'NA'

        return result

    

    try:

        # Server is source of truth for prices

        server_market = pc_result.get('market_price', 0)

        server_buy_target = pc_result.get('buy_target', 0)

        

        # === CRITICAL: ALWAYS RECALCULATE MARGIN FROM ACTUAL LISTING PRICE ===

        # AI sometimes hallucinates quantities and divides the price incorrectly

        # Use the ACTUAL total_price passed from the listing

        server_margin = server_buy_target - total_price

        

        confidence = pc_result.get('confidence', 'Low')

        product_name = pc_result.get('product_name', 'Unknown')

        

        # === MULTI-SET LOT HANDLING ===

        is_multi_set = pc_result.get('multi_set', False)

        if is_multi_set:

            set_count = pc_result.get('set_count', 1)

            set_details = pc_result.get('set_details', [])

            all_found = pc_result.get('all_sets_found', False)

            

            logger.info(f"[PC] MULTI-SET LOT: {set_count} sets, market ${server_market:.0f}, margin ${server_margin:.0f}")

            

            # Build set breakdown for display

            set_breakdown = ", ".join([f"{d['set_number']}" for d in set_details])

            

            result['SetNumber'] = f"[{set_breakdown}]"

            result['SetName'] = f"LOT of {set_count} sets"

            result['SetCount'] = str(set_count)

            result['marketprice'] = str(int(server_market))

            result['maxBuy'] = str(int(server_buy_target))

            result['Margin'] = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            result['Profit'] = result['Margin']

            result['pcMatch'] = 'Yes'

            result['pcProduct'] = f"LOT: {set_count} sets"

            result['pcConfidence'] = confidence

            

            # Recommendation based on margin

            if server_margin >= 30:

                result['Recommendation'] = 'BUY'

                result['Qualify'] = 'Yes'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot worth ${server_market:.0f}, margin ${server_margin:+.0f}"

            elif server_margin >= 0:

                result['Recommendation'] = 'RESEARCH'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot thin margin ${server_margin:+.0f}"

            else:

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot negative margin ${server_margin:.0f}"

            

            if not all_found:

                result['reasoning'] = result.get('reasoning', '') + " | WARNING: Not all sets found in database"

                result['Recommendation'] = 'RESEARCH'  # Be conservative when some sets missing

            

            return result

        

        # Get quantity from AI but VERIFY it makes sense

        ai_quantity = pc_result.get('quantity', 1)

        

        # Log the actual calculation

        logger.info(f"[PC] SERVER CALC: maxBuy ${server_buy_target:.0f} - listPrice ${total_price:.0f} = margin ${server_margin:.0f}")

        

        # Check if AI might have divided the price by quantity

        ai_margin_str = str(result.get('Margin', result.get('Profit', '0')))

        try:

            ai_margin = float(ai_margin_str.replace('$', '').replace('+', '').replace(',', ''))

        except:

            ai_margin = 0

        

        # If AI margin is positive but server margin is negative, AI likely divided price wrong

        if ai_margin > 0 and server_margin < -20:

            logger.warning(f"[PC] AI MARGIN ERROR: AI says +${ai_margin:.0f} but server calc = ${server_margin:.0f}")

            logger.warning(f"[PC] AI may have divided price by quantity - using server calculation")

            # AI hallucinated - reset quantity to 1

            ai_quantity = 1

        

        quantity = ai_quantity

        

        # === SANITY CHECK: Compare server margin to reasoning margin ===

        if reasoning_margin is not None:

            # If server and reasoning margins differ significantly, log it

            if abs(server_margin - reasoning_margin) > 50:

                logger.warning(f"[PC] MARGIN MISMATCH: Server ${server_margin:.0f} vs Reasoning ${reasoning_margin:.0f}")

                # Only trust reasoning if server margin is POSITIVE but reasoning is negative

                # (means server may have matched wrong product)

                # If server is negative, trust it - the listing price is definitive

                if server_margin > 0 and reasoning_margin < 0:

                    logger.warning(f"[PC] Server positive but reasoning negative - possible wrong PC match")

                    # Keep server_margin but flag for research

                elif server_margin < 0 and reasoning_margin > 0:

                    # AI likely did bad math (divided price by quantity, etc.)

                    logger.warning(f"[PC] AI positive but server negative - AI likely hallucinated quantity")

                    # Keep server_margin (it's calculated from actual listing price)

        

        # For multi-quantity, show per-item values but note the quantity

        if quantity > 1:

            total_margin = server_margin * quantity

            logger.info(f"[PC] Validating: {product_name} x{quantity} | Market ${server_market:.0f}/ea | Margin ${server_margin:.0f}/ea (${total_margin:.0f} total)")

            result['quantity'] = str(quantity)

            result['perItemMargin'] = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            margin_display = f"+{int(total_margin)}" if total_margin >= 0 else str(int(total_margin))

            result['Margin'] = margin_display

            result['Profit'] = margin_display  # Also set Profit so display uses correct value

        else:

            logger.info(f"[PC] Validating: {product_name} | Market ${server_market:.0f} | Buy ${server_buy_target:.0f} | List ${total_price:.0f} | Margin ${server_margin:.0f}")

            margin_display = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            result['Margin'] = margin_display

            result['Profit'] = margin_display  # Also set Profit so display uses correct value

        

        # Override AI values with server-calculated values

        result['marketprice'] = str(int(server_market))

        result['maxBuy'] = str(int(server_buy_target))

        

        # Add PriceCharting match info

        result['pcMatch'] = 'Yes'

        result['pcProduct'] = pc_result.get('product_name', '')[:50]

        result['pcConfidence'] = confidence

        

        # Override recommendation if AI got it wrong

        ai_rec = result.get('Recommendation', 'RESEARCH')

        

        # For multi-quantity lots, use TOTAL margin for thresholds

        # (a 10-item lot with $5/item = $50 total is worth it)

        decision_margin = server_margin * quantity if quantity > 1 else server_margin

        

        # CRITICAL: PASS if negative margin (AI sometimes misses this)

        if server_margin < 0 and ai_rec == 'BUY':

            result['Recommendation'] = 'PASS'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative per-item margin (${server_margin:.0f}/ea) - PASS"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative margin (${server_margin:.0f}) - PASS"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(margin ${server_margin:.0f})")

        

        # CRITICAL: PASS if total margin too thin (< $20 profit not worth it)

        elif decision_margin < 20 and ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Thin total margin (${decision_margin:.0f} for {quantity}x) - verify manually"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Thin margin (${server_margin:.0f}) - verify manually"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(thin margin ${decision_margin:.0f})")

        

        # Upgrade to BUY if strong margin and AI was too conservative

        elif decision_margin >= 50 and confidence in ['High', 'Medium'] and ai_rec == 'RESEARCH':

            result['Recommendation'] = 'BUY'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Strong total margin (${decision_margin:.0f} for {quantity}x) - BUY"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Strong margin (${server_margin:.0f}) - BUY"

            logger.info(f"[PC] Override: RESEARCHƒÆ’‚[PASS] ¢[PASS] ¢(margin ${decision_margin:.0f})")

        

        # Low confidence = always RESEARCH

        elif confidence == 'Low' and ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: Low confidence match - verify product"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(low confidence)")

            

    except Exception as e:

        logger.error(f"[PC] Validation error: {e}")

    

    return result





def validate_videogame_result(result: dict, pc_result: dict, total_price: float, data: dict) -> dict:

    """

    Server-side validation for video game results.

    Checks math, professional sellers, and applies PriceCharting data.



    NOTE: Uses standard 65% threshold. Sonnet verification catches pricing issues

    like wrong condition tier from PriceCharting.

    """

    try:
        # Set category for threshold lookup
        category = 'videogames'

        reasoning_text = str(result.get('reasoning', '')).lower()

        # === LOT ITEM LOOKUP ===
        # If AI identified individual games in a lot, look them up in PriceCharting
        lot_items = result.get('lotItems', [])
        if lot_items and isinstance(lot_items, list) and len(lot_items) > 0:
            logger.info(f"[VG-LOT] Identified {len(lot_items)} games in lot: {lot_items[:5]}...")  # Show first 5

            console = result.get('console', '')
            lot_total_value = 0
            lot_items_found = 0

            for game_title in lot_items[:20]:  # Limit to 20 games to avoid API spam
                if not game_title or len(str(game_title)) < 3:
                    continue

                # Look up in PriceCharting
                search_query = f"{game_title} {console}".strip() if console else game_title
                game_pc = pc_lookup(search_query, category="videogames", listing_price=0)

                if game_pc and game_pc.get('found') and game_pc.get('market_price', 0) > 0:
                    game_value = game_pc.get('market_price', 0)
                    lot_total_value += game_value
                    lot_items_found += 1
                    logger.info(f"[VG-LOT]   {game_title}: ${game_value:.0f}")

            if lot_items_found > 0:
                # Update market price with summed values
                logger.info(f"[VG-LOT] Total lot value: ${lot_total_value:.0f} from {lot_items_found} identified games")
                result['marketprice'] = str(int(lot_total_value))
                result['lotValueMethod'] = 'itemized'
                result['lotItemsFound'] = lot_items_found

                # Recalculate margin
                cat_threshold = get_category_threshold(category)
                lot_maxbuy = lot_total_value * cat_threshold
                lot_margin = lot_maxbuy - total_price
                result['maxBuy'] = str(int(lot_maxbuy))
                result['Margin'] = str(int(lot_margin))
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Itemized lot - {lot_items_found} games = ${lot_total_value:.0f}, maxBuy ${lot_maxbuy:.0f}"

                # Update recommendation based on new margin
                if lot_margin >= 20 and result.get('Recommendation') == 'RESEARCH':
                    result['Recommendation'] = 'BUY'
                    result['reasoning'] += " | Upgraded to BUY (positive itemized margin)"
                elif lot_margin < 0 and result.get('Recommendation') == 'BUY':
                    result['Recommendation'] = 'PASS'
                    result['reasoning'] += " | PASS (negative margin after itemization)"

        # === FALLBACK LOT VALUATION ===
        # If we have a lot count but no/few itemized games, apply minimum per-game estimate
        is_lot = str(result.get('isLot', '')).lower() == 'yes'
        lot_count = 0
        try:
            lot_count = int(result.get('lotCount', 0))
        except:
            pass

        lot_items_found = result.get('lotItemsFound', 0)

        if is_lot and lot_count >= 5 and lot_items_found < lot_count * 0.3:
            # Less than 30% of games identified - apply conservative floor estimate
            console = str(result.get('console', '')).lower()

            # Conservative per-game minimums by console
            per_game_min = {
                'ds': 3, 'nintendo ds': 3, '3ds': 4, 'nintendo 3ds': 4,
                'gba': 5, 'game boy advance': 5, 'game boy': 4,
                'snes': 8, 'super nintendo': 8, 'nes': 5,
                'n64': 10, 'nintendo 64': 10,
                'gamecube': 12, 'gcn': 12,
                'wii': 3, 'wii u': 5,
                'ps1': 3, 'ps2': 3, 'ps3': 4,
                'xbox': 3, 'xbox 360': 3,
                'genesis': 4, 'sega genesis': 4,
            }.get(console, 4)  # Default $4/game if console unknown

            floor_value = lot_count * per_game_min
            current_market = 0
            try:
                current_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))
            except:
                pass

            # Only apply floor if current estimate is less than floor
            if floor_value > current_market:
                logger.warning(f"[VG-LOT] Floor estimate: {lot_count} games x ${per_game_min} = ${floor_value} (was ${current_market:.0f})")
                result['marketprice'] = str(int(floor_value))
                result['lotValueMethod'] = 'floor_estimate'

                # Recalculate margin with floor value
                cat_threshold = get_category_threshold(category)
                floor_maxbuy = floor_value * cat_threshold
                floor_margin = floor_maxbuy - total_price
                result['maxBuy'] = str(int(floor_maxbuy))
                result['Margin'] = str(int(floor_margin))
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Floor estimate {lot_count} games x ${per_game_min} = ${floor_value}, maxBuy ${floor_maxbuy:.0f}"

                # Update recommendation if now profitable
                if floor_margin >= 30:
                    result['Recommendation'] = 'RESEARCH'
                    result['reasoning'] += " | Needs verification but floor value suggests profitable"

        # === LOW CONFIDENCE CHECK ===

        # If confidence is Low or reasoning shows uncertainty, cannot be BUY

        confidence = result.get('confidence', 'Low')

        if isinstance(confidence, (int, float)):

            confidence_val = int(confidence)

        elif isinstance(confidence, str):

            if confidence.isdigit():

                confidence_val = int(confidence)

            else:

                confidence_val = {'high': 80, 'medium': 60, 'low': 40}.get(confidence.lower().split()[0], 40)

        else:

            confidence_val = 40

        

        # Uncertainty indicators in reasoning

        uncertainty_phrases = [

            'cannot verify', 'without images', 'need visual', 'unable to confirm',

            'need verification', 'optimistic', 'seems high', 'uncertain',

            'cannot determine', 'hard to tell', 'impossible to verify',

            'no images', 'missing images', 'requires inspection'

        ]

        

        has_uncertainty = any(phrase in reasoning_text for phrase in uncertainty_phrases)

        

        if result.get('Recommendation') == 'BUY' and (confidence_val <= 30 or has_uncertainty):

            logger.warning(f"[VG] LOW CONFIDENCE BUY: conf={confidence_val}, uncertainty={has_uncertainty}")

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER OVERRIDE: Low confidence/uncertainty - cannot BUY without verification"

            logger.info(f"[VG] Override: BUY->RESEARCH (low confidence or uncertainty in reasoning)")

        

        # === PROFESSIONAL SELLER DETECTION ===

        seller_id = str(data.get('Seller', data.get('seller', ''))).lower()

        

        professional_keywords = [

            'games', 'gaming', 'retro', 'vintage', 'collectibles', 'collector',

            'video', 'game', 'shop', 'store', 'entertainment', 'media'

        ]

        

        is_professional = any(kw in seller_id for kw in professional_keywords)

        

        if is_professional:

            logger.info(f"[VG] Professional seller detected: {seller_id}")

            # Lower confidence if AI said High

            if result.get('confidence') == 'High':

                result['confidence'] = 'Medium'

            # Add to reasoning

            result['reasoning'] = result.get('reasoning', '') + f" | WARNING: Professional seller '{seller_id}' - prices likely at/above market"

        

        # === MATH VALIDATION (category-specific threshold) ===
        cat_threshold = get_category_threshold(category)
        threshold_pct = int(cat_threshold * 100)

        try:

            ai_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))

            ai_maxbuy = float(str(result.get('maxBuy', '0')).replace('$', '').replace(',', '').replace('NA', '0'))



            if ai_market > 0:

                correct_maxbuy = ai_market * cat_threshold

                correct_margin = correct_maxbuy - total_price



                # Check if AI got the threshold calculation wrong

                if ai_maxbuy > 0 and abs(ai_maxbuy - correct_maxbuy) > 5:  # More than $5 off

                    logger.warning(f"[VG] MATH ERROR: AI maxBuy ${ai_maxbuy:.0f} vs correct ${correct_maxbuy:.0f}")

                    result['maxBuy'] = str(int(correct_maxbuy))

                    result['Margin'] = f"+{int(correct_margin)}" if correct_margin >= 0 else str(int(correct_margin))

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Corrected maxBuy to ${correct_maxbuy:.0f} ({threshold_pct}% of ${ai_market:.0f})"

                

                # If margin is actually negative but AI said BUY, force PASS

                if correct_margin < 0 and result.get('Recommendation') == 'BUY':

                    logger.warning(f"[VG] Forcing PASS: Margin is actually ${correct_margin:.0f}")

                    result['Recommendation'] = 'PASS'

                    result['Margin'] = str(int(correct_margin))

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative margin (${correct_margin:.0f}) - PASS"

                

        except (ValueError, TypeError) as e:

            logger.debug(f"[VG] Math validation skipped: {e}")

        

        # === PRICECHARTING DATA OVERRIDE ===

        if pc_result and pc_result.get('found') and pc_result.get('market_price'):

            pc_market = pc_result['market_price']

            pc_maxbuy = pc_market * cat_threshold  # Use category-specific threshold

            pc_margin = pc_maxbuy - total_price

            

            logger.info(f"[VG] PriceCharting: Market ${pc_market:.0f}, maxBuy ${pc_maxbuy:.0f}, margin ${pc_margin:.0f}")

            

            # Override AI values with PriceCharting data

            result['marketprice'] = str(int(pc_market))

            result['maxBuy'] = str(int(pc_maxbuy))

            result['Margin'] = f"+{int(pc_margin)}" if pc_margin >= 0 else str(int(pc_margin))

            result['pcMatch'] = 'Yes'

            result['pcProduct'] = pc_result.get('product_name', '')[:50]

            # Add condition arbitrage flag if detected
            if pc_result.get('condition_arbitrage'):
                result['conditionArbitrage'] = 'SEALED MISPRICED?'
                result['sealedPremium'] = f"{pc_result.get('sealed_premium', 0):.0f}%"
                result['reasoning'] = result.get('reasoning', '') + f" | CONDITION ARBITRAGE: Sealed is {pc_result.get('sealed_premium', 0):.0f}% over CIB - may be mispriced!"

            # Force PASS if PriceCharting shows negative margin

            if pc_margin < 0 and result.get('Recommendation') == 'BUY':

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: PriceCharting shows ${pc_margin:.0f} margin - PASS"

                logger.info(f"[VG] Override: BUY->PASS (PC margin ${pc_margin:.0f})")

            

        # Downgrade to RESEARCH if no PC match and AI said BUY

        elif result.get('Recommendation') == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['pcMatch'] = 'No'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: No PriceCharting match - verify pricing manually"

            logger.info(f"[VG] Override: BUY->RESEARCH (no PC match)")

        

    except Exception as e:

        logger.error(f"[VG] Validation error: {e}")

    

    return result





# ============================================================
# MAIN ANALYSIS ENDPOINT
# NOTE: This function has been MOVED to routes/analysis.py
# The router is included above and configure_analysis() is called below render_result_html
# Decorators commented out to prevent route conflicts with the router
# ============================================================

# @app.post("/match_mydata")  # MOVED TO routes/analysis.py
# @app.get("/match_mydata")   # MOVED TO routes/analysis.py

async def _old_analyze_listing(request: Request):  # Renamed to prevent conflicts

    """Main analysis endpoint - processes eBay listings"""

    logger.info("=" * 60)

    logger.info("[match_mydata] Endpoint called")

    logger.info("=" * 60)

    

    # Log ALL request details

    logger.info(f"[REQUEST] Method: {request.method}")

    logger.info(f"[REQUEST] URL: {request.url}")

    logger.info(f"[REQUEST] Headers:")

    for key, value in request.headers.items():

        logger.info(f"    {key}: {value}")

    

    try:

        data = {}

        images = []

        

        # Parse request data

        query_data = dict(request.query_params)

        if query_data:

            data = query_data

            logger.info(f"[REQUEST] Query params count: {len(query_data)}")

        

        # Read body for POST requests

        body = b""

        if not data:

            try:

                body = await request.body()

                logger.info(f"[REQUEST] Body length: {len(body)} bytes")

                if len(body) < 500:

                    logger.info(f"[REQUEST] Body content: {body[:500]}")

            except Exception as e:

                logger.warning(f"Failed to read body: {e}")

        

        # Parse JSON body

        if not data and body:

            try:

                json_data = json.loads(body)

                if isinstance(json_data, dict):

                    data = json_data

                    logger.info("[REQUEST] Parsed as JSON")

                    # Log critical fields

                    logger.info(f"[REQUEST] response_type: {data.get('response_type', 'NOT SET')}")

                    logger.info(f"[REQUEST] llm_provider: {data.get('llm_provider', 'NOT SET')}")

                    logger.info(f"[REQUEST] llm_model: {data.get('llm_model', 'NOT SET')}")

                    if 'system_prompt' in data:

                        logger.info(f"[REQUEST] system_prompt length: {len(str(data.get('system_prompt', '')))}")

                    if 'display_template' in data:

                        logger.info(f"[REQUEST] display_template length: {len(str(data.get('display_template', '')))}")

            except Exception:

                pass

        

        # Parse URL-encoded body

        if not data and body:

            try:

                parsed = parse_qs(body.decode('utf-8', errors='ignore'))

                if parsed:

                    data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

                    logger.info("[REQUEST] Parsed as URL-encoded")

            except Exception:

                pass

        

        title = data.get('Title', 'No title')[:80]

        total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))

        alias = data.get('Alias', '')  # Search term from uBuyFirst

        response_type = data.get('response_type', 'html')  # Save early!

        listing_id = str(uuid.uuid4())[:8]

        timestamp = datetime.now().isoformat()

        

        # Debug: Check for CheckoutUrl/ItemId fields

        checkout_url = data.get('CheckoutUrl', data.get('checkoutUrl', data.get('checkout_url', '')))

        item_id = data.get('ItemId', data.get('itemId', data.get('item_id', '')))

        view_url = data.get('ViewUrl', data.get('viewUrl', data.get('view_url', '')))

        ebay_url = checkout_url or view_url or ''

        

        logger.info(f"Title: {title[:50]}")

        logger.info(f"Price: ${total_price}")

        logger.info(f"[SAVED] response_type: {response_type}")

        logger.info(f"[DEBUG] CheckoutUrl: '{checkout_url}'")

        logger.info(f"[DEBUG] ItemId: '{item_id}'")

        logger.info(f"[DEBUG] ViewUrl: '{view_url}'")

        logger.info(f"[DEBUG] ALL KEYS: {list(data.keys())}")

        # ============================================================
        # SPAM DETECTION - Check for blocked sellers EARLY
        # ============================================================
        spam_seller_name = data.get('SellerName', '') or data.get('StoreName', '')
        is_blocked, newly_blocked = check_seller_spam(spam_seller_name)

        if is_blocked:
            if newly_blocked:
                logger.warning(f"[SPAM] NEW BLOCK: '{spam_seller_name}' - rapid-fire listing detected")
            else:
                logger.info(f"[SPAM] INSTANT PASS: '{spam_seller_name}' is blocked")

            return JSONResponse(content={
                "Recommendation": "PASS",
                "Qualify": "No",
                "reasoning": f"Blocked seller (spam): {spam_seller_name}",
                "confidence": "High",
                "blocked_seller": True,
                "seller_name": spam_seller_name,
                "newly_blocked": newly_blocked
            })

        # ============================================================
        # DEDUPLICATION - Check if we've recently evaluated this item
        # ============================================================
        cached_result = check_recently_evaluated(title, total_price)
        if cached_result:
            logger.info(f"[DEDUP] Returning cached result: {cached_result.get('Recommendation', 'UNKNOWN')}")
            cached_result['dedup_cached'] = True
            return JSONResponse(content=cached_result)

        # ============================================================
        # PRICE CORRECTIONS - Check user's logged market prices
        # ============================================================
        user_price_correction = None
        if check_price_correction:
            try:
                user_price_correction = check_price_correction(title)
                if user_price_correction:
                    logger.info(f"[PRICE CHECK] Found user correction: '{user_price_correction['keywords']}' -> ${user_price_correction['market_price']}")
            except Exception as e:
                logger.warning(f"[PRICE CHECK] Error checking corrections: {e}")

        # Log seller-related fields for profiling
        seller_fields = {
            'SellerName': data.get('SellerName', ''),
            'SellerBusiness': data.get('SellerBusiness', ''),
            'SellerStore': data.get('SellerStore', ''),
            'SellerCountry': data.get('SellerCountry', ''),
            'SellerRegistration': data.get('SellerRegistration', ''),
            'StoreName': data.get('StoreName', ''),
            'FeedbackScore': data.get('FeedbackScore', ''),
            'FeedbackRating': data.get('FeedbackRating', ''),
            'EbayWebsite': data.get('EbayWebsite', ''),
        }
        logger.info(f"[SELLER DATA] {seller_fields}")

        # Log other potentially useful fields
        listing_fields = {
            'PostedTime': data.get('PostedTime', ''),
            'ListingType': data.get('ListingType', ''),
            'BestOffer': data.get('BestOffer', ''),
            'Returns': data.get('Returns', ''),
            'Quantity': data.get('Quantity', ''),
            'FromCountry': data.get('FromCountry', ''),
            'Condition': data.get('Condition', ''),
            'ItemPrice': data.get('ItemPrice', ''),
            'SoldTime': data.get('SoldTime', ''),
            'Authenticity': data.get('Authenticity', ''),
            'TitleMatch': data.get('TitleMatch', ''),
            'Term': data.get('Term', ''),
        }
        logger.info(f"[LISTING DATA] {listing_fields}")

        # Dump ALL non-system fields to find item ID
        skip_keys = {'system_prompt', 'display_template', 'llm_provider', 'llm_model', 'llm_api_key', 'response_type', 'description', 'images'}
        all_values = {k: str(v)[:100] for k, v in data.items() if k not in skip_keys}
        logger.info(f"[ALL VALUES] {all_values}")

        # ============================================================
        # LISTING ENHANCEMENTS - Freshness, Sold check, Seller scoring
        # ============================================================

        # Check if already sold
        sold_time = data.get('SoldTime', '').strip()
        if sold_time:
            logger.info(f"[SKIP] Item already sold at {sold_time}")
            return JSONResponse(content={
                "Recommendation": "SKIP",
                "reasoning": f"Item already sold at {sold_time}",
                "skipped": True,
                "sold_time": sold_time
            })

        # Calculate freshness from PostedTime
        freshness_minutes = None
        freshness_score = 50  # Default
        posted_time_str = data.get('PostedTime', '').replace('+', ' ')
        if posted_time_str:
            try:
                # Parse format like "1/7/2026 10:26:36 AM"
                from datetime import datetime as dt_parse
                posted_time = dt_parse.strptime(posted_time_str.strip(), '%m/%d/%Y %I:%M:%S %p')
                freshness_minutes = (dt_parse.now() - posted_time).total_seconds() / 60

                # Score based on freshness (newer = higher score)
                if freshness_minutes < 2:
                    freshness_score = 100  # Super fresh!
                elif freshness_minutes < 5:
                    freshness_score = 90
                elif freshness_minutes < 15:
                    freshness_score = 75
                elif freshness_minutes < 30:
                    freshness_score = 60
                elif freshness_minutes < 60:
                    freshness_score = 40
                else:
                    freshness_score = 20  # Stale

                logger.info(f"[FRESHNESS] Posted {freshness_minutes:.1f} min ago, score: {freshness_score}")
            except Exception as e:
                logger.debug(f"[FRESHNESS] Could not parse PostedTime: {e}")

        # Extract BestOffer flag
        best_offer = str(data.get('BestOffer', '')).lower() == 'true'
        if best_offer:
            logger.info(f"[BEST OFFER] Seller accepts offers - negotiation possible")

        # Calculate seller score with eBay data
        seller_name = data.get('SellerName', '')
        seller_score = 50
        seller_type = 'unknown'
        seller_recommendation = 'NORMAL'

        if seller_name:
            try:
                ebay_seller_data = {
                    'SellerBusiness': data.get('SellerBusiness', ''),
                    'SellerStore': data.get('SellerStore', ''),
                    'StoreName': data.get('StoreName', ''),
                    'FeedbackScore': data.get('FeedbackScore', ''),
                    'FeedbackRating': data.get('FeedbackRating', ''),
                    'SellerRegistration': data.get('SellerRegistration', ''),
                }
                seller_analysis = analyze_new_seller(
                    seller=seller_name,
                    title=title,
                    category=category if category else '',
                    ebay_data=ebay_seller_data
                )
                seller_score = seller_analysis.get('score', 50)
                seller_type = seller_analysis.get('type', 'unknown')
                seller_recommendation = seller_analysis.get('recommendation', 'NORMAL')

                if seller_score >= 70:
                    logger.info(f"[SELLER] HIGH VALUE: {seller_name} (score:{seller_score}, type:{seller_type})")
                elif seller_score <= 35:
                    logger.info(f"[SELLER] LOW VALUE (dealer): {seller_name} (score:{seller_score})")
            except Exception as e:
                logger.debug(f"[SELLER] Could not analyze seller: {e}")

        # Store enhancement data for response
        listing_enhancements = {
            'freshness_minutes': freshness_minutes,
            'freshness_score': freshness_score,
            'best_offer': best_offer,
            'seller_score': seller_score,
            'seller_type': seller_type,
            'seller_recommendation': seller_recommendation,
            'seller_name': seller_name,
        }

        # ============================================================

        # RACE COMPARISON - Log item from uBuyFirst

        # ============================================================

        try:

            price_float = float(str(total_price).replace('$', '').replace(',', ''))

            # Use ItemId if available, otherwise create hash from title+price

            race_item_id = item_id if item_id else f"ubf_{hash(title + str(price_float)) % 10000000:07d}"

            log_race_item(

                item_id=race_item_id,

                source="ubuyfirst",

                title=title,

                price=price_float,

                category=data.get('CategoryName', 'Unknown'),

            )

            logger.info(f"[RACE] Logged item {race_item_id} from uBuyFirst: {title[:40]}")

            # Log to source comparison system for latency tracking
            log_listing_received(
                item_id=race_item_id,
                source="ubf",
                posted_time=data.get('PostedTime', ''),
                title=title,
                price=price_float,
                category=data.get('CategoryName', 'Unknown'),
            )

        except Exception as e:

            logger.warning(f"[RACE] Failed to log item: {e}")

        

        # Start timing for performance analysis

        import time as _time

        _start_time = _time.time()

        _timing = {}

        

        STATS["total_requests"] += 1

        

        # ============================================================

        # CHECK SMART CACHE FIRST

        # ============================================================

        cached = cache.get(title, total_price)

        if cached:

            result, html = cached

            

            # Detect category to check if we should trust the cache

            category_check, _ = detect_category(data)

            

            # For video games: Don't trust cached BUY results without PC verification

            # This prevents serving stale results from before PC integration

            if category_check == 'videogames' and result.get('Recommendation') == 'BUY':

                if result.get('pcMatch') != 'Yes':

                    logger.warning(f"[CACHE] Skipping cached video game BUY without PC verification")

                    # Fall through to re-analyze

                else:

                    # SANITY CHECK: If cached market price is very high, it might be AI-hallucinated

                    try:

                        cached_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))

                        cached_profit = float(str(result.get('Profit', '0')).replace('$', '').replace('+', '').replace(',', ''))

                        listing_price = float(str(total_price).replace('$', '').replace(',', ''))

                        

                        # If market > $300 and profit > $100, cache might have bad data

                        if cached_market > 300 and cached_profit > 100:

                            logger.warning(f"[CACHE] SUSPICIOUS: market=${cached_market:.0f}, profit=${cached_profit:.0f} - re-verifying")

                            # Fall through to re-analyze instead of trusting cache

                        else:

                            STATS["cache_hits"] += 1

                            logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")

                            if response_type == 'json':

                                return JSONResponse(content=result)

                            else:

                                return HTMLResponse(content=html)

                    except:

                        # If we can't parse prices, trust the cache

                        STATS["cache_hits"] += 1

                        logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")

                        if response_type == 'json':

                            return JSONResponse(content=result)

                        else:

                            return HTMLResponse(content=html)

            else:

                STATS["cache_hits"] += 1

                logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')}")

                # Return based on response_type

                if response_type == 'json':

                    logger.info("[CACHE HIT] Returning JSON (response_type=json)")

                    return JSONResponse(content=result)

                else:

                    logger.info("[CACHE HIT] Returning HTML (response_type=html)")

                    return HTMLResponse(content=html)

        

        # ============================================================

        # IN-FLIGHT REQUEST DEDUPLICATION

        # If same listing is already being processed, wait for it

        # This prevents duplicate Haiku+Sonnet calls for HTML/JSON dual requests

        # ============================================================

        request_key = f"{title}|{total_price}"

        should_wait = False

        event = None

        

        async with IN_FLIGHT_LOCK:

            if request_key in IN_FLIGHT and not IN_FLIGHT[request_key].is_set():

                # Another request is already processing this SAME listing

                logger.info(f"[IN-FLIGHT] Same listing already processing, will wait...")

                event = IN_FLIGHT[request_key]

                should_wait = True

            elif request_key not in IN_FLIGHT:

                # We're the first request for this listing - register it

                event = asyncio.Event()

                IN_FLIGHT[request_key] = event

                IN_FLIGHT_RESULTS[request_key] = None

                logger.debug(f"[IN-FLIGHT] First request for this listing, processing...")

        

        # If we should wait for another request processing the same listing

        if should_wait and event:

            try:

                await asyncio.wait_for(event.wait(), timeout=30.0)

                # Get the result from the first request

                if request_key in IN_FLIGHT_RESULTS and IN_FLIGHT_RESULTS[request_key]:

                    result, html = IN_FLIGHT_RESULTS[request_key]

                    logger.info(f"[IN-FLIGHT] Got result: {result.get('Recommendation', 'UNKNOWN')}")

                    if response_type == 'json':

                        return JSONResponse(content=result)

                    else:

                        return HTMLResponse(content=html)

            except asyncio.TimeoutError:

                logger.warning(f"[IN-FLIGHT] Timeout - processing independently")

            # Fall through to process ourselves if something went wrong

        

        # Flag to track if we need to signal completion

        is_first_request = request_key in IN_FLIGHT and not IN_FLIGHT[request_key].is_set()

        

        # ============================================================

        # DISABLED CHECK

        # ============================================================

        if not ENABLED:

            logger.info("DISABLED - Returning placeholder")

            STATS["skipped"] += 1

            disabled_result = {

                "Qualify": "No",

                "Recommendation": "DISABLED",

                "reasoning": "Proxy disabled - enable at localhost:8000"

            }

            return JSONResponse(content=disabled_result)

        

        # ============================================================

        # QUEUE MODE - Store for manual review

        # ============================================================

        if QUEUE_MODE:

            category, category_reasons = detect_category(data)

            log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

            

            # Store raw image URLs for later (don't fetch yet - saves time)

            raw_images = data.get('images', [])

            if raw_images:

                first_img = raw_images[0] if raw_images else None

                if first_img:

                    img_preview = str(first_img)[:100] if isinstance(first_img, str) else str(type(first_img))

                    logger.info(f"[IMAGES] First image format: {img_preview}...")

            

            LISTING_QUEUE[listing_id] = {

                "id": listing_id,

                "timestamp": timestamp,

                "title": title,

                "total_price": total_price,

                "category": category,

                "category_reasons": category_reasons,

                "data": data,

                "raw_images": raw_images,

                "status": "queued"

            }

            

            logger.info(f"QUEUED for review - Category: {category}")

            return HTMLResponse(content=_render_queued_html(category, listing_id, title, str(total_price)))

        

        # ============================================================

        # FULL ANALYSIS

        # ============================================================

        STATS["api_calls"] += 1

        STATS["session_cost"] += COST_PER_CALL_HAIKU

        

        # Detect category

        category, category_reasons = detect_category(data)

        logger.info(f"Category: {category}")

        _timing['category'] = _time.time() - _start_time

        logger.info(f"[TIMING] Category detect + setup: {_timing['category']*1000:.0f}ms")


        # ============================================================
        # USER PRICE DATABASE CHECK
        # Check if we have a user-provided market value for this item
        # ============================================================
        user_price_match = lookup_user_price(title)
        if user_price_match:
            matched_name, price_data = user_price_match
            user_market_value = price_data['market_value']
            user_max_buy = price_data['max_buy']

            try:
                listing_price = float(str(total_price).replace('$', '').replace(',', ''))
            except:
                listing_price = 0

            if listing_price > 0:
                profit = user_market_value - listing_price
                roi = (profit / listing_price) * 100 if listing_price > 0 else 0

                if listing_price <= user_max_buy:
                    # INSTANT BUY - price is at or below our max buy threshold
                    logger.info(f"[USER-PRICE] MATCH: {matched_name} -> Market ${user_market_value}, Max Buy ${user_max_buy}")
                    logger.info(f"[USER-PRICE] BUY! Price ${listing_price} <= Max ${user_max_buy} (Profit ${profit:.2f}, ROI {roi:.0f}%)")

                    result = {
                        "Recommendation": "BUY",
                        "Qualify": "Yes",
                        "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, listing ${listing_price} = ${profit:.2f} profit ({roi:.0f}% ROI)",
                        "confidence": 95,
                        "marketprice": f"${user_market_value:.2f}",
                        "Profit": f"+${profit:.2f}",
                        "ROI": f"{roi:.0f}%",
                        "userPriceMatch": True,
                        "matchedItem": matched_name,
                        "maxBuy": f"${user_max_buy:.2f}",
                        "category": category,
                        **listing_enhancements
                    }

                    html = render_result_html(result, category, title)
                    cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)

                elif listing_price <= user_market_value * 0.85:
                    # RESEARCH - price is good but above our strict threshold
                    logger.info(f"[USER-PRICE] RESEARCH: Price ${listing_price} > Max ${user_max_buy} but < 85% market")

                    result = {
                        "Recommendation": "RESEARCH",
                        "Qualify": "Maybe",
                        "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, but price ${listing_price} > max buy ${user_max_buy}. Still {roi:.0f}% ROI if accurate.",
                        "confidence": 75,
                        "marketprice": f"${user_market_value:.2f}",
                        "Profit": f"+${profit:.2f}",
                        "ROI": f"{roi:.0f}%",
                        "userPriceMatch": True,
                        "matchedItem": matched_name,
                        "maxBuy": f"${user_max_buy:.2f}",
                        "category": category,
                        **listing_enhancements
                    }

                    html = render_result_html(result, category, title)
                    cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)
                else:
                    # Price too high - PASS
                    # CRITICAL: Must return here to prevent PriceCharting from overriding
                    logger.info(f"[USER-PRICE] PASS: Price ${listing_price} too high (market ${user_market_value})")

                    result = {
                        "Recommendation": "PASS",
                        "Qualify": "No",
                        "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, max buy ${user_max_buy}, but listing ${listing_price} is too high.",
                        "confidence": 90,
                        "marketprice": f"${user_market_value:.2f}",
                        "Profit": f"-${listing_price - user_max_buy:.2f}",
                        "userPriceMatch": True,
                        "matchedItem": matched_name,
                        "maxBuy": f"${user_max_buy:.2f}",
                        "category": category,
                        **listing_enhancements
                    }

                    html = render_result_html(result, category, title)
                    cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)

        # ============================================================

        # INSTANT PASS CHECK (No AI needed - pure rule-based)

        # ============================================================

        instant_pass_result = check_instant_pass(title, total_price, category, data)

        if instant_pass_result:

            reason, rec = instant_pass_result

            logger.info(f"[INSTANT PASS] {reason}")

            

            # Build complete result with all fields uBuyFirst expects

            result = {

                "Recommendation": "PASS",

                "Qualify": "No",

                "reasoning": f"INSTANT PASS: {reason}",

                "confidence": 95,

                "instantPass": True,

                # Gold/Silver fields

                "karat": "NA",

                "weight": "NA",

                "goldweight": "NA",

                "silverweight": "NA",

                "meltvalue": "NA",

                "maxBuy": "NA",

                "sellPrice": "NA",

                "Profit": "NA",

                "Margin": "NA",

                "pricePerGram": "NA",

                "fakerisk": "NA",

                "itemtype": "NA",

                "stoneDeduction": "0",

                "weightSource": "NA",

                "verified": "rule-based",

            }

            

            # Store and return

            html = render_result_html(result, category, title)

            cache.set(title, total_price, result, html, "PASS")

            

            STATS["pass_count"] += 1

            logger.info(f"[INSTANT PASS] Saved ~8 seconds by skipping AI!")

            

            if response_type == 'json':

                return JSONResponse(content=result)

            return HTMLResponse(content=html)

        

        # PriceCharting lookup for TCG and LEGO

        pc_result = None

        pc_context = ""

        if category in ["tcg", "lego", "videogames"]:

            try:

                price_float = float(str(total_price).replace('$', '').replace(',', ''))

                # Extract UPC if available (most accurate lookup method)

                upc = data.get('UPC', '') or data.get('upc', '')

                if upc:

                    logger.info(f"[PC] UPC found: {upc}")

                

                # Extract condition for price tier selection (critical for video games!)

                condition = data.get('Condition', '') or data.get('condition', '')

                if condition:

                    logger.info(f"[PC] Condition: {condition}")

                

                # Extract quantity for multi-item listings

                quantity = 1

                qty_raw = data.get('Quantity', '') or data.get('quantity', '')

                if qty_raw:

                    try:

                        quantity = int(float(str(qty_raw).replace(',', '')))

                        if quantity > 1:

                            logger.info(f"[PC] Quantity: {quantity} items")

                    except:

                        quantity = 1

                # === LOT QUANTITY DETECTION FROM TITLE ===
                # Detect quantities like "LOT OF 10", "x10", "10x", "SET OF 5", etc.
                title_upper = title.upper() if title else ""
                title_qty = None
                
                # Pattern: "LOT OF X" or "LOT X" or "SET OF X"
                lot_match = re.search(r'(?:LOT\s+(?:OF\s+)?(\d+)|SET\s+OF\s+(\d+))', title_upper)
                if lot_match:
                    title_qty = int(lot_match.group(1) or lot_match.group(2))
                
                # Pattern: "Xx" or "xX" (e.g., "10x" or "x10")
                if not title_qty:
                    x_match = re.search(r'(?:^|\s)(\d+)\s*[xX](?:\s|$)|(?:^|\s)[xX]\s*(\d+)(?:\s|$)', title_upper)
                    if x_match:
                        title_qty = int(x_match.group(1) or x_match.group(2))
                
                # Pattern: "X boxes" or "X ETBs" or "X booster"
                if not title_qty:
                    boxes_match = re.search(r'(\d+)\s*(?:boxes|etbs|boosters|packs|cases)', title_upper, re.IGNORECASE)
                    if boxes_match:
                        title_qty = int(boxes_match.group(1))
                
                # Use title quantity if found and > 1
                if title_qty and title_qty > 1:
                    quantity = title_qty
                    logger.info(f"[LOT] Detected quantity {quantity} from title")


                

                _pc_start = _time.time()

                pc_result, pc_context = get_pricecharting_context(title, price_float, category, upc, quantity, condition)

                _timing['pricecharting'] = _time.time() - _pc_start

                logger.info(f"[TIMING] PriceCharting lookup: {_timing['pricecharting']*1000:.0f}ms")

                

                # === QUICK PASS CHECK - Skip images if clearly not profitable ===

                if pc_result and pc_result.get('found') and pc_result.get('margin') is not None:

                    pc_margin = pc_result.get('margin', 0)

                    pc_product = pc_result.get('product_name', 'Unknown')

                    

                    # If margin is clearly negative (more than $15 loss), instant PASS

                    if pc_margin < -15:

                        logger.info(f"[QUICK PASS] {category.upper()}: {pc_product} margin ${pc_margin:.0f} - skipping images")

                        

                        # Build quick PASS result without AI call

                        quick_result = {

                            'Qualify': 'No',

                            'Recommendation': 'PASS',

                            'reasoning': f"PriceCharting: {pc_product} @ ${pc_result.get('market_price', 0):.0f} market, max buy ${pc_result.get('buy_target', 0):.0f}, listing ${price_float:.0f} = ${pc_margin:.0f} margin (auto-PASS)",

                            'marketprice': str(int(pc_result.get('market_price', 0))),

                            'maxBuy': str(int(pc_result.get('buy_target', 0))),

                            'Margin': str(int(pc_margin)),

                            'Profit': str(int(pc_margin)),

                            'confidence': 'High',

                            'fakerisk': 'Low',

                            'pcMatch': 'Yes',

                            'pcProduct': pc_product[:50],

                        }

                        

                        # Add category-specific fields

                        if category == 'lego':

                            quick_result.update({

                                'SetNumber': pc_result.get('product_id', 'Unknown'),

                                'SetName': pc_product,

                                'Theme': 'Unknown',

                                'Retired': 'Unknown',

                            })

                        elif category == 'tcg':

                            quick_result.update({

                                'TCG': 'Pokemon',  # Default

                                'ProductType': 'Unknown',

                                'SetName': pc_result.get('console_name', 'Unknown'),

                            })

                        

                        # Cache and return

                        html = render_result_html(quick_result, category, title)

                        cache.set(title, total_price, quick_result, html)

                        

                        STATS["pass_count"] += 1

                        logger.info(f"[QUICK PASS] Saved {30}+ seconds by skipping images!")

                        

                        if response_type == 'json':

                            return JSONResponse(content=quick_result)

                        return HTMLResponse(content=html)

                        

            except Exception as e:

                logger.error(f"[PC] Price parsing error: {e}")

        

        # Log for pattern analysis

        log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)


        # === AGENT QUICK PASS - Check for plated/filled keywords before AI ===
        try:
            agent_class = get_agent(category)
            if agent_class:
                agent = agent_class()
                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                reason, decision = agent.quick_pass(data, price_float)
                if decision == "PASS":
                    logger.info(f"[AGENT QUICK PASS] {category}: {reason}")
                    quick_result = {
                        'Qualify': 'No',
                        'Recommendation': 'PASS',
                        'reasoning': reason,
                        'confidence': 95,
                        'itemtype': 'Unknown',
                    }
                    html = render_result_html(quick_result, category, title)
                    cache.set(title, total_price, quick_result, html)
                    STATS["pass_count"] += 1
                    if response_type == 'json':
                        return JSONResponse(content=quick_result)
                    return HTMLResponse(content=html)
        except Exception as e:
            logger.error(f"[AGENT QUICK PASS] Error: {e}")

        # === GOLD QUICK PASS CHECK - Skip images if price/gram is clearly too high ===

        if category == "gold":

            try:

                price_float = float(str(total_price).replace('$', '').replace(',', ''))

                

                # Try to extract weight from title (common patterns: "5.5g", "5.5 grams", "5.5 gram")

                weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?|dwt)\b', title.lower())

                if weight_match:

                    title_weight = float(weight_match.group(1))

                    

                    # Convert dwt to grams if needed

                    if 'dwt' in title.lower():

                        title_weight = title_weight * 1.555

                    

                    if title_weight > 0:

                        price_per_gram = price_float / title_weight

                        

                        # If price > $100/gram, instant PASS (way over scrap value)

                        if price_per_gram > 100:

                            logger.info(f"[QUICK PASS] Gold: ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram > $100 - skipping images")

                            

                            quick_result = {

                                'Qualify': 'No',

                                'Recommendation': 'PASS',

                                'reasoning': f"Price ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram exceeds $100/gram ceiling (auto-PASS)",

                                'karat': 'Unknown',

                                'weight': f"{title_weight}g",

                                'goldweight': f"{title_weight}",

                                'meltvalue': 'NA',

                                'maxBuy': 'NA',

                                'sellPrice': 'NA',

                                'Profit': 'NA',

                                'Margin': 'NA',

                                'confidence': 60,

                                'fakerisk': 'Low',

                                'itemtype': 'Unknown',

                                'pricePerGram': f"${price_per_gram:.0f}",

                            }

                            

                            html = render_result_html(quick_result, category, title)

                            cache.set(title, total_price, quick_result, html)

                            

                            STATS["pass_count"] += 1

                            logger.info(f"[QUICK PASS] Saved time by skipping images!")

                            

                            if response_type == 'json':

                                return JSONResponse(content=quick_result)

                            return HTMLResponse(content=html)

                            

            except Exception as e:

                logger.debug(f"[QUICK PASS] Gold check error: {e}")

        

        # ============================================================

        # FAST EXTRACTION - Instant server-side calculations (0ms)

        # Runs BEFORE AI to provide instant math on verified data

        # ============================================================

        fast_result = None

        if FAST_EXTRACT_AVAILABLE and category in ['gold', 'silver']:

            try:

                _fast_start = _time.time()

                price_float = float(str(total_price).replace('$', '').replace(',', ''))

                description = data.get('Description', '') or data.get('description', '')

                # Also check ConditionDescription
                if not description:
                    description = data.get('ConditionDescription', '')
                
                # If no weight in description, try to fetch from eBay API
                # This gets the full listing description where sellers often put weight
                item_id = data.get('ItemId', '') or data.get('itemId', '')
                
                # Extract ItemId from ViewUrl if not directly available
                if not item_id:
                    view_url = data.get('ViewUrl', '') or data.get('viewUrl', '') or data.get('url', '')
                    if view_url and '/itm/' in view_url:
                        try:
                            item_id = view_url.split('/itm/')[-1].split('?')[0].split('/')[0]
                        except:
                            pass
                
                # Check if description has weight keywords
                desc_has_weight = description and any(w in description.lower() for w in ['gram', ' g ', 'dwt', ' oz', 'ounce', 'weight'])
                
                # Fetch full description from eBay if we have item_id and no weight in current description
                if item_id and not desc_has_weight and EBAY_POLLER_AVAILABLE:
                    try:
                        from ebay_poller import get_item_description
                        ebay_desc = await get_item_description(item_id)
                        if ebay_desc:
                            description = ebay_desc
                            logger.info(f"[DESC] Fetched eBay description: {len(ebay_desc)} chars")
                    except Exception as e:
                        logger.debug(f"[DESC] Could not fetch eBay description: {e}")


                

                # Get current spot prices

                spots = get_spot_prices()

                gold_spot = spots.get('gold_oz', 4350)

                silver_spot = spots.get('silver_oz', 75)

                

                if category == 'gold':

                    fast_result = fast_extract_gold(title, price_float, description, gold_spot)

                else:

                    fast_result = fast_extract_silver(title, price_float, description, silver_spot)

                

                _timing['fast_extract'] = _time.time() - _fast_start

                logger.info(f"[FAST] Extraction took {_timing['fast_extract']*1000:.1f}ms")

                

                # Log what we found

                if fast_result.weight_grams:

                    logger.info(f"[FAST] Weight: {fast_result.weight_grams}g from {fast_result.weight_source}")

                if fast_result.karat:

                    logger.info(f"[FAST] Karat: {fast_result.karat}K from {fast_result.karat_source}")

                if fast_result.melt_value:

                    logger.info(f"[FAST] Melt: ${fast_result.melt_value:.0f}, Max: ${fast_result.max_buy:.0f}")

                if fast_result.is_hot:

                    logger.info(f"[FAST] HOT DEAL: {fast_result.hot_reason}")

                if getattr(fast_result, 'has_non_metal', False):

                    logger.info(f"[FAST] NON-METAL DETECTED: '{fast_result.non_metal_type}' - needs AI for weight deductions")

                

                # INSTANT PASS - Don't even run AI (unless best offer is available and close)

                accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']



                # Check if this is a near-miss that could work with best offer

                skip_instant_pass = False

                if fast_result.instant_pass and accepts_offers and fast_result.max_buy and not fast_result.is_plated:

                    gap_percent = ((price_float - fast_result.max_buy) / price_float) * 100 if price_float > 0 else 100

                    # Also check for Native American jewelry

                    native_keywords = ['navajo', 'native american', 'zuni', 'hopi', 'squash blossom',

                                      'southwestern', 'turquoise', 'concho', 'old pawn']

                    is_native = any(kw in title.lower() for kw in native_keywords)

                    max_gap = 20 if is_native else 10



                    if gap_percent <= max_gap:

                        skip_instant_pass = True

                        logger.info(f"[FAST] Skipping instant PASS - best offer available, gap only {gap_percent:.1f}%")



                if fast_result.instant_pass and not skip_instant_pass:

                    logger.info(f"[FAST] INSTANT PASS: {fast_result.pass_reason}")



                    quick_result = {

                        'Qualify': 'No',

                        'Recommendation': 'PASS',

                        'reasoning': f"[FAST EXTRACT] {fast_result.pass_reason}",

                        'karat': str(fast_result.karat) + 'K' if fast_result.karat else 'Unknown',

                        'weight': f"{fast_result.weight_grams}g" if fast_result.weight_grams else 'Unknown',

                        'weightSource': fast_result.weight_source,

                        'goldweight': str(fast_result.weight_grams) if fast_result.weight_grams else 'Unknown',

                        'meltvalue': str(int(fast_result.melt_value)) if fast_result.melt_value else 'NA',

                        'maxBuy': str(int(fast_result.max_buy)) if fast_result.max_buy else 'NA',

                        'confidence': fast_result.confidence,

                        'itemtype': 'Plated' if fast_result.is_plated else 'Unknown',

                    }



                    html = render_result_html(quick_result, category, title)

                    cache.set(title, total_price, quick_result, html, "PASS")



                    STATS["pass_count"] += 1

                    logger.info(f"[FAST] Saved ALL AI time with instant PASS!")

                    

                    if response_type == 'json':

                        return JSONResponse(content=quick_result)

                    return HTMLResponse(content=html)

                    

            except Exception as e:

                logger.error(f"[FAST] Extraction error: {e}")

                fast_result = None

        

        # ============================================================

        # HAIKU PRE-FILTER

        # - Gold/Silver: WITH IMAGES (weight estimation requires visuals)

        # - TCG/LEGO/Video Games: TEXT ONLY (PriceCharting provides pricing)

        # ============================================================



        # Store raw image URLs

        raw_image_urls = data.get('images', [])

        images = []


        # === LAZY IMAGE LOADING OPTIMIZATION ===
        # For gold/silver, only fetch images if AI actually needs them:
        # - No verified weight (AI needs to read scale photos)
        # - Has non-metal content (AI needs to assess deductions)
        # - Weight from estimate (needs visual verification)
        # Skip images if we have clean verified weight + clear math result

        needs_images_for_tier1 = False
        skip_ai_entirely = False

        if category in ['gold', 'silver']:
            if fast_result is None:
                # No fast extraction - need AI with images
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: no fast_result")
            elif getattr(fast_result, 'has_non_metal', False):
                # Non-metal detected - AI needs images to assess deductions
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: has non-metal ({fast_result.non_metal_type})")
            elif fast_result.weight_grams is None:
                # No weight found - AI needs to estimate from scale
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: no weight in title")
            elif fast_result.weight_source == 'estimate':
                # Estimated weight - needs verification
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: weight is estimated")
            elif fast_result.max_buy and price_float > fast_result.max_buy * 1.3:
                # Verified weight + price 30%+ over max buy = clear PASS, skip AI entirely
                skip_ai_entirely = True
                logger.info(f"[LAZY] SKIP AI: verified weight {fast_result.weight_grams}g, price ${price_float:.0f} > maxBuy ${fast_result.max_buy:.0f} x 1.3")

                quick_result = {
                    'Qualify': 'No',
                    'Recommendation': 'PASS',
                    'reasoning': f"[FAST] Verified {fast_result.weight_grams}g {fast_result.karat}K = ${fast_result.melt_value:.0f} melt, maxBuy ${fast_result.max_buy:.0f} < price ${price_float:.0f}",
                    'karat': f"{fast_result.karat}K" if fast_result.karat else 'Unknown',
                    'weight': f"{fast_result.weight_grams}g",
                    'weightSource': fast_result.weight_source,
                    'goldweight': str(fast_result.weight_grams),
                    'meltvalue': str(int(fast_result.melt_value)) if fast_result.melt_value else 'NA',
                    'maxBuy': str(int(fast_result.max_buy)) if fast_result.max_buy else 'NA',
                    'Profit': str(int(fast_result.max_buy - price_float)) if fast_result.max_buy else 'NA',
                    'confidence': fast_result.confidence,
                    'category': category,
                }

                html = render_result_html(quick_result, category, title)
                cache.set(title, total_price, quick_result, html, "PASS")
                STATS["pass_count"] += 1

                _timing['total'] = _time.time() - _start_time
                logger.info(f"[LAZY] Saved {2 + 4:.0f}+ seconds (no images, no AI) - PASS in {_timing['total']*1000:.0f}ms")

                if response_type == 'json':
                    return JSONResponse(content=quick_result)
                return HTMLResponse(content=html)
            else:
                # Have verified weight, price is close - need AI to verify
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: price ${price_float:.0f} near maxBuy ${fast_result.max_buy:.0f}, need AI verification")

        if needs_images_for_tier1 and raw_image_urls:

            _img_start = _time.time()

            # Gold/silver: Use first_last selection (scale photos often at end of eBay listings)

            # More images + larger size for better scale reading with GPT-4o

            max_imgs = getattr(IMAGES, 'max_images_gold_silver', 5)

            img_size = getattr(IMAGES, 'resize_for_gold_silver', 512)

            logger.info(f"[TIER1] Fetching up to {max_imgs} images for GPT-4o (gold/silver - first+last for scale photos)...")

            images = await process_image_list(

                raw_image_urls,

                max_size=img_size,

                max_count=max_imgs,

                selection="first_last"  # Scale photos often at end of eBay listings!

            )

            _timing['images'] = _time.time() - _img_start

            logger.info(f"[TIMING] Image fetch + resize: {_timing['images']*1000:.0f}ms ({len(images)} images)")

        

        # Build prompt

        category_prompt = get_category_prompt(category)

        listing_text = format_listing_data(data)

        

        # Inject FAST EXTRACT data if available - AI doesn't need to re-calculate

        fast_context = ""

        if fast_result and (fast_result.weight_grams or fast_result.karat or fast_result.melt_value):

            fast_context = "\n\n=== SERVER PRE-CALCULATED (VERIFIED FROM TITLE) ===\n"

            if fast_result.karat:

                fast_context += f"VERIFIED KARAT: {fast_result.karat}K (from {fast_result.karat_source})\n"

            if fast_result.weight_grams:

                fast_context += f"VERIFIED WEIGHT: {fast_result.weight_grams}g (from {fast_result.weight_source})\n"

            if fast_result.melt_value:

                fast_context += f"CALCULATED MELT: ${fast_result.melt_value:.0f}\n"

                fast_context += f"CALCULATED MAX BUY: ${fast_result.max_buy:.0f}\n"

            if fast_result.is_hot:

                fast_context += f"HOT DEAL FLAG: {fast_result.hot_reason}\n"



            # CRITICAL: Alert AI if non-metal detected - weight needs deductions!

            if getattr(fast_result, 'has_non_metal', False):

                fast_context += f"\n⚠️ NON-METAL DETECTED: '{fast_result.non_metal_type}'\n"

                # If we have stated weight, tell AI to deduct FROM it, not estimate higher
                if fast_result.weight_grams and fast_result.weight_source in ['title', 'description']:
                    fast_context += f"STATED WEIGHT: {fast_result.weight_grams}g from {fast_result.weight_source} - TRUST THIS VALUE!\n"
                    fast_context += "Deduct stone/pearl weight FROM the stated weight to get actual gold/silver weight.\n"
                    fast_context += "DO NOT estimate a higher total weight - the seller's stated weight is authoritative.\n"
                else:
                    fast_context += "The stated weight likely INCLUDES non-metal components!\n"
                    fast_context += "You MUST deduct weight for stones/pearls/movement/beads before calculating melt.\n"
                    fast_context += "The pre-calculated melt above assumes ALL weight is metal - RECALCULATE after deductions!\n"

            else:

                fast_context += "USE THESE VALUES - they are extracted from title and verified.\n"

                fast_context += "Only override if you see CONFLICTING info in images (different weight on scale).\n"

            logger.info(f"[FAST] Injecting verified data into AI prompt")

        

        # Inject PriceCharting context for TCG/LEGO/videogames

        if pc_context:

            user_message = f"{category_prompt}\n\n{pc_context}{fast_context}\n\n{listing_text}"

            logger.info("[PC] Injected PriceCharting context into prompt")

        elif fast_context:

            user_message = f"{category_prompt}{fast_context}\n\n{listing_text}"

        else:

            user_message = f"{category_prompt}\n\n{listing_text}"

        

        # Build message content - include images for gold/silver

        if images:

            message_content = [{"type": "text", "text": user_message}]

            message_content.extend(images[:5])  # Max 5 images

        else:

            message_content = user_message

        

        # ============================================================

        # TIER 1 MODEL SELECTION (Category-Aware)

        # Gold/Silver: GPT-4o (smarter at weight/scale reading)

        # Other categories: GPT-4o-mini (cheaper, still effective)

        # Falls back to Haiku if OpenAI client unavailable

        # ============================================================

        # OPTIMIZATION: Pre-fetch Tier 2 images during Tier 1 (saves 500ms-4s)
        # Images will be ready when Tier 2 starts, instead of fetching after Tier 1
        tier2_images_task = None
        if raw_image_urls and category in ['gold', 'silver']:
            tier2_images_task = asyncio.create_task(
                process_image_list(raw_image_urls, max_size=IMAGES.resize_for_tier2, selection="first_last")
            )
            logger.debug(f"[OPTIMIZATION] Pre-fetching Tier 2 images in background...")

        _tier1_start = _time.time()



        # Select model based on category

        if category in ('gold', 'silver'):

            tier1_model = TIER1_MODEL_GOLD_SILVER

            tier1_cost = COST_PER_CALL_GPT4O

        else:

            tier1_model = TIER1_MODEL_DEFAULT

            tier1_cost = COST_PER_CALL_GPT4O_MINI



        if openai_client:
            # Check hourly budget before making OpenAI call
            if not check_openai_budget(tier1_cost):
                logger.warning(f"[TIER1] SKIPPED due to budget limit - returning instant PASS")
                return {
                    "Recommendation": "PASS",
                    "Qualify": "No",
                    "reasoning": "Analysis skipped - hourly OpenAI budget exceeded",
                    "confidence": "Low",
                    "budget_skip": True,
                }

            logger.info(f"[TIER1] Calling {tier1_model} for {category}...")

            

            # Convert images to OpenAI format if present

            openai_messages = []

            # Gold/silver: Use HIGH detail for better scale reading, more tokens for reasoning

            # Other categories: Use LOW detail for speed

            is_precious_metal = category in ('gold', 'silver')

            image_detail = "high" if is_precious_metal else "low"

            max_tokens = 800 if is_precious_metal else 500  # More tokens for complex gold/silver reasoning



            if images:

                openai_content = [{"type": "text", "text": user_message}]

                for img in images[:6]:  # Allow up to 6 images

                    if img.get("type") == "image":

                        # Convert Claude format to OpenAI format

                        openai_content.append({

                            "type": "image_url",

                            "image_url": {

                                "url": f"data:{img['source']['media_type']};base64,{img['source']['data']}",

                                "detail": image_detail

                            }

                        })

                openai_messages = [{"role": "user", "content": openai_content}]

            else:

                openai_messages = [{"role": "user", "content": user_message}]



            try:

                response = await openai_client.chat.completions.create(

                    model=tier1_model,

                    max_tokens=max_tokens,

                    response_format={"type": "json_object"},  # Force JSON output

                    messages=[

                        {"role": "system", "content": get_agent_prompt(category)},

                        *openai_messages

                    ]

                )

                raw_response = response.choices[0].message.content

                if raw_response:

                    raw_response = raw_response.strip()

                else:

                    logger.error(f"[TIER1] GPT-4o returned empty response!")

                    raw_response = '{"Recommendation": "RESEARCH", "reasoning": "Empty AI response"}'

                STATS["session_cost"] += tier1_cost
                record_openai_cost(tier1_cost)  # Track hourly budget

                tier1_model_used = tier1_model.upper()

            except Exception as e:

                logger.error(f"[TIER1] {tier1_model} failed, falling back to Haiku: {e}")

                # Fallback to Haiku

                response = await client.messages.create(

                    model=MODEL_FAST,

                    max_tokens=500,

                    system=get_agent_prompt(category),

                    messages=[{"role": "user", "content": message_content}]

                )

                raw_response = response.content[0].text.strip()

                STATS["session_cost"] += COST_PER_CALL_HAIKU

                tier1_model_used = "Haiku (fallback)"

        else:

            # Fallback to Haiku if OpenAI client not available

            logger.info(f"[TIER1] Calling Haiku for {category} (OpenAI not configured)...")

            response = await client.messages.create(

                model=MODEL_FAST,

                max_tokens=500,

                system=get_agent_prompt(category),

                messages=[{"role": "user", "content": message_content}]

            )

            raw_response = response.content[0].text.strip()

            STATS["session_cost"] += COST_PER_CALL_HAIKU

            tier1_model_used = "Haiku"

        

        _timing['tier1'] = _time.time() - _tier1_start

        logger.info(f"[TIMING] Tier 1 ({tier1_model_used}): {_timing['tier1']*1000:.0f}ms")

        

        response_text = sanitize_json_response(raw_response)

        

        try:

            result = json.loads(response_text)



            if 'reasoning' in result:

                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')


            # === AGENT RESPONSE VALIDATION ===
            agent_class = get_agent(category)
            if agent_class:
                agent = agent_class()
                result = agent.validate_response(result)

            # Add listing price to result for display

            result['listingPrice'] = total_price



            # === CAPTURE TIER 1 ORIGINAL RECOMMENDATION BEFORE ANY VALIDATION ===

            tier1_original_rec = result.get('Recommendation', 'RESEARCH')

            logger.info(f"[TIER1] {tier1_model_used} original recommendation: {tier1_original_rec}")

            

            # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong

            _validation_start = _time.time()

            result = validate_and_fix_margin(result, total_price, category, title, data)

            _timing['validation'] = _time.time() - _validation_start

            logger.info(f"[TIMING] Validation: {_timing['validation']*1000:.0f}ms")

            

            # TCG/LEGO VALIDATION: Normalize keys and override with PriceCharting data if available

            if category in ["tcg", "lego"]:

                try:

                    price_float = float(str(total_price).replace('$', '').replace(',', ''))

                    result = validate_tcg_lego_result(result, pc_result, price_float, category, title)

                except Exception as e:

                    logger.error(f"[PC] TCG/LEGO validation error: {e}")

            

            # VIDEO GAMES VALIDATION: Check math and professional sellers

            if category == "videogames":

                try:

                    price_float = float(str(total_price).replace('$', '').replace(',', ''))

                    result = validate_videogame_result(result, pc_result, price_float, data)

                except Exception as e:

                    logger.error(f"[VG] Video game validation error: {e}")

            

            recommendation = result.get('Recommendation', 'RESEARCH')

            

            # ============================================================

            # TIER 2 RE-ANALYSIS (Sonnet for BUY/RESEARCH)

            # PARALLEL MODE: Run Sonnet in background, return Haiku immediately

            # SEQUENTIAL MODE: Wait for Sonnet before returning

            # ============================================================

            

            # Check if we have a HOT deal from fast_extract (verified math)

            is_hot_deal = fast_result and fast_result.is_hot if fast_result else False

            

            # Force Tier 2 for gold/silver items where Haiku couldn't estimate weight

            gold_weight_na = result.get('goldweight', '') in ['NA', 'na', '', None, '0']

            silver_weight_na = result.get('silverweight', '') in ['NA', 'na', '', None, '0'] 

            weight_na = result.get('weight', '') in ['NA', 'na', '', None, '0']

            force_tier2_for_na_weight = (

                category in ['gold', 'silver'] and 

                (gold_weight_na or silver_weight_na or weight_na) and

                float(str(total_price).replace('$', '').replace(',', '') or 0) > 100

            )

            

            if force_tier2_for_na_weight:

                logger.info(f"[TIER2] Forcing Tier 2: Gold/silver item with NA weight - needs image analysis")

            

            # Determine if Tier 2 should run

            should_run_tier2 = (

                TIER2_ENABLED and 

                (tier1_original_rec in ("BUY", "RESEARCH") or recommendation in ("BUY", "RESEARCH") or force_tier2_for_na_weight)

            )

            

            # Skip Tier 2 for HOT deals if configured (math is verified)

            if is_hot_deal and SKIP_TIER2_FOR_HOT:

                logger.info(f"[TIER2] HOT DEAL - Skipping Tier 2 (verified math from title)")

                should_run_tier2 = False

                # Add HOT flag to result

                result['hot_deal'] = True

                result['reasoning'] = f"HOT DEAL (verified): {fast_result.hot_reason}\n" + result.get('reasoning', '')

            

            logger.info(f"[TIER2] Check: TIER2_ENABLED={TIER2_ENABLED}, parallel={PARALLEL_MODE}, haiku={tier1_original_rec}, hot={is_hot_deal}, should_run={should_run_tier2}")

            

            # ============================================================

            # SMART MODE: Skip Tier 2 for verified high-margin deals, wait for uncertain ones

            # ============================================================

            # Check if this is a VERIFIED deal that doesn't need Tier 2

            weight_source = result.get('weightSource', 'estimated')

            profit_val = 0

            try:

                profit_str = result.get('Profit', result.get('Margin', '0'))

                profit_val = float(str(profit_str).replace('$', '').replace('+', '').replace(',', ''))

            except:

                pass



            # Skip Tier 2 for verified deals: stated weight + significant profit + BUY recommendation
            # NOTE: 'scale' is NOT trusted for fast-track because AI scale reading is unreliable
            # Only trust weight that's explicitly stated in the title text itself
            # NOTE: API listings NEVER fast-track - they need full Tier 2 verification for stone detection

            is_from_api = data.get('source') == 'ebay_api'

            is_verified_deal = (

                category in ['gold', 'silver'] and

                weight_source in ['stated', 'title'] and  # Removed 'description' and 'scale' - less reliable

                profit_val >= 75 and  # At least $75 profit

                recommendation == 'BUY' and

                not is_from_api  # API listings always need Tier 2 verification

            )



            if is_verified_deal:

                logger.info(f"[FAST-TRACK] Verified deal: {weight_source} weight, ${profit_val:.0f} profit - SKIPPING Tier 2")

                should_run_tier2 = False

                result['fast_tracked'] = True

                result['reasoning'] = f"[FAST-TRACK: Verified {weight_source} weight, ${profit_val:.0f} profit]\n" + result.get('reasoning', '')

            # OPTIMIZATION: Skip Tier 2 for high-confidence PASS (no need to re-verify obvious rejections)
            tier1_conf_val = 0
            try:
                tier1_conf = result.get('confidence', '0')
                if isinstance(tier1_conf, str):
                    tier1_conf_val = int(tier1_conf) if tier1_conf.isdigit() else 0
                else:
                    tier1_conf_val = int(tier1_conf)
            except:
                pass

            if should_run_tier2 and recommendation == 'PASS' and tier1_conf_val >= 80:
                logger.info(f"[OPTIMIZATION] Skipping Tier 2 - High confidence PASS ({tier1_conf_val}%)")
                should_run_tier2 = False
                result['high_conf_skip'] = True

            use_parallel = False  # Don't use background parallel - either skip Tier 2 or wait for it



            if should_run_tier2 and use_parallel:

                # DISABLED: This block no longer executes

                logger.info(f"[PARALLEL] Starting background Sonnet verification (gold/silver - speed matters)...")

                logger.info(f"[PARALLEL] Returning Haiku result immediately for SPEED")



                price_float = float(str(total_price).replace('$', '').replace(',', ''))



                # Start Sonnet in background (non-blocking)

                asyncio.create_task(background_sonnet_verify(

                    title=title,

                    price=price_float,

                    category=category,

                    haiku_result=result.copy(),

                    raw_image_urls=raw_image_urls,

                    data=data,

                    fast_result=fast_result

                ))



                # Mark result as pending verification

                result['tier2_status'] = 'PENDING'

                result['reasoning'] = f"[HAIKU - Sonnet verifying in background]\n{result.get('reasoning', '')}"



                # DON'T wait for Tier 2 - continue to return Haiku result

                should_run_tier2 = False  # Skip the sequential Tier 2 below



            if should_run_tier2 and category in ['lego', 'tcg', 'videogames', 'gold', 'silver']:

                # For LEGO/TCG/VideoGames: ALWAYS wait for Sonnet before returning BUY

                # PriceCharting prices can be wrong (wrong condition tier, outdated, etc.)

                logger.info(f"[TIER2] ⏳ WAITING for Sonnet verification ({category} - PriceCharting needs validation)...")

                # Don't set should_run_tier2 = False - let it continue to sequential mode below

            

            # ============================================================

            # SEQUENTIAL MODE: Wait for Tier 2 before returning

            # ============================================================

            # Cancel pre-fetch if Tier 2 is not running (avoid wasted resources)
            if not should_run_tier2 and tier2_images_task and not tier2_images_task.done():
                tier2_images_task.cancel()
                logger.debug(f"[OPTIMIZATION] Cancelled unused image pre-fetch")

            if should_run_tier2:

                logger.info(f"[TIER2] *** MANDATORY SONNET VERIFICATION STARTING ***")

                logger.info(f"[TIER1] Tier1: {tier1_original_rec}, Post-validation: {recommendation} - triggering Tier 2 verification...")

                

                # Fetch images for Sonnet using first_last strategy

                # Scale photos are often at the END of eBay listings

                _img_start = _time.time()

                if tier2_images_task:
                    # OPTIMIZATION: Use pre-fetched images (started during Tier 1)
                    images = await tier2_images_task
                    logger.info(f"[OPTIMIZATION] Using pre-fetched images: {len(images)} images @ {IMAGES.resize_for_tier2}px")
                elif raw_image_urls:
                    logger.info(f"[TIER2] Fetching images using first_last strategy (first 3 + last 3 of {len(raw_image_urls)} total)...")
                    # Use first_last selection: first 3 + last 3 images (scale photos often at end)
                    images = await process_image_list(raw_image_urls, max_size=IMAGES.resize_for_tier2, selection="first_last")
                    logger.info(f"[TIER2] Fetched {len(images)} images @ {IMAGES.resize_for_tier2}px")

                _timing['images'] = _time.time() - _img_start

                logger.info(f"[TIMING] Image fetch (for Tier2): {_timing['images']*1000:.0f}ms")

                

                price_float = float(str(total_price).replace('$', '').replace(',', ''))

                _tier2_start = _time.time()

                

                # Use OpenAI or Claude based on config

                if TIER2_PROVIDER == "openai" and openai_client:

                    logger.info(f"[TIER2] Using OpenAI {OPENAI_TIER2_MODEL} for FAST verification...")

                    result = await tier2_reanalyze_openai(

                        title=title,

                        price=price_float,

                        category=category,

                        tier1_result=result,

                        images=images,

                        data=data,

                        system_prompt=get_agent_prompt(category)

                    )

                    _timing['tier2'] = _time.time() - _tier2_start

                    logger.info(f"[TIMING] Tier 2 OpenAI: {_timing['tier2']*1000:.0f}ms")

                else:

                    result = await tier2_reanalyze(

                        title=title,

                        price=price_float,

                        category=category,

                        tier1_result=result,

                        images=images,

                        data=data,

                        system_prompt=get_agent_prompt(category)

                    )

                    _timing['tier2'] = _time.time() - _tier2_start

                    logger.info(f"[TIMING] Tier 2 Sonnet: {_timing['tier2']*1000:.0f}ms")

                # Update recommendation after Tier 2

                recommendation = result.get('Recommendation', 'RESEARCH')

                logger.info(f"[TIER2] Final recommendation: {recommendation}")


            # ============================================================
            # USER PRICE CORRECTION OVERRIDE
            # ============================================================
            if user_price_correction and recommendation in ("BUY", "RESEARCH"):
                try:
                    listing_price = float(str(total_price).replace('$', '').replace(',', ''))
                    user_market = user_price_correction['market_price']
                    deal_threshold = user_market * 0.65  # Need 35% margin for BUY

                    if listing_price >= deal_threshold:
                        old_rec = recommendation
                        recommendation = "PASS"
                        result['Recommendation'] = "PASS"
                        result['user_correction_applied'] = True
                        result['user_market_price'] = user_market
                        result['reasoning'] = f"User correction: Market is ${user_market}. Listing at ${listing_price} is not a deal (need <${deal_threshold:.2f}). {result.get('reasoning', '')}"
                        logger.info(f"[PRICE OVERRIDE] {old_rec} -> PASS due to user correction: market=${user_market}, listing=${listing_price}")
                    else:
                        # It's below our threshold - still a potential deal!
                        result['user_market_price'] = user_market
                        result['user_correction_validated'] = True
                        logger.info(f"[PRICE VALIDATED] Listing ${listing_price} is below user market ${user_market} - keeping {recommendation}")
                except Exception as e:
                    logger.warning(f"[PRICE OVERRIDE] Error applying correction: {e}")

            # Update stats

            if recommendation == "BUY":

                STATS["buy_count"] += 1

            elif recommendation == "PASS":

                STATS["pass_count"] += 1

            else:

                STATS["research_count"] += 1

            

            # Create listing record

            # Include image URLs but not full base64 data

            input_data_clean = {k: v for k, v in data.items() if k != 'images'}

            

            # Extract just the URLs from images for thumbnail

            # uBuyFirst sends images as HTTP URLs or data URLs

            raw_images = data.get('images', [])

            if raw_images:

                image_urls = []

                for img in raw_images[:3]:  # Just first 3 URLs

                    if isinstance(img, str):

                        if img.startswith('http'):

                            image_urls.append(img)

                        # Skip data URLs - too large for thumbnails

                    elif isinstance(img, dict):

                        # Handle dict format {'url': '...', 'URL': '...'}

                        url = img.get('url', img.get('URL', img.get('src', '')))

                        if url and url.startswith('http'):

                            image_urls.append(url)

                if image_urls:

                    input_data_clean['images'] = image_urls

                    logger.info(f"[THUMBNAIL] Stored {len(image_urls)} image URLs for deal")

            

            # Get eBay item ID and gallery URL for thumbnails

            ebay_item_id = data.get('ItemId', data.get('itemId', ''))

            gallery_url = data.get('GalleryURL', data.get('galleryURL', data.get('PictureURL', '')))

            ebay_view_url = data.get('ViewUrl', data.get('CheckoutUrl', ''))

            

            # Store these for the API

            input_data_clean['ebay_item_id'] = ebay_item_id

            input_data_clean['gallery_url'] = gallery_url

            input_data_clean['ebay_url'] = ebay_view_url

            

            if gallery_url:

                logger.info(f"[THUMBNAIL] GalleryURL: {gallery_url[:60]}...")

            

            listing_record = {

                "id": listing_id,

                "timestamp": timestamp,

                "title": title,

                "total_price": total_price,

                "category": category,

                "recommendation": recommendation,

                "margin": result.get('Profit', result.get('Margin', 'NA')),

                "confidence": result.get('confidence', 'NA'),

                "reasoning": result.get('reasoning', ''),

                "raw_response": raw_response,

                "input_data": input_data_clean

            }

            

            STATS["listings"][listing_id] = listing_record

            _trim_listings()

            

            # Save to database

            save_listing(listing_record)

            

            # Broadcast to live dashboard via WebSocket

            try:

                await broadcast_new_listing(

                    listing={"title": title, "price": total_price, "category": category},

                    analysis=result

                )

                logger.debug(f"[WS] Broadcasted listing to live dashboard")

            except Exception as e:

                logger.debug(f"[WS] Broadcast error (no clients?): {e}")

            

            # Update pattern analytics with margin and confidence

            margin_val = result.get('Profit', result.get('Margin', '0'))

            conf_val = result.get('confidence', '')

            update_pattern_outcome(title, category, recommendation, margin_val, conf_val, alias)

            

            # Add price for display

            result['listingPrice'] = total_price

            

            # Add category to result

            result['category'] = category

            

            # Add default pcMatch for TCG/LEGO if not set

            if category in ["tcg", "lego"] and 'pcMatch' not in result:

                result['pcMatch'] = 'No'

                result['pcProduct'] = ''

                result['pcConfidence'] = ''

            

            # Render HTML

            html = render_result_html(result, category, title)

            

            # Store in smart cache

            cache.set(title, total_price, result, html, recommendation, category)

            

            # Signal completion to any waiting requests

            request_key = f"{title}|{total_price}"

            if request_key in IN_FLIGHT:

                IN_FLIGHT_RESULTS[request_key] = (result, html)

                IN_FLIGHT[request_key].set()

                logger.info(f"[IN-FLIGHT] Signaled completion for waiting requests")

                # Clean up after a delay (let waiting requests grab the result)

                async def cleanup_in_flight(key):

                    await asyncio.sleep(5)

                    IN_FLIGHT.pop(key, None)

                    IN_FLIGHT_RESULTS.pop(key, None)

                asyncio.create_task(cleanup_in_flight(request_key))

            

            logger.info(f"Result: {recommendation}")

            logger.info(f"[RESPONSE] Keys: {list(result.keys())}")

            

            # ============================================================

            # DISCORD ALERT FOR BUY ONLY

            # CRITICAL: Only send Discord AFTER Sonnet verification

            # In parallel mode, the background_sonnet_verify task handles Discord

            # ============================================================

            

            # Check if this is parallel mode (Sonnet running in background)

            is_parallel_pending = result.get('tier2_status') == 'PENDING'

            

            # Check if this is from API - API handler sends its own Discord alerts
            is_from_api = data.get('source') == 'ebay_api'

            if is_parallel_pending:

                # SKIP Discord here - background Sonnet will send alert after verification

                logger.info(f"[DISCORD] Skipping immediate alert - Sonnet verifying in background")

                logger.info(f"[DISCORD] Tier1 said {recommendation} but waiting for Sonnet confirmation")

            elif is_from_api:
                # SKIP Discord here - API handler sends its own alert with [API] prefix
                logger.info(f"[DISCORD] Skipping - API listing has its own Discord handler")

            elif recommendation == "BUY":

                logger.info(f"[DISCORD] Post-Tier2 recommendation: {recommendation} (Tier1 was: {tier1_original_rec})")

                try:

                    # Get list price (ItemPrice) for eBay lookup - NOT TotalPrice which includes shipping

                    item_price_str = data.get('ItemPrice', data.get('TotalPrice', '0'))

                    list_price = float(str(item_price_str).replace('$', '').replace(',', ''))

                    

                    # Use ViewUrl from uBuyFirst data first (direct link to item)
                    ebay_item_url = data.get('ViewUrl', data.get('CheckoutUrl', ''))
                    
                    # URL decode if needed (uBuyFirst sometimes sends encoded URLs)
                    if ebay_item_url:
                        from urllib.parse import unquote
                        ebay_item_url = unquote(ebay_item_url.replace('+', ' '))
                        logger.info(f"[EBAY] Using ViewUrl from data: {ebay_item_url[:80]}...")
                    
                    # Fallback: Try seller-based eBay API lookup (most accurate for uBuyFirst)
                    if not ebay_item_url:
                        seller_name = data.get('SellerName', data.get('SellerUserID', ''))
                        if seller_name:
                            logger.info(f"[EBAY] Attempting seller-based lookup for '{seller_name}'...")
                            ebay_item_url = await lookup_ebay_item_by_seller(title, seller_name, list_price)
                    
                    # Fallback: Try title-only eBay API lookup
                    if not ebay_item_url:
                        ebay_item_url = await lookup_ebay_item(title, list_price)

                    # Final fallback to search URL
                    if not ebay_item_url:
                        ebay_item_url = get_ebay_search_url(title)
                        logger.info(f"[EBAY] Using search fallback: {ebay_item_url[:60]}...")

                    

                    # Get first image URL from RAW data (not processed base64)

                    first_image = None

                    raw_images = data.get('images', [])

                    if raw_images:

                        for img in raw_images:

                            if isinstance(img, str) and img.startswith('http'):

                                first_image = img

                                break

                            elif isinstance(img, dict):

                                url = img.get('url', img.get('URL', img.get('src', '')))

                                if url and url.startswith('http'):

                                    first_image = url

                                    break

                    

                    if first_image:

                        logger.info(f"[DISCORD] Thumbnail URL: {first_image[:60]}...")

                    

                    # Extract profit from result

                    profit_val = result.get('Profit', result.get('profit', result.get('estimatedProfit', 0)))

                    try:

                        if isinstance(profit_val, str):

                            profit_val = float(profit_val.replace('$', '').replace(',', '').replace('%', '').replace('+', ''))

                        else:

                            profit_val = float(profit_val) if profit_val else 0

                    except:

                        profit_val = 0

                    

                    margin_str = result.get('margin', result.get('Margin', ''))

                    

                    # Build extra data for category-specific fields

                    extra_data = {}

                    if category == 'gold':

                        extra_data['karat'] = result.get('karat', '')

                        extra_data['weight'] = result.get('goldweight', result.get('weight', ''))

                        extra_data['melt'] = result.get('meltvalue', '')

                    elif category == 'silver':

                        extra_data['weight'] = result.get('weight', '')

                        extra_data['melt'] = result.get('meltvalue', '')

                    elif category in ['lego', 'tcg', 'videogames']:

                        extra_data['market_price'] = result.get('marketprice', result.get('market_price', ''))

                        extra_data['set_number'] = result.get('SetNumber', result.get('set_number', ''))


                    # Build seller info for purchase logging
                    seller_info = {
                        'seller_id': data.get('SellerUserID', '') or data.get('Seller', ''),
                        'feedback_score': data.get('SellerFeedback', ''),
                        'feedback_percent': data.get('FeedbackRating', ''),
                        'seller_type': data.get('SellerType', ''),
                    }

                    # Build listing info for purchase logging
                    listing_info = {
                        'item_id': item_id,
                        'condition': data.get('Condition', ''),
                        'posted_time': data.get('PostedTime', '') or data.get('StartTime', ''),
                    }

                    # Send Discord alert (non-blocking)

                    asyncio.create_task(send_discord_alert(

                        title=title,

                        price=price_float,

                        recommendation=recommendation,

                        category=category,

                        profit=profit_val,

                        margin=str(margin_str),

                        reasoning=result.get('reasoning', ''),

                        ebay_url=ebay_item_url,

                        image_url=first_image,

                        confidence=result.get('confidence', ''),

                        extra_data=extra_data,

                        seller_info=seller_info,

                        listing_info=listing_info

                    ))

                    

                except Exception as e:

                    logger.error(f"[DISCORD] Alert error: {e}")

            

            # Use saved response_type (saved early in the function)

            logger.info(f"[RESPONSE] response_type: {response_type}")

            # === HIGH-VALUE GOLD JEWELRY CHECK ===
            # Force RESEARCH for gold items that might have hidden value
            # (karat + premium stones + high price + possible scale photo)
            if category == 'gold' and result.get('Recommendation') == 'PASS':
                try:
                    price_val = float(str(total_price).replace('$', '').replace(',', ''))
                    title_lower = title.lower()

                    # Check for karat indicators
                    has_karat = any(k in title_lower for k in ['10k', '14k', '18k', '22k', '24k', '10kt', '14kt', '18kt', '22kt', '24kt', 'solid gold'])

                    # Check for premium stone indicators
                    premium_stones = ['diamond', 'sapphire', 'ruby', 'emerald', 'opal', 'tanzanite', 'aquamarine', 'topaz', 'garnet', 'amethyst', 'pearl']
                    has_premium = any(stone in title_lower for stone in premium_stones)

                    # Check for scale/weight photo indicators
                    scale_hints = ['scale', 'gram', 'grams', 'weigh', 'dwt', 'pennyweight']
                    has_scale_hint = any(hint in title_lower for hint in scale_hints)

                    # Also check description for scale hints
                    desc_lower = str(data.get('Description', '')).lower()
                    has_scale_in_desc = any(hint in desc_lower for hint in scale_hints)

                    # If price > $300 AND has karat AND (has premium stones OR has scale hints), force RESEARCH
                    if price_val > 300 and has_karat and (has_premium or has_scale_hint or has_scale_in_desc):
                        logger.warning(f"[HIGH-VALUE GOLD] Forcing RESEARCH: ${price_val:.0f}, karat={has_karat}, premium={has_premium}, scale_hint={has_scale_hint or has_scale_in_desc}")
                        result['Recommendation'] = 'RESEARCH'
                        result['Qualify'] = 'Maybe'
                        original_reasoning = result.get('reasoning', '')
                        result['reasoning'] = f"[HIGH-VALUE GOLD OVERRIDE] Price ${price_val:.0f} with karat + premium indicators - needs manual weight verification. Original: {original_reasoning}"
                        result['tier2_override'] = True
                        result['tier2_reason'] = 'High-value gold jewelry flagged for manual review'
                        # Re-render HTML with updated result
                        html = render_result_html(result, category, title)
                except Exception as e:
                    logger.error(f"[HIGH-VALUE GOLD] Check error: {e}")

            # === EXPENSIVE MIXED LOT CHECK ===
            # Flag mixed precious metals lots over $1000 as RESEARCH
            # These often contain multiple karats (10K, 14K, 18K) and/or sterling
            if category in ['gold', 'silver'] and result.get('Recommendation') == 'PASS':
                try:
                    price_val = float(str(total_price).replace('$', '').replace(',', ''))
                    title_lower = title.lower()
                    
                    # Check for lot/mixed indicators
                    is_lot = any(term in title_lower for term in ['lot', 'mixed', 'collection', 'estate', 'assorted', 'bulk'])
                    
                    # Check for multiple karats (indicates mixed lot)
                    karat_indicators = ['10k', '14k', '18k', '22k', '24k', '925', 'sterling', '.925']
                    karats_found = sum(1 for k in karat_indicators if k in title_lower)
                    is_mixed_metals = karats_found >= 2  # Has 2+ different metal types
                    
                    # Flag expensive mixed lots (over $1000) as RESEARCH
                    if price_val >= 1000 and (is_lot or is_mixed_metals):
                        logger.warning(f"[EXPENSIVE MIXED LOT] Forcing RESEARCH: ${price_val:.0f}, lot={is_lot}, mixed_metals={is_mixed_metals}, karats_found={karats_found}")
                        result['Recommendation'] = 'RESEARCH'
                        result['Qualify'] = 'Maybe'
                        original_reasoning = result.get('reasoning', '')
                        result['reasoning'] = f"[EXPENSIVE MIXED LOT] ${price_val:.0f} mixed precious metals lot - needs manual weight breakdown by karat. " + original_reasoning
                        result['tier2_override'] = True
                        result['tier2_reason'] = 'Expensive mixed lot flagged for manual review'
                        html = render_result_html(result, category, title)
                except Exception as e:
                    logger.error(f"[EXPENSIVE MIXED LOT] Check error: {e}")

            logger.info(f"[RESPONSE] FINAL Recommendation: {result.get('Recommendation')} (this should be post-Tier2)")

            

            # Log total timing breakdown

            _total_time = _time.time() - _start_time

            _timing['total'] = _total_time

            timing_summary = " | ".join([f"{k}:{v*1000:.0f}ms" for k, v in _timing.items()])

            logger.info(f"[TIMING] TOTAL: {_total_time*1000:.0f}ms | {timing_summary}")

            # Add listing enhancements to result
            result['freshness_minutes'] = listing_enhancements.get('freshness_minutes')
            result['freshness_score'] = listing_enhancements.get('freshness_score')
            result['best_offer'] = listing_enhancements.get('best_offer')
            result['seller_score'] = listing_enhancements.get('seller_score')
            result['seller_type'] = listing_enhancements.get('seller_type')
            result['seller_recommendation'] = listing_enhancements.get('seller_recommendation')

            if listing_enhancements.get('seller_score', 0) >= 70:
                logger.info(f"[ENHANCEMENTS] HIGH-VALUE SELLER: score={listing_enhancements.get('seller_score')}, type={listing_enhancements.get('seller_type')}")

            # Mark as evaluated to prevent duplicate processing
            mark_as_evaluated(title, total_price, result)

            # ALWAYS include html in result for uBuyFirst display_template
            # This ensures JSON response has both column data AND html for display
            if 'html' not in result:
                result['html'] = html

            if response_type == 'json':

                # Return JSON with all fields INCLUDING html for display_template

                logger.info("[RESPONSE] Returning JSON (response_type=json) with html field for display")

                return JSONResponse(content=result)

            else:

                # Return pure HTML for display

                logger.info("[RESPONSE] Returning HTML (response_type=html)")

                return HTMLResponse(content=html)

            

        except json.JSONDecodeError as e:

            logger.error(f"JSON parse error: {e}")

            logger.error(f"[DEBUG] Raw response was: {raw_response[:500] if raw_response else 'EMPTY'}")

            logger.error(f"[DEBUG] Sanitized response was: {response_text[:500] if response_text else 'EMPTY'}")

            error_result = {

                "Qualify": "No", "Recommendation": "RESEARCH",

                "reasoning": f"Parse error - manual review needed",

                "confidence": "Low"

            }

            return JSONResponse(content=error_result)

            

    except Exception as e:

        logger.error(f"Error: {e}")

        traceback.print_exc()

        error_result = {

            "Qualify": "No", "Recommendation": "ERROR",

            "reasoning": f"Error: {str(e)[:50]}"

        }

        return JSONResponse(content=error_result)





# ============================================================

# COSTUME JEWELRY ENDPOINT

# ============================================================

@app.post("/costume")

@app.get("/costume")

async def analyze_costume(request: Request):

    """

    Dedicated endpoint for costume jewelry analysis.

    

    AI Fields to Send (uBuyFirst):

    - Title (required)

    - TotalPrice (required)

    - Description

    - Brand

    - Type

    - Style

    - Condition

    - FeedbackScore

    - Alias (optional, will default to 'costume')

    - images (auto-sent by uBuyFirst)

    """

    logger.info("=" * 60)

    logger.info("[/costume] Costume Jewelry Endpoint Called")

    logger.info("=" * 60)

    

    try:

        data = {}

        images = []

        

        # Parse query params

        query_data = dict(request.query_params)

        if query_data:

            data = query_data

        

        # Read body for POST

        body = b""

        if not data:

            try:

                body = await request.body()

            except Exception as e:

                logger.warning(f"Failed to read body: {e}")

        

        # Parse JSON body

        if not data and body:

            try:

                json_data = json.loads(body)

                if isinstance(json_data, dict):

                    data = json_data

            except Exception:

                pass

        

        # Parse URL-encoded body

        if not data and body:

            try:

                parsed = parse_qs(body.decode('utf-8', errors='ignore'))

                if parsed:

                    data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

            except Exception:

                pass

        

        title = data.get('Title', 'No title')[:100]

        total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))

        alias = data.get('Alias', '')  # Search term from uBuyFirst

        response_type = data.get('response_type', 'json')

        listing_id = str(uuid.uuid4())[:8]

        timestamp = datetime.now().isoformat()



        logger.info(f"Title: {title[:60]}")

        logger.info(f"Price: ${total_price}")

        

        STATS["total_requests"] += 1

        

        # Force category to costume

        category = "costume"

        

        # Check cache

        cached = cache.get(title, total_price)

        if cached:

            result, html = cached

            STATS["cache_hits"] += 1

            logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')}")

            if response_type == 'json':

                return JSONResponse(content=result)

            else:

                return HTMLResponse(content=html)

        

        if not ENABLED:

            return JSONResponse(content={

                "Qualify": "No",

                "Recommendation": "DISABLED",

                "reasoning": "Proxy disabled"

            })

        

        STATS["api_calls"] += 1

        STATS["session_cost"] += COST_PER_CALL_HAIKU

        

        # Log for patterns

        log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

        

        # Fetch images

        if 'images' in data and data['images']:

            images = await process_image_list(data['images'])

            logger.info(f"Fetched {len(images)} images")

        

        # Build prompt - always use COSTUME_PROMPT

        from prompts import COSTUME_PROMPT

        listing_text = format_listing_data(data)

        user_message = f"{COSTUME_PROMPT}\n\n{listing_text}"

        

        # Build message with images

        if images:

            message_content = [{"type": "text", "text": user_message}]

            message_content.extend(images[:5])

        else:

            message_content = user_message

        

        # Call Claude API with costume-appropriate system context

        response = await client.messages.create(

            model=MODEL_FAST,

            max_tokens=600,

            system=get_system_context('costume'),

            messages=[{"role": "user", "content": message_content}]

        )

        

        raw_response = response.content[0].text.strip()

        response_text = sanitize_json_response(raw_response)

        

        try:

            result = json.loads(response_text)



            if 'reasoning' in result:

                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')


            # === AGENT RESPONSE VALIDATION ===
            agent_class = get_agent('costume')
            if agent_class:
                agent = agent_class()
                result = agent.validate_response(result)

            result['listingPrice'] = total_price

            result['category'] = 'costume'



            # === SERVER-SIDE COSTUME VALIDATION ===

            try:

                price_float = float(str(total_price).replace('$', '').replace(',', ''))

                piece_count = int(result.get('pieceCount', '1').replace('+', ''))

                quality_score = int(result.get('qualityScore', '0').replace('+', '').replace('--', '0'))

                

                # Calculate actual price per piece

                if piece_count > 0:

                    actual_ppp = price_float / piece_count

                    result['pricePerPiece'] = f"{actual_ppp:.2f}"

                

                ai_rec = result.get('Recommendation', 'RESEARCH')

                designer_tier = result.get('designerTier', 'Unknown')

                has_trifari = result.get('hasTrifari', 'No')

                itemtype = result.get('itemtype', 'Other')

                

                # RULE 1: Low quality + AI said BUY = downgrade to RESEARCH

                if ai_rec == 'BUY' and quality_score < 15 and itemtype == 'Lot':

                    result['Recommendation'] = 'RESEARCH'

                    result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Quality score {quality_score} < 15, downgraded to RESEARCH]"

                    logger.info(f"[COSTUME] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(low quality score {quality_score})")

                

                # RULE 2: Price per piece too high for generic lot

                if ai_rec == 'BUY' and itemtype == 'Lot' and has_trifari != 'Yes' and piece_count > 0:

                    if actual_ppp > 2.50 and quality_score < 25:

                        result['Recommendation'] = 'RESEARCH'

                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: ${actual_ppp:.2f}/piece too high for quality {quality_score}]"

                        logger.info(f"[COSTUME] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(${actual_ppp:.2f}/pc, quality {quality_score})")

                

                # RULE 3: Tier 4 designer (fashion brands) = always PASS

                if designer_tier == '4' and ai_rec == 'BUY':

                    result['Recommendation'] = 'PASS'

                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Tier 4 fashion brand - PASS]"

                    logger.info(f"[COSTUME] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(Tier 4 fashion brand)")

                

                # RULE 4: Single unsigned piece over $25 = PASS

                if piece_count == 1 and has_trifari != 'Yes' and price_float > 25 and ai_rec == 'BUY':

                    result['Recommendation'] = 'PASS'

                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Single unsigned piece >$25 - PASS]"

                    logger.info(f"[COSTUME] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(single unsigned >$25)")

                

                # RULE 5: Trifari with Crown mark and reasonable price = keep BUY

                trifari_collection = result.get('trifariCollection', '').lower()

                if has_trifari == 'Yes' and 'crown' in trifari_collection and price_float < 50:

                    # This is a good buy, make sure it stays BUY

                    if result.get('Recommendation') == 'RESEARCH':

                        result['Recommendation'] = 'BUY'

                        result['reasoning'] = result.get('reasoning', '') + " [SERVER: Crown Trifari under $50 - confirmed BUY]"

                

                # RULE 6: Jelly Belly under $100 = confirmed BUY

                if 'jelly' in trifari_collection and price_float < 100:

                    result['Recommendation'] = 'BUY'

                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Jelly Belly under $100 - confirmed BUY]"


                # RULE 7: Crown Trifari + Rhinestone = PREMIUM (worth more than gold tone)
                title_lower = title.lower()
                if has_trifari == 'Yes' and 'crown' in trifari_collection and 'rhinestone' in title_lower:
                    result['rhinestone_premium'] = True
                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Crown Trifari + Rhinestone - PREMIUM value, better than gold tone]"
                    # Bump threshold - rhinestone Trifari can be worth $50-200+
                    if result.get('Recommendation') == 'RESEARCH' and price_float < 75:
                        result['Recommendation'] = 'BUY'
                        result['reasoning'] = result.get('reasoning', '') + " [UPGRADED: Rhinestone Crown Trifari under $75]"
                        logger.info(f"[COSTUME] Crown Trifari + Rhinestone premium detected, upgraded to BUY @ ${price_float}")
                    elif result.get('Recommendation') == 'PASS' and price_float < 50:
                        result['Recommendation'] = 'RESEARCH'
                        result['reasoning'] = result.get('reasoning', '') + " [UPGRADED: Rhinestone Crown Trifari under $50 worth researching]"
                        logger.info(f"[COSTUME] Crown Trifari + Rhinestone premium detected, upgraded PASS->RESEARCH @ ${price_float}")



            except Exception as e:

                logger.debug(f"[COSTUME] Validation error: {e}")

            # === END COSTUME VALIDATION ===

            

            recommendation = result.get('Recommendation', 'RESEARCH')

            

            # Update stats

            if recommendation == "BUY":

                STATS["buy_count"] += 1

            elif recommendation == "PASS":

                STATS["pass_count"] += 1

            else:

                STATS["research_count"] += 1

            

            # Update pattern outcomes with EV and confidence

            margin_val = result.get('EV', result.get('Margin', '0'))

            conf_val = result.get('confidence', '')

            update_pattern_outcome(title, category, recommendation, margin_val, conf_val, alias)

            

            # Render HTML

            html = render_result_html(result, category, title)

            

            # Cache the result

            cache.set(title, total_price, result, html, recommendation)

            

            # Store in stats

            STATS["listings"][listing_id] = {

                "id": listing_id,

                "timestamp": timestamp,

                "title": title,

                "category": category,

                "total_price": total_price,

                "recommendation": recommendation,

                "margin": result.get('EV', result.get('Margin', '--')),

                "confidence": result.get('confidence', '--'),

                "reasoning": result.get('reasoning', ''),

                "raw_response": raw_response,

                "input_data": data

            }

            

            # Save to database

            save_listing(STATS["listings"][listing_id])

            

            logger.info(f"[COSTUME] {recommendation} | {result.get('pieceCount', '?')} pieces | EV: {result.get('EV', '?')}")

            

            if response_type == 'json':

                return JSONResponse(content=result)

            else:

                return HTMLResponse(content=html)

            

        except json.JSONDecodeError as e:

            logger.error(f"JSON parse error: {e}")

            return JSONResponse(content={

                "Qualify": "No", "Recommendation": "RESEARCH",

                "reasoning": f"Parse error - manual review needed"

            })

            

    except Exception as e:

        logger.error(f"Error in /costume: {e}")

        traceback.print_exc()

        return JSONResponse(content={

            "Qualify": "No", "Recommendation": "ERROR",

            "reasoning": f"Error: {str(e)[:50]}"

        })





# ============================================================

# ANALYZE QUEUED LISTING

# ============================================================

@app.post("/analyze-queued/{listing_id}")

async def analyze_queued(listing_id: str):

    """Analyze a specific queued listing"""

    global QUEUE_MODE

    

    if listing_id not in LISTING_QUEUE:

        return RedirectResponse(url="/", status_code=303)

    

    queued = LISTING_QUEUE[listing_id]

    

    # Temporarily disable queue mode for this analysis

    original_queue_mode = QUEUE_MODE

    QUEUE_MODE = False

    

    try:

        # Create a mock request with the queued data

        data = queued["data"]

        raw_images = queued.get("raw_images", queued.get("images", []))

        category = queued["category"]

        title = queued["title"]

        total_price = queued["total_price"]

        

        STATS["api_calls"] += 1

        STATS["session_cost"] += COST_PER_CALL_HAIKU

        

        # Fetch images now if we have raw URLs

        images = []

        if raw_images:

            images = await process_image_list(raw_images)

        

        # Build prompt

        category_prompt = get_category_prompt(category)

        listing_text = format_listing_data(data)

        user_message = f"{category_prompt}\n\n{listing_text}"

        

        # Build message content with images

        if images:

            message_content = [{"type": "text", "text": user_message}]

            message_content.extend(images[:5])

        else:

            message_content = user_message

        

        # Call Claude API with category-appropriate system context

        response = await client.messages.create(

            model=MODEL_FAST,

            max_tokens=500,

            system=get_agent_prompt(category),

            messages=[{"role": "user", "content": message_content}]

        )

        

        raw_response = response.content[0].text.strip()

        response_text = sanitize_json_response(raw_response)

        result = json.loads(response_text)


        # === AGENT RESPONSE VALIDATION ===
        agent_class = get_agent(category)
        if agent_class:
            agent = agent_class()
            result = agent.validate_response(result)

        # Add listing price to result for display

        result['listingPrice'] = total_price



        # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong

        result = validate_and_fix_margin(result, total_price, category, title, data)

        

        recommendation = result.get('Recommendation', 'RESEARCH')

        

        # Update stats

        if recommendation == "BUY":

            STATS["buy_count"] += 1

        elif recommendation == "PASS":

            STATS["pass_count"] += 1

        else:

            STATS["research_count"] += 1

        

        # Save to database

        listing_record = {

            "id": listing_id,

            "timestamp": queued["timestamp"],

            "title": title,

            "total_price": total_price,

            "category": category,

            "recommendation": recommendation,

            "margin": result.get('Profit', result.get('Margin', 'NA')),

            "confidence": result.get('confidence', 'NA'),

            "reasoning": result.get('reasoning', ''),

            "raw_response": raw_response,

            "input_data": {k: v for k, v in data.items() if k != 'images'}

        }

        

        STATS["listings"][listing_id] = listing_record

        save_listing(listing_record)

        margin_val = result.get('Profit', result.get('Margin', '0'))

        conf_val = result.get('confidence', '')

        update_pattern_outcome(title, category, recommendation, margin_val, conf_val, alias)

        

        # Cache the result so clicking in uBuyFirst again shows it

        result['listingPrice'] = total_price

        html = render_result_html(result, category, title)

        cache.set(title, total_price, result, html, recommendation, category)

        logger.info(f"Cached result for: {title[:40]}...")

        

        # Remove from queue

        del LISTING_QUEUE[listing_id]

        

        logger.info(f"Analyzed queued listing: {recommendation}")

        

    finally:

        QUEUE_MODE = original_queue_mode

    

    return RedirectResponse(url="/", status_code=303)





# ============================================================

# ANALYZE NOW - Called from uBuyFirst panel button

# ============================================================

@app.post("/analyze-now/{listing_id}")

async def analyze_now(listing_id: str):

    """Analyze a queued listing and return HTML directly to the panel"""

    

    if listing_id not in LISTING_QUEUE:

        return HTMLResponse(content='''

        <div style="color:#ef4444;padding:20px;text-align:center;">

        Listing not found in queue. Try clicking the listing again.

        </div>''')

    

    queued = LISTING_QUEUE[listing_id]

    

    try:

        data = queued["data"]

        raw_images = queued.get("raw_images", [])

        category = queued["category"]

        title = queued["title"]

        total_price = queued["total_price"]

        

        STATS["api_calls"] += 1

        STATS["session_cost"] += COST_PER_CALL_HAIKU

        

        # Fetch images now (parallel async)

        images = []

        if raw_images:

            images = await process_image_list(raw_images)

            logger.info(f"[analyze-now] Fetched {len(images)} images")

        

        # Build prompt

        category_prompt = get_category_prompt(category)

        listing_text = format_listing_data(data)

        user_message = f"{category_prompt}\n\n{listing_text}"

        

        # Build message content with images

        if images:

            message_content = [{"type": "text", "text": user_message}]

            message_content.extend(images[:5])

        else:

            message_content = user_message

        

        # Call Claude API with category-appropriate system context

        response = await client.messages.create(

            model=MODEL_FAST,

            max_tokens=500,

            system=get_agent_prompt(category),

            messages=[{"role": "user", "content": message_content}]

        )

        

        raw_response = response.content[0].text.strip()

        response_text = sanitize_json_response(raw_response)

        result = json.loads(response_text)



        if 'reasoning' in result:

            result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')


        # === AGENT RESPONSE VALIDATION ===
        agent_class = get_agent(category)
        if agent_class:
            agent = agent_class()
            result = agent.validate_response(result)

        # Add listing price to result for display

        result['listingPrice'] = total_price



        # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong

        result = validate_and_fix_margin(result, total_price, category, title, data)

        

        recommendation = result.get('Recommendation', 'RESEARCH')

        

        # Update stats

        if recommendation == "BUY":

            STATS["buy_count"] += 1

        elif recommendation == "PASS":

            STATS["pass_count"] += 1

        else:

            STATS["research_count"] += 1

        

        # Save to database

        listing_record = {

            "id": listing_id,

            "timestamp": queued["timestamp"],

            "title": title,

            "total_price": total_price,

            "category": category,

            "recommendation": recommendation,

            "margin": result.get('Profit', result.get('Margin', 'NA')),

            "confidence": result.get('confidence', 'NA'),

            "reasoning": result.get('reasoning', ''),

            "raw_response": raw_response,

            "input_data": {k: v for k, v in data.items() if k != 'images'}

        }

        

        STATS["listings"][listing_id] = listing_record

        save_listing(listing_record)

        margin_val = result.get('Profit', result.get('Margin', '0'))

        conf_val = result.get('confidence', '')

        update_pattern_outcome(title, category, recommendation, margin_val, conf_val, alias)

        

        # Cache the result

        result['listingPrice'] = total_price

        result['category'] = category

        html = render_result_html(result, category, title)

        result['html'] = html  # Include html in result for JSON cache response

        cache.set(title, total_price, result, html, recommendation, category)

        

        # Remove from queue

        del LISTING_QUEUE[listing_id]

        

        logger.info(f"Analyze-now complete: {recommendation}")

        

        # Add hint to click again for columns

        columns_hint = '''<div style="text-align:center;margin-top:10px;padding:8px;background:#e0e7ff;border-radius:8px;font-size:11px;color:#4338ca;">

        Click listing again to update columns

        </div></div></body></html>'''

        

        # Insert hint before closing tags

        html_with_hint = html.replace('</div></div></body></html>', columns_hint)

        

        # Return the result HTML directly to the panel

        return HTMLResponse(content=html_with_hint)

        

    except json.JSONDecodeError as e:

        logger.error(f"JSON parse error: {e}")

        return HTMLResponse(content=f'''

        <div style="background:#f8d7da;color:#721c24;padding:20px;border-radius:12px;text-align:center;">

        <div style="font-size:24px;font-weight:bold;">PARSE ERROR</div>

        <div style="margin-top:10px;">Could not parse AI response</div>

        </div>''')

    except Exception as e:

        logger.error(f"Analyze-now error: {e}")

        traceback.print_exc()

        return HTMLResponse(content=f'''

        <div style="background:#f8d7da;color:#721c24;padding:20px;border-radius:12px;text-align:center;">

        <div style="font-size:24px;font-weight:bold;">ERROR</div>

        <div style="margin-top:10px;">{str(e)[:100]}</div>

        </div>''')





# Toggle/Control endpoints moved to routes/dashboard.py


# ============================================================

# HOT RELOAD

# ============================================================

RELOAD_HISTORY = []



@app.post("/reload")

async def hot_reload():

    """Hot reload prompts.py and agents without restarting the server"""

    global RELOAD_HISTORY

    try:

        # Reload legacy prompts

        import prompts

        importlib.reload(prompts)



        # Reload new agents system

        import agents

        import agents.base, agents.gold, agents.silver, agents.costume

        import agents.videogames, agents.lego, agents.tcg, agents.coral_amber

        importlib.reload(agents.base)

        importlib.reload(agents.gold)

        importlib.reload(agents.silver)

        importlib.reload(agents.costume)

        importlib.reload(agents.videogames)

        importlib.reload(agents.lego)

        importlib.reload(agents.tcg)

        importlib.reload(agents.coral_amber)

        importlib.reload(agents)



        # Re-import the functions we use

        from prompts import get_category_prompt, get_business_context, get_system_context, get_gold_prompt, get_silver_prompt

        from agents import detect_category, get_agent, AGENTS



        # Update globals to point to new functions

        globals()['get_category_prompt'] = get_category_prompt

        globals()['get_business_context'] = get_business_context

        globals()['get_system_context'] = get_system_context

        globals()['detect_category'] = detect_category

        globals()['get_agent'] = get_agent

        globals()['AGENTS'] = AGENTS

        globals()['get_gold_prompt'] = get_gold_prompt

        globals()['get_silver_prompt'] = get_silver_prompt

        

        reload_time = datetime.now().isoformat()

        RELOAD_HISTORY.append({"time": reload_time, "status": "success", "file": "prompts.py"})

        

        # Keep only last 10 reloads

        if len(RELOAD_HISTORY) > 10:

            RELOAD_HISTORY = RELOAD_HISTORY[-10:]

        

        logger.info(f"[RELOAD] prompts.py reloaded successfully at {reload_time}")

        return RedirectResponse(url="/?reload=success", status_code=303)

    

    except Exception as e:

        error_msg = str(e)

        RELOAD_HISTORY.append({"time": datetime.now().isoformat(), "status": "error", "error": error_msg})

        logger.error(f"[RELOAD] Failed to reload prompts.py: {error_msg}")

        return RedirectResponse(url=f"/?reload=error&msg={error_msg[:50]}", status_code=303)





@app.get("/reload")

async def reload_page():

    """Page to trigger and view reload status"""

    history_html = ""

    for entry in reversed(RELOAD_HISTORY[-10:]):

        status_color = "#22c55e" if entry.get("status") == "success" else "#ef4444"

        history_html += f'<div style="padding:5px;border-bottom:1px solid #333;"><span style="color:{status_color}">x {entry.get("time", "?")} - {entry.get("status", "?")} {entry.get("error", "")}</div>'

    

    if not history_html:

        history_html = '<div style="color:#888;padding:10px;">No reloads yet</div>'

    

    return HTMLResponse(content=f'''

    <!DOCTYPE html>

    <html>

    <head><title>Hot Reload</title></head>

    <body style="background:#1a1a1a;color:#fff;font-family:monospace;padding:20px;">

        <h1>x Hot Reload</h1>

        <p>Reload prompts.py without restarting the server.</p>

        

        <form method="POST" action="/reload">

            <button type="submit" style="background:#3b82f6;color:white;border:none;padding:15px 30px;font-size:16px;cursor:pointer;border-radius:5px;">

                Reload prompts.py

            </button>

        </form>

        

        <h2 style="margin-top:30px;">Recent Reloads</h2>

        <div style="background:#222;border-radius:5px;max-width:600px;">

            {history_html}

        </div>

        

        <p style="margin-top:20px;"><a href="/" style="color:#3b82f6;">x ƒÆ’¢Back to Dashboard</a></p>

    </body>

    </html>

    ''')





# ============================================================

# API ENDPOINTS - /health, /queue, /api/spot-prices moved to routes/dashboard.py

# ============================================================
# USER PRICE DATABASE API
# ============================================================

@app.get("/api/user-prices")
async def api_user_prices():
    """Get all user-provided prices"""
    from user_price_db import get_all_prices, get_stats
    return {
        "prices": get_all_prices(),
        "stats": get_stats()
    }

@app.post("/api/user-prices/add")
async def api_add_user_price(
    category: str = "tcg",
    subcategory: str = "pokemon",
    item_name: str = "",
    market_value: float = 0,
    notes: str = ""
):
    """Add a new user price entry"""
    from user_price_db import add_price
    if not item_name or market_value <= 0:
        return {"error": "item_name and market_value required"}

    success = add_price(category, subcategory, item_name, market_value, notes)
    return {
        "success": success,
        "item": item_name,
        "market_value": market_value,
        "max_buy": round(market_value * 0.70, 2)
    }

@app.get("/api/user-prices/lookup")
async def api_lookup_user_price(title: str = ""):
    """Look up a title in user price database"""
    from user_price_db import lookup_price
    if not title:
        return {"error": "title required"}

    result = lookup_price(title)
    if result:
        name, data = result
        return {"match": True, "matched_name": name, "data": data}
    return {"match": False}



# ============================================================

# COSTUME JEWELRY OUTCOME TRACKING

# ============================================================

# Track actual outcomes to improve AI accuracy over time



COSTUME_OUTCOMES = []  # In-memory, also saved to DB



@app.post("/api/costume/outcome")

async def record_costume_outcome(request: Request):

    """

    Record actual outcome of a costume jewelry purchase.

    Use this to track what sold and for how much.

    

    POST body:

    {

        "title": "Crown Trifari butterfly brooch",

        "purchase_price": 45,

        "sold_price": 85,

        "category": "Trifari",

        "designer": "Crown Trifari",

        "collection": "Standard",

        "pieces": 1,

        "notes": "Sold on eBay within 1 week"

    }

    """

    try:

        data = await request.json()

        

        outcome = {

            "timestamp": datetime.now().isoformat(),

            "title": data.get("title", "Unknown"),

            "purchase_price": float(data.get("purchase_price", 0)),

            "sold_price": float(data.get("sold_price", 0)),

            "profit": float(data.get("sold_price", 0)) - float(data.get("purchase_price", 0)),

            "category": data.get("category", "Unknown"),

            "designer": data.get("designer", "Unknown"),

            "collection": data.get("collection", "Unknown"),

            "pieces": int(data.get("pieces", 1)),

            "notes": data.get("notes", ""),

        }

        

        # Calculate ROI

        if outcome["purchase_price"] > 0:

            outcome["roi_pct"] = (outcome["profit"] / outcome["purchase_price"]) * 100

        else:

            outcome["roi_pct"] = 0

        

        COSTUME_OUTCOMES.append(outcome)

        

        # Save to database

        save_costume_outcome(outcome)

        

        logger.info(f"[COSTUME] Recorded outcome: {outcome['title'][:30]} - profit ${outcome['profit']:.0f}")

        

        return {"status": "recorded", "outcome": outcome}

        

    except Exception as e:

        logger.error(f"Error recording costume outcome: {e}")

        return {"error": str(e)}





@app.get("/api/costume/outcomes")

async def get_costume_outcomes():

    """Get all recorded costume jewelry outcomes for analysis"""

    return {

        "count": len(COSTUME_OUTCOMES),

        "outcomes": COSTUME_OUTCOMES,

        "summary": calculate_costume_summary()

    }





def save_costume_outcome(outcome: dict):

    """Save costume outcome to database"""

    try:

        conn = sqlite3.connect(str(DB_PATH))

        cursor = conn.cursor()

        

        # Create table if needed

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS costume_outcomes (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp TEXT,

                title TEXT,

                purchase_price REAL,

                sold_price REAL,

                profit REAL,

                roi_pct REAL,

                category TEXT,

                designer TEXT,

                collection TEXT,

                pieces INTEGER,

                notes TEXT

            )

        """)

        

        cursor.execute("""

            INSERT INTO costume_outcomes 

            (timestamp, title, purchase_price, sold_price, profit, roi_pct, category, designer, collection, pieces, notes)

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        """, (

            outcome["timestamp"], outcome["title"], outcome["purchase_price"],

            outcome["sold_price"], outcome["profit"], outcome["roi_pct"],

            outcome["category"], outcome["designer"], outcome["collection"],

            outcome["pieces"], outcome["notes"]

        ))

        

        conn.commit()

        conn.close()

    except Exception as e:

        logger.error(f"Error saving costume outcome: {e}")





def calculate_costume_summary():

    """Calculate summary statistics for costume outcomes"""

    if not COSTUME_OUTCOMES:

        return {"message": "No outcomes recorded yet"}

    

    total_profit = sum(o["profit"] for o in COSTUME_OUTCOMES)

    total_spent = sum(o["purchase_price"] for o in COSTUME_OUTCOMES)

    

    # Group by category

    by_category = {}

    for o in COSTUME_OUTCOMES:

        cat = o["category"]

        if cat not in by_category:

            by_category[cat] = {"count": 0, "profit": 0, "spent": 0}

        by_category[cat]["count"] += 1

        by_category[cat]["profit"] += o["profit"]

        by_category[cat]["spent"] += o["purchase_price"]

    

    return {

        "total_outcomes": len(COSTUME_OUTCOMES),

        "total_profit": total_profit,

        "total_spent": total_spent,

        "avg_roi": (total_profit / total_spent * 100) if total_spent > 0 else 0,

        "by_category": by_category

    }





# /api/cache-stats moved to routes/dashboard.py

@app.get("/api/budget")
async def api_budget_status():
    """Get OpenAI hourly budget status"""
    return get_openai_budget_status()


@app.post("/api/budget/set")
async def api_set_budget(hourly_limit: float = 10.0):
    """Set the hourly OpenAI budget limit"""
    global OPENAI_HOURLY_BUDGET
    if hourly_limit < 1.0:
        return {"error": "Budget must be at least $1/hour"}
    if hourly_limit > 100.0:
        return {"error": "Budget cannot exceed $100/hour"}
    OPENAI_HOURLY_BUDGET = hourly_limit
    logger.info(f"[BUDGET] Hourly limit set to ${hourly_limit:.2f}")
    return {"success": True, "hourly_budget": OPENAI_HOURLY_BUDGET}



@app.get("/api/analytics")

async def api_analytics():

    return get_analytics()





@app.get("/api/patterns")

async def api_patterns():

    return get_pattern_analytics()





@app.get("/api/pricecharting")

async def api_pricecharting_stats():

    """Get PriceCharting database statistics"""

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    return pc_get_stats()





@app.get("/pc/refresh")
async def pc_refresh_endpoint(force: bool = False):
    """Manually trigger PriceCharting database refresh (runs in background)"""
    if not PRICECHARTING_AVAILABLE:
        return JSONResponse(
            content={"error": "PriceCharting module not available"},
            status_code=500
        )

    import asyncio
    import concurrent.futures

    logger.info("[PC] Manual refresh triggered (background)...")

    # Run in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Fire and forget - don't wait for result
    loop.run_in_executor(executor, lambda: pc_refresh(force=force))

    return {"status": "refresh_started", "message": "Database refresh started in background"}





@app.get("/pc/lookup")

async def pc_lookup_endpoint(q: str, category: str = None, price: float = 100):

    """

    Test PriceCharting lookup

    Usage: /pc/lookup?q=Pokemon+Evolving+Skies+Booster+Box&price=200

    """

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    result = pc_lookup(q, category=category, listing_price=price)

    return result





@app.get("/pc/rebuild-fts")

async def pc_rebuild_fts():

    """Rebuild the FTS5 search index"""

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    try:

        from pricecharting_db import rebuild_fts_index

        result = rebuild_fts_index()

        return result

    except Exception as e:

        return {"error": str(e)}





@app.get("/pc/debug")

async def pc_debug_search(q: str, category: str = None):

    """

    Debug PriceCharting search

    Usage: /pc/debug?q=LEGO+Star+Wars+75192&category=lego

    """

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    try:

        from pricecharting_db import debug_search

        result = debug_search(q, category)

        return result

    except Exception as e:

        return {"error": str(e)}





@app.get("/pc/test-download")

async def pc_test_download(console: str = "lego-star-wars"):

    """

    Test downloading a specific category CSV

    Usage: /pc/test-download?console=lego-star-wars

    """

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    try:

        from pricecharting_db import download_csv

        csv_content = download_csv(console)

        

        if not csv_content:

            return {"error": f"Failed to download {console}"}

        

        # Parse first few rows to show what we got

        lines = csv_content.split('\n')[:10]

        

        # Parse headers

        reader = csv.DictReader(StringIO(csv_content))

        headers = reader.fieldnames

        

        # Get first 5 products

        products = []

        for i, row in enumerate(reader):

            if i >= 5:

                break

            products.append({

                'product_name': row.get('product-name', ''),

                'console_name': row.get('console-name', ''),

                'new_price': row.get('new-price', 0),

            })

        

        return {

            "console_requested": console,

            "headers": headers,

            "sample_products": products,

            "total_lines": len(csv_content.split('\n'))

        }

    except Exception as e:

        return {"error": str(e)}





@app.get("/pc/api-lookup")

async def pc_api_lookup(q: str, price: float = 100, category: str = None):

    """

    Test real-time API lookup (for LEGO sets and TCG)

    Usage: /pc/api-lookup?q=LEGO+Star+Wars+75192&price=500&category=lego

           /pc/api-lookup?q=Pokemon+Evolving+Skies+Booster+Box&price=200&category=pokemon

    """

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    try:

        from pricecharting_db import api_lookup_product

        result = api_lookup_product(q, price, category)

        return result

    except Exception as e:

        return {"error": str(e)}





@app.get("/pc/upc-lookup")

async def pc_upc_lookup(upc: str, price: float = 100):

    """

    Test direct UPC lookup (most accurate method)

    Usage: /pc/upc-lookup?upc=820650853302&price=100

    """

    if not PRICECHARTING_AVAILABLE:

        return {"error": "PriceCharting module not available"}

    

    try:

        from pricecharting_db import api_lookup_by_upc

        result = api_lookup_by_upc(upc, price)

        return result

    except Exception as e:

        return {"error": str(e)}


@app.get("/api/debug-prompts")

async def debug_prompts():

    """Show current prompt values for debugging"""

    from prompts import get_gold_prompt, get_silver_prompt

    

    gold_prompt = get_gold_prompt()

    silver_prompt = get_silver_prompt()

    

    # Extract just the pricing section for easy viewing

    gold_pricing_start = gold_prompt.find("=== CURRENT GOLD PRICING")

    gold_pricing_end = gold_prompt.find("=== PRICING MODEL")

    gold_pricing = gold_prompt[gold_pricing_start:gold_pricing_end] if gold_pricing_start > 0 else "Not found"

    

    silver_pricing_start = silver_prompt.find("=== CURRENT PRICING")

    silver_pricing_end = silver_prompt.find("=== ITEM TYPE")

    silver_pricing = silver_prompt[silver_pricing_start:silver_pricing_end] if silver_pricing_start > 0 else "Not found"

    

    return {

        "spot_prices": get_spot_prices(),

        "gold_prompt_pricing": gold_pricing.strip(),

        "silver_prompt_pricing": silver_pricing.strip(),

    }





@app.get("/api/debug-db")

async def debug_database():

    """Debug endpoint to check database contents"""

    return get_db_debug_info()





# ============================================================

# OPENAI COMPATIBILITY ENDPOINTS

# ============================================================

@app.get("/v1/models")

async def list_models():

    return {

        "object": "list",

        "data": [{"id": MODEL_FAST, "object": "model", "owned_by": "anthropic"}]

    }





@app.post("/v1/chat/completions")

async def chat_completions(request: Request):

    """

    OpenAI-compatible endpoint for LiteLLM/uBuyFirst

    This must return proper OpenAI JSON format for columns to populate

    """

    logger.info("[/v1/chat/completions] Received request")

    

    try:

        body = await request.json()

        messages = body.get("messages", [])

        

        # Extract listing data from the user message

        # uBuyFirst sends listing data in the last user message

        listing_data = {}

        for msg in messages:

            if msg.get("role") == "user":

                content = msg.get("content", "")

                if isinstance(content, str):

                    # Try to parse as JSON or extract fields

                    listing_data["raw_content"] = content

                elif isinstance(content, list):

                    # Multi-part content (text + images)

                    for part in content:

                        if part.get("type") == "text":

                            listing_data["raw_content"] = part.get("text", "")

        

        # Extract title and price from raw content if possible

        raw = listing_data.get("raw_content", "")

        

        # Get query params if they were passed

        params = dict(request.query_params)

        title = params.get("Title", "Unknown")

        total_price = params.get("TotalPrice", "0")

        

        # Try to parse total_price

        try:

            total_price = float(str(total_price).replace("$", "").replace(",", ""))

        except:

            total_price = 0

        

        # Detect category from the content

        category = "unknown"

        raw_lower = raw.lower()

        if any(x in raw_lower for x in ["sterling", "925", "silver"]):

            category = "silver"

        elif any(x in raw_lower for x in ["10k", "14k", "18k", "22k", "24k", "karat", "gold"]):

            category = "gold"

        

        logger.info(f"[/v1/chat/completions] Category: {category}, Title: {title[:50]}")

        

        # Check if disabled

        if not ENABLED:

            result = {

                "Qualify": "No",

                "Recommendation": "DISABLED",

                "reasoning": "Proxy disabled - enable at localhost:8000"

            }

            return JSONResponse(content=create_openai_response(result))

        

        # Run actual Claude analysis

        STATS["api_calls"] += 1

        STATS["session_cost"] += COST_PER_CALL_HAIKU

        

        # Build prompt based on category

        if category == "silver":

            system_prompt = get_silver_prompt()

        elif category == "gold":

            system_prompt = get_gold_prompt()

        else:

            system_prompt = "Analyze this listing and return JSON with Recommendation (BUY/PASS/RESEARCH), Qualify (Yes/No), and reasoning."

        

        # Call Claude

        try:

            response = await client.messages.create(

                model=MODEL_FAST,

                max_tokens=1000,

                system=system_prompt,

                messages=[{"role": "user", "content": raw}]

            )

            

            raw_response = response.content[0].text

            logger.info(f"[/v1/chat/completions] Claude response: {raw_response[:200]}")

            

            # Parse Claude's JSON response

            # Clean up response

            cleaned = raw_response.strip()

            if cleaned.startswith("```"):

                cleaned = cleaned.split("```")[1]

                if cleaned.startswith("json"):

                    cleaned = cleaned[4:]

            cleaned = cleaned.strip()

            

            result = json.loads(cleaned)

            

            # Ensure required fields exist

            if "Recommendation" not in result:

                result["Recommendation"] = "RESEARCH"

            if "Qualify" not in result:

                result["Qualify"] = "No"

            

            logger.info(f"[/v1/chat/completions] Result: {result.get('Recommendation')}")

            

            return JSONResponse(content=create_openai_response(result))

            

        except json.JSONDecodeError as e:

            logger.error(f"[/v1/chat/completions] JSON parse error: {e}")

            result = {

                "Qualify": "No",

                "Recommendation": "RESEARCH", 

                "reasoning": f"Parse error: {str(e)[:50]}"

            }

            return JSONResponse(content=create_openai_response(result))

            

    except Exception as e:

        logger.error(f"[/v1/chat/completions] Error: {e}")

        traceback.print_exc()

        result = {

            "Qualify": "No",

            "Recommendation": "ERROR",

            "reasoning": f"Error: {str(e)[:50]}"

        }

        return JSONResponse(content=create_openai_response(result))





# ============================================================

# CONFIDENCE BREAKDOWN BUILDER

# ============================================================

def build_confidence_breakdown(category: str, parsed_response: dict, listing: dict) -> str:

    """Build HTML showing confidence score breakdown"""

    

    if not parsed_response:

        return '<div style="color:#666;padding:10px;">No parsed response available for breakdown</div>'

    

    confidence = parsed_response.get('confidence', listing.get('confidence', '--'))

    ai_breakdown = parsed_response.get('confidenceBreakdown', '')

    

    # Try to get confidence as a number for coloring

    try:

        conf_value = int(confidence) if str(confidence).isdigit() else confidence

        conf_color = "#22c55e" if isinstance(conf_value, int) and conf_value >= 70 else "#f59e0b" if isinstance(conf_value, int) and conf_value >= 50 else "#ef4444"

    except:

        conf_value = confidence

        conf_color = "#888"

    

    # If AI provided breakdown, show it prominently

    ai_breakdown_html = ""

    if ai_breakdown:

        ai_breakdown_html = f'''

        <div style="background:#1a3a1a;border:1px solid #22c55e;border-radius:8px;padding:15px;margin-bottom:15px;">

            <div style="color:#22c55e;font-weight:bold;margin-bottom:8px;">x AI's Confidence Calculation</div>

            <div style="font-family:monospace;color:#fff;">{ai_breakdown}</div>

        </div>'''

    

    # Define scoring factors by category for reference

    factors = []

    

    # Get reasoning to check for estimation indicators

    reasoning = str(parsed_response.get('reasoning', listing.get('reasoning', ''))).lower()

    weight_source = parsed_response.get('weightSource', '').lower()

    

    # Determine if weight was from scale or estimated

    if weight_source == 'scale':

        weight_was_from_scale = True

    elif weight_source == 'estimate':

        weight_was_from_scale = False

    else:

        # Fallback: check reasoning for indicators

        weight_was_from_scale = 'scale' in reasoning and 'est' not in reasoning

    

    if category == "gold":

        # Gold scoring factors

        weight = str(parsed_response.get('weight', listing.get('weight', '')))

        karat = parsed_response.get('karat', '')

        fakerisk = parsed_response.get('fakerisk', '')

        itemtype = parsed_response.get('itemtype', '')

        stoneDeduction = parsed_response.get('stoneDeduction', '')

        

        factors.append(("Base Score", "60", "Starting point for gold"))

        

        # Check weight source

        weight_has_value = weight and weight not in ['NA', '--', 'Unknown', '', '0']

        if weight_has_value and weight_was_from_scale:

            factors.append(("Weight from Scale", "+25", f"Scale: {weight}g"))

        elif weight_has_value and not weight_was_from_scale:

            factors.append(("Weight Estimated", "-15", f"Est: {weight}g (no scale read)"))

        else:

            factors.append(("No Weight", "-15", "Weight unknown"))

        

        if karat and karat not in ['NA', '--', 'Unknown', '']:

            factors.append(("Karat Visible", "+10", f"Karat: {karat}"))

        

        if fakerisk == "High":

            factors.append(("High Fake Risk", "-15", "Cuban/Rope chain or suspicious"))

        elif fakerisk == "Low":

            factors.append(("Low Fake Risk", "+5", "Vintage/signed/low risk item"))

        

        if stoneDeduction and stoneDeduction not in ['0', 'NA', '--', '']:

            factors.append(("Stone Deduction", "-10", f"Stone estimate: {stoneDeduction}"))

    

    elif category == "silver":

        weight = str(parsed_response.get('weight', listing.get('weight', '')))

        verified = parsed_response.get('verified', '')

        itemtype = parsed_response.get('itemtype', '')

        stoneDeduction = parsed_response.get('stoneDeduction', '')

        

        factors.append(("Base Score", "60", "Starting point for silver"))

        

        weight_has_value = weight and weight not in ['NA', '--', 'Unknown', '', '0']

        if weight_has_value and weight_was_from_scale:

            factors.append(("Weight from Scale", "+25", f"Scale: {weight}g"))

        elif weight_has_value and not weight_was_from_scale:

            factors.append(("Weight Estimated", "-15", f"Est: {weight}g (no scale read)"))

        else:

            factors.append(("No Weight", "-15", "Weight unknown"))

        

        if verified == "Yes":

            factors.append(("925 Mark Visible", "+10", "Sterling verified"))

        

        if stoneDeduction and stoneDeduction not in ['0', 'NA', '--', '']:

            factors.append(("Stone Deduction", "-10", f"Stone estimate: {stoneDeduction}"))

        

        if itemtype == "Weighted":

            factors.append(("Weighted Item", "-10", "Only 15% is silver"))

    

    elif category == "costume":

        pieceCount = parsed_response.get('pieceCount', '')

        designers = parsed_response.get('designers', '')

        bestDesigner = parsed_response.get('bestDesigner', '')

        metalPotential = parsed_response.get('metalPotential', '')

        variety = parsed_response.get('variety', '')

        silverEstimate = parsed_response.get('silverEstimate', '')

        

        factors.append(("Base Score", "50", "Starting point for costume"))

        

        if bestDesigner and bestDesigner not in ['None', 'Unknown', '--', '']:

            factors.append(("Designer Visible", "+20", f"Designer: {bestDesigner}"))

        

        try:

            count = int(str(pieceCount).replace('+', ''))

            if count >= 30:

                factors.append(("High Piece Count", "+10", f"Count: {pieceCount}"))

        except:

            pass

        

        if metalPotential == "High":

            factors.append(("Metal Potential", "+15", "Gold/silver likely"))

        elif metalPotential == "Low" or metalPotential == "None":

            factors.append(("No Metal", "-10", "No precious metal visible"))

        

        if silverEstimate and silverEstimate not in ['NA', '--', '']:

            factors.append(("Sterling Visible", "+15", f"Estimate: {silverEstimate}"))

        

        if variety == "Excellent" or variety == "Good":

            factors.append(("Good Variety", "+10", f"Variety: {variety}"))

        elif variety == "Poor":

            factors.append(("Poor Variety", "-10", "Limited variety"))

    

    else:

        factors.append(("Category", "--", f"No breakdown for {category}"))

    

    # Build HTML table for reference factors

    rows_html = ""

    for factor, adjustment, note in factors:

        if adjustment.startswith('+'):

            color = "#22c55e"

        elif adjustment.startswith('-'):

            color = "#ef4444"

        else:

            color = "#888"

        

        rows_html += f'''

        <tr>

            <td style="padding:8px;border-bottom:1px solid #333;">{factor}</td>

            <td style="padding:8px;border-bottom:1px solid #333;color:{color};font-weight:bold;text-align:center;">{adjustment}</td>

            <td style="padding:8px;border-bottom:1px solid #333;color:#888;font-size:12px;">{note}</td>

        </tr>'''

    

    return f'''

    <div style="background:#252540;border-radius:8px;padding:15px;">

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">

            <span style="color:#888;">Final Confidence Score</span>

            <span style="font-size:24px;font-weight:bold;color:{conf_color};">{conf_value}</span>

        </div>

        

        {ai_breakdown_html}

        

        <div style="color:#888;font-size:12px;margin-bottom:10px;">Reference Scoring Factors:</div>

        <table style="width:100%;border-collapse:collapse;">

            <tr style="color:#888;font-size:12px;text-transform:uppercase;">

                <th style="text-align:left;padding:8px;border-bottom:2px solid #444;">Factor</th>

                <th style="text-align:center;padding:8px;border-bottom:2px solid #444;">Adjust</th>

                <th style="text-align:left;padding:8px;border-bottom:2px solid #444;">Note</th>

            </tr>

            {rows_html}

        </table>

    </div>'''





# ============================================================

# HTML RENDERERS

# ============================================================

def _render_disabled_html() -> str:

    return '''<!DOCTYPE html>

<html><head><style>

body { font-family: system-ui; background: #f5f5f5; padding: 20px; }

.card { background: #fff3cd; border: 3px solid #ffc107; border-radius: 12px; padding: 20px; text-align: center; max-width: 400px; margin: auto; }

.status { font-size: 28px; font-weight: bold; color: #856404; }

</style></head><body>

<div class="card"><div class="status">PROXY DISABLED</div>

<p>Enable at <a href="http://localhost:8000">localhost:8000</a></p></div>

</body></html>'''





def _render_queued_html(category: str, listing_id: str, title: str, price: str) -> str:

    # Return a button that triggers analysis on click (no API call until clicked)

    return f'''<!DOCTYPE html>

<html><head><style>

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; padding: 15px; min-height: 100%; }}

.container {{ text-align: center; }}

.title {{ font-size: 13px; color: #888; margin-bottom: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

.category {{ display: inline-block; background: #252540; color: #6366f1; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-bottom: 15px; }}

.analyze-btn {{ 

    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); 

    color: white; 

    border: none; 

    padding: 15px 40px; 

    font-size: 18px; 

    font-weight: 700; 

    border-radius: 12px; 

    cursor: pointer; 

    transition: transform 0.2s, box-shadow 0.2s;

    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);

}}

.analyze-btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5); }}

.analyze-btn:active {{ transform: translateY(0); }}

.loading {{ display: none; color: #888; font-size: 14px; }}

.result {{ display: none; }}

</style></head><body>

<div class="container">

<div class="category">{category.upper()}</div>

<div class="title">{title[:60]}</div>

<button class="analyze-btn" onclick="runAnalysis()">ANALYZE</button>

<div class="loading" id="loading">Analyzing...</div>

<div class="result" id="result"></div>

</div>

<script>

function runAnalysis() {{

    document.querySelector('.analyze-btn').style.display = 'none';

    document.getElementById('loading').style.display = 'block';

    

    fetch('/analyze-now/{listing_id}', {{ method: 'POST' }})

        .then(response => response.text())

        .then(html => {{

            document.body.innerHTML = html;

        }})

        .catch(err => {{

            document.getElementById('loading').textContent = 'Error: ' + err;

        }});

}}

</script>

</body></html>'''





def _render_error_html(error: str) -> str:

    return f'''<!DOCTYPE html>

<html><head><style>

body {{ font-family: system-ui; background: #f5f5f5; padding: 20px; }}

.card {{ background: #f8d7da; border: 3px solid #dc3545; border-radius: 12px; padding: 20px; text-align: center; max-width: 400px; margin: auto; }}

.status {{ font-size: 28px; font-weight: bold; color: #721c24; }}

</style></head><body>

<div class="card"><div class="status">ERROR</div>

<p>{error[:100]}</p></div>

</body></html>'''





def format_confidence(confidence) -> str:

    """Format confidence as 'Number (Label)' e.g. '85 (High)'"""

    try:

        # Try to get numeric value

        if isinstance(confidence, str):

            conf_lower = confidence.lower().strip()

            # Convert word to number

            if conf_lower in ['high', 'h']:

                conf_num = 80

            elif conf_lower in ['medium', 'med', 'm']:

                conf_num = 60

            elif conf_lower in ['low', 'l']:

                conf_num = 40

            else:

                conf_num = int(confidence.replace('%', '').strip())

        else:

            conf_num = int(confidence) if confidence else 50

        

        # Determine label

        if conf_num >= 70:

            label = "High"

        elif conf_num >= 50:

            label = "Med"

        else:

            label = "Low"

        

        return f"{conf_num} ({label})"

    except (ValueError, TypeError):

        # Last resort - return what we got

        return str(confidence) if confidence else "50 (Med)"





def render_result_html(result: dict, category: str, title: str = "") -> str:

    """Render analysis result as HTML based on category"""

    recommendation = result.get('Recommendation', 'RESEARCH')

    reasoning = result.get('reasoning', 'No reasoning provided')

    # Use Profit (actual money made) not Margin (room under ceiling)

    profit = result.get('Profit', result.get('Margin', result.get('margin', '--')))

    confidence = format_confidence(result.get('confidence', '--'))

    

    # Determine card styling

    if recommendation == 'BUY':

        bg = 'linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%)'

        border = '#28a745'

        text_color = '#155724'

    elif recommendation == 'PASS':

        bg = 'linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%)'

        border = '#dc3545'

        text_color = '#721c24'

    elif recommendation in ('CLICK AGAIN', 'QUEUED', 'DISABLED'):

        bg = 'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)'

        border = '#6366f1'

        text_color = '#3730a3'

    else:

        bg = 'linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%)'

        border = '#ffc107'

        text_color = '#856404'

    

    # Build info grid based on category

    info_items = []

    

    if category == 'gold':

        listing_price = result.get('listingPrice', '--')

        # Prefer goldweight (after deductions) over total weight

        gold_weight = result.get('goldweight', result.get('weight', '--'))

        # Show deduction info if present

        stone_deduction = result.get('stoneDeduction', '')

        weight_display = f"{gold_weight}"

        if stone_deduction and stone_deduction not in ['0', 'NA', '', 'None']:

            weight_display = f"{gold_weight} (net)"

        info_items = [

            ('Karat', result.get('karat', '--')),

            ('Gold Wt', weight_display),

            ('Melt', f"${result.get('meltvalue', '--')}"),

            ('Sell (96%)', f"${result.get('sellPrice', '--')}"),

            ('Listing', f"${listing_price}"),

            ('Confidence', confidence),

        ]

    elif category == 'silver':

        listing_price = result.get('listingPrice', '--')

        info_items = [

            ('Type', result.get('itemtype', '--')),

            ('Weight', result.get('weight', result.get('silverweight', '--'))),

            ('Melt', f"${result.get('meltvalue', '--')}"),

            ('Sell (82%)', f"${result.get('sellPrice', '--')}"),

            ('Listing', f"${listing_price}"),

            ('Confidence', confidence),

        ]

    elif category == 'costume':

        # Get quality score and format it

        quality_score = result.get('qualityScore', '--')

        designer_tier = result.get('designerTier', '--')

        tier_label = f"Tier {designer_tier}" if designer_tier not in ['--', 'Unknown', 'Mixed'] else designer_tier

        

        info_items = [

            ('Type', result.get('itemtype', '--')),

            ('Pieces', result.get('pieceCount', '--')),

            ('$/Piece', f"${result.get('pricePerPiece', '--')}"),

            ('Designer', result.get('designer', '--')[:15]),  # Truncate long names

            ('Quality', quality_score),

            ('Tier', tier_label),

        ]

    elif category == 'tcg':

        info_items = [

            ('TCG', result.get('TCG', '--')),

            ('Type', result.get('ProductType', '--')),

            ('Set', result.get('SetName', '--')),

            ('Market', f"${result.get('marketprice', '--')}"),

            ('Max Buy', f"${result.get('maxBuy', '--')}"),

            ('Risk', result.get('fakerisk', '--')),

        ]

    elif category == 'lego':

        info_items = [

            ('Set#', result.get('SetNumber', '--')),

            ('Set', result.get('SetName', '--')),

            ('Theme', result.get('Theme', '--')),

            ('Market', f"${result.get('marketprice', '--')}"),

            ('Max Buy', f"${result.get('maxBuy', '--')}"),

            ('Retired', result.get('Retired', '--')),

        ]

    elif category == 'coral':

        info_items = [

            ('Material', result.get('material', '--')),

            ('Age', result.get('age', '--')),

            ('Color', result.get('color', '--')),

            ('Type', result.get('itemtype', '--')),

            ('Value', f"${result.get('estimatedvalue', '--')}"),

            ('Risk', result.get('fakerisk', '--')),

        ]

    elif category == 'videogames':

        info_items = [

            ('Game', result.get('pcProduct', result.get('product_name', '--'))[:30]),

            ('Console', result.get('console_name', result.get('detected_console', '--'))),

            ('Condition', result.get('condition', result.get('detected_condition', '--'))),

            ('Market', f"${result.get('marketprice', '--')}"),

            ('Max Buy', f"${result.get('maxBuy', '--')}"),

            ('Confidence', confidence),

        ]

    else:

        info_items = [

            ('Type', result.get('itemtype', '--')),

            ('Confidence', confidence),

        ]

    

    info_html = ""

    for label, value in info_items:

        info_html += f'''<div class="info-box">

<div class="info-label">{label}</div>

<div class="info-value">{value}</div>

</div>'''

    

    # Text-to-Speech script for BUY alerts

    # Clean the title for speech (remove special chars)

    clean_title = title.replace('"', '').replace("'", "").replace('&', 'and')[:100] if title else ""

    

    tts_script = ""

    if recommendation == 'BUY' and clean_title:

        tts_script = f'''

<script>

(function() {{

    if ('speechSynthesis' in window) {{

        // Cancel any ongoing speech

        window.speechSynthesis.cancel();

        

        // Create utterance

        var msg = new SpeechSynthesisUtterance();

        msg.text = "Buy alert! {clean_title}";

        msg.rate = 1.1;  // Slightly faster

        msg.pitch = 1.0;

        msg.volume = 1.0;

        

        // Try to use a good voice

        var voices = window.speechSynthesis.getVoices();

        if (voices.length > 0) {{

            // Prefer English voices

            var englishVoice = voices.find(v => v.lang.startsWith('en'));

            if (englishVoice) msg.voice = englishVoice;

        }}

        

        // Speak after a tiny delay (helps with voice loading)

        setTimeout(function() {{

            window.speechSynthesis.speak(msg);

        }}, 100);

    }}

}})();

</script>'''

    

    return f'''<!DOCTYPE html>

<html><head><style>

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}

.container {{ max-width: 500px; margin: 0 auto; }}

.result-card {{ border-radius: 12px; padding: 20px; text-align: center; background: {bg}; border: 3px solid {border}; }}

.status {{ font-size: 36px; font-weight: bold; color: {text_color}; margin-bottom: 5px; }}

.profit {{ font-size: 24px; font-weight: bold; color: {text_color}; margin-bottom: 10px; }}

.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}

.info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 15px; }}

.info-box {{ background: #fff; border-radius: 8px; padding: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}

.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}

.info-value {{ font-size: 14px; font-weight: bold; color: #333; }}

</style></head><body>

<div class="container">

<div class="result-card">

<div class="status">{recommendation}</div>

<div class="profit">{profit}</div>

<div class="reason">{reasoning}</div>

<div class="info-grid">{info_html}</div>

</div></div>

{tts_script}

</body></html>'''





# NOTE: configure_analysis() moved to after EBAY_POLLER_AVAILABLE is defined (see below ebay_poller import)


# ============================================================

# TTS TEST ENDPOINT

# ============================================================

@app.get("/test-tts", response_class=HTMLResponse)

async def test_tts():

    """Test Text-to-Speech functionality"""

    return HTMLResponse(content='''<!DOCTYPE html>

<html><head><title>TTS Test</title>

<style>

body { font-family: Arial, sans-serif; padding: 40px; background: #1a1a2e; color: #fff; }

.btn { padding: 20px 40px; font-size: 24px; cursor: pointer; margin: 10px; border-radius: 10px; }

.buy { background: #28a745; color: white; border: none; }

.test { background: #007bff; color: white; border: none; }

h1 { color: #00ff88; }

#status { margin-top: 20px; padding: 20px; background: #2d2d44; border-radius: 10px; }

</style>

</head><body>

<h1> TTS Test Page</h1>

<p>Click a button to test Text-to-Speech:</p>



<button class="btn buy" onclick="speak('Buy alert! 14k Gold Chain 15 grams solid gold')">

     Test BUY Alert

</button>



<button class="btn test" onclick="speak('Testing text to speech. If you can hear this, it works!')">

     Test Generic Speech

</button>



<button class="btn" style="background:#dc3545;color:white;border:none;" onclick="testVoices()">

     List Available Voices

</button>



<div id="status">Status: Ready</div>



<script>

function speak(text) {

    var status = document.getElementById('status');

    

    if (!('speechSynthesis' in window)) {

        status.innerHTML = ' Speech Synthesis NOT supported in this browser!';

        return;

    }

    

    status.innerHTML = ' Speaking: "' + text + '"';

    

    // Cancel any ongoing speech

    window.speechSynthesis.cancel();

    

    var msg = new SpeechSynthesisUtterance();

    msg.text = text;

    msg.rate = 1.1;

    msg.pitch = 1.0;

    msg.volume = 1.0;

    

    msg.onend = function() {

        status.innerHTML = ' Speech completed!';

    };

    

    msg.onerror = function(e) {

        status.innerHTML = ' Speech error: ' + e.error;

    };

    

    // Try to get a good English voice

    var voices = window.speechSynthesis.getVoices();

    if (voices.length > 0) {

        var englishVoice = voices.find(v => v.lang.startsWith('en'));

        if (englishVoice) {

            msg.voice = englishVoice;

            status.innerHTML += '<br>Using voice: ' + englishVoice.name;

        }

    }

    

    setTimeout(function() {

        window.speechSynthesis.speak(msg);

    }, 100);

}



function testVoices() {

    var status = document.getElementById('status');

    var voices = window.speechSynthesis.getVoices();

    

    if (voices.length === 0) {

        status.innerHTML = '️ No voices loaded yet. Click again in a second.';

        // Trigger voice loading

        window.speechSynthesis.getVoices();

        return;

    }

    

    var html = '<strong>Available Voices (' + voices.length + '):</strong><br>';

    voices.forEach(function(v, i) {

        html += (i+1) + '. ' + v.name + ' (' + v.lang + ')' + (v.default ? ' [DEFAULT]' : '') + '<br>';

    });

    status.innerHTML = html;

}



// Pre-load voices

window.speechSynthesis.getVoices();

</script>

</body></html>''')





# Main dashboard (/) moved to routes/dashboard.py


# ============================================================

# PATTERNS PAGE

# ============================================================

@app.get("/patterns", response_class=HTMLResponse)

async def patterns_page():

    """Pattern analytics page with waste scoring"""

    patterns = get_pattern_analytics()

    

    # Worst keywords (high waste score)

    worst_html = ""

    for kw in patterns.get('worst_keywords', [])[:20]:

        avg_margin = kw.get('avg_margin', 0) or 0

        avg_conf = kw.get('avg_confidence', 0) or 0

        waste = kw.get('waste_score', 0) or 0

        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"

        conf_color = "#ef4444" if avg_conf < 50 else "#f59e0b" if avg_conf < 70 else "#22c55e"

        worst_html += f'''

        <tr>

            <td><strong>{kw.get('keyword', '')}</strong></td>

            <td>{kw.get('category', '')}</td>

            <td>{kw.get('times_analyzed', 0)}</td>

            <td style="color:#ef4444">{kw.get('pass_rate', 0):.0%}</td>

            <td style="color:{margin_color}">${avg_margin:.0f}</td>

            <td style="color:{conf_color}">{avg_conf:.0f}</td>

            <td style="color:#ef4444;font-weight:bold">{waste:.2f}</td>

        </tr>'''

    

    # Bad keywords

    bad_html = ""

    for kw in patterns.get('bad_keywords', [])[:20]:

        avg_margin = kw.get('avg_margin', 0) or 0

        avg_conf = kw.get('avg_confidence', 0) or 0

        waste = kw.get('waste_score', 0) or 0

        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"

        bad_html += f'''

        <tr>

            <td>{kw.get('keyword', '')}</td>

            <td>{kw.get('category', '')}</td>

            <td>{kw.get('times_analyzed', 0)}</td>

            <td style="color:#f59e0b">{kw.get('pass_rate', 0):.0%}</td>

            <td style="color:{margin_color}">${avg_margin:.0f}</td>

            <td>{avg_conf:.0f}</td>

            <td style="color:#f59e0b">{waste:.2f}</td>

        </tr>'''

    

    # All high-pass keywords table

    all_html = ""

    for kw in patterns.get('high_pass_keywords', [])[:50]:

        avg_margin = kw.get('avg_margin', 0) or 0

        avg_conf = kw.get('avg_confidence', 0) or 0

        pass_rate = kw.get('pass_rate', 0) or 0

        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"

        pass_color = "#ef4444" if pass_rate > 0.8 else "#f59e0b" if pass_rate > 0.5 else "#888"

        all_html += f'''

        <tr>

            <td>{kw.get('keyword', '')}</td>

            <td>{kw.get('category', '')}</td>

            <td>{kw.get('times_seen', 0)}</td>

            <td>{kw.get('times_analyzed', 0)}</td>

            <td style="color:{pass_color}">{pass_rate:.0%}</td>

            <td style="color:{margin_color}">${avg_margin:.0f}</td>

            <td>{avg_conf:.0f}</td>

        </tr>'''

    

    return f"""<!DOCTYPE html>

<html><head>

<title>Pattern Analytics - Keyword Waste Scoring</title>

<style>

body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}

.container {{ max-width: 1200px; margin: 0 auto; }}

h1 {{ color: #fff; margin-bottom: 10px; }}

h2 {{ color: #fff; margin: 30px 0 15px 0; font-size: 18px; }}

.subtitle {{ color: #888; margin-bottom: 20px; font-size: 14px; }}

table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; margin-bottom: 30px; }}

th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #333; }}

th {{ background: #252540; color: #888; font-weight: 600; text-transform: uppercase; font-size: 11px; }}

td {{ font-size: 13px; }}

a {{ color: #6366f1; text-decoration: none; }}

.section {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}

.worst {{ border-left: 4px solid #ef4444; }}

.bad {{ border-left: 4px solid #f59e0b; }}

.legend {{ display: flex; gap: 20px; margin-bottom: 20px; font-size: 12px; }}

.legend-item {{ display: flex; align-items: center; gap: 5px; }}

.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}

.formula {{ background: #252540; padding: 15px; border-radius: 8px; margin: 15px 0; font-family: monospace; font-size: 12px; }}

</style>

</head><body>

<div class="container">

<a href="/">&larr; Back to Dashboard</a>

<h1>Keyword Waste Scoring</h1>

<p class="subtitle">Identifies the least profitable keywords to add as negative filters</p>



<div class="formula">

<strong>Waste Score Formula:</strong><br>

waste_score = (pass_rate x 0.5) + (negative_margin_penalty x 0.3) + (low_confidence_penalty x 0.2) x volume_weight<br>

<span style="color:#888;">Higher score = worse keyword. Score &gt; 0.4 = definitely add to negative filter</span>

</div>



<div class="legend">

    <div class="legend-item"><div class="legend-dot" style="background:#ef4444;"></div> Worst (score &gt; 0.4)</div>

    <div class="legend-item"><div class="legend-dot" style="background:#f59e0b;"></div> Bad (score 0.2-0.4)</div>

    <div class="legend-item"><div class="legend-dot" style="background:#22c55e;"></div> Profitable margin</div>

    <div class="legend-item"><div class="legend-dot" style="background:#ef4444;"></div> Negative margin</div>

</div>



<div class="section worst">

<h2>WORST Keywords (Add to Negative Filters!)</h2>

<p style="color:#888;font-size:12px;margin-bottom:15px;">High pass rate + negative margins + low confidence = waste of time</p>

<table>

<thead><tr><th>Keyword</th><th>Category</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th><th>Waste Score</th></tr></thead>

<tbody>{worst_html if worst_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No worst keywords yet (need more data)</td></tr>'}</tbody>

</table>

</div>



<div class="section bad">

<h2>Bad Keywords (Consider Filtering)</h2>

<p style="color:#888;font-size:12px;margin-bottom:15px;">Moderately wasteful - review before filtering</p>

<table>

<thead><tr><th>Keyword</th><th>Category</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th><th>Waste Score</th></tr></thead>

<tbody>{bad_html if bad_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No bad keywords yet</td></tr>'}</tbody>

</table>

</div>



<h2>All High-Pass Keywords</h2>

<table>

<thead><tr><th>Keyword</th><th>Category</th><th>Seen</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th></tr></thead>

<tbody>{all_html if all_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No pattern data yet</td></tr>'}</tbody>

</table>



</div>

</body></html>"""





# ============================================================

# ANALYTICS API ENDPOINT (for charts)

# ============================================================

@app.get("/api/analytics-data")

async def analytics_data():

    """JSON endpoint for chart data"""

    analytics = get_analytics()

    patterns = get_pattern_analytics()

    

    # Format daily trend for chart

    daily_labels = []

    daily_analyzed = []

    daily_buys = []

    daily_passes = []

    

    for day in reversed(analytics.get('daily_trend', [])):

        daily_labels.append(day.get('date', '')[-5:])  # MM-DD format

        daily_analyzed.append(day.get('total_analyzed', 0))

        daily_buys.append(day.get('buy_count', 0))

        daily_passes.append(day.get('pass_count', 0))

    

    # Format category data for donut chart

    cat_labels = []

    cat_values = []

    cat_colors = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

    

    for i, cat in enumerate(analytics.get('by_category', [])):

        cat_labels.append(cat.get('category', 'Unknown').upper())

        cat_values.append(cat.get('cnt', 0))

    

    # Format keyword data for bar chart

    kw_labels = []

    kw_pass_rates = []

    kw_counts = []

    

    for kw in patterns.get('high_pass_keywords', [])[:10]:

        kw_labels.append(kw.get('keyword', '')[:15])

        kw_pass_rates.append(round(kw.get('pass_rate', 0) * 100, 1))

        kw_counts.append(kw.get('times_analyzed', 0))

    

    return {

        "totals": {

            "analyzed": analytics.get('total_analyzed', 0),

            "buys": analytics.get('buy_count', 0),

            "passes": analytics.get('pass_count', 0),

            "purchases": analytics.get('actual_purchases', 0),

            "profit": analytics.get('total_profit', 0)

        },

        "daily": {

            "labels": daily_labels,

            "analyzed": daily_analyzed,

            "buys": daily_buys,

            "passes": daily_passes

        },

        "categories": {

            "labels": cat_labels,

            "values": cat_values,

            "colors": cat_colors[:len(cat_labels)]

        },

        "keywords": {

            "labels": kw_labels,

            "passRates": kw_pass_rates,

            "counts": kw_counts

        }

    }





# ============================================================

# DEALS API ENDPOINT (for desktop app)

# ============================================================

@app.get("/api/deals")

async def get_deals(limit: int = 50, include_research: bool = True, include_history: bool = False):

    """

    Get BUY and RESEARCH deals for the desktop dashboard.

    Returns deals sorted by timestamp (newest first).

    Includes thumbnail URLs and additional analysis data.

    

    Args:

        limit: Max number of deals to return

        include_research: Include RESEARCH recommendations (not just BUY)

        include_history: If True, load all historical deals. If False (default), only current session.

    """

    try:

        deals = []

        

        # Get from in-memory stats

        for listing_id, listing in STATS.get('listings', {}).items():

            rec = listing.get('recommendation', '')

            if rec == 'BUY' or (rec == 'RESEARCH' and include_research):

                # Get input data for additional fields

                input_data = listing.get('input_data', {})

                

                # Try to get thumbnail - prefer gallery_url, then images array

                thumbnail = input_data.get('gallery_url', '')

                if not thumbnail:

                    images = input_data.get('images', [])

                    if images and len(images) > 0:

                        first_img = images[0]

                        if isinstance(first_img, str) and first_img.startswith('http'):

                            thumbnail = first_img

                        elif isinstance(first_img, dict):

                            thumbnail = first_img.get('url', first_img.get('URL', ''))

                

                deals.append({

                    'id': listing_id,

                    'title': listing.get('title', 'Unknown'),

                    'total_price': listing.get('total_price', 0),

                    'category': listing.get('category', 'unknown'),

                    'recommendation': rec,

                    'margin': listing.get('margin', 'NA'),

                    'confidence': listing.get('confidence', 'NA'),

                    'reasoning': listing.get('reasoning', '')[:500],

                    'timestamp': listing.get('timestamp', ''),

                    'thumbnail': thumbnail,

                    'ebay_url': input_data.get('ebay_url', input_data.get('ViewUrl', input_data.get('CheckoutUrl', ''))),

                    'item_id': input_data.get('ebay_item_id', input_data.get('ItemId', '')),

                })

        

        # Also get from database for persistence across restarts

        # BUT only load listings from CURRENT SESSION to avoid slow startup

        try:

            conn = sqlite3.connect(DB_PATH)

            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()

            

            # Only get listings from current session unless include_history=True

            if include_history:

                # Load all historical deals

                cursor.execute("""

                    SELECT id, title, total_price, category, recommendation, margin, confidence, reasoning, timestamp, raw_response

                    FROM listings 

                    WHERE recommendation IN ('BUY', 'RESEARCH')

                    ORDER BY timestamp DESC

                    LIMIT ?

                """, (limit * 2,))

            else:

                # Only get listings from current session (after session_start)

                session_start = STATS.get("session_start", datetime.now().isoformat())

                cursor.execute("""

                    SELECT id, title, total_price, category, recommendation, margin, confidence, reasoning, timestamp, raw_response

                    FROM listings 

                    WHERE recommendation IN ('BUY', 'RESEARCH')

                    AND timestamp >= ?

                    ORDER BY timestamp DESC

                    LIMIT ?

                """, (session_start, limit * 2,))

            

            db_deals = cursor.fetchall()

            conn.close()

            

            # Merge with in-memory (avoid duplicates)

            seen_ids = {d['id'] for d in deals}

            for row in db_deals:

                if row['id'] not in seen_ids:

                    rec = row['recommendation']

                    if rec == 'BUY' or (rec == 'RESEARCH' and include_research):

                        deals.append({

                            'id': row['id'],

                            'title': row['title'],

                            'total_price': row['total_price'],

                            'category': row['category'],

                            'recommendation': rec,

                            'margin': row['margin'],

                            'confidence': row['confidence'],

                            'reasoning': (row['reasoning'] or '')[:500],

                            'timestamp': row['timestamp'],

                            'thumbnail': '',  # Not stored in DB currently

                            'ebay_url': '',

                            'item_id': '',

                        })

                        seen_ids.add(row['id'])

        except Exception as db_err:

            logger.warning(f"[DEALS API] DB query error: {db_err}")

        

        # Sort by timestamp (newest first)

        deals.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        

        # Limit

        deals = deals[:limit]

        

        # Stats

        buy_count = sum(1 for d in deals if d['recommendation'] == 'BUY')

        research_count = sum(1 for d in deals if d['recommendation'] == 'RESEARCH')

        

        return {

            'count': len(deals),

            'buy_count': buy_count,

            'research_count': research_count,

            'deals': deals

        }

        

    except Exception as e:

        logger.error(f"[DEALS API] Error: {e}")

        return {'error': str(e), 'deals': []}





@app.post("/api/deals/clear")

async def clear_deals():

    """Clear all BUY/RESEARCH deals from memory AND database (for dashboard clear button)"""

    try:

        # Clear from in-memory stats

        listings_to_remove = []

        for listing_id, listing in STATS.get('listings', {}).items():

            rec = listing.get('recommendation', '')

            if rec in ('BUY', 'RESEARCH'):

                listings_to_remove.append(listing_id)

        

        for lid in listings_to_remove:

            del STATS['listings'][lid]

        

        memory_cleared = len(listings_to_remove)

        

        # Also clear from database

        db_cleared = 0

        try:

            conn = sqlite3.connect(DB_PATH)

            cursor = conn.cursor()

            cursor.execute("DELETE FROM listings WHERE recommendation IN ('BUY', 'RESEARCH')")

            db_cleared = cursor.rowcount

            conn.commit()

            conn.close()

        except Exception as db_err:

            logger.warning(f"[DEALS API] DB clear error: {db_err}")

        

        logger.info(f"[DEALS API] Cleared {memory_cleared} from memory, {db_cleared} from database")

        return {'cleared_memory': memory_cleared, 'cleared_db': db_cleared, 'success': True}

        

    except Exception as e:

        logger.error(f"[DEALS API] Clear error: {e}")

        return {'error': str(e), 'success': False}





# ============================================================

# TRAINING DATA ENDPOINTS

# ============================================================

@app.get("/api/training-data")

async def get_training_data(limit: int = 100):

    """Get training override data for analysis"""

    try:

        if not TRAINING_LOG_PATH.exists():

            return {"count": 0, "overrides": [], "summary": {}}

        

        overrides = []

        with open(TRAINING_LOG_PATH, 'r', encoding='utf-8') as f:

            for line in f:

                try:

                    overrides.append(json.loads(line.strip()))

                except:

                    continue

        

        # Get most recent first

        overrides = list(reversed(overrides[-limit:]))

        

        # Summary statistics

        summary = {

            "total_overrides": len(overrides),

            "by_type": {},

            "by_category": {},

            "common_issues": []

        }

        

        for o in overrides:

            otype = o.get('override_type', 'Unknown')

            cat = o.get('input', {}).get('category', 'Unknown')

            summary["by_type"][otype] = summary["by_type"].get(otype, 0) + 1

            summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1

        

        return {

            "count": len(overrides),

            "overrides": overrides,

            "summary": summary

        }

    except Exception as e:

        return {"error": str(e)}





@app.get("/training", response_class=HTMLResponse)

async def training_dashboard():

    """Visual dashboard for training data analysis"""

    try:

        overrides = []

        if TRAINING_LOG_PATH.exists():

            with open(TRAINING_LOG_PATH, 'r', encoding='utf-8') as f:

                for line in f:

                    try:

                        overrides.append(json.loads(line.strip()))

                    except:

                        continue

        

        # Summary

        by_type = {}

        by_category = {}

        for o in overrides:

            otype = o.get('override_type', 'Unknown')

            cat = o.get('input', {}).get('category', 'Unknown')

            by_type[otype] = by_type.get(otype, 0) + 1

            by_category[cat] = by_category.get(cat, 0) + 1

        

        # Build table rows

        rows = ""

        for o in reversed(overrides[-50:]):  # Most recent 50

            ts = o.get('timestamp', '')[:19]

            title = o.get('input', {}).get('title', 'N/A')[:50]

            price = o.get('input', {}).get('price', 0)

            cat = o.get('input', {}).get('category', 'N/A')

            t1_rec = o.get('tier1_output', {}).get('recommendation', '?')

            t2_rec = o.get('tier2_output', {}).get('recommendation', '?')

            t1_profit = o.get('tier1_output', {}).get('profit', 'N/A')

            t2_profit = o.get('tier2_output', {}).get('profit', 'N/A')

            t2_reason = o.get('tier2_output', {}).get('tier2_reason', '')[:100]

            

            color = '#ef4444' if t1_rec == 'BUY' and t2_rec == 'PASS' else '#f59e0b'

            

            rows += f'''

            <tr style="border-bottom: 1px solid #333;">

                <td style="padding: 8px; color: #888;">{ts}</td>

                <td style="padding: 8px;">{title}</td>

                <td style="padding: 8px;">${price:.2f}</td>

                <td style="padding: 8px;">{cat}</td>

                <td style="padding: 8px; color: #22c55e;">{t1_rec}</td>

                <td style="padding: 8px;">{t1_profit}</td>

                <td style="padding: 8px; color: {color};">{t2_rec}</td>

                <td style="padding: 8px;">{t2_profit}</td>

                <td style="padding: 8px; color: #888; font-size: 11px;">{t2_reason}</td>

            </tr>

            '''

        

        # Build summary cards

        type_cards = ""

        for otype, count in sorted(by_type.items(), key=lambda x: -x[1]):

            color = '#ef4444' if 'PASS' in otype else '#f59e0b'

            type_cards += f'<div style="background: #1a1a2e; padding: 10px 15px; border-radius: 8px; margin: 5px;"><span style="color: {color}; font-weight: bold;">{otype}</span>: {count}</div>'

        

        cat_cards = ""

        for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):

            cat_cards += f'<div style="background: #1a1a2e; padding: 10px 15px; border-radius: 8px; margin: 5px;">{cat}: {count}</div>'

        

        html = f'''

        <!DOCTYPE html>

        <html>

        <head>

            <title>Training Data - Override Analysis</title>

            <style>

                body {{ background: #0f0f1a; color: #e0e0e0; font-family: system-ui; padding: 20px; }}

                h1 {{ color: #6366f1; }}

                h2 {{ color: #a5b4fc; margin-top: 30px; }}

                table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 8px; }}

                th {{ background: #252540; padding: 12px; text-align: left; }}

                .summary {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }}

                .export-btn {{ background: #6366f1; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}

            </style>

        </head>

        <body>

            <h1>Training Data - Tier Override Analysis</h1>

            <p>Captures cases where Tier 2 (Sonnet) corrected Tier 1 (Tier1) mistakes. Use this to improve prompts and identify patterns.</p>

            

            <h2>Override Types</h2>

            <div class="summary">{type_cards}</div>

            

            <h2>By Category</h2>

            <div class="summary">{cat_cards}</div>

            

            <h2>Recent Overrides ({len(overrides)} total)</h2>

            <button class="export-btn" onclick="window.location='/api/training-data?limit=1000'">Export JSON</button>

            

            <table style="margin-top: 20px;">

                <tr>

                    <th>Time</th>

                    <th>Title</th>

                    <th>Price</th>

                    <th>Category</th>

                    <th>Tier1</th>

                    <th>T1 Profit</th>

                    <th>Tier2</th>

                    <th>T2 Profit</th>

                    <th>Reason</th>

                </tr>

                {rows if rows else '<tr><td colspan="9" style="padding: 20px; text-align: center; color: #888;">No overrides logged yet. They will appear here when Tier 2 corrects Tier 1 recommendations.</td></tr>'}

            </table>

            

            <h2 style="margin-top: 40px;">Using This Data</h2>

            <ul>

                <li><strong>BUY_TO_PASS</strong> = Tier1 said BUY but Sonnet found it was actually a bad deal (most critical errors)</li>

                <li><strong>BUY_TO_RESEARCH</strong> = Tier1 was too confident, Sonnet wants more verification</li>

                <li><strong>RESEARCH_TO_PASS</strong> = Tier1 was uncertain but Sonnet confirmed it's not worth it</li>

            </ul>

            <p>Look for patterns in the reasoning - common words/phrases that correlate with errors can be added to prompts or sanity checks.</p>

        </body>

        </html>

        '''

        return HTMLResponse(content=html)

    except Exception as e:

        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")





@app.get("/training/clear")

async def clear_training_data():

    """Clear training data log"""

    try:

        if TRAINING_LOG_PATH.exists():

            TRAINING_LOG_PATH.unlink()

        return {"status": "cleared"}

    except Exception as e:

        return {"error": str(e)}





# ============================================================

# PURCHASE LOGGING - Track items user actually bought

# ============================================================



def log_purchase(listing_data: dict, analysis_data: dict, notes: str = ""):

    """Log a purchase to the purchases.jsonl file"""

    try:

        # Extract seller data if present
        seller_data = listing_data.get("seller", {})

        purchase_entry = {

            "timestamp": datetime.now().isoformat(),

            "listing": {

                "title": listing_data.get("title", ""),

                "price": listing_data.get("price") or listing_data.get("total_price"),

                "item_id": listing_data.get("item_id") or listing_data.get("id"),

                "category": listing_data.get("category", ""),

                "url": listing_data.get("url", ""),

                "condition": listing_data.get("condition", ""),

                "posted_time": listing_data.get("posted_time", ""),

            },

            "seller": {

                "seller_id": seller_data.get("seller_id", "") or listing_data.get("SellerUserID", ""),

                "feedback_score": seller_data.get("feedback_score", "") or listing_data.get("SellerFeedback", ""),

                "feedback_percent": seller_data.get("feedback_percent", ""),

                "seller_type": seller_data.get("seller_type", "") or listing_data.get("SellerType", ""),

            },

            "analysis": {

                "recommendation": analysis_data.get("Recommendation") or analysis_data.get("recommendation"),

                "profit": analysis_data.get("Profit") or analysis_data.get("profit") or analysis_data.get("Margin"),

                "confidence": analysis_data.get("confidence"),

                "weight": analysis_data.get("weight") or analysis_data.get("goldweight") or analysis_data.get("silverweight"),

                "weight_source": analysis_data.get("weightSource"),

                "melt_value": analysis_data.get("meltvalue") or analysis_data.get("melt"),

                "max_buy": analysis_data.get("maxBuy"),

                "karat": analysis_data.get("karat"),

                "market_price": analysis_data.get("market_price"),

                "item_type": analysis_data.get("itemtype"),

                "reasoning": analysis_data.get("reasoning", "")[:500],

            },

            "notes": notes,

        }

        

        with open(PURCHASE_LOG_PATH, 'a', encoding='utf-8') as f:

            f.write(json.dumps(purchase_entry) + '\n')

        

        logger.info(f"[PURCHASE] Logged: {listing_data.get('title', '')[:50]} @ ${listing_data.get('price')}")

        return True

    except Exception as e:

        logger.error(f"[PURCHASE] Failed to log: {e}")

        return False





@app.post("/api/log-purchase")

async def api_log_purchase(request: Request):

    """API endpoint to log a purchase"""

    try:

        data = await request.json()

        listing_data = data.get("listing", {})

        analysis_data = data.get("analysis", {})

        notes = data.get("notes", "")

        

        success = log_purchase(listing_data, analysis_data, notes)

        

        if success:

            return {"status": "logged", "message": "Purchase recorded successfully"}

        else:

            return JSONResponse({"status": "error", "message": "Failed to log purchase"}, status_code=500)

    except Exception as e:

        logger.error(f"[PURCHASE] API error: {e}")

        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)





@app.get("/log-purchase-quick", response_class=HTMLResponse)

async def log_purchase_quick(

    title: str = "",

    price: float = 0,

    category: str = "",

    profit: float = 0,

    confidence: str = "",

    recommendation: str = "",

    # Seller info
    seller_id: str = "",

    feedback_score: str = "",

    feedback_percent: str = "",

    seller_type: str = "",

    # Listing info
    item_id: str = "",

    condition: str = "",

    posted_time: str = "",

    # Analysis extras
    weight: str = "",

    melt: str = "",

    karat: str = "",

    market_price: str = ""

):

    """Quick log purchase from Discord link - shows confirmation page"""

    try:

        listing_data = {

            "title": title,

            "price": price,

            "category": category,

            "item_id": item_id,

            "condition": condition,

            "posted_time": posted_time,

        }

        seller_data = {

            "seller_id": seller_id,

            "feedback_score": feedback_score,

            "feedback_percent": feedback_percent,

            "seller_type": seller_type,

        }

        analysis_data = {

            "Recommendation": recommendation,

            "profit": profit,

            "confidence": confidence,

            "weight": weight,

            "melt": melt,

            "karat": karat,

            "market_price": market_price,

        }

        # Merge seller data into listing_data for storage
        listing_data["seller"] = seller_data

        success = log_purchase(listing_data, analysis_data, notes="Logged from Discord")

        

        if success:

            return HTMLResponse(content=f'''<!DOCTYPE html>

<html><head>

<title>Purchase Logged</title>

<style>

body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 40px; text-align: center; }}

.success {{ background: #22c55e; color: #fff; padding: 20px 40px; border-radius: 12px; display: inline-block; margin: 20px; }}

h1 {{ color: #22c55e; }}

a {{ color: #6366f1; }}

</style>

</head><body>

<div class="success">Purchase Logged!</div>

<h1>{title[:60]}...</h1>

<p>Price: ${price:.2f} | Category: {category} | Est Profit: ${profit:.0f}</p>

<p><a href="/purchases">View All Purchases</a> | <a href="javascript:window.close()">Close</a></p>

</body></html>''')

        else:

            return HTMLResponse(content="<h1>Error logging purchase</h1>", status_code=500)

    except Exception as e:

        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>", status_code=500)





@app.get("/api/purchases")

async def api_get_purchases(limit: int = 100):

    """Get purchase history"""

    try:

        if not PURCHASE_LOG_PATH.exists():

            return {"purchases": [], "count": 0}

        

        purchases = []

        with open(PURCHASE_LOG_PATH, 'r', encoding='utf-8') as f:

            for line in f:

                if line.strip():

                    try:

                        purchases.append(json.loads(line))

                    except:

                        pass

        

        # Return most recent first

        purchases.reverse()

        return {"purchases": purchases[:limit], "count": len(purchases)}

    except Exception as e:

        return JSONResponse({"error": str(e)}, status_code=500)





@app.get("/purchases", response_class=HTMLResponse)

async def purchases_page():

    """Purchase history dashboard"""

    try:

        purchases = []

        total_spent = 0

        total_projected_profit = 0

        

        if PURCHASE_LOG_PATH.exists():

            with open(PURCHASE_LOG_PATH, 'r', encoding='utf-8') as f:

                for line in f:

                    if line.strip():

                        try:

                            p = json.loads(line)

                            purchases.append(p)

                            price = p.get("listing", {}).get("price")

                            if price:

                                try:

                                    total_spent += float(price)

                                except:

                                    pass

                            profit = p.get("analysis", {}).get("profit")

                            if profit:

                                try:

                                    total_projected_profit += float(str(profit).replace('+', '').replace('$', ''))

                                except:

                                    pass

                        except:

                            pass

        

        purchases.reverse()

        

        # Build table rows

        rows = ""

        for p in purchases[:100]:

            listing = p.get("listing", {})

            analysis = p.get("analysis", {})

            timestamp = p.get("timestamp", "")[:19].replace("T", " ")

            title = listing.get("title", "")[:50]

            price = listing.get("price", "--")

            category = listing.get("category", "--")

            profit = analysis.get("profit", "--")

            confidence = analysis.get("confidence", "--")

            weight = analysis.get("weight", "--")

            

            profit_color = "#22c55e" if str(profit).startswith("+") or (isinstance(profit, (int, float)) and profit > 0) else "#ef4444"

            

            rows += f'''

            <tr>

                <td style="color:#888;font-size:12px">{timestamp}</td>

                <td>{title}</td>

                <td>${price}</td>

                <td>{category}</td>

                <td style="color:{profit_color};font-weight:600">${profit}</td>

                <td>{confidence}</td>

                <td>{weight}</td>

            </tr>'''

        

        html = f'''<!DOCTYPE html>

<html><head>

<title>Purchase History</title>

<style>

body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}

.container {{ max-width: 1400px; margin: 0 auto; }}

h1 {{ color: #fff; margin-bottom: 20px; }}

.stats {{ display: flex; gap: 20px; margin-bottom: 30px; }}

.stat-card {{ background: #1a1a2e; padding: 20px; border-radius: 12px; text-align: center; min-width: 150px; }}

.stat-value {{ font-size: 28px; font-weight: bold; color: #22c55e; }}

.stat-label {{ color: #888; font-size: 14px; margin-top: 5px; }}

table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}

th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #333; }}

th {{ background: #252540; color: #888; font-weight: 600; text-transform: uppercase; font-size: 11px; }}

td {{ font-size: 13px; }}

a {{ color: #6366f1; text-decoration: none; }}

.back-link {{ margin-bottom: 20px; display: inline-block; }}

</style>

</head><body>

<div class="container">

<a href="/" class="back-link">&larr; Back to Dashboard</a>

<h1>Purchase History</h1>



<div class="stats">

    <div class="stat-card">

        <div class="stat-value">{len(purchases)}</div>

        <div class="stat-label">Total Purchases</div>

    </div>

    <div class="stat-card">

        <div class="stat-value">${total_spent:,.0f}</div>

        <div class="stat-label">Total Spent</div>

    </div>

    <div class="stat-card">

        <div class="stat-value" style="color:#22c55e">${total_projected_profit:,.0f}</div>

        <div class="stat-label">Projected Profit</div>

    </div>

</div>



<table>

<thead>

<tr><th>Time</th><th>Title</th><th>Price</th><th>Category</th><th>Est Profit</th><th>Confidence</th><th>Weight</th></tr>

</thead>

<tbody>

{rows if rows else '<tr><td colspan="7" style="text-align:center;color:#888;padding:40px;">No purchases logged yet. Click "I Bought This" on listings to track your purchases.</td></tr>'}

</tbody>

</table>



<p style="margin-top:20px;color:#888;font-size:12px;">

Export: <a href="/api/purchases?limit=1000">JSON</a>

</p>

</div>

</body></html>'''

        

        return HTMLResponse(content=html)

    except Exception as e:

        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")







@app.get("/analytics", response_class=HTMLResponse)

async def analytics_page():

    """Visual analytics dashboard with charts"""

    analytics = get_analytics()

    patterns = get_pattern_analytics()

    

    # Build recent listings table

    recent_html = ""

    for listing in analytics.get('recent', [])[:10]:

        rec = listing.get('recommendation', 'UNKNOWN')

        rec_color = '#22c55e' if rec == 'BUY' else '#ef4444' if rec == 'PASS' else '#f59e0b'

        margin = listing.get('margin', '--')

        recent_html += f'''

        <tr>

            <td><a href="/detail/{listing.get('id', '')}" style="color:#6366f1">{listing.get('title', '')[:40]}...</a></td>

            <td>{listing.get('category', '').upper()}</td>

            <td style="color:{rec_color};font-weight:600">{rec}</td>

            <td>{margin}</td>

        </tr>'''

    

    # Build high-pass keywords table

    keywords_html = ""

    for kw in patterns.get('high_pass_keywords', [])[:8]:

        pass_rate = kw.get('pass_rate', 0) * 100

        keywords_html += f'''

        <tr>

            <td style="font-weight:500">{kw.get('keyword', '')}</td>

            <td>{kw.get('times_analyzed', 0)}</td>

            <td style="color:#ef4444;font-weight:600">{pass_rate:.0f}%</td>

        </tr>'''

    

    # Calculate buy rate

    total = analytics.get('total_analyzed', 0)

    buys = analytics.get('buy_count', 0)

    buy_rate = (buys / total * 100) if total > 0 else 0

    

    return f"""<!DOCTYPE html>

<html><head>

<title>Analytics Dashboard</title>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<style>

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }}

.header {{ background: #1a1a2e; padding: 20px 30px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }}

.logo {{ font-size: 20px; font-weight: 700; color: #fff; }}

.logo span {{ color: #6366f1; }}

.nav {{ display: flex; gap: 15px; }}

.nav a {{ color: #888; text-decoration: none; padding: 8px 16px; border-radius: 6px; transition: all 0.2s; }}

.nav a:hover, .nav a.active {{ color: #fff; background: rgba(99,102,241,0.2); }}

.container {{ max-width: 1400px; margin: 0 auto; padding: 25px; }}

.page-title {{ font-size: 28px; font-weight: 700; margin-bottom: 25px; color: #fff; }}



/* Stats Cards */

.stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 20px; margin-bottom: 30px; }}

.stat-card {{ background: linear-gradient(135deg, #1a1a2e 0%, #252540 100%); border-radius: 16px; padding: 25px; position: relative; overflow: hidden; }}

.stat-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: linear-gradient(90deg, #6366f1, #8b5cf6); }}

.stat-card.green::before {{ background: linear-gradient(90deg, #22c55e, #16a34a); }}

.stat-card.red::before {{ background: linear-gradient(90deg, #ef4444, #dc2626); }}

.stat-card.yellow::before {{ background: linear-gradient(90deg, #f59e0b, #d97706); }}

.stat-value {{ font-size: 36px; font-weight: 800; color: #fff; margin-bottom: 5px; }}

.stat-label {{ font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}

.stat-sub {{ font-size: 12px; color: #666; margin-top: 8px; }}



/* Charts */

.charts-row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 30px; }}

.chart-card {{ background: #1a1a2e; border-radius: 16px; padding: 25px; }}

.chart-title {{ font-size: 16px; font-weight: 600; margin-bottom: 20px; color: #fff; display: flex; align-items: center; gap: 10px; }}

.chart-title::before {{ content: ''; width: 4px; height: 20px; background: #6366f1; border-radius: 2px; }}

.chart-container {{ position: relative; height: 280px; }}



/* Tables */

.tables-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}

.table-card {{ background: #1a1a2e; border-radius: 16px; overflow: hidden; }}

.table-header {{ padding: 20px 25px; border-bottom: 1px solid #333; font-weight: 600; color: #fff; display: flex; align-items: center; gap: 10px; }}

.table-header::before {{ content: ''; width: 4px; height: 20px; background: #6366f1; border-radius: 2px; }}

table {{ width: 100%; border-collapse: collapse; }}

th, td {{ padding: 14px 20px; text-align: left; border-bottom: 1px solid #252540; }}

th {{ background: #252540; color: #888; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}

td {{ font-size: 14px; }}

tr:hover {{ background: rgba(99,102,241,0.05); }}



/* Responsive */

@media (max-width: 1200px) {{

    .stats-grid {{ grid-template-columns: repeat(3, 1fr); }}

    .charts-row, .tables-row {{ grid-template-columns: 1fr; }}

}}

@media (max-width: 768px) {{

    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}

}}

</style>

</head><body>

<div class="header">

    <div class="logo">Claude <span>Proxy v3</span></div>

    <div class="nav">

        <a href="/">Dashboard</a>

        <a href="/patterns">Patterns</a>

        <a href="/analytics" class="active">Analytics</a>

    </div>

</div>



<div class="container">

    <h1 class="page-title">Analytics Dashboard</h1>

    

    <!-- Stats Cards -->

    <div class="stats-grid">

        <div class="stat-card">

            <div class="stat-value">{analytics.get('total_analyzed', 0):,}</div>

            <div class="stat-label">Total Analyzed</div>

            <div class="stat-sub">All time listings</div>

        </div>

        <div class="stat-card green">

            <div class="stat-value" style="color:#22c55e">{analytics.get('buy_count', 0):,}</div>

            <div class="stat-label">BUY Signals</div>

            <div class="stat-sub">{buy_rate:.1f}% of analyzed</div>

        </div>

        <div class="stat-card red">

            <div class="stat-value" style="color:#ef4444">{analytics.get('pass_count', 0):,}</div>

            <div class="stat-label">PASS Signals</div>

            <div class="stat-sub">Filtered out</div>

        </div>

        <div class="stat-card yellow">

            <div class="stat-value" style="color:#f59e0b">{analytics.get('actual_purchases', 0)}</div>

            <div class="stat-label">Purchases Made</div>

            <div class="stat-sub">Following BUY signals</div>

        </div>

        <div class="stat-card">

            <div class="stat-value">${analytics.get('total_profit', 0):,.0f}</div>

            <div class="stat-label">Total Profit</div>

            <div class="stat-sub">Tracked outcomes</div>

        </div>

    </div>

    

    <!-- Charts Row -->

    <div class="charts-row">

        <div class="chart-card">

            <div class="chart-title">Daily Activity (Last 7 Days)</div>

            <div class="chart-container">

                <canvas id="dailyChart"></canvas>

            </div>

        </div>

        <div class="chart-card">

            <div class="chart-title">By Category</div>

            <div class="chart-container">

                <canvas id="categoryChart"></canvas>

            </div>

        </div>

    </div>

    

    <!-- Keywords Chart -->

    <div class="chart-card" style="margin-bottom:30px;">

        <div class="chart-title">Top PASS Keywords (Negative Filter Candidates)</div>

        <div class="chart-container" style="height:220px;">

            <canvas id="keywordsChart"></canvas>

        </div>

    </div>

    

    <!-- Tables Row -->

    <div class="tables-row">

        <div class="table-card">

            <div class="table-header">Recent Listings</div>

            <table>

                <thead><tr><th>Title</th><th>Category</th><th>Result</th><th>Margin</th></tr></thead>

                <tbody>{recent_html if recent_html else '<tr><td colspan="4" style="text-align:center;color:#666;">No listings yet</td></tr>'}</tbody>

            </table>

        </div>

        <div class="table-card">

            <div class="table-header">High-Pass Keywords</div>

            <table>

                <thead><tr><th>Keyword</th><th>Analyzed</th><th>Pass Rate</th></tr></thead>

                <tbody>{keywords_html if keywords_html else '<tr><td colspan="3" style="text-align:center;color:#666;">Need more data</td></tr>'}</tbody>

            </table>

        </div>

    </div>

</div>



<script>

// Fetch data and render charts

fetch('/api/analytics-data')

    .then(res => res.json())

    .then(data => {{

        // Daily Activity Line Chart

        new Chart(document.getElementById('dailyChart'), {{

            type: 'line',

            data: {{

                labels: data.daily.labels,

                datasets: [

                    {{

                        label: 'Analyzed',

                        data: data.daily.analyzed,

                        borderColor: '#6366f1',

                        backgroundColor: 'rgba(99,102,241,0.1)',

                        fill: true,

                        tension: 0.4

                    }},

                    {{

                        label: 'BUY',

                        data: data.daily.buys,

                        borderColor: '#22c55e',

                        backgroundColor: 'transparent',

                        tension: 0.4

                    }},

                    {{

                        label: 'PASS',

                        data: data.daily.passes,

                        borderColor: '#ef4444',

                        backgroundColor: 'transparent',

                        tension: 0.4

                    }}

                ]

            }},

            options: {{

                responsive: true,

                maintainAspectRatio: false,

                plugins: {{

                    legend: {{

                        position: 'top',

                        labels: {{ color: '#888', padding: 20 }}

                    }}

                }},

                scales: {{

                    x: {{ 

                        grid: {{ color: '#252540' }},

                        ticks: {{ color: '#888' }}

                    }},

                    y: {{ 

                        grid: {{ color: '#252540' }},

                        ticks: {{ color: '#888' }},

                        beginAtZero: true

                    }}

                }}

            }}

        }});

        

        // Category Donut Chart

        new Chart(document.getElementById('categoryChart'), {{

            type: 'doughnut',

            data: {{

                labels: data.categories.labels,

                datasets: [{{

                    data: data.categories.values,

                    backgroundColor: data.categories.colors,

                    borderWidth: 0

                }}]

            }},

            options: {{

                responsive: true,

                maintainAspectRatio: false,

                plugins: {{

                    legend: {{

                        position: 'right',

                        labels: {{ color: '#888', padding: 15 }}

                    }}

                }},

                cutout: '65%'

            }}

        }});

        

        // Keywords Bar Chart

        new Chart(document.getElementById('keywordsChart'), {{

            type: 'bar',

            data: {{

                labels: data.keywords.labels,

                datasets: [{{

                    label: 'Pass Rate %',

                    data: data.keywords.passRates,

                    backgroundColor: '#ef4444',

                    borderRadius: 6

                }}]

            }},

            options: {{

                responsive: true,

                maintainAspectRatio: false,

                indexAxis: 'y',

                plugins: {{

                    legend: {{ display: false }}

                }},

                scales: {{

                    x: {{ 

                        grid: {{ color: '#252540' }},

                        ticks: {{ color: '#888' }},

                        max: 100

                    }},

                    y: {{ 

                        grid: {{ display: false }},

                        ticks: {{ color: '#888' }}

                    }}

                }}

            }}

        }});

    }});

</script>

</body></html>"""





# ============================================================

# DETAIL VIEW

# ============================================================

@app.get("/detail/{listing_id}", response_class=HTMLResponse)

async def detail_view(listing_id: str):

    """Detailed view of a single listing analysis"""

    

    # Check in-memory stats first

    listing = STATS["listings"].get(listing_id)

    

    if not listing:

        # Try database

        row = db.fetchone(

            "SELECT * FROM listings WHERE id = ?", (listing_id,)

        )

        if row:

            listing = dict(row)

    

    if not listing:

        return HTMLResponse(content=f"""

        <html><body style="font-family:system-ui;background:#0f0f1a;color:#fff;padding:40px;">

        <h1>Listing not found</h1>

        <p>ID: {listing_id}</p>

        <a href="/" style="color:#6366f1;">x ƒÆ’¢Back to Dashboard</a>

        </body></html>

        """)

    

    # Extract data

    title = listing.get('title', 'Unknown')

    category = listing.get('category', 'unknown')

    recommendation = listing.get('recommendation', 'UNKNOWN')

    total_price = listing.get('total_price', '--')

    margin = listing.get('margin', '--')

    confidence = format_confidence(listing.get('confidence', '--'))

    reasoning = listing.get('reasoning', 'No reasoning available')

    timestamp = listing.get('timestamp', '--')

    raw_response = listing.get('raw_response', 'Not available')

    

    # Parse raw response for additional fields

    parsed_response = {}

    if raw_response and raw_response != 'Not available':

        try:

            parsed_response = json.loads(raw_response) if isinstance(raw_response, str) else raw_response

        except:

            pass

    

    # Build confidence breakdown HTML

    confidence_breakdown_html = build_confidence_breakdown(category, parsed_response, listing)

    

    # Input data

    input_data = listing.get('input_data', {})

    if isinstance(input_data, str):

        try:

            input_data = eval(input_data)  # Convert string repr back to dict

        except:

            input_data = {}

    

    # Build input data HTML

    input_html = ""

    for key, value in input_data.items():

        if value and key != 'images':

            input_html += f'<tr><td style="color:#888;padding:8px;border-bottom:1px solid #333;">{key}</td><td style="padding:8px;border-bottom:1px solid #333;">{str(value)[:100]}</td></tr>'

    

    # Recommendation styling

    if recommendation == 'BUY':

        rec_color = '#22c55e'

        rec_bg = 'rgba(34,197,94,0.1)'

    elif recommendation == 'PASS':

        rec_color = '#ef4444'

        rec_bg = 'rgba(239,68,68,0.1)'

    else:

        rec_color = '#f59e0b'

        rec_bg = 'rgba(245,158,11,0.1)'

    

    return f"""<!DOCTYPE html>

<html><head>

<title>Detail - {title[:30]}</title>

<style>

body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}

.container {{ max-width: 900px; margin: 0 auto; }}

.back {{ color: #6366f1; text-decoration: none; display: inline-block; margin-bottom: 20px; }}

.back:hover {{ text-decoration: underline; }}

.header {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}

.title {{ font-size: 18px; font-weight: 600; margin-bottom: 10px; word-break: break-word; }}

.meta {{ display: flex; gap: 20px; flex-wrap: wrap; color: #888; font-size: 14px; }}

.recommendation {{ display: inline-block; padding: 8px 20px; border-radius: 8px; font-size: 24px; font-weight: 700; background: {rec_bg}; color: {rec_color}; margin-bottom: 15px; }}

.section {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}

.section-title {{ font-size: 14px; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 15px; border-bottom: 1px solid #333; padding-bottom: 10px; }}

.reasoning {{ background: #252540; border-radius: 8px; padding: 15px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }}

.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; }}

.stat-box {{ background: #252540; border-radius: 8px; padding: 15px; text-align: center; }}

.stat-value {{ font-size: 20px; font-weight: 700; color: #fff; }}

.stat-label {{ font-size: 11px; color: #888; margin-top: 5px; }}

table {{ width: 100%; border-collapse: collapse; }}

.raw {{ background: #0a0a15; border-radius: 8px; padding: 15px; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; }}

</style>

</head><body>

<div class="container">

<a href="/" class="back">x ƒÆ’¢Back to Dashboard</a>



<div class="header">

    <div class="recommendation">{recommendation}</div>

    <div class="title">{title}</div>

    <div class="meta">

        <span>Category: <strong>{category.upper()}</strong></span>

        <span>Price: <strong>${total_price}</strong></span>

        <span>Time: {timestamp[:19] if timestamp else '--'}</span>

    </div>

</div>



<div class="section">

    <div class="section-title">Analysis Results</div>

    <div class="stats-grid">

        <div class="stat-box">

            <div class="stat-value" style="color:{rec_color}">{margin}</div>

            <div class="stat-label">Profit</div>

        </div>

        <div class="stat-box">

            <div class="stat-value">{confidence}</div>

            <div class="stat-label">Confidence</div>

        </div>

        <div class="stat-box">

            <div class="stat-value">{category.upper()}</div>

            <div class="stat-label">Category</div>

        </div>

    </div>

</div>



<div class="section">

    <div class="section-title">AI Reasoning</div>

    <div class="reasoning">{reasoning}</div>

</div>



<div class="section">

    <div class="section-title">Confidence Breakdown</div>

    {confidence_breakdown_html}

</div>



<div class="section">

    <div class="section-title">Input Data</div>

    <table>{input_html if input_html else '<tr><td style="color:#666;">No input data available</td></tr>'}</table>

</div>



<div class="section">

    <div class="section-title">Raw AI Response (Debug)</div>

    <div class="raw">{raw_response}</div>

</div>



</div>

</body></html>"""





# ============================================================

# EBAY DIRECT API POLLER

# ============================================================

# Import eBay poller for direct API access (builds usage for rate limit application)

try:

    from ebay_poller import (

        get_api_stats as ebay_get_stats,

        get_new_listings as ebay_get_new,

        start_polling as ebay_start_polling,

        stop_polling as ebay_stop_polling,

        search_ebay,

        browse_api_available,

        SEARCH_CONFIGS as EBAY_SEARCH_CONFIGS,

        clear_seen_listings as ebay_clear_seen,

        get_item_description,

        get_item_details,

    )

    EBAY_POLLER_AVAILABLE = True

    if browse_api_available():

        print("[EBAY] eBay poller loaded - Browse API enabled")

    else:

        print("[EBAY] eBay poller loaded - Finding API only (add EBAY_CERT_ID for Browse API)")

except ImportError as e:

    EBAY_POLLER_AVAILABLE = False

    print(f"[EBAY] eBay poller not available: {e}")

# Configure eBay routes module
if EBAY_POLLER_AVAILABLE:
    configure_ebay(
        search_ebay=search_ebay,
        ebay_get_stats=ebay_get_stats,
        ebay_start_polling=ebay_start_polling,
        ebay_stop_polling=ebay_stop_polling,
        ebay_clear_seen=ebay_clear_seen,
        get_item_description=get_item_description,
        get_item_details=get_item_details,
        browse_api_available=browse_api_available,
        EBAY_SEARCH_CONFIGS=EBAY_SEARCH_CONFIGS,
        get_spot_prices=get_spot_prices,
        send_discord_alert=send_discord_alert,
        EBAY_POLLER_AVAILABLE=EBAY_POLLER_AVAILABLE,
    )
    # Configure eBay race routes module
    configure_ebay_race(
        search_ebay=search_ebay,
        EBAY_POLLER_AVAILABLE=EBAY_POLLER_AVAILABLE,
        EBAY_SEARCH_CONFIGS=EBAY_SEARCH_CONFIGS,
        get_comparison_stats=get_comparison_stats,
        get_race_log=get_race_log,
        reset_source_stats=reset_source_stats,
    )


# OLD EBAY ENDPOINTS - Now in routes/ebay.py
# TODO: Remove once routes/ebay.py is fully tested

@app.get("/ebay/stats")

async def ebay_stats():

    """Get eBay API usage statistics"""

    if not EBAY_POLLER_AVAILABLE:

        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    

    stats = ebay_get_stats()

    return JSONResponse({

        "status": "ok",

        "stats": stats,

        "categories_configured": list(EBAY_SEARCH_CONFIGS.keys()) if EBAY_POLLER_AVAILABLE else [],

    })





@app.get("/ebay/search")

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

    if not EBAY_POLLER_AVAILABLE:

        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    

    category_ids = None

    if category and category in EBAY_SEARCH_CONFIGS:

        category_ids = EBAY_SEARCH_CONFIGS[category]["category_ids"]

    

    listings = await search_ebay(

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

        "api_stats": ebay_get_stats(),

    })





@app.get("/ebay/gold")

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

    if not EBAY_POLLER_AVAILABLE:

        return HTMLResponse("<h1>eBay Poller Not Available</h1><p>Check EBAY_APP_ID in .env</p>")



    # Fetch listings from eBay

    category_ids = EBAY_SEARCH_CONFIGS.get("gold", {}).get("category_ids", [])

    listings = await search_ebay(

        keywords=keywords,

        category_ids=category_ids,

        price_min=price_min,

        price_max=price_max,

        entries_per_page=min(limit, 100),

    )



    # Build HTML table rows

    from datetime import datetime, timezone

    found_time = datetime.now().strftime("%I:%M:%S %p")



    rows_html = ""

    for idx, listing in enumerate(listings):

        item_id = listing.item_id

        title = listing.title[:80] + "..." if len(listing.title) > 80 else listing.title

        price = listing.price

        thumbnail = listing.gallery_url or listing.thumbnail_url or ""

        view_url = listing.view_url or f"https://www.ebay.com/itm/{item_id}"

        # Direct checkout URL (Buy It Now)

        checkout_url = f"https://www.ebay.com/itm/{item_id}?nordt=true&orig_cvip=true&rt=nc"



        # Format posted time (convert UTC to local time)

        posted_time = ""

        posted_ago = ""

        if listing.start_time:

            try:

                if hasattr(listing.start_time, 'strftime'):

                    # Convert to local time for display

                    if listing.start_time.tzinfo is not None:

                        local_time = listing.start_time.astimezone()  # Converts to local timezone

                        posted_time = local_time.strftime("%I:%M %p")

                        diff = datetime.now(timezone.utc) - listing.start_time

                    else:

                        posted_time = listing.start_time.strftime("%I:%M %p")

                        diff = datetime.now() - listing.start_time



                    # Calculate how long ago

                    mins = int(diff.total_seconds() / 60)

                    if mins < 0:

                        posted_ago = "(just now)"

                    elif mins < 60:

                        posted_ago = f"({mins}m ago)"

                    elif mins < 1440:

                        posted_ago = f"({mins // 60}h ago)"

                    else:

                        posted_ago = f"({mins // 1440}d ago)"

            except:

                pass



        # If no posted time, show ranking (sorted by newest)

        if not posted_time:

            if idx == 0:

                posted_time = "Newest"

                posted_ago = "#1"

            elif idx < 5:

                posted_time = "Very New"

                posted_ago = f"#{idx + 1}"

            elif idx < 15:

                posted_time = "Recent"

                posted_ago = f"#{idx + 1}"

            else:

                posted_time = "Listed"

                posted_ago = f"#{idx + 1}"



        rows_html += f"""

        <tr>

            <td style="text-align:center;">

                <a href="{view_url}" target="_blank">

                    <img src="{thumbnail}" alt="" style="max-width:80px; max-height:80px; border-radius:4px;"

                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2280%22 height=%2280%22><rect fill=%22%23333%22 width=%22100%%22 height=%22100%%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23666%22 text-anchor=%22middle%22 dy=%22.3em%22>No Image</text></svg>'">

                </a>

            </td>

            <td>

                <a href="{view_url}" target="_blank" style="color:#4fc3f7; text-decoration:none;">

                    {title}

                </a>

                <div style="font-size:11px; color:#888; margin-top:4px;">

                    {listing.condition} | {listing.location} | Seller: {listing.seller_id} ({listing.seller_feedback})

                </div>

                <div style="font-size:10px; margin-top:3px;">

                    <span style="color:#ff9800;">Posted: {posted_time} {posted_ago}</span>

                </div>

            </td>

            <td style="text-align:right; font-weight:bold; color:#4caf50; font-size:18px;">

                ${price:.2f}

            </td>

            <td style="text-align:center;">

                <a href="{view_url}" target="_blank"

                   style="display:inline-block; padding:6px 12px; background:#2196f3; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    View

                </a>

                <a href="{checkout_url}" target="_blank"

                   style="display:inline-block; padding:6px 12px; background:#4caf50; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    Buy Now

                </a>

                <a href="/analyze?category=gold&title={listing.title[:100]}&price={price}"

                   style="display:inline-block; padding:6px 12px; background:#ff9800; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    Analyze

                </a>

            </td>

        </tr>

        """



    stats = ebay_get_stats()



    html = f"""<!DOCTYPE html>

<html>

<head>

    <title>ShadowSnipe - Gold Listings</title>

    <style>

        body {{ background: #1a1a2e; color: #eee; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; }}

        .container {{ max-width: 1400px; margin: 0 auto; }}

        h1 {{ color: #ffd700; margin-bottom: 10px; }}

        .stats {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 30px; flex-wrap: wrap; }}

        .stat {{ text-align: center; }}

        .stat-value {{ font-size: 24px; font-weight: bold; color: #4fc3f7; }}

        .stat-label {{ font-size: 12px; color: #888; }}

        .search-form {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}

        .search-form input, .search-form select {{ padding: 8px 12px; border-radius: 4px; border: 1px solid #333; background: #0f0f23; color: #eee; }}

        .search-form button {{ padding: 8px 20px; background: #ffd700; color: #000; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }}

        .search-form button:hover {{ background: #ffed4a; }}

        table {{ width: 100%; border-collapse: collapse; background: #16213e; border-radius: 8px; overflow: hidden; }}

        th {{ background: #0f0f23; padding: 12px; text-align: left; color: #ffd700; }}

        td {{ padding: 12px; border-bottom: 1px solid #333; vertical-align: middle; }}

        tr:hover {{ background: #1f2940; }}

        .refresh-btn {{ position: fixed; bottom: 20px; right: 20px; padding: 15px 25px; background: #ffd700; color: #000; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; box-shadow: 0 4px 15px rgba(255,215,0,0.3); }}

        .auto-refresh-bar {{ position: fixed; top: 0; left: 0; right: 0; background: #16213e; padding: 8px 20px; display: flex; justify-content: space-between; align-items: center; z-index: 1000; border-bottom: 2px solid #ffd700; }}

        .countdown {{ font-size: 14px; color: #4fc3f7; }}

        .toggle-btn {{ padding: 6px 15px; border-radius: 4px; border: none; cursor: pointer; font-weight: bold; }}

        .toggle-btn.active {{ background: #4caf50; color: white; }}

        .toggle-btn.paused {{ background: #f44336; color: white; }}

        .new-badge {{ animation: pulse 1s infinite; background: #4caf50; color: white; padding: 2px 8px; border-radius: 10px; font-size: 10px; margin-left: 8px; }}

        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

        body {{ padding-top: 50px; }}

    </style>

</head>

<body>

    <div class="auto-refresh-bar">

        <div>

            <span style="color:#ffd700; font-weight:bold;">AUTO-REFRESH</span>

            <span class="countdown" id="countdown">30s</span>

            <span id="status" style="color:#4caf50; margin-left:10px;">LIVE</span>

            <span style="color:#888; margin-left:15px;">|</span>

            <span style="color:#4fc3f7; margin-left:15px;">Found at: {found_time}</span>

        </div>

        <div>

            <button class="toggle-btn active" id="toggleBtn" onclick="toggleAutoRefresh()">Pause</button>

            <select id="intervalSelect" onchange="changeInterval()" style="padding:6px; margin-left:10px; background:#0f0f23; color:#eee; border:1px solid #333; border-radius:4px;">

                <option value="15">15 sec</option>

                <option value="30" selected>30 sec</option>

                <option value="60">1 min</option>

                <option value="120">2 min</option>

            </select>

        </div>

    </div>



    <div class="container">

        <h1> Gold Listings - Live from eBay API</h1>



        <div class="stats">

            <div class="stat">

                <div class="stat-value">{len(listings)}</div>

                <div class="stat-label">Listings Found</div>

            </div>

            <div class="stat">

                <div class="stat-value">{stats.get('calls_today', 0)}</div>

                <div class="stat-label">API Calls Today</div>

            </div>

            <div class="stat">

                <div class="stat-value">${price_min:.0f} - ${price_max:.0f}</div>

                <div class="stat-label">Price Range</div>

            </div>

            <div class="stat">

                <div class="stat-value">{keywords[:25]}...</div>

                <div class="stat-label">Search Keywords</div>

            </div>

        </div>



        <form class="search-form" method="GET" action="/ebay/gold">

            <input type="text" name="keywords" value="{keywords}" placeholder="Keywords" style="width:300px;">

            <input type="number" name="price_min" value="{price_min}" placeholder="Min $" style="width:80px;">

            <input type="number" name="price_max" value="{price_max}" placeholder="Max $" style="width:80px;">

            <input type="number" name="limit" value="{limit}" placeholder="Limit" style="width:60px;">

            <button type="submit">Search</button>

        </form>



        <table>

            <thead>

                <tr>

                    <th style="width:100px;">Image</th>

                    <th>Title</th>

                    <th style="width:100px;">Price</th>

                    <th style="width:200px;">Actions</th>

                </tr>

            </thead>

            <tbody>

                {rows_html if rows_html else '<tr><td colspan="4" style="text-align:center; padding:40px; color:#888;">No listings found. Try different keywords.</td></tr>'}

            </tbody>

        </table>

    </div>



    <button class="refresh-btn" onclick="location.reload()"> Refresh</button>



    <script>

        let autoRefresh = true;

        let interval = 30;

        let countdown = interval;

        let timerId = null;

        let seenListings = new Set();



        // Store current listings to detect new ones on refresh

        document.querySelectorAll('tbody tr').forEach(row => {{

            const link = row.querySelector('a[href*="ebay.com/itm"]');

            if (link) seenListings.add(link.href);

        }});

        localStorage.setItem('goldSeenListings', JSON.stringify([...seenListings]));



        function updateCountdown() {{

            document.getElementById('countdown').textContent = countdown + 's';

            if (countdown <= 0 && autoRefresh) {{

                location.reload();

            }}

            countdown--;

        }}



        function toggleAutoRefresh() {{

            autoRefresh = !autoRefresh;

            const btn = document.getElementById('toggleBtn');

            const status = document.getElementById('status');

            if (autoRefresh) {{

                btn.textContent = 'Pause';

                btn.className = 'toggle-btn active';

                status.textContent = 'LIVE';

                status.style.color = '#4caf50';

                countdown = interval;

                timerId = setInterval(updateCountdown, 1000);

            }} else {{

                btn.textContent = 'Resume';

                btn.className = 'toggle-btn paused';

                status.textContent = 'PAUSED';

                status.style.color = '#f44336';

                clearInterval(timerId);

            }}

        }}



        function changeInterval() {{

            interval = parseInt(document.getElementById('intervalSelect').value);

            countdown = interval;

        }}



        // Highlight new listings

        const stored = localStorage.getItem('goldSeenListings');

        if (stored) {{

            const oldListings = new Set(JSON.parse(stored));

            document.querySelectorAll('tbody tr').forEach(row => {{

                const link = row.querySelector('a[href*="ebay.com/itm"]');

                if (link && !oldListings.has(link.href)) {{

                    row.style.background = '#1a3d1a';

                    row.style.borderLeft = '4px solid #4caf50';

                    const title = row.querySelector('td:nth-child(2) a');

                    if (title) {{

                        title.innerHTML += '<span class="new-badge">NEW</span>';

                    }}

                }}

            }});

        }}



        // Start countdown

        timerId = setInterval(updateCountdown, 1000);



        // Play sound on new listing (optional - log to console)

        if (document.querySelector('.new-badge')) {{

            console.log('New gold listings detected!');

        }}

    </script>

</body>

</html>"""



    return HTMLResponse(html)





# Race routes moved to routes/ebay_race.py

# Race state now imported from routes/ebay_race.py: RACE_STATS, RACE_FEED_API, RACE_FEED_UBUYFIRST

# Configure Dashboard routes module
def _set_enabled(val):
    global ENABLED
    ENABLED = val

def _set_debug_mode(val):
    global DEBUG_MODE
    DEBUG_MODE = val

def _set_queue_mode(val):
    global QUEUE_MODE
    QUEUE_MODE = val

def _reset_stats():
    global STATS
    STATS = {
        "total_requests": 0, "api_calls": 0, "skipped": 0,
        "buy_count": 0, "pass_count": 0, "research_count": 0,
        "cache_hits": 0, "session_cost": 0.0,
        "session_start": datetime.now().isoformat(),
        "listings": {}
    }

def _clear_listing_queue():
    global LISTING_QUEUE
    LISTING_QUEUE = {}

configure_dashboard(
    get_enabled=lambda: ENABLED,
    get_debug_mode=lambda: DEBUG_MODE,
    get_queue_mode=lambda: QUEUE_MODE,
    get_stats=lambda: STATS,
    get_listing_queue=lambda: LISTING_QUEUE,
    get_race_stats=lambda: RACE_STATS,
    get_race_feed_api=lambda: RACE_FEED_API,
    get_race_feed_ubuyfirst=lambda: RACE_FEED_UBUYFIRST,
    set_enabled=_set_enabled,
    set_debug_mode=_set_debug_mode,
    set_queue_mode=_set_queue_mode,
    reset_stats=_reset_stats,
    clear_listing_queue=_clear_listing_queue,
    cache=cache,
    get_spot_prices=get_spot_prices,
    get_analytics=get_analytics,
)

# normalize_title and log_race_item moved to routes/ebay_race.py
# log_race_item is now imported from routes.ebay_race

# Race endpoints moved to routes/ebay_race.py



@app.get("/ebay/silver")

async def ebay_silver_dashboard(

    keywords: str = "sterling scrap lot",

    price_min: float = 30,

    price_max: float = 5000,

    limit: int = 50,

):

    """Silver listings dashboard - same format as gold"""

    if not EBAY_POLLER_AVAILABLE:

        return HTMLResponse("<h1>eBay Poller Not Available</h1><p>Check EBAY_APP_ID in .env</p>")



    category_ids = EBAY_SEARCH_CONFIGS.get("silver", {}).get("category_ids", [])

    listings = await search_ebay(

        keywords=keywords,

        category_ids=category_ids,

        price_min=price_min,

        price_max=price_max,

        entries_per_page=min(limit, 100),

    )



    rows_html = ""

    for listing in listings:

        item_id = listing.item_id

        title = listing.title[:80] + "..." if len(listing.title) > 80 else listing.title

        price = listing.price

        thumbnail = listing.gallery_url or listing.thumbnail_url or ""

        view_url = listing.view_url or f"https://www.ebay.com/itm/{item_id}"

        checkout_url = f"https://www.ebay.com/itm/{item_id}?nordt=true&orig_cvip=true&rt=nc"



        rows_html += f"""

        <tr>

            <td style="text-align:center;">

                <a href="{view_url}" target="_blank">

                    <img src="{thumbnail}" alt="" style="max-width:80px; max-height:80px; border-radius:4px;"

                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2280%22 height=%2280%22><rect fill=%22%23333%22 width=%22100%%22 height=%22100%%22/><text x=%2250%%22 y=%2250%%22 fill=%22%23666%22 text-anchor=%22middle%22 dy=%22.3em%22>No Image</text></svg>'">

                </a>

            </td>

            <td>

                <a href="{view_url}" target="_blank" style="color:#b0bec5; text-decoration:none;">

                    {title}

                </a>

                <div style="font-size:11px; color:#888; margin-top:4px;">

                    {listing.condition} | {listing.location} | Seller: {listing.seller_id} ({listing.seller_feedback})

                </div>

            </td>

            <td style="text-align:right; font-weight:bold; color:#b0bec5; font-size:18px;">

                ${price:.2f}

            </td>

            <td style="text-align:center;">

                <a href="{view_url}" target="_blank"

                   style="display:inline-block; padding:6px 12px; background:#2196f3; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    View

                </a>

                <a href="{checkout_url}" target="_blank"

                   style="display:inline-block; padding:6px 12px; background:#4caf50; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    Buy Now

                </a>

                <a href="/analyze?category=silver&title={listing.title[:100]}&price={price}"

                   style="display:inline-block; padding:6px 12px; background:#ff9800; color:white; text-decoration:none; border-radius:4px; margin:2px; font-size:12px;">

                    Analyze

                </a>

            </td>

        </tr>

        """



    stats = ebay_get_stats()



    html = f"""<!DOCTYPE html>

<html>

<head>

    <title>ShadowSnipe - Silver Listings</title>

    <style>

        body {{ background: #1a1a2e; color: #eee; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; }}

        .container {{ max-width: 1400px; margin: 0 auto; }}

        h1 {{ color: #b0bec5; margin-bottom: 10px; }}

        .stats {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 30px; flex-wrap: wrap; }}

        .stat {{ text-align: center; }}

        .stat-value {{ font-size: 24px; font-weight: bold; color: #b0bec5; }}

        .stat-label {{ font-size: 12px; color: #888; }}

        .search-form {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}

        .search-form input {{ padding: 8px 12px; border-radius: 4px; border: 1px solid #333; background: #0f0f23; color: #eee; }}

        .search-form button {{ padding: 8px 20px; background: #b0bec5; color: #000; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }}

        table {{ width: 100%; border-collapse: collapse; background: #16213e; border-radius: 8px; overflow: hidden; }}

        th {{ background: #0f0f23; padding: 12px; text-align: left; color: #b0bec5; }}

        td {{ padding: 12px; border-bottom: 1px solid #333; vertical-align: middle; }}

        tr:hover {{ background: #1f2940; }}

        .refresh-btn {{ position: fixed; bottom: 20px; right: 20px; padding: 15px 25px; background: #b0bec5; color: #000; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; }}

    </style>

</head>

<body>

    <div class="container">

        <h1> Silver Listings - Live from eBay API</h1>



        <div class="stats">

            <div class="stat">

                <div class="stat-value">{len(listings)}</div>

                <div class="stat-label">Listings Found</div>

            </div>

            <div class="stat">

                <div class="stat-value">{stats.get('calls_today', 0)}</div>

                <div class="stat-label">API Calls Today</div>

            </div>

            <div class="stat">

                <div class="stat-value">${price_min:.0f} - ${price_max:.0f}</div>

                <div class="stat-label">Price Range</div>

            </div>

        </div>



        <form class="search-form" method="GET" action="/ebay/silver">

            <input type="text" name="keywords" value="{keywords}" placeholder="Keywords" style="width:300px;">

            <input type="number" name="price_min" value="{price_min}" placeholder="Min $" style="width:80px;">

            <input type="number" name="price_max" value="{price_max}" placeholder="Max $" style="width:80px;">

            <input type="number" name="limit" value="{limit}" placeholder="Limit" style="width:60px;">

            <button type="submit">Search</button>

        </form>



        <table>

            <thead>

                <tr>

                    <th style="width:100px;">Image</th>

                    <th>Title</th>

                    <th style="width:100px;">Price</th>

                    <th style="width:200px;">Actions</th>

                </tr>

            </thead>

            <tbody>

                {rows_html if rows_html else '<tr><td colspan="4" style="text-align:center; padding:40px; color:#888;">No listings found.</td></tr>'}

            </tbody>

        </table>

    </div>



    <button class="refresh-btn" onclick="location.reload()"> Refresh</button>

</body>

</html>"""



    return HTMLResponse(html)





# ============================================================

# WEBSOCKET FOR REAL-TIME DASHBOARD

# ============================================================



class ConnectionManager:

    """Manage WebSocket connections for real-time updates"""

    

    def __init__(self):

        self.active_connections: List[WebSocket] = []

    

    async def connect(self, websocket: WebSocket):

        await websocket.accept()

        self.active_connections.append(websocket)

        logger.info(f"[WS] Client connected. Total: {len(self.active_connections)}")

    

    def disconnect(self, websocket: WebSocket):

        if websocket in self.active_connections:

            self.active_connections.remove(websocket)

        logger.info(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    

    async def broadcast(self, message: dict):

        """Send message to all connected clients"""

        if not self.active_connections:

            return

        

        message_json = json.dumps(message)

        disconnected = []

        

        for connection in self.active_connections:

            try:

                await connection.send_text(message_json)

            except Exception as e:

                logger.debug(f"[WS] Send error: {e}")

                disconnected.append(connection)

        

        # Clean up disconnected

        for conn in disconnected:

            self.disconnect(conn)



# Global connection manager

ws_manager = ConnectionManager()





@app.websocket("/ws")

async def websocket_endpoint(websocket: WebSocket):

    """WebSocket endpoint for real-time listing updates"""

    await ws_manager.connect(websocket)

    try:

        while True:

            # Keep connection alive, receive any client messages

            data = await websocket.receive_text()

            logger.debug(f"[WS] Received: {data}")

    except WebSocketDisconnect:

        ws_manager.disconnect(websocket)

    except Exception as e:

        logger.debug(f"[WS] Error: {e}")

        ws_manager.disconnect(websocket)





@app.get("/live")

async def live_dashboard():

    """Serve the live dashboard HTML with TTS for BUY alerts"""

    # Always serve embedded dashboard with TTS (ignore external dashboard.html)

    return HTMLResponse(content='''<!DOCTYPE html>

<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>ShadowSnipe Live</title>

    <style>

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {

            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);

            color: #fff;

            min-height: 100vh;

            padding: 20px;

        }

        .header {

            display: flex;

            justify-content: space-between;

            align-items: center;

            margin-bottom: 20px;

            padding-bottom: 15px;

            border-bottom: 2px solid #00ff88;

        }

        .header h1 {

            color: #00ff88;

            font-size: 28px;

        }

        .header h1 span { color: #fff; }

        .status-bar {

            display: flex;

            gap: 20px;

            align-items: center;

        }

        .status-item {

            background: rgba(255,255,255,0.1);

            padding: 8px 15px;

            border-radius: 20px;

            font-size: 14px;

        }

        .status-item.connected { background: rgba(40, 167, 69, 0.3); color: #28a745; }

        .status-item.disconnected { background: rgba(220, 53, 69, 0.3); color: #dc3545; }

        .controls {

            display: flex;

            gap: 10px;

            margin-bottom: 20px;

        }

        .btn {

            padding: 10px 20px;

            border: none;

            border-radius: 8px;

            cursor: pointer;

            font-size: 14px;

            font-weight: bold;

            transition: all 0.2s;

        }

        .btn-primary { background: #00ff88; color: #000; }

        .btn-primary:hover { background: #00cc6a; }

        .btn-danger { background: #dc3545; color: #fff; }

        .btn-warning { background: #ffc107; color: #000; }

        .btn-secondary { background: #6c757d; color: #fff; }

        

        .tts-toggle {

            display: flex;

            align-items: center;

            gap: 10px;

            background: rgba(255,255,255,0.1);

            padding: 10px 15px;

            border-radius: 8px;

        }

        .tts-toggle input[type="checkbox"] {

            width: 20px;

            height: 20px;

            cursor: pointer;

        }

        

        .listings-container {

            display: grid;

            gap: 15px;

        }

        .listing-card {

            background: rgba(255,255,255,0.05);

            border-radius: 12px;

            padding: 20px;

            border-left: 5px solid #6c757d;

            transition: all 0.3s;

        }

        .listing-card.buy {

            border-left-color: #28a745;

            background: rgba(40, 167, 69, 0.1);

            animation: pulse-green 2s ease-in-out;

        }

        .listing-card.pass {

            border-left-color: #dc3545;

            background: rgba(220, 53, 69, 0.05);

        }

        .listing-card.research {

            border-left-color: #ffc107;

            background: rgba(255, 193, 7, 0.1);

        }

        @keyframes pulse-green {

            0%, 100% { box-shadow: 0 0 0 0 rgba(40, 167, 69, 0); }

            50% { box-shadow: 0 0 20px 10px rgba(40, 167, 69, 0.3); }

        }

        .listing-header {

            display: flex;

            justify-content: space-between;

            align-items: flex-start;

            margin-bottom: 10px;

        }

        .listing-title {

            font-size: 16px;

            font-weight: 500;

            flex: 1;

            margin-right: 15px;

        }

        .listing-rec {

            font-size: 18px;

            font-weight: bold;

            padding: 5px 15px;

            border-radius: 20px;

        }

        .listing-rec.buy { background: #28a745; color: #fff; }

        .listing-rec.pass { background: #dc3545; color: #fff; }

        .listing-rec.research { background: #ffc107; color: #000; }

        .listing-details {

            display: grid;

            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));

            gap: 10px;

            margin-top: 15px;

        }

        .detail-item {

            background: rgba(255,255,255,0.05);

            padding: 10px;

            border-radius: 8px;

            text-align: center;

        }

        .detail-label { font-size: 11px; color: #888; text-transform: uppercase; }

        .detail-value { font-size: 16px; font-weight: bold; margin-top: 5px; }

        .listing-time {

            font-size: 12px;

            color: #666;

            margin-top: 10px;

        }

        .empty-state {

            text-align: center;

            padding: 60px 20px;

            color: #666;

        }

        .empty-state h2 { color: #00ff88; margin-bottom: 10px; }

        

        #tts-status {

            position: fixed;

            bottom: 20px;

            right: 20px;

            background: rgba(0,0,0,0.8);

            padding: 10px 20px;

            border-radius: 8px;

            font-size: 14px;

            display: none;

        }

    </style>

</head>

<body>

    <div class="header">

        <h1> <span>ShadowSnipe</span> Live</h1>

        <div class="status-bar">

            <div id="ws-status" class="status-item disconnected">● Disconnected</div>

            <div id="listing-count" class="status-item">0 listings</div>

        </div>

    </div>

    

    <div class="controls">

        <button class="btn btn-primary" onclick="clearListings()">️ Clear</button>

        <button class="btn btn-secondary" onclick="testTTS()"> Test Sound</button>

        <div class="tts-toggle">

            <input type="checkbox" id="tts-enabled" checked>

            <label for="tts-enabled"> Voice Alerts for BUY</label>

        </div>

        <div class="tts-toggle">

            <input type="checkbox" id="sound-enabled" checked>

            <label for="sound-enabled"> Sound for BUY</label>

        </div>

    </div>

    

    <div id="listings" class="listings-container">

        <div class="empty-state">

            <h2>Waiting for listings...</h2>

            <p>Listings will appear here in real-time as they're analyzed</p>

        </div>

    </div>

    

    <div id="tts-status"></div>

    

    <script>

        let ws = null;

        let listingCount = 0;

        let reconnectAttempts = 0;

        const maxReconnectAttempts = 10;

        

        // Initialize Speech Synthesis

        let voices = [];

        if ('speechSynthesis' in window) {

            voices = window.speechSynthesis.getVoices();

            window.speechSynthesis.onvoiceschanged = () => {

                voices = window.speechSynthesis.getVoices();

            };

        }

        

        function speak(text) {

            if (!document.getElementById('tts-enabled').checked) return;

            if (!('speechSynthesis' in window)) {

                console.log('TTS not supported');

                return;

            }

            

            window.speechSynthesis.cancel();

            

            const msg = new SpeechSynthesisUtterance();

            msg.text = text;

            msg.rate = 1.1;

            msg.pitch = 1.0;

            msg.volume = 1.0;

            

            // Try to use an English voice

            if (voices.length > 0) {

                const englishVoice = voices.find(v => v.lang.startsWith('en'));

                if (englishVoice) msg.voice = englishVoice;

            }

            

            showTTSStatus('Speaking: ' + text.substring(0, 50) + '...');

            window.speechSynthesis.speak(msg);

        }

        

        function playSound() {

            if (!document.getElementById('sound-enabled').checked) return;

            

            // Create a simple beep using Web Audio API

            try {

                const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

                const oscillator = audioCtx.createOscillator();

                const gainNode = audioCtx.createGain();

                

                oscillator.connect(gainNode);

                gainNode.connect(audioCtx.destination);

                

                oscillator.frequency.value = 800;

                oscillator.type = 'sine';

                gainNode.gain.setValueAtTime(0.3, audioCtx.currentTime);

                gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.5);

                

                oscillator.start(audioCtx.currentTime);

                oscillator.stop(audioCtx.currentTime + 0.5);

            } catch (e) {

                console.log('Audio error:', e);

            }

        }

        

        function testTTS() {

            playSound();

            speak('Buy alert! This is a test of the voice alert system.');

        }

        

        function showTTSStatus(text) {

            const status = document.getElementById('tts-status');

            status.textContent = text;

            status.style.display = 'block';

            setTimeout(() => { status.style.display = 'none'; }, 3000);

        }

        

        function connect() {

            const wsUrl = 'ws://' + window.location.host + '/ws';

            ws = new WebSocket(wsUrl);

            

            ws.onopen = () => {

                console.log('WebSocket connected');

                document.getElementById('ws-status').className = 'status-item connected';

                document.getElementById('ws-status').textContent = '● Connected';

                reconnectAttempts = 0;

            };

            

            ws.onclose = () => {

                console.log('WebSocket disconnected');

                document.getElementById('ws-status').className = 'status-item disconnected';

                document.getElementById('ws-status').textContent = '● Disconnected';

                

                // Attempt to reconnect

                if (reconnectAttempts < maxReconnectAttempts) {

                    reconnectAttempts++;

                    setTimeout(connect, 2000 * reconnectAttempts);

                }

            };

            

            ws.onerror = (error) => {

                console.error('WebSocket error:', error);

            };

            

            ws.onmessage = (event) => {

                try {

                    const data = JSON.parse(event.data);

                    if (data.type === 'new_listing') {

                        addListing(data);

                    }

                } catch (e) {

                    console.error('Parse error:', e);

                }

            };

        }

        

        function addListing(data) {

            console.log('[DASHBOARD] Received data:', JSON.stringify(data, null, 2));

            

            const container = document.getElementById('listings');

            

            // Remove empty state if present

            const emptyState = container.querySelector('.empty-state');

            if (emptyState) emptyState.remove();

            

            const listing = data.listing || {};

            const analysis = data.analysis || {};

            

            console.log('[DASHBOARD] listing object:', listing);

            console.log('[DASHBOARD] analysis object:', analysis);

            

            const title = (listing.title || analysis.title || 'Unknown').replace(/[+]/g, ' ');

            const rec = (analysis.Recommendation || analysis.recommendation || 'UNKNOWN').toUpperCase();

            const recClass = rec.toLowerCase();

            const price = listing.price || analysis.listingPrice || '--';

            const profit = analysis.Profit || analysis.profit || analysis.Margin || analysis.margin || '--';

            const category = analysis.category || listing.category || '--';

            const confidence = analysis.confidence || '--';

            const weight = analysis.weight || analysis.goldweight || analysis.silverweight || 'NA';

            const melt = analysis.meltvalue || analysis.melt || analysis.MeltValue || '--';

            const weightSource = analysis.weightSource || 'unknown';

            const itemId = listing.item_id || listing.id || Date.now();

            const url = listing.url || '';

            

            console.log('[DASHBOARD] Parsed values:', {title, price, rec, profit, category, weight, melt});

            

            // Store listing data for purchase logging

            const listingData = JSON.stringify({

                listing: { title, price, category, item_id: itemId, url },

                analysis: { 

                    recommendation: rec, profit, confidence, weight, 

                    weightSource, melt, karat: analysis.karat || '',

                    itemtype: analysis.itemtype || '', maxBuy: analysis.maxBuy || '',

                    reasoning: analysis.reasoning || ''

                }

            });

            

            // Create card

            const card = document.createElement('div');

            card.className = 'listing-card ' + recClass;

            card.innerHTML = `

                <div class="listing-header">

                    <div class="listing-title">${escapeHtml(title)}</div>

                    <div class="listing-rec ${recClass}">${rec}</div>

                </div>

                <div class="listing-details">

                    <div class="detail-item">

                        <div class="detail-label">Price</div>

                        <div class="detail-value">$${price}</div>

                    </div>

                    <div class="detail-item">

                        <div class="detail-label">Profit</div>

                        <div class="detail-value" style="color: ${parseFloat(profit) >= 0 ? '#28a745' : '#dc3545'}">$${profit}</div>

                    </div>

                    <div class="detail-item">

                        <div class="detail-label">Weight</div>

                        <div class="detail-value">${weight}</div>

                    </div>

                    <div class="detail-item">

                        <div class="detail-label">Melt</div>

                        <div class="detail-value">$${melt}</div>

                    </div>

                    <div class="detail-item">

                        <div class="detail-label">Category</div>

                        <div class="detail-value">${category}</div>

                    </div>

                    <div class="detail-item">

                        <div class="detail-label">Confidence</div>

                        <div class="detail-value">${confidence}</div>

                    </div>

                </div>

                <div class="listing-actions" style="margin-top:12px;display:flex;gap:10px;align-items:center;">

                    <button class="btn-bought" onclick='logPurchase(${listingData.replace(/'/g, "&#39;")}, this)' 

                            style="background:#22c55e;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:600;">

                        I Bought This

                    </button>

                    ${url ? `<a href="${url}" target="_blank" style="color:#6366f1;font-size:12px;">View on eBay</a>` : ''}

                </div>

                <div class="listing-time">${new Date().toLocaleTimeString()}</div>

            `;

            

            // Add to top of container

            container.insertBefore(card, container.firstChild);

            

            // Update count

            listingCount++;

            document.getElementById('listing-count').textContent = listingCount + ' listings';

            

            // TTS and sound for BUY alerts

            if (rec === 'BUY') {

                playSound();

                // Clean title for speech - title already has + replaced with spaces

                const cleanTitle = title.replace(/[^a-zA-Z0-9\\s]/g, ' ').substring(0, 80);

                speak('Buy alert! ' + cleanTitle);

            }

            

            // Limit to 50 listings

            while (container.children.length > 50) {

                container.removeChild(container.lastChild);

            }

        }

        

        function clearListings() {

            const container = document.getElementById('listings');

            container.innerHTML = `

                <div class="empty-state">

                    <h2>Waiting for listings...</h2>

                    <p>Listings will appear here in real-time as they're analyzed</p>

                </div>

            `;

            listingCount = 0;

            document.getElementById('listing-count').textContent = '0 listings';

        }

        

        function escapeHtml(text) {

            const div = document.createElement('div');

            div.textContent = text;

            return div.innerHTML;

        }

        

        async function logPurchase(data, btn) {

            try {

                btn.disabled = true;

                btn.textContent = 'Logging...';

                

                const response = await fetch('/api/log-purchase', {

                    method: 'POST',

                    headers: { 'Content-Type': 'application/json' },

                    body: JSON.stringify(data)

                });

                

                const result = await response.json();

                

                if (result.status === 'logged') {

                    btn.textContent = 'Logged!';

                    btn.style.background = '#6366f1';

                    showTTSStatus('Purchase logged successfully!');

                } else {

                    btn.textContent = 'Error';

                    btn.style.background = '#dc3545';

                }

            } catch (e) {

                console.error('Log purchase error:', e);

                btn.textContent = 'Error';

                btn.style.background = '#dc3545';

            }

        }

        

        // Connect on page load

        connect();

    </script>

</body>

</html>''')





async def broadcast_new_listing(listing: dict, analysis: dict = None):

    """Broadcast a new listing to all connected dashboard clients"""

    message = {

        "type": "new_listing",

        "timestamp": datetime.now().isoformat(),

        "listing": listing,

        "analysis": analysis,

    }

    logger.info(f"[WS] Broadcasting: title='{listing.get('title', 'MISSING')[:50]}', price={listing.get('price')}, rec={analysis.get('Recommendation') if analysis else 'N/A'}")

    await ws_manager.broadcast(message)





async def analyze_api_listing(listing) -> dict:
    """
    Analyze a listing from the direct eBay API.
    Uses unified adapter to normalize data, then calls /match_mydata.
    Returns the analysis result dict.
    """
    try:
        # Import adapter (handles all normalization: images, description, category detection)
        from utils.listing_adapter import normalize_api_listing, validate_listing

        # Normalize API listing to standard format (fetches images, description, specifics)
        std_listing = await normalize_api_listing(listing, fetch_details=True)

        # Validate the normalized listing
        issues = validate_listing(std_listing)
        if issues:
            logger.warning(f"[API] Validation issues: {issues}")

        # Convert to pipeline dict format
        listing_data = std_listing.to_pipeline_dict()

        logger.info(f"[API] Normalized: {std_listing.title[:40]}... | cat={std_listing.category} | {len(std_listing.images)} images")

        # Make HTTP request to our own endpoint
        # Try shared client first, fall back to inline client if needed
        response = None
        try:
            if hasattr(app, 'state') and hasattr(app.state, 'http_client'):
                response = await app.state.http_client.post(
                    "http://127.0.0.1:8000/match_mydata",
                    json=listing_data,
                    timeout=60.0  # Increased timeout for AI analysis
                )
        except Exception as client_err:
            logger.warning(f"[API ANALYSIS] Shared client failed: {client_err}, using inline client")
            response = None

        # Fallback to inline client if shared client failed or unavailable
        if response is None:
            logger.info("[API ANALYSIS] Using inline httpx client")
            async with httpx.AsyncClient(timeout=60.0) as inline_client:
                response = await inline_client.post(
                    "http://127.0.0.1:8000/match_mydata",
                    json=listing_data
                )

        if response.status_code == 200:
            # Parse JSON response with full analysis details
            try:
                result = response.json()
                result['source'] = 'ebay_api'
                result['analyzed'] = True
                logger.info(f"[API ANALYSIS] Success: {listing.title[:40]}... -> {result.get('Recommendation', 'UNKNOWN')}")
                return result
            except Exception as json_err:
                # Fallback to HTML parsing if JSON fails
                logger.warning(f"[API ANALYSIS] JSON parse failed: {json_err}")
                html_content = response.text
                rec = "UNKNOWN"
                if '>BUY<' in html_content or 'status">BUY' in html_content:
                    rec = "BUY"
                elif '>RESEARCH<' in html_content or 'status">RESEARCH' in html_content:
                    rec = "RESEARCH"
                elif '>PASS<' in html_content or 'status">PASS' in html_content:
                    rec = "PASS"
                return {
                    "Recommendation": rec,
                    "Title": listing.title,
                    "Price": listing.price,
                    "source": "ebay_api",
                    "analyzed": True,
                }
        else:
            logger.warning(f"[API ANALYSIS] HTTP {response.status_code} for {listing.title[:40]}")
            return {"Recommendation": "ERROR", "error": f"HTTP {response.status_code}"}

    except Exception as e:
        logger.error(f"[API ANALYSIS] Error analyzing listing: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"Recommendation": "ERROR", "error": str(e)}


async def race_callback(listing):
    """Callback for background poller - logs items to race comparison and optionally analyzes"""
    global API_ANALYSIS_ENABLED

    try:
        cat = listing.category_name if hasattr(listing, 'category_name') else "unknown"

        # Always log to race comparison system
        log_race_item(
            item_id=listing.item_id,
            source="api",
            title=listing.title,
            price=listing.price,
            category=cat,
        )
        logger.info(f"[RACE] API found: {listing.title[:40]}... @ ${listing.price:.2f} [{cat}]")

        # Log to source comparison system for latency tracking
        posted_time_str = ""
        if hasattr(listing, 'start_time') and listing.start_time:
            try:
                posted_time_str = listing.start_time.isoformat() if hasattr(listing.start_time, 'isoformat') else str(listing.start_time)
            except:
                pass
        log_listing_received(
            item_id=listing.item_id,
            source="direct",
            posted_time=posted_time_str,
            title=listing.title,
            price=listing.price,
            category=cat,
        )

        # If API analysis is enabled, analyze and broadcast
        if API_ANALYSIS_ENABLED:
            logger.info(f"[API] Analyzing: {listing.title[:50]}...")
            analysis = await analyze_api_listing(listing)

            # Broadcast to WebSocket clients
            listing_dict = listing.to_dict() if hasattr(listing, 'to_dict') else {
                "title": listing.title,
                "price": listing.price,
                "ItemId": listing.item_id,
            }
            listing_dict['source'] = 'ebay_api'

            await broadcast_new_listing(listing_dict, analysis)

            rec = analysis.get("Recommendation", "?")
            logger.info(f"[API] Result: {rec} - {listing.title[:40]}... @ ${listing.price:.2f}")

            # Send Discord alert for BUY from API
            if rec == "BUY" and DISCORD_WEBHOOK_URL:
                try:
                    # Build direct eBay link from item_id
                    direct_ebay_url = f"https://www.ebay.com/itm/{listing.item_id}"

                    # Get thumbnail URL
                    thumb_url = listing.thumbnail_url if hasattr(listing, 'thumbnail_url') and listing.thumbnail_url else None

                    # Get analysis details for alert
                    profit_val = analysis.get('Profit', 0)
                    if isinstance(profit_val, str):
                        profit_val = float(profit_val.replace('$', '').replace('+', '').replace(',', '') or 0)

                    # Build seller info from listing
                    api_seller_info = {
                        'seller_id': listing.seller_id if hasattr(listing, 'seller_id') else '',
                        'feedback_score': listing.seller_feedback if hasattr(listing, 'seller_feedback') else '',
                        'feedback_percent': '',
                        'seller_type': listing.seller_type if hasattr(listing, 'seller_type') else '',
                    }
                    api_listing_info = {
                        'item_id': listing.item_id,
                        'condition': listing.condition if hasattr(listing, 'condition') else '',
                        'posted_time': listing.listing_date if hasattr(listing, 'listing_date') else '',
                    }

                    await send_discord_alert(
                        title=f"🔵 API: {listing.title[:70]}",
                        price=listing.price,
                        recommendation=rec,
                        category=cat,
                        profit=profit_val,
                        reasoning=analysis.get('reasoning', f"Source: Direct eBay API"),
                        ebay_url=direct_ebay_url,
                        image_url=thumb_url,
                        confidence=analysis.get('confidence', ''),
                        extra_data={
                            'karat': analysis.get('karat'),
                            'weight': analysis.get('weight'),
                            'melt': analysis.get('meltvalue'),
                        },
                        seller_info=api_seller_info,
                        listing_info=api_listing_info
                    )
                    logger.info(f"[API] Discord alert sent for {rec} - URL: {direct_ebay_url}")
                except Exception as e:
                    logger.warning(f"[API] Discord alert failed: {e}")
                    import traceback
                    logger.warning(f"[API] Discord traceback: {traceback.format_exc()}")

    except Exception as e:
        logger.warning(f"[RACE] Callback error: {e}")
        import traceback
        logger.warning(f"[RACE] Traceback: {traceback.format_exc()}")


@app.post("/ebay/poll/start")
async def ebay_poll_start(categories: str = "gold", race_mode: bool = False):
    """
    Start background polling for categories

    Example: /ebay/poll/start?categories=gold,silver&race_mode=true
    """
    if not EBAY_POLLER_AVAILABLE:
        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    cat_list = [c.strip() for c in categories.split(",")]
    valid_cats = [c for c in cat_list if c in EBAY_SEARCH_CONFIGS]

    if not valid_cats:
        return JSONResponse({
            "error": f"No valid categories. Available: {list(EBAY_SEARCH_CONFIGS.keys())}"
        }, status_code=400)

    # For race mode, stop existing polling first so we can attach the callback
    if race_mode:
        global RACE_STATS, RACE_LOG, RACE_FEED_UBUYFIRST, RACE_FEED_API
        # Stop existing polls to attach callback to fresh tasks
        await ebay_stop_polling(valid_cats)
        await asyncio.sleep(0.5)  # Brief pause for cleanup
        ebay_clear_seen()
        # Clear the race tracking data
        RACE_STATS = {"ubuyfirst_wins": 0, "api_wins": 0, "ties": 0, "total": 0}
        RACE_LOG.clear()
        RACE_FEED_UBUYFIRST.clear()
        RACE_FEED_API.clear()
        logger.info("[RACE] Cleared race data for fresh start")

    # Start polling in background - with race callback if race_mode enabled
    callback = race_callback if race_mode else None
    asyncio.create_task(ebay_start_polling(valid_cats, callback=callback))

    return JSONResponse({
        "status": "ok",
        "message": f"Started polling for: {valid_cats}" + (" (RACE MODE)" if race_mode else ""),
        "race_mode": race_mode,
        "available_categories": list(EBAY_SEARCH_CONFIGS.keys()),
    })





@app.post("/ebay/poll/stop")

async def ebay_poll_stop(categories: str = None):

    """Stop background polling"""

    if not EBAY_POLLER_AVAILABLE:

        return JSONResponse({"error": "eBay poller not available"}, status_code=503)

    

    cat_list = None

    if categories:

        cat_list = [c.strip() for c in categories.split(",")]

    

    await ebay_stop_polling(cat_list)

    

    return JSONResponse({

        "status": "ok",

        "message": f"Stopped polling for: {cat_list or 'all'}",

    })





@app.post("/ebay/analysis/start")
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


@app.post("/ebay/analysis/stop")
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


@app.get("/ebay/analysis/status")
async def ebay_analysis_status():
    """Check if API analysis mode is enabled"""
    return JSONResponse({
        "api_analysis_enabled": API_ANALYSIS_ENABLED,
        "description": "When enabled, API listings are fully analyzed and broadcast to dashboard",
    })


# ============================================================

# KEEPA AMAZON TRACKER V2

# Efficient tracking using Deals API + Webhooks

# ============================================================

try:

    from keepa_tracker_v2 import (

        KeepaClientV2,

        start_deals_monitor,

        stop_monitor,

        get_client,

        handle_keepa_webhook,

        PriceDrop,

        send_discord_alert as keepa_send_discord_alert,

    )

    KEEPA_AVAILABLE = True

    print("[KEEPA] Keepa tracker V2 loaded (Deals API + Webhooks)")

except ImportError as e:

    KEEPA_AVAILABLE = False

    print(f"[KEEPA] Keepa tracker not available: {e}")



# Global client instance
_keepa_client: Optional[KeepaClientV2] = None

def _get_keepa_client():
    return _keepa_client

def _set_keepa_client(client):
    global _keepa_client
    _keepa_client = client

# Configure Keepa routes module
if KEEPA_AVAILABLE:
    configure_keepa(
        KEEPA_AVAILABLE=KEEPA_AVAILABLE,
        get_keepa_client=_get_keepa_client,
        set_keepa_client=_set_keepa_client,
        KeepaClientV2=KeepaClientV2,
        get_client=get_client,
        start_deals_monitor=start_deals_monitor,
        stop_monitor=stop_monitor,
        handle_keepa_webhook=handle_keepa_webhook,
        PriceDrop=PriceDrop,
        keepa_send_discord_alert=keepa_send_discord_alert,
    )































# ============================================================
# CONFIGURE ANALYSIS MODULE
# ============================================================
# Uses lambda for IN_FLIGHT_LOCK since it's created in startup event
configure_analysis(
    # API Clients
    client=client,
    openai_client=openai_client,
    # State & Config
    STATS=STATS,
    ENABLED_ref=lambda: ENABLED,
    QUEUE_MODE_ref=lambda: QUEUE_MODE,
    LISTING_QUEUE=LISTING_QUEUE,
    cache=cache,
    IN_FLIGHT=IN_FLIGHT,
    IN_FLIGHT_LOCK_ref=lambda: IN_FLIGHT_LOCK,  # Lambda - lock created in startup
    IN_FLIGHT_RESULTS=IN_FLIGHT_RESULTS,
    # Model config
    MODEL_FAST=MODEL_FAST,
    TIER1_MODEL_GOLD_SILVER=TIER1_MODEL_GOLD_SILVER,
    TIER1_MODEL_DEFAULT=TIER1_MODEL_DEFAULT,
    TIER2_ENABLED=TIER2_ENABLED,
    TIER2_PROVIDER=TIER2_PROVIDER,
    OPENAI_TIER2_MODEL=OPENAI_TIER2_MODEL,
    PARALLEL_MODE=PARALLEL_MODE,
    SKIP_TIER2_FOR_HOT=SKIP_TIER2_FOR_HOT,
    # Cost constants
    COST_PER_CALL_HAIKU=COST_PER_CALL_HAIKU,
    COST_PER_CALL_GPT4O=COST_PER_CALL_GPT4O,
    COST_PER_CALL_GPT4O_MINI=COST_PER_CALL_GPT4O_MINI,
    # Image config
    IMAGES=IMAGES,
    # Feature flags
    FAST_EXTRACT_AVAILABLE=FAST_EXTRACT_AVAILABLE,
    EBAY_POLLER_AVAILABLE=EBAY_POLLER_AVAILABLE,
    # Functions
    check_seller_spam=check_seller_spam,
    check_recently_evaluated=check_recently_evaluated,
    mark_as_evaluated=mark_as_evaluated,
    check_price_correction=check_price_correction,
    analyze_new_seller=analyze_new_seller,
    log_race_item=log_race_item,
    log_listing_received=log_listing_received,
    detect_category=detect_category,
    lookup_user_price=lookup_user_price,
    check_instant_pass=check_instant_pass,
    get_pricecharting_context=get_pricecharting_context,
    get_agent=get_agent,
    get_agent_prompt=get_agent_prompt,
    fast_extract_gold=fast_extract_gold,
    fast_extract_silver=fast_extract_silver,
    get_spot_prices=get_spot_prices,
    process_image_list=process_image_list,
    get_category_prompt=get_category_prompt,
    format_listing_data=format_listing_data,
    validate_and_fix_margin=validate_and_fix_margin,
    validate_tcg_lego_result=validate_tcg_lego_result,
    validate_videogame_result=validate_videogame_result,
    render_result_html=render_result_html,
    sanitize_json_response=sanitize_json_response,
    tier2_reanalyze=tier2_reanalyze,
    tier2_reanalyze_openai=tier2_reanalyze_openai,
    background_sonnet_verify=background_sonnet_verify,
    send_discord_alert=send_discord_alert,
    lookup_ebay_item=lookup_ebay_item,
    lookup_ebay_item_by_seller=lookup_ebay_item_by_seller,
    get_ebay_search_url=get_ebay_search_url,
    save_listing=save_listing,
    update_pattern_outcome=update_pattern_outcome,
    broadcast_new_listing=broadcast_new_listing,
    trim_listings=_trim_listings,
    check_openai_budget=check_openai_budget,
    record_openai_cost=record_openai_cost,
    log_incoming_listing=log_incoming_listing,
    render_queued_html=_render_queued_html,
)



# ============================================================

# RUN SERVER

# ============================================================

if __name__ == "__main__":

    print("\n" + "=" * 60)

    print("Claude Proxy Server v3 - Optimized")

    print("=" * 60)

    print(f"Dashboard: http://{HOST}:{PORT}")

    print(f"ShadowSnipe Live: http://{HOST}:{PORT}/live")

    print(f"Optimizations: Async images, Smart cache, Connection pooling")

    if EBAY_POLLER_AVAILABLE:

        print(f"eBay Direct API: Available - /ebay/stats, /ebay/search")

    if KEEPA_AVAILABLE:

        print(f"Keepa Amazon: Available - /keepa/stats, /keepa/lookup")

    print("=" * 60 + "\n")

    

    uvicorn.run(

        "main:app",

        host=HOST,

        port=PORT,

        reload=False,

        workers=1  # Can increase for more concurrency

    )

