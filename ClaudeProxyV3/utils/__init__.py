"""
Utils Package

Shared utilities for ClaudeProxyV3.
"""

from .extraction import (
    extract_weight_from_title,
    extract_karat_from_title,
    extract_silver_purity,
    extract_price,
    contains_non_metal_indicators,
    extract_lot_info,
    normalize_title,
)

from .spam_detection import (
    check_seller_spam,
    check_professional_seller,
    add_blocked_seller,
    remove_blocked_seller,
    clear_blocked_sellers,
    import_blocked_sellers,
    get_blocked_sellers,
    get_blocked_count,
    save_blocked_sellers,
    BLOCKED_SELLERS,
    PROFESSIONAL_SELLER_KEYWORDS as SPAM_PROFESSIONAL_KEYWORDS,
)

from .constants import (
    CATEGORY_THRESHOLDS,
    get_category_threshold,
    KARAT_TO_PURITY,
    SILVER_PURITY_MAP,
    PROFESSIONAL_SELLER_KEYWORDS,
    ESTATE_SELLER_KEYWORDS,
    SELLER_SPAM_WINDOW,
    SELLER_SPAM_THRESHOLD,
    GOLD_SELL_RATE,
    GOLD_MAX_BUY_RATE,
    SILVER_SELL_RATE,
    SILVER_MAX_BUY_RATE,
    NATIVE_MAX_MELT_MULTIPLIER,
    RECENTLY_EVALUATED_WINDOW,
    DISCORD_DEDUP_WINDOW,
)

from .discord import (
    send_discord_alert,
    send_simple_discord_message,
    is_duplicate_alert,
    mark_alert_sent,
    get_alert_count,
    clear_old_alerts,
    load_discord_alerts,
    save_discord_alerts,
    DISCORD_SENT_ALERTS,
)

from .validation import (
    normalize_tcg_lego_keys,
    parse_price,
    calculate_margin,
    extract_margin_from_reasoning,
    check_lego_condition,
    check_professional_seller,
    is_valid_recommendation,
    normalize_recommendation,
    TCG_LEGO_KEY_MAPPINGS,
    LEGO_DEFAULTS,
    TCG_DEFAULTS,
    LEGO_PASS_TERMS,
    LEGO_KNOCKOFF_TERMS,
)

from .deal_scoring import (
    calculate_deal_score,
    format_deal_score,
    detect_misspellings,
    analyze_listing_quality,
    detect_opportunity_keywords,
    DealScore,
    WEIGHTS as DEAL_SCORE_WEIGHTS,
    BRAND_MISSPELLINGS,
    VALUABLE_BRANDS,
    POOR_LISTING_KEYWORDS,
)

# Budget tracking
from .budget import (
    check_openai_budget,
    record_openai_cost,
    get_openai_budget_status,
    set_hourly_budget,
    reset_budget_tracker,
    OPENAI_HOURLY_BUDGET,
)

# Unified Listing Adapter - normalizes both uBuyFirst and Direct API data
from .listing_adapter import (
    StandardizedListing,
    normalize_ubuyfirst,
    normalize_api_listing,
    normalize_listing,
    validate_listing,
    detect_category,
    CATEGORY_KEYWORDS,
)

__all__ = [
    # Extraction
    'extract_weight_from_title',
    'extract_karat_from_title',
    'extract_silver_purity',
    'extract_price',
    'contains_non_metal_indicators',
    'extract_lot_info',
    'normalize_title',
    # Spam detection
    'check_seller_spam',
    'add_blocked_seller',
    'remove_blocked_seller',
    'clear_blocked_sellers',
    'import_blocked_sellers',
    'get_blocked_sellers',
    'get_blocked_count',
    'save_blocked_sellers',
    'BLOCKED_SELLERS',
    # Constants
    'CATEGORY_THRESHOLDS',
    'get_category_threshold',
    'KARAT_TO_PURITY',
    'SILVER_PURITY_MAP',
    'PROFESSIONAL_SELLER_KEYWORDS',
    'ESTATE_SELLER_KEYWORDS',
    'SELLER_SPAM_WINDOW',
    'SELLER_SPAM_THRESHOLD',
    'GOLD_SELL_RATE',
    'GOLD_MAX_BUY_RATE',
    'SILVER_SELL_RATE',
    'SILVER_MAX_BUY_RATE',
    'NATIVE_MAX_MELT_MULTIPLIER',
    'RECENTLY_EVALUATED_WINDOW',
    'DISCORD_DEDUP_WINDOW',
    # Discord
    'send_discord_alert',
    'send_simple_discord_message',
    'is_duplicate_alert',
    'mark_alert_sent',
    'get_alert_count',
    'clear_old_alerts',
    'load_discord_alerts',
    'save_discord_alerts',
    'DISCORD_SENT_ALERTS',
    # Validation
    'normalize_tcg_lego_keys',
    'parse_price',
    'calculate_margin',
    'extract_margin_from_reasoning',
    'check_lego_condition',
    'check_professional_seller',
    'is_valid_recommendation',
    'normalize_recommendation',
    'TCG_LEGO_KEY_MAPPINGS',
    'LEGO_DEFAULTS',
    'TCG_DEFAULTS',
    'LEGO_PASS_TERMS',
    'LEGO_KNOCKOFF_TERMS',
    # Deal Scoring
    'calculate_deal_score',
    'format_deal_score',
    'detect_misspellings',
    'analyze_listing_quality',
    'detect_opportunity_keywords',
    'DealScore',
    'DEAL_SCORE_WEIGHTS',
    'BRAND_MISSPELLINGS',
    'VALUABLE_BRANDS',
    'POOR_LISTING_KEYWORDS',
    # Listing Adapter
    'StandardizedListing',
    'normalize_ubuyfirst',
    'normalize_api_listing',
    'normalize_listing',
    'validate_listing',
    'detect_category',
    'CATEGORY_KEYWORDS',
    # Budget tracking
    'check_openai_budget',
    'record_openai_cost',
    'get_openai_budget_status',
    'set_hourly_budget',
    'reset_budget_tracker',
    'OPENAI_HOURLY_BUDGET',
]
