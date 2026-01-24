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



# /api/cache-stats moved to routes/dashboard.py

@app.get("/api/budget")
async def api_budget_status():
    """Get OpenAI hourly budget status"""
    return get_openai_budget_status()


@app.post("/api/budget/set")
async def api_set_budget(hourly_limit: float = 10.0):
    """Set the hourly OpenAI budget limit"""
    if hourly_limit < 1.0:
        return {"error": "Budget must be at least $1/hour"}
    if hourly_limit > 100.0:
        return {"error": "Budget cannot exceed $100/hour"}
    set_hourly_budget(hourly_limit)
    logger.info(f"[BUDGET] Hourly limit set to ${hourly_limit:.2f}")
    return {"success": True, "hourly_budget": hourly_limit}


@app.get("/api/memory-stats")
async def api_memory_stats(request: Request):
    """Get AppState memory usage statistics for monitoring"""
    app_state = get_app_state_from_request(request)
    return app_state.get_memory_stats()


# ============================================================
# ITEM TRACKING ENDPOINTS - Fast-selling pattern analysis
# ============================================================

@app.get("/api/tracking/stats")
async def api_tracking_stats():
    """Get item tracking statistics including fast-sale patterns"""
    return item_tracking.get_tracking_stats()


@app.get("/api/tracking/fast-sales")
async def api_tracking_fast_sales(limit: int = 50):
    """Get items that sold within 5 minutes of listing"""
    return item_tracking.get_fast_sales(limit=limit)


@app.get("/api/tracking/active")
async def api_tracking_active(limit: int = 100):
    """Get active items currently being tracked"""
    return item_tracking.get_active_items(limit=limit)


@app.post("/api/tracking/resolve-now")
async def api_tracking_resolve_now():
    """Manually trigger eBay item ID resolution for pending items"""
    await item_tracking.resolve_pending_items(batch_size=20)
    stats = item_tracking.get_tracking_stats()
    return {
        "status": "ok",
        "message": "Resolution completed",
        "resolved_ids": stats.get("resolved_ids", 0),
        "pending_resolution": stats.get("pending_resolution", 0)
    }


@app.post("/api/tracking/poll-now")
async def api_tracking_poll_now():
    """Manually trigger ID resolution + poll for sold items"""
    # First resolve any pending IDs
    await item_tracking.resolve_pending_items(batch_size=20)
    # Then poll for sold status
    await item_tracking.poll_items_for_sold_status(batch_size=50)
    return {"status": "ok", "message": "Resolution and polling completed"}


@app.get("/api/patterns/stats")
async def api_pattern_stats():
    """Get statistics about logged learning patterns"""
    return item_tracking.get_pattern_stats()


@app.get("/api/patterns/{category}")
async def api_patterns_by_category(category: str, limit: int = 50):
    """Get recent patterns for a specific category"""
    patterns = item_tracking.get_patterns_by_category(category, limit)
    return {"category": category, "count": len(patterns), "patterns": patterns}


@app.post("/api/patterns/log")
async def api_log_manual_pattern(request: Request):
    """Manually log a pattern for learning (e.g., missed opportunity)"""
    data = await request.json()

    required = ['pattern_type', 'category', 'title', 'price']
    for field in required:
        if field not in data:
            return JSONResponse(
                content={"error": f"Missing required field: {field}"},
                status_code=400
            )

    result = data.get('result', {})
    notes = data.get('notes', '')

    item_tracking.log_pattern(
        pattern_type=data['pattern_type'],
        category=data['category'],
        title=data['title'],
        price=float(data['price']),
        result=result,
        data=data,
        notes=notes
    )

    return {"status": "ok", "message": f"Logged {data['pattern_type']} pattern"}


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

        

        # Check weight source (CRITICAL - these penalties affect BUY decisions)

        weight_has_value = weight and weight not in ['NA', '--', 'Unknown', '', '0']

        if weight_has_value and weight_was_from_scale:

            factors.append(("Weight from Scale", "+25", f"Scale: {weight}g"))

        elif weight_has_value and weight_source == 'stated':

            factors.append(("Weight Stated", "+15", f"Stated: {weight}g"))

        elif weight_has_value and not weight_was_from_scale:

            factors.append(("Weight Estimated", "-30", f"Est: {weight}g (UNVERIFIED - BUY blocked)"))

        else:

            factors.append(("No Weight", "-40", "Weight unknown (BUY blocked)"))

        

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

        elif weight_has_value and weight_source == 'stated':

            factors.append(("Weight Stated", "+15", f"Stated: {weight}g"))

        elif weight_has_value and not weight_was_from_scale:

            factors.append(("Weight Estimated", "-30", f"Est: {weight}g (UNVERIFIED - BUY blocked)"))

        else:

            factors.append(("No Weight", "-40", "Weight unknown (BUY blocked)"))



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
async def training_dashboard_page():
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

        html = render_training_dashboard(overrides, by_type, by_category)
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
        html = render_purchases_page(purchases, total_spent, total_projected_profit)
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")


@app.get("/architecture", response_class=HTMLResponse)
async def architecture_page():
    """System architecture and understanding dashboard"""
    import os
    from templates.pages import render_system_architecture
    from agents import AGENTS
    from config.settings import CATEGORY_THRESHOLDS

    # Gather system data
    system_data = {}

    # Get agent info
    agents_info = {}
    agent_descriptions = {
        'gold': 'Precious metal scrap - analyzes gold jewelry by weight/karat for melt value',
        'silver': 'Sterling silver analysis - 925/800 purity, flatware, scrap lots',
        'platinum': 'Platinum jewelry - 950/900 purity melt value calculations',
        'palladium': 'Palladium items - rare precious metal analysis',
        'tcg': 'Trading cards - Pokemon, MTG sealed products and graded cards',
        'lego': 'LEGO sets - sealed/retired sets with PriceCharting lookup',
        'videogames': 'Video games - retro/collectible games with market pricing',
        'watch': 'Watches - luxury/vintage watches, NOT gold scrap',
        'knives': 'Collectible knives - Chris Reeve, Strider, Benchmade, vintage',
        'pens': 'Fountain pens - Montblanc, Pelikan, vintage collectibles',
        'costume': 'Costume jewelry - Trifari, Eisenberg, vintage signed pieces',
        'coral': 'Coral & Amber - antique/vintage natural materials',
        'textbook': 'College textbooks - ISBN lookup for buyback value',
        'industrial': 'Industrial equipment - PLCs, automation gear',
    }
    for name, agent_class in AGENTS.items():
        threshold = CATEGORY_THRESHOLDS.get(name, CATEGORY_THRESHOLDS.get('default', 0.65))
        agents_info[name.title()] = {
            'active': True,
            'description': agent_descriptions.get(name, f'{name} category analysis'),
            'threshold': f'{threshold:.0%}' if isinstance(threshold, float) else str(threshold),
        }
    system_data['agents'] = agents_info

    # Get database sizes
    dbs = []
    db_files = [
        ('arbitrage_data.db', 'Historical listings, seller patterns, dedup cache'),
        ('pricecharting_prices.db', '117K+ video game/collectible market prices'),
        ('purchase_history.db', 'Logged purchases for learning/tracking'),
        ('price_data.db', 'Cached price lookups'),
    ]
    for db_name, purpose in db_files:
        db_path = Path(db_name)
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            dbs.append({'name': db_name, 'purpose': purpose, 'size_mb': size_mb, 'records': '--'})
    system_data['databases'] = dbs

    # Get live stats
    system_data['stats'] = {
        'Listings Analyzed': STATS.get('total_count', 0),
        'BUY Signals': STATS.get('buy_count', 0),
        'PASS': STATS.get('pass_count', 0),
        'RESEARCH': STATS.get('research_count', 0),
        'Blocked Sellers': len(BLOCKED_SELLERS),
        'Cache Hits': STATS.get('cache_hits', 0),
    }

    # Get config
    from config import SPOT_PRICES
    system_data['config'] = {
        'Gold Spot': f"${SPOT_PRICES.get('gold_oz', 0):,.2f}/oz",
        'Silver Spot': f"${SPOT_PRICES.get('silver_oz', 0):,.2f}/oz",
        'Tier 1 Model': 'GPT-4o-mini',
        'Tier 2 Model': 'GPT-4o',
        'Discord Alerts': 'Enabled' if os.getenv('DISCORD_WEBHOOK_URL') else 'Disabled',
        'eBay Polling': 'Available',
    }

    # Key routes
    system_data['routes'] = [
        {'method': 'POST', 'path': '/match_mydata', 'description': 'Main analysis endpoint (uBuyFirst webhook)'},
        {'method': 'GET', 'path': '/dashboard', 'description': 'Main monitoring dashboard'},
        {'method': 'GET', 'path': '/live', 'description': 'Real-time WebSocket feed'},
        {'method': 'POST', 'path': '/ebay/poll/start', 'description': 'Start direct eBay polling'},
        {'method': 'GET', 'path': '/ebay/stats', 'description': 'eBay API usage statistics'},
        {'method': 'GET', 'path': '/api/blocked-sellers', 'description': 'List blocked sellers'},
        {'method': 'GET', 'path': '/purchases', 'description': 'Purchase history dashboard'},
        {'method': 'GET', 'path': '/training', 'description': 'Training data dashboard'},
        {'method': 'GET', 'path': '/health', 'description': 'Health check endpoint'},
    ]

    html = render_system_architecture(system_data)
    return HTMLResponse(content=html)







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
        analyze_listing_callback=analyze_listing_callback,  # For full AI analysis + source comparison
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


@app.get("/ebay/api-wins")
async def ebay_api_wins():
    """Get Direct API BUY wins - items found by API before uBuyFirst"""
    stats = get_api_buy_wins_stats()
    return JSONResponse({
        "status": "ok",
        "api_buy_wins": stats
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
    app_state=app_state,  # Phase 2: Direct AppState access
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





# NOTE: WebSocket code moved to routes/websocket.py


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

                    # Log Direct API BUY wins for tracking
                    if rec == "BUY":
                        log_api_buy_win(
                            item_id=listing.item_id,
                            title=listing.title,
                            price=listing.price,
                            profit=profit_val,
                            category=cat,
                            melt_value=float(str(analysis.get('meltvalue', '0')).replace('$', '').replace(',', '') or 0),
                            weight=analysis.get('weight', '')
                        )
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
    race_log_ubf_item=race_log_ubf_item,
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
    app_state=app_state,  # Phase 2: Direct AppState access
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

