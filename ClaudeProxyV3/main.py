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

# Add project root to path so services/, pipeline/, routes/ can be found
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

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
from utils.source_comparison import log_listing_received, get_comparison_stats, get_race_log, reset_stats as reset_source_stats, log_api_buy_win, get_api_buy_wins_stats

# NEW: Centralized state management (Phase 1.1 refactoring)
from services.app_state import AppState, get_app_state_from_request
from services.error_handler import setup_error_handlers
from services import item_tracking  # Track items for sold status monitoring

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
from routes.race import (
    router as race_router,
    configure_race,
    race_log_ubf_item,
    RACE_DATA,
)
from routes.costume import (
    router as costume_router,
    configure_costume,
    COSTUME_OUTCOMES,
)
from routes.analytics import (
    router as analytics_router,
    configure_analytics,
)
from routes.data import router as data_router, configure_data
from routes.debug import router as debug_router, configure_debug
from routes.openai_compat import router as openai_compat_router, configure_openai_compat
from routes.queue import router as queue_router, configure_queue
from routes.websocket import (
    router as websocket_router,
    ws_manager,
    broadcast_new_listing,
    get_ws_manager,
)

# HTML renderers (extracted from main.py)
from templates import (
    render_disabled_html as _render_disabled_html,
    render_queued_html as _render_queued_html,
    render_error_html as _render_error_html,
    format_confidence,
    render_result_html,
    # Page templates
    render_purchases_page,
    render_training_dashboard,
    render_patterns_page,
    render_analytics_page,
)

# Budget tracking (extracted from main.py)
from utils.budget import (
    check_openai_budget,
    record_openai_cost,
    get_openai_budget_status,
    set_hourly_budget,
    OPENAI_HOURLY_BUDGET,
)

# eBay lookup service (extracted from main.py)
from services.ebay_lookup import (
    lookup_ebay_item,
    lookup_ebay_item_by_seller,
    get_ebay_search_url,
    configure_ebay_lookup,
)

# PriceCharting validation (extracted from main.py)
from pipeline.pricecharting_validation import (
    get_pricecharting_context,
    normalize_tcg_lego_keys,
    validate_tcg_lego_result,
    validate_videogame_result,
    configure_pricecharting_validation,
)

# Instant pass logic (extracted from main.py)
from pipeline.instant_pass import (
    check_instant_pass,
    extract_weight_from_title,
    extract_karat_from_title,
    configure_instant_pass,
    extract_with_ollama,
)

# Ollama local LLM for fast extraction (optional)
try:
    from ollama_extract import check_ollama_available, is_available as ollama_is_available
    OLLAMA_AVAILABLE = True
    print("[OLLAMA] Module loaded - will check availability on startup")
except ImportError:
    OLLAMA_AVAILABLE = False
    ollama_is_available = lambda: False
    print("[OLLAMA] Module not available")

# Import path configs from centralized config
from config import TRAINING_LOG_PATH, PURCHASE_LOG_PATH, API_ANALYSIS_ENABLED, PRICE_OVERRIDES_PATH
from services.price_overrides import PRICE_OVERRIDES, load_price_overrides, check_price_override

# Pipeline orchestrator (main analysis logic)
from pipeline.orchestrator import configure_orchestrator

# NOTE: Regex patterns for weight/karat extraction moved to pipeline/instant_pass.py


# Import our optimized modules

from config import (

    HOST, PORT, CLAUDE_API_KEY, MODEL_FAST, MODEL_FULL,
    COST_PER_CALL_HAIKU, COST_PER_CALL_SONNET, CACHE, SPOT_PRICES, DB_PATH,
    EBAY_APP_ID, EBAY_CERT_ID, DISCORD_WEBHOOK_URL, TIER2_ENABLED, TIER2_MIN_MARGIN,
    IMAGES, INSTANT_PASS_KEYWORDS, INSTANT_PASS_PRICE_THRESHOLDS,
    UBF_TITLE_FILTERS, UBF_LOCATION_FILTERS, UBF_FEEDBACK_RULES, UBF_STORE_TITLE_FILTERS,
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
    fast_extract_gold = None
    fast_extract_silver = None
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

# Keepa is disabled - using dedicated KeepaTracker project on port 8001
KEEPA_AVAILABLE = False

# Configure PriceCharting validation module
configure_pricecharting_validation(
    pc_lookup=pc_lookup if PRICECHARTING_AVAILABLE else None,
    bricklink_lookup=bricklink_lookup if BRICKLINK_AVAILABLE else None,
    pricecharting_available=PRICECHARTING_AVAILABLE,
    bricklink_available=BRICKLINK_AVAILABLE,
    category_thresholds=CATEGORY_THRESHOLDS,
)

# Configure instant pass module
configure_instant_pass(
    instant_pass_keywords=INSTANT_PASS_KEYWORDS,
    get_spot_prices=get_spot_prices,
)

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
    logger.info("=" * 60)
    logger.info("Claude Proxy v3 - Optimized Starting...")
    logger.info("=" * 60)

    # Store app_state in app.state for access by routes (Phase 1.1 refactoring)
    app_instance.state.app_state = app_state
    logger.info("[INIT] AppState attached to app.state")

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

    # Start AppState memory cleanup (Phase 3 improvement)
    app_state.start_cleanup_task()
    logger.info(f"[INIT] AppState cleanup task started (TTL={app_state.IN_FLIGHT_TTL}s)")

    # Start item tracking for sold status monitoring
    if EBAY_POLLER_AVAILABLE and browse_api_available():
        item_tracking.configure_ebay(get_token_func=get_oauth_token)
        item_tracking.start_polling(interval_seconds=300)  # Check every 5 minutes
        logger.info("[TRACKING] Item tracking started - polling for sold items every 5 minutes")
    else:
        logger.info("[TRACKING] Item tracking database ready (polling disabled - no eBay API)")

    # Initialize Ollama local LLM for fast extraction
    if OLLAMA_AVAILABLE:
        try:
            await check_ollama_available()
            if ollama_is_available():
                logger.info("[OLLAMA] Local LLM ready for fast extraction (~200-400ms)")
            else:
                logger.info("[OLLAMA] Not running - install from ollama.com and run 'ollama pull llama3.2:3b'")
        except Exception as e:
            logger.warning(f"[OLLAMA] Init error: {e}")

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

    # Stop AppState cleanup task
    app_state.stop_cleanup_task()
    logger.info("[SHUTDOWN] AppState cleanup task stopped")

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

app.include_router(analysis_router)
app.include_router(ebay_router)
app.include_router(pricecharting_router)
app.include_router(sellers_router)
app.include_router(dashboard_router)
app.include_router(keepa_router)
app.include_router(ebay_race_router)
app.include_router(race_router)
app.include_router(costume_router)
app.include_router(analytics_router)
app.include_router(websocket_router)
app.include_router(data_router)
app.include_router(debug_router)
app.include_router(openai_compat_router)
app.include_router(queue_router)

# AI Clients (extracted to services/clients.py)
from services.clients import create_anthropic_client, create_openai_client
client = create_anthropic_client(CLAUDE_API_KEY)
openai_client = create_openai_client(OPENAI_API_KEY, OPENAI_TIER2_MODEL)


# Model selection for Tier 1 (category-aware)

# Gold/Silver: GPT-4o (smarter, better at weight estimation and scale reading)

# Other categories: GPT-4o-mini (cheaper, still good for TCG/LEGO/videogames)

TIER1_MODEL_GOLD_SILVER = "gpt-4o-mini"  # Mini for Tier 1 (cheaper), Tier 2 uses gpt-4o for verification

TIER1_MODEL_DEFAULT = "gpt-4o-mini"  # Mini for other categories

TIER1_MODEL_FALLBACK = MODEL_FAST   # Haiku fallback if OpenAI fails


# ============================================================
# STATE MANAGEMENT (Refactored with AppState - Phase 1.1)
# ============================================================

# Create centralized application state instance
app_state = AppState()

# Backwards compatibility aliases - these reference the AppState instance
# TODO: Gradually migrate code to use app_state directly
ENABLED = app_state.enabled
DEBUG_MODE = app_state.debug_mode
QUEUE_MODE = app_state.queue_mode
EBAY_POLLER_ENABLED = app_state.ebay_poller_enabled
LISTING_QUEUE = app_state.listing_queue
IN_FLIGHT = app_state.in_flight
IN_FLIGHT_RESULTS = app_state.in_flight_results
STATS = app_state.stats

# Setup error handling middleware (Phase 3 refactoring)
# Must be after DEBUG_MODE is defined
setup_error_handlers(app, debug=DEBUG_MODE)

IN_FLIGHT_LOCK = asyncio.Lock()

# Concurrency controls - allow parallel processing
# Semaphore limits concurrent AI API calls to prevent rate limiting
MAX_CONCURRENT_AI_CALLS = 20  # Increased from 10 to handle 4-panel spike traffic
AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI_CALLS)

# NOTE: Budget tracking functions imported from utils.budget
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

# Configure eBay lookup service
configure_ebay_lookup(ebay_app_id=EBAY_APP_ID)


# Deduplication (extracted to services/deduplication.py)
from services.deduplication import (
    RECENTLY_EVALUATED, check_recently_evaluated, mark_as_evaluated, get_evaluated_item_key
)


# NOTE: eBay lookup functions moved to services/ebay_lookup.py


# NOTE: Instant pass functions moved to pipeline/instant_pass.py

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

# HELPER FUNCTIONS (extracted to services/response_wrapper.py)
from services.response_wrapper import (
    create_openai_response, format_listing_data, sanitize_json_response, parse_reasoning
)



# ============================================================

# HOT RELOAD

# ============================================================

RELOAD_HISTORY = []


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
        analyze_listing_callback,  # Callback for full AI analysis + source comparison
        get_oauth_token,  # OAuth token for item tracking polling
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
        analyze_listing_callback=analyze_listing_callback,  # For full AI analysis + source comparison,
        get_api_buy_wins_stats=get_api_buy_wins_stats,
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

# Configure race mode routes module
configure_race(
    BLOCKED_SELLERS=BLOCKED_SELLERS,
    INSTANT_PASS_KEYWORDS=INSTANT_PASS_KEYWORDS,
    UBF_TITLE_FILTERS=UBF_TITLE_FILTERS,
    UBF_LOCATION_FILTERS=UBF_LOCATION_FILTERS,
    UBF_FEEDBACK_RULES=UBF_FEEDBACK_RULES,
)

# Configure costume jewelry routes module
configure_costume(
    client=client,
    cache=cache,
    STATS=STATS,
    get_enabled=lambda: ENABLED,
    DB_PATH=DB_PATH,
    MODEL_FAST=MODEL_FAST,
    COST_PER_CALL_HAIKU=COST_PER_CALL_HAIKU,
    get_system_context=get_system_context,
    get_agent=get_agent,
    log_incoming_listing=log_incoming_listing,
    save_listing=save_listing,
    update_pattern_outcome=update_pattern_outcome,
    process_image_list=process_image_list,
    render_result_html=render_result_html,
    format_listing_data=format_listing_data,
    sanitize_json_response=sanitize_json_response,
)

# Configure analytics routes module
configure_analytics(
    get_analytics=get_analytics,
    get_pattern_analytics=get_pattern_analytics,
    render_patterns_page=render_patterns_page,
    render_analytics_page=render_analytics_page,
)

# Configure OpenAI compat routes
configure_openai_compat(
    client=client, model_fast=MODEL_FAST, enabled_ref=[ENABLED],
    stats=STATS, create_openai_response_fn=create_openai_response,
    get_gold_prompt_fn=get_gold_prompt, get_silver_prompt_fn=get_silver_prompt
)

# Configure queue routes
configure_queue(
    client=client, model_fast=MODEL_FAST, cost_per_call=COST_PER_CALL_HAIKU,
    listing_queue=LISTING_QUEUE, queue_mode_ref=[QUEUE_MODE],
    stats=STATS, cache=cache, process_image_list_fn=process_image_list,
    get_category_prompt_fn=get_category_prompt, get_agent_prompt_fn=get_agent_prompt,
    format_listing_data_fn=format_listing_data, sanitize_json_response_fn=sanitize_json_response,
    validate_and_fix_margin_fn=validate_and_fix_margin, get_agent_fn=get_agent,
    render_result_html_fn=render_result_html, save_listing_fn=save_listing,
    update_pattern_outcome_fn=update_pattern_outcome
)

# Configure data routes
configure_data(
    stats=STATS, db_path=DB_PATH,
    training_log_path=TRAINING_LOG_PATH, purchase_log_path=PURCHASE_LOG_PATH,
    item_tracking=item_tracking,
    get_app_state_from_request_fn=get_app_state_from_request,
    get_openai_budget_status_fn=get_openai_budget_status,
    set_hourly_budget_fn=set_hourly_budget,
    render_training_dashboard_fn=render_training_dashboard,
    render_purchases_page_fn=render_purchases_page,
)

# Configure debug routes
configure_debug(
    get_spot_prices_fn=get_spot_prices,
    get_db_debug_info_fn=get_db_debug_info,
    stats=STATS,
    db_fetchone_fn=db.fetchone,
    format_confidence_fn=format_confidence,
)

# Configure pipeline orchestrator (main analysis logic - must be after all imports)
configure_orchestrator(
    client=client,
    openai_client=openai_client,
    STATS=STATS,
    cache=cache,
    IN_FLIGHT=IN_FLIGHT,
    IN_FLIGHT_RESULTS=IN_FLIGHT_RESULTS,
    IN_FLIGHT_LOCK=IN_FLIGHT_LOCK,
    ENABLED=ENABLED,
    QUEUE_MODE=QUEUE_MODE,
    LISTING_QUEUE=LISTING_QUEUE,
    TIER1_MODEL_GOLD_SILVER=TIER1_MODEL_GOLD_SILVER,
    TIER1_MODEL_DEFAULT=TIER1_MODEL_DEFAULT,
    MODEL_FAST=MODEL_FAST,
    TIER2_ENABLED=TIER2_ENABLED,
    TIER2_PROVIDER=TIER2_PROVIDER,
    OPENAI_TIER2_MODEL=OPENAI_TIER2_MODEL,
    PARALLEL_MODE=PARALLEL_MODE,
    SKIP_TIER2_FOR_HOT=SKIP_TIER2_FOR_HOT,
    COST_PER_CALL_HAIKU=COST_PER_CALL_HAIKU,
    COST_PER_CALL_GPT4O=COST_PER_CALL_GPT4O,
    COST_PER_CALL_GPT4O_MINI=COST_PER_CALL_GPT4O_MINI,
    CATEGORY_THRESHOLDS=CATEGORY_THRESHOLDS,
    IMAGES=IMAGES,
    FAST_EXTRACT_AVAILABLE=FAST_EXTRACT_AVAILABLE,
    EBAY_POLLER_AVAILABLE=EBAY_POLLER_AVAILABLE,
    check_seller_spam=check_seller_spam,
    analyze_new_seller=analyze_new_seller,
    check_price_correction_fn=check_price_correction,
    detect_category=detect_category,
    get_agent=get_agent,
    get_agent_prompt=get_agent_prompt,
    get_category_prompt=get_category_prompt,
    check_instant_pass=check_instant_pass,
    get_pricecharting_context=get_pricecharting_context,
    check_price_override=check_price_override,
    validate_and_fix_margin=validate_and_fix_margin,
    validate_tcg_lego_result=validate_tcg_lego_result,
    validate_videogame_result=validate_videogame_result,
    fast_extract_gold=fast_extract_gold,
    fast_extract_silver=fast_extract_silver,
    get_spot_prices=get_spot_prices,
    process_image_list=process_image_list,
    format_listing_data=format_listing_data,
    sanitize_json_response=sanitize_json_response,
    render_result_html=render_result_html,
    render_queued_html=_render_queued_html,
    send_discord_alert=send_discord_alert,
    lookup_ebay_item=lookup_ebay_item,
    lookup_ebay_item_by_seller=lookup_ebay_item_by_seller,
    get_ebay_search_url=get_ebay_search_url,
    save_listing=save_listing,
    log_incoming_listing=log_incoming_listing,
    update_pattern_outcome=update_pattern_outcome,
    broadcast_new_listing=broadcast_new_listing,
    check_openai_budget=check_openai_budget,
    record_openai_cost=record_openai_cost,
    log_race_item_fn=log_race_item,
    log_listing_received=log_listing_received,
    race_log_ubf_item=race_log_ubf_item,
    lookup_user_price=lookup_user_price,
)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Claude Proxy Server v3 - Optimized")
    print("=" * 60)
    print(f"Dashboard: http://{HOST}:{PORT}")
    print(f"Optimizations: Async images, Smart cache, Connection pooling")
    if EBAY_POLLER_AVAILABLE:
        print(f"eBay Direct API: Available - /ebay/stats, /ebay/search")
    print("=" * 60 + "\n")

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        workers=1,
    )
