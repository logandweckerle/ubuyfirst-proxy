"""
eBay Browse API Poller
Direct eBay API integration for listing monitoring

This module:
1. Uses Browse API (modern REST API) for searching eBay
2. Handles OAuth token management automatically

Usage:
    from ebay_poller import start_polling, get_new_listings, get_api_stats

    # Start background polling
    start_polling()

    # Or manually fetch
    listings = await get_new_listings("gold")
"""

import os
import asyncio
import logging
import httpx
import json
import threading
import time as _time
import base64
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import urllib.parse

# Import blocked sellers for filtering
try:
    from utils.spam_detection import BLOCKED_SELLERS, check_seller_spam
    BLOCKED_SELLERS_ENABLED = True
    from config import INSTANT_PASS_KEYWORDS, UBF_TITLE_FILTERS, UBF_LOCATION_FILTERS, UBF_FEEDBACK_RULES
except ImportError:
    BLOCKED_SELLERS = set()
    BLOCKED_SELLERS_ENABLED = False
    
# Import seller profiling
try:
    from database import (
        analyze_new_seller,
        score_seller_for_listing,
        get_seller_profile,
        save_seller_profile,
        calculate_seller_score
    )
    SELLER_PROFILING_ENABLED = True
except ImportError:
    SELLER_PROFILING_ENABLED = False

# Logger - must be defined early before any functions that use it
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ebay_poller")
logger.setLevel(logging.INFO)  # Explicitly set level

if not SELLER_PROFILING_ENABLED:
    logger.warning("[EBAY API] Seller profiling not available - database module not found")

# ============================================================
# CONFIGURATION
# ============================================================

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")

# Discord webhook for API monitoring
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_NOTIFY_ALL_LISTINGS = True  # Send EVERY new listing to Discord for monitoring
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID", "")  # Client Secret for OAuth

# API endpoints
BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"  # Legacy fallback

# OAuth token cache
_oauth_token: Optional[str] = None
_oauth_expires: Optional[datetime] = None
_oauth_lock = threading.Lock()

# Rate limiting - Production mode with efficient itemStartDate filtering
# With efficient filtering, we can poll faster since responses are smaller
# Daily quota: 25,000 calls/day (increased from 5K on 2026-01-16)
RATE_LIMIT_MIN_INTERVAL = 2.0  # 2 seconds between calls - aggressive for speed

# Track last API call time for rate limiting
_last_api_call: Optional[float] = None

# Efficient polling: Track newest timestamp per keyword for itemStartDate filtering
# This dramatically reduces data transfer by only fetching truly new items
KEYWORD_TIMESTAMPS: Dict[str, datetime] = {}
_rate_limit_lock: Optional[asyncio.Lock] = None  # Async lock for proper serialization

def _get_rate_limit_lock():
    """Get or create the async rate limit lock"""
    global _rate_limit_lock
    if _rate_limit_lock is None:
        _rate_limit_lock = asyncio.Lock()
    return _rate_limit_lock

async def rate_limit_wait():
    """Wait if needed to respect rate limits - properly serializes concurrent callers"""
    global _last_api_call

    lock = _get_rate_limit_lock()

    # Hold the lock through the entire wait to prevent concurrent calls
    async with lock:
        now = _time.time()
        if _last_api_call is not None:
            elapsed = now - _last_api_call
            if elapsed < RATE_LIMIT_MIN_INTERVAL:
                wait_time = RATE_LIMIT_MIN_INTERVAL - elapsed
                logger.info(f"[EBAY API] Rate limiting: waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        # Update last call time BEFORE releasing lock
        _last_api_call = _time.time()


# ============================================================
# DISCORD NOTIFICATIONS
# ============================================================

async def send_discord_listing(
    listing,
    keyword: str = "",
    source: str = "API",
    recommendation: str = None,
    reasoning: str = None,
    melt_value: float = None,
    max_buy: float = None
):
    """
    Send a new listing notification to Discord for monitoring.
    This helps verify the API is actually finding listings.

    Args:
        listing: The eBay listing object
        keyword: Search keyword that found this item
        source: Source identifier (e.g., "RACE-API-BUY")
        recommendation: BUY/RESEARCH/PASS
        reasoning: Explanation for the recommendation
        melt_value: Calculated melt value if applicable
        max_buy: Maximum buy price if applicable
    """
    if not DISCORD_WEBHOOK_URL or not DISCORD_NOTIFY_ALL_LISTINGS:
        return

    try:
        # Color based on recommendation
        if recommendation == "BUY":
            color = 0x00ff00  # Green
            emoji = "💰"
        elif recommendation == "RESEARCH":
            color = 0xffff00  # Yellow
            emoji = "🔍"
        else:
            color = 0x808080  # Gray
            emoji = "📋"

        # Format the embed - Title is clickable link to item
        item_url = listing.view_url if hasattr(listing, 'view_url') and listing.view_url else f"https://www.ebay.com/itm/{listing.item_id}"
        embed = {
            "title": listing.title[:200] if hasattr(listing, 'title') else "New Listing",
            "url": item_url,  # Makes title clickable
            "description": f"{emoji} **{source}**: {recommendation or 'Monitoring'}",
            "color": color,
            "fields": [
                {"name": "💵 Price", "value": f"${listing.price:.2f}" if hasattr(listing, 'price') else "N/A", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add analysis fields if available
        if melt_value:
            embed["fields"].append({"name": "🔥 Melt Value", "value": f"${melt_value:.0f}", "inline": True})
        if max_buy:
            embed["fields"].append({"name": "📊 Max Buy", "value": f"${max_buy:.0f}", "inline": True})
            if hasattr(listing, 'price') and listing.price:
                margin = max_buy - listing.price
                embed["fields"].append({"name": "💎 Margin", "value": f"${margin:.0f}", "inline": True})

        # Add reasoning
        if reasoning:
            embed["fields"].append({"name": "📝 Analysis", "value": reasoning[:100], "inline": False})

        # Add seller info
        embed["fields"].append({"name": "👤 Seller", "value": listing.seller_id[:30] if hasattr(listing, 'seller_id') else "N/A", "inline": True})
        embed["fields"].append({"name": "🔎 Keyword", "value": keyword[:50] if keyword else "N/A", "inline": True})

        # Add seller score if available
        if hasattr(listing, 'seller_score') and listing.seller_score != 50:
            embed["fields"].append({
                "name": "📊 Seller Score",
                "value": f"{listing.seller_score} ({listing.seller_priority})" if hasattr(listing, 'seller_priority') else str(listing.seller_score),
                "inline": True
            })

        # URL is already set in embed title above

        # Add "I Bought This" link
        if hasattr(listing, 'item_id'):
            purchase_data = {
                "title": listing.title[:100] if hasattr(listing, 'title') else "",
                "price": listing.price if hasattr(listing, 'price') else 0,
                "category": "gold" if "gold" in keyword.lower() or "14k" in keyword.lower() else "silver",
                "item_id": listing.item_id,
                "profit": (max_buy - listing.price) if max_buy and hasattr(listing, 'price') else 0,
                "seller_id": listing.seller_id if hasattr(listing, 'seller_id') else "",
                "melt": melt_value or 0,
            }
            purchase_params = urllib.parse.urlencode(purchase_data)
            log_url = f"http://localhost:8000/log-purchase-quick?{purchase_params}"
            embed["fields"].append({
                "name": "🛒 Log Purchase",
                "value": f"[I Bought This]({log_url})",
                "inline": True
            })

        # Add thumbnail
        if hasattr(listing, 'thumbnail_url') and listing.thumbnail_url:
            embed["thumbnail"] = {"url": listing.thumbnail_url}

        # Add item ID for tracking
        if hasattr(listing, 'item_id'):
            embed["footer"] = {"text": f"Item ID: {listing.item_id}"}

        payload = {
            "embeds": [embed],
            "username": "eBay API Monitor"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload)
            if response.status_code not in (200, 204):
                logger.warning(f"[DISCORD] Failed to send: {response.status_code}")

    except Exception as e:
        logger.debug(f"[DISCORD] Error sending notification: {e}")


async def send_discord_status(message: str, color: int = 0x0099ff):
    """Send a status message to Discord"""
    if not DISCORD_WEBHOOK_URL:
        return

    try:
        payload = {
            "embeds": [{
                "title": "📡 eBay API Status",
                "description": message,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
            }],
            "username": "eBay API Monitor"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        logger.debug(f"[DISCORD] Status error: {e}")


async def get_oauth_token() -> Optional[str]:
    """
    Get OAuth2 token for Browse API using Client Credentials flow.
    Caches token until it expires.
    """
    global _oauth_token, _oauth_expires

    # Check if we have a valid cached token
    with _oauth_lock:
        if _oauth_token and _oauth_expires and datetime.now() < _oauth_expires:
            return _oauth_token

    if not EBAY_APP_ID or not EBAY_CERT_ID:
        logger.warning("[EBAY OAuth] Missing EBAY_APP_ID or EBAY_CERT_ID")
        return None

    try:
        # Create Basic Auth header
        credentials = f"{EBAY_APP_ID}:{EBAY_CERT_ID}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_credentials}",
        }

        # Request application token (no user auth needed for Browse API search)
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(OAUTH_URL, headers=headers, data=data)

            if response.status_code != 200:
                logger.error(f"[EBAY OAuth] Token request failed: {response.status_code} - {response.text[:200]}")
                return None

            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 7200)  # Default 2 hours

            if access_token:
                with _oauth_lock:
                    _oauth_token = access_token
                    # Set expiry 5 minutes early to be safe
                    _oauth_expires = datetime.now() + timedelta(seconds=expires_in - 300)
                logger.info(f"[EBAY OAuth] Token acquired, expires in {expires_in}s")
                return access_token
            else:
                logger.error("[EBAY OAuth] No access_token in response")
                return None

    except Exception as e:
        logger.error(f"[EBAY OAuth] Error getting token: {e}")
        return None


def browse_api_available() -> bool:
    """Check if Browse API credentials are configured"""
    return bool(EBAY_APP_ID and EBAY_CERT_ID)


# ============================================================
# STAGGERED POLLING CONFIGURATION
# ============================================================
# Round-robin polling: one keyword at a time, cycling through all
# Target: 25,000 calls / 14 hours = 1,785 calls/hour = 1 call every 2 seconds
# With 3 keywords, each keyword refreshes every 2s * 3 = 6 seconds
# This should consistently beat uBuyFirst's 6-38 second latency
STAGGERED_POLL_INTERVAL = 2.0  # Seconds between each API call (AGGRESSIVE - 25K quota)

# Legacy intervals (kept for reference/fallback)
POLL_INTERVAL_GOLD = 26      # Each gold keyword refreshes every ~26s
POLL_INTERVAL_SILVER = 26    # Each silver keyword refreshes every ~26s
POLL_INTERVAL_TCG = 600      # TCG - disabled, 10 min placeholder
POLL_INTERVAL_LEGO = 600     # LEGO - disabled, 10 min placeholder

# ============================================================
# RSS FEED CONFIGURATION
# ============================================================
# NOTE: eBay public RSS feeds appear to be deprecated/blocked (returns HTML not XML)
# uBuyFirst likely uses a proprietary method or eBay partner API for their RSS
# Keeping code in place but DISABLED until we find a working RSS endpoint
RSS_ENABLED = False  # DISABLED - eBay public RSS returns HTML, not XML
RSS_POLL_INTERVAL = 5.0  # Seconds between RSS polls (can be faster since no rate limit)
RSS_BASE_URL = "https://www.ebay.com/sch/i.html"

# Track API usage - persisted to file for survival across restarts
API_STATS_FILE = Path(__file__).parent / "api_stats.json"

def _load_api_stats() -> dict:
    """Load API stats from file, reset if new day"""
    default_stats = {
        "total_calls": 0,
        "calls_today": 0,
        "last_reset": datetime.now().date().isoformat(),
        "calls_by_category": {},
        "errors": 0,
        "last_call": None,
    }

    if API_STATS_FILE.exists():
        try:
            with open(API_STATS_FILE, 'r') as f:
                saved = json.load(f)
                # Check if it's a new day - reset if so
                saved_date = saved.get("last_reset", "")
                today = datetime.now().date().isoformat()
                if saved_date != today:
                    logger.info(f"[EBAY API] New day - resetting stats (yesterday: {saved.get('calls_today', 0)} calls)")
                    saved["calls_today"] = 0
                    saved["calls_by_category"] = {}
                    saved["errors"] = 0
                    saved["last_reset"] = today
                return saved
        except Exception as e:
            logger.warning(f"[EBAY API] Could not load stats: {e}")
    return default_stats

def _save_api_stats():
    """Save API stats to file"""
    try:
        # Convert date objects to strings for JSON
        stats_to_save = API_STATS.copy()
        if isinstance(stats_to_save.get("last_reset"), date):
            stats_to_save["last_reset"] = stats_to_save["last_reset"].isoformat()
        if stats_to_save.get("last_call"):
            stats_to_save["last_call"] = stats_to_save["last_call"].isoformat() if hasattr(stats_to_save["last_call"], 'isoformat') else str(stats_to_save["last_call"])

        with open(API_STATS_FILE, 'w') as f:
            json.dump(stats_to_save, f, indent=2)
    except Exception as e:
        logger.warning(f"[EBAY API] Could not save stats: {e}")

# Load stats on module import
API_STATS = _load_api_stats()

# Track seen listings to avoid duplicates
SEEN_LISTINGS: Dict[str, datetime] = {}
SEEN_LISTINGS_MAX_AGE = 3600  # Forget listings after 1 hour

# Keyword rotation - only search a subset per poll to avoid rate limits
KEYWORDS_PER_POLL = 10  # Max keywords to search per poll cycle
KEYWORD_ROTATION_INDEX: Dict[str, int] = {}  # Track rotation position per category

# OPTIMIZED: 3 priority keywords with 25K calls/day quota
# With 2s between calls, each keyword refreshes every 6 seconds
# This beats uBuyFirst's typical 6-38 second latency consistently
#
# IMPORTANT: Using specific category IDs for faster eBay indexing
# Categories from uBuyFirst config:
#   Gold: 281 (Jewelry), 162134 (Gold Bullion), 3360 (Coins & Paper Money)
#   Silver: 20081 (Fine Silver), 163271 (Sterling Silver Mixed Lots)
PRIORITY_KEYWORDS = {
    "gold": [
        # Keep to 3-4 keywords for fast refresh (~8-10s each @ 2s interval)
        "14k gold",       # Broadest 14k coverage - most common karat
        "18k gold",       # Higher karat = higher value
        "10k gold",       # 10k items
    ],
    "silver": [
        # Match uBuyFirst's "New Silver Search" keywords exactly for race testing
        "sterling scrap",
        "sterling lot",
        "sterling flatware",
        "925 scrap",
        "sterling gorham",
        "sterling towle",
    ],
}

# Category IDs for priority keywords (NOT searching all categories!)
# Match uBuyFirst's exact categories for race testing
PRIORITY_CATEGORY_IDS = {
    "gold": ["281", "162134", "3360"],  # Jewelry, Gold Bullion, Coins
    "silver": ["20096", "262022", "281", "2213"],  # uBuyFirst: 20096/262022 (New Silver Search), 281/2213 (Search 2)
}
# BATCHED KEYWORDS - Available but disabled to maximize speed on priority keywords
# With 25K quota, could enable these if broader coverage preferred over speed
# Each additional keyword adds 2s to the refresh cycle time
BATCHED_KEYWORDS = {
    "gold": [],      # DISABLED - using priority only for max speed
    "watch": [],     # DISABLED
    "silver": [],    # DISABLED - using priority only for max speed
}

def clear_seen_listings():
    """Clear the seen listings cache - useful for race testing"""
    global SEEN_LISTINGS
    count = len(SEEN_LISTINGS)
    SEEN_LISTINGS.clear()
    logger.info(f"[EBAY API] Cleared {count} seen listings from cache")
    return count

# ============================================================
# LOAD KEYWORDS FROM UBUYFIRST EXPORT
# ============================================================

def load_ubuyfirst_keywords() -> dict:
    """Load keywords from uBuyFirst export JSON file"""
    keywords_file = Path(__file__).parent / "ubuyfirst_keywords.json"
    if keywords_file.exists():
        try:
            with open(keywords_file, 'r') as f:
                data = json.load(f)
                gold_count = len(data.get('gold', []))
                silver_count = len(data.get('silver', []))
                logger.info(f"[EBAY API] Loaded {gold_count} gold + {silver_count} silver keywords from uBuyFirst")
                return data
        except Exception as e:
            logger.error(f"[EBAY API] Failed to load keywords file: {e}")
    else:
        logger.warning(f"[EBAY API] Keywords file not found: {keywords_file}")
    return None

# Load keywords from uBuyFirst export
_UBUYFIRST_KEYWORDS = load_ubuyfirst_keywords()

# ============================================================
# SEARCH CONFIGURATIONS (from your uBuyFirst export)
# ============================================================

SEARCH_CONFIGS = {
    "gold": {
        "keywords": [
            # === 8K/9K (European) ===
            "8k gold", "8kt gold", "9k gold", "9kt gold",
            "8k scrap", "9k scrap", "375 gold", "375 scrap",
            # === 10K ===
            "10k grams", "10kt grams", "10k scrap", "10kt scrap",
            "10k bracelet", "10k ring", "10k chain", "10k lot",
            "10k necklace", "417 gold", "417 scrap",
            # === 14K (most common) ===
            "14k grams", "14kt grams", "14k gram", "14k scrap", "14kt scrap",
            "14k bracelet", "14kt bracelet", "14k lot", "14k ring", "14k chain",
            "14k necklace", "14k watch", "14k vintage", "14k diamond", "14k charm",
            "14k pendant", "14k earrings", "14k bangle",
            "585 gold", "585 grams", "585 scrap", "583 gold",
            # === 18K ===
            "18k grams", "18kt grams", "18k gram", "18k scrap", "18kt scrap",
            "18k bracelet", "18kt bracelet", "18k lot", "18k ring", "18k chain",
            "18k necklace", "750 gold", "750 grams", "750 scrap",
            # === 22K/24K ===
            "22k gold", "22kt gold", "22k scrap", "22k bracelet",
            "916 gold", "950 gold", "24k gold", "fine gold",
            # === Generic/Scrap ===
            "scrap gold", "gold scrap lot", "gold jewelry lot",
            "karat gold scrap", "solid gold lot",
            # === Gold Nuggets (natural gold ~85% pure) ===
            "gold nugget", "gold nuggets", "placer gold", "raw gold",
            "natural gold nugget", "alaska gold nugget", "california gold",
            # === Dental Gold (usually 10K-22K) ===
            "dental gold", "dental scrap gold", "gold crowns", "dental gold lot",
        ],
        "category_ids": ["281", "162134", "3360", "262022", "10290"],
        "price_min": 50,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_GOLD,
    },
    "silver": {
        "keywords": [
            "sterling scrap", "sterling lot", "sterling flatware", "sterling grams",
            "scrap lot sterling", "scrap lot 925", "925 scrap lot", "silver scrap lot",
            "925 scrap", "925 grams", "sterling gorham", "sterling towle",
            "sterling bowl", "sterling tea", "800 silver", "800 grams",
            "830 silver", "900 silver", "coin silver", "mexican silver",
            "navajo sterling", "native sterling", "sterling turquoise",
        ],
        # 163271 = Sterling Silver Mixed Lots (under Antiques), 20081 = Fine Silver
        "category_ids": ["163271", "20081", "1", "281", "20096", "262022", "262025"],
        "price_min": 30,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_SILVER,
    },
    "platinum": {
        "keywords": [
            # === Platinum Jewelry ===
            "platinum ring", "platinum band", "platinum wedding",
            "platinum bracelet", "platinum necklace", "platinum chain",
            "platinum scrap", "platinum lot", "platinum grams",
            "PT950 ring", "PT950 band", "950 platinum",
            "PT900 ring", "PT900 band", "900 platinum",
            "platinum diamond", "platinum vintage", "platinum estate",
            "iridium platinum",  # Antique platinum often has iridium
        ],
        "category_ids": ["281", "164315", "110633", "262022"],  # Fine Jewelry, Wedding Rings
        "price_min": 100,
        "price_max": 15000,
        "poll_interval": POLL_INTERVAL_GOLD,  # Same as gold
    },
    "palladium": {
        "keywords": [
            # === Palladium Jewelry (rare but valuable) ===
            "palladium ring", "palladium band", "palladium wedding",
            "palladium scrap", "PD950", "950 palladium", "PD500",
            "palladium lot", "palladium grams",
        ],
        "category_ids": ["281", "164315", "262022"],
        "price_min": 100,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_GOLD,
    },
    "coin_scrap": {
        "keywords": [
            # === Junk Silver (90% silver coins at face value) ===
            "junk silver lot", "90% silver lot", "90% silver coins",
            "silver coin lot", "constitutional silver", "pre-1965 silver",
            "walking liberty lot", "mercury dime lot", "silver quarter lot",
            "silver half dollar lot", "barber silver lot", "peace dollar lot",
            "morgan dollar lot", "silver dollar lot cull",
            # === Scrap Gold Coins ===
            "gold coin scrap", "gold coin damaged", "gold coin lot cull",
            # === Bullion Scrap ===
            "silver bar scrap", "silver rounds lot", "generic silver lot",
        ],
        "category_ids": ["39482", "39489", "145410", "163116"],  # US Coins, Bullion
        "price_min": 50,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_SILVER,
    },
    "tcg": {
        "keywords": [
            # === POKEMON - High value/vintage ===
            "evolving skies booster box", "hidden fates etb", "celebrations upc",
            "151 booster box pokemon", "prismatic evolutions booster",
            "crown zenith etb", "shining fates etb",
            # === POKEMON - Current hot sets ===
            "surging sparks booster box", "stellar crown booster box",
            "shrouded fable booster", "temporal forces booster box",
            "paldea evolved booster box", "obsidian flames booster box",
            # === POKEMON - Japanese/Premium ===
            "japanese booster box pokemon", "ultra premium collection pokemon",
            "pokemon booster case", "pokemon sealed lot",
            # === MTG - High value ===
            "modern horizons 3 booster box", "modern horizons 2 booster box",
            "double masters booster box", "commander masters booster",
            "murders at karlov manor collector", "outlaws thunder junction collector",
            "mtg collector booster box", "mtg draft booster box",
            "mtg set booster box", "mtg sealed lot",
            # === YU-GI-OH - Sealed ===
            "yugioh booster box sealed", "yugioh case sealed",
            "yugioh collection sealed", "yugioh display box",
            # === Generic sealed ===
            "booster box sealed", "elite trainer box sealed", "etb sealed",
        ],
        "category_ids": ["183454", "183453", "183456", "2536", "261044", "261045"],  # TCG + Yu-Gi-Oh + Pokemon sealed
        "price_min": 40,
        "price_max": 15000,
        "poll_interval": POLL_INTERVAL_TCG,
    },
    "lego": {
        "keywords": [
            "lego sealed", "lego new", "lego retired", "lego ucs",
            "lego star wars", "lego technic", "lego creator",
        ],
        "category_ids": ["19006"],
        "price_min": 50,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_LEGO,
    },
    "watch": {
        "keywords": [
            # Chronographs (often mispriced)
            "heuer chronograph", "heuer autavia", "wakmann chronograph",
            "omega chronostop", "breitling chronograph", "zodiac sea-chron",
            "citizen bullhead", "vintage chronograph",
            # Vintage divers
            "zodiac sea wolf", "bulova devil diver", "bulova oceanographer",
            "bulova 666", "vintage diver watch",
            # Classic brands
            "omega vintage", "omega seamaster", "longines vintage",
            "hamilton vintage", "tudor vintage", "gruen vintage",
            # Gold watches (scrap floor)
            "14k gold watch", "18k gold watch", "solid gold watch",
            # Pocket watches
            "gold pocket watch", "14k pocket watch", "18k pocket watch",
            "elgin pocket watch", "waltham pocket watch", "hamilton pocket watch",
            "illinois pocket watch", "railroad pocket watch",
            # Niche brands (undervalued)
            "wakmann", "ulysse nardin", "girard perregaux", "universal geneve",
            "alsta", "enicar", "jules jurgensen",
        ],
        "category_ids": ["31387", "3937", "14324"],  # Wristwatches, Pocket Watches, Watches Parts & Accessories
        "price_min": 30,
        "price_max": 5000,
        "poll_interval": POLL_INTERVAL_SILVER,  # Same interval as silver
    },
    "textbook": {
        "keywords": [
            # Publisher-specific (high value)
            "pearson textbook", "mcgraw hill textbook", "cengage textbook",
            "wiley textbook", "pearson isbn", "mcgraw-hill isbn",
            # Subject-specific (high demand)
            "organic chemistry textbook", "calculus textbook",
            "anatomy physiology textbook", "biology textbook",
            "accounting textbook", "physics textbook",
            "nursing textbook", "medical textbook",
            "engineering textbook", "computer science textbook",
            # General textbook terms
            "college textbook isbn", "university textbook",
            "11th edition textbook", "12th edition textbook",
        ],
        "category_ids": ["267"],  # Books category
        "price_min": 10,
        "price_max": 150,  # Most textbook arbitrage buys are under $150
        "poll_interval": 120,  # Slower polling - textbooks don't need instant grab
    },
}

# Override keywords with uBuyFirst export if available
if _UBUYFIRST_KEYWORDS:
    if _UBUYFIRST_KEYWORDS.get('gold'):
        SEARCH_CONFIGS['gold']['keywords'] = _UBUYFIRST_KEYWORDS['gold']
        logger.info(f"[EBAY API] Using {len(_UBUYFIRST_KEYWORDS['gold'])} uBuyFirst gold keywords")
    if _UBUYFIRST_KEYWORDS.get('silver'):
        SEARCH_CONFIGS['silver']['keywords'] = _UBUYFIRST_KEYWORDS['silver']
        logger.info(f"[EBAY API] Using {len(_UBUYFIRST_KEYWORDS['silver'])} uBuyFirst silver keywords")
    if _UBUYFIRST_KEYWORDS.get('watch'):
        SEARCH_CONFIGS['watch']['keywords'] = _UBUYFIRST_KEYWORDS['watch']
        logger.info(f"[EBAY API] Using {len(_UBUYFIRST_KEYWORDS['watch'])} uBuyFirst watch keywords")

# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class EbayListing:
    """Normalized eBay listing data"""
    item_id: str
    title: str
    price: float
    currency: str
    thumbnail_url: str
    gallery_url: str
    view_url: str
    listing_type: str
    condition: str
    location: str
    seller_id: str
    seller_feedback: int
    start_time: datetime
    category_id: str
    category_name: str
    source: str = "ebay_direct"
    # Seller profile fields
    seller_score: int = 50
    seller_type: str = "unknown"
    seller_priority: str = "NORMAL"
    seller_patterns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        # Handle start_time serialization carefully
        start_time_str = None
        if self.start_time:
            try:
                if hasattr(self.start_time, 'isoformat'):
                    start_time_str = self.start_time.isoformat()
                else:
                    start_time_str = str(self.start_time)
            except:
                start_time_str = None

        return {
            "ItemId": self.item_id,
            "Title": self.title,
            "TotalPrice": f"${self.price:.2f}",
            "price": self.price,
            "GalleryURL": self.gallery_url,
            "PictureURL": self.thumbnail_url,
            "ViewUrl": self.view_url,
            "ListingType": self.listing_type,
            "Condition": self.condition,
            "Location": self.location,
            "SellerUserID": self.seller_id,
            "SellerFeedback": self.seller_feedback,
            "StartTime": start_time_str,
            "CategoryID": self.category_id,
            "CategoryName": self.category_name,
            "source": self.source,
            # Seller profile data
            "SellerScore": self.seller_score,
            "SellerType": self.seller_type,
            "SellerPriority": self.seller_priority,
            "SellerPatterns": self.seller_patterns,
        }


# ============================================================
# SELLER PROFILING INTEGRATION
# ============================================================

def enrich_listing_with_seller_profile(listing: EbayListing, category: str = "") -> EbayListing:
    """
    Enrich an EbayListing with seller profile data.
    This scores the seller and adds priority/type info.
    """
    if not SELLER_PROFILING_ENABLED:
        return listing

    try:
        # Get or calculate seller profile
        seller_analysis = analyze_new_seller(
            seller=listing.seller_id,
            title=listing.title,
            category=category
        )

        # Update listing with seller data
        listing.seller_score = seller_analysis.get('score', 50)
        listing.seller_type = seller_analysis.get('type', 'unknown')
        listing.seller_priority = seller_analysis.get('recommendation', 'NORMAL')
        listing.seller_patterns = seller_analysis.get('patterns', [])

        # Log high-value sellers
        if listing.seller_score >= 70:
            logger.info(f"[SELLER] HIGH VALUE: {listing.seller_id} (score:{listing.seller_score}, type:{listing.seller_type})")

    except Exception as e:
        logger.debug(f"[SELLER] Error enriching listing: {e}")

    return listing


def get_seller_score_quick(seller_id: str, title: str = "", category: str = "") -> int:
    """Quick seller score lookup - for filtering"""
    if not SELLER_PROFILING_ENABLED:
        return 50

    try:
        return score_seller_for_listing(seller_id, title, category)
    except Exception:
        return 50


# ============================================================
# API FUNCTIONS
# ============================================================

def update_api_stats(category: str, success: bool = True):
    """Track API usage for rate limit application"""
    global API_STATS

    # Reset daily counter if new day
    today = datetime.now().date().isoformat()
    last_reset = API_STATS.get("last_reset", "")
    # Handle both string and date object for comparison
    if isinstance(last_reset, date):
        last_reset = last_reset.isoformat()

    if last_reset != today:
        logger.info(f"[EBAY API] Daily reset - yesterday's calls: {API_STATS['calls_today']}")
        API_STATS["calls_today"] = 0
        API_STATS["calls_by_category"] = {}
        API_STATS["last_reset"] = today

    API_STATS["total_calls"] += 1
    API_STATS["calls_today"] += 1
    API_STATS["last_call"] = datetime.now()

    if category not in API_STATS["calls_by_category"]:
        API_STATS["calls_by_category"][category] = 0
    API_STATS["calls_by_category"][category] += 1

    if not success:
        API_STATS["errors"] += 1

    # Persist stats to file after each update
    _save_api_stats()


def get_api_stats() -> Dict:
    """Get current API usage statistics"""
    # Serialize dates properly
    last_call_str = None
    if API_STATS["last_call"]:
        try:
            last_call_str = API_STATS["last_call"].isoformat()
        except:
            last_call_str = str(API_STATS["last_call"])
    
    last_reset_str = None
    if API_STATS["last_reset"]:
        try:
            last_reset_str = API_STATS["last_reset"].isoformat()
        except:
            last_reset_str = str(API_STATS["last_reset"])
    
    return {
        "total_calls": API_STATS["total_calls"],
        "calls_today": API_STATS["calls_today"],
        "last_reset": last_reset_str,
        "calls_by_category": API_STATS["calls_by_category"],
        "errors": API_STATS["errors"],
        "last_call": last_call_str,
    }


# ============================================================
# WEB SCRAPING SEARCH
# ============================================================
# WARNING: Web scraping eBay violates their Terms of Service!
# Can result in account suspension or legal action.
# Use only the official API for legitimate access.

WEB_SCRAPING_ENABLED = False  # DISABLED - Violates eBay ToS

async def search_ebay_web(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    entries_per_page: int = 50,
) -> List[EbayListing]:
    """
    Search eBay by scraping the website directly - NO API indexing delay!
    Returns list of EbayListing objects.
    """
    import re
    from urllib.parse import quote_plus

    # Build search URL
    params = [
        f"_nkw={quote_plus(keywords)}",
        "_sop=10",  # Sort by newly listed
        "LH_BIN=1",  # Buy It Now only
        "LH_PrefLoc=1",  # US preferred
        f"_ipg={min(entries_per_page, 60)}",  # Items per page
    ]

    if price_min is not None:
        params.append(f"_udlo={int(price_min)}")
    if price_max is not None:
        params.append(f"_udhi={int(price_max)}")
    if category_ids and len(category_ids) > 0:
        params.append(f"_sacat={category_ids[0]}")

    url = "https://www.ebay.com/sch/i.html?" + "&".join(params)
    listings = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            })

            if response.status_code != 200:
                logger.warning(f"[WEB] HTTP {response.status_code} for '{keywords}'")
                return []

            html = response.text

            # Extract item IDs from the page
            # Pattern: /itm/ITEM_ID? or data attributes
            item_ids = set(re.findall(r'/itm/(\d{10,14})\?', html))

            # Also try to extract prices and titles
            # Pattern: s-item__price and s-item__title
            for item_id in list(item_ids)[:entries_per_page]:
                try:
                    # Extract title for this item (look for link with item ID)
                    title_match = re.search(
                        rf'href="[^"]*{item_id}[^"]*"[^>]*>([^<]+)</a>',
                        html
                    )
                    title = title_match.group(1).strip() if title_match else f"Item {item_id}"

                    # Extract price (look near the item link)
                    # Prices are formatted like $123.45
                    price = 0.0
                    price_section = html[max(0, html.find(item_id)-2000):html.find(item_id)+500]
                    price_match = re.search(r'\$[\d,]+\.?\d*', price_section)
                    if price_match:
                        price_str = price_match.group().replace('$', '').replace(',', '')
                        try:
                            price = float(price_str)
                        except:
                            pass

                    # Create listing object
                    listing = EbayListing(
                        item_id=item_id,
                        title=title[:200],
                        price=price,
                        currency="USD",
                        thumbnail_url="",
                        gallery_url="",
                        view_url=f"https://www.ebay.com/itm/{item_id}",
                        listing_type="FixedPrice",
                        condition="",
                        location="US",
                        seller_id="",  # Not available from scraping
                        seller_feedback=0,
                        start_time=datetime.now(),  # Use current time (we just found it!)
                        category_id=category_ids[0] if category_ids else "",
                        category_name="",
                        source="web_scrape",
                        seller_score=50,
                        seller_priority="NORMAL",
                    )

                    listings.append(listing)

                except Exception as e:
                    logger.debug(f"[WEB] Error parsing item {item_id}: {e}")
                    continue

            logger.info(f"[WEB] '{keywords}': {len(listings)} listings scraped")

    except httpx.TimeoutException:
        logger.warning(f"[WEB] Timeout scraping '{keywords}'")
    except Exception as e:
        logger.error(f"[WEB] Error scraping '{keywords}': {e}")

    return listings


# ============================================================
# RSS FEED SEARCH
# ============================================================

async def search_ebay_rss(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    entries_per_page: int = 50,
) -> List[EbayListing]:
    """
    Search eBay using RSS feed - MUCH faster than Browse API!
    RSS feeds update within seconds of listing going live.

    Returns list of EbayListing objects, or empty list on error.
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import quote_plus

    # Build RSS URL
    # Format: https://www.ebay.com/sch/i.html?_nkw=keyword&_sop=10&_rss=1&LH_BIN=1&_ipg=50
    params = {
        "_nkw": quote_plus(keywords),  # Search keyword
        "_sop": "10",  # Sort by newly listed
        "_rss": "1",   # Return RSS format
        "LH_BIN": "1", # Buy It Now only
        "LH_PrefLoc": "1",  # US only (prefer US)
        "_ipg": str(min(entries_per_page, 100)),  # Items per page (max 100 for RSS)
    }

    # Add price filters
    if price_min is not None:
        params["_udlo"] = str(int(price_min))
    if price_max is not None:
        params["_udhi"] = str(int(price_max))

    # Add category filter (only first category for RSS)
    if category_ids and len(category_ids) > 0:
        params["_sacat"] = category_ids[0]

    # Build URL
    url = RSS_BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    listings = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

            if response.status_code != 200:
                logger.warning(f"[RSS] HTTP {response.status_code} for '{keywords}'")
                return []

            # Parse RSS XML
            root = ET.fromstring(response.text)

            # Find all items in RSS feed
            # RSS format: <rss><channel><item>...</item></channel></rss>
            channel = root.find("channel")
            if channel is None:
                logger.warning(f"[RSS] No channel found in response for '{keywords}'")
                return []

            items = channel.findall("item")
            logger.debug(f"[RSS] Found {len(items)} items for '{keywords}'")

            for item in items:
                try:
                    # Extract item data from RSS
                    title_elem = item.find("title")
                    link_elem = item.find("link")

                    if title_elem is None or link_elem is None:
                        continue

                    title = title_elem.text or ""
                    link = link_elem.text or ""

                    # Extract item ID from link
                    # Format: https://www.ebay.com/itm/TITLE/123456789?...
                    item_id = ""
                    if "/itm/" in link:
                        # Try to get ID from URL path
                        parts = link.split("/itm/")
                        if len(parts) > 1:
                            id_part = parts[1].split("?")[0].split("/")[-1]
                            if id_part.isdigit():
                                item_id = id_part

                    if not item_id:
                        # Try guid element
                        guid_elem = item.find("guid")
                        if guid_elem is not None and guid_elem.text:
                            # GUID might be the item ID or URL
                            guid = guid_elem.text
                            if guid.isdigit():
                                item_id = guid
                            elif "/itm/" in guid:
                                parts = guid.split("/itm/")
                                if len(parts) > 1:
                                    id_part = parts[1].split("?")[0].split("/")[-1]
                                    if id_part.isdigit():
                                        item_id = id_part

                    if not item_id:
                        continue

                    # Extract price from description or title
                    # RSS description often contains price info
                    price = 0.0
                    desc_elem = item.find("description")
                    if desc_elem is not None and desc_elem.text:
                        desc = desc_elem.text
                        # Look for price patterns like $123.45 or US $123.45
                        import re
                        price_match = re.search(r'\$[\d,]+\.?\d*', desc)
                        if price_match:
                            price_str = price_match.group().replace('$', '').replace(',', '')
                            try:
                                price = float(price_str)
                            except:
                                pass

                    # Extract publication date (listing start time)
                    start_time = None
                    pubdate_elem = item.find("pubDate")
                    if pubdate_elem is not None and pubdate_elem.text:
                        try:
                            from email.utils import parsedate_to_datetime
                            start_time = parsedate_to_datetime(pubdate_elem.text)
                        except:
                            pass

                    # Extract image URL if available
                    image_url = ""
                    # Check for media:content or enclosure
                    for child in item:
                        if "content" in child.tag.lower() or child.tag == "enclosure":
                            image_url = child.get("url", "")
                            break

                    # Create listing object
                    listing = EbayListing(
                        item_id=item_id,
                        title=title,
                        price=price,
                        currency="USD",
                        thumbnail_url=image_url,
                        gallery_url=image_url,
                        view_url=link,
                        listing_type="FixedPrice",
                        condition="",
                        location="US",
                        seller_id="",  # Not available in RSS
                        seller_feedback=0,
                        start_time=start_time,
                        category_id="",
                        category_name="",
                        source="rss",
                        seller_score=50,  # Default score since we don't have seller info
                        seller_priority="NORMAL",
                    )

                    listings.append(listing)

                except Exception as e:
                    logger.debug(f"[RSS] Error parsing item: {e}")
                    continue

            logger.info(f"[RSS] '{keywords}': {len(listings)} listings found")

    except httpx.TimeoutException:
        logger.warning(f"[RSS] Timeout fetching '{keywords}'")
    except ET.ParseError as e:
        logger.warning(f"[RSS] XML parse error for '{keywords}': {e}")
    except Exception as e:
        logger.error(f"[RSS] Error searching '{keywords}': {e}")

    return listings


# Try Finding API first for potentially faster indexing
# NOTE: Finding API has stricter rate limits - hits 500 error immediately
USE_FINDING_API_FIRST = False  # DISABLED - Finding API rate limited heavily

async def search_ebay(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    sort_order: str = "StartTimeNewest",
    entries_per_page: int = 50,
    use_rss: bool = True,
    since_date: datetime = None,
    condition_filter: str = None,  # "USED" for pre-owned only, "NEW" for new only
) -> List[EbayListing]:
    """
    Search eBay - tries multiple methods in order of speed:
    1. Web scraping (FASTEST - no API indexing delay)
    2. RSS feed (if enabled)
    3. Finding API (if enabled)
    4. Browse API (fallback)

    since_date: If provided, only return items listed AFTER this timestamp (Browse API only)
    condition_filter: "USED" for pre-owned only, "NEW" for new only, None for all

    Returns list of EbayListing objects
    """
    # Try WEB SCRAPING first (FASTEST - bypasses API indexing delay!)
    if WEB_SCRAPING_ENABLED:
        web_results = await search_ebay_web(keywords, category_ids, price_min, price_max, entries_per_page)
        if web_results:
            return web_results
        logger.debug(f"[EBAY] Web scraping returned no results for '{keywords}', trying API")

    # Try RSS if enabled
    if use_rss and RSS_ENABLED:
        rss_results = await search_ebay_rss(keywords, category_ids, price_min, price_max, entries_per_page)
        if rss_results:
            return rss_results
        logger.debug(f"[EBAY] RSS returned no results for '{keywords}', trying API")

    if not EBAY_APP_ID:
        logger.error("[EBAY API] No EBAY_APP_ID configured!")
        return []

    # Try Finding API if enabled
    if USE_FINDING_API_FIRST:
        finding_results = await search_ebay_finding(keywords, category_ids, price_min, price_max, sort_order, entries_per_page)
        if finding_results:
            return finding_results
        logger.debug(f"[EBAY] Finding API returned no results for '{keywords}', trying Browse API")

    # Use Browse API as fallback
    if not browse_api_available():
        logger.error("[EBAY API] Browse API not available - check EBAY_CERT_ID")
        return []

    result = await search_ebay_browse(keywords, category_ids, price_min, price_max, sort_order, entries_per_page, since_date, condition_filter)
    if result is None:  # None means API error
        logger.warning("[EBAY API] Browse API returned error - skipping this search")
        return []
    return result


async def search_ebay_browse(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    sort_order: str = "StartTimeNewest",
    entries_per_page: int = 50,
    since_date: datetime = None,
    condition_filter: str = None,  # "USED" for pre-owned only, "NEW" for new only, None for all
) -> Optional[List[EbayListing]]:
    """
    Search eBay using Browse API (modern REST API)
    Returns None on API error (to trigger fallback), [] on no results

    since_date: If provided, only return items listed AFTER this timestamp (itemStartDate filter)
                This makes polling much more efficient by only fetching truly new items.
    condition_filter: "USED" for pre-owned only, "NEW" for new only, None for all conditions
    """
    # Get OAuth token
    token = await get_oauth_token()
    if not token:
        logger.error("[Browse API] Failed to get OAuth token")
        return None

    # Rate limit
    await rate_limit_wait()

    # Map sort order
    sort_map = {
        "StartTimeNewest": "newlyListed",
        "PricePlusShippingLowest": "price",
        "BestMatch": "bestMatch",
    }
    browse_sort = sort_map.get(sort_order, "newlyListed")

    # Build filter string
    filters = ["buyingOptions:{FIXED_PRICE}", "itemLocationCountry:US"]
    if price_min is not None:
        filters.append(f"price:[{price_min}..{price_max or ''}],priceCurrency:USD")
    elif price_max is not None:
        filters.append(f"price:[..{price_max}],priceCurrency:USD")

    # Add condition filter (USED = pre-owned, NEW = new only)
    if condition_filter:
        filters.append(f"conditions:{{{condition_filter}}}")
        logger.debug(f"[Browse API] Using condition filter: {condition_filter}")

    # Add itemStartDate filter for efficient polling (only fetch items newer than since_date)
    if since_date is not None:
        # Add 1 second to exclude the item we just processed (eBay filter is inclusive >=)
        from datetime import timedelta
        filter_date = since_date + timedelta(seconds=1)
        # Format: 2025-01-13T03:00:00Z (ISO 8601 UTC)
        since_str = filter_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        filters.append(f"itemStartDate:[{since_str}..]")
        logger.info(f"[Browse API] Using itemStartDate filter: since {since_str}")

    # Build request
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    params = {
        "q": keywords,
        "sort": browse_sort,
        "limit": str(min(entries_per_page, 200)),  # Browse API max is 200
        "filter": ",".join(filters),
    }

    # Add category filter to params (Browse API only allows 1 category at a time)
    if category_ids:
        params["category_ids"] = category_ids[0]  # Use first category only

    try:
        url = BROWSE_API_URL
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)

            update_api_stats(keywords[:20], success=(response.status_code == 200))

            if response.status_code == 200:
                data = response.json()
                items = data.get("itemSummaries", [])
                total = data.get("total", len(items))

                logger.info(f"[Browse API] Fetched {len(items)} of {total} for '{keywords[:30]}...'")

                listings = []
                for item in items:
                    try:
                        listing = parse_browse_item(item)
                        if listing:
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"[Browse API] Error parsing item: {e}")

                return listings

            elif response.status_code == 401:
                # Token expired, clear cache and retry once
                global _oauth_token, _oauth_expires
                with _oauth_lock:
                    _oauth_token = None
                    _oauth_expires = None
                logger.warning("[Browse API] Token expired, will retry with new token")
                return None

            else:
                logger.error(f"[Browse API] Error {response.status_code}: {response.text[:300]}")
                return None

    except Exception as e:
        logger.error(f"[Browse API] Request error: {e}")
        update_api_stats(keywords[:20], success=False)
        return None


def parse_browse_item(item: Dict) -> Optional[EbayListing]:
    """Parse a Browse API item response into EbayListing"""
    try:
        # Extract price
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        currency = price_info.get("currency", "USD")

        # Extract seller info
        seller_info = item.get("seller", {})
        seller_id = seller_info.get("username", "unknown")
        feedback = int(seller_info.get("feedbackScore", 0))

        # Extract images
        image = item.get("image", {})
        thumbnail_url = image.get("imageUrl", "")

        # Extract condition
        condition = item.get("condition", "Unknown")

        # Extract location
        location_info = item.get("itemLocation", {})
        location = location_info.get("city", "") or location_info.get("country", "Unknown")

        # Extract category
        categories = item.get("categories", [{}])
        category_id = categories[0].get("categoryId", "") if categories else ""
        category_name = categories[0].get("categoryName", "") if categories else ""

        # Extract listing creation date (try multiple fields)
        start_time = None
        date_str = item.get("itemCreationDate") or item.get("listingMarketplaceId")
        if not date_str:
            # Try to get from itemEndDate and estimate (listings usually 30 days)
            end_date_str = item.get("itemEndDate")
            if end_date_str:
                try:
                    from datetime import timedelta
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    start_time = end_date - timedelta(days=30)  # Estimate
                except:
                    pass
        else:
            try:
                start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                pass

        # Build listing
        # Browse API returns itemId as "v1|376847105664|0" - extract middle part (actual item ID)
        raw_item_id = item.get("itemId", "")
        parts = raw_item_id.split("|")
        item_id = parts[1] if len(parts) >= 2 else raw_item_id  # Get middle part

        listing = EbayListing(
            item_id=item_id,
            title=item.get("title", ""),
            price=price,
            currency=currency,
            thumbnail_url=thumbnail_url,
            gallery_url=thumbnail_url,
            view_url=item.get("itemWebUrl", ""),
            listing_type="FixedPrice",
            condition=condition,
            location=location,
            seller_id=seller_id,
            seller_feedback=feedback,
            start_time=start_time,
            category_id=category_id,
            category_name=category_name,
            source="browse_api",
        )

        return listing

    except Exception as e:
        logger.debug(f"[Browse API] Parse error: {e}")
        return None




async def get_item_details(item_id: str) -> Optional[Dict]:
    """
    Fetch full item details from eBay Browse API including:
    - Full description
    - All image URLs (for scale photo analysis)
    - Item specifics (weight, metal, etc.)
    
    Returns dict with 'description', 'images', 'specifics' or None if failed.
    """
    if not item_id:
        return None
    
    # Clean item_id (remove any 'v1|' prefix if present)
    clean_id = item_id.split('|')[-1] if '|' in item_id else item_id
    
    # Get OAuth token
    token = await get_oauth_token()
    if not token:
        logger.debug("[EBAY DETAILS] No OAuth token available")
        return None
    
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    
    # Use getItem endpoint - returns full details
    url = f"https://api.ebay.com/buy/browse/v1/item/v1|{clean_id}|0"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                result = {
                    'description': '',
                    'images': [],
                    'specifics': {},
                }
                
                # Get description
                description = data.get('description', '')
                short_desc = data.get('shortDescription', '')
                result['description'] = f"{short_desc} {description}".strip()
                
                # Get ALL image URLs
                # Primary image
                primary_image = data.get('image', {})
                if primary_image.get('imageUrl'):
                    result['images'].append(primary_image['imageUrl'])
                
                # Additional images
                additional_images = data.get('additionalImages', [])
                for img in additional_images:
                    if img.get('imageUrl'):
                        result['images'].append(img['imageUrl'])
                
                # Get item specifics (weight, metal type, etc.)
                local_aspects = data.get('localizedAspects', [])
                for aspect in local_aspects:
                    name = aspect.get('name', '')
                    value = aspect.get('value', '')
                    if name and value:
                        result['specifics'][name] = value
                
                if result['images']:
                    logger.info(f"[EBAY DETAILS] Got {len(result['images'])} images for item {clean_id}")
                if result['description']:
                    logger.info(f"[EBAY DETAILS] Got description: {len(result['description'])} chars")
                
                return result
                    
            elif response.status_code == 404:
                logger.debug(f"[EBAY DETAILS] Item {clean_id} not found")
                return None
            else:
                logger.debug(f"[EBAY DETAILS] Error {response.status_code} for item {clean_id}")
                return None
                
    except Exception as e:
        logger.debug(f"[EBAY DETAILS] Error fetching details: {e}")
        return None


# Backwards compatible wrapper
async def get_item_description(item_id: str) -> Optional[str]:
    """Backwards compatible - returns just description"""
    details = await get_item_details(item_id)
    return details.get('description') if details else None


async def search_ebay_finding(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    sort_order: str = "StartTimeNewest",
    entries_per_page: int = 50,
) -> List[EbayListing]:
    """
    Search eBay using Finding API (legacy fallback)

    Returns list of EbayListing objects
    """
    # Rate limit - wait if needed
    await rate_limit_wait()

    # Build request parameters
    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "keywords": keywords,
        "sortOrder": sort_order,
        "paginationInput.entriesPerPage": str(entries_per_page),
        # Buy It Now only
        "itemFilter(0).name": "ListingType",
        "itemFilter(0).value": "FixedPrice",
        # US only
        "itemFilter(1).name": "LocatedIn",
        "itemFilter(1).value": "US",
    }

    filter_idx = 2

    # Add category filter
    if category_ids:
        params["categoryId"] = ",".join(category_ids[:3])  # API allows max 3

    # Add price filters
    if price_min is not None:
        params[f"itemFilter({filter_idx}).name"] = "MinPrice"
        params[f"itemFilter({filter_idx}).value"] = str(price_min)
        filter_idx += 1

    if price_max is not None:
        params[f"itemFilter({filter_idx}).name"] = "MaxPrice"
        params[f"itemFilter({filter_idx}).value"] = str(price_max)
        filter_idx += 1

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(FINDING_API_URL, params=params)

            update_api_stats(keywords[:20], success=(response.status_code == 200))

            if response.status_code != 200:
                logger.error(f"[Finding API] Error {response.status_code}: {response.text[:200]}")
                return []

            data = response.json()

            # Parse response
            search_result = data.get("findItemsAdvancedResponse", [{}])[0]
            ack = search_result.get("ack", ["Failure"])[0]

            if ack != "Success":
                error_msg = search_result.get("errorMessage", [{}])[0].get("error", [{}])[0].get("message", ["Unknown"])[0]
                logger.error(f"[Finding API] Search failed: {error_msg}")
                return []

            # Extract items
            search_items = search_result.get("searchResult", [{}])[0]
            count = int(search_items.get("@count", 0))
            items = search_items.get("item", [])

            logger.info(f"[Finding API] Found {count} items for '{keywords[:30]}...'")

            listings = []
            for item in items:
                try:
                    listing = parse_finding_item(item)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"[Finding API] Error parsing item: {e}")

            return listings

    except Exception as e:
        logger.error(f"[Finding API] Request error: {e}")
        update_api_stats(keywords[:20], success=False)
        return []


def parse_finding_item(item: Dict) -> Optional[EbayListing]:
    """Parse a Finding API item response into EbayListing"""
    try:
        # Extract price
        selling_status = item.get("sellingStatus", [{}])[0]
        current_price = selling_status.get("currentPrice", [{}])[0]
        price = float(current_price.get("__value__", 0))
        currency = current_price.get("@currencyId", "USD")
        
        # Extract seller info
        seller_info = item.get("sellerInfo", [{}])[0]
        seller_id = seller_info.get("sellerUserName", ["unknown"])[0]
        feedback = int(seller_info.get("feedbackScore", [0])[0])
        
        # Extract listing info
        listing_info = item.get("listingInfo", [{}])[0]
        listing_type = listing_info.get("listingType", ["FixedPrice"])[0]
        start_time_str = listing_info.get("startTime", [None])[0]
        
        # Parse start time
        start_time = None
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            except:
                pass
        
        # Extract condition
        condition = item.get("condition", [{}])[0].get("conditionDisplayName", ["Unknown"])[0]
        
        # Extract category
        primary_category = item.get("primaryCategory", [{}])[0]
        category_id = primary_category.get("categoryId", [""])[0]
        category_name = primary_category.get("categoryName", [""])[0]
        
        # Extract location
        location = item.get("location", ["Unknown"])[0]
        
        # Build listing
        listing = EbayListing(
            item_id=item.get("itemId", [""])[0],
            title=item.get("title", [""])[0],
            price=price,
            currency=currency,
            thumbnail_url=item.get("galleryURL", [""])[0],
            gallery_url=item.get("galleryURL", [""])[0],
            view_url=item.get("viewItemURL", [""])[0],
            listing_type=listing_type,
            condition=condition,
            location=location,
            seller_id=seller_id,
            seller_feedback=feedback,
            start_time=start_time,
            category_id=category_id,
            category_name=category_name,
        )
        
        return listing
        
    except Exception as e:
        logger.debug(f"[EBAY API] Parse error: {e}")
        return None


# ============================================================
# POLLING FUNCTIONS
# ============================================================

async def _safe_callback(callback, listing):
    """Wrapper to safely run callback without crashing the poller"""
    try:
        await callback(listing)
    except Exception as e:
        logger.error(f"[EBAY API] Callback error: {e}")

# ============================================================

# Lock to prevent race conditions in is_new_listing
_SEEN_LISTINGS_LOCK = asyncio.Lock()

def is_new_listing(item_id: str) -> bool:
    """
    Check if we've seen this listing before (SYNC version for backwards compat).
    WARNING: This has a race condition in async code - use is_new_listing_async instead.
    """
    global SEEN_LISTINGS

    # Clean old entries
    now = datetime.now()
    expired = [k for k, v in SEEN_LISTINGS.items()
               if (now - v).total_seconds() > SEEN_LISTINGS_MAX_AGE]
    for k in expired:
        del SEEN_LISTINGS[k]

    # Check if new
    if item_id in SEEN_LISTINGS:
        return False

    # Mark as seen
    SEEN_LISTINGS[item_id] = now
    return True


async def is_new_listing_async(item_id: str) -> bool:
    """
    Check if we've seen this listing before (ASYNC version with lock).
    Uses a lock to prevent race conditions when multiple tasks check the same item.
    """
    global SEEN_LISTINGS

    async with _SEEN_LISTINGS_LOCK:
        # Clean old entries (do this inside lock to avoid mutation during iteration)
        now = datetime.now()
        expired = [k for k, v in SEEN_LISTINGS.items()
                   if (now - v).total_seconds() > SEEN_LISTINGS_MAX_AGE]
        for k in expired:
            del SEEN_LISTINGS[k]

        # Check if new
        if item_id in SEEN_LISTINGS:
            return False

        # Mark as seen IMMEDIATELY (atomic with check)
        SEEN_LISTINGS[item_id] = now
        return True


async def get_new_listings(category: str, enrich_sellers: bool = True, immediate_callback=None) -> List[EbayListing]:
    """
    Get new listings for a category
    Filters out previously seen listings
    Optionally enriches with seller profile data

    immediate_callback: if provided, called immediately for each new listing as found
                       (for real-time analysis without waiting for all keywords)
    """
    if category not in SEARCH_CONFIGS:
        logger.error(f"[EBAY API] Unknown category: {category}")
        return []

    config = SEARCH_CONFIGS[category]
    all_listings = []

    # PRIORITY_KEYWORDS run EVERY cycle first, then rotate through BATCHED_KEYWORDS
    keywords_to_search = []

    # Always add priority keywords first (these are the money-makers)
    if category in PRIORITY_KEYWORDS:
        keywords_to_search.extend(PRIORITY_KEYWORDS[category])
        logger.info(f"[EBAY API] {category}: {len(PRIORITY_KEYWORDS[category])} priority keywords FIRST")

    # Then add batched keywords
    if category in BATCHED_KEYWORDS:
        keywords_to_search.extend(BATCHED_KEYWORDS[category])
        logger.info(f"[EBAY API] {category}: using {len(keywords_to_search)} total keyword groups")
    else:
        # Fallback to rotation for categories without batched keywords
        all_keywords = config["keywords"]
        total_keywords = len(all_keywords)

        if category not in KEYWORD_ROTATION_INDEX:
            KEYWORD_ROTATION_INDEX[category] = 0

        start_idx = KEYWORD_ROTATION_INDEX[category]

        keywords_to_search = []
        for i in range(KEYWORDS_PER_POLL):
            idx = (start_idx + i) % total_keywords
            keywords_to_search.append(all_keywords[idx])

        KEYWORD_ROTATION_INDEX[category] = (start_idx + KEYWORDS_PER_POLL) % total_keywords
        logger.info(f"[EBAY API] {category}: searching {len(keywords_to_search)} keywords (rotation)")

    # Search each keyword in the subset
    # For priority keywords, search ALL categories to avoid missing items
    is_priority_keyword = category in PRIORITY_KEYWORDS

    for keyword in keywords_to_search:
        # Priority keywords: NO category filter (catches items in any category)
        # Regular keywords: Use category filter from config
        search_categories = None if (is_priority_keyword and keyword in PRIORITY_KEYWORDS.get(category, [])) else config["category_ids"]

        # Get the newest timestamp we've seen for this keyword (efficient polling)
        since_date = KEYWORD_TIMESTAMPS.get(keyword)

        # Gold/Silver: Only search pre-owned items (new items are retail priced, no arbitrage)
        condition = "USED" if category in ("gold", "silver") else None

        listings = await search_ebay(
            keywords=keyword,
            category_ids=search_categories,
            price_min=config["price_min"],
            price_max=config["price_max"],
            entries_per_page=50,  # Get more per call since we make fewer calls
            since_date=since_date,  # Only fetch items newer than this timestamp
            condition_filter=condition,  # Pre-owned only for gold/silver
        )

        # Log efficiency stats
        if since_date:
            logger.debug(f"[EFFICIENT] {keyword}: {len(listings)} new items (since {since_date.strftime('%H:%M:%S')})")

        # Filter to new listings only
        for listing in listings:
            # Update keyword timestamp for efficient polling (track ALL items)
            if listing.start_time:
                current_ts = KEYWORD_TIMESTAMPS.get(keyword)
                if current_ts is None or listing.start_time > current_ts:
                    KEYWORD_TIMESTAMPS[keyword] = listing.start_time
            if await is_new_listing_async(listing.item_id):
                # FRESHNESS CHECK - only analyze listings from last 5 minutes
                if listing.start_time:
                    try:
                        from datetime import timezone
                        now = datetime.now(timezone.utc) if listing.start_time.tzinfo else datetime.now()
                        age_minutes = (now - listing.start_time).total_seconds() / 60
                        if age_minutes > 5:
                            logger.debug(f"[EBAY API] Skipping old listing ({age_minutes:.1f} min old): {listing.title[:40]}")
                            continue
                    except Exception as e:
                        logger.debug(f"[EBAY API] Could not check freshness: {e}")

                # Check if seller is blocked
                if BLOCKED_SELLERS_ENABLED:
                    seller_key = listing.seller_id.lower().strip()
                    if seller_key in BLOCKED_SELLERS:
                        logger.debug(f"[EBAY API] Skipping blocked seller: {listing.seller_id}")
                        continue

                # Check feedback rules (same as uBuyFirst filters)
                feedback_score = listing.seller_feedback
                if feedback_score < 1:
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: 0 feedback")
                    continue
                if feedback_score < UBF_FEEDBACK_RULES.get('min_feedback_score', 3):
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: feedback {feedback_score} < min")
                    continue
                if feedback_score > UBF_FEEDBACK_RULES.get('max_feedback_score', 30000):
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: feedback {feedback_score} > max")
                    continue

                # Check location filters (skip Japan, China, etc.)
                location_lower = listing.location.lower() if listing.location else ''
                skip_location = False
                for loc in UBF_LOCATION_FILTERS:
                    if loc in location_lower:
                        logger.debug(f"[FILTER] Skip location '{loc}': {listing.title[:40]}")
                        skip_location = True
                        break
                if skip_location:
                    continue

                # Check for instant pass keywords (gold plated, silver plated, etc.)
                title_lower = listing.title.lower()
                skip_instant = False
                for kw in INSTANT_PASS_KEYWORDS:
                    if kw in title_lower:
                        logger.debug(f"[EBAY API] Skipping instant-pass keyword '{kw}': {listing.title[:40]}")
                        skip_instant = True
                        break
                # Also check UBF title filters (trading cards, coins, etc.)
                if not skip_instant:
                    for kw in UBF_TITLE_FILTERS:
                        if kw in title_lower:
                            logger.debug(f"[EBAY API] Skipping UBF filter '{kw}': {listing.title[:40]}")
                            skip_instant = True
                            break
                if skip_instant:
                    continue

                # Enrich with seller profile data
                if enrich_sellers and SELLER_PROFILING_ENABLED:
                    listing = enrich_listing_with_seller_profile(listing, category)

                all_listings.append(listing)

                # Log with seller priority if available
                priority_tag = f"[{listing.seller_priority}]" if listing.seller_score >= 60 else ""
                logger.info(f"[EBAY API] NEW{priority_tag}: ${listing.price:.0f} - {listing.title[:50]}...")

                # Fire immediate callback if provided (real-time mode)
                if immediate_callback:
                    try:
                        asyncio.create_task(_safe_callback(immediate_callback, listing))
                    except Exception as e:
                        logger.error(f"[EBAY API] Immediate callback error: {e}")

        # Minimal delay between searches - rate_limit_wait() handles throttling
        await asyncio.sleep(0.5)

    # Sort by seller score (highest first) to prioritize high-value sellers
    if enrich_sellers and SELLER_PROFILING_ENABLED:
        all_listings.sort(key=lambda x: x.seller_score, reverse=True)

    return all_listings


async def poll_category(category: str, callback=None):
    """
    Continuously poll a category for new listings

    callback: async function(listing: EbayListing) called for each new listing
              NOW fires immediately as listings are found (real-time mode)
    """
    if category not in SEARCH_CONFIGS:
        logger.error(f"[EBAY API] Unknown category: {category}")
        return

    config = SEARCH_CONFIGS[category]
    interval = config["poll_interval"]

    logger.info(f"[EBAY API] Starting poll for {category} (every {interval}s, realtime={callback is not None})")

    while True:
        try:
            # Pass callback as immediate_callback for real-time processing
            # Callback fires immediately as each listing is found, not after all keywords searched
            new_listings = await get_new_listings(category, immediate_callback=callback)

            # Debug logging for race test
            logger.info(f"[EBAY API] Poll complete: {len(new_listings)} new items")

            logger.debug(f"[EBAY API] {category}: {len(new_listings)} new, {API_STATS['calls_today']} calls today")

        except Exception as e:
            logger.error(f"[EBAY API] Poll error for {category}: {e}")

        await asyncio.sleep(interval)


# ============================================================
# STAGGERED ROUND-ROBIN POLLING
# ============================================================
# Single polling loop that cycles through all keywords one at a time
# More efficient than independent polling - consistent API usage rate

def build_staggered_keyword_list() -> List[Dict]:
    """
    Build a unified list of all keywords to poll in round-robin order.
    Returns list of dicts with keyword, category, and config info.
    """
    keywords = []

    # Add priority keywords from all enabled categories
    for category, kw_list in PRIORITY_KEYWORDS.items():
        config = SEARCH_CONFIGS.get(category, {})
        # Use specific category IDs for faster indexing (not searching all of eBay!)
        cat_ids = PRIORITY_CATEGORY_IDS.get(category, config.get("category_ids"))
        for kw in kw_list:
            keywords.append({
                "keyword": kw,
                "category": category,
                "price_min": config.get("price_min", 50),
                "price_max": config.get("price_max", 10000),
                "category_ids": cat_ids,  # Specific categories for faster results
            })

    return keywords


async def poll_single_keyword(kw_info: Dict, callback=None) -> List[EbayListing]:
    """
    Poll a single keyword and process new listings.
    Returns list of new listings found.

    Uses itemStartDate filter for efficient polling - only fetches items newer than last seen.
    """
    keyword = kw_info["keyword"]
    category = kw_info["category"]

    new_listings = []

    # DISABLED: since_date filter was too aggressive - API indexing delay means
    # items don't appear immediately, so filtering by timestamp misses items
    # that are posted but take 30-60s to index.
    # Instead, rely on local SEEN_ITEM_IDS dedup + freshness check (5 min window)
    since_date = None  # DISABLED - fetch all, filter locally
    is_initial_baseline = not KEYWORD_TIMESTAMPS.get(keyword)  # True on first poll

    # Gold/Silver: Only search pre-owned items (new items are retail priced, no arbitrage)
    condition = "USED" if category in ("gold", "silver") else None

    try:
        listings = await search_ebay(
            keywords=keyword,
            category_ids=kw_info.get("category_ids"),
            price_min=kw_info.get("price_min", 50),
            price_max=kw_info.get("price_max", 10000),
            entries_per_page=50,
            since_date=None,  # Fetch all recent items, filter locally
            condition_filter=condition,  # Pre-owned only for gold/silver
        )

        # Log stats
        if is_initial_baseline:
            logger.debug(f"[POLL] {keyword}: {len(listings)} items (baseline, callback disabled)")
        else:
            logger.debug(f"[POLL] {keyword}: {len(listings)} items fetched, filtering for new")

        for listing in listings:
            # Update keyword timestamp for efficient polling (track ALL items, even filtered)
            if listing.start_time:
                current_ts = KEYWORD_TIMESTAMPS.get(keyword)
                if current_ts is None or listing.start_time > current_ts:
                    KEYWORD_TIMESTAMPS[keyword] = listing.start_time

            if await is_new_listing_async(listing.item_id):
                # Freshness check - only items from last 5 minutes
                if listing.start_time:
                    try:
                        from datetime import timezone
                        now = datetime.now(timezone.utc) if listing.start_time.tzinfo else datetime.now()
                        age_minutes = (now - listing.start_time).total_seconds() / 60
                        if age_minutes > 5:
                            continue
                    except:
                        pass

                # Check blocked sellers
                if BLOCKED_SELLERS_ENABLED:
                    seller_key = listing.seller_id.lower().strip()
                    if seller_key in BLOCKED_SELLERS:
                        continue

                # Check feedback rules (from uBuyFirst FiltersExport)
                feedback_score = listing.seller_feedback
                # Skip 0 feedback sellers (rule: remove 0 feedbacks)
                if feedback_score < 1:
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: 0 feedback")
                    continue
                # Skip low feedback sellers (rule: Remove less than 3 feedback)
                if feedback_score < UBF_FEEDBACK_RULES.get('min_feedback_score', 3):
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: feedback {feedback_score} < min")
                    continue
                # Skip high volume sellers (rule: Remove over 30K feedback)
                if feedback_score > UBF_FEEDBACK_RULES.get('max_feedback_score', 30000):
                    logger.debug(f"[FILTER] Skip {listing.seller_id}: feedback {feedback_score} > max")
                    continue

                # Check instant pass keywords AND uBuyFirst title filters
                title_lower = listing.title.lower()
                skip = False
                # Check basic instant pass keywords
                for kw in INSTANT_PASS_KEYWORDS:
                    if kw in title_lower:
                        skip = True
                        break
                # Check uBuyFirst title filters (trading cards, coins, etc.)
                if not skip:
                    for kw in UBF_TITLE_FILTERS:
                        if kw in title_lower:
                            skip = True
                            break
                if skip:
                    continue

                # Enrich with seller profile
                if SELLER_PROFILING_ENABLED:
                    listing = enrich_listing_with_seller_profile(listing, category)

                new_listings.append(listing)

                priority_tag = f"[{listing.seller_priority}]" if listing.seller_score >= 60 else ""
                logger.info(f"[EBAY API] NEW{priority_tag}: ${listing.price:.0f} - {listing.title[:50]}...")

                # Send to analysis callback - Discord notification handled there based on recommendation
                if callback and not is_initial_baseline:
                    asyncio.create_task(_safe_callback(callback, listing))

    except Exception as e:
        logger.error(f"[EBAY API] Error polling '{keyword}': {e}")

    return new_listings


async def poll_staggered(callback=None):
    """
    Staggered round-robin polling loop.
    Cycles through all priority keywords one at a time with consistent intervals.

    This is MORE EFFICIENT than independent polling because:
    1. Consistent API call rate (no bursts)
    2. Even distribution of calls over time
    3. Better rate limit handling
    4. Same per-keyword refresh rate (26s each with 3 keywords at 8.6s interval)
    """
    keywords = build_staggered_keyword_list()

    if not keywords:
        logger.error("[EBAY API] No keywords configured for staggered polling!")
        return

    logger.info(f"[STAGGERED] Starting round-robin polling: {len(keywords)} keywords, {STAGGERED_POLL_INTERVAL}s interval")
    logger.info(f"[STAGGERED] Each keyword refreshes every {STAGGERED_POLL_INTERVAL * len(keywords):.1f}s")
    logger.info(f"[STAGGERED] Keywords: {[k['keyword'] for k in keywords]}")

#     # Send startup notification to Discord
#     startup_msg = f"**eBay API Polling Started**\n" \
#                   f"• Keywords: {[k['keyword'] for k in keywords]}\n" \
#                   f"• Poll Interval: {STAGGERED_POLL_INTERVAL}s\n" \
#                   f"• Refresh Rate: {STAGGERED_POLL_INTERVAL * len(keywords):.1f}s per keyword\n" \
#                   f"• Discord notifications: **ENABLED** for all new listings"
#     await send_discord_status(startup_msg, 0x00ff00)

    keyword_index = 0
    poll_count = 0
    total_found = 0

    while True:
        kw_info = keywords[keyword_index]

        # Poll this keyword
        new_items = await poll_single_keyword(kw_info, callback)
        poll_count += 1
        total_found += len(new_items)

        logger.debug(f"[STAGGERED] {kw_info['keyword']}: {len(new_items)} new items | next in {STAGGERED_POLL_INTERVAL}s")

#         # Send periodic status every 20 polls (about every 3 minutes)
#         if poll_count % 20 == 0:
#             status_msg = f"**Polling Status** (poll #{poll_count})\n" \
#                          f"• Total new items found: {total_found}\n" \
#                          f"• API calls today: {API_STATS.get('calls_today', 0)}\n" \
#                          f"• Last keyword: {kw_info['keyword']}"
#             await send_discord_status(status_msg, 0x0099ff)

        # Move to next keyword
        keyword_index = (keyword_index + 1) % len(keywords)

        # Wait for next poll
        await asyncio.sleep(STAGGERED_POLL_INTERVAL)


# ============================================================
# RSS FAST POLLING (NO RATE LIMITS!)
# ============================================================
# RSS feeds don't count against API limits, so we can poll much faster

_RSS_TASK: Optional[asyncio.Task] = None

async def poll_rss_fast(callback=None):
    """
    Fast RSS-only polling loop.
    Since RSS doesn't have rate limits, we can poll every 5 seconds!
    This should get items within 10-15 seconds of listing.
    """
    keywords = build_staggered_keyword_list()

    if not keywords:
        logger.error("[RSS] No keywords configured for polling!")
        return

    logger.info(f"[RSS FAST] Starting fast RSS polling: {len(keywords)} keywords, {RSS_POLL_INTERVAL}s interval")
    logger.info(f"[RSS FAST] Each keyword refreshes every {RSS_POLL_INTERVAL * len(keywords):.1f}s")
    logger.info(f"[RSS FAST] Keywords: {[k['keyword'] for k in keywords]}")

    keyword_index = 0

    while True:
        kw_info = keywords[keyword_index]
        keyword = kw_info["keyword"]

        try:
            # Use RSS only (no API fallback for speed)
            listings = await search_ebay_rss(
                keywords=keyword,
                category_ids=kw_info.get("category_ids"),
                price_min=kw_info.get("price_min", 50),
                price_max=kw_info.get("price_max", 10000),
                entries_per_page=50,
            )

            new_count = 0
            for listing in listings:
                if await is_new_listing_async(listing.item_id):
                    # Freshness check - only items from last 5 minutes
                    if listing.start_time:
                        try:
                            from datetime import timezone
                            now = datetime.now(timezone.utc) if listing.start_time.tzinfo else datetime.now()
                            age_minutes = (now - listing.start_time).total_seconds() / 60
                            if age_minutes > 5:
                                continue
                        except:
                            pass

                    # Check instant pass keywords
                    title_lower = listing.title.lower()
                    skip = False
                    try:
                        for kw in INSTANT_PASS_KEYWORDS:
                            if kw in title_lower:
                                skip = True
                                break
                    except:
                        pass
                    if skip:
                        continue

                    new_count += 1
                    logger.info(f"[RSS] NEW: ${listing.price:.0f} - {listing.title[:50]}...")

                    # Fire callback immediately
                    if callback:
                        asyncio.create_task(_safe_callback(callback, listing))

            if new_count > 0:
                logger.info(f"[RSS FAST] {keyword}: {new_count} new items")

        except Exception as e:
            logger.error(f"[RSS FAST] Error polling '{keyword}': {e}")

        # Move to next keyword
        keyword_index = (keyword_index + 1) % len(keywords)

        # Wait for next poll (short interval since no rate limits)
        await asyncio.sleep(RSS_POLL_INTERVAL)


# ============================================================
# BACKGROUND POLLING
# ============================================================

POLL_TASKS: Dict[str, asyncio.Task] = {}
_STAGGERED_TASK: Optional[asyncio.Task] = None

async def start_polling(categories: List[str] = None, callback=None, use_staggered: bool = True, use_rss_fast: bool = True):
    """
    Start background polling for specified categories

    categories: List of category names, or None for all
    callback: async function to call for each new listing
    use_staggered: If True (default), use efficient round-robin polling
    use_rss_fast: If True (default), use fast RSS polling (no rate limits!)
    """
    global POLL_TASKS, _STAGGERED_TASK, _RSS_TASK

    # Prefer RSS fast polling (much faster, no rate limits)
    if use_rss_fast and RSS_ENABLED:
        if _RSS_TASK is not None:
            logger.warning("[RSS] Fast RSS polling already running")
            return

        _RSS_TASK = asyncio.create_task(poll_rss_fast(callback))
        logger.info("[RSS] Started FAST RSS polling (no rate limits!)")
        return

    if use_staggered:
        # Use new staggered polling (recommended)
        if _STAGGERED_TASK is not None:
            logger.warning("[EBAY API] Staggered polling already running")
            return

        _STAGGERED_TASK = asyncio.create_task(poll_staggered(callback))
        logger.info("[EBAY API] Started staggered round-robin polling")
        return

    # Legacy: independent polling per category
    if categories is None:
        categories = list(SEARCH_CONFIGS.keys())

    for category in categories:
        if category in POLL_TASKS:
            logger.warning(f"[EBAY API] Already polling {category}")
            continue

        task = asyncio.create_task(poll_category(category, callback))
        POLL_TASKS[category] = task
        logger.info(f"[EBAY API] Started polling: {category}")


async def stop_polling(categories: List[str] = None):
    """Stop polling for specified categories"""
    global POLL_TASKS, _STAGGERED_TASK, _RSS_TASK

    # Stop RSS fast polling if running
    if _RSS_TASK is not None:
        _RSS_TASK.cancel()
        _RSS_TASK = None
        logger.info("[RSS] Stopped fast RSS polling")

    # Stop staggered polling if running
    if _STAGGERED_TASK is not None:
        _STAGGERED_TASK.cancel()
        _STAGGERED_TASK = None
        logger.info("[EBAY API] Stopped staggered polling")

    # Stop legacy per-category polling
    if categories is None:
        categories = list(POLL_TASKS.keys())

    for category in categories:
        if category in POLL_TASKS:
            POLL_TASKS[category].cancel()
            del POLL_TASKS[category]
            logger.info(f"[EBAY API] Stopped polling: {category}")


# ============================================================
# TEXTBOOK ARBITRAGE POLLING
# ============================================================

TEXTBOOK_POLL_INTERVAL = 120  # 2 minutes between textbook searches
TEXTBOOK_SEEN_ITEMS: Dict[str, datetime] = {}  # Track seen items
_TEXTBOOK_TASK: Optional[asyncio.Task] = None
KEEPA_TRACKER_URL = "http://127.0.0.1:8001"  # KeepaTracker service


async def analyze_textbook_listing(listing: EbayListing) -> Optional[Dict]:
    """
    Send a textbook listing to KeepaTracker for analysis.
    Returns deal info if profitable, None otherwise.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{KEEPA_TRACKER_URL}/textbook/analyze",
                json={
                    "title": listing.title,
                    "price": listing.price,
                    "url": listing.view_url,
                    "description": "",  # Could fetch if needed
                    "condition": listing.condition or "Used",
                },
                timeout=15.0,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "profitable":
                    return data.get("deal")
            return None

    except Exception as e:
        logger.error(f"[TEXTBOOK] Error calling KeepaTracker: {e}")
        return None


async def textbook_polling_loop(callback=None):
    """
    Dedicated textbook polling loop.
    Runs separately from main gold/silver polling at a slower rate.
    """
    global TEXTBOOK_SEEN_ITEMS

    config = SEARCH_CONFIGS.get("textbook", {})
    keywords = config.get("keywords", [])
    category_ids = config.get("category_ids", ["267"])
    price_min = config.get("price_min", 10)
    price_max = config.get("price_max", 150)

    logger.info(f"[TEXTBOOK] Starting textbook polling: {len(keywords)} keywords, {TEXTBOOK_POLL_INTERVAL}s interval")

    keyword_index = 0

    while True:
        keyword = keywords[keyword_index]

        try:
            listings = await search_ebay(
                keywords=keyword,
                category_ids=category_ids,
                price_min=price_min,
                price_max=price_max,
                entries_per_page=50,
            )

            new_count = 0
            profitable_count = 0

            for listing in listings:
                # Skip if already seen
                if listing.item_id in TEXTBOOK_SEEN_ITEMS:
                    continue

                # Mark as seen
                TEXTBOOK_SEEN_ITEMS[listing.item_id] = datetime.now()
                new_count += 1

                # Skip blocked sellers
                if BLOCKED_SELLERS_ENABLED:
                    seller_lower = listing.seller_username.lower() if listing.seller_username else ""
                    if seller_lower in BLOCKED_SELLERS:
                        continue

                # Analyze with KeepaTracker
                deal = await analyze_textbook_listing(listing)

                if deal:
                    profitable_count += 1
                    logger.info(f"[TEXTBOOK] PROFITABLE: {deal['title'][:50]} - ${deal['estimated_profit']} profit")

                    # Call callback if provided
                    if callback:
                        await callback(listing, deal)

            logger.info(f"[TEXTBOOK] '{keyword}': {new_count} new, {profitable_count} profitable")

        except Exception as e:
            logger.error(f"[TEXTBOOK] Polling error: {e}")

        # Move to next keyword
        keyword_index = (keyword_index + 1) % len(keywords)

        # Clean up old seen items (older than 1 hour)
        cutoff = datetime.now() - timedelta(hours=1)
        TEXTBOOK_SEEN_ITEMS = {k: v for k, v in TEXTBOOK_SEEN_ITEMS.items() if v > cutoff}

        # Wait for next poll
        await asyncio.sleep(TEXTBOOK_POLL_INTERVAL)


def start_textbook_polling(callback=None):
    """Start the textbook polling loop in the background"""
    global _TEXTBOOK_TASK

    if _TEXTBOOK_TASK is not None:
        logger.warning("[TEXTBOOK] Polling already running")
        return

    loop = asyncio.get_event_loop()
    _TEXTBOOK_TASK = loop.create_task(textbook_polling_loop(callback))
    logger.info("[TEXTBOOK] Started textbook polling")


def stop_textbook_polling():
    """Stop the textbook polling loop"""
    global _TEXTBOOK_TASK

    if _TEXTBOOK_TASK is not None:
        _TEXTBOOK_TASK.cancel()
        _TEXTBOOK_TASK = None
        logger.info("[TEXTBOOK] Stopped textbook polling")


# ============================================================
# CLI / TESTING
# ============================================================

async def test_search():
    """Test the eBay API connection"""
    print("\n=== eBay Finding API Test ===\n")
    
    if not EBAY_APP_ID:
        print("ERROR: EBAY_APP_ID not set in environment!")
        print("Set it with: export EBAY_APP_ID=your_app_id")
        return
    
    print(f"App ID: {EBAY_APP_ID[:20]}...")
    print(f"Testing search for '14k gold scrap'...\n")
    
    listings = await search_ebay(
        keywords="14k gold scrap",
        category_ids=["281"],
        price_min=50,
        price_max=5000,
        entries_per_page=10,
    )
    
    print(f"Found {len(listings)} listings:\n")
    for listing in listings[:5]:
        print(f"  ${listing.price:>7.2f} | {listing.title[:60]}")
        print(f"           | {listing.view_url}")
        print()
    
    print(f"\nAPI Stats: {API_STATS['calls_today']} calls today")




# ============================================================
# ANALYSIS CALLBACK - Send listings to proxy for full analysis
# ============================================================

async def analyze_listing_callback(listing):
    """Send a listing to the proxy for full AI analysis"""
    logger.info(f"[ANALYSIS] Callback invoked for: {listing.title[:40]}...")
    try:
        # Log to source comparison system for race tracking
        try:
            from utils.source_comparison import log_listing_received
            log_listing_received(
                item_id=listing.item_id,
                source="direct",  # Direct API source
                posted_time=listing.start_time.isoformat() if listing.start_time else "",
                title=listing.title,
                price=listing.price,
                category="gold" if "gold" in listing.title.lower() or "14k" in listing.title.lower() or "18k" in listing.title.lower() else "silver"
            )
            logger.info(f"[ANALYSIS] Logged to source comparison: {listing.item_id}")
        except Exception as e:
            logger.warning(f"[ANALYSIS] Source comparison logging failed: {e}")

        proxy_url = os.getenv("PROXY_URL", "http://127.0.0.1:8000") + "/match_mydata"

        # Fetch full item details (description, images) for better analysis
        item_details = await get_item_details(listing.item_id)
        description = ""
        images = []
        if item_details:
            description = item_details.get('description', '')
            images = item_details.get('images', [])
        
        # Build request data - include description and images for full AI analysis
        data = {
            "Title": listing.title,
            "TotalPrice": f"${listing.price:.2f}",
            "ItemPrice": f"${listing.price:.2f}",
            "URL": listing.view_url or f"https://www.ebay.com/itm/{listing.item_id}",
            "SellerName": listing.seller_id,
            "Description": description,
            "response_type": "json",
        }
        
        # Add images if available (for scale photo detection)
        if images:
            data["Images"] = ",".join(images[:5])  # Max 5 images
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(proxy_url, params=data)
            if response.status_code == 200:
                result = response.json()
                recommendation = result.get("Recommendation", "UNKNOWN")
                
                # Update Discord notification with analysis results
                if recommendation == "BUY":
                    # Extract numeric values from proxy response
                    max_buy_str = result.get("MaxBuy", "0") or "0"
                    max_buy = float(max_buy_str.replace("$", "").replace(",", "").replace("+", "") or 0)
                    
                    profit_str = result.get("Profit", "0") or "0"
                    profit = float(profit_str.replace("$", "").replace(",", "").replace("+", "") or 0)
                    
                    await send_discord_listing(
                        listing,
                        keyword="API Analysis",
                        source="Full Pipeline",
                        recommendation=recommendation,
                        reasoning=f"Profit: ${profit:.0f} | {result.get('reasoning', '')[:100]}",
                        melt_value=None,  # Don't show raw melt value
                        max_buy=max_buy if max_buy > 0 else None,
                    )
                    logger.info(f"[ANALYSIS] {recommendation}: {listing.title[:40]}...")
                else:
                    logger.debug(f"[ANALYSIS] {recommendation}: {listing.title[:40]}...")
            else:
                logger.warning(f"[ANALYSIS] Proxy error {response.status_code}")
    except Exception as e:
        logger.warning(f"[ANALYSIS] Error analyzing listing: {e}")


async def run_polling_forever():
    """Start polling and run forever with analysis callback"""
    await start_polling(callback=analyze_listing_callback)
    # Keep running forever
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await stop_polling()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        asyncio.run(test_search())
    else:
        print("[EBAY POLLER] Starting continuous polling... (Ctrl+C to stop)")
        try:
            asyncio.run(run_polling_forever())
        except KeyboardInterrupt:
            print("[EBAY POLLER] Stopped by user")
