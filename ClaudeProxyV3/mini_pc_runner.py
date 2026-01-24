"""
Mini PC Runner - Standalone launcher for eBay Poller + Keepa Tracker

Runs both services independently on the mini PC:
- eBay Poller: Polls eBay Browse API for new listings, sends to main PC for analysis
- Keepa Tracker: Monitors Amazon price drops via Keepa Deals API, sends Discord alerts

Setup:
1. Clone repo on mini PC
2. pip install -r requirements.txt
3. Copy .env.example to .env and fill in your keys
4. Set PROXY_URL to your main PC's IP (e.g., http://192.168.1.100:8000)
5. python mini_pc_runner.py
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure we're in the right directory for imports
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mini_pc")


async def run_ebay_poller():
    """Start the eBay poller with analysis callback"""
    from ebay_poller import start_polling, analyze_listing_callback

    proxy_url = os.getenv("PROXY_URL", "http://127.0.0.1:8000")
    logger.info(f"[POLLER] Starting eBay poller (proxy: {proxy_url})")

    await start_polling(callback=analyze_listing_callback)

    # Keep alive
    while True:
        await asyncio.sleep(3600)


async def run_keepa_tracker():
    """Start the Keepa deals monitor"""
    from keepa_tracker_v2 import start_deals_monitor

    csv_path = os.getenv("KEEPA_CSV_PATH", "asin-tracker-tasks-export.csv")
    check_interval = int(os.getenv("KEEPA_CHECK_INTERVAL", "300"))

    logger.info(f"[KEEPA] Starting Keepa tracker (interval: {check_interval}s)")

    await start_deals_monitor(
        csv_path=csv_path,
        check_interval=check_interval,
        enable_brand_monitoring=True,
        enable_analysis=True,
        min_flip_score=50,
    )


async def main():
    """Run both services concurrently"""
    logger.info("=" * 50)
    logger.info("  Mini PC Runner - eBay Poller + Keepa Tracker")
    logger.info("=" * 50)

    proxy_url = os.getenv("PROXY_URL", "http://127.0.0.1:8000")
    logger.info(f"  Proxy URL: {proxy_url}")
    logger.info(f"  Keepa Key: {'SET' if os.getenv('KEEPA_API_KEY') else 'NOT SET'}")
    logger.info(f"  eBay Keys: {'SET' if os.getenv('EBAY_APP_ID') else 'NOT SET'}")
    logger.info(f"  Discord:   {'SET' if os.getenv('DISCORD_WEBHOOK_URL') else 'NOT SET'}")
    logger.info("=" * 50)

    # Determine which services to run
    run_poller = os.getenv("ENABLE_POLLER", "true").lower() == "true"
    run_keepa = os.getenv("ENABLE_KEEPA", "true").lower() == "true"

    tasks = []

    if run_poller and os.getenv("EBAY_APP_ID"):
        tasks.append(asyncio.create_task(run_ebay_poller()))
        logger.info("[STARTUP] eBay Poller: ENABLED")
    else:
        logger.info("[STARTUP] eBay Poller: DISABLED (missing EBAY_APP_ID or ENABLE_POLLER=false)")

    if run_keepa and os.getenv("KEEPA_API_KEY"):
        tasks.append(asyncio.create_task(run_keepa_tracker()))
        logger.info("[STARTUP] Keepa Tracker: ENABLED")
    else:
        logger.info("[STARTUP] Keepa Tracker: DISABLED (missing KEEPA_API_KEY or ENABLE_KEEPA=false)")

    if not tasks:
        logger.error("[STARTUP] No services enabled! Check your .env file.")
        return

    # Wait for all tasks (they run forever)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("[SHUTDOWN] Services stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MINI PC] Stopped by user (Ctrl+C)")
