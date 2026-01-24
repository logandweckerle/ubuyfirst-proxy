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
)

# Import path configs from centralized config
from config import TRAINING_LOG_PATH, PURCHASE_LOG_PATH, API_ANALYSIS_ENABLED, PRICE_OVERRIDES_PATH
from services.price_overrides import PRICE_OVERRIDES, load_price_overrides, check_price_override

# Pipeline modules (Phase B extraction)
from pipeline.request_parser import parse_analysis_request, extract_listing_fields, log_request_fields
from pipeline.pre_checks import (
    check_spam, check_dedup, check_sold, check_disabled,
    check_queue_mode, check_cache, check_in_flight,
)
from pipeline.listing_enrichment import build_enhancements, log_race_item as pipeline_log_race_item
from pipeline.fast_pass import (
    check_user_price_db, check_pc_quick_pass, check_agent_quick_pass,
    check_textbook, check_gold_price_per_gram, check_fast_extract_pass,
    check_lazy_image_skip, determine_image_needs,
)
from pipeline.response_builder import finalize_result

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
    global IN_FLIGHT_LOCK

    logger.info("=" * 60)
    logger.info("Claude Proxy v3 - Optimized Starting...")
    logger.info("=" * 60)

    # Store app_state in app.state for access by routes (Phase 1.1 refactoring)
    app_instance.state.app_state = app_state
    logger.info("[INIT] AppState attached to app.state")

    # FIX: Initialize asyncio Lock here (not at module level) to avoid loop issues
    # Note: app_state.in_flight_lock is lazy-initialized, but we also keep global for compat
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

# Analysis router disabled - using main.py endpoint with create_openai_response wrapper
# app.include_router(analysis_router)
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

# Note: IN_FLIGHT_LOCK is now a property on app_state (lazy initialized)
# Access via app_state.in_flight_lock instead of global IN_FLIGHT_LOCK
IN_FLIGHT_LOCK = None  # Keep for backwards compat, but use app_state.in_flight_lock

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















def _trim_listings():

    """Keep only last 100 listings in memory"""

    if len(STATS["listings"]) > 100:

        sorted_ids = sorted(STATS["listings"].keys(), key=lambda x: STATS["listings"][x]["timestamp"])

        for old_id in sorted_ids[:-100]:

            del STATS["listings"][old_id]






# NOTE: PriceCharting validation functions moved to pipeline/pricecharting_validation.py

# ============================================================
# MAIN ANALYSIS ENDPOINT
# ============================================================

@app.post("/match_mydata")
@app.get("/match_mydata")
async def analyze_listing(request: Request):

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

        # Parse request data
        data = await parse_analysis_request(request)
        fields = extract_listing_fields(data)
        title = fields["title"]
        total_price = fields["total_price"]
        alias = fields["alias"]
        response_type = fields["response_type"]
        listing_id = fields["listing_id"]
        timestamp = fields["timestamp"]
        item_id = fields["item_id"]
        ebay_url = fields["ebay_url"]
        images = []


        # ============================================================
        # ============================================================
        # SPAM + DEDUP CHECKS
        # ============================================================
        spam_response = check_spam(data, check_seller_spam)
        if spam_response:
            return spam_response

        dedup_response = check_dedup(title, total_price)
        if dedup_response:
            return dedup_response

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

        # Log request fields for profiling
        log_request_fields(data)


        # ============================================================
        # ============================================================
        # LISTING ENHANCEMENTS
        # ============================================================
        sold_response = check_sold(data)
        if sold_response:
            return sold_response

        listing_enhancements = build_enhancements(data, analyze_new_seller)
        freshness_minutes = listing_enhancements.get("freshness_minutes")
        seller_name = listing_enhancements.get("seller_name", "")


        # ============================================================
        # Race comparison logging
        pipeline_log_race_item(
            data, title, total_price, item_id, freshness_minutes, seller_name,
            log_race_item, log_listing_received, race_log_ubf_item
        )

        

        # Start timing for performance analysis

        import time as _time

        _start_time = _time.time()

        _timing = {}

        

        STATS["total_requests"] += 1

        

        # ============================================================

        # ============================================================
        # SMART CACHE CHECK
        # ============================================================
        cache_response = check_cache(title, total_price, response_type, cache, data, detect_category, STATS)
        if cache_response:
            return cache_response


        # ============================================================
        # IN-FLIGHT DEDUP
        # ============================================================
        is_first_request, inflight_response = await check_in_flight(
            title, total_price, response_type, IN_FLIGHT, IN_FLIGHT_RESULTS, IN_FLIGHT_LOCK
        )
        if inflight_response:
            return inflight_response

        # ============================================================

        # ============================================================
        # DISABLED CHECK
        # ============================================================
        disabled_response = check_disabled(ENABLED, STATS)
        if disabled_response:
            return disabled_response


        # ============================================================
        # QUEUE MODE
        # ============================================================
        queue_response = check_queue_mode(
            QUEUE_MODE, data, title, total_price, listing_id, timestamp,
            None, None, LISTING_QUEUE, alias, detect_category, log_incoming_listing,
            _render_queued_html
        )
        if queue_response:
            return queue_response


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
        # ============================================================
        # USER PRICE DATABASE CHECK
        # ============================================================
        user_price_result = check_user_price_db(
            title, total_price, category, listing_enhancements,
            lookup_user_price, render_result_html, cache
        )
        if user_price_result:
            result, html = user_price_result
            if response_type == "json":
                return JSONResponse(content=result)
            else:
                return HTMLResponse(content=html)


        # ============================================================
        # INSTANT PASS CHECK (Rule-based, no AI)
        # ============================================================
        instant_pass_result = check_instant_pass(title, total_price, category, data)
        if instant_pass_result:
            reason, rec = instant_pass_result
            logger.info(f"[INSTANT PASS] {reason}")
            result = {
                "Recommendation": "PASS", "Qualify": "No",
                "reasoning": f"INSTANT PASS: {reason}", "confidence": 95,
                "instantPass": True, "karat": "NA", "weight": "NA",
                "goldweight": "NA", "silverweight": "NA", "meltvalue": "NA",
                "maxBuy": "NA", "sellPrice": "NA", "Profit": "NA",
                "Margin": "NA", "pricePerGram": "NA", "fakerisk": "NA",
                "itemtype": "NA", "stoneDeduction": "0",
                "weightSource": "NA", "verified": "rule-based",
            }
            html = render_result_html(result, category, title)
            cache.set(title, total_price, result, html, "PASS")
            STATS["pass_count"] += 1
            if response_type == "json":
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

                # === PRICE OVERRIDE CHECK - Manual market prices take precedence ===
                override = check_price_override(title, category)
                if override:
                    override_market = override['market_price']
                    threshold = CATEGORY_THRESHOLDS.get(category, 0.65)
                    override_buy_target = override_market * threshold
                    override_margin = override_buy_target - price_float

                    # Update or create pc_result with override values
                    if pc_result is None:
                        pc_result = {'found': True}
                    pc_result['market_price'] = override_market
                    pc_result['buy_target'] = override_buy_target
                    pc_result['margin'] = override_margin
                    pc_result['product_name'] = override.get('notes', override['product_key'])
                    pc_result['override_applied'] = True

                    logger.info(f"[OVERRIDE] Applied: {override['product_key']} -> market ${override_market}, max buy ${override_buy_target:.0f}, margin ${override_margin:.0f}")



                # Quick pass check
                pc_quick_response = check_pc_quick_pass(
                    pc_result, category, title, total_price, price_float,
                    render_result_html, cache, STATS, response_type
                )
                if pc_quick_response:
                    return pc_quick_response

            except Exception as e:
                logger.error(f"[PC] Price parsing error: {e}")

        # Log for pattern analysis

        log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)


        # === QUICK PASS CHECKS (Agent, Textbook, Gold) ===
        agent_qp_response = check_agent_quick_pass(
            category, data, total_price, title, get_agent,
            render_result_html, cache, STATS, response_type
        )
        if agent_qp_response:
            return agent_qp_response

        textbook_response = await check_textbook(
            category, data, total_price, title, get_agent,
            render_result_html, cache, STATS, response_type
        )
        if textbook_response:
            return textbook_response

        gold_qp_response = check_gold_price_per_gram(
            category, title, total_price, render_result_html, cache, STATS, response_type
        )
        if gold_qp_response:
            return gold_qp_response


        

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


                

                # Extract item specifics from eBay (if available)
                item_specifics = {
                    'Metal': data.get('Metal', ''),
                    'MetalPurity': data.get('MetalPurity', '') or data.get('Metal Purity', ''),
                    'Fineness': data.get('Fineness', ''),
                    'BaseMetal': data.get('BaseMetal', '') or data.get('Base Metal', ''),
                    'Material': data.get('Material', ''),
                    'MainStone': data.get('MainStone', '') or data.get('Main Stone', ''),
                    'TotalCaratWeight': data.get('TotalCaratWeight', '') or data.get('Total Carat Weight', ''),
                }
                # Log if we have item specifics
                item_specifics_present = {k: v for k, v in item_specifics.items() if v}
                if item_specifics_present:
                    logger.info(f"[ITEM SPECIFICS] {item_specifics_present}")

                # Get current spot prices

                spots = get_spot_prices()

                gold_spot = spots.get('gold_oz', 4350)

                silver_spot = spots.get('silver_oz', 75)



                if category == 'gold':

                    fast_result = fast_extract_gold(title, price_float, description, gold_spot, item_specifics)

                else:

                    fast_result = fast_extract_silver(title, price_float, description, silver_spot, item_specifics)

                

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

                

                # Check fast extract instant pass
                fast_extract_response = check_fast_extract_pass(
                    fast_result, category, data, total_price, title,
                    render_result_html, cache, STATS, response_type
                )
                if fast_extract_response:
                    return fast_extract_response

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

        # === FLATWARE WEIGHT ESTIMATION ===
        # If silver item with no weight in title, estimate based on piece type
        if category == 'silver' and not (fast_result and fast_result.weight_grams):
            try:
                from utils.extraction import detect_flatware
                is_flatware, piece_type, flat_qty, estimated_weight = detect_flatware(title)
                if is_flatware and estimated_weight > 0:
                    spots = get_spot_prices()
                    sterling_rate = spots.get('sterling', 2.50)
                    est_melt = estimated_weight * sterling_rate
                    max_buy_est = est_melt * 0.75

                    flatware_context = "\n\n=== FLATWARE WEIGHT ESTIMATE (NO WEIGHT IN TITLE) ===\n"
                    flatware_context += f"DETECTED: {flat_qty}x {piece_type.replace('_', ' ').title()}\n"
                    flatware_context += f"ESTIMATED WEIGHT: {estimated_weight:.0f}g (based on typical flatware sizes)\n"
                    flatware_context += f"ESTIMATED MELT: ${est_melt:.0f} (at ${sterling_rate:.2f}/g sterling)\n"
                    flatware_context += f"ESTIMATED MAX BUY: ${max_buy_est:.0f}\n"
                    flatware_context += "⚠️ WEIGHT IS ESTIMATED - Use images to verify piece type/size.\n"
                    flatware_context += "If listing price < max buy estimate, recommend BUY or RESEARCH.\n"
                    flatware_context += "Flatware from known makers (Dominick & Haff, Gorham, etc.) is solid sterling.\n"

                    fast_context += flatware_context
                    logger.info(f"[FLATWARE] Injecting estimate into prompt: {flat_qty}x {piece_type} = {estimated_weight:.0f}g")
            except Exception as e:
                logger.warning(f"[FLATWARE] Detection error: {e}")

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

            image_detail = "low"  # All Tier 1 uses low detail - Tier 2 verifies with high detail

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

            # SERVER-SIDE VALIDATION: Verify AI's "stated" weight claim against actual title
            # If AI claims weightSource="stated" but no weight exists in title, override to "estimate"
            if weight_source in ['stated', 'title']:
                title_text = data.get('title', '') or data.get('Title', '') or ''
                # Check for actual weight patterns in title: Xg, X grams, X.Xg, X dwt, X oz
                has_weight_in_title = bool(re.search(r'\d+\.?\d*\s*(?:g(?:ram)?s?|dwt|oz)\b', title_text, re.IGNORECASE))
                if not has_weight_in_title:
                    original_source = weight_source
                    logger.warning(f"[WEIGHT-CHECK] AI claimed weightSource='{original_source}' but NO weight found in title: '{title_text[:80]}...'")
                    weight_source = 'estimate'  # Override to estimate - this prevents fast-tracking
                    result['weightSource'] = 'estimate'
                    result['weight_validation_override'] = f"AI claimed '{original_source}' but no weight in title"

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

                    # EXCLUDE lab-created/synthetic diamonds - these are retail junk, not arbitrage opportunities
                    lab_diamond_indicators = ['lab created', 'lab grown', 'lab-created', 'lab-grown', 'igi certified', 'igi lab', 'lgd', 'cvd diamond', 'hpht', 'moissanite', 'simulated', 'cz ', 'cubic zirconia']
                    is_lab_diamond = any(indicator in title_lower for indicator in lab_diamond_indicators)

                    # Check for scale/weight photo indicators
                    scale_hints = ['scale', 'gram', 'grams', 'weigh', 'dwt', 'pennyweight']
                    has_scale_hint = any(hint in title_lower for hint in scale_hints)

                    # Also check description for scale hints
                    desc_lower = str(data.get('Description', '')).lower()
                    has_scale_in_desc = any(hint in desc_lower for hint in scale_hints)

                    # If price > $300 AND has karat AND (has premium stones OR has scale hints), force RESEARCH
                    # BUT skip if it's lab-created diamond jewelry (retail trash)
                    # AND skip if margin is clearly negative (price way above max buy = no opportunity)
                    max_buy = result.get('maxBuy', 0)
                    try:
                        max_buy_val = float(str(max_buy).replace('$', '').replace(',', '')) if max_buy else 0
                    except:
                        max_buy_val = 0

                    # Skip override if price is 50%+ above max buy - clearly overpriced, no opportunity
                    is_clearly_overpriced = max_buy_val > 0 and price_val > max_buy_val * 1.5

                    if is_clearly_overpriced:
                        logger.info(f"[HIGH-VALUE GOLD] Skipping override - clearly overpriced: ${price_val:.0f} vs maxBuy ${max_buy_val:.0f} (margin: -${price_val - max_buy_val:.0f})")
                    elif price_val > 300 and has_karat and (has_premium or has_scale_hint or has_scale_in_desc) and not is_lab_diamond:
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

            # === SERVER CONFIDENCE SCORING (GOLD/SILVER) ===
            # Calculate a real server-side confidence score and use it to influence decisions
            # AI confidence is unreliable - server enforces objective scoring
            if category in ['gold', 'silver'] and result.get('Recommendation') == 'BUY':
                # Calculate server confidence score
                server_score = 60  # Base score
                score_reasons = ["Base: 60"]

                weight_source = result.get('weightSource', 'estimate').lower()
                weight_val = result.get('weight', result.get('goldweight', ''))
                has_weight = weight_val and str(weight_val) not in ['NA', '--', 'Unknown', '', '0', 'None']

                # Weight scoring (CRITICAL for gold/silver)
                if weight_source in ['scale']:
                    server_score += 25
                    score_reasons.append("Scale weight: +25")
                elif weight_source in ['stated', 'title']:
                    server_score += 15
                    score_reasons.append("Stated weight: +15")
                elif has_weight and weight_source in ['estimate', 'estimated', '', 'unknown', 'na']:
                    server_score -= 30  # Heavy penalty for estimated weight
                    score_reasons.append("Estimated weight: -30")
                else:
                    server_score -= 40  # Severe penalty for no weight at all
                    score_reasons.append("No weight: -40")

                # Purity verification (karat for gold, itemtype for silver)
                if category == 'gold':
                    karat = result.get('karat', '')
                    if karat and str(karat) not in ['NA', '--', 'Unknown', '', 'None']:
                        server_score += 10
                        score_reasons.append(f"Karat {karat}: +10")
                    else:
                        server_score -= 10
                        score_reasons.append("No karat: -10")
                else:  # silver
                    itemtype = result.get('itemtype', '')
                    if itemtype and str(itemtype) not in ['NA', '--', 'Unknown', '', 'None', 'Plated', 'NotSilver']:
                        server_score += 10
                        score_reasons.append(f"Silver type {itemtype}: +10")
                    elif itemtype in ['Plated', 'NotSilver']:
                        server_score -= 20
                        score_reasons.append(f"Not silver ({itemtype}): -20")
                    else:
                        server_score -= 10
                        score_reasons.append("No itemtype: -10")

                # Fake risk
                fakerisk = result.get('fakerisk', '').lower()
                if fakerisk == 'high':
                    server_score -= 20
                    score_reasons.append("High fake risk: -20")
                elif fakerisk == 'low':
                    server_score += 5
                    score_reasons.append("Low fake risk: +5")

                # Stone deduction uncertainty
                stone_deduction = result.get('stoneDeduction', '')
                if stone_deduction and str(stone_deduction) not in ['0', 'NA', '--', '', 'None']:
                    server_score -= 10
                    score_reasons.append("Stone deduction: -10")

                # CAMEO CHECK: Shell is NOT gold - AI must deduct shell weight
                title_lower = title.lower() if title else ''
                if 'cameo' in title_lower and category == 'gold':
                    stone_ded_str = str(stone_deduction).lower() if stone_deduction else ''
                    ded_digits = ''.join(c for c in stone_ded_str if c in '0123456789.')
                    ded_grams = float(ded_digits) if ded_digits and ded_digits != '.' else 0
                    has_cameo_deduction = stone_ded_str not in ['0', 'na', '--', '', 'none'] and ded_grams >= 1.5

                    # Also check if AI used full weight as gold weight (no meaningful deduction)
                    try:
                        total_wt = float(str(result.get('weight', '0')).replace('g', '').strip() or '0')
                        gold_wt = float(str(result.get('goldweight', '0')).replace('g', '').strip() or '0')
                        no_weight_deduction = total_wt > 0 and gold_wt > 0 and gold_wt >= total_wt * 0.75
                    except (ValueError, TypeError):
                        no_weight_deduction = False

                    if not has_cameo_deduction or no_weight_deduction:
                        # AI didn't properly deduct cameo shell weight - force RESEARCH
                        server_score -= 40
                        score_reasons.append("Cameo: no proper shell deduction: -40")
                        logger.warning(f"[CAMEO CHECK] Shell weight not deducted! weight={result.get('weight')}, goldweight={result.get('goldweight')}, stoneDeduction='{stone_deduction}', title='{title[:60]}'")
                    else:
                        server_score -= 5
                        score_reasons.append("Cameo (shell deducted): -5")

                # Store calculated score in result
                result['serverConfidence'] = server_score
                result['serverScoreBreakdown'] = " | ".join(score_reasons)

                # Decision logic based on server score
                if server_score < 50:
                    logger.warning(f"[SERVER SCORE] Forcing BUY->RESEARCH: score={server_score} ({' | '.join(score_reasons)})")
                    result['Recommendation'] = 'RESEARCH'
                    original_reasoning = result.get('reasoning', '')
                    result['reasoning'] = f"[LOW CONFIDENCE: {server_score}/100] {' | '.join(score_reasons)} - needs verification. " + original_reasoning
                    result['tier2_override'] = True
                    result['tier2_reason'] = f'Server confidence {server_score} < 50 threshold'
                    html = render_result_html(result, category, title)
                elif server_score < 65:
                    logger.info(f"[SERVER SCORE] BUY with caution: score={server_score} ({' | '.join(score_reasons)})")
                    result['reasoning'] = f"[MODERATE CONFIDENCE: {server_score}/100] " + result.get('reasoning', '')
                else:
                    logger.info(f"[SERVER SCORE] HIGH confidence BUY: score={server_score}")

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

            

            # Build final response
            return finalize_result(
                result, html, title, total_price, listing_enhancements,
                response_type, _timing, _start_time, cache
            )


            

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

# ANALYZE QUEUED LISTING

# ============================================================

# MOVED TO routes/ module: analyze-queued

# ============================================================

# ANALYZE NOW - Called from uBuyFirst panel button

# ============================================================

# MOVED TO routes/ module: analyze-now

# Toggle/Control endpoints moved to routes/dashboard.py


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


