"""
Pre-analysis checks for the pipeline.

Fast checks that can short-circuit analysis before any AI calls:
spam detection, deduplication, sold items, disabled state, queue mode, cache.
"""

import asyncio
import logging
from typing import Optional, Tuple

from fastapi.responses import JSONResponse, HTMLResponse

from services.deduplication import check_recently_evaluated

logger = logging.getLogger(__name__)


def check_spam(data: dict, check_seller_spam_fn) -> Optional[JSONResponse]:
    """
    Check if seller is blocked (spam/rapid-fire detection).

    Returns JSONResponse if blocked, None to continue.
    High-value keywords bypass blocked seller check.
    """
    seller_name = data.get('SellerName', '') or data.get('StoreName', '')
    is_blocked, newly_blocked = check_seller_spam_fn(seller_name)

    if is_blocked:
        # High-value keywords that bypass blocked seller check
        title = str(data.get('Title', '')).lower().replace('+', ' ')
        high_value_keywords = [
            'scrap gold', 'gold scrap', 'scrap 10k', 'scrap 14k', 'scrap 18k',
            '10k scrap', '14k scrap', '18k scrap', '10kt scrap', '14kt scrap', '18kt scrap',
            'scrap 10kt', 'scrap 14kt', 'scrap 18kt',
            'gold lot', 'jewelry lot', 'chain lot', 'ring lot',
            'for refining', 'for melt', 'melt value'
        ]

        if any(kw in title for kw in high_value_keywords):
            logger.info(f"[SPAM BYPASS] High-value keyword in title - sending to AI despite blocked seller '{seller_name}'")
            return None  # Continue to AI analysis

        if newly_blocked:
            logger.warning(f"[SPAM] NEW BLOCK: '{seller_name}' - rapid-fire listing detected")
        else:
            logger.info(f"[SPAM] INSTANT PASS: '{seller_name}' is blocked")

        return JSONResponse(content={
            "Recommendation": "PASS",
            "Qualify": "No",
            "reasoning": f"Blocked seller (spam): {seller_name}",
            "confidence": "High",
            "blocked_seller": True,
            "seller_name": seller_name,
            "newly_blocked": newly_blocked
        })

    return None


def check_dedup(title: str, total_price) -> Optional[JSONResponse]:
    """
    Check if item was recently evaluated (deduplication).

    Returns JSONResponse with cached result if found, None to continue.
    """
    cached_result = check_recently_evaluated(title, total_price)
    if cached_result:
        logger.info(f"[DEDUP] Returning cached result: {cached_result.get('Recommendation', 'UNKNOWN')}")
        cached_result['dedup_cached'] = True
        return JSONResponse(content=cached_result)
    return None


def check_sold(data: dict) -> Optional[JSONResponse]:
    """
    Check if item is already sold.

    Returns JSONResponse if sold, None to continue.
    """
    sold_time = data.get('SoldTime', '') or data.get('Sold Time', '') or ''
    sold_time = sold_time.strip() if sold_time else ''
    if sold_time:
        logger.info(f"[SKIP] Item already sold at {sold_time}")
        return JSONResponse(content={
            "Recommendation": "SKIP",
            "reasoning": f"Item already sold at {sold_time}",
            "skipped": True,
            "sold_time": sold_time
        })
    return None


def check_disabled(enabled: bool, stats: dict) -> Optional[JSONResponse]:
    """
    Check if proxy is disabled.

    Returns JSONResponse if disabled, None to continue.
    """
    if not enabled:
        logger.info("DISABLED - Returning placeholder")
        stats["skipped"] += 1
        return JSONResponse(content={
            "Qualify": "No",
            "Recommendation": "DISABLED",
            "reasoning": "Proxy disabled - enable at localhost:8000"
        })
    return None


def check_queue_mode(queue_mode: bool, data: dict, title: str, total_price: str,
                     listing_id: str, timestamp: str, category: str,
                     category_reasons, listing_queue: dict, alias: str,
                     detect_category_fn, log_incoming_fn, render_queued_fn) -> Optional[HTMLResponse]:
    """
    Handle queue mode - store listing for manual review.

    Returns HTMLResponse if queued, None to continue.
    """
    if not queue_mode:
        return None

    if not category:
        category, category_reasons = detect_category_fn(data)

    log_incoming_fn(title, float(str(total_price).replace('$', '').replace(',', '') or 0), category, alias)

    raw_images = data.get('images', [])
    if raw_images:
        first_img = raw_images[0] if raw_images else None
        if first_img:
            img_preview = str(first_img)[:100] if isinstance(first_img, str) else str(type(first_img))
            logger.info(f"[IMAGES] First image format: {img_preview}...")

    listing_queue[listing_id] = {
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
    return HTMLResponse(content=render_queued_fn(category, listing_id, title, str(total_price)))


def check_cache(title: str, total_price: str, response_type: str,
                cache, data: dict, detect_category_fn, stats: dict) -> Optional[object]:
    """
    Check smart cache for existing result.

    Returns Response if cache hit, None to continue.
    """
    cached = cache.get(title, total_price)
    if not cached:
        return None

    result, html = cached

    # Detect category to check if we should trust the cache
    category_check, _ = detect_category_fn(data)

    # For video games: Don't trust cached BUY results without PC verification
    if category_check == 'videogames' and result.get('Recommendation') == 'BUY':
        if result.get('pcMatch') != 'Yes':
            logger.warning(f"[CACHE] Skipping cached video game BUY without PC verification")
            return None  # Fall through to re-analyze
        else:
            # SANITY CHECK: If cached market price is very high, it might be AI-hallucinated
            try:
                cached_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))
                cached_profit = float(str(result.get('Profit', '0')).replace('$', '').replace('+', '').replace(',', ''))

                if cached_market > 300 and cached_profit > 100:
                    logger.warning(f"[CACHE] SUSPICIOUS: market=${cached_market:.0f}, profit=${cached_profit:.0f} - re-verifying")
                    return None  # Fall through to re-analyze
                else:
                    stats["cache_hits"] += 1
                    logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")
                    if response_type == 'json':
                        return JSONResponse(content=result)
                    else:
                        return HTMLResponse(content=html)
            except:
                stats["cache_hits"] += 1
                logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')} (PC verified)")
                if response_type == 'json':
                    return JSONResponse(content=result)
                else:
                    return HTMLResponse(content=html)
    else:
        stats["cache_hits"] += 1
        logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')}")
        if response_type == 'json':
            logger.info("[CACHE HIT] Returning JSON (response_type=json)")
            return JSONResponse(content=result)
        else:
            logger.info("[CACHE HIT] Returning HTML (response_type=html)")
            return HTMLResponse(content=html)


async def check_in_flight(title: str, total_price: str, response_type: str,
                          in_flight: dict, in_flight_results: dict,
                          in_flight_lock) -> Tuple[bool, Optional[object]]:
    """
    Handle in-flight request deduplication.

    If the same listing is already being processed, wait for its result.

    Returns (is_first_request, optional_response).
    If optional_response is set, caller should return it immediately.
    """
    request_key = f"{title}|{total_price}"
    should_wait = False
    event = None

    async with in_flight_lock:
        if request_key in in_flight and not in_flight[request_key].is_set():
            logger.info(f"[IN-FLIGHT] Same listing already processing, will wait...")
            event = in_flight[request_key]
            should_wait = True
        elif request_key not in in_flight:
            event = asyncio.Event()
            in_flight[request_key] = event
            in_flight_results[request_key] = None
            logger.debug(f"[IN-FLIGHT] First request for this listing, processing...")

    if should_wait and event:
        try:
            await asyncio.wait_for(event.wait(), timeout=30.0)
            if request_key in in_flight_results and in_flight_results[request_key]:
                result, html = in_flight_results[request_key]
                logger.info(f"[IN-FLIGHT] Got result: {result.get('Recommendation', 'UNKNOWN')}")
                if response_type == 'json':
                    return False, JSONResponse(content=result)
                else:
                    return False, HTMLResponse(content=html)
        except asyncio.TimeoutError:
            logger.warning(f"[IN-FLIGHT] Timeout - processing independently")

    is_first_request = request_key in in_flight and not in_flight[request_key].is_set()
    return is_first_request, None
