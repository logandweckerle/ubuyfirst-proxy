"""
Centralized Configuration Settings for Claude Proxy Server

All configuration values are consolidated here for easy management.
This replaces the scattered config across config.py, utils/constants.py, and main.py.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional

# ============================================================
# ENVIRONMENT LOADING
# ============================================================
try:
    from dotenv import load_dotenv
    # Try .env in package dir first, then project root
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[CONFIG] Loaded .env from {env_path}")
    else:
        print(f"[CONFIG] No .env file found at {env_path}")
except ImportError:
    print("[CONFIG] python-dotenv not installed. Run: pip install python-dotenv")

# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "arbitrage_data.db"
LOG_PATH = BASE_DIR / "proxy.log"
TRAINING_LOG_PATH = BASE_DIR / "training_overrides.jsonl"
PURCHASE_LOG_PATH = BASE_DIR / "purchases.jsonl"
PRICE_OVERRIDES_PATH = BASE_DIR / "price_overrides.json"
BLOCKED_SELLERS_PATH = BASE_DIR / "blocked_sellers.json"

# ============================================================
# SERVER SETTINGS
# ============================================================
HOST = os.getenv("HOST", "127.0.0.1")  # Set to "0.0.0.0" to allow LAN access from mini PC
PORT = int(os.getenv("PORT", "8000"))

# ============================================================
# API KEYS & CREDENTIALS
# ============================================================
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not CLAUDE_API_KEY or CLAUDE_API_KEY == "YOUR_API_KEY_HERE":
    print("[CONFIG] WARNING: ANTHROPIC_API_KEY not set! Check your .env file.")
else:
    print(f"[CONFIG] API key loaded ({CLAUDE_API_KEY[:8]}...)")

# eBay API (Browse API - OAuth2)
EBAY_APP_ID = os.getenv("EBAY_APP_ID")  # Also called Client ID
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID")  # Also called Client Secret

if EBAY_APP_ID and EBAY_APP_ID != "YOUR_EBAY_APP_ID_HERE":
    print(f"[CONFIG] eBay App ID loaded ({EBAY_APP_ID[:8]}...)")
    if EBAY_CERT_ID and EBAY_CERT_ID != "YOUR_EBAY_CERT_ID_HERE":
        print(f"[CONFIG] eBay Cert ID loaded - Browse API enabled")
    else:
        print("[CONFIG] WARNING: EBAY_CERT_ID not set - Browse API disabled, Finding API only")
        EBAY_CERT_ID = None
else:
    print("[CONFIG] WARNING: EBAY_APP_ID not set - eBay lookup disabled")
    EBAY_APP_ID = None
    EBAY_CERT_ID = None

# Discord Webhook
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "YOUR_DISCORD_WEBHOOK_URL_HERE":
    print(f"[CONFIG] Discord webhook configured")
else:
    print("[CONFIG] WARNING: DISCORD_WEBHOOK_URL not set - Discord alerts disabled")
    DISCORD_WEBHOOK_URL = None

# OpenAI API (for Tier 2)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ============================================================
# AI MODEL SETTINGS
# ============================================================
MODEL_FAST = "claude-3-5-haiku-20241022"  # Tier 1: Quick pre-filters
MODEL_FULL = "claude-sonnet-4-20250514"   # Tier 2: Full analysis on BUY/RESEARCH
OPENAI_TIER2_MODEL = os.getenv("OPENAI_TIER2_MODEL", "gpt-4o")

# Cost tracking (per call estimates)
COST_PER_CALL_HAIKU = 0.002        # Claude 3.5 Haiku
COST_PER_CALL_SONNET = 0.015       # Claude 4 Sonnet
COST_PER_CALL_GPT4O = 0.02         # GPT-4o with images
COST_PER_CALL_GPT4O_LOW_DETAIL = 0.008  # GPT-4o with low-detail images
COST_PER_CALL_GPT4O_MINI = 0.001   # GPT-4o-mini
COST_PER_CALL_OPENAI = 0.02        # Default for Tier 2

# Budget limits
OPENAI_HOURLY_BUDGET = 5.00        # Max $5/hour on OpenAI

# ============================================================
# TIER 2 VERIFICATION SETTINGS
# ============================================================
TIER2_ENABLED = os.getenv("TIER2_ENABLED", "true").lower() == "true"
TIER2_MIN_MARGIN = float(os.getenv("TIER2_MIN_MARGIN", "30"))
TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "claude").lower()
TIER2_MIN_CONFIDENCE = 50          # Minimum Tier 1 confidence to verify

# Sanity check thresholds
MIN_PROFIT_FOR_BUY = 10.0          # Minimum profit to justify BUY
MAX_ESTIMATED_WEIGHT_PROFIT = 100.0  # Cap profit if weight is estimated
SUSPICIOUS_PROFIT_THRESHOLD = 500.0  # Flag for manual review

if TIER2_ENABLED:
    if TIER2_PROVIDER == "openai":
        if OPENAI_API_KEY and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY_HERE":
            print(f"[CONFIG] Tier 2 ENABLED: OpenAI {OPENAI_TIER2_MODEL} (FAST MODE)")
        else:
            print("[CONFIG] WARNING: TIER2_PROVIDER=openai but OPENAI_API_KEY not set! Falling back to Claude")
            TIER2_PROVIDER = "claude"

    if TIER2_PROVIDER == "claude":
        print(f"[CONFIG] Tier 2 ENABLED: Claude Sonnet re-analysis (min margin: ${TIER2_MIN_MARGIN})")
else:
    print("[CONFIG] Tier 2 DISABLED: Haiku only")

# ============================================================
# PARALLEL PROCESSING MODE
# ============================================================
PARALLEL_MODE = os.getenv("PARALLEL_MODE", "true").lower() == "true"
SKIP_TIER2_FOR_HOT = os.getenv("SKIP_TIER2_FOR_HOT", "true").lower() == "true"
API_ANALYSIS_ENABLED = False  # When True, direct API listings get full analysis

# ============================================================
# CATEGORY BUY THRESHOLDS (percentage of market value)
# ============================================================
# Only applies to PriceCharting categories (lego, tcg, videogames)
# Gold/silver use spot price * weight calculations, not market %
CATEGORY_THRESHOLDS = {
    'lego': 0.70,       # 70% - was 65%, too many false buys
    'tcg': 0.70,        # 70% - was 65%, too many variant/language mistakes
    'pokemon': 0.70,    # 70% - alias for tcg
    'videogames': 0.65, # 65% - keep standard, issues are matching not threshold
    'default': 0.65,    # 65% - fallback
}

def get_category_threshold(category: str) -> float:
    """Get the buy threshold for a category (as decimal, e.g., 0.65 for 65%)"""
    cat_lower = category.lower() if category else 'default'
    if cat_lower in ['tcg', 'pokemon']:
        return CATEGORY_THRESHOLDS.get('tcg', 0.65)
    return CATEGORY_THRESHOLDS.get(cat_lower, CATEGORY_THRESHOLDS['default'])

# ============================================================
# CACHE SETTINGS
# ============================================================
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

@dataclass
class CacheConfig:
    """Different cache durations based on recommendation"""
    ttl_buy: int = 30 if DEV_MODE else 60        # BUY: 30s dev, 1 min prod
    ttl_pass: int = 60 if DEV_MODE else 300      # PASS: 1 min dev, 5 min prod
    ttl_research: int = 30 if DEV_MODE else 120  # RESEARCH: 30s dev, 2 min prod
    ttl_queued: int = 10                          # Queued: 10 seconds always
    max_size: int = 500      # Max cached items

CACHE = CacheConfig()

if DEV_MODE:
    print("[CONFIG] DEV_MODE enabled - using short cache TTLs (30-60 seconds)")

# ============================================================
# IMAGE FETCHING SETTINGS
# ============================================================
@dataclass
class ImageConfig:
    """Settings for async image fetching"""
    max_images_haiku: int = 2         # For non-precious-metal categories
    max_images_gold_silver: int = 6   # More images for gold/silver
    resize_for_haiku: int = 384       # Smaller for speed
    resize_for_gold_silver: int = 1024 # Larger for scale reading (increased for better digit recognition)

    max_images_tier2: int = 12        # ALL images for Tier 2
    resize_for_tier2: int = 768       # 768px for Tier 2

    timeout: float = 5.0              # Per-image timeout
    max_concurrent: int = 8           # Concurrent fetch limit
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

IMAGES = ImageConfig()

# ============================================================
# DATABASE SETTINGS
# ============================================================
@dataclass
class DatabaseConfig:
    """SQLite optimization settings"""
    wal_mode: bool = True
    cache_size: int = -64000     # 64MB cache
    busy_timeout: int = 5000     # 5 second timeout
    synchronous: str = "NORMAL"
    journal_size_limit: int = 67108864  # 64MB

DATABASE = DatabaseConfig()

# ============================================================
# PRECIOUS METAL RATES & RULES
# ============================================================
# Gold rates (multipliers from melt value)
GOLD_SELL_RATE = 0.96     # 96% of melt - what we can sell gold for
GOLD_MAX_BUY_RATE = 0.90  # 90% of melt - max we should pay

# Silver rates
SILVER_SELL_RATE = 0.82   # 82% of melt - lower margin on silver
SILVER_MAX_BUY_RATE = 0.70  # 70% of melt - max we should pay

# Native American jewelry
NATIVE_MAX_MELT_MULTIPLIER = 4.0  # Never pay more than 4x melt

@dataclass
class GoldRules:
    max_buy_pct: float = 0.90
    sell_pct: float = 0.96
    high_risk_types: tuple = ("chain", "rope", "herringbone", "cuban", "franco")
    low_risk_types: tuple = ("ring", "pendant", "bracelet", "vintage", "signed")

@dataclass
class SilverRules:
    max_buy_pct: float = 0.70
    sell_pct: float = 0.82
    weighted_actual_pct: float = 0.15  # Weighted items only 15% silver

GOLD_RULES = GoldRules()
SILVER_RULES = SilverRules()

# Metal purity mappings
KARAT_TO_PURITY = {
    24: 0.999,
    22: 0.916,
    18: 0.750,
    14: 0.585,
    10: 0.417,
    9: 0.375,
}

SILVER_PURITY_MAP = {
    'sterling': 0.925,
    '925': 0.925,
    '900': 0.900,
    '800': 0.800,
    'coin': 0.900,
}

# Spot price defaults (updated at runtime from Yahoo/Metals.live)
SPOT_PRICES: Dict[str, float] = {
    "gold_oz": 4987.00,       # Jan 2026 fallback (~$5000)
    "silver_oz": 82.00,       # ~Jan 2026 fallback
    "gold_gram": 160.34,      # 4987 / 31.1035
    "silver_gram": 2.637,     # 82 / 31.1035
    "10K": 66.86,
    "14K": 93.48,
    "18K": 120.26,
    "22K": 147.03,
    "24K": 160.34,
    "sterling": 2.439,
    "last_updated": None,
    "source": "default",
}

# ============================================================
# WEIGHT ESTIMATION CAPS
# ============================================================
MAX_ESTIMATED_FLATWARE_WEIGHT = 2000  # grams
MAX_CHAIN_WEIGHT_PER_INCH = 2.0       # grams - max chain weight/inch
MAX_RING_WEIGHT = 40                  # grams - max ring weight

# ============================================================
# INSTANT PASS RULES (No AI needed)
# ============================================================
INSTANT_PASS_KEYWORDS = [
    # Plated/Filled/Wash (no gold value)
    'gold filled', 'gf ', ' gf', '/gf', 'gold plated', 'gp ', ' gp', '/gp',
    'gold wash', 'gold-wash', 'goldwash',
    'hge', 'rgp', 'vermeil', 'gold tone', 'gold-tone', 'goldtone',
    'plated', 'gold over', 'bonded gold', 'clad',
    # Silver plated
    'silver plated', 'silverplate', 'silver plate', 'epns', 'silver tone',
    # Hollow/Resin
    'resin core', 'resin filled', 'hollow core',
    # Single items
    'single earring',
]

# Price thresholds for instant PASS
INSTANT_PASS_PRICE_THRESHOLDS = {
    '10k': 1.00, '14k': 1.00, '18k': 1.00, '22k': 1.00, '24k': 1.00,
    'sterling': 0.90, '925': 0.90,
}

# ============================================================
# UBUYFIRST FILTER RULES
# ============================================================
UBF_TITLE_FILTERS = [
    'prizm', 'topps', 'bowman', 'keychain', 'stereoview', 'trading card', 'key chain',
    'american eagle', 'silver dollar', 'morgan dollar', 'cents', 'penny', 'quarter',
    'american silver eagle', 'railroad', 'finish', 'i5',
]

UBF_LOCATION_FILTERS = [
    'japan', 'china', 'hong kong', 'shanghai', 'shenzen', 'tokyo',
    'australia', 'india', 'france',
]

UBF_FEEDBACK_RULES = {
    'min_feedback_pct': 93.0,
    'min_feedback_score': 3,
    'max_feedback_score': 30000,
}

UBF_STORE_TITLE_FILTERS = ['watch', 'pen', 'knife']

# ============================================================
# SELLER DETECTION
# ============================================================
SELLER_SPAM_WINDOW = 10       # seconds (2 listings in 10s = spam)
SELLER_SPAM_THRESHOLD = 2     # appearances to trigger block

PROFESSIONAL_SELLER_KEYWORDS = {
    'gold': ['gold', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious', 'bullion', 'scrap'],
    'silver': ['silver', 'sterling', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious'],
    'videogames': ['games', 'gaming', 'retro', 'vintage', 'collectibles', 'collector',
                   'video', 'game', 'shop', 'store', 'entertainment', 'media'],
    'lego': ['lego', 'brick', 'building', 'toy', 'collectibles'],
    'tcg': ['card', 'cards', 'pokemon', 'tcg', 'trading', 'collectibles'],
}

ESTATE_SELLER_KEYWORDS = [
    'estate', 'inherited', 'grandma', 'grandmother', 'attic', 'downsizing',
    'moving', 'thrift', 'goodwill', 'salvation', 'hospice', 'charity',
    'liquidation', 'storage', 'auction', 'deceased', 'clean', 'cleanout'
]

# ============================================================
# DEDUPLICATION WINDOWS
# ============================================================
RECENTLY_EVALUATED_WINDOW = 600   # 10 minutes
DISCORD_DEDUP_WINDOW = 1800       # 30 minutes

# ============================================================
# CONCURRENCY LIMITS
# ============================================================
MAX_CONCURRENT_AI_CALLS = 20  # Increased from 10 to handle 4-panel spike traffic
MAX_CONCURRENT_IMAGES = 8     # Increased from 5 for faster parallel fetching

# ============================================================
# LEGO-SPECIFIC TERMS
# ============================================================
# Condition terms that indicate NOT sealed/new - INSTANT PASS
LEGO_PASS_TERMS = [
    'no box', 'missing box', 'without box', 'box only',
    'open box', 'opened', 'box opened',
    'used', 'played with', 'pre-owned', 'previously owned',
    'built', 'assembled', 'displayed', 'complete build',
    'incomplete', 'partial', 'missing pieces', 'missing parts',
    'bulk', 'loose', 'bricks only', 'parts only',
    'damaged box', 'box damage', 'crushed', 'dented', 'torn',
    'minifigures only', 'minifig lot', 'figures only',
    'bags only', 'sealed bags', 'numbered bags',
]

# Knockoff/fake terms
LEGO_KNOCKOFF_TERMS = [
    'alt of lego', 'alternative of lego', 'generic bricks', 'generic blocks',
    'compatible with lego', 'lego compatible', 'building blocks',
    'mould king', 'lepin', 'bela', 'lele', 'decool', 'sy blocks',
    'king blocks', 'lion king', 'xinlexin', 'lari', 'nuogao',
    'not lego', 'non-lego', 'third party', '3rd party bricks',
    'clone', 'knockoff', 'replica blocks', 'off-brand',
]

# ============================================================
# STOP WORDS FOR KEYWORD EXTRACTION
# ============================================================
STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
    'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can',
    'new', 'used', 'lot', 'set', 'piece', 'pieces', 'item', 'items', 'vintage', 'antique',
    'rare', 'beautiful', 'nice', 'great', 'good', 'excellent', 'free', 'shipping', 'fast',
    'authentic', 'genuine', 'real', 'original', 'estate', 'sale', 'auction', 'buy', 'now',
    'best', 'offer', 'obo', 'nr', 'no', 'reserve', 'look', 'see', 'pics', 'photos', 'pictures'
}
