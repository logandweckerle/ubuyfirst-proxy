"""
Listing deduplication service.

Prevents re-analyzing the same listing within a configurable time window.
Tracks recently evaluated items by normalized title + price key.
"""

import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# In-memory cache of recently evaluated items
RECENTLY_EVALUATED: Dict[str, Dict] = {}
RECENTLY_EVALUATED_WINDOW = 600  # 10 minutes


def get_evaluated_item_key(title: str, price) -> str:
    """Create a unique key for an item based on title and price."""
    normalized = title[:80].lower().strip().replace('+', ' ').replace('%20', ' ')
    try:
        price_float = float(str(price).replace('$', '').replace(',', '').strip())
    except (ValueError, TypeError):
        price_float = 0.0
    return f"{normalized}_{price_float:.2f}"


def check_recently_evaluated(title: str, price) -> Optional[Dict]:
    """
    Check if item was recently evaluated.
    Returns cached result if found within the dedup window, None otherwise.
    """
    current_time = time.time()
    item_key = get_evaluated_item_key(title, price)

    # Clean expired entries
    expired = [k for k, v in RECENTLY_EVALUATED.items()
               if current_time - v['timestamp'] > RECENTLY_EVALUATED_WINDOW]
    for k in expired:
        del RECENTLY_EVALUATED[k]

    # Check if this item was recently evaluated
    if item_key in RECENTLY_EVALUATED:
        cached = RECENTLY_EVALUATED[item_key]
        age = current_time - cached['timestamp']
        logger.info(f"[DEDUP] Found recent evaluation ({age:.0f}s ago): {title[:40]}...")
        return cached['result']

    return None


def mark_as_evaluated(title: str, price, result: Dict):
    """Mark an item as evaluated with its result."""
    item_key = get_evaluated_item_key(title, price)
    RECENTLY_EVALUATED[item_key] = {
        'timestamp': time.time(),
        'result': result
    }
