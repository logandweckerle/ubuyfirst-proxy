"""
Constants and Configuration

Category thresholds and other configuration values for ClaudeProxyV3.
"""

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
    'default': 0.65,    # 65% - fallback for any other pricecharting category
}


def get_category_threshold(category: str) -> float:
    """Get the buy threshold for a category (as decimal, e.g., 0.65 for 65%)"""
    cat_lower = category.lower() if category else 'default'
    # Handle tcg/pokemon as same category
    if cat_lower in ['tcg', 'pokemon']:
        return CATEGORY_THRESHOLDS.get('tcg', 0.65)
    return CATEGORY_THRESHOLDS.get(cat_lower, CATEGORY_THRESHOLDS['default'])


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

# Professional seller detection keywords
PROFESSIONAL_SELLER_KEYWORDS = {
    'gold': ['gold', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious', 'bullion', 'scrap'],
    'silver': ['silver', 'sterling', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious'],
    'videogames': ['games', 'gaming', 'retro', 'vintage', 'collectibles', 'collector',
                   'video', 'game', 'shop', 'store', 'entertainment', 'media'],
    'lego': ['lego', 'brick', 'building', 'toy', 'collectibles'],
    'tcg': ['card', 'cards', 'pokemon', 'tcg', 'trading', 'collectibles'],
}

# Estate/thrift seller keywords (high value targets)
ESTATE_SELLER_KEYWORDS = [
    'estate', 'inherited', 'grandma', 'grandmother', 'attic', 'downsizing',
    'moving', 'thrift', 'goodwill', 'salvation', 'hospice', 'charity',
    'liquidation', 'storage', 'auction', 'deceased', 'clean', 'cleanout'
]

# Spam detection configuration
SELLER_SPAM_WINDOW = 30  # seconds
SELLER_SPAM_THRESHOLD = 2  # number of appearances to trigger block

# ============================================================
# PRECIOUS METAL RATES
# ============================================================
# These are multipliers used for calculating buy/sell values from melt

# Gold rates
GOLD_SELL_RATE = 0.96     # 96% of melt - what we can sell gold for
GOLD_MAX_BUY_RATE = 0.90  # 90% of melt - max we should pay

# Silver rates
SILVER_SELL_RATE = 0.82   # 82% of melt - lower margin on silver
SILVER_MAX_BUY_RATE = 0.75  # 75% of melt - max we should pay

# Native American jewelry cap
NATIVE_MAX_MELT_MULTIPLIER = 4.0  # Never pay more than 4x melt for Native American pieces

# Deduplication windows (seconds)
RECENTLY_EVALUATED_WINDOW = 600   # 10 minutes - don't re-evaluate same item
DISCORD_DEDUP_WINDOW = 1800       # 30 minutes - don't re-alert same item

# ============================================================
# AI MODEL COSTS (per call estimates)
# ============================================================
COST_PER_CALL_HAIKU = 0.002       # Claude 3 Haiku
COST_PER_CALL_SONNET = 0.015      # Claude 3.5 Sonnet
COST_PER_CALL_GPT4O_MINI = 0.005  # GPT-4o-mini (Tier 1)
COST_PER_CALL_GPT4O = 0.03        # GPT-4o (Tier 2)
COST_PER_CALL_OPENAI = 0.03       # Alias for GPT-4o

# Hourly budget limits
OPENAI_HOURLY_BUDGET = 5.00       # Max $5/hour on OpenAI

# ============================================================
# TIER 2 VERIFICATION THRESHOLDS
# ============================================================
TIER2_MIN_MARGIN = 15.0           # Minimum profit to trigger Tier 2 verification
TIER2_MIN_CONFIDENCE = 50         # Minimum Tier 1 confidence to verify

# Sanity check thresholds (from pipeline/tier2.py)
MIN_PROFIT_FOR_BUY = 10.0         # Minimum profit to justify BUY
MAX_ESTIMATED_WEIGHT_PROFIT = 100.0  # Cap profit if weight is estimated
SUSPICIOUS_PROFIT_THRESHOLD = 500.0  # Flag for manual review

# ============================================================
# WEIGHT ESTIMATION CAPS
# ============================================================
MAX_ESTIMATED_FLATWARE_WEIGHT = 2000  # grams - cap for estimated flatware
MAX_CHAIN_WEIGHT_PER_INCH = 2.0       # grams - max realistic chain weight/inch
MAX_RING_WEIGHT = 40                  # grams - max realistic ring weight

# ============================================================
# CONCURRENCY LIMITS
# ============================================================
MAX_CONCURRENT_AI_CALLS = 10      # Parallel AI call limit
MAX_CONCURRENT_IMAGES = 5         # Parallel image downloads
