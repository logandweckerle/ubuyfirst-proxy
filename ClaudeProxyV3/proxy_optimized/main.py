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
from prompts import get_category_prompt, get_business_context, detect_category

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
ENABLED = False  # Starts OFF - no API costs until enabled
DEBUG_MODE = False
QUEUE_MODE = True  # Queue listings for manual review

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
    
    try:
        data = {}
        images = []
        
        # Parse request data
        query_data = dict(request.query_params)
        if query_data:
            data = query_data
        
        # Read body for POST requests
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
        
        title = data.get('Title', 'No title')[:80]
        total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))
        listing_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        
        logger.info(f"Title: {title[:50]}")
        logger.info(f"Price: ${total_price}")
        
        STATS["total_requests"] += 1
        
        # ============================================================
        # CHECK SMART CACHE FIRST
        # ============================================================
        cached = cache.get(title, total_price)
        if cached:
            result, html = cached
            STATS["cache_hits"] += 1
            logger.info(f"[CACHE HIT] Returning cached {result.get('Recommendation', 'UNKNOWN')}")
            return HTMLResponse(content=html)
        
        # ============================================================
        # DISABLED CHECK
        # ============================================================
        if not ENABLED:
            logger.info("DISABLED - Returning placeholder")
            STATS["skipped"] += 1
            html = _render_disabled_html()
            return HTMLResponse(content=html)
        
        # ============================================================
        # QUEUE MODE - Store for manual review
        # ============================================================
        if QUEUE_MODE:
            category, category_reasons = detect_category(data)
            log_incoming_listing(data, category, 'queued')
            
            # Fetch images in parallel (for later use)
            if 'images' in data and data['images']:
                images = await process_image_list(data['images'])
            
            LISTING_QUEUE[listing_id] = {
                "id": listing_id,
                "timestamp": timestamp,
                "title": title,
                "total_price": total_price,
                "category": category,
                "category_reasons": category_reasons,
                "data": data,
                "images": images,
                "status": "queued"
            }
            
            logger.info(f"QUEUED for review - Category: {category}")
            html = _render_queued_html(category)
            return HTMLResponse(content=html)
        
        # ============================================================
        # FULL ANALYSIS
        # ============================================================
        STATS["api_calls"] += 1
        
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
            
            # Render HTML
            html = render_result_html(result, category)
            
            # Store in smart cache with recommendation-based TTL
            cache.set(title, total_price, result, html, recommendation, category)
            
            logger.info(f"Result: {recommendation}")
            return HTMLResponse(content=html)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            error_result = {
                "Qualify": "No", "Recommendation": "RESEARCH",
                "reasoning": f"Parse error - manual review needed",
                "confidence": "Low"
            }
            html = render_result_html(error_result, category)
            return HTMLResponse(content=html)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
        error_result = {
            "Qualify": "No", "Recommendation": "RESEARCH",
            "reasoning": f"Error: {str(e)[:50]}",
            "confidence": "Low"
        }
        html = _render_error_html(str(e))
        return HTMLResponse(content=html)


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
        images = queued.get("images", [])
        category = queued["category"]
        title = queued["title"]
        total_price = queued["total_price"]
        
        STATS["api_calls"] += 1
        
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
        
        # Remove from queue
        del LISTING_QUEUE[listing_id]
        
        logger.info(f"Analyzed queued listing: {recommendation}")
        
    finally:
        QUEUE_MODE = original_queue_mode
    
    return RedirectResponse(url="/", status_code=303)


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
        "cache_hits": 0, "listings": {}
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
    """OpenAI-compatible endpoint - redirects to match_mydata"""
    logger.info("[/v1/chat/completions] Redirecting to match_mydata")
    return await analyze_listing(request)


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


def _render_queued_html(category: str) -> str:
    return f'''<!DOCTYPE html>
<html><head><style>
body {{ font-family: system-ui; background: #f5f5f5; padding: 20px; }}
.card {{ background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%); border: 3px solid #2196f3; border-radius: 12px; padding: 20px; text-align: center; max-width: 400px; margin: auto; }}
.status {{ font-size: 32px; font-weight: bold; color: #1565c0; }}
.category {{ font-size: 18px; color: #1976d2; margin-top: 10px; }}
</style></head><body>
<div class="card">
<div class="status">QUEUED</div>
<div class="category">{category.upper()}</div>
<p>Open dashboard to analyze</p>
</div></body></html>'''


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
    else:
        bg = 'linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%)'
        border = '#ffc107'
        text_color = '#856404'
    
    # Build info grid based on category
    info_items = []
    
    if category == 'gold':
        info_items = [
            ('Karat', result.get('karat', '--')),
            ('Weight', result.get('weight', '--')),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Risk', result.get('fakerisk', '--')),
            ('Confidence', confidence),
        ]
    elif category == 'silver':
        info_items = [
            ('Type', result.get('itemtype', '--')),
            ('Weight', result.get('weight', '--')),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('$/gram', result.get('pricepergram', '--')),
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
        
        recent_html += f'''
        <div class="listing-item {rec_class}">
            <span class="listing-rec">{rec}</span>
            <span class="listing-title">{title}</span>
            <span class="listing-margin">{margin}</span>
        </div>'''
    
    if not recent_html:
        recent_html = '<div style="text-align:center;color:#666;padding:20px;">No listings analyzed yet</div>'
    
    # Build queue HTML
    queue_html = ""
    for lid, q in list(LISTING_QUEUE.items())[:10]:
        queue_html += f'''
        <div class="queue-item">
            <div class="queue-title">{q["title"][:50]}...</div>
            <div class="queue-meta">{q["category"].upper()} | ${q["total_price"]}</div>
            <form action="/analyze-queued/{lid}" method="post">
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
.listing-item {{ display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 8px; margin-bottom: 8px; background: #252540; }}
.listing-item.buy {{ border-left: 4px solid #22c55e; }}
.listing-item.pass {{ border-left: 4px solid #ef4444; }}
.listing-item.research {{ border-left: 4px solid #f59e0b; }}
.listing-rec {{ font-weight: 700; width: 80px; }}
.listing-title {{ flex: 1; font-size: 14px; }}
.listing-margin {{ font-weight: 600; color: #888; }}
.queue-item {{ display: flex; align-items: center; gap: 10px; padding: 12px; background: #252540; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #2196f3; }}
.queue-title {{ flex: 1; font-weight: 500; }}
.queue-meta {{ color: #888; font-size: 12px; }}
.analyze-btn {{ background: #2196f3; color: #fff; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; }}
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
# ANALYTICS PAGE
# ============================================================
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page():
    """Analytics dashboard page"""
    analytics = get_analytics()
    
    category_html = ""
    for cat in analytics.get('by_category', []):
        category_html += f'''
        <tr>
            <td>{cat.get('category', 'Unknown')}</td>
            <td>{cat.get('count', 0)}</td>
            <td style="color:#22c55e">{cat.get('buys', 0)}</td>
        </tr>'''
    
    return f"""<!DOCTYPE html>
<html><head>
<title>Analytics</title>
<style>
body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}
.container {{ max-width: 1000px; margin: 0 auto; }}
h1 {{ color: #fff; margin-bottom: 20px; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }}
.stat {{ background: #1a1a2e; padding: 20px; border-radius: 12px; text-align: center; }}
.stat-value {{ font-size: 32px; font-weight: 700; color: #fff; }}
.stat-label {{ font-size: 12px; color: #888; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}
th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #333; }}
th {{ background: #252540; color: #888; font-weight: 600; }}
a {{ color: #6366f1; text-decoration: none; }}
</style>
</head><body>
<div class="container">
<a href="/">← Back to Dashboard</a>
<h1>Analytics</h1>
<div class="stats">
    <div class="stat">
        <div class="stat-value">{analytics.get('total_listings', 0)}</div>
        <div class="stat-label">Total Analyzed</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#22c55e">{analytics.get('total_buys', 0)}</div>
        <div class="stat-label">BUY Recommendations</div>
    </div>
    <div class="stat">
        <div class="stat-value" style="color:#ef4444">{analytics.get('total_passes', 0)}</div>
        <div class="stat-label">PASS Recommendations</div>
    </div>
    <div class="stat">
        <div class="stat-value">{analytics.get('actual_purchases', 0)}</div>
        <div class="stat-label">Actual Purchases</div>
    </div>
</div>
<h2 style="margin-bottom:15px;">By Category</h2>
<table>
<thead><tr><th>Category</th><th>Count</th><th>BUY</th></tr></thead>
<tbody>{category_html}</tbody>
</table>
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
