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

# Import blocked sellers for filtering
try:
    from utils.spam_detection import BLOCKED_SELLERS, check_seller_spam
    BLOCKED_SELLERS_ENABLED = True
    from config import INSTANT_PASS_KEYWORDS
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
    logger = logging.getLogger("ebay_poller")
    logger.warning("[EBAY API] Seller profiling not available - database module not found")

# ============================================================
# CONFIGURATION
# ============================================================

EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID", "")  # Client Secret for OAuth

# API endpoints
BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"  # Legacy fallback

# OAuth token cache
_oauth_token: Optional[str] = None
_oauth_expires: Optional[datetime] = None
_oauth_lock = threading.Lock()

# Rate limiting - eBay allows ~5000 calls/day over 14 hours
# 5000 / 14hr = 357/hr = 6 calls/min = 10 seconds between calls
# With 2 keywords: each refreshes every 20 seconds
RATE_LIMIT_MIN_INTERVAL = 10.0  # 10 seconds between calls - OPTIMIZED for 5000/day

# Track last API call time for rate limiting
_last_api_call: Optional[float] = None
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


# Polling intervals (seconds) - OPTIMIZED for 2 keywords only
# With RATE_LIMIT_MIN_INTERVAL=10s and 2 keywords:
#   - Gold polls, waits 10s, Silver polls, waits 10s = 20s cycle
#   - Each keyword refreshes every 20 seconds
# Poll interval just needs to be >= cycle time (20s)
POLL_INTERVAL_GOLD = 20      # Gold "14k scrap" - refreshes every 20s
POLL_INTERVAL_SILVER = 20    # Silver "sterling scrap" - refreshes every 20s
POLL_INTERVAL_TCG = 600      # TCG - disabled, 10 min placeholder
POLL_INTERVAL_LEGO = 600     # LEGO - disabled, 10 min placeholder

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

# OPTIMIZED: Only 2 keywords to maximize refresh rate within 5000 calls/day
# With 10s between calls, each keyword refreshes every 20 seconds
# This beats uBuyFirst's typical 6-38 second latency
PRIORITY_KEYWORDS = {
    "gold": [
        "14k scrap",      # Most common karat, highest volume scrap
        "14K Gold",       # Broad coverage for 14K items (chains, necklaces, etc.)
    ],
    "silver": [
        "sterling scrap", # Direct scrap sellers
    ],
}
# DISABLED - batched keywords consume too much API budget
# Re-enable if eBay increases rate limits or you get additional API keys

# DISABLED to maximize refresh rate on priority keywords
# Uncomment if you get more API budget
BATCHED_KEYWORDS = {
    "gold": [],      # DISABLED - using priority only
    "watch": [],     # DISABLED
    "silver": [],    # DISABLED - using priority only
}

def clear_seen_listings():
    """Clear the seen listings cache - useful for race testing"""
    global SEEN_LISTINGS
    count = len(SEEN_LISTINGS)
    SEEN_LISTINGS.clear()
    logger.info(f"[EBAY API] Cleared {count} seen listings from cache")
    return count

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ebay_poller")

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
        ],
        "category_ids": ["281", "162134", "3360", "262022", "10290"],
        "price_min": 50,
        "price_max": 10000,
        "poll_interval": POLL_INTERVAL_GOLD,
    },
    "silver": {
        "keywords": [
            "sterling scrap", "sterling lot", "sterling flatware", "sterling grams",
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


async def search_ebay(
    keywords: str,
    category_ids: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    sort_order: str = "StartTimeNewest",
    entries_per_page: int = 50,
) -> List[EbayListing]:
    """
    Search eBay using Browse API (preferred) or Finding API (fallback)

    Returns list of EbayListing objects
    """
    if not EBAY_APP_ID:
        logger.error("[EBAY API] No EBAY_APP_ID configured!")
        return []

    # Use Browse API only (Finding API is deprecated/legacy)
    if not browse_api_available():
        logger.error("[EBAY API] Browse API not available - check EBAY_CERT_ID")
        return []

    result = await search_ebay_browse(keywords, category_ids, price_min, price_max, sort_order, entries_per_page)
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
) -> Optional[List[EbayListing]]:
    """
    Search eBay using Browse API (modern REST API)
    Returns None on API error (to trigger fallback), [] on no results
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

def is_new_listing(item_id: str) -> bool:
    """Check if we've seen this listing before"""
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

        listings = await search_ebay(
            keywords=keyword,
            category_ids=search_categories,
            price_min=config["price_min"],
            price_max=config["price_max"],
            entries_per_page=50,  # Get more per call since we make fewer calls
        )

        # Filter to new listings only
        for listing in listings:
            if is_new_listing(listing.item_id):
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

                # Check for instant pass keywords (gold plated, silver plated, etc.)
                title_lower = listing.title.lower()
                skip_instant = False
                for kw in INSTANT_PASS_KEYWORDS:
                    if kw in title_lower:
                        logger.debug(f"[EBAY API] Skipping instant-pass keyword '{kw}': {listing.title[:40]}")
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
# INTEGRATION WITH PROXY
# ============================================================

async def analyze_listing_callback(listing: EbayListing):
    """
    Callback to send new listings to the proxy for analysis
    """
    # This would send to localhost:8000/match_mydata
    # For now, just log it
    logger.info(f"[EBAY API] Would analyze: ${listing.price:.0f} - {listing.title[:40]}")
    
    # TODO: Implement actual proxy call
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(
    #         "http://localhost:8000/match_mydata",
    #         json=listing.to_dict()
    #     )


# ============================================================
# BACKGROUND POLLING
# ============================================================

POLL_TASKS: Dict[str, asyncio.Task] = {}

async def start_polling(categories: List[str] = None, callback=None):
    """
    Start background polling for specified categories
    
    categories: List of category names, or None for all
    callback: async function to call for each new listing
    """
    global POLL_TASKS
    
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
    global POLL_TASKS
    
    if categories is None:
        categories = list(POLL_TASKS.keys())
    
    for category in categories:
        if category in POLL_TASKS:
            POLL_TASKS[category].cancel()
            del POLL_TASKS[category]
            logger.info(f"[EBAY API] Stopped polling: {category}")


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


if __name__ == "__main__":
    # Run test
    asyncio.run(test_search())
