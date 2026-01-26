"""
Configuration Settings for Claude Proxy Server

BACKWARDS COMPATIBILITY: This module re-exports everything from config/settings.py.
For new code, import directly from config.settings or from the config package.
"""

# Re-export everything from the centralized config package
from config import (
    # Paths
    BASE_DIR,
    DB_PATH,
    LOG_PATH,
    TRAINING_LOG_PATH,
    PURCHASE_LOG_PATH,
    PRICE_OVERRIDES_PATH,
    BLOCKED_SELLERS_PATH,

    # Server
    HOST,
    PORT,

    # API Keys
    CLAUDE_API_KEY,
    EBAY_APP_ID,
    EBAY_CERT_ID,
    DISCORD_WEBHOOK_URL,
    OPENAI_API_KEY,

    # Models
    MODEL_FAST,
    MODEL_FULL,
    OPENAI_TIER2_MODEL,

    # Cost tracking
    COST_PER_CALL_HAIKU,
    COST_PER_CALL_SONNET,
    COST_PER_CALL_GPT4O,
    COST_PER_CALL_GPT4O_LOW_DETAIL,
    COST_PER_CALL_GPT4O_MINI,
    COST_PER_CALL_OPENAI,
    OPENAI_HOURLY_BUDGET,

    # Tier 2
    TIER2_ENABLED,
    TIER2_MIN_MARGIN,
    TIER2_PROVIDER,
    TIER2_MIN_CONFIDENCE,
    MIN_PROFIT_FOR_BUY,
    MAX_ESTIMATED_WEIGHT_PROFIT,
    SUSPICIOUS_PROFIT_THRESHOLD,

    # Parallel processing
    PARALLEL_MODE,
    SKIP_TIER2_FOR_HOT,
    API_ANALYSIS_ENABLED,

    # Category thresholds
    CATEGORY_THRESHOLDS,
    get_category_threshold,

    # Dataclass configs
    CacheConfig,
    CACHE,
    DEV_MODE,
    ImageConfig,
    IMAGES,
    DatabaseConfig,
    DATABASE,
    GoldRules,
    GOLD_RULES,
    SilverRules,
    SILVER_RULES,

    # Precious metal rates
    GOLD_SELL_RATE,
    GOLD_MAX_BUY_RATE,
    SILVER_SELL_RATE,
    SILVER_MAX_BUY_RATE,
    NATIVE_MAX_MELT_MULTIPLIER,
    KARAT_TO_PURITY,
    SILVER_PURITY_MAP,
    SPOT_PRICES,

    # Weight estimation
    MAX_ESTIMATED_FLATWARE_WEIGHT,
    MAX_CHAIN_WEIGHT_PER_INCH,
    MAX_RING_WEIGHT,

    # Instant pass
    INSTANT_PASS_KEYWORDS,
    INSTANT_PASS_PRICE_THRESHOLDS,

    # uBuyFirst filters
    UBF_TITLE_FILTERS,
    UBF_LOCATION_FILTERS,
    UBF_FEEDBACK_RULES,
    UBF_STORE_TITLE_FILTERS,

    # Seller detection
    SELLER_SPAM_WINDOW,
    SELLER_SPAM_THRESHOLD,
    PROFESSIONAL_SELLER_KEYWORDS,
    ESTATE_SELLER_KEYWORDS,

    # Deduplication
    RECENTLY_EVALUATED_WINDOW,
    DISCORD_DEDUP_WINDOW,

    # Concurrency
    MAX_CONCURRENT_AI_CALLS,
    MAX_CONCURRENT_IMAGES,

    # LEGO terms
    LEGO_PASS_TERMS,
    LEGO_KNOCKOFF_TERMS,

    # Stop words
    STOP_WORDS,
)
