"""
Dashboard Routes - Main dashboard and control endpoints
Extracted from main.py for modularity

This module contains:
- Control endpoints: /toggle*, /clear-*, /reset-stats
- Status endpoints: /health, /queue
- Main dashboard: /

Phase 2 Refactoring: Routes now support direct AppState access via request.
"""

import logging
from datetime import datetime
from typing import Callable, Dict, Any, Optional, TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

if TYPE_CHECKING:
    from services.app_state import AppState

logger = logging.getLogger(__name__)

# Create router for dashboard endpoints
router = APIRouter(tags=["dashboard"])

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_dashboard)
# ============================================================

# NEW: Direct AppState reference (Phase 2 refactoring)
_app_state: Optional["AppState"] = None

# State getters (return current value) - LEGACY, kept for backwards compat
_get_enabled = None
_get_debug_mode = None
_get_queue_mode = None
_get_stats = None
_get_listing_queue = None
_get_race_stats = None
_get_race_feed_api = None
_get_race_feed_ubuyfirst = None

# State setters (modify state) - LEGACY, kept for backwards compat
_set_enabled = None
_set_debug_mode = None
_set_queue_mode = None
_reset_stats = None
_clear_listing_queue = None

# External functions
_cache = None
_get_spot_prices = None
_get_analytics = None


def _get_state(request: Optional[Request] = None) -> Optional["AppState"]:
    """
    Get AppState from request or module-level reference.
    Provides backwards compatibility during migration.
    """
    if request and hasattr(request.app.state, 'app_state'):
        return request.app.state.app_state
    return _app_state


def configure_dashboard(
    get_enabled: Callable,
    get_debug_mode: Callable,
    get_queue_mode: Callable,
    get_stats: Callable,
    get_listing_queue: Callable,
    get_race_stats: Callable,
    get_race_feed_api: Callable,
    get_race_feed_ubuyfirst: Callable,
    set_enabled: Callable,
    set_debug_mode: Callable,
    set_queue_mode: Callable,
    reset_stats: Callable,
    clear_listing_queue: Callable,
    cache: Any,
    get_spot_prices: Callable,
    get_analytics: Callable,
    app_state: Optional["AppState"] = None,
):
    """
    Configure the dashboard module with required dependencies.

    Args:
        app_state: Optional AppState instance. When provided, routes will use
                   this directly instead of the legacy getter/setter callbacks.
    """
    global _get_enabled, _get_debug_mode, _get_queue_mode, _get_stats
    global _get_listing_queue, _get_race_stats, _get_race_feed_api, _get_race_feed_ubuyfirst
    global _set_enabled, _set_debug_mode, _set_queue_mode, _reset_stats, _clear_listing_queue
    global _cache, _get_spot_prices, _get_analytics, _app_state

    # NEW: Store direct AppState reference if provided
    _app_state = app_state

    _get_enabled = get_enabled
    _get_debug_mode = get_debug_mode
    _get_queue_mode = get_queue_mode
    _get_stats = get_stats
    _get_listing_queue = get_listing_queue
    _get_race_stats = get_race_stats
    _get_race_feed_api = get_race_feed_api
    _get_race_feed_ubuyfirst = get_race_feed_ubuyfirst
    _set_enabled = set_enabled
    _set_debug_mode = set_debug_mode
    _set_queue_mode = set_queue_mode
    _reset_stats = reset_stats
    _clear_listing_queue = clear_listing_queue
    _cache = cache
    _get_spot_prices = get_spot_prices
    _get_analytics = get_analytics

    logger.info(f"[DASHBOARD ROUTES] Module configured (app_state={'provided' if app_state else 'legacy mode'})")


# ============================================================
# CONTROL ENDPOINTS
# ============================================================

@router.post("/toggle")
async def toggle_proxy(request: Request):
    state = _get_state(request)
    if state:
        state.enabled = not state.enabled
        logger.info(f"Proxy {'ENABLED' if state.enabled else 'DISABLED'}")
    else:
        # Legacy fallback
        ENABLED = _get_enabled()
        _set_enabled(not ENABLED)
        logger.info(f"Proxy {'ENABLED' if not ENABLED else 'DISABLED'}")
    return RedirectResponse(url="/", status_code=303)


@router.post("/toggle-debug")
async def toggle_debug(request: Request):
    state = _get_state(request)
    if state:
        state.debug_mode = not state.debug_mode
    else:
        DEBUG_MODE = _get_debug_mode()
        _set_debug_mode(not DEBUG_MODE)
    return RedirectResponse(url="/", status_code=303)


@router.post("/toggle-queue")
async def toggle_queue(request: Request):
    state = _get_state(request)
    if state:
        state.queue_mode = not state.queue_mode
        logger.info(f"Queue mode {'ENABLED' if state.queue_mode else 'DISABLED'}")
    else:
        QUEUE_MODE = _get_queue_mode()
        _set_queue_mode(not QUEUE_MODE)
        logger.info(f"Queue mode {'ENABLED' if not QUEUE_MODE else 'DISABLED'}")
    return RedirectResponse(url="/", status_code=303)


@router.post("/clear-queue")
async def clear_queue(request: Request):
    state = _get_state(request)
    if state:
        state.listing_queue.clear()
    else:
        _clear_listing_queue()
    return RedirectResponse(url="/", status_code=303)


@router.post("/clear-cache")
async def clear_cache():
    """Clear the response cache"""
    count = _cache.clear()
    logger.info(f"[CACHE] Cleared {count} cached items")
    return {"status": "Cache cleared", "items_removed": count}


@router.get("/clear-cache")
async def clear_cache_get():
    """Clear cache via GET for easy browser access"""
    count = _cache.clear()
    logger.info(f"[CACHE] Cleared {count} cached items")
    return {"status": "Cache cleared", "items_removed": count}


@router.post("/reset-stats")
async def reset_stats(request: Request):
    state = _get_state(request)
    if state:
        state.reset_stats()
    else:
        _reset_stats()
    return RedirectResponse(url="/", status_code=303)


# ============================================================
# STATUS ENDPOINTS
# ============================================================

@router.get("/health")
async def health(request: Request):
    state = _get_state(request)
    if state:
        return {"status": "ok", "enabled": state.enabled, "queue_mode": state.queue_mode}
    return {"status": "ok", "enabled": _get_enabled(), "queue_mode": _get_queue_mode()}


@router.get("/queue")
async def get_queue(request: Request):
    state = _get_state(request)
    if state:
        queue = state.listing_queue
    else:
        queue = _get_listing_queue()
    return {"queue": list(queue.values()), "count": len(queue)}


@router.get("/api/spot-prices")
async def api_spot_prices():
    return _get_spot_prices()


@router.get("/api/cache-stats")
async def api_cache_stats():
    return _cache.get_stats()


# ============================================================
# MAIN DASHBOARD
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    state = _get_state(request)

    # Use AppState if available, otherwise fallback to legacy getters
    if state:
        ENABLED = state.enabled
        QUEUE_MODE = state.queue_mode
        STATS = state.stats
        LISTING_QUEUE = state.listing_queue
    else:
        ENABLED = _get_enabled()
        QUEUE_MODE = _get_queue_mode()
        STATS = _get_stats()
        LISTING_QUEUE = _get_listing_queue()

    # These still use legacy getters (not part of AppState yet)
    RACE_STATS = _get_race_stats()
    RACE_FEED_API = _get_race_feed_api()
    RACE_FEED_UBUYFIRST = _get_race_feed_ubuyfirst()

    status = "ENABLED" if ENABLED else "DISABLED"
    status_class = "active" if ENABLED else "inactive"
    queue_status = "ON" if QUEUE_MODE else "OFF"

    # Get spot prices
    spots = _get_spot_prices()

    # Get cache stats
    cache_stats = _cache.get_stats()

    # Build recent listings HTML from database
    recent_html = ""
    analytics_data = _get_analytics()
    recent_from_db = analytics_data.get('recent', [])[:15]

    for listing in recent_from_db:
        rec = listing.get("recommendation", "UNKNOWN")
        rec_class = rec.lower()
        title = listing.get("title", "")[:55]
        margin = listing.get("margin", "--")
        if margin and isinstance(margin, (int, float)):
            margin = f"${margin:,.0f}" if margin >= 0 else f"-${abs(margin):,.0f}"
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
        <a href="/live" style="background: linear-gradient(135deg, #00ff88, #00cc6a); color: #000; font-weight: bold;">ShadowSnipe Live</a>
        <a href="/purchases" style="background: linear-gradient(135deg, #22c55e, #16a34a); color: #fff; font-weight: bold;">Purchases</a>
        <a href="/training">Training</a>
        <a href="/patterns">Patterns</a>
        <a href="/keepa">Keepa</a>
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
        <form action="/reload" method="post" style="display:inline;">
            <button type="submit" class="btn btn-secondary" style="background:#8b5cf6;">Reload Prompts</button>
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

    <!-- RACE STATS -->
    <div class="stats-row" style="margin-top:10px;">
        <div class="stat-card" style="border: 2px solid #ff4444;">
            <div class="stat-value" style="color:#ff4444">{RACE_STATS['total']}</div>
            <div class="stat-label">Race Matches</div>
        </div>
        <div class="stat-card" style="border: 2px solid #22c55e;">
            <div class="stat-value" style="color:#22c55e">{RACE_STATS['api_wins']}</div>
            <div class="stat-label">API Wins</div>
        </div>
        <div class="stat-card" style="border: 2px solid #ffd700;">
            <div class="stat-value" style="color:#ffd700">{RACE_STATS['ubuyfirst_wins']}</div>
            <div class="stat-label">uBuyFirst Wins</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:#888">{len(RACE_FEED_API)}</div>
            <div class="stat-label">API Feed</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:#888">{len(RACE_FEED_UBUYFIRST)}</div>
            <div class="stat-label">uBF Feed</div>
        </div>
        <div class="stat-card">
            <a href="/ebay/race/gold" style="color:#ffd700;text-decoration:none;">
                <div class="stat-value" style="color:#ffd700">RACE</div>
                <div class="stat-label">Open Dashboard</div>
            </a>
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
