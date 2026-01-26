"""
Seller Spam Detection Module

Tracks seller appearances and auto-blocks spammers who list multiple items rapidly.
"""

import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

from .constants import SELLER_SPAM_WINDOW, SELLER_SPAM_THRESHOLD

logger = logging.getLogger(__name__)

# File path for persistent storage
BLOCKED_SELLERS_FILE = Path(__file__).parent.parent / "blocked_sellers.json"

# Runtime state
SELLER_APPEARANCES: Dict[str, List[float]] = {}
BLOCKED_SELLERS: set = set()


def load_blocked_sellers() -> set:
    """Load blocked sellers from file."""
    if BLOCKED_SELLERS_FILE.exists():
        try:
            with open(BLOCKED_SELLERS_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get('sellers', []))
        except Exception as e:
            logger.error(f"Failed to load blocked sellers: {e}")
    return set()


def save_blocked_sellers(sellers: set):
    """Save blocked sellers to file."""
    try:
        with open(BLOCKED_SELLERS_FILE, 'w') as f:
            json.dump({
                'sellers': list(sellers),
                'updated': datetime.now().isoformat(),
                'count': len(sellers)
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save blocked sellers: {e}")


def check_seller_spam(seller_name: str) -> Tuple[bool, bool]:
    """
    Check if seller is a spammer. Returns (is_blocked, newly_blocked).
    - is_blocked: True if seller is on the block list
    - newly_blocked: True if seller was just added to block list this call
    """
    global BLOCKED_SELLERS

    if not seller_name:
        return False, False

    seller_key = seller_name.lower().strip()

    # Check if already blocked
    if seller_key in BLOCKED_SELLERS:
        return True, False

    # Track this appearance
    now = time.time()
    if seller_key not in SELLER_APPEARANCES:
        SELLER_APPEARANCES[seller_key] = []

    # Clean old appearances outside window
    SELLER_APPEARANCES[seller_key] = [
        t for t in SELLER_APPEARANCES[seller_key]
        if now - t < SELLER_SPAM_WINDOW
    ]

    # Add current appearance
    SELLER_APPEARANCES[seller_key].append(now)

    # Check if spam threshold exceeded
    if len(SELLER_APPEARANCES[seller_key]) >= SELLER_SPAM_THRESHOLD:
        # Block this seller
        BLOCKED_SELLERS.add(seller_key)
        save_blocked_sellers(BLOCKED_SELLERS)
        logger.warning(f"[SPAM] BLOCKED seller '{seller_name}' - {len(SELLER_APPEARANCES[seller_key])} listings in {SELLER_SPAM_WINDOW}s")
        return True, True

    return False, False


def add_blocked_seller(seller_name: str) -> bool:
    """Manually add a seller to the block list."""
    global BLOCKED_SELLERS
    seller_key = seller_name.lower().strip()
    if seller_key in BLOCKED_SELLERS:
        return False
    BLOCKED_SELLERS.add(seller_key)
    save_blocked_sellers(BLOCKED_SELLERS)
    logger.info(f"[BLOCKED] Manually added seller: {seller_name}")
    return True


def remove_blocked_seller(seller_name: str) -> bool:
    """Remove a seller from the block list."""
    global BLOCKED_SELLERS
    seller_key = seller_name.lower().strip()
    if seller_key not in BLOCKED_SELLERS:
        return False
    BLOCKED_SELLERS.discard(seller_key)
    save_blocked_sellers(BLOCKED_SELLERS)
    logger.info(f"[BLOCKED] Removed seller from block list: {seller_name}")
    return True


def clear_blocked_sellers() -> int:
    """Clear all blocked sellers. Returns count of removed sellers."""
    global BLOCKED_SELLERS
    count = len(BLOCKED_SELLERS)
    BLOCKED_SELLERS.clear()
    save_blocked_sellers(BLOCKED_SELLERS)
    logger.warning(f"[BLOCKED] Cleared all {count} blocked sellers")
    return count


def import_blocked_sellers(sellers: List[str]) -> Tuple[int, int]:
    """Import multiple sellers. Returns (added, skipped)."""
    global BLOCKED_SELLERS
    added = 0
    skipped = 0
    for seller in sellers:
        seller_key = str(seller).lower().strip()
        if seller_key and seller_key not in BLOCKED_SELLERS:
            BLOCKED_SELLERS.add(seller_key)
            added += 1
        else:
            skipped += 1
    save_blocked_sellers(BLOCKED_SELLERS)
    logger.info(f"[BLOCKED] Imported {added} sellers ({skipped} already blocked)")
    return added, skipped


def get_blocked_sellers() -> set:
    """Get the current set of blocked sellers."""
    return BLOCKED_SELLERS.copy()


def get_blocked_count() -> int:
    """Get count of blocked sellers."""
    return len(BLOCKED_SELLERS)


# ============================================================
# PROFESSIONAL SELLER DETECTION
# ============================================================
# Category-specific keywords that indicate professional dealers
# These sellers know pricing and rarely have arbitrage opportunities

PROFESSIONAL_SELLER_KEYWORDS = {
    'tcg': [
        'cards', 'card', 'tcg', 'poke', 'pokemon', 'collectible', 'graded',
        'slab', 'psa', 'bgs', 'cgc', 'trading', 'hobby', 'sportscards',
        'cardshop', 'cardstore', 'pokemart', 'pokeshop', 'mtg', 'magic',
        'yugioh', 'lorcana', 'breaks', 'rips'
    ],
    'gold': [
        'jewelry', 'jewel', 'jeweler', 'gold', 'silver', 'pawn', 'coin',
        'precious', 'metal', 'bullion', 'estate', 'antique', 'vintage',
        'gems', 'diamond', 'karat', 'carat', 'scrap', 'refinery', 'refiner'
    ],
    'silver': [
        'jewelry', 'jewel', 'jeweler', 'gold', 'silver', 'pawn', 'coin',
        'precious', 'metal', 'bullion', 'estate', 'antique', 'vintage',
        'sterling', 'flatware', 'silverware', 'scrap', 'refinery', 'refiner'
    ],
    'watch': [
        'watch', 'watches', 'time', 'timepiece', 'horology', 'chrono',
        'rolex', 'omega', 'seiko', 'vintage', 'wristwatch', 'dial',
        'horologist', 'watchmaker', 'watchshop', 'luxurywatch'
    ],
    'lego': [
        'brick', 'bricks', 'lego', 'minifig', 'minifigure', 'blocks',
        'buildingblocks', 'legostore', 'bricklink', 'afol'
    ],
    'videogames': [
        'games', 'gaming', 'retro', 'videogame', 'nintendo', 'playstation',
        'xbox', 'sega', 'gamestop', 'gamestore', 'retrogaming', 'arcade',
        'collector', 'gameroom', 'gamer'
    ]
}

# High feedback threshold - sellers above this are likely professionals
HIGH_FEEDBACK_THRESHOLD = 1000


def check_professional_seller(seller_name: str, category: str, feedback_count: int = 0) -> Tuple[bool, str]:
    """
    Check if seller appears to be a professional dealer in this category.

    Returns (is_professional, reason)
    - is_professional: True if seller name contains category keywords
    - reason: Description of why flagged
    """
    if not seller_name:
        return False, ""

    seller_lower = seller_name.lower().strip()
    category_lower = category.lower() if category else ""

    # Get keywords for this category (and related categories)
    keywords = set()

    # Map categories to keyword sets
    category_map = {
        'tcg': ['tcg'],
        'pokemon': ['tcg'],
        'gold': ['gold', 'silver'],  # Gold sellers often sell silver too
        'silver': ['gold', 'silver'],
        'watch': ['watch'],
        'lego': ['lego'],
        'videogames': ['videogames'],
    }

    for cat_key in category_map.get(category_lower, [category_lower]):
        if cat_key in PROFESSIONAL_SELLER_KEYWORDS:
            keywords.update(PROFESSIONAL_SELLER_KEYWORDS[cat_key])

    # Check seller name against keywords
    matched_keywords = []
    for keyword in keywords:
        if keyword in seller_lower:
            matched_keywords.append(keyword)

    if matched_keywords:
        reason = f"Seller '{seller_name}' has category keywords: {', '.join(matched_keywords)}"

        # Extra strong signal if also high feedback
        if feedback_count >= HIGH_FEEDBACK_THRESHOLD:
            reason += f" + high feedback ({feedback_count})"
            return True, reason
        elif feedback_count >= 500:
            # Medium feedback + keywords = still professional
            reason += f" + {feedback_count} feedback"
            return True, reason
        else:
            # Keywords alone with low feedback - still flag but note it
            return True, reason

    # High feedback alone (without keywords) is suspicious but not definitive
    if feedback_count >= HIGH_FEEDBACK_THRESHOLD:
        return False, f"High feedback ({feedback_count}) but no category keywords"

    return False, ""


# Initialize on module load
BLOCKED_SELLERS = load_blocked_sellers()
