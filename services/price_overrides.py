"""
Manual price override system.

Allows user-maintained market prices for items where automated
lookups (PriceCharting, etc.) are insufficient or incorrect.
Supports TCG abbreviation expansion for product matching.
"""

import json
import logging
from typing import Optional
from pathlib import Path

from config import PRICE_OVERRIDES_PATH

logger = logging.getLogger(__name__)

# Module-level storage for loaded overrides
PRICE_OVERRIDES: dict = {}

# TCG abbreviation expansions
TCG_EXPANSIONS = {
    'etb': ['etb', 'elite trainer box'],
    'bb': ['bb', 'booster box'],
    'upc': ['upc', 'ultra premium collection'],
    'pc': ['pc', 'premium collection'],
}


def load_price_overrides():
    """Load manual price overrides from JSON file."""
    global PRICE_OVERRIDES
    try:
        if PRICE_OVERRIDES_PATH.exists():
            with open(PRICE_OVERRIDES_PATH, 'r') as f:
                PRICE_OVERRIDES = json.load(f)
            product_count = sum(
                len(v) for k, v in PRICE_OVERRIDES.items()
                if isinstance(v, dict) and not k.startswith('_')
            )
            logger.info(f"[OVERRIDES] Loaded price overrides: {product_count} products")
    except Exception as e:
        logger.error(f"[OVERRIDES] Failed to load: {e}")
        PRICE_OVERRIDES = {}


def _term_matches(term: str, text: str) -> bool:
    """Check if a term matches text, handling TCG abbreviation expansion."""
    if term in TCG_EXPANSIONS:
        return any(exp in text for exp in TCG_EXPANSIONS[term])
    return term in text


def check_price_override(title: str, category: str) -> Optional[dict]:
    """
    Check if title matches a price override.

    Returns override dict with market_price, notes, category if matched.
    Returns None if no match found.
    """
    if not PRICE_OVERRIDES or not title:
        return None

    title_lower = title.lower()

    # Map category to override keys
    category_keys = {
        'tcg': ['pokemon', 'mtg', 'yugioh', 'onepiece'],
        'lego': ['lego'],
        'videogames': ['videogames'],
    }

    keys_to_check = category_keys.get(category, [])

    for key in keys_to_check:
        if key not in PRICE_OVERRIDES:
            continue
        overrides = PRICE_OVERRIDES[key]
        if not isinstance(overrides, dict):
            continue

        for product_key, override_data in overrides.items():
            if product_key.startswith('_'):
                continue
            if not isinstance(override_data, dict):
                continue

            # Convert product key to search terms
            search_terms = product_key.replace('_', ' ').split()

            # Check if ALL terms appear in title (with abbreviation expansion)
            if all(_term_matches(term, title_lower) for term in search_terms):
                logger.info(f"[OVERRIDE] Matched '{product_key}' -> ${override_data.get('market_price', 0)}")
                return {
                    'product_key': product_key,
                    'market_price': override_data.get('market_price', 0),
                    'notes': override_data.get('notes', ''),
                    'category': key
                }

    return None


# Load overrides at import time
load_price_overrides()
