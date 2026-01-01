"""
Claude Proxy Server v3 - Optimized
Enhanced with async image fetching, smart caching, and connection pooling

Optimizations:
1. Async parallel image fetching (httpx) - 2-4 seconds faster per listing
2. Database connection pooling with WAL mode - faster writes
3. Smart cache with different TTLs for BUY vs PASS results
4. Modular code structure for maintainability
5. Background workers for spot price updates and cache cleanup
"""

import os
import sys
import json
import uuid
import asyncio
import logging
from datetime import datetime
from urllib.parse import parse_qs
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import anthropic
import uvicorn

# Import our optimized modules
from config import (
    HOST, PORT, CLAUDE_API_KEY, MODEL_FAST, MODEL_FULL,
    COST_PER_CALL_HAIKU, CACHE, SPOT_PRICES
)
from database import (
    db, save_listing, log_incoming_listing, update_pattern_outcome,
    get_analytics, get_pattern_analytics, extract_title_keywords
)
from smart_cache import cache, start_cache_cleanup
from image_fetcher import fetch_images_parallel, process_image_list
from spot_prices import fetch_spot_prices, start_spot_updates, get_spot_prices
from prompts import get_category_prompt, get_business_context, detect_category, get_gold_prompt, get_silver_prompt

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
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="Claude Proxy v3 - Optimized",
    description="eBay arbitrage analyzer with async image fetching and smart caching"
)

# Claude client
client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# ============================================================
# STATE MANAGEMENT
# ============================================================
ENABLED = True  # Start enabled for testing
DEBUG_MODE = False
QUEUE_MODE = False  # Queue mode OFF - auto-analyze immediately

# Queue for manual review mode
LISTING_QUEUE: Dict[str, Dict] = {}

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
# STARTUP EVENTS
# ============================================================
@app.on_event("startup")
async def startup_event():
    """Initialize background tasks on startup"""
    logger.info("=" * 60)
    logger.info("Claude Proxy v3 - Optimized Starting...")
    logger.info("=" * 60)
    
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
    
    logger.info(f"Server ready at http://{HOST}:{PORT}")
    logger.info("=" * 60)


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
        "–": "-", "→": "->", "×": "x", "…": "...", "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = " ".join(text.split())
    return text.strip()


def validate_and_fix_margin(result: dict, listing_price, category: str) -> dict:
    """
    Server-side validation of AI's math.
    Recalculates melt, maxBuy, margin and forces PASS if negative.
    """
    try:
        # Clean listing price (handle strings like "$1499" or "1499")
        if isinstance(listing_price, str):
            listing_price = float(listing_price.replace('$', '').replace(',', ''))
        else:
            listing_price = float(listing_price)
        
        # Get spot prices
        gold_oz = SPOT_PRICES.get("gold_oz", 2650)
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        
        # Karat rates
        karat_rates = {
            "10K": gold_oz / 31.1035 * 0.417,
            "14K": gold_oz / 31.1035 * 0.583,
            "18K": gold_oz / 31.1035 * 0.75,
            "22K": gold_oz / 31.1035 * 0.917,
            "24K": gold_oz / 31.1035,
        }
        sterling_rate = silver_oz / 31.1035 * 0.925
        
        # Get gold weight (after deductions) - prefer this over total weight
        gold_weight_str = str(result.get('goldweight', result.get('silverweight', result.get('weight', '0'))))
        gold_weight_str = gold_weight_str.replace('g', '').replace(' est', '').replace('NA', '0').strip()
        try:
            gold_weight = float(gold_weight_str) if gold_weight_str else 0
        except:
            gold_weight = 0
        
        # Get karat for gold category
        karat = result.get('karat', '14K')
        
        # Calculate melt value if missing or invalid
        melt_str = str(result.get('meltvalue', '$--'))
        needs_melt_calc = melt_str in ['$--', '--', 'NA', '', '0', 'None'] or not melt_str.replace('$','').replace('.','').replace('-','').isdigit()
        
        if needs_melt_calc and gold_weight > 0:
            if category == "gold":
                rate = karat_rates.get(karat, karat_rates["14K"])
                melt_value = gold_weight * rate
            elif category == "silver":
                melt_value = gold_weight * sterling_rate
            else:
                melt_value = 0
            
            if melt_value > 0:
                result['meltvalue'] = f"{melt_value:.0f}"
                logger.info(f"[CALC] Melt value calculated: {gold_weight}g × ${rate:.2f} = ${melt_value:.0f}")
        else:
            try:
                melt_value = float(melt_str.replace('$', '').replace(',', ''))
            except:
                melt_value = 0
        
        # Get or calculate maxBuy
        max_buy_str = str(result.get('maxBuy', '0'))
        try:
            max_buy = float(max_buy_str.replace('$', '').replace(',', ''))
        except:
            max_buy = 0
        
        # If maxBuy is 0 or seems wrong, recalculate from melt
        if max_buy == 0 and melt_value > 0:
            if category == "gold":
                max_buy = melt_value * 0.90
            elif category == "silver":
                max_buy = melt_value * 0.75
            result['maxBuy'] = f"{max_buy:.0f}"
            logger.info(f"[CALC] maxBuy calculated: ${melt_value:.0f} × 0.90 = ${max_buy:.0f}")
        
        # Calculate correct margin
        correct_margin = max_buy - listing_price
        
        # Get AI's reported margin for comparison
        ai_margin_str = str(result.get('Margin', '0'))
        try:
            ai_margin = float(ai_margin_str.replace('$', '').replace('+', '').replace(',', ''))
            if ai_margin_str.startswith('-') or '-' in ai_margin_str:
                ai_margin = -abs(ai_margin)
        except:
            ai_margin = 0
        
        # Check if AI got it wrong
        if abs(correct_margin - ai_margin) > 5:  # Allow $5 tolerance for rounding
            logger.warning(f"MATH FIX: AI margin={ai_margin_str}, Correct margin=${correct_margin:.2f} (maxBuy=${max_buy:.2f} - listing=${listing_price:.2f})")
            result['Margin'] = f"{correct_margin:+.0f}"
            result['reasoning'] = result.get('reasoning', '') + f" [SERVER RECALC: maxBuy ${max_buy:.0f} - listing ${listing_price:.0f} = ${correct_margin:.0f}]"
        
        # Force PASS if margin is negative
        if correct_margin < 0 and result.get('Recommendation') == 'BUY':
            logger.warning(f"OVERRIDE: Forcing PASS (recalculated margin=${correct_margin:.2f})")
            result['Recommendation'] = 'PASS'
            result['Margin'] = f"{correct_margin:.0f}"
        
    except (ValueError, TypeError) as e:
        logger.error(f"Could not validate margin: {e}")
        import traceback
        traceback.print_exc()
    
    return result


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
    import uuid
    
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
        response_type = data.get('response_type', 'html')  # Save early!
        listing_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        
        logger.info(f"Title: {title[:50]}")
        logger.info(f"Price: ${total_price}")
        logger.info(f"[SAVED] response_type: {response_type}")
        
        STATS["total_requests"] += 1
        
        # ============================================================
        # CHECK SMART CACHE FIRST
        # ============================================================
        cached = cache.get(title, total_price)
        if cached:
            result, html = cached
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
            log_incoming_listing(data, category, 'queued')
            
            # Store raw image URLs for later (don't fetch yet - saves time)
            raw_images = data.get('images', [])
            
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
        
        # Log for pattern analysis
        log_incoming_listing(data, category, 'analyzing')
        
        # Fetch images in parallel (async!)
        if 'images' in data and data['images']:
            images = await process_image_list(data['images'])
            logger.info(f"Fetched {len(images)} images")
        
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
        
        # Call Claude API
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=500,
            system=get_business_context(),
            messages=[{"role": "user", "content": message_content}]
        )
        
        raw_response = response.content[0].text.strip()
        response_text = sanitize_json_response(raw_response)
        
        try:
            result = json.loads(response_text)
            
            if 'reasoning' in result:
                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')
            
            # Add listing price to result for display
            result['listingPrice'] = total_price
            
            # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong
            result = validate_and_fix_margin(result, total_price, category)
            
            recommendation = result.get('Recommendation', 'RESEARCH')
            
            # Update stats
            if recommendation == "BUY":
                STATS["buy_count"] += 1
            elif recommendation == "PASS":
                STATS["pass_count"] += 1
            else:
                STATS["research_count"] += 1
            
            # Create listing record
            listing_record = {
                "id": listing_id,
                "timestamp": timestamp,
                "title": title,
                "total_price": total_price,
                "category": category,
                "recommendation": recommendation,
                "margin": result.get('Margin', 'NA'),
                "confidence": result.get('confidence', 'NA'),
                "reasoning": result.get('reasoning', ''),
                "raw_response": raw_response,
                "input_data": {k: v for k, v in data.items() if k != 'images'}
            }
            
            STATS["listings"][listing_id] = listing_record
            _trim_listings()
            
            # Save to database
            save_listing(listing_record)
            
            # Update pattern analytics
            update_pattern_outcome(title, category, recommendation)
            
            # Add price for display
            result['listingPrice'] = total_price
            
            # Add category to result
            result['category'] = category
            
            # Render HTML
            html = render_result_html(result, category)
            
            # Store in smart cache
            cache.set(title, total_price, result, html, recommendation, category)
            
            logger.info(f"Result: {recommendation}")
            logger.info(f"[RESPONSE] Keys: {list(result.keys())}")
            
            # Use saved response_type (saved early in the function)
            logger.info(f"[RESPONSE] response_type: {response_type}")
            
            if response_type == 'json':
                # Return pure JSON for column population
                logger.info("[RESPONSE] Returning JSON (response_type=json)")
                return JSONResponse(content=result)
            else:
                # Return HTML for display
                logger.info("[RESPONSE] Returning HTML (response_type=html)")
                return HTMLResponse(content=html)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            error_result = {
                "Qualify": "No", "Recommendation": "RESEARCH",
                "reasoning": f"Parse error - manual review needed",
                "confidence": "Low"
            }
            return JSONResponse(content=error_result)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
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
        log_incoming_listing(data, category, 'analyzing')
        
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
        
        # Call Claude API
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=600,
            system=get_business_context(),
            messages=[{"role": "user", "content": message_content}]
        )
        
        raw_response = response.content[0].text.strip()
        response_text = sanitize_json_response(raw_response)
        
        try:
            result = json.loads(response_text)
            
            if 'reasoning' in result:
                result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')
            
            result['listingPrice'] = total_price
            result['category'] = 'costume'
            
            recommendation = result.get('Recommendation', 'RESEARCH')
            
            # Update stats
            if recommendation == "BUY":
                STATS["buy_count"] += 1
            elif recommendation == "PASS":
                STATS["pass_count"] += 1
            else:
                STATS["research_count"] += 1
            
            # Update pattern outcomes
            update_pattern_outcome(title, category, recommendation)
            
            # Render HTML
            html = _render_result_html(result, category)
            
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
        import traceback
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
        
        # Call Claude API
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=500,
            system=get_business_context(),
            messages=[{"role": "user", "content": message_content}]
        )
        
        raw_response = response.content[0].text.strip()
        response_text = sanitize_json_response(raw_response)
        result = json.loads(response_text)
        
        # Add listing price to result for display
        result['listingPrice'] = total_price
        
        # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong
        result = validate_and_fix_margin(result, total_price, category)
        
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
            "margin": result.get('Margin', 'NA'),
            "confidence": result.get('confidence', 'NA'),
            "reasoning": result.get('reasoning', ''),
            "raw_response": raw_response,
            "input_data": {k: v for k, v in data.items() if k != 'images'}
        }
        
        STATS["listings"][listing_id] = listing_record
        save_listing(listing_record)
        update_pattern_outcome(title, category, recommendation)
        
        # Cache the result so clicking in uBuyFirst again shows it
        result['listingPrice'] = total_price
        html = render_result_html(result, category)
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
        
        # Call Claude API
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=500,
            system=get_business_context(),
            messages=[{"role": "user", "content": message_content}]
        )
        
        raw_response = response.content[0].text.strip()
        response_text = sanitize_json_response(raw_response)
        result = json.loads(response_text)
        
        if 'reasoning' in result:
            result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')
        
        # Add listing price to result for display
        result['listingPrice'] = total_price
        
        # SERVER-SIDE MATH VALIDATION: Recalculate margin and fix if AI got it wrong
        result = validate_and_fix_margin(result, total_price, category)
        
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
            "margin": result.get('Margin', 'NA'),
            "confidence": result.get('confidence', 'NA'),
            "reasoning": result.get('reasoning', ''),
            "raw_response": raw_response,
            "input_data": {k: v for k, v in data.items() if k != 'images'}
        }
        
        STATS["listings"][listing_id] = listing_record
        save_listing(listing_record)
        update_pattern_outcome(title, category, recommendation)
        
        # Cache the result
        result['listingPrice'] = total_price
        result['category'] = category
        html = render_result_html(result, category)
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
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f'''
        <div style="background:#f8d7da;color:#721c24;padding:20px;border-radius:12px;text-align:center;">
        <div style="font-size:24px;font-weight:bold;">ERROR</div>
        <div style="margin-top:10px;">{str(e)[:100]}</div>
        </div>''')


# ============================================================
# TOGGLE ENDPOINTS
# ============================================================
@app.post("/toggle")
async def toggle_proxy():
    global ENABLED
    ENABLED = not ENABLED
    logger.info(f"Proxy {'ENABLED' if ENABLED else 'DISABLED'}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle-debug")
async def toggle_debug():
    global DEBUG_MODE
    DEBUG_MODE = not DEBUG_MODE
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle-queue")
async def toggle_queue():
    global QUEUE_MODE
    QUEUE_MODE = not QUEUE_MODE
    logger.info(f"Queue mode {'ENABLED' if QUEUE_MODE else 'DISABLED'}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/clear-queue")
async def clear_queue():
    global LISTING_QUEUE
    LISTING_QUEUE = {}
    return RedirectResponse(url="/", status_code=303)


@app.post("/reset-stats")
async def reset_stats():
    global STATS
    STATS = {
        "total_requests": 0, "api_calls": 0, "skipped": 0,
        "buy_count": 0, "pass_count": 0, "research_count": 0,
        "cache_hits": 0, "session_cost": 0.0,
        "session_start": datetime.now().isoformat(),
        "listings": {}
    }
    return RedirectResponse(url="/", status_code=303)


# ============================================================
# API ENDPOINTS
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "enabled": ENABLED, "queue_mode": QUEUE_MODE}


@app.get("/queue")
async def get_queue():
    return {"queue": list(LISTING_QUEUE.values()), "count": len(LISTING_QUEUE)}


@app.get("/api/spot-prices")
async def api_spot_prices():
    return get_spot_prices()


@app.get("/api/cache-stats")
async def api_cache_stats():
    return cache.get_stats()


@app.get("/api/analytics")
async def api_analytics():
    return get_analytics()


@app.get("/api/patterns")
async def api_patterns():
    return get_pattern_analytics()


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
            response = client.messages.create(
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
        import traceback
        traceback.print_exc()
        result = {
            "Qualify": "No",
            "Recommendation": "ERROR",
            "reasoning": f"Error: {str(e)[:50]}"
        }
        return JSONResponse(content=create_openai_response(result))


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


def render_result_html(result: dict, category: str) -> str:
    """Render analysis result as HTML based on category"""
    recommendation = result.get('Recommendation', 'RESEARCH')
    reasoning = result.get('reasoning', 'No reasoning provided')
    margin = result.get('Margin', result.get('margin', '--'))
    confidence = result.get('confidence', '--')
    
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
        info_items = [
            ('Karat', result.get('karat', '--')),
            ('Weight', result.get('weight', '--')),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Listing', f"${listing_price}"),
            ('Confidence', confidence),
        ]
    elif category == 'silver':
        listing_price = result.get('listingPrice', '--')
        info_items = [
            ('Type', result.get('itemtype', '--')),
            ('Weight', result.get('weight', '--')),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Listing', f"${listing_price}"),
            ('Confidence', confidence),
        ]
    elif category == 'tcg':
        info_items = [
            ('Brand', result.get('tcgbrand', '--')),
            ('Type', result.get('producttype', '--')),
            ('Set', result.get('setname', '--')),
            ('Market', f"${result.get('marketprice', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Risk', result.get('fakerisk', '--')),
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
    
    return f'''<!DOCTYPE html>
<html><head><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; background: {bg}; border: 3px solid {border}; }}
.status {{ font-size: 36px; font-weight: bold; color: {text_color}; margin-bottom: 5px; }}
.margin {{ font-size: 24px; font-weight: bold; color: {text_color}; margin-bottom: 10px; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 14px; font-weight: bold; color: #333; }}
</style></head><body>
<div class="container">
<div class="result-card">
<div class="status">{recommendation}</div>
<div class="margin">{margin}</div>
<div class="reason">{reasoning}</div>
<div class="info-grid">{info_html}</div>
</div></div></body></html>'''


# ============================================================
# DASHBOARD
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Main dashboard"""
    status = "ENABLED" if ENABLED else "DISABLED"
    status_class = "active" if ENABLED else "inactive"
    queue_status = "ON" if QUEUE_MODE else "OFF"
    
    # Get spot prices
    spots = get_spot_prices()
    
    # Get cache stats
    cache_stats = cache.get_stats()
    
    # Build recent listings HTML
    recent_html = ""
    sorted_listings = sorted(STATS["listings"].values(), key=lambda x: x["timestamp"], reverse=True)[:15]
    
    for listing in sorted_listings:
        rec = listing["recommendation"]
        rec_class = rec.lower()
        title = listing["title"][:55]
        margin = listing.get("margin", "--")
        lid = listing.get("id", "")
        
        recent_html += f'''
        <a href="/detail/{lid}" class="listing-item {rec_class}" style="text-decoration:none;color:inherit;">
            <span class="listing-rec">{rec}</span>
            <span class="listing-title">{title}</span>
            <span class="listing-margin">{margin}</span>
        </a>'''
    
    if not recent_html:
        recent_html = '<div style="text-align:center;color:#666;padding:20px;">No listings analyzed yet</div>'
    
    # Build queue HTML
    queue_html = ""
    for lid, q in list(LISTING_QUEUE.items())[:10]:
        queue_html += f'''
        <div class="queue-item">
            <div class="queue-title">{q["title"][:45]}...</div>
            <div class="queue-meta">{q["category"].upper()} | ${q["total_price"]}</div>
            <form action="/analyze-queued/{lid}" method="post" style="margin:0;">
                <button type="submit" class="analyze-btn">Analyze</button>
            </form>
        </div>'''
    
    if not queue_html:
        queue_html = '<div style="text-align:center;color:#666;padding:20px;">Queue empty</div>'
    
    return f"""<!DOCTYPE html>
<html><head>
<title>Claude Proxy v3 - Dashboard</title>
<meta http-equiv="refresh" content="5">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }}
.header {{ background: #1a1a2e; padding: 20px 30px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }}
.logo {{ font-size: 20px; font-weight: 700; color: #fff; }}
.logo span {{ color: #6366f1; }}
.nav {{ display: flex; gap: 15px; }}
.nav a {{ color: #888; text-decoration: none; padding: 8px 16px; border-radius: 6px; }}
.nav a:hover {{ color: #fff; background: rgba(255,255,255,0.1); }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
.stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }}
.stat-card {{ background: #1a1a2e; border-radius: 10px; padding: 20px; text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: 700; color: #fff; }}
.stat-label {{ font-size: 12px; color: #888; margin-top: 5px; }}
.stat-value.buy {{ color: #22c55e; }}
.stat-value.pass {{ color: #ef4444; }}
.controls {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }}
.btn {{ padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; }}
.btn-primary {{ background: #6366f1; color: #fff; }}
.btn-danger {{ background: #ef4444; color: #fff; }}
.btn-secondary {{ background: #333; color: #fff; }}
.status-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }}
.status-dot.active {{ background: #22c55e; }}
.status-dot.inactive {{ background: #ef4444; }}
.section {{ background: #1a1a2e; border-radius: 12px; margin-bottom: 20px; overflow: hidden; }}
.section-header {{ padding: 15px 20px; border-bottom: 1px solid #333; font-weight: 600; }}
.section-content {{ padding: 15px; max-height: 400px; overflow-y: auto; }}
.listing-item {{ display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 8px; margin-bottom: 8px; background: #252540; cursor: pointer; transition: background 0.2s; }}
.listing-item:hover {{ background: #303055; }}
.listing-item.buy {{ border-left: 4px solid #22c55e; }}
.listing-item.pass {{ border-left: 4px solid #ef4444; }}
.listing-item.research {{ border-left: 4px solid #f59e0b; }}
.listing-rec {{ font-weight: 700; width: 80px; }}
.listing-title {{ flex: 1; font-size: 14px; }}
.listing-margin {{ font-weight: 600; color: #888; }}
.queue-item {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px; background: #252540; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #2196f3; }}
.queue-title {{ flex: 1 1 100%; font-weight: 500; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.queue-meta {{ color: #888; font-size: 12px; flex: 1; }}
.analyze-btn {{ background: #2196f3; color: #fff; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }}
.spot-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; }}
.spot-item {{ background: #252540; padding: 10px; border-radius: 8px; text-align: center; }}
.spot-value {{ font-size: 18px; font-weight: 700; color: #22c55e; }}
.spot-label {{ font-size: 11px; color: #888; }}
</style>
</head><body>
<div class="header">
    <div class="logo">Claude <span>Proxy v3</span></div>
    <div class="nav">
        <a href="/">Dashboard</a>
        <a href="/patterns">Patterns</a>
        <a href="/analytics">Analytics</a>
    </div>
</div>
<div class="container">
    <div class="controls">
        <form action="/toggle" method="post" style="display:inline;">
            <button type="submit" class="btn {'btn-danger' if ENABLED else 'btn-primary'}">
                <span class="status-dot {status_class}"></span>{status} - Click to {'Disable' if ENABLED else 'Enable'}
            </button>
        </form>
        <form action="/toggle-queue" method="post" style="display:inline;">
            <button type="submit" class="btn btn-secondary">Queue Mode: {queue_status}</button>
        </form>
        <form action="/reset-stats" method="post" style="display:inline;">
            <button type="submit" class="btn btn-secondary">Reset Stats</button>
        </form>
    </div>
    
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-value">{STATS['total_requests']}</div>
            <div class="stat-label">Total Requests</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{STATS['api_calls']}</div>
            <div class="stat-label">API Calls</div>
        </div>
        <div class="stat-card">
            <div class="stat-value buy">{STATS['buy_count']}</div>
            <div class="stat-label">BUY</div>
        </div>
        <div class="stat-card">
            <div class="stat-value pass">{STATS['pass_count']}</div>
            <div class="stat-label">PASS</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{STATS['cache_hits']}</div>
            <div class="stat-label">Cache Hits</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{cache_stats['hit_rate']}</div>
            <div class="stat-label">Cache Hit Rate</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:#f59e0b">${STATS['session_cost']:.3f}</div>
            <div class="stat-label">Session Cost</div>
        </div>
        </div>
    </div>
    
    <div class="section">
        <div class="section-header">Spot Prices ({spots.get('source', 'default')})</div>
        <div class="section-content">
            <div class="spot-grid">
                <div class="spot-item">
                    <div class="spot-value">${spots.get('gold_oz', 0):,.0f}</div>
                    <div class="spot-label">Gold/oz</div>
                </div>
                <div class="spot-item">
                    <div class="spot-value">${spots.get('silver_oz', 0):.2f}</div>
                    <div class="spot-label">Silver/oz</div>
                </div>
                <div class="spot-item">
                    <div class="spot-value">${spots.get('14K', 0):.2f}</div>
                    <div class="spot-label">14K/gram</div>
                </div>
                <div class="spot-item">
                    <div class="spot-value">${spots.get('18K', 0):.2f}</div>
                    <div class="spot-label">18K/gram</div>
                </div>
                <div class="spot-item">
                    <div class="spot-value">${spots.get('sterling', 0):.3f}</div>
                    <div class="spot-label">Sterling/gram</div>
                </div>
            </div>
        </div>
    </div>
    
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div class="section">
            <div class="section-header">Queue ({len(LISTING_QUEUE)})</div>
            <div class="section-content">{queue_html}</div>
        </div>
        <div class="section">
            <div class="section-header">Recent Listings</div>
            <div class="section-content">{recent_html}</div>
        </div>
    </div>
</div>
</body></html>"""


# ============================================================
# PATTERNS PAGE
# ============================================================
@app.get("/patterns", response_class=HTMLResponse)
async def patterns_page():
    """Pattern analytics page"""
    patterns = get_pattern_analytics()
    
    high_pass_html = ""
    for kw in patterns.get('high_pass_keywords', [])[:30]:
        high_pass_html += f'''
        <tr>
            <td>{kw.get('keyword', '')}</td>
            <td>{kw.get('category', '')}</td>
            <td>{kw.get('times_seen', 0)}</td>
            <td>{kw.get('times_analyzed', 0)}</td>
            <td style="color:#ef4444">{kw.get('pass_rate', 0):.0%}</td>
        </tr>'''
    
    return f"""<!DOCTYPE html>
<html><head>
<title>Pattern Analytics</title>
<style>
body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}
.container {{ max-width: 1000px; margin: 0 auto; }}
h1 {{ color: #fff; margin-bottom: 20px; }}
table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}
th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #333; }}
th {{ background: #252540; color: #888; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
td {{ font-size: 14px; }}
a {{ color: #6366f1; text-decoration: none; }}
</style>
</head><body>
<div class="container">
<a href="/">← Back to Dashboard</a>
<h1>High-Pass Keywords (Candidates for Negative Filters)</h1>
<p style="color:#888;margin-bottom:20px;">Keywords that frequently result in PASS - consider adding as negative filters.</p>
<table>
<thead><tr><th>Keyword</th><th>Category</th><th>Times Seen</th><th>Analyzed</th><th>Pass Rate</th></tr></thead>
<tbody>{high_pass_html}</tbody>
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
        cat_values.append(cat.get('count', 0))
    
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
            "analyzed": analytics.get('total_listings', 0),
            "buys": analytics.get('total_buys', 0),
            "passes": analytics.get('total_passes', 0),
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
# ANALYTICS PAGE (Visual Dashboard)
# ============================================================
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
    total = analytics.get('total_listings', 0)
    buys = analytics.get('total_buys', 0)
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
            <div class="stat-value">{analytics.get('total_listings', 0):,}</div>
            <div class="stat-label">Total Analyzed</div>
            <div class="stat-sub">All time listings</div>
        </div>
        <div class="stat-card green">
            <div class="stat-value" style="color:#22c55e">{analytics.get('total_buys', 0):,}</div>
            <div class="stat-label">BUY Signals</div>
            <div class="stat-sub">{buy_rate:.1f}% of analyzed</div>
        </div>
        <div class="stat-card red">
            <div class="stat-value" style="color:#ef4444">{analytics.get('total_passes', 0):,}</div>
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
        <a href="/" style="color:#6366f1;">← Back to Dashboard</a>
        </body></html>
        """)
    
    # Extract data
    title = listing.get('title', 'Unknown')
    category = listing.get('category', 'unknown')
    recommendation = listing.get('recommendation', 'UNKNOWN')
    total_price = listing.get('total_price', '--')
    margin = listing.get('margin', '--')
    confidence = listing.get('confidence', '--')
    reasoning = listing.get('reasoning', 'No reasoning available')
    timestamp = listing.get('timestamp', '--')
    raw_response = listing.get('raw_response', 'Not available')
    
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
<a href="/" class="back">← Back to Dashboard</a>

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
            <div class="stat-label">Margin</div>
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
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Claude Proxy Server v3 - Optimized")
    print("=" * 60)
    print(f"Dashboard: http://{HOST}:{PORT}")
    print(f"Optimizations: Async images, Smart cache, Connection pooling")
    print("=" * 60 + "\n")
    
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        workers=1  # Can increase for more concurrency
    )
