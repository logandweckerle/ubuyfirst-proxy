"""
Tier 0: Rule-based Fast Filtering

Zero-cost filtering that catches obvious PASS cases before AI analysis.
This saves API costs and reduces latency.

Tier 0 checks:
1. Blocked sellers (spam detection)
2. User price database matches
3. Instant-pass keywords (plated, reproduction, etc.)
4. Category-specific agent quick_pass() rules
5. Price sanity checks

Returns:
- (None, None) to continue to Tier 1
- (reason, "PASS") to skip AI entirely
- (reason, "RESEARCH") to force manual review
- (reason, "BUY") for user price database matches
"""

import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class Tier0Filter:
    """Rule-based filtering before AI analysis"""

    # Keywords that indicate item has no resale value
    INSTANT_PASS_KEYWORDS = [
        "gold plated", "gold-plated", "goldplated",
        "silver plated", "silver-plated", "silverplated",
        "gold filled", "gold-filled", "goldfilled",
        "rolled gold", "gold tone", "goldtone",
        "silver tone", "silvertone",
        "costume jewelry", "fashion jewelry",
        "reproduction", "replica", "fake",
        "cz", "cubic zirconia",
        "single earring", "one earring",
    ]

    # Keywords that require manual research (not auto-buy)
    RESEARCH_KEYWORDS = [
        "untested", "unknown metal", "unmarked",
        "estate find", "as is", "sold as is",
    ]

    def __init__(self, blocked_sellers: set = None, user_prices_db=None):
        """
        Initialize Tier 0 filter.

        Args:
            blocked_sellers: Set of blocked seller usernames (lowercase)
            user_prices_db: User price database lookup function
        """
        self.blocked_sellers = blocked_sellers or set()
        self.user_prices_db = user_prices_db

    def filter(self, data: Dict[str, Any], category: str, agent=None) -> Tuple[Optional[str], Optional[str]]:
        """
        Run Tier 0 filtering on a listing.

        Args:
            data: Listing data dict with Title, TotalPrice, SellerName, etc.
            category: Detected category (gold, silver, watch, etc.)
            agent: Category agent instance (for quick_pass)

        Returns:
            (reason, recommendation) or (None, None) to continue
        """
        title = data.get("Title", "").lower().replace("+", " ")
        seller = data.get("SellerName", "").lower().strip()

        # Parse price
        try:
            price_str = str(data.get("TotalPrice", data.get("ItemPrice", "0")))
            price = float(price_str.replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            price = 0

        # 1. Blocked seller check
        if seller in self.blocked_sellers:
            logger.debug(f"[TIER0] Blocked seller: {seller}")
            return (f"Blocked seller: {seller}", "PASS")

        # 2. User price database check
        if self.user_prices_db:
            match = self.user_prices_db(title)
            if match:
                matched_name, price_data = match
                max_buy = price_data.get("max_buy", 0)
                market_value = price_data.get("market_value", 0)

                if price <= max_buy:
                    profit = market_value - price
                    logger.info(f"[TIER0] User price match BUY: {matched_name} @ ${price} (profit ${profit:.2f})")
                    return (f"USER_PRICE_MATCH: {matched_name}", "BUY")
                elif price <= market_value * 0.85:
                    logger.info(f"[TIER0] User price match RESEARCH: {matched_name} @ ${price}")
                    return (f"USER_PRICE_MATCH: {matched_name} - price above max buy", "RESEARCH")

        # 3. Instant-pass keywords
        for keyword in self.INSTANT_PASS_KEYWORDS:
            if keyword in title:
                logger.debug(f"[TIER0] Instant-pass keyword: {keyword}")
                return (f"Instant-pass keyword: {keyword}", "PASS")

        # 4. Research keywords
        for keyword in self.RESEARCH_KEYWORDS:
            if keyword in title:
                logger.debug(f"[TIER0] Research keyword: {keyword}")
                return (f"Needs manual verification: {keyword}", "RESEARCH")

        # 5. Agent-specific quick_pass
        if agent and hasattr(agent, 'quick_pass'):
            try:
                reason, rec = agent.quick_pass(data, price)
                if reason and rec:
                    logger.debug(f"[TIER0] Agent quick_pass: {reason} -> {rec}")
                    return (reason, rec)
            except Exception as e:
                logger.warning(f"[TIER0] Agent quick_pass error: {e}")

        # 6. Price sanity checks
        if price <= 0:
            return ("Invalid price", "PASS")
        if price > 50000:
            return (f"Price ${price:.0f} exceeds maximum - requires manual review", "RESEARCH")

        # Continue to Tier 1
        return (None, None)

    def add_blocked_seller(self, seller: str):
        """Add a seller to the blocked list"""
        self.blocked_sellers.add(seller.lower().strip())

    def is_blocked(self, seller: str) -> bool:
        """Check if a seller is blocked"""
        return seller.lower().strip() in self.blocked_sellers


# Singleton instance for easy import
_tier0_instance: Optional[Tier0Filter] = None


def get_tier0_filter() -> Tier0Filter:
    """Get the global Tier0Filter instance"""
    global _tier0_instance
    if _tier0_instance is None:
        _tier0_instance = Tier0Filter()
    return _tier0_instance


def init_tier0(blocked_sellers: set = None, user_prices_db=None) -> Tier0Filter:
    """Initialize the global Tier0Filter with dependencies"""
    global _tier0_instance
    _tier0_instance = Tier0Filter(blocked_sellers, user_prices_db)
    return _tier0_instance
