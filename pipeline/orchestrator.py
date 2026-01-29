"""
Pipeline Orchestrator - Main analysis logic

Coordinates the full analysis pipeline:
  request parsing -> pre-checks -> category detection -> fast extraction ->
  Tier 1 AI -> validation -> Tier 2 verification -> discord -> response

All dependencies are injected via configure_orchestrator().
Called by the thin route handler in routes/analysis.py.
"""

import re
import json
import asyncio
import logging
import time as _time
import traceback
from typing import Dict, Any, Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

# Pipeline modules (relative imports within the pipeline package)
from .request_parser import parse_analysis_request, extract_listing_fields, log_request_fields
from .pre_checks import (
    check_spam, check_dedup, check_sold, check_disabled,
    check_queue_mode, check_cache, check_in_flight,
)
from .listing_enrichment import build_enhancements, log_race_item as pipeline_log_race_item
from .fast_pass import (
    check_user_price_db, check_pc_quick_pass, check_agent_quick_pass,
    check_textbook, check_gold_price_per_gram, check_fast_extract_pass,
)
from .response_builder import finalize_result
from .tier2 import (
    background_sonnet_verify,
    tier2_reanalyze,
    tier2_reanalyze_openai,
)

logger = logging.getLogger(__name__)


# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_orchestrator)
# ============================================================

# API Clients
_client = None  # Anthropic client
_openai_client = None  # OpenAI client

# State
_STATS = None
_cache = None
_IN_FLIGHT = None
_IN_FLIGHT_RESULTS = None
_IN_FLIGHT_LOCK = None
_ENABLED = None
_QUEUE_MODE = None
_LISTING_QUEUE = None

# Model config
_TIER1_MODEL_GOLD_SILVER = None
_TIER1_MODEL_DEFAULT = None
_MODEL_FAST = None
_TIER2_ENABLED = None
_TIER2_PROVIDER = None
_OPENAI_TIER2_MODEL = None
_PARALLEL_MODE = None
_SKIP_TIER2_FOR_HOT = None

# Cost constants
_COST_PER_CALL_HAIKU = None
_COST_PER_CALL_GPT4O = None
_COST_PER_CALL_GPT4O_MINI = None

# Thresholds and config objects
_CATEGORY_THRESHOLDS = None
_IMAGES = None

# Feature flags
_FAST_EXTRACT_AVAILABLE = False
_EBAY_POLLER_AVAILABLE = False

# Injected functions
_check_seller_spam = None
_analyze_new_seller = None
_check_price_correction = None
_detect_category = None
_get_agent = None
_get_agent_prompt = None
_get_category_prompt = None
_check_instant_pass = None
_get_pricecharting_context = None
_check_price_override = None
_validate_and_fix_margin = None
_validate_tcg_lego_result = None
_validate_videogame_result = None
_fast_extract_gold = None
_fast_extract_silver = None
_get_spot_prices = None
_process_image_list = None
_format_listing_data = None
_sanitize_json_response = None
_render_result_html = None
_render_queued_html = None
_send_discord_alert = None
_lookup_ebay_item = None
_lookup_ebay_item_by_seller = None
_get_ebay_search_url = None
_save_listing = None
_log_incoming_listing = None
_update_pattern_outcome = None
_broadcast_new_listing = None
_check_openai_budget = None
_record_openai_cost = None
_log_race_item = None
_log_listing_received = None
_race_log_ubf_item = None
_lookup_user_price = None


def configure_orchestrator(
    # API Clients
    client=None,
    openai_client=None,
    # State
    STATS=None,
    cache=None,
    IN_FLIGHT=None,
    IN_FLIGHT_RESULTS=None,
    IN_FLIGHT_LOCK=None,
    ENABLED=None,
    QUEUE_MODE=None,
    LISTING_QUEUE=None,
    # Model config
    TIER1_MODEL_GOLD_SILVER=None,
    TIER1_MODEL_DEFAULT=None,
    MODEL_FAST=None,
    TIER2_ENABLED=None,
    TIER2_PROVIDER=None,
    OPENAI_TIER2_MODEL=None,
    PARALLEL_MODE=None,
    SKIP_TIER2_FOR_HOT=None,
    # Cost constants
    COST_PER_CALL_HAIKU=None,
    COST_PER_CALL_GPT4O=None,
    COST_PER_CALL_GPT4O_MINI=None,
    # Config objects
    CATEGORY_THRESHOLDS=None,
    IMAGES=None,
    # Feature flags
    FAST_EXTRACT_AVAILABLE=False,
    EBAY_POLLER_AVAILABLE=False,
    # Injected functions
    check_seller_spam=None,
    analyze_new_seller=None,
    check_price_correction_fn=None,
    detect_category=None,
    get_agent=None,
    get_agent_prompt=None,
    get_category_prompt=None,
    check_instant_pass=None,
    get_pricecharting_context=None,
    check_price_override=None,
    validate_and_fix_margin=None,
    validate_tcg_lego_result=None,
    validate_videogame_result=None,
    fast_extract_gold=None,
    fast_extract_silver=None,
    get_spot_prices=None,
    process_image_list=None,
    format_listing_data=None,
    sanitize_json_response=None,
    render_result_html=None,
    render_queued_html=None,
    send_discord_alert=None,
    lookup_ebay_item=None,
    lookup_ebay_item_by_seller=None,
    get_ebay_search_url=None,
    save_listing=None,
    log_incoming_listing=None,
    update_pattern_outcome=None,
    broadcast_new_listing=None,
    check_openai_budget=None,
    record_openai_cost=None,
    log_race_item_fn=None,
    log_listing_received=None,
    race_log_ubf_item=None,
    lookup_user_price=None,
):
    """Inject all dependencies from main.py into the orchestrator module."""
    global _client, _openai_client, _STATS, _cache, _IN_FLIGHT, _IN_FLIGHT_RESULTS
    global _IN_FLIGHT_LOCK, _ENABLED, _QUEUE_MODE, _LISTING_QUEUE
    global _TIER1_MODEL_GOLD_SILVER, _TIER1_MODEL_DEFAULT, _MODEL_FAST
    global _TIER2_ENABLED, _TIER2_PROVIDER, _OPENAI_TIER2_MODEL
    global _PARALLEL_MODE, _SKIP_TIER2_FOR_HOT
    global _COST_PER_CALL_HAIKU, _COST_PER_CALL_GPT4O, _COST_PER_CALL_GPT4O_MINI
    global _CATEGORY_THRESHOLDS, _IMAGES
    global _FAST_EXTRACT_AVAILABLE, _EBAY_POLLER_AVAILABLE
    global _check_seller_spam, _analyze_new_seller, _check_price_correction
    global _detect_category, _get_agent, _get_agent_prompt, _get_category_prompt
    global _check_instant_pass, _get_pricecharting_context, _check_price_override
    global _validate_and_fix_margin, _validate_tcg_lego_result, _validate_videogame_result
    global _fast_extract_gold, _fast_extract_silver, _get_spot_prices
    global _process_image_list, _format_listing_data, _sanitize_json_response
    global _render_result_html, _render_queued_html
    global _send_discord_alert, _lookup_ebay_item, _lookup_ebay_item_by_seller
    global _get_ebay_search_url, _save_listing, _log_incoming_listing
    global _update_pattern_outcome, _broadcast_new_listing
    global _check_openai_budget, _record_openai_cost
    global _log_race_item, _log_listing_received, _race_log_ubf_item
    global _lookup_user_price

    _client = client
    _openai_client = openai_client
    _STATS = STATS
    _cache = cache
    _IN_FLIGHT = IN_FLIGHT
    _IN_FLIGHT_RESULTS = IN_FLIGHT_RESULTS
    _IN_FLIGHT_LOCK = IN_FLIGHT_LOCK
    _ENABLED = ENABLED
    _QUEUE_MODE = QUEUE_MODE
    _LISTING_QUEUE = LISTING_QUEUE
    _TIER1_MODEL_GOLD_SILVER = TIER1_MODEL_GOLD_SILVER
    _TIER1_MODEL_DEFAULT = TIER1_MODEL_DEFAULT
    _MODEL_FAST = MODEL_FAST
    _TIER2_ENABLED = TIER2_ENABLED
    _TIER2_PROVIDER = TIER2_PROVIDER
    _OPENAI_TIER2_MODEL = OPENAI_TIER2_MODEL
    _PARALLEL_MODE = PARALLEL_MODE
    _SKIP_TIER2_FOR_HOT = SKIP_TIER2_FOR_HOT
    _COST_PER_CALL_HAIKU = COST_PER_CALL_HAIKU
    _COST_PER_CALL_GPT4O = COST_PER_CALL_GPT4O
    _COST_PER_CALL_GPT4O_MINI = COST_PER_CALL_GPT4O_MINI
    _CATEGORY_THRESHOLDS = CATEGORY_THRESHOLDS
    _IMAGES = IMAGES
    _FAST_EXTRACT_AVAILABLE = FAST_EXTRACT_AVAILABLE
    _EBAY_POLLER_AVAILABLE = EBAY_POLLER_AVAILABLE
    _check_seller_spam = check_seller_spam
    _analyze_new_seller = analyze_new_seller
    _check_price_correction = check_price_correction_fn
    _detect_category = detect_category
    _get_agent = get_agent
    _get_agent_prompt = get_agent_prompt
    _get_category_prompt = get_category_prompt
    _check_instant_pass = check_instant_pass
    _get_pricecharting_context = get_pricecharting_context
    _check_price_override = check_price_override
    _validate_and_fix_margin = validate_and_fix_margin
    _validate_tcg_lego_result = validate_tcg_lego_result
    _validate_videogame_result = validate_videogame_result
    _fast_extract_gold = fast_extract_gold
    _fast_extract_silver = fast_extract_silver
    _get_spot_prices = get_spot_prices
    _process_image_list = process_image_list
    _format_listing_data = format_listing_data
    _sanitize_json_response = sanitize_json_response
    _render_result_html = render_result_html
    _render_queued_html = render_queued_html
    _send_discord_alert = send_discord_alert
    _lookup_ebay_item = lookup_ebay_item
    _lookup_ebay_item_by_seller = lookup_ebay_item_by_seller
    _get_ebay_search_url = get_ebay_search_url
    _save_listing = save_listing
    _log_incoming_listing = log_incoming_listing
    _update_pattern_outcome = update_pattern_outcome
    _broadcast_new_listing = broadcast_new_listing
    _check_openai_budget = check_openai_budget
    _record_openai_cost = record_openai_cost
    _log_race_item = log_race_item_fn
    _log_listing_received = log_listing_received
    _race_log_ubf_item = race_log_ubf_item
    _lookup_user_price = lookup_user_price

    logger.info("[ORCHESTRATOR] Configured with all dependencies")


def _trim_listings():
    """Keep only last 100 listings in memory"""
    if len(_STATS["listings"]) > 100:
        sorted_ids = sorted(_STATS["listings"].keys(), key=lambda x: _STATS["listings"][x]["timestamp"])
        for old_id in sorted_ids[:-100]:
            del _STATS["listings"][old_id]


# ============================================================
# MAIN ANALYSIS FUNCTION
# ============================================================

async def run_analysis(request: Request):
    """Main analysis - processes eBay listings through AI pipeline.

    This is the full analyze_listing function moved from main.py.
    Called by the thin route handler in routes/analysis.py.
    """
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
        # SPAM + DEDUP CHECKS
        # ============================================================
        spam_response = check_spam(data, _check_seller_spam)
        if spam_response:
            return spam_response
        dedup_response = check_dedup(title, total_price)
        if dedup_response:
            return dedup_response

        # PRICE CORRECTIONS - Check user's logged market prices
        user_price_correction = None
        if _check_price_correction:
            try:
                user_price_correction = _check_price_correction(title)
                if user_price_correction:
                    logger.info(f"[PRICE CHECK] Found user correction: '{user_price_correction['keywords']}' -> ${user_price_correction['market_price']}")
            except Exception as e:
                logger.warning(f"[PRICE CHECK] Error checking corrections: {e}")

        # Log request fields for profiling
        log_request_fields(data)

        # ============================================================
        # LISTING ENHANCEMENTS
        # ============================================================
        sold_response = check_sold(data)
        if sold_response:
            return sold_response
        listing_enhancements = build_enhancements(data, _analyze_new_seller)
        freshness_minutes = listing_enhancements.get("freshness_minutes")
        seller_name = listing_enhancements.get("seller_name", "")

        # ============================================================
        # Race comparison logging
        pipeline_log_race_item(
            data, title, total_price, item_id, freshness_minutes, seller_name,
            _log_race_item, _log_listing_received, _race_log_ubf_item
        )

        # Start timing for performance analysis
        _start_time = _time.time()
        _timing = {}

        _STATS["total_requests"] += 1

        # ============================================================
        # SMART CACHE CHECK
        # ============================================================
        cache_response = check_cache(title, total_price, response_type, _cache, data, _detect_category, _STATS)
        if cache_response:
            return cache_response

        # ============================================================
        # IN-FLIGHT DEDUP
        # ============================================================
        is_first_request, inflight_response = await check_in_flight(
            title, total_price, response_type, _IN_FLIGHT, _IN_FLIGHT_RESULTS, _IN_FLIGHT_LOCK
        )
        if inflight_response:
            return inflight_response

        # ============================================================
        # DISABLED CHECK
        # ============================================================
        disabled_response = check_disabled(_ENABLED, _STATS)
        if disabled_response:
            return disabled_response

        # ============================================================
        # QUEUE MODE
        # ============================================================
        queue_response = check_queue_mode(
            _QUEUE_MODE, data, title, total_price, listing_id, timestamp,
            None, None, _LISTING_QUEUE, alias, _detect_category, _log_incoming_listing,
            _render_queued_html
        )
        if queue_response:
            return queue_response

        # FULL ANALYSIS
        # ============================================================
        _STATS["api_calls"] += 1
        _STATS["session_cost"] += _COST_PER_CALL_HAIKU

        # Detect category
        category, category_reasons = _detect_category(data)
        logger.info(f"Category: {category}")
        _timing['category'] = _time.time() - _start_time
        logger.info(f"[TIMING] Category detect + setup: {_timing['category']*1000:.0f}ms")

        # ============================================================
        # USER PRICE DATABASE CHECK
        # ============================================================
        user_price_result = check_user_price_db(
            title, total_price, category, listing_enhancements,
            _lookup_user_price, _render_result_html, _cache
        )
        if user_price_result:
            result, html = user_price_result
            result['html'] = html
            # Always return JSON with html field for uBuyFirst columns + display
            return JSONResponse(content=result)

        # ============================================================
        # INSTANT PASS CHECK (Rule-based, no AI)
        # ============================================================
        instant_pass_result = _check_instant_pass(title, total_price, category, data)
        if instant_pass_result:
            reason = instant_pass_result[0]
            rec = instant_pass_result[1]  # "PASS" or "BUY"
            instant_data = instant_pass_result[2] if len(instant_pass_result) > 2 else {}
            is_buy = (rec == "BUY")
            logger.info(f"[INSTANT {'BUY' if is_buy else 'PASS'}] {reason}")
            result = {
                "Recommendation": rec,
                "Qualify": "Yes" if is_buy else "No",
                "reasoning": f"INSTANT {rec}: {reason}",
                "confidence": instant_data.get("confidence", 95),
                "instantPass": not is_buy,
                "instantBuy": is_buy,
                "karat": "NA", "weight": "NA",
                "goldweight": "NA", "silverweight": "NA", "meltvalue": "NA",
                "maxBuy": "NA", "sellPrice": "NA", "Profit": "NA",
                "Margin": "NA", "pricePerGram": "NA",
                "fakerisk": "low" if is_buy else "NA",
                "itemtype": "NA", "stoneDeduction": "0",
                "weightSource": "NA", "verified": "rule-based",
            }
            # Override NA values with real calculated data when available
            if instant_data:
                result.update(instant_data)
                if 'weightSource' not in instant_data:
                    result['weightSource'] = 'stated'
            html = _render_result_html(result, category, title)
            result['html'] = html
            _cache.set(title, total_price, result, html, rec)

            # Update correct stat counter
            if is_buy:
                _STATS["buy_count"] += 1
            else:
                _STATS["pass_count"] += 1

            # Send Discord alert for instant BUY
            if is_buy and _send_discord_alert:
                try:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    ebay_url_alert = data.get('ViewUrl', data.get('CheckoutUrl', ''))
                    if not ebay_url_alert and _get_ebay_search_url:
                        ebay_url_alert = _get_ebay_search_url(title)
                    first_image = None
                    raw_imgs = data.get('images', data.get('PictureURL', []))
                    if isinstance(raw_imgs, str):
                        raw_imgs = [raw_imgs]
                    for img in (raw_imgs or []):
                        if isinstance(img, str) and img.startswith('http'):
                            first_image = img
                            break
                        elif isinstance(img, dict):
                            url = img.get('url', img.get('URL', ''))
                            if url.startswith('http'):
                                first_image = url
                                break
                    profit_val = float(str(instant_data.get('Profit', '0')).replace('$', '').replace('+', ''))
                    asyncio.create_task(_send_discord_alert(
                        title=title, price=price_float,
                        recommendation="BUY", category=category,
                        profit=profit_val,
                        reasoning=reason, ebay_url=ebay_url_alert,
                        image_url=first_image,
                        confidence=str(instant_data.get('confidence', 90)),
                        extra_data={"instant_buy": True, "source": "rule-based"},
                    ))
                except Exception as e:
                    logger.error(f"[DISCORD] Instant BUY alert error: {e}")

            # Always return JSON with html field for uBuyFirst columns + display
            return JSONResponse(content=result)

        # ============================================================
        # OLLAMA FALLBACK (if instant_pass didn't find weight for gold/silver)
        # ============================================================
        if not instant_pass_result and category in ['gold', 'silver']:
            # Check if we might have weight in ConditionDescription that wasn't found by regex
            condition_desc = data.get('ConditionDescription', '')
            if condition_desc and ('gram' in condition_desc.lower() or 'g ' in condition_desc.lower() or 'oz' in condition_desc.lower()):
                try:
                    from pipeline.instant_pass import extract_with_ollama
                    ollama_result = await extract_with_ollama(title, condition_desc)
                    if ollama_result and ollama_result[0]:  # Found weight via Ollama
                        weight_grams, karat = ollama_result
                        logger.info(f"[OLLAMA] Extracted weight={weight_grams}g, karat={karat}K from ConditionDescription")
                        # Add the discovered weight to the data and re-run instant pass
                        modified_data = dict(data)
                        modified_data['_ollama_weight'] = weight_grams
                        modified_data['_ollama_karat'] = karat
                        # Append weight to description so instant_pass can find it
                        modified_data['description'] = f"{data.get('description', '')} {weight_grams} grams"
                        instant_pass_result = _check_instant_pass(title, total_price, category, modified_data)
                        if instant_pass_result:
                            reason = instant_pass_result[0]
                            rec = instant_pass_result[1]
                            instant_data = instant_pass_result[2] if len(instant_pass_result) > 2 else {}
                            is_buy = (rec == "BUY")
                            logger.info(f"[OLLAMA→INSTANT {rec}] {reason}")
                            result = {
                                "Recommendation": rec,
                                "Qualify": "Yes" if is_buy else "No",
                                "reasoning": f"OLLAMA→INSTANT {rec}: {reason}",
                                "confidence": instant_data.get("confidence", 85),
                                "instantPass": not is_buy,
                                "instantBuy": is_buy,
                                "weightSource": "ollama",
                            }
                            html = _render_result_html(result, category, title)
                            result['html'] = html
                            _cache.set(title, total_price, result, html, rec)
                            _STATS["pass_count" if not is_buy else "buy_count"] += 1
                            # Always return JSON with html field for uBuyFirst columns + display
                            return JSONResponse(content=result)
                except Exception as e:
                    logger.debug(f"[OLLAMA] Fallback error: {e}")

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

                # === PRICE OVERRIDE CHECK - Manual market prices take precedence ===
                override = _check_price_override(title, category)
                if override:
                    override_market = override['market_price']
                    threshold = _CATEGORY_THRESHOLDS.get(category, 0.65)
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
                    _render_result_html, _cache, _STATS, response_type
                )
                if pc_quick_response:
                    return pc_quick_response
            except Exception as e:
                logger.error(f"[PC] Price parsing error: {e}")

        # Log for pattern analysis
        _log_incoming_listing(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

        # === QUICK PASS CHECKS (Agent, Textbook, Gold) ===
        agent_qp_response = check_agent_quick_pass(
            category, data, total_price, title, _get_agent,
            _render_result_html, _cache, _STATS, response_type
        )
        if agent_qp_response:
            # Send Discord alert for agent quick pass BUY
            try:
                import json as _json
                result_body = agent_qp_response.body
                if isinstance(result_body, bytes):
                    qp_result = _json.loads(result_body.decode('utf-8'))
                else:
                    qp_result = result_body

                qp_rec = qp_result.get('Recommendation', '')
                if qp_rec == 'BUY' and _send_discord_alert:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    profit_val = qp_result.get('Profit', 0)
                    if isinstance(profit_val, str):
                        profit_val = float(profit_val.replace('$', '').replace('+', '').replace(',', '') or 0)

                    # Get first image
                    first_image = None
                    raw_imgs = data.get('images', data.get('PictureURL', []))
                    if isinstance(raw_imgs, str):
                        raw_imgs = [raw_imgs]
                    for img in (raw_imgs or []):
                        if isinstance(img, str) and img.startswith('http'):
                            first_image = img
                            break
                        elif isinstance(img, dict):
                            url = img.get('url', img.get('URL', ''))
                            if url.startswith('http'):
                                first_image = url
                                break

                    ebay_url = data.get('ViewUrl', data.get('CheckoutUrl', ''))
                    if not ebay_url and _get_ebay_search_url:
                        ebay_url = _get_ebay_search_url(title)

                    logger.info(f"[DISCORD] Agent quick pass {qp_rec}: {title[:40]}...")
                    asyncio.create_task(_send_discord_alert(
                        title=title, price=price_float,
                        recommendation=qp_rec, category=category,
                        profit=profit_val,
                        reasoning=qp_result.get('reasoning', ''),
                        ebay_url=ebay_url,
                        image_url=first_image,
                        confidence=str(qp_result.get('confidence', 85)),
                        extra_data={"source": "agent-quick-pass"},
                    ))
            except Exception as e:
                logger.error(f"[DISCORD] Agent quick pass alert error: {e}")

            return agent_qp_response
        textbook_response = await check_textbook(
            category, data, total_price, title, _get_agent,
            _render_result_html, _cache, _STATS, response_type
        )
        if textbook_response:
            return textbook_response
        gold_qp_response = check_gold_price_per_gram(
            category, title, total_price, _render_result_html, _cache, _STATS, response_type
        )
        if gold_qp_response:
            return gold_qp_response

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
                if item_id and not desc_has_weight and _EBAY_POLLER_AVAILABLE:
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

                # Check fast extract instant pass
                fast_extract_response = check_fast_extract_pass(
                    fast_result, category, data, total_price, title,
                    _render_result_html, _cache, _STATS, response_type
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
        needs_images_for_tier1 = False
        skip_ai_entirely = False
        if category in ['gold', 'silver']:
            if fast_result is None:
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: no fast_result")
            elif getattr(fast_result, 'has_non_metal', False):
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: has non-metal ({fast_result.non_metal_type})")
            elif fast_result.weight_grams is None:
                # Check if heuristic flagged this as hot (heavy chain type)
                is_heuristic_hot = data.get('_heuristic', {}).get('is_hot', False)
                if is_heuristic_hot:
                    # Skip images for heuristic hot items - chain type estimation is enough
                    logger.info(f"[HEURISTIC] Skipping images for hot {data['_heuristic']['chain_type']} chain (est {data['_heuristic']['est_weight']:.0f}g)")
                else:
                    needs_images_for_tier1 = True
                    logger.info(f"[LAZY] Need images: no weight in title")
            elif fast_result.weight_source == 'estimate':
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: weight is estimated")
            elif fast_result.max_buy and price_float > fast_result.max_buy * 1.3:
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
                quick_result['html'] = html
                _cache.set(title, total_price, quick_result, html, "PASS")
                _STATS["pass_count"] += 1
                _timing['total'] = _time.time() - _start_time
                logger.info(f"[LAZY] Saved {2 + 4:.0f}+ seconds (no images, no AI) - PASS in {_timing['total']*1000:.0f}ms")
                # Always return JSON with html field for uBuyFirst columns + display
                return JSONResponse(content=quick_result)
            else:
                needs_images_for_tier1 = True
                logger.info(f"[LAZY] Need images: price ${price_float:.0f} near maxBuy ${fast_result.max_buy:.0f}, need AI verification")
        if needs_images_for_tier1 and raw_image_urls:
            _img_start = _time.time()
            max_imgs = getattr(_IMAGES, 'max_images_gold_silver', 5)
            img_size = getattr(_IMAGES, 'resize_for_gold_silver', 1024)
            logger.info(f"[TIER1] Fetching up to {max_imgs} images for GPT-4o (gold/silver - first+last for scale photos)...")
            images = await _process_image_list(
                raw_image_urls,
                max_size=img_size,
                max_count=max_imgs,
                selection="first_last"
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
                fast_context += f"\n!! NON-METAL DETECTED: '{fast_result.non_metal_type}'\n"
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
                    flatware_context += "!! WEIGHT IS ESTIMATED - Use images to verify piece type/size.\n"
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
        # ============================================================

        # OPTIMIZATION: Pre-fetch Tier 2 images during Tier 1 (saves 500ms-4s)
        tier2_images_task = None
        if raw_image_urls and category in ['gold', 'silver']:
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
            is_precious_metal = category in ('gold', 'silver')
            image_detail = "low"
            max_tokens = 800 if is_precious_metal else 500

            if images:
                openai_content = [{"type": "text", "text": user_message}]
                for img in images[:6]:
                    if img.get("type") == "image":
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
                # === NO-WEIGHT ANALYSIS PATH ===
                # For gold/silver without stated weight, use specialized prompt
                system_prompt = _get_agent_prompt(category)
                is_no_weight_analysis = False

                if category in ('gold', 'silver') and fast_result:
                    has_weight = fast_result.weight_grams and fast_result.weight_grams > 0
                    if not has_weight:
                        # No weight stated - use specialized no-weight prompt
                        agent = _get_agent(category) if _get_agent else None
                        if agent and hasattr(agent, 'get_no_weight_prompt'):
                            system_prompt = agent.get_no_weight_prompt()
                            is_no_weight_analysis = True
                            logger.info(f"[NO-WEIGHT] Using visual estimation prompt for {category}")

                            # Also run visual analysis for context
                            if hasattr(agent, 'analyze_no_weight_indicators'):
                                no_weight_analysis = agent.analyze_no_weight_indicators(data, price_float)
                                if no_weight_analysis.get('green_flags'):
                                    logger.info(f"[NO-WEIGHT] Green flags: {no_weight_analysis['green_flags']}")
                                if no_weight_analysis.get('weight_estimate_low'):
                                    logger.info(f"[NO-WEIGHT] Est. weight: {no_weight_analysis['weight_estimate_low']:.1f}-{no_weight_analysis['weight_estimate_high']:.1f}g")

                response = await _openai_client.chat.completions.create(
                    model=tier1_model,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *openai_messages
                    ]
                )
                raw_response = response.choices[0].message.content
                if raw_response:
                    raw_response = raw_response.strip()
                else:
                    logger.error(f"[TIER1] GPT-4o returned empty response!")
                    raw_response = '{"Recommendation": "RESEARCH", "reasoning": "Empty AI response"}'
                _STATS["session_cost"] += tier1_cost
                _record_openai_cost(tier1_cost)
                tier1_model_used = tier1_model.upper()
            except Exception as e:
                logger.error(f"[TIER1] {tier1_model} failed, falling back to Haiku: {e}")
                # Fallback to Haiku - use same prompt (system_prompt already set above)
                response = await _client.messages.create(
                    model=_MODEL_FAST,
                    max_tokens=500,
                    system=system_prompt,
                    messages=[{"role": "user", "content": message_content}]
                )
                raw_response = response.content[0].text.strip()
                _STATS["session_cost"] += _COST_PER_CALL_HAIKU
                tier1_model_used = "Haiku (fallback)"
        else:
            # Fallback to Haiku if OpenAI client not available
            # Check for no-weight analysis path
            system_prompt = _get_agent_prompt(category)
            if category in ('gold', 'silver') and fast_result:
                has_weight = fast_result.weight_grams and fast_result.weight_grams > 0
                if not has_weight:
                    agent = _get_agent(category) if _get_agent else None
                    if agent and hasattr(agent, 'get_no_weight_prompt'):
                        system_prompt = agent.get_no_weight_prompt()
                        logger.info(f"[NO-WEIGHT] Using visual estimation prompt for {category}")

            logger.info(f"[TIER1] Calling Haiku for {category} (OpenAI not configured)...")
            response = await _client.messages.create(
                model=_MODEL_FAST,
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": message_content}]
            )
            raw_response = response.content[0].text.strip()
            _STATS["session_cost"] += _COST_PER_CALL_HAIKU
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
                result = agent.validate_response(result)

            # === FAST EXTRACT WEIGHT OVERRIDE ===
            # If fast_extract estimated a heavy weight (military ring, class ring, etc.)
            # ALWAYS mark the weightSource with our reliable estimate type for scoring
            if fast_result and fast_result.weight_grams and fast_result.weight_source:
                if 'estimate:' in str(fast_result.weight_source) and fast_result.weight_grams >= 10:
                    estimate_type = fast_result.weight_source.replace('estimate:', '')
                    # Check for reliable heavy gold estimates that deserve trusted scoring
                    reliable_estimates = ['military', 'army', 'navy', 'marine', 'infantry', 'queen of battle',
                                        'class ring', 'college ring', 'school ring', 'signet', 'championship']
                    is_reliable = any(kw in estimate_type.lower() for kw in reliable_estimates)

                    if is_reliable:
                        # Get AI's weight
                        ai_weight_str = result.get('weight', result.get('goldweight', ''))
                        ai_weight = None
                        try:
                            ai_weight = float(str(ai_weight_str).replace('g', '').replace('G', '').strip())
                        except:
                            pass

                        # If AI weight is much lower, override with our estimate
                        if ai_weight and ai_weight < fast_result.weight_grams * 0.5:
                            logger.warning(f"[FAST] WEIGHT OVERRIDE: AI={ai_weight}g << fast_extract={fast_result.weight_grams}g ({estimate_type}) - using estimate")
                            if category == 'gold':
                                result['goldweight'] = str(fast_result.weight_grams)
                            else:
                                result['silverweight'] = str(fast_result.weight_grams)
                            result['weight'] = f"{fast_result.weight_grams}g"

                        # ALWAYS set the trusted estimate weightSource for reliable estimates
                        # This ensures proper scoring even if AI's weight matches
                        result['weightSource'] = f'estimate:{estimate_type}'
                        logger.info(f"[FAST] Trusted estimate: {fast_result.weight_grams}g from {estimate_type}")

            # Add listing price to result for display
            result['listingPrice'] = total_price

            # === CAPTURE TIER 1 ORIGINAL RECOMMENDATION BEFORE ANY VALIDATION ===
            tier1_original_rec = result.get('Recommendation', 'RESEARCH')
            logger.info(f"[TIER1] {tier1_model_used} original recommendation: {tier1_original_rec}")

            # SERVER-SIDE MATH VALIDATION
            _validation_start = _time.time()
            result = _validate_and_fix_margin(result, total_price, category, title, data)
            _timing['validation'] = _time.time() - _validation_start
            logger.info(f"[TIMING] Validation: {_timing['validation']*1000:.0f}ms")

            # TCG/LEGO VALIDATION
            if category in ["tcg", "lego"]:
                try:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    result = _validate_tcg_lego_result(result, pc_result, price_float, category, title)
                except Exception as e:
                    logger.error(f"[PC] TCG/LEGO validation error: {e}")

            # VIDEO GAMES VALIDATION
            if category == "videogames":
                try:
                    price_float = float(str(total_price).replace('$', '').replace(',', ''))
                    result = _validate_videogame_result(result, pc_result, price_float, data)
                except Exception as e:
                    logger.error(f"[VG] Video game validation error: {e}")

            recommendation = result.get('Recommendation', 'RESEARCH')

            # ============================================================
            # TIER 2 RE-ANALYSIS (Sonnet for BUY/RESEARCH)
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
                result['hot_deal'] = True
                result['reasoning'] = f"HOT DEAL (verified): {fast_result.hot_reason}\n" + result.get('reasoning', '')

            logger.info(f"[TIER2] Check: TIER2_ENABLED={_TIER2_ENABLED}, parallel={_PARALLEL_MODE}, haiku={tier1_original_rec}, hot={is_hot_deal}, should_run={should_run_tier2}")

            # ============================================================
            # SMART MODE: Skip Tier 2 for verified high-margin deals
            # ============================================================
            weight_source = result.get('weightSource', 'estimated')

            # SERVER-SIDE VALIDATION: Verify AI's "stated" weight claim against actual title
            if weight_source in ['stated', 'title']:
                title_text = data.get('title', '') or data.get('Title', '') or ''
                has_weight_in_title = bool(re.search(r'\d+\.?\d*\s*(?:g(?:ram)?s?|dwt|oz)\b', title_text, re.IGNORECASE))
                if not has_weight_in_title:
                    original_source = weight_source
                    logger.warning(f"[WEIGHT-CHECK] AI claimed weightSource='{original_source}' but NO weight found in title: '{title_text[:80]}...'")
                    weight_source = 'estimate'
                    result['weightSource'] = 'estimate'
                    result['weight_validation_override'] = f"AI claimed '{original_source}' but no weight in title"
            profit_val = 0
            try:
                profit_str = result.get('Profit', result.get('Margin', '0'))
                profit_val = float(str(profit_str).replace('$', '').replace('+', '').replace(',', ''))
            except:
                pass

            # Skip Tier 2 for verified deals: stated weight + significant profit + BUY recommendation
            is_from_api = data.get('source') == 'ebay_api'
            is_verified_deal = (
                category in ['gold', 'silver'] and
                weight_source in ['stated', 'title'] and
                profit_val >= 75 and
                recommendation == 'BUY' and
                not is_from_api
            )

            if is_verified_deal:
                logger.info(f"[FAST-TRACK] Verified deal: {weight_source} weight, ${profit_val:.0f} profit - SKIPPING Tier 2")
                should_run_tier2 = False
                result['fast_tracked'] = True
                result['reasoning'] = f"[FAST-TRACK: Verified {weight_source} weight, ${profit_val:.0f} profit]\n" + result.get('reasoning', '')

            # OPTIMIZATION: Skip Tier 2 for high-confidence PASS
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
            use_parallel = False

            if should_run_tier2 and use_parallel:
                # DISABLED: This block no longer executes
                logger.info(f"[PARALLEL] Starting background Sonnet verification (gold/silver - speed matters)...")
                logger.info(f"[PARALLEL] Returning Haiku result immediately for SPEED")
                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                asyncio.create_task(background_sonnet_verify(
                    title=title,
                    price=price_float,
                    category=category,
                    haiku_result=result.copy(),
                    raw_image_urls=raw_image_urls,
                    data=data,
                    fast_result=fast_result
                ))
                result['tier2_status'] = 'PENDING'
                result['reasoning'] = f"[HAIKU - Sonnet verifying in background]\n{result.get('reasoning', '')}"
                should_run_tier2 = False

            if should_run_tier2 and category in ['lego', 'tcg', 'videogames', 'gold', 'silver']:
                logger.info(f"[TIER2] Waiting for Sonnet verification ({category} - PriceCharting needs validation)...")

            # ============================================================
            # SEQUENTIAL MODE: Wait for Tier 2 before returning
            # ============================================================
            if not should_run_tier2 and tier2_images_task and not tier2_images_task.done():
                tier2_images_task.cancel()
                logger.debug(f"[OPTIMIZATION] Cancelled unused image pre-fetch")
            if should_run_tier2:
                logger.info(f"[TIER2] *** MANDATORY SONNET VERIFICATION STARTING ***")
                logger.info(f"[TIER1] Tier1: {tier1_original_rec}, Post-validation: {recommendation} - triggering Tier 2 verification...")

                # Fetch images for Sonnet using first_last strategy
                _img_start = _time.time()
                if tier2_images_task:
                    images = await tier2_images_task
                    logger.info(f"[OPTIMIZATION] Using pre-fetched images: {len(images)} images @ {_IMAGES.resize_for_tier2}px")
                elif raw_image_urls:
                    logger.info(f"[TIER2] Fetching images using first_last strategy (first 3 + last 3 of {len(raw_image_urls)} total)...")
                    images = await _process_image_list(raw_image_urls, max_size=_IMAGES.resize_for_tier2, selection="first_last")
                    logger.info(f"[TIER2] Fetched {len(images)} images @ {_IMAGES.resize_for_tier2}px")
                _timing['images'] = _time.time() - _img_start
                logger.info(f"[TIMING] Image fetch (for Tier2): {_timing['images']*1000:.0f}ms")

                price_float = float(str(total_price).replace('$', '').replace(',', ''))
                _tier2_start = _time.time()

                # Use OpenAI or Claude based on config
                if _TIER2_PROVIDER == "openai" and _openai_client:
                    logger.info(f"[TIER2] Using OpenAI {_OPENAI_TIER2_MODEL} for FAST verification...")
                    result = await tier2_reanalyze_openai(
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
                    result = await tier2_reanalyze(
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
                    deal_threshold = user_market * 0.65
                    if listing_price >= deal_threshold:
                        old_rec = recommendation
                        recommendation = "PASS"
                        result['Recommendation'] = "PASS"
                        result['user_correction_applied'] = True
                        result['user_market_price'] = user_market
                        result['reasoning'] = f"User correction: Market is ${user_market}. Listing at ${listing_price} is not a deal (need <${deal_threshold:.2f}). {result.get('reasoning', '')}"
                        logger.info(f"[PRICE OVERRIDE] {old_rec} -> PASS due to user correction: market=${user_market}, listing=${listing_price}")
                    else:
                        result['user_market_price'] = user_market
                        result['user_correction_validated'] = True
                        logger.info(f"[PRICE VALIDATED] Listing ${listing_price} is below user market ${user_market} - keeping {recommendation}")
                except Exception as e:
                    logger.warning(f"[PRICE OVERRIDE] Error applying correction: {e}")

            # Update stats
            if recommendation == "BUY":
                _STATS["buy_count"] += 1
            elif recommendation == "PASS":
                _STATS["pass_count"] += 1
            else:
                _STATS["research_count"] += 1

            # Create listing record
            input_data_clean = {k: v for k, v in data.items() if k != 'images'}

            # Extract just the URLs from images for thumbnail
            raw_images = data.get('images', [])
            if raw_images:
                image_urls = []
                for img in raw_images[:3]:
                    if isinstance(img, str):
                        if img.startswith('http'):
                            image_urls.append(img)
                    elif isinstance(img, dict):
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

            _STATS["listings"][listing_id] = listing_record
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

                # Clean up after a delay
                async def cleanup_in_flight(key):
                    await asyncio.sleep(5)
                    _IN_FLIGHT.pop(key, None)
                    _IN_FLIGHT_RESULTS.pop(key, None)
                asyncio.create_task(cleanup_in_flight(request_key))

            logger.info(f"Result: {recommendation}")
            logger.info(f"[RESPONSE] Keys: {list(result.keys())}")

            # Discord notification moved to after all validation checks (see below)

            # Use saved response_type
            logger.info(f"[RESPONSE] response_type: {response_type}")

            # === HIGH-VALUE GOLD JEWELRY CHECK ===
            if category == 'gold' and result.get('Recommendation') == 'PASS':
                try:
                    price_val = float(str(total_price).replace('$', '').replace(',', ''))
                    title_lower = title.lower()
                    has_karat = any(k in title_lower for k in ['10k', '14k', '18k', '22k', '24k', '10kt', '14kt', '18kt', '22kt', '24kt', 'solid gold'])
                    premium_stones = ['diamond', 'sapphire', 'ruby', 'emerald', 'opal', 'tanzanite', 'aquamarine', 'topaz', 'garnet', 'amethyst', 'pearl']
                    has_premium = any(stone in title_lower for stone in premium_stones)
                    lab_diamond_indicators = ['lab created', 'lab grown', 'lab-created', 'lab-grown', 'igi certified', 'igi lab', 'lgd', 'cvd diamond', 'hpht', 'moissanite', 'simulated', 'cz ', 'cubic zirconia']
                    is_lab_diamond = any(indicator in title_lower for indicator in lab_diamond_indicators)
                    scale_hints = ['scale', 'gram', 'grams', 'weigh', 'dwt', 'pennyweight']
                    has_scale_hint = any(hint in title_lower for hint in scale_hints)
                    desc_lower = str(data.get('Description', '')).lower()
                    has_scale_in_desc = any(hint in desc_lower for hint in scale_hints)

                    max_buy = result.get('maxBuy', 0)
                    try:
                        max_buy_val = float(str(max_buy).replace('$', '').replace(',', '')) if max_buy else 0
                    except:
                        max_buy_val = 0

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
                        html = _render_result_html(result, category, title)
                except Exception as e:
                    logger.error(f"[HIGH-VALUE GOLD] Check error: {e}")

            # === SERVER CONFIDENCE SCORING (GOLD/SILVER) ===
            if category in ['gold', 'silver'] and result.get('Recommendation') == 'BUY':
                server_score = 60
                score_reasons = ["Base: 60"]
                weight_source = result.get('weightSource', 'estimate').lower()
                weight_val = result.get('weight', result.get('goldweight', ''))
                has_weight = weight_val and str(weight_val) not in ['NA', '--', 'Unknown', '', '0', 'None']

                if weight_source in ['scale']:
                    server_score += 25
                    score_reasons.append("Scale weight: +25")
                elif weight_source in ['stated', 'title']:
                    server_score += 15
                    score_reasons.append("Stated weight: +15")
                elif has_weight and (weight_source in ['estimate', 'estimated', '', 'unknown', 'na'] or weight_source.startswith('estimate:')):
                    # Check for reliable heavy gold estimates (military rings, class rings, etc.)
                    # These have distinctive keywords that reliably indicate heavy items
                    full_weight_source = result.get('weightSource', '').lower()
                    reliable_estimates = ['military', 'army', 'navy', 'marine', 'infantry', 'queen of battle',
                                        'class ring', 'college ring', 'school ring', 'signet', 'championship']
                    is_reliable_estimate = any(kw in full_weight_source for kw in reliable_estimates)

                    if is_reliable_estimate:
                        # Trusted estimate from known heavy item type - small penalty only
                        server_score -= 5
                        score_reasons.append(f"Trusted estimate ({full_weight_source.split(':')[-1] if ':' in full_weight_source else 'heavy item'}): -5")
                    else:
                        # Check if this is "plain gold" without stones/complexity
                        title_lower = title.lower() if title else ''
                        stone_indicators = ['diamond', 'stone', 'gem', 'pearl', 'jade', 'turquoise',
                                          'opal', 'sapphire', 'ruby', 'emerald', 'tanzanite', 'cameo']
                        has_stones = any(s in title_lower for s in stone_indicators)

                        if category == 'gold' and not has_stones:
                            # Plain gold - weight estimates are more reliable
                            server_score -= 15
                            score_reasons.append("Estimated weight (plain gold): -15")
                        else:
                            server_score -= 30
                            score_reasons.append("Estimated weight: -30")
                else:
                    server_score -= 40
                    score_reasons.append("No weight: -40")

                if category == 'gold':
                    karat = result.get('karat', '')
                    if karat and str(karat) not in ['NA', '--', 'Unknown', '', 'None']:
                        server_score += 10
                        score_reasons.append(f"Karat {karat}: +10")
                    else:
                        server_score -= 10
                        score_reasons.append("No karat: -10")
                else:
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

                fakerisk = result.get('fakerisk', '').lower()
                if fakerisk == 'high':
                    server_score -= 20
                    score_reasons.append("High fake risk: -20")
                elif fakerisk == 'low':
                    server_score += 5
                    score_reasons.append("Low fake risk: +5")

                stone_deduction = result.get('stoneDeduction', '')
                if stone_deduction and str(stone_deduction) not in ['0', 'NA', '--', '', 'None']:
                    server_score -= 10
                    score_reasons.append("Stone deduction: -10")

                # CAMEO CHECK
                title_lower = title.lower() if title else ''
                if 'cameo' in title_lower and category == 'gold':
                    stone_ded_str = str(stone_deduction).lower() if stone_deduction else ''
                    ded_digits = ''.join(c for c in stone_ded_str if c in '0123456789.')
                    ded_grams = float(ded_digits) if ded_digits and ded_digits != '.' else 0
                    has_cameo_deduction = stone_ded_str not in ['0', 'na', '--', '', 'none'] and ded_grams >= 1.5

                    try:
                        total_wt = float(str(result.get('weight', '0')).replace('g', '').strip() or '0')
                        gold_wt = float(str(result.get('goldweight', '0')).replace('g', '').strip() or '0')
                        no_weight_deduction = total_wt > 0 and gold_wt > 0 and gold_wt >= total_wt * 0.75
                    except (ValueError, TypeError):
                        no_weight_deduction = False
                    if not has_cameo_deduction or no_weight_deduction:
                        server_score -= 40
                        score_reasons.append("Cameo: no proper shell deduction: -40")
                        logger.warning(f"[CAMEO CHECK] Shell weight not deducted! weight={result.get('weight')}, goldweight={result.get('goldweight')}, stoneDeduction='{stone_deduction}', title='{title[:60]}'")
                    else:
                        server_score -= 5
                        score_reasons.append("Cameo (shell deducted): -5")

                result['serverConfidence'] = server_score
                result['serverScoreBreakdown'] = " | ".join(score_reasons)

                if server_score < 50:
                    logger.warning(f"[SERVER SCORE] Forcing BUY->RESEARCH: score={server_score} ({' | '.join(score_reasons)})")
                    result['Recommendation'] = 'RESEARCH'
                    original_reasoning = result.get('reasoning', '')
                    result['reasoning'] = f"[LOW CONFIDENCE: {server_score}/100] {' | '.join(score_reasons)} - needs verification. " + original_reasoning
                    result['tier2_override'] = True
                    result['tier2_reason'] = f'Server confidence {server_score} < 50 threshold'
                    html = _render_result_html(result, category, title)
                elif server_score < 65:
                    logger.info(f"[SERVER SCORE] BUY with caution: score={server_score} ({' | '.join(score_reasons)})")
                    result['reasoning'] = f"[MODERATE CONFIDENCE: {server_score}/100] " + result.get('reasoning', '')
                else:
                    logger.info(f"[SERVER SCORE] HIGH confidence BUY: score={server_score}")

            # === EXPENSIVE MIXED LOT CHECK ===
            if category in ['gold', 'silver'] and result.get('Recommendation') == 'PASS':
                try:
                    price_val = float(str(total_price).replace('$', '').replace(',', ''))
                    title_lower = title.lower()
                    is_lot = any(term in title_lower for term in ['lot', 'mixed', 'collection', 'estate', 'assorted', 'bulk'])
                    karat_indicators = ['10k', '14k', '18k', '22k', '24k', '925', 'sterling', '.925']
                    karats_found = sum(1 for k in karat_indicators if k in title_lower)
                    is_mixed_metals = karats_found >= 2

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

            # ============================================================
            # DISCORD ALERT FOR BUY ONLY (after all validation checks)
            # ============================================================
            final_recommendation = result.get('Recommendation')
            is_parallel_pending = result.get('tier2_status') == 'PENDING'
            is_from_api = data.get('source') == 'ebay_api'

            if is_parallel_pending:
                logger.info(f"[DISCORD] Skipping immediate alert - Sonnet verifying in background")
            elif is_from_api:
                logger.info(f"[DISCORD] Skipping - API listing has its own Discord handler")
            elif final_recommendation == "BUY":
                logger.info(f"[DISCORD] FINAL BUY confirmed after all validation - sending alert")
                try:
                    item_price_str = data.get('ItemPrice', data.get('TotalPrice', '0'))
                    list_price = float(str(item_price_str).replace('$', '').replace(',', ''))

                    # Use ViewUrl from uBuyFirst data first
                    ebay_item_url = data.get('ViewUrl', data.get('CheckoutUrl', ''))
                    if ebay_item_url:
                        from urllib.parse import unquote
                        ebay_item_url = unquote(ebay_item_url.replace('+', ' '))
                        logger.info(f"[EBAY] Using ViewUrl from data: {ebay_item_url[:80]}...")

                    # Fallback: Try seller-based eBay API lookup
                    if not ebay_item_url:
                        seller_name_lookup = data.get('SellerName', data.get('SellerUserID', ''))
                        if seller_name_lookup:
                            logger.info(f"[EBAY] Attempting seller-based lookup for '{seller_name_lookup}'...")
                            ebay_item_url = await _lookup_ebay_item_by_seller(title, seller_name_lookup, list_price)

                    # Fallback: Try title-only eBay API lookup
                    if not ebay_item_url:
                        ebay_item_url = await _lookup_ebay_item(title, list_price)

                    # Final fallback to search URL
                    if not ebay_item_url:
                        ebay_item_url = _get_ebay_search_url(title)
                        logger.info(f"[EBAY] Using search fallback: {ebay_item_url[:60]}...")

                    # Get first image URL from RAW data
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
                        recommendation=final_recommendation,
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
            else:
                logger.info(f"[DISCORD] Skipping - final recommendation is {final_recommendation}, not BUY")

            # Build final response
            return finalize_result(
                result, html, title, total_price, listing_enhancements,
                response_type, _timing, _start_time, _cache
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
            try:
                error_result['html'] = _render_result_html(error_result, category, title)
            except Exception:
                pass
            return JSONResponse(content=error_result)

    except Exception as e:
        logger.error(f"Error: {e}")
        traceback.print_exc()
        error_result = {
            "Qualify": "No", "Recommendation": "ERROR",
            "reasoning": f"Error: {str(e)[:50]}"
        }
        try:
            error_result['html'] = _render_result_html(error_result, locals().get('category', 'unknown'), locals().get('title', ''))
        except Exception:
            pass
        return JSONResponse(content=error_result)
