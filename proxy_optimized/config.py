"""
Configuration settings for Claude Proxy Server
Centralized settings for easy management
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

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
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
MODEL_FAST = "claude-3-5-haiku-20241022"  # For quick pre-filters
MODEL_FULL = "claude-3-5-haiku-20241022"  # For full analysis (can upgrade to Sonnet)

# Cost tracking
COST_PER_CALL_HAIKU = 0.001
COST_PER_CALL_SONNET = 0.015

# ============================================================
# CACHE SETTINGS (Smart TTL)
# ============================================================
@dataclass
class CacheConfig:
    """Different cache durations based on recommendation"""
    ttl_buy: int = 60        # BUY results: 1 minute (might want to re-check)
    ttl_pass: int = 300      # PASS results: 5 minutes (won't change)
    ttl_research: int = 120  # RESEARCH: 2 minutes
    ttl_queued: int = 10     # Queued items: 10 seconds
    max_size: int = 500      # Max cached items

CACHE = CacheConfig()

# ============================================================
# IMAGE FETCHING SETTINGS
# ============================================================
@dataclass 
class ImageConfig:
    """Settings for async image fetching"""
    max_images: int = 5          # Max images to fetch per listing
    timeout: float = 5.0         # Per-image timeout (seconds)
    max_concurrent: int = 5      # Concurrent fetch limit
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

IMAGES = ImageConfig()

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
# SPOT PRICES (Defaults - updated at runtime)
# ============================================================
SPOT_PRICES: Dict[str, float] = {
    "gold_oz": 2650.00,
    "silver_oz": 30.00,
    "gold_gram": 85.20,
    "silver_gram": 0.96,
    "10K": 35.53,
    "14K": 49.67,
    "18K": 63.90,
    "22K": 78.13,
    "24K": 85.20,
    "sterling": 0.89,
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
