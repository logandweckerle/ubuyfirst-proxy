"""
Constants and Utilities for ClaudeProxyV3

This module re-exports configuration from config.settings and provides
utility functions for working with those values.
"""

# Re-export all configuration from centralized config
from config import (
    # Category thresholds
    CATEGORY_THRESHOLDS,
    get_category_threshold,

    # Metal purity mappings
    KARAT_TO_PURITY,
    SILVER_PURITY_MAP,

    # Professional seller detection
    PROFESSIONAL_SELLER_KEYWORDS,
    ESTATE_SELLER_KEYWORDS,

    # Spam detection
    SELLER_SPAM_WINDOW,
    SELLER_SPAM_THRESHOLD,

    # Precious metal rates
    GOLD_SELL_RATE,
    GOLD_MAX_BUY_RATE,
    SILVER_SELL_RATE,
    SILVER_MAX_BUY_RATE,
    NATIVE_MAX_MELT_MULTIPLIER,

    # Deduplication windows
    RECENTLY_EVALUATED_WINDOW,
    DISCORD_DEDUP_WINDOW,

    # AI costs
    COST_PER_CALL_HAIKU,
    COST_PER_CALL_SONNET,
    COST_PER_CALL_GPT4O_MINI,
    COST_PER_CALL_GPT4O,
    COST_PER_CALL_OPENAI,
    OPENAI_HOURLY_BUDGET,

    # Tier 2 thresholds
    TIER2_MIN_MARGIN,
    TIER2_MIN_CONFIDENCE,
    MIN_PROFIT_FOR_BUY,
    MAX_ESTIMATED_WEIGHT_PROFIT,
    SUSPICIOUS_PROFIT_THRESHOLD,

    # Weight estimation caps
    MAX_ESTIMATED_FLATWARE_WEIGHT,
    MAX_CHAIN_WEIGHT_PER_INCH,
    MAX_RING_WEIGHT,

    # Concurrency
    MAX_CONCURRENT_AI_CALLS,
    MAX_CONCURRENT_IMAGES,

    # LEGO terms
    LEGO_PASS_TERMS,
    LEGO_KNOCKOFF_TERMS,
)
