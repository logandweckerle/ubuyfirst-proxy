"""
Validation Utilities

Helper functions for validating AI responses and calculating margins/profits.
"""

import re
import logging
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ============================================================
# KEY NORMALIZATION
# ============================================================

# Common key mappings (AI often returns wrong case/spacing)
TCG_LEGO_KEY_MAPPINGS = {
    # LEGO keys
    'set count': 'SetCount',
    'setcount': 'SetCount',
    'Set Count': 'SetCount',
    'setnumber': 'SetNumber',
    'setNumbers': 'SetNumber',
    'set number': 'SetNumber',
    'Set Number': 'SetNumber',
    'setname': 'SetName',
    'set name': 'SetName',
    'Set Name': 'SetName',
    'theme': 'Theme',
    'retired': 'Retired',
    'qualify': 'Qualify',
    'recommendation': 'Recommendation',
    'market price': 'marketprice',
    'Market Price': 'marketprice',
    'MarketPrice': 'marketprice',
    'MarketValue': 'marketprice',
    'marketValue': 'marketprice',
    'market_price': 'marketprice',
    'BuyThreshold': 'maxBuy',
    'buyThreshold': 'maxBuy',
    'max buy': 'maxBuy',
    'Max Buy': 'maxBuy',
    'MaxBuy': 'maxBuy',
    'maxbuy': 'maxBuy',
    'margin': 'Margin',
    'fake risk': 'fakerisk',
    'Fake Risk': 'fakerisk',
    'FakeRisk': 'fakerisk',
    # TCG keys
    'tcg': 'TCG',
    'Tcg': 'TCG',
    'tcgbrand': 'TCG',
    'product type': 'ProductType',
    'producttype': 'ProductType',
    'Product Type': 'ProductType',
    'item count': 'ItemCount',
    'itemcount': 'ItemCount',
    'Item Count': 'ItemCount',
}

LEGO_DEFAULTS = {
    'Qualify': 'No',
    'SetNumber': 'Unknown',
    'SetName': 'Unknown',
    'Theme': 'Other',
    'Retired': 'Unknown',
    'SetCount': '1',
    'marketprice': 'Unknown',
    'maxBuy': 'NA',
    'Margin': 'NA',
    'confidence': 'Low',
    'fakerisk': 'Medium',
}

TCG_DEFAULTS = {
    'Qualify': 'No',
    'TCG': 'Unknown',
    'ProductType': 'Unknown',
    'SetName': 'Unknown',
    'ItemCount': '1',
    'marketprice': 'Unknown',
    'maxBuy': 'NA',
    'Margin': 'NA',
    'confidence': 'Low',
    'fakerisk': 'Medium',
}

# Allen Bradley defaults - must match exact column names for uBuyFirst
ALLEN_BRADLEY_DEFAULTS = {
    'Qualify': 'No',
    'Recommendation': 'RESEARCH',
    'ProductType': 'Unknown',
    'CatalogNumber': 'Unknown',
    'Series': 'Unknown',
    'Condition': 'Unknown',
    'Sealed': 'Unknown',
    'FirmwareVersion': 'Unknown',
    'marketprice': 'NA',
    'maxBuy': 'NA',
    'Profit': 'NA',
    'confidence': '50',
    'fakerisk': 'Medium',
    'reasoning': 'Analysis pending',
}

# Allen Bradley key mappings (AI may return wrong case)
ALLEN_BRADLEY_KEY_MAPPINGS = {
    'qualify': 'Qualify',
    'recommendation': 'Recommendation',
    'producttype': 'ProductType',
    'product_type': 'ProductType',
    'catalognumber': 'CatalogNumber',
    'catalog_number': 'CatalogNumber',
    'catalog': 'CatalogNumber',
    'partnumber': 'CatalogNumber',
    'part_number': 'CatalogNumber',
    'series': 'Series',
    'condition': 'Condition',
    'sealed': 'Sealed',
    'firmwareversion': 'FirmwareVersion',
    'firmware_version': 'FirmwareVersion',
    'firmware': 'FirmwareVersion',
    'marketprice': 'marketprice',
    'market_price': 'marketprice',
    'MarketPrice': 'marketprice',
    'maxbuy': 'maxBuy',
    'max_buy': 'maxBuy',
    'MaxBuy': 'maxBuy',
    'profit': 'Profit',
    'Margin': 'Profit',
    'margin': 'Profit',
    'confidence': 'confidence',
    'fakerisk': 'fakerisk',
    'fake_risk': 'fakerisk',
    'FakeRisk': 'fakerisk',
    'reasoning': 'reasoning',
}


def normalize_tcg_lego_keys(result: dict, category: str) -> dict:
    """
    Normalize AI response keys to match expected column names.
    GPT-4o-mini often returns wrong case/spacing.
    """
    normalized = {}
    for key, value in result.items():
        normalized_key = TCG_LEGO_KEY_MAPPINGS.get(key, key)
        normalized[normalized_key] = value

    # Get defaults based on category
    if category == 'lego':
        defaults = LEGO_DEFAULTS.copy()
        defaults['Recommendation'] = normalized.get('Recommendation', 'RESEARCH')
    elif category == 'tcg':
        defaults = TCG_DEFAULTS.copy()
        defaults['Recommendation'] = normalized.get('Recommendation', 'RESEARCH')
    else:
        defaults = {}

    # Apply defaults for missing keys
    for key, default_val in defaults.items():
        if key not in normalized or normalized[key] in (None, '', 'null'):
            normalized[key] = default_val

    return normalized


def normalize_allen_bradley_keys(result: dict) -> dict:
    """
    Normalize Allen Bradley AI response keys to match uBuyFirst column names.
    Ensures all required columns are present.

    Required columns: Qualify, Recommendation, ProductType, CatalogNumber, Series,
    Condition, Sealed, FirmwareVersion, marketprice, maxBuy, Profit, confidence,
    fakerisk, reasoning
    """
    normalized = {}

    # First pass: normalize key names
    for key, value in result.items():
        normalized_key = ALLEN_BRADLEY_KEY_MAPPINGS.get(key.lower() if isinstance(key, str) else key, key)
        normalized[normalized_key] = value

    # Second pass: apply defaults for missing keys
    for key, default_val in ALLEN_BRADLEY_DEFAULTS.items():
        if key not in normalized or normalized[key] in (None, '', 'null', 'NA', 'Unknown'):
            # Don't override if we have a real value
            if key not in normalized:
                normalized[key] = default_val

    # Ensure Recommendation is preserved
    if 'Recommendation' in result:
        normalized['Recommendation'] = result['Recommendation']

    logger.debug(f"[AB-NORM] Normalized Allen Bradley response: {list(normalized.keys())}")

    return normalized


# ============================================================
# PRICE/MARGIN CALCULATIONS
# ============================================================

def parse_price(price_str: Any) -> float:
    """
    Parse price from string or number.
    Handles formats like "$149.99", "149.99", 149.99
    Returns 0.0 on failure.
    """
    if price_str is None:
        return 0.0

    try:
        if isinstance(price_str, (int, float)):
            return float(price_str)

        cleaned = str(price_str).replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def calculate_margin(listing_price: float, market_price: float, threshold: float = 0.65) -> Tuple[float, float, str]:
    """
    Calculate margin, max buy, and margin string.

    Args:
        listing_price: Current listing price
        market_price: Market/resale value
        threshold: Buy threshold (e.g., 0.65 for 65%)

    Returns:
        (profit, max_buy, margin_str)
    """
    if market_price <= 0:
        return 0.0, 0.0, "N/A"

    max_buy = market_price * threshold
    profit = max_buy - listing_price

    if profit > 0:
        margin_str = f"+${profit:.0f}"
    else:
        margin_str = f"-${abs(profit):.0f}"

    return profit, max_buy, margin_str


def extract_margin_from_reasoning(reasoning: str) -> Optional[float]:
    """
    Extract margin/profit value from AI reasoning text.
    AI sometimes calculates correctly in reasoning but puts wrong value in Profit field.
    """
    if not reasoning:
        return None

    reasoning_lower = reasoning.lower()

    # Patterns to find margin in reasoning
    margin_patterns = [
        r'[=\s]\+?\$?(\d+(?:\.\d+)?)\s*margin',      # "= $101 margin"
        r'margin[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "margin: $101"
        r'profit[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "profit: $101"
        r'\+\$(\d+(?:\.\d+)?)\s*(?:margin|profit)',   # "+$101 margin"
    ]

    for pattern in margin_patterns:
        match = re.search(pattern, reasoning_lower)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue

    return None


# ============================================================
# CONDITION CHECKS
# ============================================================

# Import LEGO terms from centralized config
from config import LEGO_PASS_TERMS, LEGO_KNOCKOFF_TERMS


def check_lego_condition(title: str, reasoning: str = "") -> Tuple[bool, str]:
    """
    Check if LEGO listing passes condition requirements.

    Returns:
        (passes, reason) - passes=True if OK, reason explains failure
    """
    check_text = f"{title.lower()} {reasoning.lower()}"

    # Check for knockoffs first
    for term in LEGO_KNOCKOFF_TERMS:
        if term in check_text:
            return False, f"KNOCKOFF detected: '{term}'"

    # Check for condition issues
    for term in LEGO_PASS_TERMS:
        if term in check_text:
            # Special handling for bags terms
            if term in ['sealed bags', 'numbered bags', 'bags only']:
                if 'with box' not in check_text and 'box included' not in check_text:
                    return False, f"'{term}' without box"
            else:
                return False, f"'{term}' - not sealed/new"

    return True, ""


def check_professional_seller(username: str, category: str, keywords: Dict[str, list] = None) -> Tuple[bool, int]:
    """
    Check if seller appears to be a professional dealer.

    Returns:
        (is_professional, match_count)
    """
    if not username:
        return False, 0

    username_lower = username.lower()

    # Default keywords if not provided
    if keywords is None:
        keywords = {
            'gold': ['gold', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious', 'bullion'],
            'silver': ['silver', 'sterling', 'jewelry', 'jeweler', 'pawn', 'coin', 'precious'],
            'videogames': ['games', 'gaming', 'retro', 'vintage', 'collectibles', 'video', 'game'],
            'lego': ['lego', 'brick', 'building', 'toy', 'collectibles'],
            'tcg': ['card', 'cards', 'pokemon', 'tcg', 'trading', 'collectibles'],
        }

    category_keywords = keywords.get(category, [])
    match_count = sum(1 for kw in category_keywords if kw in username_lower)

    # 2+ keyword matches = likely professional
    return match_count >= 2, match_count


def is_valid_recommendation(rec: str) -> bool:
    """Check if recommendation is a valid value."""
    return rec in ('BUY', 'RESEARCH', 'PASS')


def normalize_recommendation(rec: str) -> str:
    """Normalize recommendation to standard format."""
    if not rec:
        return 'RESEARCH'

    rec_upper = str(rec).upper().strip()

    if rec_upper in ('BUY', 'YES', 'TRUE', '1'):
        return 'BUY'
    elif rec_upper in ('PASS', 'NO', 'FALSE', '0', 'SKIP'):
        return 'PASS'
    else:
        return 'RESEARCH'
