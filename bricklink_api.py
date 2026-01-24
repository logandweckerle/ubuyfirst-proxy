"""
Bricklink API Module
OAuth 1.0a authenticated price lookups for LEGO sets

Especially useful for Bricklink Designer Program sets (910xxx) not in PriceCharting
"""

import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
import json
from typing import Optional, Dict

# Load credentials from environment
CONSUMER_KEY = os.getenv("BRICKLINK_CONSUMER_KEY", "")
CONSUMER_SECRET = os.getenv("BRICKLINK_CONSUMER_SECRET", "")
TOKEN = os.getenv("BRICKLINK_TOKEN", "")
TOKEN_SECRET = os.getenv("BRICKLINK_TOKEN_SECRET", "")

API_BASE = "https://api.bricklink.com/api/store/v1"

# Simple cache to avoid hammering API
_cache = {}
CACHE_TTL = 3600  # 1 hour


def _generate_nonce():
    """Generate a random nonce for OAuth"""
    import random
    import string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))


def _oauth_signature(method: str, url: str, params: dict) -> str:
    """Generate OAuth 1.0a signature"""
    # Sort parameters
    sorted_params = sorted(params.items())
    param_string = urllib.parse.urlencode(sorted_params, quote_via=urllib.parse.quote)

    # Create signature base string
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_string, safe="")
    ])

    # Create signing key
    signing_key = f"{urllib.parse.quote(CONSUMER_SECRET, safe='')}&{urllib.parse.quote(TOKEN_SECRET, safe='')}"

    # Generate HMAC-SHA1 signature
    signature = hmac.new(
        signing_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha1
    )

    return base64.b64encode(signature.digest()).decode('utf-8')


def _make_request(endpoint: str, params: dict = None) -> Optional[dict]:
    """Make authenticated request to Bricklink API"""
    if not all([CONSUMER_KEY, CONSUMER_SECRET, TOKEN, TOKEN_SECRET]):
        print("[BRICKLINK] API credentials not configured")
        return None

    url = f"{API_BASE}{endpoint}"
    method = "GET"

    # OAuth parameters
    oauth_params = {
        "oauth_consumer_key": CONSUMER_KEY,
        "oauth_token": TOKEN,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": _generate_nonce(),
        "oauth_version": "1.0"
    }

    # Combine with request params for signature
    all_params = oauth_params.copy()
    if params:
        all_params.update(params)

    # Generate signature
    oauth_params["oauth_signature"] = _oauth_signature(method, url, all_params)

    # Build Authorization header
    auth_header = "OAuth " + ", ".join([
        f'{k}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth_params.items())
    ])

    # Build URL with query params
    if params:
        url += "?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={
            "Authorization": auth_header,
            "Accept": "application/json"
        })

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data

    except urllib.error.HTTPError as e:
        print(f"[BRICKLINK] HTTP Error {e.code}: {e.reason}")
        try:
            error_body = e.read().decode('utf-8')
            print(f"[BRICKLINK] Response: {error_body[:200]}")
        except:
            pass
        return None
    except Exception as e:
        print(f"[BRICKLINK] Error: {e}")
        return None


def get_price_guide(set_number: str, condition: str = "N") -> Optional[Dict]:
    """
    Get price guide for a LEGO set

    Args:
        set_number: LEGO set number (e.g., "910041" or "910041-1")
        condition: "N" for new, "U" for used

    Returns:
        Dict with price info or None
    """
    # Normalize set number (add -1 suffix if not present)
    if "-" not in set_number:
        set_number = f"{set_number}-1"

    cache_key = f"price_{set_number}_{condition}"
    if cache_key in _cache:
        cached, timestamp = _cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            print(f"[BRICKLINK] Cache hit: {set_number}")
            return cached

    # Get price guide
    # item_type: SET, guide_type: sold (actual sales) or stock (current listings)
    endpoint = f"/items/SET/{set_number}/price"
    params = {
        "guide_type": "sold",  # Use actual sold prices
        "new_or_used": condition,
        "region": "north_america",
        "currency_code": "USD"
    }

    result = _make_request(endpoint, params)

    if result and result.get("meta", {}).get("code") == 200:
        data = result.get("data", {})

        price_info = {
            "set_number": set_number,
            "condition": "New" if condition == "N" else "Used",
            "avg_price": float(data.get("avg_price", 0)),
            "min_price": float(data.get("min_price", 0)),
            "max_price": float(data.get("max_price", 0)),
            "qty_avg_price": float(data.get("qty_avg_price", 0)),  # Qty-weighted avg
            "total_quantity": data.get("total_quantity", 0),
            "unit_quantity": data.get("unit_quantity", 0),  # Number of sales
            "currency": data.get("currency_code", "USD"),
            "source": "bricklink"
        }

        # Cache result
        _cache[cache_key] = (price_info, time.time())

        print(f"[BRICKLINK] {set_number} ({condition}): Avg ${price_info['avg_price']:.2f} ({price_info['unit_quantity']} sales)")
        return price_info

    print(f"[BRICKLINK] No price data for {set_number}")
    return None


def get_item_info(set_number: str) -> Optional[Dict]:
    """Get item details (name, year, etc.)"""
    if "-" not in set_number:
        set_number = f"{set_number}-1"

    cache_key = f"item_{set_number}"
    if cache_key in _cache:
        cached, timestamp = _cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            return cached

    endpoint = f"/items/SET/{set_number}"
    result = _make_request(endpoint)

    if result and result.get("meta", {}).get("code") == 200:
        data = result.get("data", {})

        item_info = {
            "set_number": set_number,
            "name": data.get("name", ""),
            "category_id": data.get("category_id"),
            "year_released": data.get("year_released"),
            "weight": data.get("weight"),  # in grams
            "dim_x": data.get("dim_x"),
            "dim_y": data.get("dim_y"),
            "dim_z": data.get("dim_z"),
        }

        _cache[cache_key] = (item_info, time.time())
        print(f"[BRICKLINK] Item: {item_info['name']} ({item_info['year_released']})")
        return item_info

    return None


def lookup_set(set_number: str, listing_price: float = 0, condition: str = "new") -> Dict:
    """
    Full lookup for a LEGO set - returns pricing and profit analysis

    Args:
        set_number: LEGO set number
        listing_price: Current listing price to calculate profit
        condition: "new" or "used"

    Returns:
        Dict with pricing, profit, recommendation
    """
    bl_condition = "N" if condition.lower() == "new" else "U"

    # Get price guide
    prices = get_price_guide(set_number, bl_condition)

    if not prices:
        return {
            "found": False,
            "set_number": set_number,
            "error": "Not found in Bricklink",
            "source": "bricklink"
        }

    # Get item info
    item = get_item_info(set_number)

    # Use qty-weighted average as market price (more accurate than simple avg)
    market_price = prices["qty_avg_price"] if prices["qty_avg_price"] > 0 else prices["avg_price"]

    # Calculate buy target (70% of market for resale margin)
    buy_target = market_price * 0.70

    # Calculate profit
    profit = buy_target - listing_price if listing_price > 0 else 0

    result = {
        "found": True,
        "set_number": set_number,
        "name": item["name"] if item else "",
        "year": item["year_released"] if item else None,
        "condition": prices["condition"],
        "market_price": round(market_price, 2),
        "buy_target": round(buy_target, 2),
        "listing_price": listing_price,
        "profit": round(profit, 2),
        "min_price": prices["min_price"],
        "max_price": prices["max_price"],
        "sales_count": prices["unit_quantity"],
        "source": "bricklink",
        "confidence": "High" if prices["unit_quantity"] >= 5 else "Medium" if prices["unit_quantity"] >= 2 else "Low"
    }

    # Add recommendation
    if listing_price > 0:
        if profit >= 30 and result["confidence"] in ["High", "Medium"]:
            result["recommendation"] = "BUY"
        elif profit < 0:
            result["recommendation"] = "PASS"
        else:
            result["recommendation"] = "RESEARCH"

    return result


def is_available() -> bool:
    """Check if Bricklink API is configured"""
    return all([CONSUMER_KEY, CONSUMER_SECRET, TOKEN, TOKEN_SECRET]) and \
           CONSUMER_KEY != "your_consumer_key_here"


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    # Reload env vars
    CONSUMER_KEY = os.getenv("BRICKLINK_CONSUMER_KEY", "")
    CONSUMER_SECRET = os.getenv("BRICKLINK_CONSUMER_SECRET", "")
    TOKEN = os.getenv("BRICKLINK_TOKEN", "")
    TOKEN_SECRET = os.getenv("BRICKLINK_TOKEN_SECRET", "")

    print(f"API Configured: {is_available()}")

    if is_available():
        # Test with a Designer Program set
        result = lookup_set("910041", listing_price=200, condition="new")
        print(json.dumps(result, indent=2))
