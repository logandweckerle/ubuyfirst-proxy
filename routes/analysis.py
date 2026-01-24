"""
Analysis Route - Main listing analysis endpoint
Extracted from main.py for modularity

This module contains the /match_mydata endpoint which processes
eBay listings through the AI analysis pipeline.

Phase 2 Refactoring: Routes now support direct AppState access via request.
"""

import json
import uuid
import asyncio
import logging
import traceback
import re
import time as _time
from datetime import datetime
from urllib.parse import parse_qs, unquote
from typing import Dict, Any, Optional, List, Callable, Tuple, TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from services.app_state import AppState

# Item tracking for sold status monitoring
from services import item_tracking

# Allen Bradley key normalization
from utils.validation import normalize_allen_bradley_keys

logger = logging.getLogger(__name__)

# Create router for analysis endpoints
router = APIRouter()

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_analysis)
# ============================================================

# API Clients
_client = None  # Anthropic client
_openai_client = None  # OpenAI client

# NEW: Direct AppState reference (Phase 2 refactoring)
_app_state: Optional["AppState"] = None


def _get_state(request: Optional[Request] = None) -> Optional["AppState"]:
    """
    Get AppState from request or module-level reference.
    Provides backwards compatibility during migration.
    """
    if request and hasattr(request.app.state, 'app_state'):
        return request.app.state.app_state
    return _app_state


def _increment_stat(key: str, amount: int = 1, request: Optional[Request] = None) -> None:
    """
    Increment a stat counter using AppState if available, else legacy _STATS.
    """
    state = _get_state(request)
    if state:
        state.increment_stat(key, amount)
    elif _STATS is not None:
        if key in _STATS:
            _STATS[key] += amount


def _add_session_cost(cost: float, request: Optional[Request] = None) -> None:
    """
    Add to session cost using AppState if available, else legacy _STATS.
    """
    state = _get_state(request)
    if state:
        state.add_cost(cost)
    elif _STATS is not None:
        _STATS["session_cost"] += cost


def _is_enabled(request: Optional[Request] = None) -> bool:
    """
    Check if proxy is enabled using AppState if available, else legacy callback.
    """
    state = _get_state(request)
    if state:
        return state.enabled
    return _ENABLED() if _ENABLED else True


def _get_stats_dict(request: Optional[Request] = None) -> Dict:
    """
    Get the stats dictionary for direct access (e.g., for listings).
    """
    state = _get_state(request)
    if state:
        return state.stats
    return _STATS if _STATS else {}


# State & Config (LEGACY - kept for backwards compat)
_STATS = None
_ENABLED = None
_QUEUE_MODE = None
_LISTING_QUEUE = None
_cache = None
_IN_FLIGHT = None
_IN_FLIGHT_LOCK = None
_IN_FLIGHT_RESULTS = None

# Model config
_MODEL_FAST = None
_TIER1_MODEL_GOLD_SILVER = None
_TIER1_MODEL_DEFAULT = None
_TIER2_ENABLED = None
_TIER2_PROVIDER = None
_OPENAI_TIER2_MODEL = None
_PARALLEL_MODE = None
_SKIP_TIER2_FOR_HOT = None

# Cost constants
_COST_PER_CALL_HAIKU = None
_COST_PER_CALL_GPT4O = None
_COST_PER_CALL_GPT4O_MINI = None

# Image config
_IMAGES = None

# Feature flags
_FAST_EXTRACT_AVAILABLE = False
_EBAY_POLLER_AVAILABLE = False

# Functions (injected)
_check_seller_spam = None
_check_recently_evaluated = None
_mark_as_evaluated = None
_check_price_correction = None
_analyze_new_seller = None
_log_race_item = None
_log_listing_received = None
_race_log_ubf_item = None  # For RACE_DATA tracking in main.py
_detect_category = None
_lookup_user_price = None
_check_instant_pass = None
_get_pricecharting_context = None
_get_agent = None
_get_agent_prompt = None
_fast_extract_gold = None
_fast_extract_silver = None
_get_spot_prices = None
_process_image_list = None
_get_category_prompt = None
_format_listing_data = None
_validate_and_fix_margin = None
_validate_tcg_lego_result = None
_validate_videogame_result = None
_render_result_html = None
_sanitize_json_response = None
_tier2_reanalyze = None
_tier2_reanalyze_openai = None
_background_sonnet_verify = None
_send_discord_alert = None
_lookup_ebay_item = None
_lookup_ebay_item_by_seller = None
_get_ebay_search_url = None
_save_listing = None
_update_pattern_outcome = None
_broadcast_new_listing = None
_trim_listings = None
_check_openai_budget = None
_record_openai_cost = None
_log_incoming_listing = None
_render_queued_html = None


def configure_analysis(
    # API Clients
    client,
    openai_client,
    # State & Config
    STATS: Dict,
    ENABLED_ref: Callable[[], bool],
    QUEUE_MODE_ref: Callable[[], bool],
    LISTING_QUEUE: Dict,
    cache,
    IN_FLIGHT: Dict,
    IN_FLIGHT_LOCK_ref: Callable,  # Callable to get lock (created in startup event)
    IN_FLIGHT_RESULTS: Dict,
    # Model config
    MODEL_FAST: str,
    TIER1_MODEL_GOLD_SILVER: str,
    TIER1_MODEL_DEFAULT: str,
    TIER2_ENABLED: bool,
    TIER2_PROVIDER: str,
    OPENAI_TIER2_MODEL: str,
    PARALLEL_MODE: bool,
    SKIP_TIER2_FOR_HOT: bool,
    # Cost constants
    COST_PER_CALL_HAIKU: float,
    COST_PER_CALL_GPT4O: float,
    COST_PER_CALL_GPT4O_MINI: float,
    # Image config
    IMAGES,
    # Feature flags
    FAST_EXTRACT_AVAILABLE: bool,
    EBAY_POLLER_AVAILABLE: bool,
    # Functions
    check_seller_spam: Callable,
    check_recently_evaluated: Callable,
    mark_as_evaluated: Callable,
    check_price_correction: Callable,
    analyze_new_seller: Callable,
    log_race_item: Callable,
    log_listing_received: Callable,
    race_log_ubf_item: Callable,  # For RACE_DATA tracking
    detect_category: Callable,
    lookup_user_price: Callable,
    check_instant_pass: Callable,
    get_pricecharting_context: Callable,
    get_agent: Callable,
    get_agent_prompt: Callable,
    fast_extract_gold: Callable,
    fast_extract_silver: Callable,
    get_spot_prices: Callable,
    process_image_list: Callable,
    get_category_prompt: Callable,
    format_listing_data: Callable,
    validate_and_fix_margin: Callable,
    validate_tcg_lego_result: Callable,
    validate_videogame_result: Callable,
    render_result_html: Callable,
    sanitize_json_response: Callable,
    tier2_reanalyze: Callable,
    tier2_reanalyze_openai: Callable,
    background_sonnet_verify: Callable,
    send_discord_alert: Callable,
    lookup_ebay_item: Callable,
    lookup_ebay_item_by_seller: Callable,
    get_ebay_search_url: Callable,
    save_listing: Callable,
    update_pattern_outcome: Callable,
    broadcast_new_listing: Callable,
    trim_listings: Callable,
    check_openai_budget: Callable,
    record_openai_cost: Callable,
    log_incoming_listing: Callable,
    render_queued_html: Callable,
    # NEW: Direct AppState (Phase 2)
    app_state: Optional["AppState"] = None,
):
    """
    Configure the analysis module with all required dependencies.

    Args:
        app_state: Optional AppState instance. When provided, routes will use
                   this directly instead of the legacy getter/setter callbacks.
    """
    global _client, _openai_client, _app_state
    global _STATS, _ENABLED, _QUEUE_MODE, _LISTING_QUEUE, _cache
    global _IN_FLIGHT, _IN_FLIGHT_LOCK, _IN_FLIGHT_RESULTS
    global _MODEL_FAST, _TIER1_MODEL_GOLD_SILVER, _TIER1_MODEL_DEFAULT
    global _TIER2_ENABLED, _TIER2_PROVIDER, _OPENAI_TIER2_MODEL
    global _PARALLEL_MODE, _SKIP_TIER2_FOR_HOT
    global _COST_PER_CALL_HAIKU, _COST_PER_CALL_GPT4O, _COST_PER_CALL_GPT4O_MINI
    global _IMAGES, _FAST_EXTRACT_AVAILABLE, _EBAY_POLLER_AVAILABLE
    global _check_seller_spam, _check_recently_evaluated, _mark_as_evaluated
    global _check_price_correction, _analyze_new_seller
    global _log_race_item, _log_listing_received, _race_log_ubf_item, _detect_category
    global _lookup_user_price, _check_instant_pass, _get_pricecharting_context
    global _get_agent, _get_agent_prompt, _fast_extract_gold, _fast_extract_silver
    global _get_spot_prices, _process_image_list, _get_category_prompt, _format_listing_data
    global _validate_and_fix_margin, _validate_tcg_lego_result, _validate_videogame_result
    global _render_result_html, _sanitize_json_response
    global _tier2_reanalyze, _tier2_reanalyze_openai, _background_sonnet_verify
    global _send_discord_alert, _lookup_ebay_item, _lookup_ebay_item_by_seller
    global _get_ebay_search_url, _save_listing, _update_pattern_outcome
    global _broadcast_new_listing, _trim_listings
    global _check_openai_budget, _record_openai_cost
    global _log_incoming_listing, _render_queued_html

    # API Clients
    _client = client
    _openai_client = openai_client

    # NEW: Direct AppState reference
    _app_state = app_state

    # State & Config (legacy - kept for backwards compat)
    _STATS = STATS
    _ENABLED = ENABLED_ref
    _QUEUE_MODE = QUEUE_MODE_ref
    _LISTING_QUEUE = LISTING_QUEUE
    _cache = cache
    _IN_FLIGHT = IN_FLIGHT
    _IN_FLIGHT_LOCK = IN_FLIGHT_LOCK_ref  # Store the callable
    _IN_FLIGHT_RESULTS = IN_FLIGHT_RESULTS

    # Model config
    _MODEL_FAST = MODEL_FAST
    _TIER1_MODEL_GOLD_SILVER = TIER1_MODEL_GOLD_SILVER
    _TIER1_MODEL_DEFAULT = TIER1_MODEL_DEFAULT
    _TIER2_ENABLED = TIER2_ENABLED
    _TIER2_PROVIDER = TIER2_PROVIDER
    _OPENAI_TIER2_MODEL = OPENAI_TIER2_MODEL
    _PARALLEL_MODE = PARALLEL_MODE
    _SKIP_TIER2_FOR_HOT = SKIP_TIER2_FOR_HOT

    # Cost constants
    _COST_PER_CALL_HAIKU = COST_PER_CALL_HAIKU
    _COST_PER_CALL_GPT4O = COST_PER_CALL_GPT4O
    _COST_PER_CALL_GPT4O_MINI = COST_PER_CALL_GPT4O_MINI

    # Image config
    _IMAGES = IMAGES

    # Feature flags
    _FAST_EXTRACT_AVAILABLE = FAST_EXTRACT_AVAILABLE
    _EBAY_POLLER_AVAILABLE = EBAY_POLLER_AVAILABLE

    # Functions
    _check_seller_spam = check_seller_spam
    _check_recently_evaluated = check_recently_evaluated
    _mark_as_evaluated = mark_as_evaluated
    _check_price_correction = check_price_correction
    _analyze_new_seller = analyze_new_seller
    _log_race_item = log_race_item
    _log_listing_received = log_listing_received
    _race_log_ubf_item = race_log_ubf_item
    _detect_category = detect_category
    _lookup_user_price = lookup_user_price
    _check_instant_pass = check_instant_pass
    _get_pricecharting_context = get_pricecharting_context
    _get_agent = get_agent
    _get_agent_prompt = get_agent_prompt
    _fast_extract_gold = fast_extract_gold
    _fast_extract_silver = fast_extract_silver
    _get_spot_prices = get_spot_prices
    _process_image_list = process_image_list
    _get_category_prompt = get_category_prompt
    _format_listing_data = format_listing_data
    _validate_and_fix_margin = validate_and_fix_margin
    _validate_tcg_lego_result = validate_tcg_lego_result
    _validate_videogame_result = validate_videogame_result
    _render_result_html = render_result_html
    _sanitize_json_response = sanitize_json_response
    _tier2_reanalyze = tier2_reanalyze
    _tier2_reanalyze_openai = tier2_reanalyze_openai
    _background_sonnet_verify = background_sonnet_verify
    _send_discord_alert = send_discord_alert
    _lookup_ebay_item = lookup_ebay_item
    _lookup_ebay_item_by_seller = lookup_ebay_item_by_seller
    _get_ebay_search_url = get_ebay_search_url
    _save_listing = save_listing
    _update_pattern_outcome = update_pattern_outcome
    _broadcast_new_listing = broadcast_new_listing
    _trim_listings = trim_listings
    _check_openai_budget = check_openai_budget
    _record_openai_cost = record_openai_cost
    _log_incoming_listing = log_incoming_listing
    _render_queued_html = render_queued_html

    logger.info(f"[ANALYSIS] Module configured (app_state={'provided' if app_state else 'legacy mode'})")


# ============================================================
# MAIN ANALYSIS ENDPOINT
# ============================================================

@router.post("/match_mydata")
@router.get("/match_mydata")
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

        # Extract item_id from various sources
        if not item_id:
            # Try ProductReferenceID (sometimes contains eBay item ID)
            prod_ref = data.get('ProductReferenceID', '')
            if prod_ref:
                prod_ref_str = str(prod_ref).strip()
                if prod_ref_str and prod_ref_str.isdigit() and len(prod_ref_str) >= 10:
                    item_id = prod_ref_str

        # If still no item_id, generate a hash from title+price for tracking
        if not item_id:
            import hashlib
            tracking_key = f"{title}|{total_price}"
            item_id = "ubf_" + hashlib.md5(tracking_key.encode()).hexdigest()[:12]
            logger.debug(f"[TRACKING] Generated hash ID: {item_id}")

        # URL format: https://www.ebay.com/itm/297941758779?...
        if not item_id:
            url_param = data.get('URL', '')
            if '/itm/' in url_param:
                # re is already imported at module level
                match = re.search(r'/itm/(\d+)', url_param)
                if match:
                    item_id = match.group(1)
                    logger.debug(f"[DEBUG] Extracted item_id from URL: {item_id}")

        logger.info(f"Title: {title[:50]}")
        logger.info(f"Price: ${total_price}")
        logger.info(f"[SAVED] response_type: {response_type}")
        logger.info(f"[DEBUG] CheckoutUrl: '{checkout_url}'")
        logger.info(f"[DEBUG] ItemId: '{item_id}'")
        logger.info(f"[DEBUG] ViewUrl: '{view_url}'")
        logger.info(f"[DEBUG] ALL KEYS: {list(data.keys())}")

        # DEBUG: Log SoldTime for ALL requests to detect sold items
        _sold_time = data.get('SoldTime', '') or data.get('Sold Time', '') or ''
        logger.warning(f"[SOLD-CHECK] Title: {title[:60]} | SoldTime: '{_sold_time}'")

        # ============================================================
        # SPAM DETECTION - Check for blocked sellers EARLY
        # ============================================================
        spam_seller_name = data.get('SellerName', '') or data.get('StoreName', '')
        is_blocked, newly_blocked = _check_seller_spam(spam_seller_name)

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
        cached_result = _check_recently_evaluated(title, total_price)
        if cached_result:
            logger.info(f"[DEDUP] Returning cached result: {cached_result.get('Recommendation', 'UNKNOWN')}")
            cached_result['dedup_cached'] = True
            # Ensure html is present for uBuyFirst display
            if 'html' not in cached_result and _render_result_html:
                try:
                    cached_html = _render_result_html(cached_result, cached_result.get('category', 'silver'), title)
                    cached_result['html'] = cached_html
                    logger.info("[DEDUP] Regenerated missing html for cached result")
                except Exception as e:
                    logger.warning(f"[DEDUP] Could not regenerate html: {e}")
            # Respect response_type for dual-request uBuyFirst system
            if response_type == 'json':
                return JSONResponse(content=cached_result)
            else:
                cached_html = cached_result.get('html', '')
                if cached_html:
                    return HTMLResponse(content=cached_html)
                return JSONResponse(content=cached_result)

        # ============================================================
        # PRICE CORRECTIONS - Check user's logged market prices
        # ============================================================
        user_price_correction = None
        if _check_price_correction:
            try:
                user_price_correction = _check_price_correction(title)
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

        # Extract item specifics fields (from eBay item specifics via uBuyFirst)
        # These are critical for gold/silver detection - much more reliable than regex
        item_specifics = {
            # Metal/Purity fields - most valuable for gold/silver
            'Metal': data.get('Metal', ''),
            'MetalPurity': data.get('MetalPurity', '') or data.get('Metal Purity', ''),
            'Fineness': data.get('Fineness', ''),
            'BaseMetal': data.get('BaseMetal', '') or data.get('Base Metal', ''),
            'Material': data.get('Material', ''),
            # Stone fields - for deduction calculations
            'MainStone': data.get('MainStone', '') or data.get('Main Stone', ''),
            'MainStoneCreation': data.get('MainStoneCreation', '') or data.get('Main Stone Creation', ''),
            'TotalCaratWeight': data.get('TotalCaratWeight', '') or data.get('Total Carat Weight', ''),
            'SecondaryStone': data.get('SecondaryStone', '') or data.get('Secondary Stone', ''),
            # Item type fields
            'Type': data.get('Type', ''),
            'Style': data.get('Style', ''),
            'RingSize': data.get('RingSize', '') or data.get('Ring Size', ''),
            'ItemLength': data.get('ItemLength', '') or data.get('Item Length', '') or data.get('Length', ''),
            'ChainLength': data.get('ChainLength', '') or data.get('Chain Length', ''),
            # Value indicators
            'Antique': data.get('Antique', ''),
            'Vintage': data.get('Vintage', ''),
            'Signed': data.get('Signed', ''),
            'Brand': data.get('Brand', ''),
            'Designer': data.get('Designer', ''),
        }
        # Filter out empty values for cleaner logging
        item_specifics_present = {k: v for k, v in item_specifics.items() if v}
        if item_specifics_present:
            logger.info(f"[ITEM SPECIFICS] {item_specifics_present}")

        # Dump ALL non-system fields to find item ID
        skip_keys = {'system_prompt', 'display_template', 'llm_provider', 'llm_model', 'llm_api_key', 'response_type', 'description', 'images'}
        all_values = {k: str(v)[:100] for k, v in data.items() if k not in skip_keys}
        logger.info(f"[ALL VALUES] {all_values}")

        # ============================================================
        # CATEGORY DETECTION (needed early for seller analysis)
        # ============================================================
        category, category_reasons = _detect_category(data)

        # ============================================================
        # ITEM TRACKING - Track for sold status monitoring
        # Use async version with IMMEDIATE eBay ID resolution
        # (spawned as background task to not block response)
        # ============================================================
        if item_id:
            try:
                seller_name = data.get('SellerName', '') or data.get('StoreName', '')
                posted_time = data.get('PostedTime', '').replace('+', ' ')

                # Spawn immediate resolution as background task (don't await - non-blocking)
                # Now passes full original data for learning from missed opportunities
                asyncio.create_task(
                    item_tracking.track_item_with_resolution(
                        item_id=item_id,
                        title=title,
                        price=total_price,
                        category=category or "",
                        alias=alias or "",
                        seller_name=seller_name,
                        posted_time=posted_time,
                        original_data=data  # Store full listing data for learning
                    )
                )
            except Exception as e:
                logger.warning(f"[TRACKING] Error tracking item: {e}")

        # === SILVER CATEGORY LOGGING ===
        # Log all silver items for debugging missed opportunities
        if category == 'silver':
            logger.warning(f"[SILVER-TRACK] Title: {title}")
            logger.warning(f"[SILVER-TRACK] Price: ${total_price}")
            logger.warning(f"[SILVER-TRACK] Alias: {alias}")
            logger.warning(f"[SILVER-TRACK] Category reasons: {category_reasons}")

        # ============================================================
        # LISTING ENHANCEMENTS - Freshness, Sold check, Seller scoring
        # ============================================================

        # Check if already sold (handle both field name formats)
        sold_time_v1 = data.get('SoldTime', '')
        sold_time_v2 = data.get('Sold Time', '')
        sold_time = sold_time_v1 or sold_time_v2 or ''
        sold_time = sold_time.strip() if sold_time else ''
        # Debug: Log sold time values
        if sold_time_v1 or sold_time_v2:
            logger.info(f"[SOLD-TIME] SoldTime='{sold_time_v1}', Sold Time='{sold_time_v2}'")
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
                # Pass listing data for data-driven scoring (24K+ listings analysis)
                listing_scoring_data = {
                    'Condition': data.get('Condition', ''),
                    'Title': title,
                    'Description': data.get('Description', ''),
                    'BestOffer': data.get('BestOffer', ''),
                    'UPC': data.get('UPC', ''),
                    'ConditionDescription': data.get('ConditionDescription', ''),
                }
                seller_analysis = _analyze_new_seller(
                    seller=seller_name,
                    title=title,
                    category=category if category else '',
                    ebay_data=ebay_seller_data,
                    listing_data=listing_scoring_data
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

        # === PROFESSIONAL DEALER AUTO-PASS ===
        # For precious metals and watches, professional dealers know exact values - no arbitrage opportunity
        feedback_score = 0
        try:
            feedback_score = int(data.get('FeedbackScore', 0) or 0)
        except:
            pass

        seller_name_lower = seller_name.lower()
        # Strong dealer indicators - seller name explicitly contains these = instant dealer
        strong_dealer_keywords = ['watches', 'jewelry', 'jeweler', 'coins', 'numismatic', 'bullion', 'precious metals']
        # Weak indicators - need high feedback to confirm
        weak_dealer_keywords = ['gold', 'silver', 'pawn', 'dealer', 'metals']

        is_strong_dealer_name = any(kw in seller_name_lower for kw in strong_dealer_keywords)
        is_weak_dealer_name = any(kw in seller_name_lower for kw in weak_dealer_keywords)
        is_high_feedback = feedback_score >= 500  # Lowered threshold

        if category in ['gold', 'silver', 'watch', 'platinum', 'palladium']:
            # Strong dealer name = instant PASS (e.g., "atlantiswatches", "Piece Unique Watches")
            # Weak dealer name + high feedback = PASS
            # seller_type == 'dealer' from database analysis = PASS
            if is_strong_dealer_name or seller_type == 'dealer' or (is_weak_dealer_name and is_high_feedback):
                logger.warning(f"[DEALER PASS] {seller_name} (feedback:{feedback_score}, type:{seller_type}) - professional dealer")
                quick_result = {
                    'Qualify': 'No',
                    'Recommendation': 'PASS',
                    'reasoning': f"PROFESSIONAL DEALER: '{seller_name}' with {feedback_score} feedback - knows exact values, no arbitrage opportunity",
                    'confidence': 99,
                    'itemtype': category.title(),
                    'seller_score': seller_score,
                    'seller_type': seller_type,
                }
                html = _render_result_html(quick_result, category, title)
                _cache.set(title, total_price, quick_result, html)
                _increment_stat("pass_count", request=request)
                if response_type == 'json':
                    quick_result["html"] = html
                    return JSONResponse(content=quick_result)
                return HTMLResponse(content=html)

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
            seller_name = data.get('SellerName', '') or data.get('StoreName', '')

            _log_race_item(
                item_id=race_item_id,
                source="ubuyfirst",
                title=title,
                price=price_float,
                category=data.get('CategoryName', 'Unknown'),
            )
            logger.info(f"[RACE] Logged item {race_item_id} from uBuyFirst: {title[:40]}")

            # Log to RACE_DATA tracking in main.py (for /race/data endpoint)
            # Calculate latency from PostedTime
            latency_ms = 0
            posted_time_str = data.get('PostedTime', '').replace('+', ' ')
            if posted_time_str:
                try:
                    from datetime import datetime as dt
                    # Multiple format attempts - eBay/UBF use various formats
                    for fmt in ["%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"]:
                        try:
                            # Strip timezone info if present
                            clean_time = posted_time_str.split(' -')[0].split(' +')[0].strip()
                            posted_dt = dt.strptime(clean_time, fmt)
                            latency_ms = int((dt.now() - posted_dt).total_seconds() * 1000)
                            # Sanity check: if latency is negative by more than 5 min, likely timezone issue
                            # Just set to 0 (unknown) rather than showing bogus negative values
                            if latency_ms < -300000:  # More than 5 min negative
                                logger.debug(f"[LATENCY] Bogus negative latency {latency_ms}ms, setting to 0")
                                latency_ms = 0
                            break
                        except:
                            continue
                except:
                    pass

            if _race_log_ubf_item:
                _race_log_ubf_item(race_item_id, title, price_float, seller_name, latency_ms)

            # Log to source comparison system for latency tracking
            _log_listing_received(
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
        _start_time = _time.time()
        _timing = {}

        _increment_stat("total_requests", request=request)

        # ============================================================
        # CHECK SMART CACHE FIRST
        # ============================================================
        cached = _cache.get(title, total_price)
        if cached:
            result, html = cached

            # Detect category to check if we should trust the cache
            category_check, _ = _detect_category(data)

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
                            _increment_stat("cache_hits", request=request)
                            logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")
                            if response_type == 'json':
                                result["html"] = html  # Include HTML for uBuyFirst display
                                return JSONResponse(content=result)
                            else:
                                return HTMLResponse(content=html)
                    except:
                        # If we can't parse prices, trust the cache
                        _increment_stat("cache_hits", request=request)
                        logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")
                        if response_type == 'json':
                            result["html"] = html  # Include HTML for uBuyFirst display
                            return JSONResponse(content=result)
                        else:
                            return HTMLResponse(content=html)
            else:
                _increment_stat("cache_hits", request=request)
                logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')}")
                # Return based on response_type
                if response_type == 'json':
                    logger.info("[CACHE HIT] Returning JSON (response_type=json)")
                    result["html"] = html  # Include HTML for uBuyFirst display
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

        async with _IN_FLIGHT_LOCK():  # Call the callable to get the lock
            if request_key in _IN_FLIGHT and not _IN_FLIGHT[request_key].is_set():
                # Another request is already processing this SAME listing
                logger.info(f"[IN-FLIGHT] Same listing already processing, will wait...")
                event = _IN_FLIGHT[request_key]
                should_wait = True
            elif request_key not in _IN_FLIGHT:
                # We're the first request for this listing - register it
                event = asyncio.Event()
                _IN_FLIGHT[request_key] = event
                _IN_FLIGHT_RESULTS[request_key] = None
                logger.debug(f"[IN-FLIGHT] First request for this listing, processing...")

        # If we should wait for another request processing the same listing
        if should_wait and event:
            try:
                await asyncio.wait_for(event.wait(), timeout=30.0)
                # Get the result from the first request
                if request_key in _IN_FLIGHT_RESULTS and _IN_FLIGHT_RESULTS[request_key]:
                    result, html = _IN_FLIGHT_RESULTS[request_key]
                    logger.info(f"[IN-FLIGHT] Got result: {result.get('Recommendation', 'UNKNOWN')}")
                    if response_type == 'json':
                        result["html"] = html  # Include HTML for uBuyFirst display
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)
            except asyncio.TimeoutError:
                logger.warning(f"[IN-FLIGHT] Timeout - processing independently")
            # Fall through to process ourselves if something went wrong

        # Flag to track if we need to signal completion
        is_first_request = request_key in _IN_FLIGHT and not _IN_FLIGHT[request_key].is_set()

        # ============================================================
        # DISABLED CHECK
        # ============================================================
        if not _is_enabled(request):
            logger.info("DISABLED - Returning placeholder")
            _increment_stat("skipped", request=request)
            disabled_result = {
                "Qualify": "No",
                "Recommendation": "DISABLED",
                "reasoning": "Proxy disabled - enable at localhost:8000"
            }
            return JSONResponse(content=disabled_result)

        # ============================================================
        # QUEUE MODE - Store for manual review
        # ============================================================
        if _QUEUE_MODE():
            _log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

            # Store raw image URLs for later (don't fetch yet - saves time)
            raw_images = data.get('images', [])
            if raw_images:
                first_img = raw_images[0] if raw_images else None
                if first_img:
                    img_preview = str(first_img)[:100] if isinstance(first_img, str) else str(type(first_img))
                    logger.info(f"[IMAGES] First image format: {img_preview}...")

            _LISTING_QUEUE[listing_id] = {
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
        _increment_stat("api_calls", request=request)
        _add_session_cost(_COST_PER_CALL_HAIKU, request=request)

        # Category already detected above
        logger.info(f"Category: {category}")
        _timing['category'] = _time.time() - _start_time
        logger.info(f"[TIMING] Category detect + setup: {_timing['category']*1000:.0f}ms")

        # ============================================================
        # USER PRICE DATABASE CHECK
        # Check if we have a user-provided market value for this item
        # ============================================================
        user_price_match = _lookup_user_price(title)
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

                    html = _render_result_html(result, category, title)
                    _cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        result["html"] = html  # Include HTML for uBuyFirst display
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

                    html = _render_result_html(result, category, title)
                    _cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        result["html"] = html  # Include HTML for uBuyFirst display
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

                    html = _render_result_html(result, category, title)
                    _cache.set(title, total_price, result, html)

                    if response_type == 'json':
                        result["html"] = html  # Include HTML for uBuyFirst display
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)

        # ============================================================
        # INSTANT PASS CHECK (No AI needed - pure rule-based)
        # ============================================================
        instant_pass_result = _check_instant_pass(title, total_price, category, data)
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
            html = _render_result_html(result, category, title)
            _cache.set(title, total_price, result, html, "PASS")

            _increment_stat("pass_count", request=request)
            logger.info(f"[INSTANT PASS] Saved ~8 seconds by skipping AI!")

            if response_type == 'json':
                result["html"] = html  # Include HTML for uBuyFirst display
                return JSONResponse(content=result)
            return HTMLResponse(content=html)

        # ============================================================
        # TEXTBOOK HANDLING - Calls KeepaTracker API (no AI needed)
        # ============================================================
        if category == "textbook":
            logger.info(f"[TEXTBOOK] Routing to KeepaTracker for ISBN lookup")
            try:
                from agents.textbook import TextbookAgent
                textbook_agent = TextbookAgent()

                # Quick pass check
                quick_reason, quick_rec = textbook_agent.quick_pass(data, float(str(total_price).replace('$', '').replace(',', '') or 0))
                if quick_reason:
                    result = {
                        "Recommendation": quick_rec,
                        "Qualify": "No",
                        "reasoning": quick_reason,
                        "confidence": 90,
                        "category": "textbook",
                        **listing_enhancements
                    }
                    html = _render_result_html(result, category, title)
                    if response_type == 'json':
                        result["html"] = html  # Include HTML for uBuyFirst display
                        return JSONResponse(content=result)
                    return HTMLResponse(content=html)

                # Call KeepaTracker for analysis
                textbook_result = await textbook_agent.analyze_textbook(
                    data,
                    float(str(total_price).replace('$', '').replace(',', '') or 0)
                )

                # Add listing enhancements
                textbook_result.update(listing_enhancements)
                textbook_result["category"] = "textbook"

                html = _render_result_html(textbook_result, category, title)
                _cache.set(title, total_price, textbook_result, html)

                if textbook_result.get("Recommendation") == "BUY":
                    _increment_stat("buy_count", request=request)
                else:
                    _increment_stat("pass_count", request=request)

                if response_type == 'json':
                    textbook_result["html"] = html  # Include HTML for uBuyFirst display
                    return JSONResponse(content=textbook_result)
                return HTMLResponse(content=html)

            except Exception as e:
                logger.error(f"[TEXTBOOK] Error: {e}")
                traceback.print_exc()  # traceback already imported at top of file
                # Fall through to standard analysis on error

        # ============================================================
        # COLLECTIBLES HANDLING - Non-arbitrage items, auto-PASS
        # Books, figurines, jars, daguerreotypes, etc. from gold/silver searches
        # ============================================================
        if category == "collectibles":
            logger.info(f"[COLLECTIBLES] Non-arbitrage item detected, auto-PASS: {title[:60]}")
            result = {
                "Recommendation": "PASS",
                "Qualify": "No",
                "Profit": "0",
                "confidence": 80,
                "reasoning": f"Non-arbitrage category (collectibles) - not a precious metal or tracked item. Routed here because item appeared in gold/silver search but contains no gold/silver keywords.",
                "category": "collectibles",
            }
            result.update(listing_enhancements)
            html = _render_result_html(result, category, title)
            if response_type == 'json':
                result["html"] = html
                return JSONResponse(content=result)
            return HTMLResponse(content=html)

        # ============================================================
        # PARALLEL IMAGE PREFETCH OPTIMIZATION
        # Start fetching images in background while doing PriceCharting lookup
        # If we quick-pass, images are wasted but it's a small cost
        # If we continue to AI, images are already fetched = faster response
        # ============================================================
        _image_prefetch_task = None
        _prefetched_images = None
        raw_image_urls = data.get('images', [])

        logger.info(f"[PREFETCH-CHECK] category={category}, has_images={len(raw_image_urls) if raw_image_urls else 0}")

        # Start image prefetch for categories that likely need AI analysis
        if raw_image_urls and category in ['gold', 'silver', 'tcg', 'lego', 'videogames', 'allen_bradley', 'industrial']:
            async def _prefetch_images():
                """Background image fetch - runs in parallel with PC lookup"""
                try:
                    # Determine image settings based on category
                    if category in ['gold', 'silver']:
                        max_imgs = getattr(_IMAGES, 'max_images_gold_silver', 5)
                        img_size = getattr(_IMAGES, 'resize_for_gold_silver', 512)
                    else:
                        max_imgs = 3  # Fewer images for non-precious metal categories
                        img_size = 384

                    # Respect load limits
                    concurrent_requests = len(_IN_FLIGHT) if _IN_FLIGHT else 0
                    if concurrent_requests > 15:
                        max_imgs = 2
                        img_size = 384
                    elif concurrent_requests > 8:
                        max_imgs = 3

                    return await _process_image_list(
                        raw_image_urls,
                        max_size=img_size,
                        max_count=max_imgs,
                        selection="first_last"
                    )
                except Exception as e:
                    logger.error(f"[PREFETCH] Image prefetch error: {e}")
                    return []

            _image_prefetch_task = asyncio.create_task(_prefetch_images())
            logger.info(f"[PREFETCH] Started background image fetch for {category} ({len(raw_image_urls)} URLs)")

        # PriceCharting lookup for TCG and LEGO
        pc_result = None
        pc_context = ""
        if category in ["tcg", "lego", "videogames"]:
            try:
                import re  # Explicit import to avoid "cannot access local variable 're'" error
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
                pc_result, pc_context = _get_pricecharting_context(title, price_float, category, upc, quantity, condition)
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
                        html = _render_result_html(quick_result, category, title)
                        _cache.set(title, total_price, quick_result, html)

                        _increment_stat("pass_count", request=request)
                        logger.info(f"[QUICK PASS] Saved {30}+ seconds by skipping images!")

                        if response_type == 'json':
                            quick_result["html"] = html  # Include HTML for uBuyFirst display
                            return JSONResponse(content=quick_result)
                        return HTMLResponse(content=html)

            except Exception as e:
                logger.error(f"[PC] Price parsing error: {e}")

        # Log for pattern analysis
        _log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

        # === AGENT QUICK PASS - Check for plated/filled keywords before AI ===
        try:
            agent_class = _get_agent(category)
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
                    # Normalize Allen Bradley results to match uBuyFirst column format
                    if category == "allen_bradley":
                        quick_result = normalize_allen_bradley_keys(quick_result)
                    html = _render_result_html(quick_result, category, title)
                    _cache.set(title, total_price, quick_result, html)
                    _increment_stat("pass_count", request=request)
                    if response_type == 'json':
                        quick_result["html"] = html  # Include HTML for uBuyFirst display
                        return JSONResponse(content=quick_result)
                    return HTMLResponse(content=html)
        except Exception as e:
            logger.error(f"[AGENT QUICK PASS] Error: {e}")

        # === TCG GRADED CARD ENRICHMENT - Look up actual PriceCharting prices ===
        # Detect graded cards directly from title (don't rely on _grade_info which may not be set)
        title_lower = title.lower() if title else ""
        is_graded_card = category == 'tcg' and any(g in title_lower for g in ['psa ', 'psa-', 'bgs ', 'bgs-', 'cgc ', 'cgc-'])

        if is_graded_card:
            try:
                from agents.tcg import TCGAgent
                tcg_agent = TCGAgent()
                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                pc_graded_data = tcg_agent.enrich_graded_data(data, price_float)
                if pc_graded_data.get('pc_found'):
                    pc_market = pc_graded_data.get('pc_market_price', 0)
                    pc_buy_target = pc_graded_data.get('pc_buy_target', 0)
                    pc_margin = pc_buy_target - price_float
                    logger.info(f"[TCG-GRADED] PriceCharting: {pc_graded_data.get('pc_card_name')} @ ${pc_market:.0f}, maxBuy ${pc_buy_target:.0f}, margin ${pc_margin:.0f}")

                    # CRITICAL: If price > maxBuy, this is overpriced - instant PASS
                    if price_float > pc_buy_target and pc_buy_target > 0:
                        logger.warning(f"[TCG-GRADED] OVERPRICED: ${price_float:.0f} > maxBuy ${pc_buy_target:.0f} -> instant PASS")
                        quick_result = {
                            'Qualify': 'No',
                            'Recommendation': 'PASS',
                            'reasoning': f"PRICECHARTING: {pc_graded_data.get('pc_card_name')} market ${pc_market:.0f}, maxBuy ${pc_buy_target:.0f}, listing ${price_float:.0f} = ${pc_margin:.0f} (OVERPRICED)",
                            'marketprice': str(int(pc_market)),
                            'maxBuy': str(int(pc_buy_target)),
                            'Profit': str(int(pc_margin)),
                            'confidence': 90,
                            'pcMatch': 'Yes',
                        }
                        html = _render_result_html(quick_result, category, title)
                        _cache.set(title, total_price, quick_result, html)
                        _increment_stat("pass_count", request=request)
                        if response_type == 'json':
                            quick_result["html"] = html
                            return JSONResponse(content=quick_result)
                        return HTMLResponse(content=html)
                else:
                    logger.warning(f"[TCG-GRADED] PriceCharting lookup failed: {pc_graded_data.get('pc_error', 'Unknown')}")
            except Exception as e:
                logger.error(f"[TCG-GRADED] Enrichment error: {e}")
                import traceback
                logger.error(f"[TCG-GRADED] Traceback: {traceback.format_exc()}")

        # === ITEM SPECIFICS DANGER CHECK - Use eBay item specifics to catch fakes ===
        # This catches items where title says "18K Gold" but item specifics say "Stainless Steel"
        if category in ['gold', 'silver', 'watch']:
            try:
                from fast_extract import check_item_specifics_danger
                is_danger, danger_reason = check_item_specifics_danger(data)
                if is_danger:
                    logger.warning(f"[ITEM SPECIFICS] DANGER: {danger_reason}")
                    quick_result = {
                        'Qualify': 'No',
                        'Recommendation': 'PASS',
                        'reasoning': f"ITEM SPECIFICS MISMATCH: {danger_reason}",
                        'confidence': 99,
                        'itemtype': 'Fake/Plated',
                    }
                    html = _render_result_html(quick_result, category, title)
                    _cache.set(title, total_price, quick_result, html)
                    _increment_stat("pass_count", request=request)
                    if response_type == 'json':
                        quick_result["html"] = html
                        return JSONResponse(content=quick_result)
                    return HTMLResponse(content=html)
            except Exception as e:
                logger.debug(f"[ITEM SPECIFICS] Check error: {e}")

        # === GOLD QUICK PASS CHECK - Skip images if price/gram is clearly too high ===
        # Only applies to 10K/14K gold - higher karats (18K+) have higher melt values
        if category == "gold":
            try:
                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                title_lower = title.lower()

                # Check karat in title - only apply quick pass to 10K/14K
                is_low_karat = any(k in title_lower for k in ['10k', '10kt', '14k', '14kt'])
                is_high_karat = any(k in title_lower for k in ['18k', '18kt', '22k', '22kt', '24k', '24kt', 'pure gold', '999'])

                # Skip this check for high karat gold (18K+ has higher melt value)
                if is_high_karat:
                    logger.debug(f"[QUICK PASS] Skipping price/gram check - high karat gold detected")
                elif is_low_karat or not is_high_karat:  # Apply to 10K/14K or unknown karat
                    # Try to extract weight from title (common patterns: "5.5g", "5.5 grams", "5.5 gram")
                    weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?|dwt)\b', title_lower)
                    if weight_match:
                        title_weight = float(weight_match.group(1))

                        # Convert dwt to grams if needed
                        if 'dwt' in title_lower:
                            title_weight = title_weight * 1.555

                        if title_weight > 0:
                            price_per_gram = price_float / title_weight

                            # If price > $100/gram for 10K/14K, instant PASS (way over scrap value)
                            if price_per_gram > 100:
                                logger.info(f"[QUICK PASS] Gold (10K/14K): ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram > $100 - skipping images")

                                quick_result = {
                                    'Qualify': 'No',
                                    'Recommendation': 'PASS',
                                    'reasoning': f"Price ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram exceeds $100/gram ceiling for 10K/14K (auto-PASS)",
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

                                html = _render_result_html(quick_result, category, title)
                                _cache.set(title, total_price, quick_result, html)

                                _increment_stat("pass_count", request=request)
                                logger.info(f"[QUICK PASS] Saved time by skipping images!")

                                if response_type == 'json':
                                    quick_result["html"] = html  # Include HTML for uBuyFirst display
                                    return JSONResponse(content=quick_result)
                                return HTMLResponse(content=html)

            except Exception as e:
                logger.debug(f"[QUICK PASS] Gold check error: {e}")

        # ============================================================
        # FAST EXTRACTION - Instant server-side calculations (0ms)
        # Runs BEFORE AI to provide instant math on verified data
        # ============================================================
        fast_result = None
        if _FAST_EXTRACT_AVAILABLE and category in ['gold', 'silver']:
            try:
                _fast_start = _time.time()
                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                description = data.get('Description', '') or data.get('description', '')
                # Also check ConditionDescription
                if not description:
                    description = data.get('ConditionDescription', '')

                # If no weight in description, try to fetch from eBay API
                # This gets the full listing description where sellers often put weight
                item_id_for_desc = data.get('ItemId', '') or data.get('itemId', '')

                # Extract ItemId from ViewUrl if not directly available
                if not item_id_for_desc:
                    view_url_for_desc = data.get('ViewUrl', '') or data.get('viewUrl', '') or data.get('url', '')
                    if view_url_for_desc and '/itm/' in view_url_for_desc:
                        try:
                            item_id_for_desc = view_url_for_desc.split('/itm/')[-1].split('?')[0].split('/')[0]
                        except:
                            pass

                # Check if description has weight keywords
                desc_has_weight = description and any(w in description.lower() for w in ['gram', ' g ', 'dwt', ' oz', 'ounce', 'weight'])

                # Fetch full description from eBay if we have item_id and no weight in current description
                if item_id_for_desc and not desc_has_weight and _EBAY_POLLER_AVAILABLE:
                    try:
                        from ebay_poller import get_item_description
                        ebay_desc = await get_item_description(item_id_for_desc)
                        if ebay_desc:
                            description = ebay_desc
                            logger.info(f"[DESC] Fetched eBay description: {len(ebay_desc)} chars")
                    except Exception as e:
                        logger.debug(f"[DESC] Could not fetch eBay description: {e}")

                # Get current spot prices
                spots = _get_spot_prices()
                gold_spot = spots.get('gold_oz', 4350)
                silver_spot = spots.get('silver_oz', 75)

                if category == 'gold':
                    fast_result = _fast_extract_gold(title, price_float, description, gold_spot, item_specifics)
                else:
                    fast_result = _fast_extract_silver(title, price_float, description, silver_spot, item_specifics)

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

                    html = _render_result_html(quick_result, category, title)
                    _cache.set(title, total_price, quick_result, html, "PASS")

                    _increment_stat("pass_count", request=request)
                    logger.info(f"[FAST] Saved ALL AI time with instant PASS!")

                    if response_type == 'json':
                        quick_result["html"] = html  # Include HTML for uBuyFirst display
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

                html = _render_result_html(quick_result, category, title)
                _cache.set(title, total_price, quick_result, html, "PASS")
                _increment_stat("pass_count", request=request)

                _timing['total'] = _time.time() - _start_time
                logger.info(f"[LAZY] Saved {2 + 4:.0f}+ seconds (no images, no AI) - PASS in {_timing['total']*1000:.0f}ms")

                if response_type == 'json':
                    quick_result["html"] = html  # Include HTML for uBuyFirst display
                    return JSONResponse(content=quick_result)
                return HTMLResponse(content=html)
            elif fast_result.is_hot and fast_result.weight_source in ['title', 'stated'] and fast_result.max_buy:
                # HOT DEAL with verified weight from title - skip AI, instant BUY
                # This is a high-confidence buy based on pure math
                profit = fast_result.max_buy - price_float
                if profit >= 50:  # At least $50 profit
                    skip_ai_entirely = True
                    logger.warning(f"[FAST-BUY] SKIP AI: verified weight {fast_result.weight_grams}g, profit ${profit:.0f} - instant BUY!")

                    quick_result = {
                        'Qualify': 'Yes',
                        'Recommendation': 'BUY',
                        'reasoning': f"[FAST-BUY] Verified {fast_result.weight_grams}g {fast_result.karat}K = ${fast_result.melt_value:.0f} melt, maxBuy ${fast_result.max_buy:.0f}, profit ${profit:.0f}. {fast_result.hot_reason}",
                        'karat': f"{fast_result.karat}K" if fast_result.karat else 'Unknown',
                        'weight': f"{fast_result.weight_grams}g",
                        'weightSource': fast_result.weight_source,
                        'goldweight': str(fast_result.weight_grams),
                        'meltvalue': str(int(fast_result.melt_value)) if fast_result.melt_value else 'NA',
                        'maxBuy': str(int(fast_result.max_buy)) if fast_result.max_buy else 'NA',
                        'Profit': str(int(profit)),
                        'confidence': max(75, fast_result.confidence),  # High confidence for verified weight
                        'category': category,
                        'fastBuy': True,
                    }

                    html = _render_result_html(quick_result, category, title)
                    _cache.set(title, total_price, quick_result, html, "BUY")
                    _increment_stat("buy_count", request=request)

                    _timing['total'] = _time.time() - _start_time
                    logger.warning(f"[FAST-BUY] Instant BUY in {_timing['total']*1000:.0f}ms - profit ${profit:.0f}!")

                    if response_type == 'json':
                        quick_result["html"] = html
                        return JSONResponse(content=quick_result)
                    return HTMLResponse(content=html)
                else:
                    # Marginal profit - still skip images but let AI verify
                    needs_images_for_tier1 = False
                    logger.info(f"[LAZY] SKIP images: verified weight, marginal profit ${profit:.0f}")
            else:
                # Have verified weight from title - run Tier 1 WITHOUT images
                # Images are a LAST RESORT - only fetch for Tier 2 verification on uncertain BUYs
                needs_images_for_tier1 = False
                logger.info(f"[LAZY] SKIP images for Tier 1: verified weight {fast_result.weight_grams}g from title - AI has enough data")

        if needs_images_for_tier1 and raw_image_urls:
            _img_start = _time.time()

            # === PARALLEL OPTIMIZATION: Use prefetched images if available ===
            if _image_prefetch_task is not None:
                try:
                    # Await the prefetch task that's been running in parallel
                    images = await _image_prefetch_task
                    _timing['images'] = _time.time() - _img_start
                    logger.info(f"[PREFETCH] Using prefetched images: {len(images)} images (parallel fetch saved time)")
                except Exception as e:
                    logger.error(f"[PREFETCH] Prefetch failed, falling back to direct fetch: {e}")
                    images = []  # Fall through to direct fetch below

            # If no prefetched images (task failed or wasn't created), fetch directly
            if not images:
                # Gold/silver: Use first_last selection (scale photos often at end of eBay listings)
                # More images + larger size for better scale reading with GPT-4o
                max_imgs = getattr(_IMAGES, 'max_images_gold_silver', 5)
                img_size = getattr(_IMAGES, 'resize_for_gold_silver', 512)

                # LOAD-ADAPTIVE IMAGE FETCHING
                # Reduce image count when system is under high load (many concurrent requests)
                concurrent_requests = len(_IN_FLIGHT) if _IN_FLIGHT else 0
                if concurrent_requests > 15:
                    # Very high load - minimal images (just first+last for scale)
                    max_imgs = 2
                    img_size = 384  # Smaller size for faster processing
                    logger.warning(f"[HIGH-LOAD] {concurrent_requests} concurrent requests - reducing to {max_imgs} images @ {img_size}px")
                elif concurrent_requests > 8:
                    # High load - reduce images
                    max_imgs = 3
                    logger.info(f"[LOAD] {concurrent_requests} concurrent requests - reducing to {max_imgs} images")

                logger.info(f"[TIER1] Fetching up to {max_imgs} images for GPT-4o (gold/silver - first+last for scale photos)...")
                images = await _process_image_list(
                    raw_image_urls,
                    max_size=img_size,
                    max_count=max_imgs,
                    selection="first_last"  # Scale photos often at end of eBay listings!
                )
                _timing['images'] = _time.time() - _img_start
                logger.info(f"[TIMING] Image fetch + resize: {_timing['images']*1000:.0f}ms ({len(images)} images)")

        # Build prompt
        category_prompt = _get_category_prompt(category)
        listing_text = _format_listing_data(data)

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
                    spots = _get_spot_prices()
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
                    flatware_context += "Flatware from known makers (Dominick & Haff, Gorham, Wallace, etc.) is solid sterling.\n"

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
        # OPTIMIZATION: Pre-fetch Tier 2 images ONLY if item might need them
        # Images are LAST RESORT - only for uncertain BUYs needing visual verification
        tier2_images_task = None
        should_prefetch_images = False
        if raw_image_urls and category in ['gold', 'silver']:
            # Only pre-fetch if:
            # 1. No verified weight (AI might need to read scale photos)
            # 2. OR price is close enough that it could be a BUY (worth verifying)
            if fast_result is None or fast_result.weight_grams is None:
                should_prefetch_images = True
                logger.debug(f"[IMAGES] Pre-fetch: no verified weight - might need scale photos")
            elif fast_result.max_buy and price_float < fast_result.max_buy * 1.3:
                should_prefetch_images = True
                logger.debug(f"[IMAGES] Pre-fetch: potential BUY territory (price ${price_float:.0f} < maxBuy ${fast_result.max_buy:.0f} * 1.3)")
            else:
                logger.info(f"[IMAGES] SKIP pre-fetch: clear PASS territory (price ${price_float:.0f} >> maxBuy ${fast_result.max_buy:.0f})")

        if should_prefetch_images:
            tier2_images_task = asyncio.create_task(
                _process_image_list(raw_image_urls, max_size=_IMAGES.resize_for_tier2, selection="first_last")
            )
            logger.debug(f"[OPTIMIZATION] Pre-fetching Tier 2 images in background...")

        _tier1_start = _time.time()

        # Select model based on category
        if category in ('gold', 'silver'):
            tier1_model = _TIER1_MODEL_GOLD_SILVER
            tier1_cost = _COST_PER_CALL_GPT4O
        else:
            tier1_model = _TIER1_MODEL_DEFAULT
            tier1_cost = _COST_PER_CALL_GPT4O_MINI

        if _openai_client:
            # Check hourly budget before making OpenAI call
            if not _check_openai_budget(tier1_cost):
                logger.warning(f"[TIER1] SKIPPED due to budget limit - returning instant PASS")
                return JSONResponse(content={
                    "Recommendation": "PASS",
                    "Qualify": "No",
                    "reasoning": "Analysis skipped - hourly OpenAI budget exceeded",
                    "confidence": "Low",
                    "budget_skip": True,
                })

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
                response = await _openai_client.chat.completions.create(
                    model=tier1_model,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},  # Force JSON output
                    messages=[
                        {"role": "system", "content": _get_agent_prompt(category)},
                        *openai_messages
                    ]
                )
                raw_response = response.choices[0].message.content
                if raw_response:
                    raw_response = raw_response.strip()
                else:
                    logger.error(f"[TIER1] GPT-4o returned empty response!")
                    raw_response = '{"Recommendation": "RESEARCH", "reasoning": "Empty AI response"}'
                _add_session_cost(tier1_cost, request=request)
                _record_openai_cost(tier1_cost)  # Track hourly budget
                tier1_model_used = tier1_model.upper()
            except Exception as e:
                logger.error(f"[TIER1] {tier1_model} failed, falling back to Haiku: {e}")
                # Fallback to Haiku
                response = await _client.messages.create(
                    model=_MODEL_FAST,
                    max_tokens=500,
                    system=_get_agent_prompt(category),
                    messages=[{"role": "user", "content": message_content}]
                )
                raw_response = response.content[0].text.strip()
                _add_session_cost(_COST_PER_CALL_HAIKU, request=request)
                tier1_model_used = "Haiku (fallback)"
        else:
            # Fallback to Haiku if OpenAI client not available
            logger.info(f"[TIER1] Calling Haiku for {category} (OpenAI not configured)...")
            response = await _client.messages.create(
                model=_MODEL_FAST,
                max_tokens=500,
                system=_get_agent_prompt(category),
                messages=[{"role": "user", "content": message_content}]
            )
            raw_response = response.content[0].text.strip()
            _add_session_cost(_COST_PER_CALL_HAIKU, request=request)
            tier1_model_used = "Haiku"

        _timing['tier1'] = _time.time() - _tier1_start
        logger.info(f"[TIMING] Tier 1 ({tier1_model_used}): {_timing['tier1']*1000:.0f}ms")

        response_text = _sanitize_json_response(raw_response)

        try:
            result = json.loads(response_text)

            if 'reasoning' in result:
                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')

            # === AGENT RESPONSE VALIDATION ===
            agent_class = _get_agent(category)
            if agent_class:
                agent = agent_class()
                # Pass data to all agents for validation (high-value checks, price overrides, etc.)
                # Ensure listing price is available in data for validation
                data['_listing_price'] = total_price
                try:
                    result = agent.validate_response(result, data)
                except TypeError:
                    # Fallback for agents that don't accept data parameter
                    result = agent.validate_response(result)

            # Add listing price to result for display
            result['listingPrice'] = total_price

            # === CAPTURE TIER 1 ORIGINAL RECOMMENDATION BEFORE ANY VALIDATION ===
            tier1_original_rec = result.get('Recommendation', 'RESEARCH')
            logger.info(f"[TIER1] {tier1_model_used} original recommendation: {tier1_original_rec}")

            # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong
            _validation_start = _time.time()
            result = _validate_and_fix_margin(result, total_price, category, title, data)
            _timing['validation'] = _time.time() - _validation_start
            logger.info(f"[TIMING] Validation: {_timing['validation']*1000:.0f}ms")

            # === SILVER RESULT LOGGING ===
            if category == 'silver':
                logger.warning(f"[SILVER-RESULT] Title: {title}")
                logger.warning(f"[SILVER-RESULT] Recommendation: {result.get('Recommendation')}")
                logger.warning(f"[SILVER-RESULT] Weight: {result.get('weight', result.get('silverweight', 'NA'))}")
                logger.warning(f"[SILVER-RESULT] WeightSource: {result.get('weightSource', 'NA')}")
                logger.warning(f"[SILVER-RESULT] Melt: {result.get('meltvalue', 'NA')}")
                logger.warning(f"[SILVER-RESULT] Profit: {result.get('Profit', 'NA')}")

            # TCG/LEGO VALIDATION: Normalize keys and override with PriceCharting data if available
            if category in ["tcg", "lego"]:
                try:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    result = _validate_tcg_lego_result(result, pc_result, price_float, category, title)
                except Exception as e:
                    logger.error(f"[PC] TCG/LEGO validation error: {e}")

            # VIDEO GAMES VALIDATION: Check math and professional sellers
            if category == "videogames":
                try:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    result = _validate_videogame_result(result, pc_result, price_float, data)
                except Exception as e:
                    logger.error(f"[VG] Video game validation error: {e}")

            # ALLEN BRADLEY VALIDATION: Normalize keys to match uBuyFirst column format
            # Required columns: Qualify, Recommendation, ProductType, CatalogNumber, Series,
            # Condition, Sealed, FirmwareVersion, marketprice, maxBuy, Profit, confidence, fakerisk, reasoning
            if category == "allen_bradley":
                try:
                    result = normalize_allen_bradley_keys(result)
                    logger.debug(f"[AB] Normalized Allen Bradley result: {list(result.keys())}")
                except Exception as e:
                    logger.error(f"[AB] Allen Bradley validation error: {e}")

            # ============================================================
            # GLOBAL RESELLER DETECTION - Downgrade BUY to RESEARCH
            # Professional resellers with high feedback + store know market prices
            # ============================================================
            try:
                reseller_feedback = int(data.get('FeedbackScore', 0) or 0)
                reseller_store = data.get('StoreName', '') or ''
                reseller_name = data.get('SellerName', '') or ''

                # Rule: High feedback (>1000) + has store name = professional reseller
                is_professional_reseller = reseller_feedback > 1000 and len(reseller_store) > 0

                # Additional check: Seller name contains business keywords
                business_keywords = ['llc', 'inc', 'corp', 'trading', 'wholesale', 'liquidat', 'retail', 'outlet', 'store', 'shop', 'emporium', 'exchange', 'depot', 'warehouse']
                has_business_name = any(kw in reseller_name.lower() for kw in business_keywords)

                # Also flag if feedback > 5000 (definitely professional regardless of store)
                is_mega_seller = reseller_feedback > 5000

                if (is_professional_reseller or has_business_name or is_mega_seller) and result.get('Recommendation') == 'BUY':
                    result['Recommendation'] = 'RESEARCH'
                    result['Qualify'] = 'Maybe'
                    reason_parts = []
                    if is_mega_seller:
                        reason_parts.append(f"mega-seller ({reseller_feedback} feedback)")
                    elif is_professional_reseller:
                        reason_parts.append(f"professional reseller ({reseller_feedback} feedback + store)")
                    if has_business_name:
                        reason_parts.append(f"business name detected")

                    result['reasoning'] = result.get('reasoning', '') + f" | RESELLER CHECK: {', '.join(reason_parts)} - verify pricing manually"
                    logger.warning(f"[RESELLER] BUY->RESEARCH: {reseller_name} ({reseller_feedback} feedback, store: {reseller_store[:20] if reseller_store else 'N/A'})")
            except Exception as e:
                logger.debug(f"[RESELLER] Check error: {e}")

            # ============================================================
            # GLOBAL JUNK LOT FILTER - Downgrade BUY to RESEARCH
            # Bulk/mystery lots often have inflated claims, require manual review
            # ============================================================
            try:
                junk_title = data.get('Title', '').lower().replace('+', ' ')

                # Keywords that indicate bulk/mystery lots
                junk_lot_keywords = [
                    'mystery', 'grab bag', 'junk drawer', 'destash', 'random lot',
                    'assorted lot', 'mixed lot', 'unsorted', 'untested lot',
                    'as is lot', 'wholesale lot', 'reseller lot', 'flea market'
                ]

                # Bulk quantity patterns (careful - "lot" alone is too broad)
                bulk_patterns = [
                    'bulk lot', 'huge lot', 'large lot', 'massive lot', 'mega lot',
                    'pound lot', 'lb lot', 'lbs lot', 'pounds of', 'kilo lot'
                ]

                has_junk_keyword = any(kw in junk_title for kw in junk_lot_keywords)
                has_bulk_pattern = any(bp in junk_title for bp in bulk_patterns)

                # Check for quantity patterns like "50 pieces" or "100+ items"
                import re
                qty_match = re.search(r'\b(\d{2,})\s*(pieces?|items?|rings?|chains?|bracelets?)\b', junk_title)
                has_high_quantity = qty_match and int(qty_match.group(1)) >= 20

                is_junk_lot = has_junk_keyword or has_bulk_pattern or has_high_quantity

                if is_junk_lot and result.get('Recommendation') == 'BUY':
                    result['Recommendation'] = 'RESEARCH'
                    result['Qualify'] = 'Maybe'

                    lot_reason = []
                    if has_junk_keyword:
                        lot_reason.append("mystery/junk keywords")
                    if has_bulk_pattern:
                        lot_reason.append("bulk lot pattern")
                    if has_high_quantity:
                        lot_reason.append(f"high quantity ({qty_match.group(0)})")

                    result['reasoning'] = result.get('reasoning', '') + f" | JUNK LOT: {', '.join(lot_reason)} - verify contents manually"
                    logger.warning(f"[JUNK LOT] BUY->RESEARCH: {', '.join(lot_reason)}")
            except Exception as e:
                logger.debug(f"[JUNK LOT] Check error: {e}")

            # ============================================================
            # GLOBAL PRICE/WEIGHT SANITY CHECK - Flag impossible pricing
            # Catches listings where price is too high relative to claimed weight
            # ============================================================
            try:
                if category in ['gold', 'silver'] and result.get('Recommendation') == 'BUY':
                    # Get claimed weight
                    claimed_weight = 0
                    weight_str = result.get('weight', '') or result.get('goldweight', '') or result.get('silverweight', '') or '0'
                    try:
                        claimed_weight = float(str(weight_str).replace('g', '').replace('gram', '').replace('dwt', '').strip() or 0)
                    except:
                        pass

                    # Get listing price
                    sanity_price = 0
                    try:
                        sanity_price = float(str(total_price).replace('$', '').replace(',', '') or 0)
                    except:
                        pass

                    # Price per gram sanity check
                    # Gold spot ~$65/g for 14K, Silver ~$0.90/g
                    # If someone is paying MORE than spot for scrap, something is wrong
                    if claimed_weight > 0 and sanity_price > 0:
                        price_per_gram = sanity_price / claimed_weight

                        # Gold: >$100/gram is suspicious (even 24K is ~$90/g)
                        # Silver: >$5/gram is suspicious (spot is ~$0.90/g)
                        is_gold = category == 'gold' or 'gold' in result.get('Alias', '').lower()
                        is_silver = category == 'silver' or 'silver' in result.get('Alias', '').lower()

                        max_reasonable_ppg = 100 if is_gold else 5  # $/gram thresholds

                        if price_per_gram > max_reasonable_ppg:
                            result['Recommendation'] = 'RESEARCH'
                            result['Qualify'] = 'Maybe'
                            result['reasoning'] = result.get('reasoning', '') + f" | PRICE SANITY: ${price_per_gram:.2f}/gram exceeds max reasonable ${max_reasonable_ppg}/g - verify weight claim"
                            logger.warning(f"[PRICE SANITY] BUY->RESEARCH: ${price_per_gram:.2f}/gram for {claimed_weight}g at ${sanity_price}")

                    # Also check: If weight is very high but price is very low = probably wrong weight
                    # e.g., 50 grams of 14K gold should be worth ~$3000+ in melt
                    if claimed_weight >= 30 and sanity_price < 200:
                        result['Recommendation'] = 'RESEARCH'
                        result['Qualify'] = 'Maybe'
                        result['reasoning'] = result.get('reasoning', '') + f" | WEIGHT SANITY: {claimed_weight}g claimed but only ${sanity_price} - weight likely wrong"
                        logger.warning(f"[WEIGHT SANITY] BUY->RESEARCH: {claimed_weight}g at ${sanity_price} - mismatch")

            except Exception as e:
                logger.debug(f"[SANITY] Check error: {e}")

            # ============================================================
            # OPPORTUNITY DETECTION - Flag likely mispriced items
            # These signals indicate seller may not know item's value
            # ============================================================
            opportunity_signals = []
            opportunity_score = 0

            try:
                opp_title = data.get('Title', '').replace('+', ' ')
                opp_description = data.get('Description', '') or ''
                opp_price = float(str(total_price).replace('$', '').replace(',', '') or 0)

                # ---------------------------------------------------------
                # 1. ROUND NUMBER PRICING - Gut feeling, not calculated
                # Dealers price at $73.47; casual sellers price at $75
                # ---------------------------------------------------------
                round_numbers = [10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100, 125, 150, 175, 200, 250, 300, 400, 500, 750, 1000]
                is_round_price = opp_price in round_numbers or (opp_price > 0 and opp_price % 50 == 0)

                if is_round_price and opp_price >= 20:
                    opportunity_signals.append(f"round pricing (${opp_price})")
                    opportunity_score += 15
                    logger.debug(f"[OPPORTUNITY] Round price detected: ${opp_price}")

                # ---------------------------------------------------------
                # 2. IGNORANCE LANGUAGE - Seller admits they don't know value
                # ---------------------------------------------------------
                ignorance_phrases = [
                    "don't know", "dont know", "not sure", "unsure",
                    "no idea", "can't tell", "cant tell", "might be",
                    "could be real", "could be fake", "possibly",
                    "inherited", "estate", "grandma", "grandmother", "grandfather",
                    "passed away", "attic", "basement find", "storage unit",
                    "found this", "found these", "cleaning out", "downsizing",
                    "not my area", "don't collect", "dont collect",
                    "i think it's", "i believe", "appears to be",
                    "untested", "haven't tested", "as found", "as-found"
                ]

                check_text = (opp_title + ' ' + opp_description).lower()
                found_phrases = [phrase for phrase in ignorance_phrases if phrase in check_text]

                if found_phrases:
                    opportunity_signals.append(f"ignorance language ({found_phrases[0]})")
                    opportunity_score += 20 * min(len(found_phrases), 3)  # Cap at 3 matches
                    logger.debug(f"[OPPORTUNITY] Ignorance phrases: {found_phrases[:3]}")

                # ---------------------------------------------------------
                # 3. TITLE EFFICIENCY - Casual sellers don't optimize titles
                # eBay allows 80 chars; dealers use most of it
                # ---------------------------------------------------------
                title_len = len(opp_title.strip())
                max_title = 80
                title_efficiency = (title_len / max_title) * 100

                # Very short title (<40%) = casual seller
                if title_efficiency < 40 and opp_price >= 50:
                    opportunity_signals.append(f"short title ({title_len} chars)")
                    opportunity_score += 15
                    logger.debug(f"[OPPORTUNITY] Short title: {title_len}/{max_title} chars")

                # ---------------------------------------------------------
                # 4. DESCRIPTION LENGTH - Dealers write novels
                # ---------------------------------------------------------
                desc_len = len(opp_description.strip())

                # Very short or no description on item worth $50+ = opportunity
                if desc_len < 100 and opp_price >= 50:
                    opportunity_signals.append(f"minimal description ({desc_len} chars)")
                    opportunity_score += 10
                    logger.debug(f"[OPPORTUNITY] Short description: {desc_len} chars")

                # ---------------------------------------------------------
                # 5. LOW FEEDBACK + HIGH VALUE - First-timer with treasure
                # ---------------------------------------------------------
                opp_feedback = int(data.get('FeedbackScore', 0) or 0)

                if opp_feedback < 50 and opp_price >= 100:
                    opportunity_signals.append(f"low feedback seller ({opp_feedback})")
                    opportunity_score += 20
                    logger.debug(f"[OPPORTUNITY] Low feedback: {opp_feedback}")
                elif opp_feedback < 100 and opp_price >= 200:
                    opportunity_signals.append(f"newer seller ({opp_feedback} feedback)")
                    opportunity_score += 10

                # ---------------------------------------------------------
                # 6. BEST OFFER AVAILABLE - Can negotiate even lower
                # ---------------------------------------------------------
                has_best_offer = data.get('BestOfferEnabled', False) or 'best offer' in check_text

                if has_best_offer:
                    opportunity_signals.append("accepts offers")
                    opportunity_score += 10
                    logger.debug(f"[OPPORTUNITY] Best offer enabled")

                # ---------------------------------------------------------
                # 7. PREMIUM BRAND DETECTION - High-value brands from missed data
                # Based on analysis of fast-selling missed items
                # ---------------------------------------------------------
                brand_title = opp_title.lower()

                # Designer jewelry brands (frequently missed, sell fast)
                designer_jewelry = [
                    ('david yurman', 30), ('tiffany', 25), ('john hardy', 25),
                    ('pandora', 15), ('lagos', 20), ('konstantino', 20),
                    ('james avery', 15), ('kendra scott', 10)
                ]

                # Premium watch brands
                premium_watches = [
                    ('rolex', 35), ('patek', 35), ('omega', 25), ('cartier', 30),
                    ('tudor', 25), ('breitling', 20), ('iwc', 25), ('panerai', 20),
                    ('girard perregaux', 25), ('jaeger', 25), ('vacheron', 30),
                    ('audemars', 30), ('grand seiko', 20), ('king seiko', 20)
                ]

                # Collectible knife brands (Case XX, Benchmade frequently missed)
                knife_brands = [
                    ('case xx', 20), ('benchmade', 20), ('chris reeve', 25),
                    ('spyderco', 15), ('microtech', 20), ('hinderer', 25),
                    ('strider', 25), ('william henry', 20)
                ]

                # TCG/Graded cards (PSA 10 frequently missed)
                tcg_grades = [
                    ('psa 10', 25), ('psa 9', 15), ('bgs 10', 25), ('bgs 9.5', 20),
                    ('cgc 10', 20), ('cgc 9.5', 15)
                ]

                # Pokemon specific (high value cards)
                pokemon_cards = [
                    ('charizard', 25), ('1st edition', 20), ('shadowless', 25),
                    ('gold star', 20), ('alt art', 15), ('illustration rare', 15)
                ]

                # Sports cards (rookies and autos)
                sports_cards = [
                    ('rookie auto', 20), ('rc auto', 20), ('1/1', 30),
                    ('printing plate', 20), ('superfractor', 25)
                ]

                # Check all brand categories
                all_brands = designer_jewelry + premium_watches + knife_brands + tcg_grades + pokemon_cards + sports_cards
                matched_brands = []

                for brand, points in all_brands:
                    if brand in brand_title:
                        matched_brands.append((brand, points))

                if matched_brands:
                    # Take top 2 brand matches
                    matched_brands.sort(key=lambda x: -x[1])
                    for brand, points in matched_brands[:2]:
                        opportunity_signals.append(f"premium brand ({brand})")
                        opportunity_score += points
                        logger.debug(f"[OPPORTUNITY] Premium brand: {brand} (+{points}pts)")

                # ---------------------------------------------------------
                # 8. HOT SELLER DETECTION - Sellers with history of fast sales
                # ---------------------------------------------------------
                try:
                    seller_name_check = data.get('SellerName', '') or data.get('sellerId', '') or ''
                    if seller_name_check:
                        seller_signal = item_tracking.get_seller_signal(seller_name_check)
                        if seller_signal:
                            fast_sales = seller_signal.get('fast_sales', 0)
                            signal_type = seller_signal.get('signal_type', '')

                            if fast_sales >= 3 or signal_type == 'collection_dump':
                                opportunity_signals.append(f"hot seller ({fast_sales} fast sales)")
                                opportunity_score += 25
                                logger.info(f"[OPPORTUNITY] Hot seller detected: {seller_name_check} ({fast_sales} fast sales)")
                            elif fast_sales >= 2:
                                opportunity_signals.append(f"active seller ({fast_sales} fast sales)")
                                opportunity_score += 15
                except Exception as e:
                    logger.debug(f"[OPPORTUNITY] Seller signal check error: {e}")

                # ---------------------------------------------------------
                # APPLY OPPORTUNITY BOOST
                # ---------------------------------------------------------
                if opportunity_score >= 30:
                    result['opportunity_score'] = opportunity_score
                    result['opportunity_signals'] = opportunity_signals

                    # Add to reasoning
                    signal_text = ', '.join(opportunity_signals[:4])
                    result['reasoning'] = f"🎯 OPPORTUNITY ({opportunity_score}pts): {signal_text} | " + result.get('reasoning', '')

                    # Upgrade RESEARCH to BUY if score is high enough AND profit looks good
                    current_rec = result.get('Recommendation', 'RESEARCH')
                    profit_str = result.get('Profit', result.get('Margin', '0'))
                    try:
                        profit_val = float(str(profit_str).replace('$', '').replace('+', '').replace(',', '').replace('NA', '0'))
                    except:
                        profit_val = 0

                    if current_rec == 'RESEARCH' and opportunity_score >= 50 and profit_val >= 20:
                        result['Recommendation'] = 'BUY'
                        result['Qualify'] = 'Yes'
                        result['reasoning'] = f"⬆️ UPGRADED: High opportunity score + profit | " + result.get('reasoning', '')
                        logger.info(f"[OPPORTUNITY] RESEARCH->BUY: score={opportunity_score}, profit=${profit_val}")

                    logger.info(f"[OPPORTUNITY] Score {opportunity_score}: {signal_text}")

            except Exception as e:
                logger.debug(f"[OPPORTUNITY] Detection error: {e}")

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
                _TIER2_ENABLED and
                (tier1_original_rec in ("BUY", "RESEARCH") or recommendation in ("BUY", "RESEARCH") or force_tier2_for_na_weight)
            )

            # Skip Tier 2 for HOT deals if configured (math is verified)
            if is_hot_deal and _SKIP_TIER2_FOR_HOT:
                logger.info(f"[TIER2] HOT DEAL - Skipping Tier 2 (verified math from title)")
                should_run_tier2 = False
                # Add HOT flag to result
                result['hot_deal'] = True
                result['reasoning'] = f"HOT DEAL (verified): {fast_result.hot_reason}\n" + result.get('reasoning', '')

            logger.info(f"[TIER2] Check: TIER2_ENABLED={_TIER2_ENABLED}, parallel={_PARALLEL_MODE}, haiku={tier1_original_rec}, hot={is_hot_deal}, should_run={should_run_tier2}")

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
                asyncio.create_task(_background_sonnet_verify(
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
                    logger.info(f"[OPTIMIZATION] Using pre-fetched images: {len(images)} images @ {_IMAGES.resize_for_tier2}px")
                elif raw_image_urls:
                    logger.info(f"[TIER2] Fetching images using first_last strategy (first 3 + last 3 of {len(raw_image_urls)} total)...")
                    # Use first_last selection: first 3 + last 3 images (scale photos often at end)
                    images = await _process_image_list(raw_image_urls, max_size=_IMAGES.resize_for_tier2, selection="first_last")
                    logger.info(f"[TIER2] Fetched {len(images)} images @ {_IMAGES.resize_for_tier2}px")

                _timing['images'] = _time.time() - _img_start
                logger.info(f"[TIMING] Image fetch (for Tier2): {_timing['images']*1000:.0f}ms")

                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                _tier2_start = _time.time()

                # Use OpenAI or Claude based on config
                if _TIER2_PROVIDER == "openai" and _openai_client:
                    logger.info(f"[TIER2] Using OpenAI {_OPENAI_TIER2_MODEL} for FAST verification...")
                    result = await _tier2_reanalyze_openai(
                        title=title,
                        price=price_float,
                        category=category,
                        tier1_result=result,
                        images=images,
                        data=data,
                        system_prompt=_get_agent_prompt(category)
                    )
                    _timing['tier2'] = _time.time() - _tier2_start
                    logger.info(f"[TIMING] Tier 2 OpenAI: {_timing['tier2']*1000:.0f}ms")
                else:
                    result = await _tier2_reanalyze(
                        title=title,
                        price=price_float,
                        category=category,
                        tier1_result=result,
                        images=images,
                        data=data,
                        system_prompt=_get_agent_prompt(category)
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

            # ============================================================
            # HIGH-VALUE ITEM ESCALATION
            # Items over $1000 that got PASS might be opportunities if priced below market
            # Force RESEARCH for manual verification
            # ============================================================
            try:
                price_val = float(str(total_price).replace('$', '').replace(',', ''))
                if recommendation == "PASS" and price_val >= 1000:
                    # High-value PASS - escalate to RESEARCH
                    recommendation = "RESEARCH"
                    result['Recommendation'] = "RESEARCH"
                    result['Qualify'] = "Maybe"
                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER: High-value item (${price_val:.0f}) - AI said PASS but verify if priced below market"
                    logger.info(f"[HIGH-VALUE] PASS->RESEARCH for ${price_val:.0f} item")
            except:
                pass

            # Update stats
            if recommendation == "BUY":
                _increment_stat("buy_count", request=request)
            elif recommendation == "PASS":
                _increment_stat("pass_count", request=request)
            else:
                _increment_stat("research_count", request=request)

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

            _get_stats_dict(request)["listings"][listing_id] = listing_record
            _trim_listings()

            # Save to database
            _save_listing(listing_record)

            # Broadcast to live dashboard via WebSocket
            try:
                await _broadcast_new_listing(
                    listing={"title": title, "price": total_price, "category": category},
                    analysis=result
                )
                logger.debug(f"[WS] Broadcasted listing to live dashboard")
            except Exception as e:
                logger.debug(f"[WS] Broadcast error (no clients?): {e}")

            # Update pattern analytics with margin and confidence
            margin_val = result.get('Profit', result.get('Margin', '0'))
            conf_val = result.get('confidence', '')
            _update_pattern_outcome(title, category, recommendation, margin_val, conf_val, alias)

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
            html = _render_result_html(result, category, title)

            # Store in smart cache
            _cache.set(title, total_price, result, html, recommendation, category)

            # Signal completion to any waiting requests
            request_key = f"{title}|{total_price}"
            if request_key in _IN_FLIGHT:
                _IN_FLIGHT_RESULTS[request_key] = (result, html)
                _IN_FLIGHT[request_key].set()
                logger.info(f"[IN-FLIGHT] Signaled completion for waiting requests")

                # Clean up after a delay (let waiting requests grab the result)
                async def cleanup_in_flight(key):
                    await asyncio.sleep(5)
                    _IN_FLIGHT.pop(key, None)
                    _IN_FLIGHT_RESULTS.pop(key, None)
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
                        ebay_item_url = unquote(ebay_item_url.replace('+', ' '))
                        logger.info(f"[EBAY] Using ViewUrl from data: {ebay_item_url[:80]}...")

                    # Fallback: Try seller-based eBay API lookup (most accurate for uBuyFirst)
                    if not ebay_item_url:
                        seller_name_for_lookup = data.get('SellerName', data.get('SellerUserID', ''))
                        if seller_name_for_lookup:
                            logger.info(f"[EBAY] Attempting seller-based lookup for '{seller_name_for_lookup}'...")
                            ebay_item_url = await _lookup_ebay_item_by_seller(title, seller_name_for_lookup, list_price)

                    # Fallback: Try title-only eBay API lookup
                    if not ebay_item_url:
                        ebay_item_url = await _lookup_ebay_item(title, list_price)

                    # Final fallback to search URL
                    if not ebay_item_url:
                        ebay_item_url = _get_ebay_search_url(title)
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
                    asyncio.create_task(_send_discord_alert(
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
            # (karat + premium stones + high price + possible scale photo + heavy indicators)
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

                    # Check for HEAVY GOLD indicators - items that may be large/valuable
                    heavy_gold_indicators = [
                        'signet', 'shield', 'chunky', 'thick', 'heavy', 'massive', 'wide band',
                        'solid', 'substantial', 'large', 'big', 'oversized', 'mens ring',
                        "men's ring", 'class ring', 'college ring', 'championship', 'nugget',
                        'cuban', 'miami cuban', 'rope chain', 'franco', 'herringbone',
                        'byzantine', 'figaro', 'mariner', 'anchor', 'tennis bracelet',
                        'bangle', 'cuff', 'id bracelet', 'vintage', 'antique', 'estate'
                    ]
                    has_heavy_indicator = any(indicator in title_lower for indicator in heavy_gold_indicators)

                    # If price > $300 AND has karat AND (has premium stones OR has scale hints OR heavy indicator), force RESEARCH
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
                    elif price_val > 300 and has_karat and (has_premium or has_scale_hint or has_scale_in_desc or has_heavy_indicator) and not is_lab_diamond:
                        logger.warning(f"[HIGH-VALUE GOLD] Forcing RESEARCH: ${price_val:.0f}, karat={has_karat}, premium={has_premium}, scale_hint={has_scale_hint or has_scale_in_desc}, heavy={has_heavy_indicator}")
                        result['Recommendation'] = 'RESEARCH'
                        result['Qualify'] = 'Maybe'
                        original_reasoning = result.get('reasoning', '')
                        override_reason = "heavy gold indicator" if has_heavy_indicator else "premium indicators"
                        result['reasoning'] = f"[HIGH-VALUE GOLD OVERRIDE] Price ${price_val:.0f} with karat + {override_reason} - needs manual weight verification. Original: {original_reasoning}"
                        result['tier2_override'] = True
                        result['tier2_reason'] = 'High-value gold jewelry flagged for manual review'
                        # Re-render HTML with updated result
                        html = _render_result_html(result, category, title)
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
                        html = _render_result_html(result, category, title)
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
            _mark_as_evaluated(title, total_price, result)

            # Update item tracking with recommendation
            if item_id and result.get('Recommendation'):
                try:
                    item_tracking.update_item_recommendation(item_id, result['Recommendation'])
                except Exception as e:
                    logger.warning(f"[TRACKING] Error updating recommendation: {e}")

            # Log patterns for learning - especially important for newer categories
            # Log: all BUYs, all RESEARCH, and PASS for categories we're still learning
            recommendation = result.get('Recommendation', 'PASS')
            try:
                price_for_logging = float(str(total_price).replace('$', '').replace(',', ''))
            except:
                price_for_logging = 0
            should_log_pattern = (
                recommendation == 'BUY' or
                recommendation == 'RESEARCH' or
                # Log PASS for newer/learning categories
                category in ['lego', 'tcg', 'pokemon', 'costume', 'videogames'] or
                # Log PASS for high-value items we might be missing
                (recommendation == 'PASS' and price_for_logging >= 100 and category in ['gold', 'silver'])
            )
            if should_log_pattern:
                try:
                    item_tracking.log_pattern(
                        pattern_type=recommendation,
                        category=category,
                        title=title,
                        price=price_for_logging,
                        result=result,
                        data=data
                    )
                except Exception as e:
                    logger.warning(f"[PATTERN] Error logging pattern: {e}")

            # ============================================================
            # STORE FULL ANALYSIS RESULT FOR MISSED OPPORTUNITY TRACKING
            # This captures everything needed to analyze why we passed
            # ============================================================
            if item_id:
                try:
                    item_tracking.store_analysis_result(
                        item_id=item_id,
                        result=result,
                        data=data
                    )
                except Exception as e:
                    logger.debug(f"[TRACKING] Error storing analysis result: {e}")

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
