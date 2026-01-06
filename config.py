"""
Configuration settings for Claude Proxy Server
Centralized settings for easy management
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
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
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "arbitrage_data.db"
LOG_PATH = BASE_DIR / "proxy.log"

# ============================================================
# SERVER SETTINGS
# ============================================================
HOST = "127.0.0.1"
PORT = 8000

# ============================================================
# API SETTINGS
# ============================================================
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not CLAUDE_API_KEY or CLAUDE_API_KEY == "YOUR_API_KEY_HERE":
    print("[CONFIG] WARNING: ANTHROPIC_API_KEY not set! Check your .env file.")
else:
    print(f"[CONFIG] API key loaded ({CLAUDE_API_KEY[:8]}...)")

# eBay Finding API
EBAY_APP_ID = os.getenv("EBAY_APP_ID")
if EBAY_APP_ID and EBAY_APP_ID != "YOUR_EBAY_APP_ID_HERE":
    print(f"[CONFIG] eBay App ID loaded ({EBAY_APP_ID[:8]}...)")
else:
    print("[CONFIG] WARNING: EBAY_APP_ID not set - eBay URL lookup disabled")
    EBAY_APP_ID = None

# Discord Webhook
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "YOUR_DISCORD_WEBHOOK_URL_HERE":
    print(f"[CONFIG] Discord webhook configured")
else:
    print("[CONFIG] WARNING: DISCORD_WEBHOOK_URL not set - Discord alerts disabled")
    DISCORD_WEBHOOK_URL = None

MODEL_FAST = "claude-3-5-haiku-20241022"  # Tier 1: Quick pre-filters
MODEL_FULL = "claude-sonnet-4-20250514"  # Tier 2: Full analysis on BUY/RESEARCH (Claude 4 Sonnet)

# Cost tracking
COST_PER_CALL_HAIKU = 0.001
COST_PER_CALL_SONNET = 0.015

# ============================================================
# TWO-TIER ANALYSIS SETTINGS
# ============================================================
# Tier 1: Haiku pre-filter (all listings) - cheap, fast
# Tier 2: Sonnet re-analysis (BUY/RESEARCH only) - expensive, accurate

TIER2_ENABLED = os.getenv("TIER2_ENABLED", "true").lower() == "true"
TIER2_MIN_MARGIN = float(os.getenv("TIER2_MIN_MARGIN", "30"))  # Only re-analyze if margin > $30

# Tier 2 Provider Selection
# Options: "claude" (Sonnet - accurate but slow), "openai" (GPT-4o - fast)
TIER2_PROVIDER = os.getenv("TIER2_PROVIDER", "claude").lower()

# ============================================================
# PARALLEL PROCESSING MODE
# ============================================================
# When enabled, Haiku and Sonnet run SIMULTANEOUSLY
# - Haiku result returns immediately for fast display
# - Sonnet confirms/overrides and triggers Discord alert
# This gives you speed (see result in ~2s) + accuracy (Sonnet verification)
PARALLEL_MODE = os.getenv("PARALLEL_MODE", "true").lower() == "true"

# For HOT deals (verified weight+karat from title), skip Tier 2 entirely
# The math is verified - no need for AI confirmation
SKIP_TIER2_FOR_HOT = os.getenv("SKIP_TIER2_FOR_HOT", "true").lower() == "true"

# OpenAI API Key (for Tier 2 if using OpenAI)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TIER2_MODEL = os.getenv("OPENAI_TIER2_MODEL", "gpt-4o")  # CHANGED: Was mini - need smarter model

# OpenAI Cost Tracking (updated for high-detail images)
# GPT-4o pricing: $2.50/1M input, $10/1M output + image costs
# High detail images: ~$0.01-0.03 per image depending on size (512px = ~$0.01)
# Low detail images: ~$0.003 per image
COST_PER_CALL_GPT4O = 0.02           # GPT-4o with ~5 high-detail images for gold/silver
COST_PER_CALL_GPT4O_LOW_DETAIL = 0.008  # GPT-4o with low-detail images
COST_PER_CALL_GPT4O_MINI = 0.001     # GPT-4o-mini: ~$0.001 per call (text or low-detail)
COST_PER_CALL_OPENAI = 0.02          # Default for Tier 2 with images

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
# CACHE SETTINGS (Smart TTL)
# ============================================================
# Set DEV_MODE=true in .env for shorter cache times during development
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

@dataclass
class CacheConfig:
    """Different cache durations based on recommendation"""
    # Development mode: very short TTLs to avoid stale data while coding
    # Production mode: longer TTLs for performance
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
    # Tier 1 settings (now GPT-4o for gold/silver - can handle more images)
    max_images_haiku: int = 2         # For non-precious-metal categories
    max_images_gold_silver: int = 5   # More images for gold/silver (scale photos!)
    resize_for_haiku: int = 384       # Smaller for speed on non-PM categories
    resize_for_gold_silver: int = 512 # Larger for gold/silver (need scale reading)

    # Tier 2 settings
    max_images_tier2: int = 12        # ALL images for Tier 2 Sonnet
    resize_for_tier2: int = 768       # 768px for Tier 2 (balance speed/accuracy)

    # Connection settings
    timeout: float = 5.0              # Per-image timeout (seconds)
    max_concurrent: int = 8           # Increased concurrent fetch limit
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

IMAGES = ImageConfig()

# ============================================================
# INSTANT PASS RULES (No AI needed - pure rule-based)
# ============================================================
# These keywords in title = instant PASS, no AI analysis needed
INSTANT_PASS_KEYWORDS = [
    # Plated/Filled (no gold value)
    'gold filled', 'gf ', ' gf', '/gf', 'gold plated', 'gp ', ' gp', '/gp',
    'hge', 'rgp', 'vermeil', 'gold tone', 'gold-tone', 'goldtone',
    'plated', 'gold over', 'bonded gold', 'clad',
    # Silver plated
    'silver plated', 'silverplate', 'silver plate', 'epns', 'silver tone',
    # Hollow/Resin (minimal metal)
    'resin core', 'resin filled', 'hollow core',
    # Single items (no resale)
    'single earring',
    # Costume
    'costume jewelry', 'fashion jewelry',
]

# Price thresholds for instant PASS (only used when weight is STATED in title)
# If price > (stated_weight * rate * threshold), instant PASS
INSTANT_PASS_PRICE_THRESHOLDS = {
    # Gold: If paying more than 100% of melt, instant PASS
    '10k': 1.00,
    '14k': 1.00,
    '18k': 1.00,
    '22k': 1.00,
    '24k': 1.00,
    # Silver: If paying more than 90% of melt, instant PASS
    'sterling': 0.90,
    '925': 0.90,
}

# ============================================================
# DATABASE SETTINGS
# ============================================================
@dataclass
class DatabaseConfig:
    """SQLite optimization settings"""
    wal_mode: bool = True        # Write-Ahead Logging for better concurrency
    cache_size: int = -64000     # 64MB cache (negative = KB)
    busy_timeout: int = 5000     # 5 second busy timeout
    synchronous: str = "NORMAL"  # NORMAL is faster than FULL, still safe
    journal_size_limit: int = 67108864  # 64MB journal limit

DATABASE = DatabaseConfig()

# ============================================================
# SPOT PRICES (Defaults - updated at runtime from Yahoo/Metals.live)
# These fallbacks should be updated periodically to stay close to market
# ============================================================
SPOT_PRICES: Dict[str, float] = {
    "gold_oz": 4450.00,      # ~Jan 2025 fallback
    "silver_oz": 78.00,       # ~Jan 2025 fallback
    "gold_gram": 143.08,      # 4450 / 31.1035
    "silver_gram": 2.51,      # 78 / 31.1035
    "10K": 59.66,             # gold_gram * 0.417
    "14K": 83.42,             # gold_gram * 0.583
    "18K": 107.31,            # gold_gram * 0.750
    "22K": 131.20,            # gold_gram * 0.917
    "24K": 143.08,            # gold_gram * 1.000
    "sterling": 2.32,         # silver_gram * 0.925
    "last_updated": None,
    "source": "default",
}

# ============================================================
# BUSINESS RULES
# ============================================================
@dataclass
class GoldRules:
    max_buy_pct: float = 0.90    # Buy at max 90% of melt
    sell_pct: float = 0.96       # Sell at 96% of melt
    high_risk_types: tuple = ("chain", "rope", "herringbone", "cuban", "franco")
    low_risk_types: tuple = ("ring", "pendant", "bracelet", "vintage", "signed")

@dataclass
class SilverRules:
    max_buy_pct: float = 0.75    # Buy at max 75% of melt
    weighted_actual_pct: float = 0.20  # Weighted items only 20% silver

GOLD_RULES = GoldRules()
SILVER_RULES = SilverRules()

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
