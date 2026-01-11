"""
Keepa Routes - Amazon price tracking and deal monitoring endpoints
Extracted from main.py for modularity

This module contains:
- /keepa/* endpoints for Keepa deal tracking
- Webhook handling for price drop notifications
- Deal monitoring and Discord alerts
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Optional, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

logger = logging.getLogger(__name__)

# Create router for Keepa endpoints
router = APIRouter(tags=["keepa"])

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_keepa)
# ============================================================

_KEEPA_AVAILABLE = False
_get_keepa_client = None
_set_keepa_client = None
_KeepaClientV2 = None
_get_client = None
_start_deals_monitor = None
_stop_monitor = None
_handle_keepa_webhook = None
_PriceDrop = None
_keepa_send_discord_alert = None


def configure_keepa(
    KEEPA_AVAILABLE: bool,
    get_keepa_client: Callable,
    set_keepa_client: Callable,
    KeepaClientV2: Any,
    get_client: Callable,
    start_deals_monitor: Callable,
    stop_monitor: Callable,
    handle_keepa_webhook: Callable,
    PriceDrop: Any,
    keepa_send_discord_alert: Callable,
):
    """Configure the Keepa module with required dependencies."""
    global _KEEPA_AVAILABLE, _get_keepa_client, _set_keepa_client
    global _KeepaClientV2, _get_client, _start_deals_monitor, _stop_monitor
    global _handle_keepa_webhook, _PriceDrop, _keepa_send_discord_alert

    _KEEPA_AVAILABLE = KEEPA_AVAILABLE
    _get_keepa_client = get_keepa_client
    _set_keepa_client = set_keepa_client
    _KeepaClientV2 = KeepaClientV2
    _get_client = get_client
    _start_deals_monitor = start_deals_monitor
    _stop_monitor = stop_monitor
    _handle_keepa_webhook = handle_keepa_webhook
    _PriceDrop = PriceDrop
    _keepa_send_discord_alert = keepa_send_discord_alert

    logger.info("[KEEPA ROUTES] Module configured")


# ============================================================
# KEEPA ENDPOINTS
# ============================================================

@router.get("/keepa/stats")
async def keepa_stats():
    """Get Keepa tracker statistics"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    # Check both the monitor's client and the legacy client
    monitor_client = _get_client()
    keepa_client = _get_keepa_client()

    client = monitor_client or keepa_client

    if client:
        return JSONResponse({
            "status": "ok",
            "stats": client.get_stats(),
        })
    else:
        return JSONResponse({
            "status": "not_initialized",
            "message": "Keepa tracker not started. Use POST /keepa/poll/start",
        })


@router.get("/keepa", response_class=HTMLResponse)
async def keepa_dashboard_page():
    """Serve the Keepa dashboard HTML"""
    dashboard_path = Path(__file__).parent.parent / "keepa_dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path, media_type="text/html")
    else:
        return HTMLResponse("<h1>Keepa Dashboard not found</h1><p>Place keepa_dashboard.html in the same directory as main.py</p>")


@router.post("/keepa/start")
async def keepa_start(csv_file: str = "asin-tracker-tasks-export.csv"):
    """Initialize Keepa tracker with your CSV export"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    client = _KeepaClientV2()
    client.load_tracked_products_csv(csv_file)
    _set_keepa_client(client)

    return JSONResponse({
        "status": "ok",
        "message": "Keepa tracker V2 initialized",
        "tracked_products": len(client.tracked_products),
        "stats": client.get_stats(),
    })


@router.get("/keepa/check")
async def keepa_check_deals():
    """Check Keepa Deals API for price drops matching tracked products"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    keepa_client = _get_keepa_client()
    if not keepa_client:
        keepa_client = _KeepaClientV2()
        keepa_client.load_tracked_products_csv("asin-tracker-tasks-export.csv")
        _set_keepa_client(keepa_client)

    # Check deals against tracked list
    matches = await keepa_client.check_deals_against_tracked()

    # Send Discord alerts for matches
    for drop in matches:
        await _keepa_send_discord_alert(drop)

    return JSONResponse({
        "status": "ok",
        "deals_found": len(matches),
        "deals": [d.to_dict() for d in matches],
        "stats": keepa_client.get_stats(),
    })


@router.get("/keepa/deals")
async def keepa_raw_deals(
    min_drop: int = 20,
    hours: int = 24,
    max_rank: int = 500000,
):
    """Get raw deals from Keepa (not filtered by tracked list)"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    keepa_client = _get_keepa_client()
    if not keepa_client:
        keepa_client = _KeepaClientV2()
        _set_keepa_client(keepa_client)

    deals = await keepa_client.get_deals(
        delta_percent_range=(min_drop, 100),
        delta_last_hours=hours,
        sales_rank_range=(1, max_rank),
    )

    return JSONResponse({
        "status": "ok",
        "count": len(deals),
        "deals": deals[:50],  # Limit response size
        "stats": keepa_client.get_stats(),
    })


@router.get("/keepa/lookup")
async def keepa_lookup(asin: str):
    """Check if an ASIN is in tracked list and show target price"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    keepa_client = _get_keepa_client()
    if not keepa_client:
        keepa_client = _KeepaClientV2()
        keepa_client.load_tracked_products_csv("asin-tracker-tasks-export.csv")
        _set_keepa_client(keepa_client)

    asin = asin.upper().strip()

    if asin in keepa_client.tracked_products:
        product = keepa_client.tracked_products[asin]
        return JSONResponse({
            "status": "ok",
            "tracked": True,
            "asin": asin,
            "title": product.title,
            "target_price": product.target_price,
            "notes": product.notes,
        })
    else:
        return JSONResponse({
            "status": "ok",
            "tracked": False,
            "asin": asin,
            "message": "ASIN not in tracked list",
        })


@router.post("/keepa/register-trackings")
async def keepa_register_trackings(batch_size: int = 50):
    """
    Register all tracked products with Keepa's Tracking API
    This enables webhook notifications when prices drop!

    WARNING: This uses API tokens for each registration.
    """
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    keepa_client = _get_keepa_client()
    if not keepa_client:
        keepa_client = _KeepaClientV2()
        keepa_client.load_tracked_products_csv("asin-tracker-tasks-export.csv")
        _set_keepa_client(keepa_client)

    results = await keepa_client.register_all_trackings(batch_size)

    return JSONResponse({
        "status": "ok",
        "results": results,
        "stats": keepa_client.get_stats(),
    })


@router.post("/keepa/webhook")
async def keepa_webhook_receiver(request: Request):
    """
    Receive webhook notifications from Keepa

    Set this URL in Keepa: https://your-ngrok-url.ngrok.io/keepa/webhook
    """
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    try:
        # Keepa sends notifications as JSON
        payload = await request.json()

        # Log for debugging
        logger.info(f"[KEEPA WEBHOOK] Received: {json.dumps(payload)[:200]}...")

        result = await _handle_keepa_webhook(payload)

        # Must return 200 for Keepa to confirm delivery
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logger.error(f"[KEEPA WEBHOOK] Error: {e}")
        # Still return 200 to prevent Keepa retries flooding
        return JSONResponse({"status": "error", "message": str(e)}, status_code=200)


@router.post("/keepa/set-webhook")
async def keepa_set_webhook(webhook_url: str):
    """Set the webhook URL for Keepa to push notifications"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    keepa_client = _get_keepa_client()
    if not keepa_client:
        keepa_client = _KeepaClientV2()
        _set_keepa_client(keepa_client)

    success = await keepa_client.set_webhook_url(webhook_url)

    return JSONResponse({
        "status": "ok" if success else "error",
        "webhook_url": webhook_url,
    })


@router.post("/keepa/poll/start")
async def keepa_poll_start(
    interval: int = 300,
    enable_analysis: bool = True,
    min_flip_score: int = 50,
    enable_brand_monitoring: bool = True,
):
    """
    Start background monitoring using Deals API.

    Args:
        interval: Check interval in seconds (default 300 = 5 min)
        enable_analysis: If True, analyzes each deal before alerting (uses Product API)
        min_flip_score: Minimum flip score to alert (0-100, default 50)
        enable_brand_monitoring: If True, also checks deals from tracked brands
    """
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    # Start monitoring in background
    asyncio.create_task(_start_deals_monitor(
        csv_path="asin-tracker-tasks-export.csv",
        check_interval=interval,
        enable_analysis=enable_analysis,
        min_flip_score=min_flip_score,
        enable_brand_monitoring=enable_brand_monitoring,
    ))

    return JSONResponse({
        "status": "ok",
        "message": f"Started Keepa deals monitor (every {interval}s)",
        "settings": {
            "enable_analysis": enable_analysis,
            "min_flip_score": min_flip_score,
            "enable_brand_monitoring": enable_brand_monitoring,
        }
    })


@router.post("/keepa/poll/stop")
async def keepa_poll_stop():
    """Stop Keepa background monitoring"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    await _stop_monitor()

    return JSONResponse({
        "status": "ok",
        "message": "Keepa monitoring stopped",
    })


@router.post("/keepa/test-discord")
async def keepa_test_discord():
    """Send a test Discord alert"""
    if not _KEEPA_AVAILABLE:
        return JSONResponse({"error": "Keepa tracker not available"}, status_code=503)

    # Create a fake deal for testing
    test_drop = _PriceDrop(
        asin="TEST12345",
        title="TEST ALERT - Keepa Integration Working!",
        current_price=29.99,
        previous_price=49.99,
        target_price=35.00,
        drop_percent=40.0,
        sales_rank=12345,
        category="Test Category",
        image_url="",
        amazon_url="https://www.amazon.com/dp/TEST12345",
    )

    try:
        await _keepa_send_discord_alert(test_drop)
        return JSONResponse({
            "status": "ok",
            "message": "Test alert sent to Discord!",
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e),
        }, status_code=500)
