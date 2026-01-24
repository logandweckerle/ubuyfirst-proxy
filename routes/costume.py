"""
Costume Jewelry Routes - Dedicated costume jewelry analysis endpoint
Extracted from main.py for modularity

This module contains:
- /costume endpoint for costume jewelry analysis
- /api/costume/outcome endpoint for recording purchase outcomes
- /api/costume/outcomes endpoint for retrieving outcomes
- Costume-specific validation rules (Trifari, designer tiers, etc.)
"""

import json
import uuid
import sqlite3
import logging
import traceback
from datetime import datetime
from urllib.parse import parse_qs
from typing import Dict, Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse

logger = logging.getLogger(__name__)

# Create router for costume jewelry endpoints
router = APIRouter(tags=["costume"])

# ============================================================
# MODULE-LEVEL STATE
# ============================================================

# Track actual outcomes to improve AI accuracy over time
COSTUME_OUTCOMES = []  # In-memory, also saved to DB

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_costume)
# ============================================================

_config: Dict = {
    "client": None,  # Anthropic client
    "cache": None,  # Smart cache
    "STATS": None,  # Global stats dict
    "ENABLED": True,  # Global enabled flag getter
    "DB_PATH": None,
    "MODEL_FAST": "claude-3-haiku-20240307",
    "COST_PER_CALL_HAIKU": 0.001,
    "get_system_context": None,
    "get_agent": None,
    "log_incoming_listing": None,
    "save_listing": None,
    "update_pattern_outcome": None,
    "process_image_list": None,
    "render_result_html": None,
    "format_listing_data": None,
    "sanitize_json_response": None,
}


def configure_costume(
    client,
    cache,
    STATS: dict,
    get_enabled: Callable,
    DB_PATH,
    MODEL_FAST: str,
    COST_PER_CALL_HAIKU: float,
    get_system_context: Callable,
    get_agent: Callable,
    log_incoming_listing: Callable,
    save_listing: Callable,
    update_pattern_outcome: Callable,
    process_image_list: Callable,
    render_result_html: Callable,
    format_listing_data: Callable,
    sanitize_json_response: Callable,
):
    """Configure the costume module with all required dependencies."""
    global _config

    _config["client"] = client
    _config["cache"] = cache
    _config["STATS"] = STATS
    _config["get_enabled"] = get_enabled
    _config["DB_PATH"] = DB_PATH
    _config["MODEL_FAST"] = MODEL_FAST
    _config["COST_PER_CALL_HAIKU"] = COST_PER_CALL_HAIKU
    _config["get_system_context"] = get_system_context
    _config["get_agent"] = get_agent
    _config["log_incoming_listing"] = log_incoming_listing
    _config["save_listing"] = save_listing
    _config["update_pattern_outcome"] = update_pattern_outcome
    _config["process_image_list"] = process_image_list
    _config["render_result_html"] = render_result_html
    _config["format_listing_data"] = format_listing_data
    _config["sanitize_json_response"] = sanitize_json_response

    logger.info("[COSTUME ROUTES] Module configured")


# ============================================================
# COSTUME JEWELRY ENDPOINT
# ============================================================

@router.post("/costume")
@router.get("/costume")
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
    # Get dependencies
    client = _config["client"]
    cache = _config["cache"]
    STATS = _config["STATS"]
    get_enabled = _config["get_enabled"]
    MODEL_FAST = _config["MODEL_FAST"]
    COST_PER_CALL_HAIKU = _config["COST_PER_CALL_HAIKU"]
    get_system_context = _config["get_system_context"]
    get_agent = _config["get_agent"]
    log_incoming_listing = _config["log_incoming_listing"]
    save_listing = _config["save_listing"]
    update_pattern_outcome = _config["update_pattern_outcome"]
    process_image_list = _config["process_image_list"]
    render_result_html = _config["render_result_html"]
    format_listing_data = _config["format_listing_data"]
    sanitize_json_response = _config["sanitize_json_response"]

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

        if not get_enabled():
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
                    logger.info(f"[COSTUME] Override: BUY->RESEARCH (low quality score {quality_score})")

                # RULE 2: Price per piece too high for generic lot
                if ai_rec == 'BUY' and itemtype == 'Lot' and has_trifari != 'Yes' and piece_count > 0:
                    if actual_ppp > 2.50 and quality_score < 25:
                        result['Recommendation'] = 'RESEARCH'
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: ${actual_ppp:.2f}/piece too high for quality {quality_score}]"
                        logger.info(f"[COSTUME] Override: BUY->RESEARCH (${actual_ppp:.2f}/pc, quality {quality_score})")

                # RULE 3: Tier 4 designer (fashion brands) = always PASS
                if designer_tier == '4' and ai_rec == 'BUY':
                    result['Recommendation'] = 'PASS'
                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Tier 4 fashion brand - PASS]"
                    logger.info(f"[COSTUME] Override: BUY->PASS (Tier 4 fashion brand)")

                # RULE 4: Single unsigned piece over $25 = PASS
                if piece_count == 1 and has_trifari != 'Yes' and price_float > 25 and ai_rec == 'BUY':
                    result['Recommendation'] = 'PASS'
                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Single unsigned piece >$25 - PASS]"
                    logger.info(f"[COSTUME] Override: BUY->PASS (single unsigned >$25)")

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
# COSTUME JEWELRY OUTCOME TRACKING
# ============================================================

@router.post("/api/costume/outcome")
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


@router.get("/api/costume/outcomes")
async def get_costume_outcomes():
    """Get all recorded costume jewelry outcomes for analysis"""
    return {
        "count": len(COSTUME_OUTCOMES),
        "outcomes": COSTUME_OUTCOMES,
        "summary": calculate_costume_summary()
    }


def save_costume_outcome(outcome: dict):
    """Save costume outcome to database"""
    DB_PATH = _config["DB_PATH"]
    if not DB_PATH:
        logger.warning("[COSTUME] DB_PATH not configured, skipping save")
        return

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
