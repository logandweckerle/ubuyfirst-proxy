"""
KeepaTracker - Amazon Arbitrage Server

Standalone FastAPI server for Amazon price drop monitoring.
Runs separately from ClaudeProxyV3 on port 8001.
"""

# Load .env BEFORE other imports (so env vars are available)
from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# Import Keepa tracker module (after env is loaded)
from keepa_tracker import (
    KeepaClientV2,
    start_deals_monitor,
    stop_monitor,
    get_client,
    get_deduplicator,
    send_discord_alert,
    send_smart_deal_alert,
    PriceDrop,
    KEEPA_API_KEY,
    DISCORD_WEBHOOK_URL,
)

# Import deal analyzer
from deal_analyzer import (
    DealAnalyzer,
    DealScore,
    analyze_deal_quick,
    quick_filter_deal,
    quick_filter_deals,
    QuickFilterResult,
)

# ============================================================
# CONFIGURATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Default CSV path
DEFAULT_CSV_PATH = "asin-tracker-tasks-export.csv"

# Server port (different from ClaudeProxyV3)
SERVER_PORT = 8001

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="KeepaTracker",
    description="Amazon arbitrage monitoring with Keepa API",
    version="1.0.0"
)

# Global state
_monitor_task = None
_poll_task = None


@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("=" * 60)
    logger.info("KeepaTracker Starting...")
    logger.info("=" * 60)

    if not KEEPA_API_KEY:
        logger.warning("[KEEPA] No API key configured!")
    else:
        logger.info(f"[KEEPA] API key loaded ({KEEPA_API_KEY[:10]}...)")

    if DISCORD_WEBHOOK_URL:
        logger.info("[DISCORD] Webhook configured")
    else:
        logger.warning("[DISCORD] No webhook configured")

    # Auto-start monitor if CSV exists
    csv_path = Path(DEFAULT_CSV_PATH)
    if csv_path.exists():
        logger.info(f"[KEEPA] Found {csv_path}, auto-starting monitor...")
        asyncio.create_task(auto_start_monitor())
    else:
        logger.info(f"[KEEPA] No CSV found at {csv_path}, waiting for manual start")

    logger.info(f"Server ready at http://127.0.0.1:{SERVER_PORT}")
    logger.info("=" * 60)


async def auto_start_monitor():
    """Auto-start the deals monitor"""
    global _monitor_task
    await asyncio.sleep(2)  # Wait for app to fully start
    _monitor_task = asyncio.create_task(
        start_deals_monitor(
            csv_path=DEFAULT_CSV_PATH,
            check_interval=300,  # 5 minutes
            enable_brand_monitoring=True,
            enable_analysis=True,
            min_flip_score=50,
        )
    )


# ============================================================
# ROUTES - Stats & Control
# ============================================================

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return HTMLResponse(content='<script>window.location="/keepa/dashboard"</script>')


@app.get("/keepa/stats")
async def get_stats():
    """Get tracker statistics"""
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "not_initialized",
            "message": "Tracker not started. POST to /keepa/start first."
        })

    stats = client.get_stats()
    dedup = get_deduplicator()

    return JSONResponse(content={
        "status": "ok",
        "stats": {
            "api_calls": stats.get("api_calls", 0),
            "tokens_left": stats.get("tokens_left", 0),
            "deals_found": stats.get("deals_checked", 0),
            "alerts_sent": stats.get("alerts_sent", 0),
            "tracked_asins": stats.get("tracked_products", 0),
            "tracked_brands": stats.get("tracked_brands", 0),
            "top_brands": stats.get("top_brands", []),
            "last_check": stats.get("last_check"),
            "dedup_stats": dedup.get_stats() if dedup else {},
        }
    })


@app.post("/keepa/start")
async def start_tracker(csv_path: str = DEFAULT_CSV_PATH):
    """Start the Keepa tracker with a CSV file"""
    global _monitor_task

    if not KEEPA_API_KEY:
        return JSONResponse(content={
            "status": "error",
            "message": "KEEPA_API_KEY not configured"
        }, status_code=400)

    path = Path(csv_path)
    if not path.exists():
        return JSONResponse(content={
            "status": "error",
            "message": f"CSV file not found: {csv_path}"
        }, status_code=400)

    # Start monitor in background
    _monitor_task = asyncio.create_task(
        start_deals_monitor(
            csv_path=csv_path,
            check_interval=300,
            enable_brand_monitoring=True,
            enable_analysis=True,
            min_flip_score=50,
        )
    )

    return JSONResponse(content={
        "status": "ok",
        "message": f"Tracker started with {csv_path}"
    })


@app.post("/keepa/poll/start")
async def start_polling(interval: int = 300):
    """Start automatic polling"""
    global _poll_task

    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    return JSONResponse(content={
        "status": "ok",
        "message": f"Polling every {interval} seconds (already running via monitor)"
    })


@app.post("/keepa/poll/stop")
async def stop_polling():
    """Stop automatic polling"""
    global _monitor_task

    if _monitor_task:
        _monitor_task.cancel()
        _monitor_task = None

    await stop_monitor()

    return JSONResponse(content={
        "status": "ok",
        "message": "Polling stopped"
    })


# ============================================================
# ROUTES - Deal Checking
# ============================================================

@app.get("/keepa/check")
async def check_deals():
    """Check for deals now"""
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        matches = await client.check_deals_against_tracked()

        deals = []
        for drop in matches:
            deals.append({
                "asin": drop.asin,
                "title": drop.title,
                "current_price": drop.current_price,
                "target_price": drop.target_price,
                "profit": drop.profit_potential,
                "roi": (drop.profit_potential / drop.current_price * 100) if drop.current_price > 0 else 0,
                "sales_rank": drop.sales_rank,
                "category": drop.category,
                "amazon_url": drop.amazon_url,
                "image_url": drop.image_url,
            })

        return JSONResponse(content={
            "status": "ok",
            "deals": deals,
            "count": len(deals)
        })
    except Exception as e:
        logger.error(f"Error checking deals: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@app.get("/keepa/discover")
async def open_discovery(
    min_discount: float = 40.0,
    min_profit: float = 5.0,
    max_rank: int = 500000,
    min_price: float = 10.0,
    max_price: float = 100.0,
    send_alerts: bool = False
):
    """
    Open Discovery Mode - Find ANY profitable deal on Amazon.

    Searches for deals matching criteria regardless of tracked ASINs.
    40% minimum discount by default.
    """
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        # Convert price to cents for API
        price_range = (int(min_price * 100), int(max_price * 100))

        deals = await client.check_open_discovery_deals(
            min_discount_pct=min_discount,
            min_profit=min_profit,
            max_sales_rank=max_rank,
            price_range=price_range,
        )

        # Optionally send Discord alerts
        alerts_sent = 0
        if send_alerts and deals:
            deduplicator = get_deduplicator()
            for deal in deals[:10]:  # Limit to top 10
                asin = deal["asin"]
                if deduplicator.should_alert(asin):
                    # Create PriceDrop for alert
                    from keepa_tracker import PriceDrop
                    price_drop = PriceDrop(
                        asin=asin,
                        title=deal["title"],
                        current_price=deal["current_price"],
                        previous_price=deal["previous_price"],
                        target_price=deal["estimated_sell_price"],
                        drop_percent=deal["discount_pct"],
                        sales_rank=deal["sales_rank"],
                        category=deal["category"],
                        image_url="",
                        amazon_url=deal["amazon_url"],
                        product_category=deal["category"],
                    )
                    await send_discord_alert(price_drop, source="open_discovery")
                    deduplicator.mark_alerted(asin)
                    alerts_sent += 1

        return JSONResponse(content={
            "status": "ok",
            "mode": "open_discovery",
            "criteria": {
                "min_discount": min_discount,
                "min_profit": min_profit,
                "max_rank": max_rank,
                "price_range": f"${min_price}-${max_price}"
            },
            "deals": deals,
            "count": len(deals),
            "alerts_sent": alerts_sent
        })
    except Exception as e:
        logger.error(f"Error in open discovery: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@app.get("/keepa/lookup")
async def lookup_asin(asin: str):
    """Look up a single ASIN"""
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        # Get product details
        product = await client.get_product_details(asin)

        if not product:
            return JSONResponse(content={
                "status": "not_found",
                "message": f"No data for ASIN: {asin}"
            })

        # Get analysis
        analysis = await client.analyze_product(asin)

        return JSONResponse(content={
            "status": "ok",
            "asin": asin,
            "analysis": analysis.to_dict(),
            "product": {
                "title": product.get("title", "Unknown"),
                "sales_rank": product.get("salesRank", 0),
                "offers_new": product.get("offerCountNew", 0),
                "offers_fba": product.get("offerCountFBA", 0),
            }
        })
    except Exception as e:
        logger.error(f"Error looking up {asin}: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@app.get("/keepa/analyze")
async def analyze_asin(asin: str):
    """Get detailed analysis for an ASIN"""
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        analysis = await client.analyze_product(asin)
        return JSONResponse(content={
            "status": "ok",
            "analysis": analysis.to_dict()
        })
    except Exception as e:
        logger.error(f"Error analyzing {asin}: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@app.get("/keepa/smart-analyze")
async def smart_analyze_asin(asin: str, price: float = None, title: str = None, category: str = "general"):
    """
    Smart analysis using the new DealAnalyzer.

    Based on good vs bad Keepa chart patterns:
    - Price stability (volatile = bad)
    - True deal detection (20%+ below 90d avg)
    - Amazon competition check (ok if sales > 200/mo)
    - Sales velocity analysis
    - Profit/ROI calculation
    """
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        # Fetch Keepa product data
        product_data = await client.get_product_details(asin)

        if not product_data:
            return JSONResponse(content={
                "status": "error",
                "message": "Could not fetch Keepa data for ASIN"
            }, status_code=404)

        # Get current price from Keepa if not provided
        if price is None:
            stats = product_data.get("stats", {})
            current_prices = stats.get("current", [])
            if len(current_prices) > 1 and current_prices[1] > 0:
                price = current_prices[1] / 100.0
            else:
                return JSONResponse(content={
                    "status": "error",
                    "message": "No price data available"
                }, status_code=400)

        # Get title from Keepa if not provided
        if not title:
            title = product_data.get("title", f"ASIN: {asin}")

        # Run analysis
        analyzer = DealAnalyzer()
        score = analyzer.analyze_deal(asin, title, price, product_data, category)

        return JSONResponse(content={
            "status": "ok",
            "score": score.to_dict(),
            "summary": {
                "recommendation": score.recommendation,
                "total_score": score.total_score,
                "is_good_deal": score.total_score >= 70,
                "current_price": price,
                "estimated_profit": round(score.estimated_profit, 2),
                "roi_percent": round(score.roi_percent, 1),
            }
        })
    except Exception as e:
        logger.error(f"Error smart-analyzing {asin}: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


@app.get("/keepa/smart-deals")
async def get_smart_deals(
    min_score: int = 60,
    min_drop_percent: int = 40,  # 40%+ drop = 30% ROI minimum
    max_sales_rank: int = 300000,
    max_results: int = 20,
    send_alerts: bool = True,
    alert_threshold: int = 70,
    min_price: float = 40.0,   # Min item price (need margin after ~$8-10 FBA fees)
    max_price: float = 2000.0,  # Max item price
):
    """
    Fetch deals from Keepa and filter using smart analysis.

    Uses QUICK FILTER to save tokens:
    1. Fetch deals from Deals API (50 tokens)
    2. Quick filter using only Deals data (FREE - no Product API calls)
    3. Only call Product API for deals that pass quick filter (1 token each)

    Returns only deals that pass the analysis criteria:
    - Score >= min_score (default 60)
    - Price drop >= min_drop_percent
    - Sales rank <= max_sales_rank

    If send_alerts=True, sends Discord alerts for deals with score >= alert_threshold.
    """
    client = get_client()
    if not client:
        return JSONResponse(content={
            "status": "error",
            "message": "Tracker not initialized"
        }, status_code=400)

    try:
        # Fetch raw deals from Keepa (50 tokens)
        # Use Buy Box price (18) to include FBA/3P sellers, not just Amazon
        logger.info(f"[SMART-DEALS] Fetching deals (min_drop={min_drop_percent}%, max_rank={max_sales_rank})...")
        raw_deals = await client.get_deals(
            price_types=18,  # Buy Box price (includes FBA/3P)
            delta_percent_range=(min_drop_percent, 100),
            delta_last_hours=24,
            sales_rank_range=(1, max_sales_rank),
            must_have_amazon=False,  # Don't require Amazon to be selling
        )

        logger.info(f"[SMART-DEALS] Got {len(raw_deals)} raw deals")

        # === QUICK FILTER (FREE - no tokens!) ===
        quick_filter_config = {
            "min_price": min_price,
            "max_price": max_price,
            "max_sales_rank": max_sales_rank,
            "min_drop_percent": min_drop_percent,
            "skip_amazon_competing": False,  # Include Amazon first-party deals
            "require_amazon_seller": False,  # Include 3P/FBA sellers too
        }

        passed_deals, filtered_count, filter_stats = quick_filter_deals(raw_deals, quick_filter_config)

        logger.info(f"[SMART-DEALS] Quick filter: {len(passed_deals)} passed, {filtered_count} filtered out")
        logger.info(f"[SMART-DEALS] Filter breakdown: {filter_stats}")
        logger.info(f"[SMART-DEALS] TOKEN SAVINGS: {filtered_count} Product API calls avoided!")

        # === FULL ANALYSIS (1 token per deal) ===
        analyzer = DealAnalyzer()
        smart_deals = []
        alerts_sent = 0
        product_api_calls = 0

        # Limit to avoid burning too many tokens
        max_product_lookups = min(len(passed_deals), 30)

        for deal, quick_result in passed_deals[:max_product_lookups]:
            asin = quick_result.asin
            title = quick_result.title
            current_price = quick_result.current_price

            # Fetch full product data for deep analysis (1 token)
            product_data = await client.get_product_details(asin)
            product_api_calls += 1

            if not product_data:
                logger.warning(f"[SMART-DEALS] No product data for {asin}")
                continue

            # Full analysis
            score = analyzer.analyze_deal(asin, title, current_price, product_data)

            if score.total_score >= min_score:
                smart_deals.append({
                    "asin": asin,
                    "title": title[:100],
                    "current_price": current_price,
                    "score": score.total_score,
                    "recommendation": score.recommendation,
                    "estimated_profit": round(score.estimated_profit, 2),
                    "roi_percent": round(score.roi_percent, 1),
                    "monthly_sales": score.estimated_monthly_sales,
                    "amazon_competing": score.amazon_is_competing,
                    "price_drop_percent": round(score.price_drop_percent, 1),
                    "flags": score.flags,
                    "reasons": score.reasons[:3],  # Top 3 reasons
                    "amazon_url": f"https://www.amazon.com/dp/{asin}",
                })

                logger.info(f"[SMART-DEALS] ✓ {asin}: Score {score.total_score} - {score.recommendation}")

                # Send Discord alert for high-score deals
                if send_alerts and score.total_score >= alert_threshold:
                    was_sent = await send_smart_deal_alert(score)
                    if was_sent:
                        alerts_sent += 1
                        logger.info(f"[SMART-DEALS] 📢 Discord alert sent for {asin}")

            if len(smart_deals) >= max_results:
                break

        # Sort by score
        smart_deals.sort(key=lambda x: x["score"], reverse=True)

        # Calculate token usage
        tokens_used = 50 + product_api_calls  # Deals API + Product lookups
        tokens_saved = filtered_count  # Each filtered deal = 1 token saved

        logger.info(f"[SMART-DEALS] Found {len(smart_deals)} deals (score >= {min_score}), {alerts_sent} alerts sent")
        logger.info(f"[SMART-DEALS] Tokens: {tokens_used} used, {tokens_saved} saved by quick filter")

        return JSONResponse(content={
            "status": "ok",
            "deals": smart_deals,
            "count": len(smart_deals),
            "alerts_sent": alerts_sent,
            "alert_threshold": alert_threshold,
            "token_stats": {
                "raw_deals": len(raw_deals),
                "quick_filtered": filtered_count,
                "product_api_calls": product_api_calls,
                "tokens_used": tokens_used,
                "tokens_saved": tokens_saved,
            },
            "filter_stats": filter_stats,
            "analyzer_stats": analyzer.get_stats(),
        })

    except Exception as e:
        logger.error(f"Error fetching smart deals: {e}")
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)


# ============================================================
# ROUTES - Alerts
# ============================================================

@app.post("/keepa/test-discord")
async def test_discord():
    """Send a test Discord alert"""
    if not DISCORD_WEBHOOK_URL:
        return JSONResponse(content={
            "status": "error",
            "message": "Discord webhook not configured"
        }, status_code=400)

    # Create test drop
    test_drop = PriceDrop(
        asin="B0TEST1234",
        title="Test Product - KeepaTracker Alert",
        current_price=19.99,
        previous_price=39.99,
        target_price=29.99,
        drop_percent=50.0,
        sales_rank=12345,
        category="Test",
        image_url="",
        amazon_url="https://www.amazon.com/dp/B0TEST1234",
        product_category="general",
    )

    success = await send_discord_alert(test_drop, skip_dedup=True)

    if success:
        return JSONResponse(content={
            "status": "ok",
            "message": "Test alert sent to Discord"
        })
    else:
        return JSONResponse(content={
            "status": "error",
            "message": "Failed to send alert"
        }, status_code=500)


@app.post("/keepa/test-smart-alert")
async def test_smart_alert():
    """Send a test smart deal Discord alert with fake high-score data"""
    if not DISCORD_WEBHOOK_URL:
        return JSONResponse(content={
            "status": "error",
            "message": "Discord webhook not configured"
        }, status_code=400)

    # Create a fake high-score DealScore
    test_score = DealScore(
        asin="B0CTEST123",
        title="Community Coffee Breakfast Blend Ground Coffee, 32 Ounce (Pack of 2)",
        current_price=18.99,
        sell_price=34.99,
        estimated_profit=9.50,
        roi_percent=50.0,
        total_score=82,
        recommendation="STRONG BUY",
        score_breakdown={
            "price_stability": 22,
            "true_deal": 20,
            "sales_velocity": 18,
            "amazon_competition": 12,
            "profit": 10,
        },
        reasons=[
            "Price 35% below 90-day average ($29.22)",
            "Stable price history (low volatility)",
            "High sales velocity (~450/month)",
            "Good ROI of 50%",
        ],
        flags=[],
        amazon_is_competing=False,
        estimated_monthly_sales=450,
        price_drop_percent=35.2,
        avg_price_90d=29.22,
        price_volatility=0.15,
    )

    success = await send_smart_deal_alert(test_score, skip_dedup=True)

    if success:
        return JSONResponse(content={
            "status": "ok",
            "message": "Test smart alert sent to Discord",
            "test_score": test_score.to_dict()
        })
    else:
        return JSONResponse(content={
            "status": "error",
            "message": "Failed to send smart alert"
        }, status_code=500)


# ============================================================
# ROUTES - Dashboard
# ============================================================

@app.get("/keepa/dashboard")
async def dashboard():
    """Serve the Keepa dashboard"""
    dashboard_path = Path(__file__).parent / "keepa_dashboard.html"

    if dashboard_path.exists():
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Update API base URL for this server
            content = content.replace(
                "const API_BASE = 'http://localhost:8000'",
                f"const API_BASE = 'http://localhost:{SERVER_PORT}'"
            )
            return HTMLResponse(content=content)
    else:
        return HTMLResponse(content="""
        <html>
        <body style="background: #0a0a0f; color: #fff; font-family: sans-serif; padding: 50px; text-align: center;">
            <h1>KeepaTracker</h1>
            <p>Dashboard file not found. API is running at port {}</p>
            <p><a href="/keepa/stats" style="color: #ff9500;">View Stats</a></p>
        </body>
        </html>
        """.format(SERVER_PORT))


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return JSONResponse(content={
        "status": "healthy",
        "service": "KeepaTracker",
        "timestamp": datetime.now().isoformat()
    })


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=SERVER_PORT,
        reload=False,
        log_level="info"
    )
