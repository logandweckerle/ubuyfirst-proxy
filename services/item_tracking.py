"""
Item Tracking System for ClaudeProxyV3

Tracks items as they come through the proxy and monitors for sold status
to identify fast-selling patterns (items that sell within minutes of listing).

This data is valuable for:
- Identifying high-demand item categories
- Understanding what sells fast (potential goldmine patterns)
- Improving buying decisions based on historical velocity
"""

import sqlite3
import asyncio
import aiohttp
import hashlib
import logging
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent / "item_tracking.db"

# eBay API config (will be set from main.py)
_ebay_app_id: Optional[str] = None
_ebay_access_token: Optional[str] = None
_get_ebay_token: Optional[callable] = None


@dataclass
class TrackedItem:
    """Represents a tracked item"""
    item_id: str
    title: str
    price: float
    category: str
    alias: str
    seller_name: str
    posted_time: str  # ISO format from eBay
    first_seen: str   # ISO format when we first saw it
    sold_time: Optional[str] = None  # ISO format when sold detected
    time_to_sell_minutes: Optional[float] = None
    is_fast_sale: bool = False  # Sold in < 5 minutes
    recommendation: Optional[str] = None  # BUY/PASS/RESEARCH
    check_count: int = 0  # How many times we've checked this item
    last_checked: Optional[str] = None
    status: str = "active"  # active, sold, ended, error


def init_database():
    """Initialize the SQLite database for item tracking"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_items (
            item_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT,
            alias TEXT,
            seller_name TEXT,
            posted_time TEXT,
            first_seen TEXT NOT NULL,
            sold_time TEXT,
            time_to_sell_minutes REAL,
            is_fast_sale BOOLEAN DEFAULT 0,
            recommendation TEXT,
            check_count INTEGER DEFAULT 0,
            last_checked TEXT,
            status TEXT DEFAULT 'active',
            ebay_item_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Add ebay_item_id column if not exists (for existing databases)
    try:
        cursor.execute("ALTER TABLE tracked_items ADD COLUMN ebay_item_id TEXT")
        logger.info("[TRACKING] Added ebay_item_id column to existing database")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add analysis_result_json column to store full analysis for MISSED opportunity logging
    try:
        cursor.execute("ALTER TABLE tracked_items ADD COLUMN analysis_result_json TEXT")
        logger.info("[TRACKING] Added analysis_result_json column to existing database")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add original_data_json column to store original request data
    try:
        cursor.execute("ALTER TABLE tracked_items ADD COLUMN original_data_json TEXT")
        logger.info("[TRACKING] Added original_data_json column to existing database")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Index for fast queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status ON tracked_items(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_fast_sale ON tracked_items(is_fast_sale)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_category ON tracked_items(category)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_first_seen ON tracked_items(first_seen)
    """)

    # Learning patterns table - stores BUY/PASS/RESEARCH decisions for pattern learning
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,  -- BUY, PASS, RESEARCH, MISSED
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            seller_name TEXT,
            seller_type TEXT,  -- estate, thrift, individual, dealer, etc.

            -- Extracted features
            weight_grams REAL,
            weight_source TEXT,  -- stated, scale, estimated
            karat TEXT,
            melt_value REAL,
            max_buy REAL,
            profit REAL,

            -- AI analysis
            reasoning TEXT,
            confidence INTEGER,

            -- Validation
            ebay_item_id TEXT,
            sold_quickly BOOLEAN,  -- Did it sell within 30 min? (validates our decision)
            validated_at TEXT,

            -- Item Specifics (from eBay)
            metal TEXT,  -- e.g., "Gold", "Sterling Silver"
            metal_purity TEXT,  -- e.g., "14K", "18K", ".925"
            fineness TEXT,  -- e.g., "585", "750", "999"
            main_stone TEXT,  -- e.g., "Diamond", "Ruby"
            total_carat_weight TEXT,  -- e.g., "0.50 ctw"
            item_specifics_json TEXT,  -- Full item_specifics as JSON for analysis

            -- Metadata
            notes TEXT,  -- Manual notes for learning
            alias TEXT,  -- uBuyFirst alias that triggered this
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_patterns_type ON learning_patterns(pattern_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_patterns_category ON learning_patterns(category)
    """)

    # Seller signals table - tracks seller behavior patterns
    # Helps identify collection dumpers, quick-offer-accepters, estate sellers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seller_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_name TEXT NOT NULL,
            signal_type TEXT NOT NULL,  -- collection_dump, quick_offer, estate_sale, etc.

            -- Listing patterns
            listings_in_window INTEGER DEFAULT 0,  -- How many listings in short time
            window_minutes INTEGER DEFAULT 60,     -- Time window for listings
            categories_listed TEXT,                -- JSON list of categories they list in
            avg_price REAL,                        -- Average listing price
            price_range TEXT,                      -- e.g., "$50-500"

            -- Sale patterns
            fast_sales INTEGER DEFAULT 0,          -- How many sold in <5 min
            total_sales_tracked INTEGER DEFAULT 0,
            avg_time_to_sell REAL,                 -- Average minutes to sell
            best_offer_accepted INTEGER DEFAULT 0, -- Times they accepted best offer

            -- Seller profile
            feedback_score INTEGER,
            has_store INTEGER DEFAULT 0,
            account_type TEXT,                     -- individual, business
            seller_notes TEXT,                     -- Manual notes

            -- Timing
            first_seen TEXT,
            last_seen TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_seller_signals_name ON seller_signals(seller_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_seller_signals_type ON seller_signals(signal_type)
    """)

    conn.commit()
    conn.close()
    logger.info(f"[TRACKING] Database initialized at {DB_PATH}")


def extract_item_id_from_url(url: str) -> Optional[str]:
    """Extract eBay item ID from various URL formats"""
    if not url:
        return None

    # Pattern 1: /itm/123456789
    match = re.search(r'/itm/(\d+)', url)
    if match:
        return match.group(1)

    # Pattern 2: item=123456789 or itemId=123456789
    match = re.search(r'[?&]item[Ii]?d?=(\d+)', url)
    if match:
        return match.group(1)

    # Pattern 3: customid=123456789 (sometimes contains item ID)
    match = re.search(r'customid=(\d{10,})', url)
    if match:
        return match.group(1)

    return None


def _parse_price_value(price_value) -> float:
    """Parse price from various formats (string like '$159' or float)"""
    if isinstance(price_value, (int, float)):
        return float(price_value)
    if isinstance(price_value, str):
        # Remove $ and any other non-numeric chars except .
        clean = ''.join(c for c in price_value if c.isdigit() or c == '.')
        if clean:
            return float(clean)
    return 0.0


def track_item(
    item_id: str,
    title: str,
    price: float,
    category: str = "",
    alias: str = "",
    seller_name: str = "",
    posted_time: str = "",
    recommendation: str = "",
    original_data: Dict[str, Any] = None
) -> bool:
    """
    Track a new item. Returns True if item was newly added, False if already existed.
    GAP FIX #4: Generates hash-based ID if item_id extraction failed.

    Now also stores original_data_json for learning from missed opportunities.
    """
    import json as json_lib

    # GAP FIX: Generate hash-based ID if item_id is missing
    if not item_id:
        tracking_key = f"{title}|{price}"
        item_id = "hash_" + hashlib.md5(tracking_key.encode()).hexdigest()[:12]
        logger.debug(f"[TRACKING] Generated hash-based ID: {item_id}")

    # Ensure price is a float
    price_float = _parse_price_value(price)

    # Serialize original data for storage
    original_data_json = None
    if original_data:
        try:
            # Clean data - remove very large fields and API keys
            clean_data = {k: v for k, v in original_data.items()
                         if k not in ('llm_api_key', 'api_key', 'Images')
                         and not (isinstance(v, str) and len(v) > 10000)}
            original_data_json = json_lib.dumps(clean_data)
        except Exception as e:
            logger.debug(f"[TRACKING] Could not serialize original_data: {e}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if item already exists
    cursor.execute("SELECT item_id, original_data_json FROM tracked_items WHERE item_id = ?", (item_id,))
    existing = cursor.fetchone()
    if existing:
        # Update recommendation if provided
        updates = []
        params = []
        if recommendation:
            updates.append("recommendation = ?")
            params.append(recommendation)
        # Store original_data if not already present
        if original_data_json and not existing[1]:
            updates.append("original_data_json = ?")
            params.append(original_data_json)
        if updates:
            params.append(item_id)
            cursor.execute(
                f"UPDATE tracked_items SET {', '.join(updates)} WHERE item_id = ?",
                params
            )
            conn.commit()
        conn.close()
        return False

    # Insert new item with original_data_json
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO tracked_items
        (item_id, title, price, category, alias, seller_name, posted_time, first_seen, recommendation, original_data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (item_id, title, price_float, category, alias, seller_name, posted_time, now, recommendation, original_data_json))

    conn.commit()
    conn.close()

    logger.info(f"[TRACKING] New item tracked: {item_id} - {title[:50]} (data: {'YES' if original_data_json else 'NO'})")
    return True


async def track_item_with_resolution(
    item_id: str,
    title: str,
    price: float,
    category: str = "",
    alias: str = "",
    seller_name: str = "",
    posted_time: str = "",
    recommendation: str = "",
    original_data: Dict[str, Any] = None
) -> bool:
    """
    Track item AND schedule delayed resolution attempts.

    IMPORTANT: Brand new eBay listings may not be indexed in search yet.
    Items can sell within seconds, before eBay indexes them.

    Strategy: Schedule multiple resolution attempts with delays
    - 30 seconds: First attempt (gives time for indexing)
    - 60 seconds: Second attempt
    - 120 seconds: Third attempt
    """
    # First, track the item synchronously (now with original_data for learning)
    is_new = track_item(item_id, title, price, category, alias, seller_name, posted_time, recommendation, original_data)

    if not is_new:
        return False  # Already tracked

    # If we have a hash-based ID and seller name, schedule delayed resolution
    if (item_id.startswith('hash_') or item_id.startswith('ubf_')) and seller_name:
        # Schedule resolution attempts with delays (don't await - fire and forget)
        asyncio.create_task(_delayed_resolution(
            item_id, title, price, seller_name,
            delays=[30, 60, 120]  # Try at 30s, 60s, 120s
        ))
        logger.debug(f"[TRACKING] Scheduled delayed resolution for: {title[:40]}...")

    return True


async def _delayed_resolution(item_id: str, title: str, price: float, seller_name: str, delays: list):
    """
    Attempt resolution multiple times with delays.
    This accounts for eBay's indexing delay on new listings.
    """
    from urllib.parse import unquote

    clean_title = unquote(title.replace('+', ' '))
    clean_seller = unquote(seller_name.replace('+', ' '))
    price_float = _parse_price_value(price)

    for i, delay in enumerate(delays):
        # Wait before attempting
        await asyncio.sleep(delay)

        # Check if already resolved (another process might have done it)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT ebay_item_id FROM tracked_items WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            logger.debug(f"[TRACKING] Already resolved: {item_id}")
            return  # Already resolved, stop trying

        # Attempt resolution
        try:
            logger.info(f"[TRACKING] Delayed resolution attempt {i+1} ({delay}s) for: {clean_title[:35]}...")
            ebay_id = await resolve_ebay_item_id(clean_title, clean_seller, price_float)

            if ebay_id:
                update_ebay_item_id(item_id, ebay_id)
                logger.info(f"[TRACKING] DELAYED resolution SUCCESS after {delay}s: {item_id} -> {ebay_id}")
                return  # Success, stop trying
        except Exception as e:
            logger.debug(f"[TRACKING] Delayed resolution error: {e}")

    logger.debug(f"[TRACKING] All resolution attempts failed for: {clean_title[:40]}")


def update_item_recommendation(item_id: str, recommendation: str):
    """Update the recommendation for a tracked item"""
    if not item_id:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tracked_items SET recommendation = ? WHERE item_id = ?",
        (recommendation, item_id)
    )
    conn.commit()
    conn.close()


def store_analysis_result(item_id: str, result: Dict[str, Any], data: Dict[str, Any] = None):
    """
    Store the full analysis result for a tracked item.
    This allows us to capture complete profit/melt/weight data when logging MISSED opportunities.
    """
    import json as json_lib

    if not item_id:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        result_json = json_lib.dumps(result) if result else None
        data_json = json_lib.dumps(data) if data else None

        cursor.execute(
            """UPDATE tracked_items
               SET analysis_result_json = ?, original_data_json = ?, recommendation = ?
               WHERE item_id = ?""",
            (result_json, data_json, result.get('Recommendation', ''), item_id)
        )
        conn.commit()
        logger.debug(f"[TRACKING] Stored analysis result for {item_id}")
    except Exception as e:
        logger.warning(f"[TRACKING] Error storing analysis result: {e}")
    finally:
        conn.close()


def log_missed_opportunity(
    ebay_item_id: str,
    title: str,
    price: float,
    category: str = "",
    notes: str = "",
    recommendation: str = "PASS"
):
    """
    Manually log a missed opportunity (item we passed on that sold quickly).
    This helps train our agents to catch similar items in the future.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if already exists
    cursor.execute("SELECT item_id FROM tracked_items WHERE ebay_item_id = ?", (ebay_item_id,))
    if cursor.fetchone():
        conn.close()
        logger.info(f"[TRACKING] Item {ebay_item_id} already tracked")
        return False

    now = datetime.now().isoformat()
    item_id = f"missed_{ebay_item_id}"

    cursor.execute("""
        INSERT INTO tracked_items
        (item_id, ebay_item_id, title, price, category, recommendation,
         first_seen, sold_time, status, time_to_sell_minutes, is_fast_sale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sold', ?, 1)
    """, (item_id, ebay_item_id, title, price, category, f"MISSED:{recommendation}:{notes}",
          now, now, 0.0))

    conn.commit()
    conn.close()

    logger.warning(f"[TRACKING] MISSED OPPORTUNITY logged: {title[:50]} @ ${price}")
    return True


def log_pattern(
    pattern_type: str,  # BUY, PASS, RESEARCH
    category: str,
    title: str,
    price: float,
    result: Dict[str, Any],
    data: Dict[str, Any] = None,
    notes: str = ""
) -> bool:
    """
    Log a decision pattern for learning.

    This captures BUY/PASS/RESEARCH decisions with all relevant features
    so we can analyze patterns and improve agent accuracy.

    Especially useful for:
    - Newer categories (LEGO, TCG) where we're still learning
    - Edge cases where AI reasoning was interesting
    - Patterns we want to replicate or avoid
    """
    import json as json_lib

    if data is None:
        data = {}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Extract features from result
    weight_str = str(result.get('weight', result.get('goldweight', result.get('silverweight', '')))).replace('g', '').strip()
    try:
        weight_grams = float(weight_str) if weight_str and weight_str not in ['NA', 'None', '--', '0'] else None
    except:
        weight_grams = None

    weight_source = result.get('weightSource', result.get('weightsource', ''))
    karat = result.get('karat', '')

    melt_str = str(result.get('meltvalue', result.get('melt', ''))).replace('$', '').replace(',', '').strip()
    try:
        melt_value = float(melt_str) if melt_str and melt_str not in ['NA', 'None', '--'] else None
    except:
        melt_value = None

    max_buy_str = str(result.get('maxBuy', '')).replace('$', '').replace(',', '').strip()
    try:
        max_buy = float(max_buy_str) if max_buy_str and max_buy_str not in ['NA', 'None', '--'] else None
    except:
        max_buy = None

    profit_str = str(result.get('Profit', '')).replace('$', '').replace('+', '').replace(',', '').strip()
    try:
        profit = float(profit_str) if profit_str and profit_str not in ['NA', 'None', '--'] else None
    except:
        profit = None

    reasoning = result.get('reasoning', '')[:2000]  # Limit length
    confidence = result.get('confidence', 0)

    seller_name = data.get('sellerId', data.get('seller', data.get('SellerName', '')))
    seller_type = data.get('sellerType', '')
    alias = data.get('alias', data.get('Alias', ''))
    ebay_item_id = data.get('ebayItemId', data.get('itemId', data.get('ItemId', '')))

    # Extract item specifics from data (eBay item attributes)
    metal = data.get('Metal', '')
    metal_purity = data.get('MetalPurity', data.get('Metal Purity', ''))
    fineness = data.get('Fineness', '')
    main_stone = data.get('MainStone', data.get('Main Stone', ''))
    total_carat_weight = data.get('TotalCaratWeight', data.get('Total Carat Weight', ''))

    # Build item_specifics dict for JSON storage
    item_specifics = {
        'Metal': metal,
        'MetalPurity': metal_purity,
        'Fineness': fineness,
        'BaseMetal': data.get('BaseMetal', data.get('Base Metal', '')),
        'MainStone': main_stone,
        'MainStoneCreation': data.get('MainStoneCreation', data.get('Main Stone Creation', '')),
        'TotalCaratWeight': total_carat_weight,
        'SecondaryStone': data.get('SecondaryStone', data.get('Secondary Stone', '')),
        'Type': data.get('Type', ''),
        'Style': data.get('Style', ''),
        'RingSize': data.get('RingSize', data.get('Ring Size', '')),
        'ItemLength': data.get('ItemLength', data.get('Item Length', data.get('Length', ''))),
        'Antique': data.get('Antique', ''),
        'Vintage': data.get('Vintage', ''),
        'Brand': data.get('Brand', ''),
        'Designer': data.get('Designer', ''),
    }
    # Filter out empty values
    item_specifics = {k: v for k, v in item_specifics.items() if v}
    item_specifics_json = json_lib.dumps(item_specifics) if item_specifics else None

    cursor.execute("""
        INSERT INTO learning_patterns
        (pattern_type, category, title, price, seller_name, seller_type,
         weight_grams, weight_source, karat, melt_value, max_buy, profit,
         reasoning, confidence, ebay_item_id, alias, notes,
         metal, metal_purity, fineness, main_stone, total_carat_weight, item_specifics_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pattern_type, category, title[:500], price, seller_name, seller_type,
        weight_grams, weight_source, karat, melt_value, max_buy, profit,
        reasoning, confidence, ebay_item_id, alias, notes,
        metal, metal_purity, fineness, main_stone, total_carat_weight, item_specifics_json
    ))

    conn.commit()
    conn.close()

    logger.info(f"[PATTERN] Logged {pattern_type} pattern: {category} - {title[:40]}... @ ${price}")
    return True


def update_seller_signal(
    seller_name: str,
    category: str = "",
    price: float = 0,
    sold_quickly: bool = False,
    time_to_sell: float = None,
    feedback_score: int = None,
    has_store: bool = False,
    best_offer_accepted: bool = False
):
    """
    Track seller behavior patterns to identify:
    - Collection dumpers (multiple listings in short time)
    - Quick-offer-accepters (regularly accept best offers)
    - Estate sellers (selling across categories, varied prices)
    """
    import json as json_lib

    if not seller_name:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    now = datetime.now().isoformat()

    # Check if seller already exists
    cursor.execute("SELECT * FROM seller_signals WHERE seller_name = ?", (seller_name,))
    row = cursor.fetchone()

    if row:
        # Update existing seller
        cursor.execute("SELECT categories_listed FROM seller_signals WHERE seller_name = ?", (seller_name,))
        cat_row = cursor.fetchone()
        existing_cats = []
        if cat_row and cat_row[0]:
            try:
                existing_cats = json_lib.loads(cat_row[0])
            except:
                existing_cats = []

        if category and category not in existing_cats:
            existing_cats.append(category)

        # Calculate new averages
        cursor.execute("""
            UPDATE seller_signals SET
                listings_in_window = listings_in_window + 1,
                categories_listed = ?,
                fast_sales = fast_sales + ?,
                total_sales_tracked = total_sales_tracked + 1,
                best_offer_accepted = best_offer_accepted + ?,
                feedback_score = COALESCE(?, feedback_score),
                has_store = COALESCE(?, has_store),
                last_seen = ?,
                updated_at = ?
            WHERE seller_name = ?
        """, (
            json_lib.dumps(existing_cats),
            1 if sold_quickly else 0,
            1 if best_offer_accepted else 0,
            feedback_score,
            1 if has_store else None,
            now,
            now,
            seller_name
        ))

        # Determine signal type based on patterns
        cursor.execute("""
            SELECT listings_in_window, fast_sales, total_sales_tracked, categories_listed
            FROM seller_signals WHERE seller_name = ?
        """, (seller_name,))
        stats = cursor.fetchone()
        if stats:
            listings, fast, total, cats_json = stats
            cats = json_lib.loads(cats_json) if cats_json else []

            signal_type = "normal"
            if listings >= 5 and len(cats) >= 2:
                signal_type = "collection_dump"
            elif fast >= 3:
                signal_type = "hot_seller"
            elif len(cats) >= 3:
                signal_type = "estate_sale"

            cursor.execute(
                "UPDATE seller_signals SET signal_type = ? WHERE seller_name = ?",
                (signal_type, seller_name)
            )

    else:
        # Create new seller record
        cursor.execute("""
            INSERT INTO seller_signals
            (seller_name, signal_type, listings_in_window, categories_listed,
             avg_price, fast_sales, total_sales_tracked, feedback_score, has_store,
             first_seen, last_seen)
            VALUES (?, 'new', 1, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (
            seller_name,
            json_lib.dumps([category]) if category else "[]",
            price,
            1 if sold_quickly else 0,
            feedback_score,
            1 if has_store else 0,
            now,
            now
        ))

    conn.commit()
    conn.close()
    logger.debug(f"[SELLER] Updated signal for: {seller_name}")


def get_seller_signal(seller_name: str) -> Optional[Dict]:
    """Get seller signal data if exists."""
    if not seller_name:
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM seller_signals WHERE seller_name = ?", (seller_name,))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def get_hot_sellers(min_fast_sales: int = 2) -> List[Dict]:
    """Get sellers with multiple fast sales - potential collection dumpers."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM seller_signals
        WHERE fast_sales >= ?
        ORDER BY fast_sales DESC, listings_in_window DESC
        LIMIT 50
    """, (min_fast_sales,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_patterns_by_category(category: str, limit: int = 50) -> List[Dict]:
    """Get recent patterns for a category to analyze trends."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM learning_patterns
        WHERE category = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (category, limit))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_pattern_stats() -> Dict[str, Any]:
    """Get statistics about logged patterns."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    # Count by type
    cursor.execute("""
        SELECT pattern_type, COUNT(*) as count
        FROM learning_patterns
        GROUP BY pattern_type
    """)
    stats['by_type'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Count by category
    cursor.execute("""
        SELECT category, pattern_type, COUNT(*) as count
        FROM learning_patterns
        GROUP BY category, pattern_type
        ORDER BY category, pattern_type
    """)
    by_category = {}
    for row in cursor.fetchall():
        cat, ptype, count = row
        if cat not in by_category:
            by_category[cat] = {}
        by_category[cat][ptype] = count
    stats['by_category'] = by_category

    # Recent patterns
    cursor.execute("""
        SELECT COUNT(*) FROM learning_patterns
        WHERE created_at > datetime('now', '-24 hours')
    """)
    stats['last_24h'] = cursor.fetchone()[0]

    conn.close()
    return stats


def mark_item_sold(item_id: str, sold_time: Optional[str] = None) -> Optional[float]:
    """
    Mark an item as sold and calculate time-to-sell.
    Returns time_to_sell_minutes or None if item not found.

    Now captures FULL analysis data for MISSED opportunities including:
    - Complete AI analysis (melt value, weight, profit, reasoning)
    - Original request data (title, description, seller info, etc.)
    """
    import json as json_lib

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get ALL item data including stored analysis result
    cursor.execute("""
        SELECT posted_time, first_seen, title, price, category, recommendation,
               seller_name, alias, analysis_result_json, original_data_json
        FROM tracked_items WHERE item_id = ?
    """, (item_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    (posted_time_str, first_seen_str, title, price, category, recommendation,
     seller_name, alias, analysis_result_json, original_data_json) = row

    now = datetime.now()
    sold_time_dt = datetime.fromisoformat(sold_time) if sold_time else now

    # Calculate time to sell from posted_time if available, otherwise first_seen
    try:
        if posted_time_str:
            posted_dt = datetime.fromisoformat(posted_time_str.replace('Z', '+00:00'))
            time_to_sell = (sold_time_dt - posted_dt).total_seconds() / 60
        else:
            first_seen_dt = datetime.fromisoformat(first_seen_str)
            time_to_sell = (sold_time_dt - first_seen_dt).total_seconds() / 60
    except Exception as e:
        logger.warning(f"[TRACKING] Error calculating time_to_sell for {item_id}: {e}")
        first_seen_dt = datetime.fromisoformat(first_seen_str)
        time_to_sell = (sold_time_dt - first_seen_dt).total_seconds() / 60

    is_fast_sale = time_to_sell <= 5.0  # 5 minutes or less

    cursor.execute("""
        UPDATE tracked_items
        SET sold_time = ?, time_to_sell_minutes = ?, is_fast_sale = ?, status = 'sold'
        WHERE item_id = ?
    """, (sold_time_dt.isoformat(), time_to_sell, is_fast_sale, item_id))

    conn.commit()
    conn.close()

    if is_fast_sale:
        logger.warning(f"[TRACKING] FAST SALE! Item {item_id} sold in {time_to_sell:.1f} minutes")

        # If we passed on this item and it sold fast, log as MISSED opportunity
        # Now with FULL analysis data if available
        if recommendation and 'PASS' in str(recommendation).upper():
            try:
                # Parse stored analysis result if available
                stored_result = {}
                if analysis_result_json:
                    try:
                        stored_result = json_lib.loads(analysis_result_json)
                    except:
                        pass

                # Parse stored original data if available
                stored_data = {}
                if original_data_json:
                    try:
                        stored_data = json_lib.loads(original_data_json)
                    except:
                        pass

                # Build comprehensive result with all available data
                full_result = {
                    "Recommendation": recommendation or "PASS",
                    "reasoning": stored_result.get('reasoning', f"MISSED: Item sold in {time_to_sell:.1f} min"),
                    # Melt/profit data
                    "weight": stored_result.get('weight', stored_result.get('goldweight', stored_result.get('silverweight', ''))),
                    "weightSource": stored_result.get('weightSource', ''),
                    "karat": stored_result.get('karat', ''),
                    "meltvalue": stored_result.get('meltvalue', stored_result.get('melt', '')),
                    "maxBuy": stored_result.get('maxBuy', ''),
                    "Profit": stored_result.get('Profit', stored_result.get('Margin', '')),
                    "confidence": stored_result.get('confidence', 0),
                    # Opportunity detection data
                    "opportunity_score": stored_result.get('opportunity_score', 0),
                    "opportunity_signals": stored_result.get('opportunity_signals', []),
                }

                # Build comprehensive data with everything from original request
                full_data = {
                    # Seller info
                    "seller": seller_name or stored_data.get('SellerName', ''),
                    "SellerName": stored_data.get('SellerName', seller_name),
                    "FeedbackScore": stored_data.get('FeedbackScore', ''),
                    "StoreName": stored_data.get('StoreName', ''),
                    "sellerType": stored_data.get('sellerType', ''),
                    # Listing info
                    "alias": alias or stored_data.get('Alias', ''),
                    "Alias": stored_data.get('Alias', alias),
                    "Title": stored_data.get('Title', title),
                    "Description": stored_data.get('Description', ''),
                    "ItemURL": stored_data.get('ItemURL', ''),
                    "ImageURL": stored_data.get('ImageURL', ''),
                    # Item specifics
                    "Metal": stored_data.get('Metal', ''),
                    "MetalPurity": stored_data.get('MetalPurity', stored_data.get('Metal Purity', '')),
                    "Fineness": stored_data.get('Fineness', ''),
                    "MainStone": stored_data.get('MainStone', stored_data.get('Main Stone', '')),
                    "TotalCaratWeight": stored_data.get('TotalCaratWeight', ''),
                    "Brand": stored_data.get('Brand', ''),
                    "Type": stored_data.get('Type', ''),
                    # Timing
                    "time_to_sell": time_to_sell,
                    "sold_time": sold_time_dt.isoformat(),
                    "PostedTime": stored_data.get('PostedTime', posted_time_str),
                }

                log_pattern(
                    pattern_type="MISSED",
                    category=category or "unknown",
                    title=title or "",
                    price=float(str(price).replace('$', '').replace(',', '')) if price else 0,
                    result=full_result,
                    data=full_data,
                    notes=f"Sold in {time_to_sell:.1f} min - should have bought"
                )
                logger.warning(f"[PATTERN] Logged MISSED with FULL DATA: {title[:40]}... sold in {time_to_sell:.1f}m, melt={full_result.get('meltvalue', 'NA')}")

                # Track seller signal for fast sale
                try:
                    feedback = None
                    try:
                        feedback = int(stored_data.get('FeedbackScore', 0) or 0)
                    except:
                        pass

                    update_seller_signal(
                        seller_name=seller_name,
                        category=category,
                        price=float(str(price).replace('$', '').replace(',', '')) if price else 0,
                        sold_quickly=True,
                        time_to_sell=time_to_sell,
                        feedback_score=feedback,
                        has_store=bool(stored_data.get('StoreName', ''))
                    )
                except Exception as e:
                    logger.debug(f"[SELLER] Error updating seller signal: {e}")

            except Exception as e:
                logger.warning(f"[PATTERN] Error logging missed opportunity: {e}")
    else:
        logger.info(f"[TRACKING] Item {item_id} sold in {time_to_sell:.1f} minutes")

    return time_to_sell


def get_active_items(limit: int = 100, max_age_hours: int = 24) -> List[Dict]:
    """Get active items that need to be checked for sold status"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get items that are still active and were seen within max_age_hours
    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()

    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'active' AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff, limit))

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return items


def get_fast_sales(limit: int = 100) -> List[Dict]:
    """Get items that sold within 5 minutes"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE is_fast_sale = 1
        ORDER BY sold_time DESC
        LIMIT ?
    """, (limit,))

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return items


def get_tracking_stats() -> Dict[str, Any]:
    """Get overall tracking statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    # Total items tracked
    cursor.execute("SELECT COUNT(*) FROM tracked_items")
    stats["total_tracked"] = cursor.fetchone()[0]

    # Active items
    cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE status = 'active'")
    stats["active_items"] = cursor.fetchone()[0]

    # Items with resolved eBay IDs
    cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE ebay_item_id IS NOT NULL AND ebay_item_id != ''")
    stats["resolved_ids"] = cursor.fetchone()[0]

    # Items pending resolution (active + no ebay_item_id)
    cursor.execute("""
        SELECT COUNT(*) FROM tracked_items
        WHERE status = 'active'
        AND (ebay_item_id IS NULL OR ebay_item_id = '')
    """)
    stats["pending_resolution"] = cursor.fetchone()[0]

    # Sold items
    cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE status = 'sold'")
    stats["sold_items"] = cursor.fetchone()[0]

    # Fast sales
    cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE is_fast_sale = 1")
    stats["fast_sales"] = cursor.fetchone()[0]

    # Average time to sell (for sold items)
    cursor.execute("""
        SELECT AVG(time_to_sell_minutes) FROM tracked_items
        WHERE status = 'sold' AND time_to_sell_minutes IS NOT NULL
    """)
    avg = cursor.fetchone()[0]
    stats["avg_time_to_sell_minutes"] = round(avg, 1) if avg else None

    # Fast sales by category
    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM tracked_items
        WHERE is_fast_sale = 1 AND category != ''
        GROUP BY category
        ORDER BY count DESC
        LIMIT 10
    """)
    stats["fast_sales_by_category"] = [
        {"category": row[0], "count": row[1]} for row in cursor.fetchall()
    ]

    # Recent fast sales
    cursor.execute("""
        SELECT title, price, time_to_sell_minutes, category, sold_time
        FROM tracked_items
        WHERE is_fast_sale = 1
        ORDER BY sold_time DESC
        LIMIT 10
    """)
    stats["recent_fast_sales"] = [
        {
            "title": row[0][:60],
            "price": row[1],
            "time_to_sell": round(row[2], 1) if row[2] else None,
            "category": row[3],
            "sold_time": row[4]
        }
        for row in cursor.fetchall()
    ]

    conn.close()
    return stats


def update_item_check(item_id: str, status: str = "active"):
    """Update item's check count and last_checked timestamp"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tracked_items
        SET check_count = check_count + 1, last_checked = ?, status = ?
        WHERE item_id = ?
    """, (datetime.now().isoformat(), status, item_id))

    conn.commit()
    conn.close()


# ============================================================
# eBay Item ID Resolution
# ============================================================

async def resolve_ebay_item_id(title: str, seller_name: str, price: float) -> Optional[str]:
    """
    Resolve the real eBay item ID by looking up the item via Browse API.
    Returns the numeric item ID (e.g., "123456789") or None if not found.
    """
    try:
        # Import lazily to avoid circular imports
        from services.ebay_lookup import lookup_ebay_item_by_seller

        logger.info(f"[TRACKING] Resolving eBay ID for: {title[:50]}... (seller: {seller_name})")

        # Look up the item on eBay
        item_url = await lookup_ebay_item_by_seller(title, seller_name, price)

        if not item_url:
            logger.debug(f"[TRACKING] No eBay listing found for: {title[:50]}")
            return None

        # Extract item ID from URL
        # URL formats:
        # - https://www.ebay.com/itm/123456789
        # - https://www.ebay.com/itm/Some-Title/123456789
        # - v1|123456789|0 (Browse API format)

        item_id = None

        # Try Browse API format first: v1|123456789|0
        if "|" in item_url:
            parts = item_url.split("|")
            if len(parts) >= 2 and parts[1].isdigit():
                item_id = parts[1]
                logger.info(f"[TRACKING] Extracted ID from Browse format: {item_id}")

        # Try URL format: /itm/123456789 or /itm/title/123456789
        if not item_id:
            match = re.search(r'/itm/(?:[^/]+/)?(\d+)', item_url)
            if match:
                item_id = match.group(1)
                logger.info(f"[TRACKING] Extracted ID from URL: {item_id}")

        # Last resort: find any 10+ digit number
        if not item_id:
            match = re.search(r'(\d{10,})', item_url)
            if match:
                item_id = match.group(1)
                logger.info(f"[TRACKING] Extracted ID from digits: {item_id}")

        return item_id

    except Exception as e:
        logger.warning(f"[TRACKING] Error resolving eBay ID: {e}")
        return None


def update_ebay_item_id(tracking_id: str, ebay_item_id: str):
    """Update a tracked item with its resolved eBay item ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE tracked_items SET ebay_item_id = ? WHERE item_id = ?",
        (ebay_item_id, tracking_id)
    )

    conn.commit()
    conn.close()
    logger.info(f"[TRACKING] Updated item {tracking_id} with eBay ID: {ebay_item_id}")


def get_items_without_ebay_id(limit: int = 20, max_age_minutes: int = 30) -> List[Dict]:
    """
    Get tracked items that need eBay ID resolution.
    Only returns items < max_age_minutes old (default 30 min).

    Items older than 30 min aren't fast-sale candidates anyway,
    so no point resolving their IDs.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()

    # GAP FIX #1: Removed seller_name filter - items without seller names should still be tracked
    # They can be resolved via title+price search fallback
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'active'
        AND (ebay_item_id IS NULL OR ebay_item_id = '')
        AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff, limit))

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return items


def get_error_items_for_retry(limit: int = 10, max_age_hours: int = 2) -> List[Dict]:
    """
    GAP FIX #2: Get items with 'error' status for retry.
    Only returns items that had errors within max_age_hours (default 2 hours).
    Older error items are likely permanently unavailable.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()

    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'error'
        AND last_checked > ?
        AND check_count < 5
        ORDER BY last_checked ASC
        LIMIT ?
    """, (cutoff, limit))

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()

    logger.debug(f"[TRACKING] Found {len(items)} error items for retry")
    return items


async def resolve_pending_items(batch_size: int = 10):
    """
    Background task to resolve eBay item IDs for tracked items.
    Should be called periodically to fill in missing IDs.
    """
    items = get_items_without_ebay_id(limit=batch_size)

    if not items:
        logger.debug("[TRACKING] No items pending eBay ID resolution")
        return

    logger.info(f"[TRACKING] Resolving eBay IDs for {len(items)} items...")

    resolved_count = 0
    for item in items:
        tracking_id = item["item_id"]
        title = item["title"]
        seller_name = item.get("seller_name", "")
        price = _parse_price_value(item.get("price", 0))

        ebay_id = None

        # GAP FIX #1: Try seller-based lookup first, then fall back to title-only
        if seller_name:
            ebay_id = await resolve_ebay_item_id(title, seller_name, price)

        # Fallback: try title-only search if no seller name or seller lookup failed
        if not ebay_id:
            try:
                from services.ebay_lookup import lookup_ebay_item
                item_url = await lookup_ebay_item(title, price)
                if item_url:
                    # Extract item ID from URL
                    match = re.search(r'(\d{10,})', item_url)
                    if match:
                        ebay_id = match.group(1)
                        logger.info(f"[TRACKING] Resolved via title search: {ebay_id}")
            except Exception as e:
                logger.debug(f"[TRACKING] Title-only lookup failed: {e}")

        if ebay_id:
            update_ebay_item_id(tracking_id, ebay_id)
            resolved_count += 1

        # Small delay between API calls
        await asyncio.sleep(0.5)

    if resolved_count > 0:
        logger.info(f"[TRACKING] Resolved {resolved_count}/{len(items)} eBay item IDs")


# ============================================================
# eBay API Polling
# ============================================================

def configure_ebay(app_id: str = None, get_token_func: callable = None):
    """Configure eBay API credentials for polling"""
    global _ebay_app_id, _get_ebay_token
    if app_id:
        _ebay_app_id = app_id
    if get_token_func:
        _get_ebay_token = get_token_func
    logger.info("[TRACKING] eBay API configured for item status polling")


async def check_items_batch_ebay(item_ids: List[str], session: aiohttp.ClientSession) -> Dict[str, str]:
    """
    Check multiple items at once using Browse API getItems (up to 20 per call).
    Returns dict mapping item_id -> status ('active', 'sold', 'error')

    This is much more efficient than individual calls:
    - 20 items = 1 API call instead of 20
    """
    global _get_ebay_token

    if not _get_ebay_token or not item_ids:
        return {item_id: "error" for item_id in item_ids}

    results = {}

    try:
        token = await _get_ebay_token()
        if not token:
            return {item_id: "error" for item_id in item_ids}

        # Format item IDs for the API: v1|itemId|0
        formatted_ids = [f"v1|{item_id}|0" for item_id in item_ids]
        ids_param = ",".join(formatted_ids)

        url = f"https://api.ebay.com/buy/browse/v1/item/?item_ids={ids_param}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("items", [])

                # Process returned items
                for item in items:
                    item_id_full = item.get("itemId", "")
                    # Extract numeric ID from v1|123456|0 format
                    parts = item_id_full.split("|")
                    item_id = parts[1] if len(parts) >= 2 else item_id_full

                    # Check if sold
                    if item.get("itemEndDate"):
                        results[item_id] = "sold"
                    else:
                        avails = item.get("estimatedAvailabilities", [])
                        if avails and avails[0].get("estimatedAvailabilityStatus") == "OUT_OF_STOCK":
                            results[item_id] = "sold"
                        else:
                            results[item_id] = "active"

                # Items not in response are likely sold/removed (404)
                for item_id in item_ids:
                    if item_id not in results:
                        results[item_id] = "sold"

                return results

            elif resp.status == 404:
                # All items not found
                return {item_id: "sold" for item_id in item_ids}
            else:
                logger.warning(f"[TRACKING] Batch API returned {resp.status}")
                # Fall back to individual checks would go here
                return {item_id: "error" for item_id in item_ids}

    except Exception as e:
        logger.warning(f"[TRACKING] Batch check error: {e}")
        return {item_id: "error" for item_id in item_ids}


async def check_item_status_ebay(item_id: str, session: aiohttp.ClientSession) -> str:
    """
    Check single item status (fallback for when batch fails).
    Returns: 'active', 'sold', or 'error'
    """
    global _get_ebay_token

    if not _get_ebay_token:
        return "error"

    try:
        token = await _get_ebay_token()
        if not token:
            return "error"

        url = f"https://api.ebay.com/buy/browse/v1/item/v1|{item_id}|0?fieldgroups=COMPACT"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("itemEndDate"):
                    return "sold"
                availabilities = data.get("estimatedAvailabilities", [])
                for avail in availabilities:
                    if avail.get("estimatedAvailabilityStatus") == "OUT_OF_STOCK":
                        return "sold"
                return "active"
            elif resp.status == 404:
                return "sold"
            else:
                return "error"

    except Exception as e:
        logger.warning(f"[TRACKING] Error checking item {item_id}: {e}")
        return "error"


def get_items_by_priority(limit: int = 100) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Get active items grouped by priority based on age.
    Returns: (high_priority, medium_priority, low_priority)

    High priority: < 10 min old (fast-sale candidates)
    Medium priority: 10-60 min old
    Low priority: 1-6 hours old
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    now = datetime.now()
    cutoff_high = (now - timedelta(minutes=10)).isoformat()
    cutoff_medium = (now - timedelta(hours=1)).isoformat()
    cutoff_low = (now - timedelta(hours=6)).isoformat()

    # High priority: items < 10 min old with resolved IDs
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'active'
        AND ebay_item_id IS NOT NULL AND ebay_item_id != ''
        AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff_high, limit))
    high = [dict(row) for row in cursor.fetchall()]

    # Medium priority: 10-60 min old
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'active'
        AND ebay_item_id IS NOT NULL AND ebay_item_id != ''
        AND first_seen <= ? AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff_high, cutoff_medium, limit))
    medium = [dict(row) for row in cursor.fetchall()]

    # Low priority: 1-6 hours old
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE status = 'active'
        AND ebay_item_id IS NOT NULL AND ebay_item_id != ''
        AND first_seen <= ? AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff_medium, cutoff_low, limit))
    low = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return high, medium, low


async def poll_items_for_sold_status(batch_size: int = 30):
    """
    Poll active items with PRIORITY-BASED checking to minimize API calls.

    Strategy:
    - High priority (< 10 min): Check ALL (fast-sale candidates)
    - Medium priority (10-60 min): Check up to 10
    - Low priority (1-6 hr): Check up to 5
    - Very old (> 6 hr): Stop checking (not fast sales)

    This limits API calls to ~25-30 per poll cycle instead of hundreds.
    """
    high, medium, low = get_items_by_priority(limit=batch_size)

    # Smart selection: prioritize fresh items, limit older ones
    items_to_check = high + medium[:10] + low[:5]

    if not items_to_check:
        logger.debug("[TRACKING] No items with resolved eBay IDs to check")
        return

    logger.info(f"[TRACKING] Checking {len(items_to_check)} items (new={len(high)}, med={min(10, len(medium))}, old={min(5, len(low))})")

    sold_count = 0
    fast_sale_count = 0

    async with aiohttp.ClientSession() as session:
        for item in items_to_check:
            tracking_id = item["item_id"]
            ebay_id = item["ebay_item_id"]

            status = await check_item_status_ebay(ebay_id, session)

            if status == "sold":
                time_to_sell = mark_item_sold(tracking_id)
                sold_count += 1

                if time_to_sell and time_to_sell <= 5:
                    fast_sale_count += 1
                    logger.warning(
                        f"[TRACKING] FAST SALE: {item['title'][:50]} | "
                        f"${item['price']} | {time_to_sell:.1f}min | "
                        f"rec={item.get('recommendation', '?')}"
                    )
                elif time_to_sell:
                    logger.info(f"[TRACKING] Sold: {item['title'][:40]} in {time_to_sell:.0f}min")
            elif status == "error":
                update_item_check(tracking_id, "error")
            else:
                update_item_check(tracking_id, "active")

            # Small delay between calls
            await asyncio.sleep(0.2)

    if sold_count > 0:
        logger.info(f"[TRACKING] Found {sold_count} sold ({fast_sale_count} fast sales)")


# Background polling task
_polling_task: Optional[asyncio.Task] = None
_polling_interval: int = 300  # 5 minutes default


async def _polling_loop():
    """Background task that periodically resolves IDs and checks for sold items"""
    logger.info(f"[TRACKING] Background polling started (interval={_polling_interval}s)")

    while True:
        try:
            await asyncio.sleep(_polling_interval)

            # Step 1: Resolve eBay item IDs for items that don't have them yet
            try:
                await resolve_pending_items(batch_size=10)
            except Exception as e:
                logger.warning(f"[TRACKING] Error resolving item IDs: {e}")

            # Step 2: Check for sold status on items with resolved IDs
            await poll_items_for_sold_status()

            # Step 3: Validate BUY recommendations (check if they sold)
            try:
                await validate_buy_recommendations()
            except Exception as e:
                logger.warning(f"[TRACKING] Error validating BUY recommendations: {e}")

            # GAP FIX #2: Step 4 - Retry error items periodically
            try:
                error_items = get_error_items_for_retry(limit=5)
                if error_items:
                    logger.info(f"[TRACKING] Retrying {len(error_items)} error items...")
                    async with aiohttp.ClientSession() as session:
                        for item in error_items:
                            ebay_id = item.get("ebay_item_id")
                            if ebay_id:
                                status = await check_item_status_ebay(ebay_id, session)
                                if status != "error":
                                    update_item_check(item["item_id"], status)
                                    logger.info(f"[TRACKING] Retry success: {item['item_id']} -> {status}")
                                await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"[TRACKING] Error retry failed: {e}")

        except asyncio.CancelledError:
            logger.info("[TRACKING] Background polling stopped")
            break
        except Exception as e:
            logger.error(f"[TRACKING] Error in polling loop: {e}")


def start_polling(interval_seconds: int = 300):
    """Start the background polling task"""
    global _polling_task, _polling_interval
    _polling_interval = interval_seconds

    if _polling_task is None or _polling_task.done():
        _polling_task = asyncio.create_task(_polling_loop())
        logger.info(f"[TRACKING] Polling task started (every {interval_seconds}s)")


def stop_polling():
    """Stop the background polling task"""
    global _polling_task
    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        logger.info("[TRACKING] Polling task stopped")


# ============================================================
# BUY RECOMMENDATION VALIDATION
# Check if BUY recommendations actually sold (validates our AI)
# ============================================================

def get_buy_items_for_validation(max_age_minutes: int = 15, limit: int = 50) -> Tuple[List[Dict], List[Dict]]:
    """
    Get BUY recommendations that need validation.

    Returns two lists:
    1. fresh_buys: BUY items < max_age_minutes old (check if sold = VALIDATED)
    2. stale_buys: BUY items > max_age_minutes old still active (likely FALSE_BUY)

    Note: Uses 24-hour window for stale items since eBay ID resolution can take time.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    now = datetime.now()
    cutoff_fresh = (now - timedelta(minutes=max_age_minutes)).isoformat()
    cutoff_stale = (now - timedelta(minutes=max_age_minutes)).isoformat()
    cutoff_max = (now - timedelta(hours=24)).isoformat()  # Check items up to 24 hours old

    # Fresh BUY items (< 15 min old) - check if sold yet
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE recommendation = 'BUY'
        AND status = 'active'
        AND ebay_item_id IS NOT NULL AND ebay_item_id != ''
        AND first_seen > ?
        ORDER BY first_seen DESC
        LIMIT ?
    """, (cutoff_fresh, limit))
    fresh_buys = [dict(row) for row in cursor.fetchall()]

    # Stale BUY items (15 min - 2 hours old, still active) - potential false positives
    cursor.execute("""
        SELECT * FROM tracked_items
        WHERE recommendation = 'BUY'
        AND status = 'active'
        AND ebay_item_id IS NOT NULL AND ebay_item_id != ''
        AND first_seen <= ?
        AND first_seen > ?
        ORDER BY first_seen ASC
        LIMIT ?
    """, (cutoff_stale, cutoff_max, limit))
    stale_buys = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return fresh_buys, stale_buys


def log_buy_validation(
    item_id: str,
    title: str,
    price: float,
    category: str,
    validation_type: str,  # VALIDATED_BUY or FALSE_BUY
    time_to_sell: Optional[float] = None,
    notes: str = ""
):
    """
    Log BUY recommendation validation result for learning.

    VALIDATED_BUY: Item sold quickly - our BUY was correct
    FALSE_BUY: Item didn't sell - our BUY was a false positive
    """
    import json as json_lib

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Log to learning_patterns table
    cursor.execute("""
        INSERT INTO learning_patterns
        (pattern_type, category, title, price, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        validation_type,
        category or "unknown",
        title[:500] if title else "",
        price,
        notes,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    if validation_type == "VALIDATED_BUY":
        logger.warning(f"[BUY-VALID] CONFIRMED: {title[:50]} sold in {time_to_sell:.1f}m - BUY was correct!")
    else:
        logger.warning(f"[BUY-VALID] FALSE POSITIVE: {title[:50]} didn't sell - BUY was wrong")


def mark_buy_as_false_positive(item_id: str):
    """Mark a BUY recommendation as a false positive (didn't sell)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tracked_items
        SET recommendation = 'FALSE_BUY', status = 'validated'
        WHERE item_id = ?
    """, (item_id,))

    conn.commit()
    conn.close()


async def validate_buy_recommendations():
    """
    Validate BUY recommendations by checking if they sold.

    Strategy:
    - Check fresh BUY items (< 15 min) - if sold, it's VALIDATED_BUY
    - Check stale BUY items (> 15 min still active) - likely FALSE_BUY
    - Log results for learning
    """
    fresh_buys, stale_buys = get_buy_items_for_validation(max_age_minutes=10, limit=30)

    if not fresh_buys and not stale_buys:
        return

    validated_count = 0
    false_positive_count = 0

    async with aiohttp.ClientSession() as session:
        # Check fresh BUY items - see if they sold (validates our recommendation)
        for item in fresh_buys:
            tracking_id = item["item_id"]
            ebay_id = item["ebay_item_id"]
            title = item.get("title", "")
            price = item.get("price", 0)
            category = item.get("category", "")

            status = await check_item_status_ebay(ebay_id, session)

            if status == "sold":
                time_to_sell = mark_item_sold(tracking_id)
                validated_count += 1

                # Log as VALIDATED_BUY
                log_buy_validation(
                    item_id=tracking_id,
                    title=title,
                    price=price,
                    category=category,
                    validation_type="VALIDATED_BUY",
                    time_to_sell=time_to_sell,
                    notes=f"Sold in {time_to_sell:.1f}m - BUY recommendation confirmed"
                )
            elif status == "active":
                update_item_check(tracking_id, "active")

            await asyncio.sleep(0.2)

        # Check stale BUY items - if still active after 10+ min, likely false positive
        for item in stale_buys[:10]:  # Limit to 10 stale checks per cycle
            tracking_id = item["item_id"]
            ebay_id = item["ebay_item_id"]
            title = item.get("title", "")
            price = item.get("price", 0)
            category = item.get("category", "")
            first_seen = item.get("first_seen", "")

            status = await check_item_status_ebay(ebay_id, session)

            if status == "sold":
                # It did sell eventually
                time_to_sell = mark_item_sold(tracking_id)
                validated_count += 1
                log_buy_validation(
                    item_id=tracking_id,
                    title=title,
                    price=price,
                    category=category,
                    validation_type="VALIDATED_BUY",
                    time_to_sell=time_to_sell,
                    notes=f"Sold in {time_to_sell:.1f}m (late validation)"
                )
            elif status == "active":
                # Still active after 10+ min - likely false positive
                # Calculate how long it's been listed
                try:
                    first_seen_dt = datetime.fromisoformat(first_seen)
                    minutes_listed = (datetime.now() - first_seen_dt).total_seconds() / 60

                    if minutes_listed > 15:  # If it's been 15+ min and still active
                        false_positive_count += 1
                        mark_buy_as_false_positive(tracking_id)
                        log_buy_validation(
                            item_id=tracking_id,
                            title=title,
                            price=price,
                            category=category,
                            validation_type="FALSE_BUY",
                            notes=f"Still active after {minutes_listed:.0f}m - likely overpriced or wrong category"
                        )
                except Exception as e:
                    logger.debug(f"[BUY-VALID] Error calculating age: {e}")

            await asyncio.sleep(0.2)

    if validated_count > 0 or false_positive_count > 0:
        logger.info(f"[BUY-VALID] Results: {validated_count} confirmed, {false_positive_count} false positives")


def get_buy_validation_stats() -> Dict[str, Any]:
    """Get statistics on BUY recommendation accuracy."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    # Count by validation type
    cursor.execute("""
        SELECT pattern_type, COUNT(*), AVG(price)
        FROM learning_patterns
        WHERE pattern_type IN ('VALIDATED_BUY', 'FALSE_BUY')
        GROUP BY pattern_type
    """)
    for row in cursor.fetchall():
        stats[row[0]] = {"count": row[1], "avg_price": row[2]}

    # Calculate accuracy
    validated = stats.get("VALIDATED_BUY", {}).get("count", 0)
    false_pos = stats.get("FALSE_BUY", {}).get("count", 0)
    total = validated + false_pos

    if total > 0:
        stats["accuracy"] = f"{100 * validated / total:.1f}%"
        stats["total_validated"] = total
    else:
        stats["accuracy"] = "N/A"
        stats["total_validated"] = 0

    # Recent validations
    cursor.execute("""
        SELECT pattern_type, title, price, category, created_at
        FROM learning_patterns
        WHERE pattern_type IN ('VALIDATED_BUY', 'FALSE_BUY')
        ORDER BY created_at DESC
        LIMIT 10
    """)
    stats["recent"] = [
        {
            "type": row[0],
            "title": row[1][:50] if row[1] else "",
            "price": row[2],
            "category": row[3],
            "time": row[4]
        }
        for row in cursor.fetchall()
    ]

    conn.close()
    return stats


# Initialize database on module load
init_database()
