"""
Race Mode Routes - Head-to-head API vs uBuyFirst comparison with full AI pipeline
Extracted from main.py for modularity

This module contains:
- /race/* endpoints for head-to-head race comparison
- Full AI pipeline integration (calls /match_mydata internally)
- Race state management (RACE_DATA, RACE_TASK)
- Helper functions for race matching and winner determination
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse

import httpx

logger = logging.getLogger(__name__)

# Create router for race endpoints
router = APIRouter(tags=["race"])

# ============================================================
# MODULE-LEVEL STATE
# ============================================================

# Race tracking storage
RACE_DATA: Dict = {
    "active": False,
    "keyword": "",
    "api_items": [],  # List of {item_id, title, price, seller, latency, found_time}
    "ubf_items": [],  # Same structure
    "api_wins": 0,
    "ubf_wins": 0,
    "ties": 0,
    "seen_items": {},  # item_id -> {api_time, ubf_time, winner}
}
RACE_TASK: Optional[asyncio.Task] = None

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_race)
# ============================================================

_config: Dict = {
    "BLOCKED_SELLERS": set(),
    "INSTANT_PASS_KEYWORDS": [],
    "UBF_TITLE_FILTERS": [],
    "UBF_LOCATION_FILTERS": [],
    "UBF_FEEDBACK_RULES": {"min_feedback_score": 3, "max_feedback_score": 30000},
    "dashboard_path": None,
}


def configure_race(
    BLOCKED_SELLERS: set,
    INSTANT_PASS_KEYWORDS: list,
    UBF_TITLE_FILTERS: list,
    UBF_LOCATION_FILTERS: list,
    UBF_FEEDBACK_RULES: dict,
    dashboard_path: Path = None,
):
    """Configure the race module with filter settings."""
    global _config

    _config["BLOCKED_SELLERS"] = BLOCKED_SELLERS
    _config["INSTANT_PASS_KEYWORDS"] = INSTANT_PASS_KEYWORDS
    _config["UBF_TITLE_FILTERS"] = UBF_TITLE_FILTERS
    _config["UBF_LOCATION_FILTERS"] = UBF_LOCATION_FILTERS
    _config["UBF_FEEDBACK_RULES"] = UBF_FEEDBACK_RULES
    _config["dashboard_path"] = dashboard_path or Path(__file__).parent.parent / "race_dashboard.html"

    logger.info("[RACE ROUTES] Module configured")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def race_make_key(title: str, seller: str, price: float) -> str:
    """Create a normalized key for matching items between API and UBF"""
    # Normalize title: lowercase, remove URL encoding, take first 50 chars
    title_norm = title.lower().replace('+', ' ').replace('%20', ' ')[:50].strip()
    seller_norm = seller.lower().replace('+', ' ')[:20].strip()
    # Round price to nearest dollar to handle slight variations
    price_norm = int(round(price))
    return f"{title_norm}|{seller_norm}|{price_norm}"


def race_check_winner(item_id: str, source: str, latency: int, title: str = "", seller: str = "", price: float = 0):
    """Check if this item was already found by the other source"""
    global RACE_DATA

    # Use normalized key instead of item_id for matching
    match_key = race_make_key(title, seller, price) if title else item_id

    if match_key in RACE_DATA["seen_items"]:
        existing = RACE_DATA["seen_items"][match_key]
        if existing.get("winner"):
            return  # Already determined

        existing[source] = datetime.now()

        # Both found - determine winner
        if "api" in existing and "ubf" in existing:
            diff = (existing["api"] - existing["ubf"]).total_seconds()
            if abs(diff) < 5:
                existing["winner"] = "tie"
                RACE_DATA["ties"] += 1
            elif diff < 0:
                existing["winner"] = "api"
                RACE_DATA["api_wins"] += 1
            else:
                existing["winner"] = "ubf"
                RACE_DATA["ubf_wins"] += 1

            logger.info(f"[RACE] Winner: {existing['winner']} (diff={diff:.1f}s) - {title[:40]}")
    else:
        RACE_DATA["seen_items"][match_key] = {source: datetime.now()}


def race_log_ubf_item(item_id: str, title: str, price: float, seller: str, latency: int):
    """Called from match_mydata when uBuyFirst sends an item"""
    global RACE_DATA

    if not RACE_DATA["active"]:
        return

    # Check if this item matches our race keyword
    keyword_lower = RACE_DATA["keyword"].lower()
    title_lower = title.lower().replace('+', ' ')  # Handle URL-encoded titles

    # Match if keyword is in title OR category matches (gold/silver)
    keyword_match = keyword_lower in title_lower
    gold_match = "gold" in keyword_lower and "gold" in title_lower
    silver_match = "silver" in keyword_lower and ("silver" in title_lower or "sterling" in title_lower)

    if not keyword_match and not gold_match and not silver_match:
        logger.debug(f"[RACE-UBF] Filtered - no match: keyword='{keyword_lower}', title='{title_lower[:50]}'")
        return  # Not relevant to our race

    logger.info(f"[RACE-UBF] MATCH! keyword={keyword_match}, gold={gold_match}, silver={silver_match}, title={title[:40]}")

    item_data = {
        "item_id": item_id,
        "title": title[:80],
        "price": price,
        "seller": seller,
        "latency": latency,
        "found_time": datetime.now().isoformat(),
    }

    RACE_DATA["ubf_items"].append(item_data)
    race_check_winner(item_id, "ubf", latency, title, seller, price)
    logger.info(f"[RACE-UBF] Found: {title[:40]}... latency={latency}ms")


# ============================================================
# RACE POLL LOOP
# ============================================================

async def race_poll_loop(keyword: str):
    """Aggressive polling loop for race mode - with same filters as uBuyFirst

    FULL AI PIPELINE:
    - Same blocked sellers and filters as uBuyFirst
    - Calls /match_mydata internally for full AI analysis (GPT-4o-mini)
    - Only sends BUY and RESEARCH to Discord
    - PASS items are filtered silently
    """
    # Import ebay_poller functions locally to avoid circular imports
    from ebay_poller import search_ebay, send_discord_listing

    BLOCKED_SELLERS = _config["BLOCKED_SELLERS"]
    INSTANT_PASS_KEYWORDS = _config["INSTANT_PASS_KEYWORDS"]
    UBF_TITLE_FILTERS = _config["UBF_TITLE_FILTERS"]
    UBF_LOCATION_FILTERS = _config["UBF_LOCATION_FILTERS"]
    UBF_FEEDBACK_RULES = _config["UBF_FEEDBACK_RULES"]

    logger.info(f"[RACE] Poll loop started for '{keyword}'")
    logger.info(f"[RACE] === FILTERS FROM FiltersExport CSV ===")
    logger.info(f"[RACE] 1. Blocked sellers: {len(BLOCKED_SELLERS)}")
    logger.info(f"[RACE] 2. Numeric seller names: enabled (>70% digits)")
    logger.info(f"[RACE] 3. Instant-pass keywords: {len(INSTANT_PASS_KEYWORDS)} (plated, filled, etc.)")
    logger.info(f"[RACE] 4. UBF title filters: {len(UBF_TITLE_FILTERS)} (prizm, coins, railroad, etc.)")
    logger.info(f"[RACE] 5. Location filters: {len(UBF_LOCATION_FILTERS)} (Japan, China, Australia, etc.)")
    logger.info(f"[RACE] 6. Feedback score: min={UBF_FEEDBACK_RULES['min_feedback_score']}, max={UBF_FEEDBACK_RULES['max_feedback_score']}")
    logger.info(f"[RACE] 7. Condition filters: For parts, tags, New other")
    logger.info(f"[RACE] 8. Seller country in location: Japan, China, France, etc.")
    logger.info(f"[RACE] 9. Freshness: max 5 minutes old")
    logger.info(f"[RACE] 10. Full AI pipeline: /match_mydata (same as uBuyFirst)")
    logger.info(f"[RACE] =======================================")

    seen_ids = set()
    newest_timestamp = None  # Track newest item for efficient polling with itemStartDate filter
    filtered_counts = {
        "blocked_seller": 0,
        "numeric_seller": 0,
        "instant_pass": 0,
        "ubf_title": 0,
        "location": 0,
        "feedback_low": 0,
        "feedback_high": 0,
        "condition": 0,
        "seller_country": 0,
        "stale": 0
    }

    while RACE_DATA["active"]:
        try:
            # Poll eBay API with itemStartDate filter for efficiency
            # First poll: no filter (get baseline), subsequent polls: only items newer than newest_timestamp
            listings = await search_ebay(
                keywords=keyword,
                category_ids=["281"],  # Jewelry
                price_min=50,
                price_max=10000,
                entries_per_page=50,
                since_date=newest_timestamp,  # Only fetch items newer than this
            )

            # Log efficiency stats
            if newest_timestamp:
                logger.info(f"[RACE] Efficient poll: {len(listings)} new items (since {newest_timestamp.strftime('%H:%M:%S')})")
            else:
                logger.info(f"[RACE] Initial poll: {len(listings)} items (building baseline)")

            now = datetime.now()

            for listing in listings:
                if listing.item_id in seen_ids:
                    continue

                seen_ids.add(listing.item_id)

                # Update newest_timestamp for ALL items (even filtered ones) for efficient polling
                if listing.start_time:
                    if newest_timestamp is None or listing.start_time > newest_timestamp:
                        newest_timestamp = listing.start_time

                title_lower = listing.title.lower()

                # FILTER 1: Blocked sellers (4700+ sellers)
                seller_lower = (listing.seller_id or "").lower().strip()
                if seller_lower in BLOCKED_SELLERS:
                    filtered_counts["blocked_seller"] += 1
                    logger.debug(f"[RACE] Filtered blocked seller: {listing.seller_id}")
                    continue

                # FILTER 1b: Numeric seller names (spam pattern from FiltersExport)
                # Sellers with names that are mostly digits are often spam
                if seller_lower and len(seller_lower) >= 5:
                    digit_count = sum(1 for c in seller_lower if c.isdigit())
                    if digit_count / len(seller_lower) > 0.7:  # >70% digits = spam
                        if "numeric_seller" not in filtered_counts:
                            filtered_counts["numeric_seller"] = 0
                        filtered_counts["numeric_seller"] += 1
                        logger.debug(f"[RACE] Filtered numeric seller: {listing.seller_id}")
                        continue

                # FILTER 2: Instant-pass keywords (gold plated, silver plated, etc.)
                skip_instant = False
                for kw in INSTANT_PASS_KEYWORDS:
                    if kw in title_lower:
                        skip_instant = True
                        filtered_counts["instant_pass"] += 1
                        logger.debug(f"[RACE] Filtered instant-pass '{kw}': {listing.title[:40]}")
                        break
                if skip_instant:
                    continue

                # FILTER 3: UBF title keywords (prizm, coins, railroad, etc.)
                skip_ubf = False
                for kw in UBF_TITLE_FILTERS:
                    if kw in title_lower:
                        skip_ubf = True
                        filtered_counts["ubf_title"] += 1
                        logger.debug(f"[RACE] Filtered UBF title '{kw}': {listing.title[:40]}")
                        break
                if skip_ubf:
                    continue

                # FILTER 4: Location (China, Japan, Australia, etc.)
                location_lower = (listing.location or "").lower()
                skip_location = False
                for loc in UBF_LOCATION_FILTERS:
                    if loc in location_lower:
                        skip_location = True
                        filtered_counts["location"] += 1
                        logger.debug(f"[RACE] Filtered location '{loc}': {listing.location}")
                        break
                if skip_location:
                    continue

                # FILTER 5: Feedback score < 3 (new/no feedback sellers)
                feedback_score = listing.seller_feedback or 0
                if feedback_score < UBF_FEEDBACK_RULES['min_feedback_score']:
                    filtered_counts["feedback_low"] += 1
                    logger.debug(f"[RACE] Filtered low feedback ({feedback_score}): {listing.seller_id}")
                    continue

                # FILTER 6: Feedback score > 30K (big business sellers)
                if feedback_score > UBF_FEEDBACK_RULES['max_feedback_score']:
                    filtered_counts["feedback_high"] += 1
                    logger.debug(f"[RACE] Filtered high feedback ({feedback_score}): {listing.seller_id}")
                    continue

                # FILTER 7: Condition filters (tags, For parts, New other)
                condition_lower = (listing.condition or "").lower()
                skip_condition = False
                bad_conditions = ['for parts', 'parts only', 'tags', 'new other']
                for bad_cond in bad_conditions:
                    if bad_cond in condition_lower:
                        skip_condition = True
                        if "condition" not in filtered_counts:
                            filtered_counts["condition"] = 0
                        filtered_counts["condition"] += 1
                        logger.debug(f"[RACE] Filtered condition '{bad_cond}': {listing.condition}")
                        break
                if skip_condition:
                    continue

                # FILTER 8: Seller country in location field (Browse API puts country in location sometimes)
                # Check for international in the full location string
                location_full = (listing.location or "").lower()
                seller_country_skip = False
                country_keywords = ['japan', 'china', 'hong kong', 'shanghai', 'shenzen', 'tokyo',
                                   'australia', 'india', 'france', 'germany', 'uk', 'united kingdom']
                for country in country_keywords:
                    if country in location_full:
                        seller_country_skip = True
                        if "seller_country" not in filtered_counts:
                            filtered_counts["seller_country"] = 0
                        filtered_counts["seller_country"] += 1
                        logger.debug(f"[RACE] Filtered seller country '{country}' in: {listing.location}")
                        break
                if seller_country_skip:
                    continue

                # Calculate latency
                latency_ms = 999999
                if listing.start_time:
                    try:
                        if listing.start_time.tzinfo:
                            now_tz = datetime.now(timezone.utc)
                        else:
                            now_tz = datetime.now()
                        latency_ms = int((now_tz - listing.start_time).total_seconds() * 1000)
                    except:
                        pass

                # Check freshness - only items from last 5 minutes
                if latency_ms > 300000:  # 5 min
                    filtered_counts["stale"] += 1
                    continue

                # ============================================================
                # FULL AI PIPELINE ANALYSIS
                # Same pipeline as uBuyFirst - calls /match_mydata internally
                # ============================================================
                try:
                    # Format listing data to match uBuyFirst format
                    analysis_data = {
                        "Title": listing.title,
                        "TotalPrice": f"${listing.price:.2f}",
                        "ItemPrice": f"${listing.price:.2f}",
                        "Alias": keyword,
                        "SellerName": listing.seller_id or "",
                        "FeedbackScore": str(listing.seller_feedback or 0),
                        "FeedbackRating": "99.0",  # Default, not available from Browse API
                        "FromCountry": "US",
                        "Condition": "Used",
                        "CategoryName": "Jewelry",
                        "PostedTime": listing.start_time.strftime("%m/%d/%Y %I:%M:%S %p") if listing.start_time else "",
                        "ViewUrl": listing.view_url or "",
                        "images": listing.image_urls[:6] if hasattr(listing, 'image_urls') and listing.image_urls else [],
                        "response_type": "json",
                        "llm_provider": "openai",
                        "llm_model": "openai/gpt-4o-mini",
                    }

                    # Make internal HTTP call to /match_mydata
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            "http://127.0.0.1:8000/match_mydata",
                            json=analysis_data,
                            headers={"Content-Type": "application/json"}
                        )

                        if response.status_code == 200:
                            result = response.json()
                            recommendation = result.get("Recommendation", "PASS")
                            reasoning = result.get("reasoning", result.get("Qualify", ""))[:100]
                            melt_value = None
                            max_buy = None

                            # Extract melt/max values if present
                            melt_str = result.get("meltvalue", result.get("melt", ""))
                            if melt_str and melt_str != "NA":
                                try:
                                    melt_value = float(str(melt_str).replace("$", "").replace(",", ""))
                                except:
                                    pass

                            max_str = result.get("maxBuy", "")
                            if max_str and max_str != "NA":
                                try:
                                    max_buy = float(str(max_str).replace("$", "").replace(",", ""))
                                except:
                                    pass

                            logger.info(f"[RACE-API] AI Result: {recommendation} - {listing.title[:40]}...")
                        else:
                            logger.warning(f"[RACE-API] Analysis failed ({response.status_code}): {listing.title[:40]}")
                            recommendation = "RESEARCH"
                            reasoning = "Analysis failed - manual review needed"
                            melt_value = None
                            max_buy = None

                except Exception as analysis_error:
                    logger.error(f"[RACE-API] Analysis error: {analysis_error}")
                    recommendation = "RESEARCH"
                    reasoning = f"Analysis error: {str(analysis_error)[:50]}"
                    melt_value = None
                    max_buy = None

                item_data = {
                    "item_id": listing.item_id,
                    "title": listing.title[:80],
                    "price": listing.price,
                    "seller": listing.seller_id,
                    "latency": latency_ms,
                    "found_time": now.isoformat(),
                    "recommendation": recommendation,
                    "reasoning": reasoning,
                    "melt_value": melt_value,
                    "max_buy": max_buy,
                }

                RACE_DATA["api_items"].append(item_data)

                # Check if uBuyFirst already found this (match by title+seller+price)
                race_check_winner(listing.item_id, "api", latency_ms, listing.title, listing.seller_id or "", listing.price)

                # Only send BUY and RESEARCH to Discord
                if recommendation in ("BUY", "RESEARCH"):
                    await send_discord_listing(listing, keyword, f"RACE-API-{recommendation}", recommendation, reasoning, melt_value, max_buy)
                    logger.info(f"[RACE-API] {recommendation}: {listing.title[:40]}... ${listing.price} - {reasoning}")
                else:
                    logger.debug(f"[RACE-API] PASS: {listing.title[:40]}... ${listing.price} - {reasoning}")

        except Exception as e:
            logger.error(f"[RACE] Poll error: {e}")

        # Aggressive 3-second polling
        await asyncio.sleep(3)


# ============================================================
# RACE ENDPOINTS
# ============================================================

@router.get("/race")
async def race_dashboard():
    """Serve the race dashboard HTML"""
    dashboard_path = _config["dashboard_path"]
    if dashboard_path and dashboard_path.exists():
        return Response(
            content=dashboard_path.read_text(encoding='utf-8'),
            media_type="text/html"
        )
    return {"error": "race_dashboard.html not found"}


@router.get("/race/data")
async def race_data():
    """Get current race data for dashboard"""
    # Get recent items only (last 100)
    return {
        "active": RACE_DATA["active"],
        "keyword": RACE_DATA["keyword"],
        "skip_api": RACE_DATA.get("skip_api", False),
        "api_items": RACE_DATA["api_items"][-50:],
        "ubf_items": RACE_DATA["ubf_items"][-50:],
        "api_wins": RACE_DATA["api_wins"],
        "ubf_wins": RACE_DATA["ubf_wins"],
        "ties": RACE_DATA["ties"],
    }


@router.post("/race/start")
async def race_start(keyword: str = "14K Gold", skip_api: bool = False):
    """Start racing on a specific keyword

    Args:
        keyword: The keyword to track (e.g., "14K Gold", "Sterling Silver")
        skip_api: If True, only track uBuyFirst items (no direct API polling)
    """
    global RACE_TASK, RACE_DATA

    # Reset race data
    RACE_DATA = {
        "active": True,
        "keyword": keyword,
        "skip_api": skip_api,
        "api_items": [],
        "ubf_items": [],
        "api_wins": 0,
        "ubf_wins": 0,
        "ties": 0,
        "seen_items": {},
    }

    # Start polling task (only if not skipping API)
    if RACE_TASK:
        RACE_TASK.cancel()
        RACE_TASK = None

    if not skip_api:
        RACE_TASK = asyncio.create_task(race_poll_loop(keyword))
        logger.info(f"[RACE] Started racing on keyword: {keyword} (API polling enabled)")
    else:
        logger.info(f"[RACE] Started tracking on keyword: {keyword} (UBF only, no API polling)")

    return {"status": "started", "keyword": keyword, "skip_api": skip_api}


@router.post("/race/stop")
async def race_stop():
    """Stop the race"""
    global RACE_TASK, RACE_DATA

    RACE_DATA["active"] = False
    if RACE_TASK:
        RACE_TASK.cancel()
        RACE_TASK = None

    logger.info("[RACE] Race stopped")
    return {"status": "stopped", "results": {
        "api_wins": RACE_DATA["api_wins"],
        "ubf_wins": RACE_DATA["ubf_wins"],
        "ties": RACE_DATA["ties"],
    }}
