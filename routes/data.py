"""
Data API endpoints.

Handles data management operations:
- /api/user-prices: User price database CRUD
- /api/budget: OpenAI budget management
- /api/memory-stats: AppState memory monitoring
- /api/tracking/*: Item tracking and fast-sale patterns
- /api/patterns/*: Learning pattern management
- /api/deals: BUY/RESEARCH deals for desktop app
- /api/training-data, /training: Training data analysis
- /api/log-purchase, /purchases: Purchase history
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])

# Module state (set by configure_data)
_stats = None
_db_path = None
_training_log_path = None
_purchase_log_path = None
_item_tracking = None
_get_app_state_from_request = None
_get_openai_budget_status = None
_set_hourly_budget = None
_render_training_dashboard = None
_render_purchases_page = None


def configure_data(stats, db_path, training_log_path, purchase_log_path,
                   item_tracking, get_app_state_from_request_fn,
                   get_openai_budget_status_fn, set_hourly_budget_fn,
                   render_training_dashboard_fn, render_purchases_page_fn):
    """Configure module dependencies."""
    global _stats, _db_path, _training_log_path, _purchase_log_path
    global _item_tracking, _get_app_state_from_request
    global _get_openai_budget_status, _set_hourly_budget
    global _render_training_dashboard, _render_purchases_page

    _stats = stats
    _db_path = db_path
    _training_log_path = training_log_path
    _purchase_log_path = purchase_log_path
    _item_tracking = item_tracking
    _get_app_state_from_request = get_app_state_from_request_fn
    _get_openai_budget_status = get_openai_budget_status_fn
    _set_hourly_budget = set_hourly_budget_fn
    _render_training_dashboard = render_training_dashboard_fn
    _render_purchases_page = render_purchases_page_fn
    logger.info("[DATA ROUTES] Module configured")


# ============================================================
# USER PRICE DATABASE
# ============================================================

@router.get("/api/user-prices")
async def api_user_prices():
    """Get all user-provided prices"""
    from user_price_db import get_all_prices, get_stats
    return {
        "prices": get_all_prices(),
        "stats": get_stats()
    }


@router.post("/api/user-prices/add")
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


@router.get("/api/user-prices/lookup")
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


# ============================================================
# BUDGET
# ============================================================

@router.get("/api/budget")
async def api_budget_status():
    """Get OpenAI hourly budget status"""
    return _get_openai_budget_status()


@router.post("/api/budget/set")
async def api_set_budget(hourly_limit: float = 10.0):
    """Set the hourly OpenAI budget limit"""
    if hourly_limit < 1.0:
        return {"error": "Budget must be at least $1/hour"}
    if hourly_limit > 100.0:
        return {"error": "Budget cannot exceed $100/hour"}
    _set_hourly_budget(hourly_limit)
    logger.info(f"[BUDGET] Hourly limit set to ${hourly_limit:.2f}")
    return {"success": True, "hourly_budget": hourly_limit}


# ============================================================
# MEMORY STATS
# ============================================================

@router.get("/api/memory-stats")
async def api_memory_stats(request: Request):
    """Get AppState memory usage statistics for monitoring"""
    app_state = _get_app_state_from_request(request)
    return app_state.get_memory_stats()


# ============================================================
# ITEM TRACKING
# ============================================================

@router.get("/api/tracking/stats")
async def api_tracking_stats():
    """Get item tracking statistics including fast-sale patterns"""
    return _item_tracking.get_tracking_stats()


@router.get("/api/tracking/fast-sales")
async def api_tracking_fast_sales(limit: int = 50):
    """Get items that sold within 5 minutes of listing"""
    return _item_tracking.get_fast_sales(limit=limit)


@router.get("/api/tracking/active")
async def api_tracking_active(limit: int = 100):
    """Get active items currently being tracked"""
    return _item_tracking.get_active_items(limit=limit)


@router.post("/api/tracking/resolve-now")
async def api_tracking_resolve_now():
    """Manually trigger eBay item ID resolution for pending items"""
    await _item_tracking.resolve_pending_items(batch_size=20)
    stats = _item_tracking.get_tracking_stats()
    return {
        "status": "ok",
        "message": "Resolution completed",
        "resolved_ids": stats.get("resolved_ids", 0),
        "pending_resolution": stats.get("pending_resolution", 0)
    }


@router.post("/api/tracking/poll-now")
async def api_tracking_poll_now():
    """Manually trigger ID resolution + poll for sold items"""
    await _item_tracking.resolve_pending_items(batch_size=20)
    await _item_tracking.poll_items_for_sold_status(batch_size=50)
    return {"status": "ok", "message": "Resolution and polling completed"}


# ============================================================
# PATTERNS
# ============================================================

@router.get("/api/patterns/stats")
async def api_pattern_stats():
    """Get statistics about logged learning patterns"""
    return _item_tracking.get_pattern_stats()


@router.get("/api/patterns/{category}")
async def api_patterns_by_category(category: str, limit: int = 50):
    """Get recent patterns for a specific category"""
    patterns = _item_tracking.get_patterns_by_category(category, limit)
    return {"category": category, "count": len(patterns), "patterns": patterns}


@router.post("/api/patterns/log")
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

    _item_tracking.log_pattern(
        pattern_type=data['pattern_type'],
        category=data['category'],
        title=data['title'],
        price=float(data['price']),
        result=result,
        data=data,
        notes=notes
    )

    return {"status": "ok", "message": f"Logged {data['pattern_type']} pattern"}


# ============================================================
# DEALS API
# ============================================================

@router.get("/api/deals")
async def get_deals(limit: int = 50, include_research: bool = True, include_history: bool = False):
    """
    Get BUY and RESEARCH deals for the desktop dashboard.
    Returns deals sorted by timestamp (newest first).
    """
    try:
        deals = []

        # Get from in-memory stats
        for listing_id, listing in _stats.get('listings', {}).items():
            rec = listing.get('recommendation', '')
            if rec == 'BUY' or (rec == 'RESEARCH' and include_research):
                input_data = listing.get('input_data', {})

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
        try:
            conn = sqlite3.connect(_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if include_history:
                cursor.execute("""
                    SELECT id, title, total_price, category, recommendation, margin, confidence, reasoning, timestamp, raw_response
                    FROM listings
                    WHERE recommendation IN ('BUY', 'RESEARCH')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit * 2,))
            else:
                session_start = _stats.get("session_start", datetime.now().isoformat())
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
                            'thumbnail': '',
                            'ebay_url': '',
                            'item_id': '',
                        })
                        seen_ids.add(row['id'])
        except Exception as db_err:
            logger.warning(f"[DEALS API] DB query error: {db_err}")

        deals.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        deals = deals[:limit]

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


@router.post("/api/deals/clear")
async def clear_deals():
    """Clear all BUY/RESEARCH deals from memory AND database"""
    try:
        listings_to_remove = []
        for listing_id, listing in _stats.get('listings', {}).items():
            rec = listing.get('recommendation', '')
            if rec in ('BUY', 'RESEARCH'):
                listings_to_remove.append(listing_id)

        for lid in listings_to_remove:
            del _stats['listings'][lid]

        memory_cleared = len(listings_to_remove)

        db_cleared = 0
        try:
            conn = sqlite3.connect(_db_path)
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
# TRAINING DATA
# ============================================================

@router.get("/api/training-data")
async def get_training_data(limit: int = 100):
    """Get training override data for analysis"""
    try:
        if not _training_log_path.exists():
            return {"count": 0, "overrides": [], "summary": {}}

        overrides = []
        with open(_training_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    overrides.append(json.loads(line.strip()))
                except:
                    continue

        overrides = list(reversed(overrides[-limit:]))

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


@router.get("/training", response_class=HTMLResponse)
async def training_dashboard_page():
    """Visual dashboard for training data analysis"""
    try:
        overrides = []
        if _training_log_path.exists():
            with open(_training_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        overrides.append(json.loads(line.strip()))
                    except:
                        continue

        by_type = {}
        by_category = {}
        for o in overrides:
            otype = o.get('override_type', 'Unknown')
            cat = o.get('input', {}).get('category', 'Unknown')
            by_type[otype] = by_type.get(otype, 0) + 1
            by_category[cat] = by_category.get(cat, 0) + 1

        html = _render_training_dashboard(overrides, by_type, by_category)
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")


@router.get("/training/clear")
async def clear_training_data():
    """Clear training data log"""
    try:
        if _training_log_path.exists():
            _training_log_path.unlink()
        return {"status": "cleared"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# PURCHASE LOGGING
# ============================================================

def log_purchase(listing_data: dict, analysis_data: dict, notes: str = ""):
    """Log a purchase to the purchases.jsonl file"""
    try:
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

        with open(_purchase_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(purchase_entry) + '\n')

        logger.info(f"[PURCHASE] Logged: {listing_data.get('title', '')[:50]} @ ${listing_data.get('price')}")
        return True
    except Exception as e:
        logger.error(f"[PURCHASE] Failed to log: {e}")
        return False


@router.post("/api/log-purchase")
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


@router.get("/log-purchase-quick", response_class=HTMLResponse)
async def log_purchase_quick(
    title: str = "",
    price: float = 0,
    category: str = "",
    profit: float = 0,
    confidence: str = "",
    recommendation: str = "",
    seller_id: str = "",
    feedback_score: str = "",
    feedback_percent: str = "",
    seller_type: str = "",
    item_id: str = "",
    condition: str = "",
    posted_time: str = "",
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


@router.get("/api/purchases")
async def api_get_purchases(limit: int = 100):
    """Get purchase history"""
    try:
        if not _purchase_log_path.exists():
            return {"purchases": [], "count": 0}

        purchases = []
        with open(_purchase_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        purchases.append(json.loads(line))
                    except:
                        pass

        purchases.reverse()
        return {"purchases": purchases[:limit], "count": len(purchases)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/purchases", response_class=HTMLResponse)
async def purchases_page():
    """Purchase history dashboard"""
    try:
        purchases = []
        total_spent = 0
        total_projected_profit = 0

        if _purchase_log_path.exists():
            with open(_purchase_log_path, 'r', encoding='utf-8') as f:
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
        html = _render_purchases_page(purchases, total_spent, total_projected_profit)
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><p>{str(e)}</p>")


# ============================================================
# FEEDBACK / LEARNING LOOP
# ============================================================

@router.post("/api/feedback")
async def post_feedback(request: Request):
    """
    Record feedback on a listing outcome.

    Body JSON:
        listing_id: str - listing identifier
        item_id: str (optional) - eBay item ID
        title: str (optional) - listing title
        listing_price: float (optional) - price at time of listing
        category: str (optional) - gold/silver/videogames/etc
        recommendation: str (optional) - what the system recommended
        action: str (required) - 'bought', 'skipped', 'missed', 'returned'
        actual_sell_price: float (optional) - what it sold for
        notes: str (optional) - freeform notes
    """
    try:
        from database import save_feedback
        data = await request.json()

        action = data.get("action")
        if not action:
            return JSONResponse({"error": "action field required"}, status_code=400)
        if action not in ('bought', 'skipped', 'missed', 'returned'):
            return JSONResponse({"error": f"Invalid action: {action}. Must be bought/skipped/missed/returned"}, status_code=400)

        save_feedback(
            listing_id=data.get("listing_id", ""),
            item_id=data.get("item_id"),
            title=data.get("title"),
            listing_price=data.get("listing_price"),
            category=data.get("category"),
            recommendation=data.get("recommendation"),
            action=action,
            actual_sell_price=data.get("actual_sell_price"),
            notes=data.get("notes"),
        )
        return {"status": "ok", "action": action}
    except Exception as e:
        logger.error(f"[FEEDBACK] Endpoint error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/feedback/stats")
async def get_feedback_stats_endpoint():
    """Get aggregate feedback statistics."""
    try:
        from database import get_feedback_stats, get_feedback_by_category
        return {
            "overall": get_feedback_stats(),
            "by_category": get_feedback_by_category(),
        }
    except Exception as e:
        logger.error(f"[FEEDBACK] Stats error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
