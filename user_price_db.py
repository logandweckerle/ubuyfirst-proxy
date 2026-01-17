"""
User Price Database - Stores user-provided market values for TCG, collectibles, etc.
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

PRICE_FILE = os.path.join(os.path.dirname(__file__), "user_prices.json")
DEFAULT_THRESHOLD = 0.70  # 70% of market value

_prices: Dict = {}
_loaded = False


def load_prices() -> Dict:
    """Load user prices from JSON file"""
    global _prices, _loaded

    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, 'r') as f:
                _prices = json.load(f)
            _loaded = True

            # Count items
            total = 0
            for category in _prices:
                if category == "meta":
                    continue
                for subcat in _prices[category]:
                    total += len(_prices[category][subcat])

            logger.info(f"[USER-PRICES] Loaded {total} items from user price database")
        except Exception as e:
            logger.error(f"[USER-PRICES] Error loading prices: {e}")
            _prices = {}
    else:
        _prices = {"tcg": {"pokemon": {}, "mtg": {}, "yugioh": {}}, "meta": {}}
        save_prices()

    return _prices


def save_prices() -> bool:
    """Save prices to JSON file"""
    global _prices

    try:
        _prices["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(PRICE_FILE, 'w') as f:
            json.dump(_prices, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[USER-PRICES] Error saving prices: {e}")
        return False


def add_price(category: str, subcategory: str, item_name: str, market_value: float, notes: str = "") -> bool:
    """Add or update a price entry"""
    global _prices

    if not _loaded:
        load_prices()

    if category not in _prices:
        _prices[category] = {}
    if subcategory not in _prices[category]:
        _prices[category][subcategory] = {}

    threshold = _prices.get("meta", {}).get("threshold", DEFAULT_THRESHOLD)

    _prices[category][subcategory][item_name] = {
        "market_value": market_value,
        "max_buy": round(market_value * threshold, 2),
        "added": datetime.now().strftime("%Y-%m-%d"),
        "notes": notes
    }

    logger.info(f"[USER-PRICES] Added: {item_name} = ${market_value} (max buy ${market_value * threshold:.2f})")
    return save_prices()


def lookup_price(title: str) -> Optional[Tuple[str, Dict]]:
    """
    Look up a title in the user price database.
    Returns (matched_name, price_data) or None if not found.

    Uses STRICT matching - requires set name keywords to match for TCG items.
    """
    global _prices

    if not _loaded:
        load_prices()

    title_lower = title.lower().replace('+', ' ')  # Handle URL encoding

    # Common generic words that don't identify the product
    GENERIC_WORDS = {
        'pokemon', 'tcg', 'scarlet', 'violet', 'elite', 'trainer', 'box', 'etb',
        'booster', 'sealed', 'new', 'factory', 'the', 'and', '&', 'of', 'a',
        'center', 'collection', 'premium', 'ultra', 'special'
    }

    for category in _prices:
        if category == "meta":
            continue
        for subcategory in _prices[category]:
            for item_name, data in _prices[category][subcategory].items():
                item_lower = item_name.lower()
                item_words = item_lower.split()

                # Identify SET NAME words (non-generic words that identify the product)
                set_name_words = [w for w in item_words if w not in GENERIC_WORDS and len(w) > 2]

                # STRICT: ALL set name words must appear in title
                if set_name_words:
                    set_name_match = all(word in title_lower for word in set_name_words)
                    if not set_name_match:
                        continue  # Set name doesn't match, skip

                # Also require generic word matches (at least 50% of item words)
                all_matches = sum(1 for word in item_words if word in title_lower and len(word) > 2)
                required = max(2, int(len(item_words) * 0.5))

                if all_matches >= required:
                    logger.info(f"[USER-PRICES] STRICT Match: '{item_name}' -> ${data['market_value']} (set words: {set_name_words})")
                    return (item_name, data)

    return None


def get_all_prices() -> Dict:
    """Get all stored prices"""
    if not _loaded:
        load_prices()
    return _prices


def get_stats() -> Dict:
    """Get price database statistics"""
    if not _loaded:
        load_prices()

    stats = {"total": 0, "categories": {}}

    for category in _prices:
        if category == "meta":
            continue
        cat_total = 0
        for subcategory in _prices[category]:
            count = len(_prices[category][subcategory])
            cat_total += count
            stats["categories"][f"{category}/{subcategory}"] = count
        stats["total"] += cat_total

    stats["last_updated"] = _prices.get("meta", {}).get("last_updated", "unknown")
    return stats


# Load on import
load_prices()
