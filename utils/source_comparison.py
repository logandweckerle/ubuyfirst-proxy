"""
Source Comparison Logger - Compare Direct API vs uBuyFirst latency

Tracks when listings are received from each source and calculates
latency to determine which source delivers faster.

Usage:
    from utils.source_comparison import log_listing_received, get_comparison_stats

    # Log when a listing arrives
    log_listing_received(
        item_id="123456",
        source="ubf",  # or "direct"
        posted_time="1/8/2026 9:16:41 AM",
        title="14k Gold Ring"
    )

    # Get stats
    stats = get_comparison_stats()
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from dateutil import parser as dt_parser

logger = logging.getLogger("source_comparison")

# File to store comparison data
COMPARISON_LOG_FILE = Path(__file__).parent.parent / "source_comparison.jsonl"

# In-memory tracking for race detection (same item from both sources)
_recent_items: Dict[str, Dict] = {}  # item_id -> {source, received_at, posted_at, latency_ms}
_recent_items_lock = threading.Lock()
_RECENT_WINDOW_SEC = 300  # Track items for 5 minutes

# Stats counters
_stats = {
    "ubf": {"count": 0, "total_latency_ms": 0, "wins": 0},
    "direct": {"count": 0, "total_latency_ms": 0, "wins": 0},
    "races": [],  # Items seen from both sources
}
_stats_lock = threading.Lock()


def parse_posted_time(posted_time_str: str) -> Optional[datetime]:
    """Parse various posted time formats from eBay/uBuyFirst"""
    if not posted_time_str:
        return None

    try:
        # Check if it's an ISO format with timezone (from Browse API)
        # e.g., "2026-01-12T16:41:44+00:00" - don't mangle the timezone
        if 'T' in posted_time_str and ('+00:00' in posted_time_str or 'Z' in posted_time_str):
            return dt_parser.parse(posted_time_str)

        # Handle URL-encoded plus signs in uBuyFirst format
        # e.g., "1/12/2026+9:19:40+AM" -> "1/12/2026 9:19:40 AM"
        cleaned = posted_time_str.replace('+', ' ').strip()
        return dt_parser.parse(cleaned)
    except Exception as e:
        logger.debug(f"[SOURCE] Could not parse posted time '{posted_time_str}': {e}")
        return None


def log_listing_received(
    item_id: str,
    source: str,  # "ubf" or "direct"
    posted_time: str = "",
    title: str = "",
    price: float = 0,
    category: str = ""
) -> Dict:
    """
    Log when a listing is received from a source.

    Returns dict with latency info and whether this was a "race" (seen from both sources)
    """
    global _recent_items, _stats

    received_at = datetime.now()
    posted_dt = parse_posted_time(posted_time)

    # Calculate latency (how long after posting did we receive it)
    latency_ms = None
    if posted_dt:
        try:
            # Handle timezone-aware vs naive datetime comparison
            if posted_dt.tzinfo is not None:
                # posted_dt is timezone-aware (from Browse API), use UTC for comparison
                from datetime import timezone
                received_at_utc = datetime.now(timezone.utc)
                latency_ms = int((received_at_utc - posted_dt).total_seconds() * 1000)
            else:
                # Both naive (local time), compare directly
                latency_ms = int((received_at - posted_dt).total_seconds() * 1000)
        except Exception as e:
            logger.debug(f"[SOURCE] Latency calc error: {e}")
            latency_ms = None

    entry = {
        "item_id": item_id,
        "source": source,
        "received_at": received_at.isoformat(),
        "posted_time": posted_time,
        "posted_dt": posted_dt.isoformat() if posted_dt else None,
        "latency_ms": latency_ms,
        "title": title[:100] if title else "",
        "price": price,
        "category": category,
    }

    race_info = None

    with _recent_items_lock:
        # Clean old entries
        cutoff = received_at.timestamp() - _RECENT_WINDOW_SEC
        expired = [k for k, v in _recent_items.items()
                   if datetime.fromisoformat(v["received_at"]).timestamp() < cutoff]
        for k in expired:
            del _recent_items[k]

        # Check if we've seen this item from the OTHER source (race!)
        if item_id in _recent_items:
            other = _recent_items[item_id]
            if other["source"] != source:
                # RACE DETECTED - same item from both sources
                race_info = {
                    "item_id": item_id,
                    "title": title[:60],
                    "first_source": other["source"],
                    "first_received": other["received_at"],
                    "first_latency_ms": other["latency_ms"],
                    "second_source": source,
                    "second_received": entry["received_at"],
                    "second_latency_ms": latency_ms,
                    "winner": other["source"],  # First one wins
                    "advantage_ms": None,
                }

                # Calculate advantage
                first_dt = datetime.fromisoformat(other["received_at"])
                second_dt = received_at
                race_info["advantage_ms"] = int((second_dt - first_dt).total_seconds() * 1000)

                entry["race"] = race_info

                # Log the race
                logger.info(f"[RACE] {item_id[:12]} - Winner: {race_info['winner'].upper()} "
                           f"(+{race_info['advantage_ms']}ms) - {title[:40]}")

        # Store this entry
        _recent_items[item_id] = entry

    # Update stats
    with _stats_lock:
        if source in _stats:
            _stats[source]["count"] += 1
            if latency_ms is not None:
                _stats[source]["total_latency_ms"] += latency_ms
            if race_info and race_info["winner"] == source:
                _stats[source]["wins"] += 1

        if race_info:
            _stats["races"].append(race_info)
            # Keep only last 100 races
            _stats["races"] = _stats["races"][-100:]

    # Write to log file
    try:
        with open(COMPARISON_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"[SOURCE] Failed to write to log: {e}")

    # Console log
    latency_str = f"{latency_ms}ms" if latency_ms else "unknown"
    logger.info(f"[SOURCE] {source.upper():6} | latency: {latency_str:>8} | {item_id[:12]} | {title[:40]}")

    return entry


def get_comparison_stats() -> Dict:
    """Get current comparison statistics"""
    with _stats_lock:
        stats = {
            "ubf": {
                "count": _stats["ubf"]["count"],
                "avg_latency_ms": (
                    _stats["ubf"]["total_latency_ms"] / _stats["ubf"]["count"]
                    if _stats["ubf"]["count"] > 0 else None
                ),
                "wins": _stats["ubf"]["wins"],
            },
            "direct": {
                "count": _stats["direct"]["count"],
                "avg_latency_ms": (
                    _stats["direct"]["total_latency_ms"] / _stats["direct"]["count"]
                    if _stats["direct"]["count"] > 0 else None
                ),
                "wins": _stats["direct"]["wins"],
            },
            "total_races": len(_stats["races"]),
            "recent_races": _stats["races"][-10:],  # Last 10 races
        }

        # Determine overall winner
        if stats["ubf"]["wins"] > stats["direct"]["wins"]:
            stats["overall_winner"] = "ubf"
        elif stats["direct"]["wins"] > stats["ubf"]["wins"]:
            stats["overall_winner"] = "direct"
        else:
            stats["overall_winner"] = "tie"

        return stats


def get_race_log() -> List[Dict]:
    """Get all race events (items seen from both sources)"""
    with _stats_lock:
        return list(_stats["races"])


def reset_stats():
    """Reset all statistics (for testing)"""
    global _stats, _recent_items
    with _stats_lock:
        _stats = {
            "ubf": {"count": 0, "total_latency_ms": 0, "wins": 0},
            "direct": {"count": 0, "total_latency_ms": 0, "wins": 0},
            "races": [],
        }
    with _recent_items_lock:
        _recent_items.clear()
    logger.info("[SOURCE] Stats reset")


# ============================================================
# DIRECT API BUY WINS TRACKING
# ============================================================
# Log when Direct API finds a BUY before uBuyFirst

API_BUY_WINS_FILE = Path(__file__).parent.parent / "api_buy_wins.jsonl"
_api_buy_wins_lock = threading.Lock()

def log_api_buy_win(
    item_id: str,
    title: str,
    price: float,
    profit: float,
    category: str = "",
    race_advantage_ms: int = None,
    melt_value: float = None,
    weight: str = None
):
    """
    Log when Direct API finds a BUY before uBuyFirst.
    Called when:
    1. Item came from Direct API (source == 'ebay_api')
    2. Final recommendation is BUY
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "item_id": item_id,
        "title": title[:100] if title else "",
        "price": price,
        "profit": profit,
        "category": category,
        "race_advantage_ms": race_advantage_ms,
        "melt_value": melt_value,
        "weight": weight,
    }

    # Check if this item won a race against uBuyFirst
    with _recent_items_lock:
        if item_id in _recent_items:
            race_data = _recent_items[item_id]
            if race_data.get("first_source") == "direct":
                entry["beat_ubf"] = True
                entry["race_advantage_ms"] = race_data.get("advantage_ms")
            else:
                entry["beat_ubf"] = False
        else:
            # No race data - Direct API found it exclusively
            entry["beat_ubf"] = "exclusive"

    # Write to file
    with _api_buy_wins_lock:
        try:
            with open(API_BUY_WINS_FILE, 'a') as f:
                f.write(json.dumps(entry) + '\n')
            logger.info(f"[API WIN] BUY logged: ${profit:.0f} profit - {title[:50]}...")
        except Exception as e:
            logger.error(f"[API WIN] Could not log: {e}")

    return entry


def get_api_buy_wins(limit: int = 50) -> List[Dict]:
    """Get recent Direct API BUY wins"""
    wins = []
    if API_BUY_WINS_FILE.exists():
        try:
            with open(API_BUY_WINS_FILE, 'r') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        wins.append(json.loads(line.strip()))
                    except:
                        pass
        except Exception as e:
            logger.error(f"[API WIN] Could not read log: {e}")
    return wins


def get_api_buy_wins_stats() -> Dict:
    """Get summary stats for Direct API BUY wins"""
    wins = get_api_buy_wins(limit=1000)

    total_profit = sum(w.get('profit', 0) for w in wins)
    beat_ubf_count = sum(1 for w in wins if w.get('beat_ubf') == True)
    exclusive_count = sum(1 for w in wins if w.get('beat_ubf') == 'exclusive')

    return {
        "total_wins": len(wins),
        "total_profit": total_profit,
        "beat_ubf": beat_ubf_count,
        "exclusive_finds": exclusive_count,
        "recent": wins[-10:] if wins else []
    }
