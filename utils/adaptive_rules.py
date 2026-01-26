"""
Adaptive Rules - Learn from multiple signals to improve decisions.

Learns from:
1. training_overrides.jsonl - BUY→PASS corrections (what AI got wrong)
2. purchases.jsonl - Successful purchases (what patterns lead to profit)
3. item_tracking.db - Missed opportunities (items we passed that sold fast)

Outputs:
- PASS patterns: Skip these items (saves API costs)
- BUY boost patterns: Increase confidence on these (don't miss deals)
- RESEARCH patterns: Items that need closer look (frequently missed)

Usage:
    from utils.adaptive_rules import check_learned_pattern, get_buy_boost, reload_patterns

    # Check if a listing matches a learned PASS pattern
    result = check_learned_pattern(title, category, price)
    if result:
        return {"Recommendation": "PASS", "reasoning": result["reason"]}

    # Check if a listing matches a BUY boost pattern
    boost = get_buy_boost(title, category, price)
    if boost:
        # Increase confidence, lower threshold
        confidence += boost["confidence_boost"]
"""

import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Paths to data sources
TRAINING_LOG_PATH = Path(__file__).parent.parent / "training_overrides.jsonl"
PURCHASES_LOG_PATH = Path(__file__).parent.parent / "purchases.jsonl"
ITEM_TRACKING_DB = Path(__file__).parent.parent / "item_tracking.db"

# Minimum occurrences before creating a rule
MIN_PATTERN_COUNT = 3
MIN_BUY_PATTERN_COUNT = 2  # Lower threshold for BUY patterns (we want to catch deals)

# Pattern storage
_learned_patterns: Dict[str, List[Dict]] = {
    "pass_keywords": [],       # Keywords that trigger PASS
    "buy_boost_keywords": [],  # Keywords that boost BUY confidence
    "missed_keywords": [],     # Keywords from missed opportunities -> RESEARCH
    "category_rules": [],      # Category + price range rules
    "exact_phrases": [],       # Exact title phrases
}
_patterns_lock = threading.Lock()
_last_reload = None
_stats = {
    "checks": 0,
    "pass_matches": 0,
    "buy_boosts": 0,
    "patterns_loaded": 0,
    "pass_rules": 0,
    "buy_rules": 0,
    "missed_rules": 0,
}


def extract_keywords(title: str) -> List[str]:
    """Extract meaningful keywords from title for pattern matching."""
    # Decode URL encoding
    title = title.replace('+', ' ').lower()

    # Remove common noise words AND category words (too generic to be useful patterns)
    noise = {'the', 'a', 'an', 'and', 'or', 'of', 'for', 'with', 'in', 'on', 'at',
             'to', 'is', 'it', 'by', 'from', 'as', 'be', 'was', 'are', 'been',
             'lot', 'vintage', 'antique', 'rare', 'nice', 'great', 'good', 'new',
             'used', 'pre-owned', 'preowned', 'estate', 'beautiful', 'gorgeous',
             # Category words - too generic, would match everything
             'gold', 'silver', 'sterling', 'jewelry', 'necklace', 'bracelet',
             'ring', 'earring', 'earrings', 'pendant', 'chain', 'watch', 'coin',
             'bar', 'bullion', 'scrap', 'karat', 'solid', 'pure', 'fine',
             'yellow', 'white', 'rose', 'mens', 'womens', 'ladies',
             'pokemon', 'tcg', 'card', 'cards', 'game', 'video', 'nintendo',
             'playstation', 'xbox', 'lego', 'set', 'sealed', 'box', 'pack',
             'collection', 'complete', 'lot', 'knife', 'american', 'japanese'}

    # Extract words
    words = re.findall(r'\b[a-z]{3,}\b', title)
    keywords = [w for w in words if w not in noise]

    # Also extract 2-word phrases
    phrases = []
    words_list = title.split()
    for i in range(len(words_list) - 1):
        phrase = f"{words_list[i]} {words_list[i+1]}".lower()
        # Clean phrase
        phrase = re.sub(r'[^a-z\s]', '', phrase).strip()
        if len(phrase) > 5:
            phrases.append(phrase)

    return keywords + phrases


def analyze_training_data() -> Dict[str, List[Dict]]:
    """
    Analyze training_overrides.jsonl to find patterns.

    Looks for:
    1. Title keywords that consistently lead to BUY→PASS
    2. Category + price combinations that fail
    3. Exact phrases that indicate non-valuable items
    """
    if not TRAINING_LOG_PATH.exists():
        logger.warning("[ADAPTIVE] No training data found")
        return {"title_keywords": [], "category_rules": [], "exact_phrases": []}

    # Track patterns
    keyword_overrides = defaultdict(lambda: {"buy_to_pass": 0, "buy_to_research": 0, "total": 0, "examples": []})
    category_price_overrides = defaultdict(lambda: {"buy_to_pass": 0, "total": 0, "prices": []})
    phrase_overrides = defaultdict(lambda: {"count": 0, "examples": []})

    try:
        with open(TRAINING_LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line.strip())

                    override_type = record.get("override_type", "")
                    title = record.get("input", {}).get("title", "")
                    price = record.get("input", {}).get("price", 0)
                    category = record.get("input", {}).get("category", "")

                    # Only learn from BUY→PASS and BUY→RESEARCH (where AI was wrong)
                    if override_type not in ("BUY_TO_PASS", "BUY_TO_RESEARCH"):
                        continue

                    # Extract keywords
                    keywords = extract_keywords(title)

                    for kw in keywords:
                        keyword_overrides[kw]["total"] += 1
                        if override_type == "BUY_TO_PASS":
                            keyword_overrides[kw]["buy_to_pass"] += 1
                        elif override_type == "BUY_TO_RESEARCH":
                            keyword_overrides[kw]["buy_to_research"] += 1
                        keyword_overrides[kw]["examples"].append(title[:60])

                    # Track category + price range
                    if category and price:
                        price_bucket = int(price / 100) * 100  # Round to nearest $100
                        key = f"{category}_{price_bucket}"
                        category_price_overrides[key]["total"] += 1
                        if override_type == "BUY_TO_PASS":
                            category_price_overrides[key]["buy_to_pass"] += 1
                        category_price_overrides[key]["prices"].append(price)

                    # Track specific phrases that indicate problems
                    problem_phrases = [
                        "amber pendant", "baltic amber", "murano glass", "glass pendant",
                        "stone pendant", "crystal pendant", "pearl strand", "pearl necklace",
                        "costume jewelry", "fashion jewelry", "gold filled", "gold plated",
                        "gold tone", "smart watch", "apple watch", "fitbit"
                    ]
                    title_lower = title.replace('+', ' ').lower()
                    for phrase in problem_phrases:
                        if phrase in title_lower:
                            phrase_overrides[phrase]["count"] += 1
                            phrase_overrides[phrase]["examples"].append(title[:60])

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.debug(f"[ADAPTIVE] Error parsing record: {e}")
                    continue

        # Build rules from patterns
        rules = {
            "title_keywords": [],
            "category_rules": [],
            "exact_phrases": [],
        }

        # Keywords that consistently lead to PASS (>= MIN_PATTERN_COUNT occurrences, >70% PASS rate)
        # Only include specific/unique keywords (2+ words preferred, or known brand names)
        known_brands = {'benchmade', 'charizard', 'turquoise', 'invicta', 'stuhrling', 'murano'}
        # Blacklist generic phrases that are category identifiers, not problem indicators
        blacklist_phrases = {
            'sterling silver', 'yellow gold', 'white gold', 'rose gold', 'k gold', 'k yellow',
            'k white', 'solid gold', 'pure gold', 'pure silver', '925 silver', '925 sterling',
            'lot of', 'vintage k', 'gold ring', 'gold chain', 'gold bracelet', 'gold necklace',
            'silver ring', 'silver chain', 'silver bracelet', 'silver necklace',
            'pokemon tcg', 'booster box', 'collection box', 'trainer box', 'elite trainer',
            'factory sealed', 'new sealed', 'base set', 'complete', 'collection',
            'native american', 'pocket knife',
        }
        for kw, data in keyword_overrides.items():
            if data["total"] >= MIN_PATTERN_COUNT:
                # Skip blacklisted generic phrases
                if kw in blacklist_phrases:
                    continue
                pass_rate = data["buy_to_pass"] / data["total"] if data["total"] > 0 else 0
                if pass_rate >= 0.85:  # Higher threshold for safety
                    word_count = len(kw.split())
                    # Accept: multi-word phrases (2+ words), or known problematic brands
                    if word_count < 2 and kw not in known_brands:
                        continue  # Skip single words unless they're known problem brands
                    rules["title_keywords"].append({
                        "keyword": kw,
                        "pass_count": data["buy_to_pass"],
                        "total_count": data["total"],
                        "pass_rate": round(pass_rate, 2),
                        "action": "PASS",
                        "examples": data["examples"][:3],
                    })

        # Sort by pass_count (most frequent first)
        rules["title_keywords"].sort(key=lambda x: x["pass_count"], reverse=True)
        # Keep top 100 keywords
        rules["title_keywords"] = rules["title_keywords"][:100]

        # Category + price rules
        for key, data in category_price_overrides.items():
            if data["total"] >= MIN_PATTERN_COUNT:
                pass_rate = data["buy_to_pass"] / data["total"] if data["total"] > 0 else 0
                if pass_rate >= 0.8:  # Higher threshold for category rules
                    category, price_bucket = key.rsplit('_', 1)
                    rules["category_rules"].append({
                        "category": category,
                        "price_min": int(price_bucket),
                        "price_max": int(price_bucket) + 100,
                        "pass_count": data["buy_to_pass"],
                        "total_count": data["total"],
                        "action": "PASS",
                    })

        # Exact phrases (already known problem patterns)
        for phrase, data in phrase_overrides.items():
            if data["count"] >= 2:  # Lower threshold for known problem phrases
                rules["exact_phrases"].append({
                    "phrase": phrase,
                    "count": data["count"],
                    "action": "PASS",
                    "examples": data["examples"][:3],
                })

        logger.info(f"[ADAPTIVE] Analyzed {TRAINING_LOG_PATH}: "
                   f"{len(rules['title_keywords'])} keyword rules, "
                   f"{len(rules['category_rules'])} category rules, "
                   f"{len(rules['exact_phrases'])} phrase rules")

        return rules

    except Exception as e:
        logger.error(f"[ADAPTIVE] Error analyzing training data: {e}")
        return {"title_keywords": [], "category_rules": [], "exact_phrases": []}


def analyze_purchases() -> Dict[str, List[Dict]]:
    """
    Analyze purchases.jsonl to find patterns in successful buys.
    These patterns should BOOST confidence, not trigger auto-BUY.
    """
    if not PURCHASES_LOG_PATH.exists():
        logger.debug("[ADAPTIVE] No purchases log found")
        return {"buy_boost_keywords": []}

    keyword_profits = defaultdict(lambda: {"total_profit": 0, "count": 0, "examples": []})

    try:
        with open(PURCHASES_LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    listing = record.get("listing", {})
                    analysis = record.get("analysis", {})

                    title = listing.get("title", "")
                    price = listing.get("price", 0)
                    profit = analysis.get("profit", 0)
                    category = listing.get("category", "")

                    if not title or not profit:
                        continue

                    # Only learn from profitable purchases
                    if isinstance(profit, str):
                        profit = float(profit.replace('$', '').replace('+', '').replace(',', '') or 0)
                    if profit <= 0:
                        continue

                    keywords = extract_keywords(title)
                    for kw in keywords:
                        keyword_profits[kw]["total_profit"] += profit
                        keyword_profits[kw]["count"] += 1
                        keyword_profits[kw]["examples"].append({
                            "title": title[:50],
                            "profit": profit,
                            "category": category,
                        })

                except (json.JSONDecodeError, ValueError):
                    continue

        # Build BUY boost rules
        rules = {"buy_boost_keywords": []}

        for kw, data in keyword_profits.items():
            if data["count"] >= MIN_BUY_PATTERN_COUNT:
                avg_profit = data["total_profit"] / data["count"]
                if avg_profit >= 50:  # Only boost if avg profit >= $50
                    rules["buy_boost_keywords"].append({
                        "keyword": kw,
                        "count": data["count"],
                        "avg_profit": round(avg_profit, 2),
                        "total_profit": round(data["total_profit"], 2),
                        "action": "BOOST",
                        "confidence_boost": min(15, int(avg_profit / 20)),  # +5 to +15 confidence
                        "examples": data["examples"][:3],
                    })

        rules["buy_boost_keywords"].sort(key=lambda x: x["total_profit"], reverse=True)
        rules["buy_boost_keywords"] = rules["buy_boost_keywords"][:50]  # Top 50

        logger.info(f"[ADAPTIVE] Purchases: {len(rules['buy_boost_keywords'])} BUY boost patterns")
        return rules

    except Exception as e:
        logger.error(f"[ADAPTIVE] Error analyzing purchases: {e}")
        return {"buy_boost_keywords": []}


def analyze_missed_opportunities() -> Dict[str, List[Dict]]:
    """
    Analyze item_tracking.db for items we PASS'd that sold quickly.
    These patterns should trigger RESEARCH instead of auto-PASS.
    """
    if not ITEM_TRACKING_DB.exists():
        logger.debug("[ADAPTIVE] No item tracking database found")
        return {"missed_keywords": []}

    keyword_misses = defaultdict(lambda: {"count": 0, "avg_time_to_sell": 0, "examples": []})

    try:
        conn = sqlite3.connect(str(ITEM_TRACKING_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get items that sold fast (< 30 min) where we passed
        cursor.execute("""
            SELECT title, price, category, time_to_sell_minutes, recommendation
            FROM tracked_items
            WHERE is_fast_sale = 1
              AND recommendation IN ('PASS', 'pass')
              AND time_to_sell_minutes < 30
            ORDER BY first_seen DESC
            LIMIT 500
        """)

        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            title = row["title"] or ""
            price = row["price"] or 0
            category = row["category"] or ""
            time_to_sell = row["time_to_sell_minutes"] or 0

            keywords = extract_keywords(title)
            for kw in keywords:
                keyword_misses[kw]["count"] += 1
                keyword_misses[kw]["avg_time_to_sell"] += time_to_sell
                keyword_misses[kw]["examples"].append({
                    "title": title[:50],
                    "price": price,
                    "sold_in_min": time_to_sell,
                    "category": category,
                })

        # Build MISSED (RESEARCH) rules
        rules = {"missed_keywords": []}

        for kw, data in keyword_misses.items():
            if data["count"] >= MIN_PATTERN_COUNT:
                avg_time = data["avg_time_to_sell"] / data["count"] if data["count"] > 0 else 0
                rules["missed_keywords"].append({
                    "keyword": kw,
                    "missed_count": data["count"],
                    "avg_sell_time_min": round(avg_time, 1),
                    "action": "RESEARCH",
                    "reason": f"Missed {data['count']}x, avg sold in {avg_time:.0f}min",
                    "examples": data["examples"][:3],
                })

        rules["missed_keywords"].sort(key=lambda x: x["missed_count"], reverse=True)
        rules["missed_keywords"] = rules["missed_keywords"][:50]  # Top 50

        logger.info(f"[ADAPTIVE] Missed opportunities: {len(rules['missed_keywords'])} RESEARCH patterns")
        return rules

    except Exception as e:
        logger.error(f"[ADAPTIVE] Error analyzing missed opportunities: {e}")
        return {"missed_keywords": []}


def reload_patterns(force: bool = False) -> int:
    """
    Reload learned patterns from all data sources.

    Returns number of patterns loaded.
    """
    global _learned_patterns, _last_reload, _stats

    # Don't reload more than once per 5 minutes unless forced
    if not force and _last_reload:
        if datetime.now() - _last_reload < timedelta(minutes=5):
            return _stats["patterns_loaded"]

    with _patterns_lock:
        # Load from all sources
        pass_patterns = analyze_training_data()
        buy_patterns = analyze_purchases()
        missed_patterns = analyze_missed_opportunities()

        # Merge into unified pattern store
        _learned_patterns = {
            "pass_keywords": pass_patterns.get("title_keywords", []),
            "buy_boost_keywords": buy_patterns.get("buy_boost_keywords", []),
            "missed_keywords": missed_patterns.get("missed_keywords", []),
            "category_rules": pass_patterns.get("category_rules", []),
            "exact_phrases": pass_patterns.get("exact_phrases", []),
        }
        _last_reload = datetime.now()

        # Update stats
        _stats["pass_rules"] = len(_learned_patterns["pass_keywords"])
        _stats["buy_rules"] = len(_learned_patterns["buy_boost_keywords"])
        _stats["missed_rules"] = len(_learned_patterns["missed_keywords"])
        _stats["patterns_loaded"] = _stats["pass_rules"] + _stats["buy_rules"] + _stats["missed_rules"]

        logger.info(f"[ADAPTIVE] Loaded: {_stats['pass_rules']} PASS, "
                   f"{_stats['buy_rules']} BUY boost, {_stats['missed_rules']} MISSED patterns")

        return _stats["patterns_loaded"]


def check_learned_pattern(title: str, category: str = "", price: float = 0) -> Optional[Dict]:
    """
    Check if a listing matches a learned PASS pattern.

    Returns:
        Dict with 'action' and 'reason' if pattern matches, None otherwise.
    """
    global _stats

    _stats["checks"] += 1

    # Lazy load patterns on first call
    if _last_reload is None:
        reload_patterns()

    title_lower = title.replace('+', ' ').lower()

    with _patterns_lock:
        # Check exact phrases first (highest confidence)
        for rule in _learned_patterns.get("exact_phrases", []):
            if rule["phrase"] in title_lower:
                _stats["matches"] += 1
                logger.info(f"[ADAPTIVE] MATCH phrase '{rule['phrase']}' (seen {rule['count']}x) -> PASS")
                return {
                    "action": "PASS",
                    "reason": f"ADAPTIVE: '{rule['phrase']}' matched (overridden {rule['count']}x before)",
                    "pattern_type": "exact_phrase",
                    "pattern": rule["phrase"],
                }

        # Check PASS keywords
        title_keywords = set(extract_keywords(title))
        for rule in _learned_patterns.get("pass_keywords", []):
            if rule["keyword"] in title_keywords or rule["keyword"] in title_lower:
                # Require high pass rate for single keyword match
                if rule["pass_rate"] >= 0.85 and rule["pass_count"] >= 5:
                    _stats["pass_matches"] += 1
                    logger.info(f"[ADAPTIVE] MATCH keyword '{rule['keyword']}' "
                               f"({rule['pass_count']}/{rule['total_count']} = {rule['pass_rate']*100:.0f}% PASS) -> PASS")
                    return {
                        "action": "PASS",
                        "reason": f"ADAPTIVE: keyword '{rule['keyword']}' -> PASS {rule['pass_rate']*100:.0f}% of time ({rule['pass_count']} cases)",
                        "pattern_type": "keyword",
                        "pattern": rule["keyword"],
                    }

        # Category + price rules DISABLED - too broad, would PASS good deals
        # TODO: Re-enable with much higher thresholds or more specific conditions
        # if category and price:
        #     for rule in _learned_patterns.get("category_rules", []):
        #         if (rule["category"] == category and
        #             rule["price_min"] <= price < rule["price_max"]):
        #             _stats["matches"] += 1
        #             logger.info(f"[ADAPTIVE] MATCH category rule: {category} ${rule['price_min']}-${rule['price_max']} -> PASS")
        #             return {
        #                 "action": "PASS",
        #                 "reason": f"ADAPTIVE: {category} at ${price:.0f} matches PASS pattern ({rule['pass_count']} cases)",
        #                 "pattern_type": "category_price",
        #                 "pattern": f"{category}_{rule['price_min']}",
        #             }

    return None


def get_buy_boost(title: str, category: str = "", price: float = 0) -> Optional[Dict]:
    """
    Check if a listing matches a learned BUY boost pattern.

    Returns:
        Dict with 'confidence_boost' and 'reason' if pattern matches, None otherwise.
    """
    global _stats

    if _last_reload is None:
        reload_patterns()

    title_lower = title.replace('+', ' ').lower()
    title_keywords = set(extract_keywords(title))

    with _patterns_lock:
        for rule in _learned_patterns.get("buy_boost_keywords", []):
            if rule["keyword"] in title_keywords or rule["keyword"] in title_lower:
                _stats["buy_boosts"] += 1
                logger.info(f"[ADAPTIVE] BUY BOOST '{rule['keyword']}' "
                           f"(avg profit ${rule['avg_profit']:.0f}) -> +{rule['confidence_boost']} confidence")
                return {
                    "action": "BOOST",
                    "confidence_boost": rule["confidence_boost"],
                    "reason": f"ADAPTIVE: '{rule['keyword']}' profitable {rule['count']}x (avg ${rule['avg_profit']:.0f})",
                    "pattern_type": "buy_boost",
                    "pattern": rule["keyword"],
                }

    return None


def get_missed_alert(title: str, category: str = "", price: float = 0) -> Optional[Dict]:
    """
    Check if a listing matches a missed opportunity pattern.
    These items were PASS'd but sold quickly - should be RESEARCH.

    Returns:
        Dict with 'action': 'RESEARCH' if pattern matches, None otherwise.
    """
    if _last_reload is None:
        reload_patterns()

    title_lower = title.replace('+', ' ').lower()
    title_keywords = set(extract_keywords(title))

    with _patterns_lock:
        for rule in _learned_patterns.get("missed_keywords", []):
            if rule["keyword"] in title_keywords or rule["keyword"] in title_lower:
                if rule["missed_count"] >= 3:  # Only alert if missed 3+ times
                    logger.info(f"[ADAPTIVE] MISSED ALERT '{rule['keyword']}' "
                               f"(missed {rule['missed_count']}x, avg sold {rule['avg_sell_time_min']:.0f}min)")
                    return {
                        "action": "RESEARCH",
                        "reason": rule["reason"],
                        "pattern_type": "missed",
                        "pattern": rule["keyword"],
                    }

    return None


def get_adaptive_stats() -> Dict:
    """Get statistics about adaptive rule usage."""
    with _patterns_lock:
        return {
            "patterns_loaded": _stats["patterns_loaded"],
            "checks": _stats["checks"],
            "pass_matches": _stats.get("pass_matches", 0),
            "buy_boosts": _stats.get("buy_boosts", 0),
            "last_reload": _last_reload.isoformat() if _last_reload else None,
            "pass_rules": _stats.get("pass_rules", len(_learned_patterns.get("pass_keywords", []))),
            "buy_rules": _stats.get("buy_rules", len(_learned_patterns.get("buy_boost_keywords", []))),
            "missed_rules": _stats.get("missed_rules", len(_learned_patterns.get("missed_keywords", []))),
            "category_rules": len(_learned_patterns.get("category_rules", [])),
            "phrase_rules": len(_learned_patterns.get("exact_phrases", [])),
        }


def get_learned_rules() -> Dict:
    """Get all learned rules for debugging/display."""
    with _patterns_lock:
        return {
            "pass_keywords": _learned_patterns.get("pass_keywords", [])[:20],
            "buy_boost_keywords": _learned_patterns.get("buy_boost_keywords", [])[:20],
            "missed_keywords": _learned_patterns.get("missed_keywords", [])[:20],
            "category_rules": _learned_patterns.get("category_rules", []),
            "exact_phrases": _learned_patterns.get("exact_phrases", []),
        }


# Auto-load patterns on module import
try:
    reload_patterns()
except Exception as e:
    logger.warning(f"[ADAPTIVE] Could not load patterns on startup: {e}")
