"""
Spot Price Fetcher - Auto-updating precious metal prices
Gold, Silver, Platinum, Palladium
"""

import json
import urllib.request
import threading
import time
from datetime import datetime
from typing import Optional

from config import SPOT_PRICES

# Try to import yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[SPOT] yfinance not installed. Run: pip install yfinance")


def update_gram_rates() -> None:
    """Update per-gram and karat rates from spot price"""
    gold_oz = SPOT_PRICES["gold_oz"]
    silver_oz = SPOT_PRICES["silver_oz"]
    platinum_oz = SPOT_PRICES.get("platinum_oz", 2412)
    palladium_oz = SPOT_PRICES.get("palladium_oz", 1908)

    # Convert to per-gram (31.1035 grams per troy ounce)
    gold_gram = gold_oz / 31.1035
    silver_gram = silver_oz / 31.1035
    platinum_gram = platinum_oz / 31.1035
    palladium_gram = palladium_oz / 31.1035

    SPOT_PRICES["gold_gram"] = gold_gram
    SPOT_PRICES["silver_gram"] = silver_gram
    SPOT_PRICES["platinum_gram"] = platinum_gram
    SPOT_PRICES["palladium_gram"] = palladium_gram

    # Update gold karat rates
    SPOT_PRICES["10K"] = gold_gram * 0.417
    SPOT_PRICES["14K"] = gold_gram * 0.583
    SPOT_PRICES["18K"] = gold_gram * 0.750
    SPOT_PRICES["22K"] = gold_gram * 0.917
    SPOT_PRICES["24K"] = gold_gram * 1.000
    SPOT_PRICES["sterling"] = silver_gram * 0.925

    # Platinum purity rates (PT950 = 95%, PT900 = 90%, PT850 = 85%)
    SPOT_PRICES["PT950"] = platinum_gram * 0.950
    SPOT_PRICES["PT900"] = platinum_gram * 0.900
    SPOT_PRICES["PT850"] = platinum_gram * 0.850

    # Palladium purity rates (PD950 = 95%, PD500 = 50%)
    SPOT_PRICES["PD950"] = palladium_gram * 0.950
    SPOT_PRICES["PD500"] = palladium_gram * 0.500

    print(f"[SPOT] Rates updated:")
    print(f"  Gold: ${gold_oz:.2f}/oz = ${gold_gram:.2f}/g")
    print(f"  Silver: ${silver_oz:.2f}/oz = ${silver_gram:.4f}/g")
    print(f"  Platinum: ${platinum_oz:.2f}/oz = ${platinum_gram:.2f}/g")
    print(f"  Palladium: ${palladium_oz:.2f}/oz = ${palladium_gram:.2f}/g")
    print(f"  14K: ${SPOT_PRICES['14K']:.2f}/g | PT950: ${SPOT_PRICES['PT950']:.2f}/g")


def fetch_from_yahoo() -> bool:
    """Fetch prices from Yahoo Finance"""
    if not YFINANCE_AVAILABLE:
        return False

    try:
        print("[SPOT] Trying Yahoo Finance...")
        gold = yf.Ticker("GC=F")
        silver = yf.Ticker("SI=F")
        platinum = yf.Ticker("PL=F")
        palladium = yf.Ticker("PA=F")

        gold_price = gold.fast_info.get('lastPrice', None)
        silver_price = silver.fast_info.get('lastPrice', None)
        platinum_price = platinum.fast_info.get('lastPrice', None)
        palladium_price = palladium.fast_info.get('lastPrice', None)

        if gold_price and silver_price and gold_price > 1000:  # Sanity check
            SPOT_PRICES["gold_oz"] = gold_price
            SPOT_PRICES["silver_oz"] = silver_price
            SPOT_PRICES["platinum_oz"] = platinum_price if platinum_price else 2412
            SPOT_PRICES["palladium_oz"] = palladium_price if palladium_price else 1908
            SPOT_PRICES["source"] = "Yahoo Finance"
            SPOT_PRICES["last_updated"] = datetime.now().isoformat()
            update_gram_rates()
            print(f"[SPOT] OK Yahoo - Gold: ${gold_price:.2f}, Silver: ${silver_price:.2f}")
            print(f"[SPOT] OK Yahoo - Platinum: ${SPOT_PRICES['platinum_oz']:.2f}, Palladium: ${SPOT_PRICES['palladium_oz']:.2f}")
            return True
    except Exception as e:
        print(f"[SPOT] Yahoo Finance failed: {e}")

    return False


def fetch_from_metals_live() -> bool:
    """Fetch prices from Metals.live API (free, no key)"""
    try:
        print("[SPOT] Trying Metals.live API...")
        req = urllib.request.Request(
            "https://api.metals.live/v1/spot",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if item.get('gold'):
                        SPOT_PRICES["gold_oz"] = float(item['gold'])
                    if item.get('silver'):
                        SPOT_PRICES["silver_oz"] = float(item['silver'])
                
                SPOT_PRICES["source"] = "Metals.live"
                SPOT_PRICES["last_updated"] = datetime.now().isoformat()
                update_gram_rates()
                print(f"[SPOT] OK Metals.live - Gold: ${SPOT_PRICES['gold_oz']:.2f}/oz, Silver: ${SPOT_PRICES['silver_oz']:.2f}/oz")
                return True
    except Exception as e:
        print(f"[SPOT] Metals.live failed: {e}")
    
    return False


def fetch_spot_prices() -> bool:
    """Fetch current gold and silver spot prices"""
    print("\n" + "=" * 60)
    print("[SPOT] Fetching current spot prices...")
    print("=" * 60)
    
    # Try Yahoo Finance first (most reliable)
    if fetch_from_yahoo():
        return True
    
    # Fall back to Metals.live
    if fetch_from_metals_live():
        return True
    
    print("[SPOT] WARNING: Using default/cached prices")
    return False


def get_spot_prices() -> dict:
    """Get current spot prices"""
    return SPOT_PRICES.copy()


def refresh_spot_prices() -> dict:
    """Force refresh spot prices and return them"""
    fetch_spot_prices()
    return get_spot_prices()


# Background update thread
_update_thread: Optional[threading.Thread] = None
_stop_updates = threading.Event()


def start_spot_updates(interval_minutes: int = 240):
    """Start background thread for periodic spot price updates
    
    Default: 240 minutes (4 hours) - spot prices don't change fast enough to need frequent updates
    """
    global _update_thread
    
    if _update_thread is not None and _update_thread.is_alive():
        print("[SPOT] Update thread already running")
        return
    
    def update_loop():
        while not _stop_updates.wait(interval_minutes * 60):
            print(f"\n[SPOT] Scheduled refresh...")
            fetch_spot_prices()
    
    _stop_updates.clear()
    _update_thread = threading.Thread(target=update_loop, daemon=True)
    _update_thread.start()
    hours = interval_minutes / 60
    print(f"[SPOT] Background updates started (every {hours:.1f} hours / {interval_minutes} minutes)")


def stop_spot_updates():
    """Stop background spot price updates"""
    _stop_updates.set()
    print("[SPOT] Background updates stopped")


# Initial fetch on module load
fetch_spot_prices()
