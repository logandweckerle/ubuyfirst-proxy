"""
Database module for Claude Proxy Server
Handles SQLite storage, pattern analytics, and listing management
"""
import sqlite3
import json
import re
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

# Get absolute path to database file (same directory as this script)
DB_DIR = Path(__file__).parent.absolute()
DB_PATH = DB_DIR / "arbitrage_data.db"

# ============================================================
# DATABASE CONNECTION
# ============================================================
class Database:
    def __init__(self, path: str = None):
        # Use absolute path by default
        self.path = str(path or DB_PATH)
        self.conn = None
        self._init_db()
        logger.info(f"[DB] Database initialized at: {self.path}")
    
    def _init_db(self):
        """Initialize database with required tables"""
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        # Listings table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                title TEXT,
                total_price REAL,
                category TEXT,
                recommendation TEXT,
                margin REAL,
                confidence TEXT,
                reasoning TEXT,
                raw_response TEXT,
                input_data TEXT
            )
        """)
        
        # Keyword patterns table - ENHANCED with confidence, margin, and alias tracking
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS keyword_patterns (
                keyword TEXT,
                category TEXT,
                alias TEXT DEFAULT '',
                times_seen INTEGER DEFAULT 0,
                times_analyzed INTEGER DEFAULT 0,
                buy_count INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                research_count INTEGER DEFAULT 0,
                total_margin REAL DEFAULT 0,
                total_confidence REAL DEFAULT 0,
                avg_margin REAL DEFAULT 0,
                avg_confidence REAL DEFAULT 0,
                last_seen TEXT,
                PRIMARY KEY (keyword, category, alias)
            )
        """)
        
        # Check if keyword_patterns needs migration for alias column
        try:
            cursor = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='keyword_patterns'")
            row = cursor.fetchone()
            if row:
                schema = row[0].upper()
                # Check if alias column exists
                if 'ALIAS' not in schema:
                    logger.info("[DB] Migrating keyword_patterns table to add alias column...")
                    self.conn.execute("ALTER TABLE keyword_patterns RENAME TO keyword_patterns_old")
                    self.conn.execute("""
                        CREATE TABLE keyword_patterns (
                            keyword TEXT,
                            category TEXT,
                            alias TEXT DEFAULT '',
                            times_seen INTEGER DEFAULT 0,
                            times_analyzed INTEGER DEFAULT 0,
                            buy_count INTEGER DEFAULT 0,
                            pass_count INTEGER DEFAULT 0,
                            research_count INTEGER DEFAULT 0,
                            total_margin REAL DEFAULT 0,
                            total_confidence REAL DEFAULT 0,
                            avg_margin REAL DEFAULT 0,
                            avg_confidence REAL DEFAULT 0,
                            last_seen TEXT,
                            PRIMARY KEY (keyword, category, alias)
                        )
                    """)
                    # Migrate old data with empty alias
                    self.conn.execute("""
                        INSERT OR IGNORE INTO keyword_patterns
                        (keyword, category, alias, times_seen, times_analyzed, buy_count, pass_count,
                         research_count, total_margin, total_confidence, avg_margin, avg_confidence, last_seen)
                        SELECT keyword, category, '', times_seen, times_analyzed, buy_count, pass_count,
                               research_count, total_margin, total_confidence, avg_margin, avg_confidence, last_seen
                        FROM keyword_patterns_old
                    """)
                    self.conn.execute("DROP TABLE keyword_patterns_old")
                    self.conn.commit()
                    logger.info("[DB] Migration complete - keyword_patterns now has alias column")
        except Exception as e:
            logger.warning(f"[DB] Migration check: {e}")
        
        # Add new columns if they don't exist (migration)
        try:
            self.conn.execute("ALTER TABLE keyword_patterns ADD COLUMN total_margin REAL DEFAULT 0")
        except:
            pass
        try:
            self.conn.execute("ALTER TABLE keyword_patterns ADD COLUMN total_confidence REAL DEFAULT 0")
        except:
            pass
        try:
            self.conn.execute("ALTER TABLE keyword_patterns ADD COLUMN avg_margin REAL DEFAULT 0")
        except:
            pass
        try:
            self.conn.execute("ALTER TABLE keyword_patterns ADD COLUMN avg_confidence REAL DEFAULT 0")
        except:
            pass
        
        # Incoming listings log
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS incoming_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                title TEXT,
                price REAL,
                category TEXT,
                alias TEXT
            )
        """)

        # Feedback table for learning loop
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT,
                item_id TEXT,
                title TEXT,
                listing_price REAL,
                category TEXT,
                recommendation TEXT,
                action TEXT,
                actual_sell_price REAL,
                profit_realized REAL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(listing_id, action)
            )
        """)

        self.conn.commit()
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(query, params)
    
    def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(query, params).fetchone()
    
    def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.conn.execute(query, params).fetchall()
    
    def commit(self):
        self.conn.commit()

# Global database instance
db = Database()


# ============================================================
# LISTING MANAGEMENT
# ============================================================
def save_listing(listing: Dict[str, Any]):
    """Save a listing to the database"""
    try:
        listing_id = listing.get('id', '')
        title = listing.get('title', '')[:50]
        recommendation = listing.get('recommendation', '')
        
        db.execute("""
            INSERT OR REPLACE INTO listings 
            (id, timestamp, title, total_price, category, recommendation, margin, confidence, reasoning, raw_response, input_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            listing.get('id', ''),
            listing.get('timestamp', ''),
            listing.get('title', ''),
            listing.get('total_price', 0),
            listing.get('category', ''),
            listing.get('recommendation', ''),
            _parse_margin(listing.get('margin', '0')),
            str(listing.get('confidence', '')),
            listing.get('reasoning', ''),
            listing.get('raw_response', ''),
            json.dumps(listing.get('input_data', {}))
        ))
        db.commit()
        logger.info(f"[DB] Saved listing: {listing_id} | {title}... | {recommendation}")
    except Exception as e:
        logger.error(f"[DB] Error saving listing: {e}")


def log_incoming_listing(title: str, price: float, category: str, alias: str = ""):
    """Log an incoming listing for pattern analysis"""
    try:
        db.execute("""
            INSERT INTO incoming_log (timestamp, title, price, category, alias)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), title, price, category, alias))
        db.commit()

        # Normalize alias for consistency
        clean_alias = alias.strip().lower() if alias else ""

        # Update keyword patterns (times_seen) - now organized by alias
        keywords = extract_title_keywords(title)
        for keyword in keywords:
            db.execute("""
                INSERT INTO keyword_patterns (keyword, category, alias, times_seen, last_seen)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(keyword, category, alias) DO UPDATE SET
                    times_seen = times_seen + 1,
                    last_seen = ?
            """, (keyword, category, clean_alias, datetime.now().isoformat(), datetime.now().isoformat()))
        db.commit()
        logger.debug(f"[DB] Logged incoming: {title[:40]}... | {category} | {alias} | ${price}")
    except Exception as e:
        logger.error(f"[DB] Error logging incoming: {e}")


def _parse_margin(margin_str) -> float:
    """Parse margin string to float"""
    try:
        if isinstance(margin_str, (int, float)):
            return float(margin_str)
        margin_str = str(margin_str).replace('$', '').replace('+', '').replace(',', '').strip()
        return float(margin_str) if margin_str else 0
    except:
        return 0


def _parse_confidence(conf_str) -> float:
    """Parse confidence to numeric value"""
    try:
        if isinstance(conf_str, (int, float)):
            return float(conf_str)
        conf_str = str(conf_str).strip()
        # Handle numeric strings
        if conf_str.isdigit():
            return float(conf_str)
        # Handle word formats
        if 'high' in conf_str.lower():
            return 80
        elif 'med' in conf_str.lower():
            return 60
        elif 'low' in conf_str.lower():
            return 40
        # Try to extract number
        match = re.search(r'(\d+)', conf_str)
        if match:
            return float(match.group(1))
        return 50  # default
    except:
        return 50


def update_pattern_outcome(title: str, category: str, recommendation: str, margin: float = 0, confidence: str = "", alias: str = ""):
    """Update keyword patterns with analysis outcome including margin and confidence, organized by alias"""
    try:
        keywords = extract_title_keywords(title)
        margin_val = _parse_margin(margin) if margin else 0
        conf_val = _parse_confidence(confidence) if confidence else 50
        clean_alias = alias.strip().lower() if alias else ""

        for keyword in keywords:
            if recommendation == 'BUY':
                db.execute("""
                    UPDATE keyword_patterns
                    SET times_analyzed = times_analyzed + 1,
                        buy_count = buy_count + 1,
                        total_margin = total_margin + ?,
                        total_confidence = total_confidence + ?,
                        avg_margin = (total_margin + ?) / (times_analyzed + 1),
                        avg_confidence = (total_confidence + ?) / (times_analyzed + 1)
                    WHERE keyword = ? AND category = ? AND alias = ?
                """, (margin_val, conf_val, margin_val, conf_val, keyword, category, clean_alias))
            elif recommendation == 'PASS':
                db.execute("""
                    UPDATE keyword_patterns
                    SET times_analyzed = times_analyzed + 1,
                        pass_count = pass_count + 1,
                        total_margin = total_margin + ?,
                        total_confidence = total_confidence + ?,
                        avg_margin = (total_margin + ?) / (times_analyzed + 1),
                        avg_confidence = (total_confidence + ?) / (times_analyzed + 1)
                    WHERE keyword = ? AND category = ? AND alias = ?
                """, (margin_val, conf_val, margin_val, conf_val, keyword, category, clean_alias))
            else:  # RESEARCH
                db.execute("""
                    UPDATE keyword_patterns
                    SET times_analyzed = times_analyzed + 1,
                        research_count = research_count + 1,
                        total_margin = total_margin + ?,
                        total_confidence = total_confidence + ?,
                        avg_margin = (total_margin + ?) / (times_analyzed + 1),
                        avg_confidence = (total_confidence + ?) / (times_analyzed + 1)
                    WHERE keyword = ? AND category = ? AND alias = ?
                """, (margin_val, conf_val, margin_val, conf_val, keyword, category, clean_alias))
        db.commit()
    except Exception as e:
        logger.error(f"Error updating pattern outcome: {e}")


# ============================================================
# KEYWORD EXTRACTION
# ============================================================
# Common words to skip
SKIP_WORDS = {
    'the', 'and', 'for', 'with', 'lot', 'set', 'new', 'used', 'vintage', 'antique',
    'old', 'rare', 'nice', 'great', 'good', 'excellent', 'fine', 'beautiful',
    'stunning', 'gorgeous', 'lovely', 'pretty', 'estate', 'collection',
    'item', 'items', 'piece', 'pieces', 'mixed', 'assorted', 'various',
    'see', 'pics', 'photos', 'pictures', 'look', 'please', 'read', 'description',
    'fast', 'free', 'shipping', 'ship', 'ships', 'priority', 'usps',
    'auction', 'buy', 'now', 'sale', 'price', 'obo', 'offer', 'offers',
    'gram', 'grams', 'dwt', 'ounce', 'oz', 'inch', 'inches', 'size',
    'marked', 'stamped', 'signed', 'hallmarked', 'tested', 'guaranteed',
    'authentic', 'genuine', 'real', 'solid', 'pure', 'scrap', 'melt',
    'not', 'but', 'has', 'have', 'was', 'were', 'are', 'from', 'this', 'that',
    'will', 'can', 'may', 'all', 'any', 'some', 'each', 'per', 'one', 'two', 'three',
    'approx', 'approximately', 'about', 'total', 'weight', 'weighs'
}

def extract_title_keywords(title: str) -> List[str]:
    """Extract meaningful keywords from a listing title"""
    if not title:
        return []
    
    # Clean and tokenize
    title = title.lower()
    # Remove special characters but keep hyphens for compound words
    title = re.sub(r'[^\w\s\-]', ' ', title)
    words = title.split()
    
    keywords = []
    for word in words:
        word = word.strip('-')
        if len(word) < 2:
            continue
        if word in SKIP_WORDS:
            continue
        if word.isdigit():
            continue
        # Skip pure numbers with units
        if re.match(r'^\d+[a-z]*$', word):
            continue
        keywords.append(word)
    
    # Also extract bigrams for compound terms
    bigrams = []
    for i in range(len(words) - 1):
        w1, w2 = words[i].strip('-'), words[i+1].strip('-')
        if w1 not in SKIP_WORDS and w2 not in SKIP_WORDS:
            if len(w1) > 1 and len(w2) > 1:
                bigrams.append(f"{w1} {w2}")
    
    return list(set(keywords + bigrams[:5]))  # Limit bigrams


# ============================================================
# ANALYTICS
# ============================================================
def get_analytics() -> Dict[str, Any]:
    """Get general analytics data"""
    try:
        # Total counts
        total = db.fetchone("SELECT COUNT(*) as cnt FROM listings")
        total_count = total['cnt'] if total else 0
        
        # By recommendation
        by_rec = db.fetchall("""
            SELECT recommendation, COUNT(*) as cnt 
            FROM listings 
            GROUP BY recommendation
        """)
        rec_counts = {row['recommendation']: row['cnt'] for row in by_rec}
        
        # By category
        by_cat = db.fetchall("""
            SELECT category, COUNT(*) as cnt, 
                   SUM(CASE WHEN recommendation = 'BUY' THEN 1 ELSE 0 END) as buys,
                   SUM(CASE WHEN recommendation = 'PASS' THEN 1 ELSE 0 END) as passes
            FROM listings 
            GROUP BY category
            ORDER BY cnt DESC
        """)
        
        # Daily trend (last 7 days)
        daily = db.fetchall("""
            SELECT DATE(timestamp) as date,
                   COUNT(*) as total_analyzed,
                   SUM(CASE WHEN recommendation = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                   SUM(CASE WHEN recommendation = 'PASS' THEN 1 ELSE 0 END) as pass_count
            FROM listings
            WHERE timestamp > datetime('now', '-7 days')
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """)
        
        # Recent listings (last 20)
        recent = db.fetchall("""
            SELECT id, timestamp, title, category, recommendation, margin, confidence
            FROM listings
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        
        return {
            'total_analyzed': total_count,
            'buy_count': rec_counts.get('BUY', 0),
            'pass_count': rec_counts.get('PASS', 0),
            'research_count': rec_counts.get('RESEARCH', 0),
            'by_category': [dict(row) for row in by_cat],
            'daily_trend': [dict(row) for row in daily],
            'recent': [dict(row) for row in recent]
        }
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return {}


def get_pattern_analytics() -> Dict[str, Any]:
    """Get pattern analytics with enhanced scoring, organized by alias"""
    try:
        # High-pass keywords with margin, confidence, and alias data
        high_pass = db.fetchall("""
            SELECT keyword, category, alias, times_seen, times_analyzed,
                   buy_count, pass_count, research_count,
                   CAST(pass_count AS REAL) / NULLIF(times_analyzed, 0) as pass_rate,
                   avg_margin, avg_confidence,
                   total_margin, total_confidence
            FROM keyword_patterns
            WHERE times_analyzed >= 3
            ORDER BY pass_rate DESC, times_analyzed DESC
            LIMIT 200
        """)
        
        # Calculate "waste score" for each keyword
        # Higher = worse (high pass rate, low confidence, negative margins)
        scored_keywords = []
        for row in high_pass:
            row_dict = dict(row)
            pass_rate = row_dict.get('pass_rate', 0) or 0
            avg_margin = row_dict.get('avg_margin', 0) or 0
            avg_conf = row_dict.get('avg_confidence', 50) or 50
            times_analyzed = row_dict.get('times_analyzed', 0) or 0
            
            # Waste score formula:
            # - Pass rate contributes positively (more passes = worse)
            # - Negative margin contributes positively (more negative = worse)
            # - Low confidence contributes positively (lower = worse)
            # - Volume matters (more samples = more reliable)
            margin_penalty = max(0, -avg_margin) / 100  # Normalize negative margins
            conf_penalty = (100 - avg_conf) / 100  # Lower conf = higher penalty
            volume_weight = min(1.0, times_analyzed / 10)  # Cap at 10 samples
            
            waste_score = (pass_rate * 0.5 + margin_penalty * 0.3 + conf_penalty * 0.2) * volume_weight
            row_dict['waste_score'] = waste_score
            row_dict['pass_rate'] = pass_rate
            
            scored_keywords.append(row_dict)
        
        # Sort by waste score (worst keywords first)
        scored_keywords.sort(key=lambda x: x.get('waste_score', 0), reverse=True)

        # Group by waste level
        worst_keywords = [k for k in scored_keywords if k.get('waste_score', 0) > 0.4]
        bad_keywords = [k for k in scored_keywords if 0.2 < k.get('waste_score', 0) <= 0.4]
        moderate_keywords = [k for k in scored_keywords if k.get('waste_score', 0) <= 0.2 and k.get('pass_rate', 0) > 0.5]

        # Group by alias for easy filtering
        by_alias = {}
        for k in scored_keywords:
            alias = k.get('alias', '') or 'unknown'
            if alias not in by_alias:
                by_alias[alias] = []
            by_alias[alias].append(k)

        # Calculate alias-level stats
        alias_stats = {}
        for alias, keywords in by_alias.items():
            total_passes = sum(k.get('pass_count', 0) for k in keywords)
            total_analyzed = sum(k.get('times_analyzed', 0) for k in keywords)
            avg_waste = sum(k.get('waste_score', 0) for k in keywords) / len(keywords) if keywords else 0
            alias_stats[alias] = {
                'keyword_count': len(keywords),
                'total_passes': total_passes,
                'total_analyzed': total_analyzed,
                'pass_rate': total_passes / total_analyzed if total_analyzed > 0 else 0,
                'avg_waste_score': avg_waste,
                'worst_keywords': sorted(keywords, key=lambda x: x.get('waste_score', 0), reverse=True)[:10]
            }

        return {
            'high_pass_keywords': scored_keywords,
            'worst_keywords': worst_keywords[:20],
            'bad_keywords': bad_keywords[:20],
            'moderate_keywords': moderate_keywords[:20],
            'total_patterns': len(scored_keywords),
            'by_alias': by_alias,
            'alias_stats': alias_stats
        }
    except Exception as e:
        logger.error(f"Error getting pattern analytics: {e}")
        return {'high_pass_keywords': [], 'worst_keywords': [], 'bad_keywords': [], 'moderate_keywords': [], 'by_alias': {}, 'alias_stats': {}}


def get_db_debug_info() -> Dict[str, Any]:
    """Get database debug information"""
    try:
        import os

        # Check file existence and size
        db_exists = os.path.exists(db.path)
        db_size = os.path.getsize(db.path) if db_exists else 0

        # Count records
        listings_count = db.fetchone("SELECT COUNT(*) as cnt FROM listings")
        incoming_count = db.fetchone("SELECT COUNT(*) as cnt FROM incoming_log")
        patterns_count = db.fetchone("SELECT COUNT(*) as cnt FROM keyword_patterns")

        # Get recent listings
        recent = db.fetchall("""
            SELECT id, timestamp, title, category, recommendation
            FROM listings
            ORDER BY timestamp DESC
            LIMIT 5
        """)

        return {
            "database_path": db.path,
            "db_exists": db_exists,
            "db_size_bytes": db_size,
            "db_size_kb": round(db_size / 1024, 2),
            "listings_count": listings_count['cnt'] if listings_count else 0,
            "incoming_log_count": incoming_count['cnt'] if incoming_count else 0,
            "keyword_patterns_count": patterns_count['cnt'] if patterns_count else 0,
            "recent_listings": [dict(row) for row in recent] if recent else [],
        }
    except Exception as e:
        return {"error": str(e), "database_path": db.path}


# ============================================================
# FEEDBACK / LEARNING LOOP
# ============================================================

def save_feedback(listing_id: str, item_id: str = None, title: str = None,
                  listing_price: float = None, category: str = None,
                  recommendation: str = None, action: str = None,
                  actual_sell_price: float = None, notes: str = None):
    """
    Save feedback for a listing outcome.

    Actions: 'bought', 'skipped', 'missed', 'returned'
    """
    try:
        profit = (actual_sell_price - listing_price) if (actual_sell_price and listing_price) else None
        db.execute("""
            INSERT OR REPLACE INTO feedback
            (listing_id, item_id, title, listing_price, category, recommendation,
             action, actual_sell_price, profit_realized, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (listing_id, item_id, title, listing_price, category, recommendation,
              action, actual_sell_price, profit, notes))
        db.commit()
        logger.info(f"[FEEDBACK] Saved: {action} | {title[:40] if title else 'N/A'}... | profit: {profit}")
    except Exception as e:
        logger.error(f"[FEEDBACK] Error saving: {e}")


def get_feedback_stats() -> Dict[str, Any]:
    """Get aggregate feedback statistics."""
    try:
        rows = db.fetchall("""
            SELECT action, COUNT(*) as cnt,
                   AVG(profit_realized) as avg_profit,
                   SUM(profit_realized) as total_profit
            FROM feedback
            GROUP BY action
        """)
        stats = {}
        for row in rows:
            row_dict = dict(row)
            stats[row_dict['action']] = {
                "count": row_dict['cnt'],
                "avg_profit": row_dict['avg_profit'],
                "total_profit": row_dict['total_profit'],
            }

        total = db.fetchone("SELECT COUNT(*) as cnt FROM feedback")
        stats['total_entries'] = total['cnt'] if total else 0
        return stats
    except Exception as e:
        logger.error(f"[FEEDBACK] Error getting stats: {e}")
        return {}


def get_feedback_by_category() -> Dict[str, Any]:
    """Get feedback stats grouped by category."""
    try:
        rows = db.fetchall("""
            SELECT category, action, COUNT(*) as cnt,
                   AVG(profit_realized) as avg_profit,
                   SUM(profit_realized) as total_profit
            FROM feedback
            WHERE category IS NOT NULL
            GROUP BY category, action
            ORDER BY category, action
        """)
        result = {}
        for row in rows:
            row_dict = dict(row)
            cat = row_dict['category']
            if cat not in result:
                result[cat] = {}
            result[cat][row_dict['action']] = {
                "count": row_dict['cnt'],
                "avg_profit": row_dict['avg_profit'],
                "total_profit": row_dict['total_profit'],
            }
        return result
    except Exception as e:
        logger.error(f"[FEEDBACK] Error getting category stats: {e}")
        return {}


# ============================================================
# SELLER PROFILING SYSTEM
# ============================================================

def init_seller_profiles_table():
    """Initialize the seller_profiles table"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS seller_profiles (
            seller_id TEXT PRIMARY KEY,
            profile_score INTEGER DEFAULT 50,
            username_patterns TEXT DEFAULT '[]',
            category_focus TEXT DEFAULT '',
            mentions_weight BOOLEAN DEFAULT 0,
            estimated_type TEXT DEFAULT 'unknown',
            avg_purchase_price REAL DEFAULT 0,
            total_purchases INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,
            first_seen TEXT,
            last_seen TEXT,
            notes TEXT DEFAULT '',
            score_breakdown TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    logger.info("[DB] Seller profiles table initialized")

# Initialize on module load
try:
    init_seller_profiles_table()
except Exception as e:
    logger.warning(f"[DB] Could not init seller_profiles: {e}")


# ============================================================
# SELLER AVATAR SYSTEM
# ============================================================
# Avatars represent seller "types" that help predict deal quality
# Higher priority avatars override lower ones

SELLER_AVATARS = {
    'TRUSTED': {
        'priority': 100,  # Highest - based on purchase history
        'score_modifier': 30,
        'description': 'Previously purchased from 3+ times',
        'color': '🟢',
    },
    'ESTATE': {
        'priority': 90,
        'score_modifier': 25,
        'keywords': ['estate', 'inherited', 'grandma', 'grandpa', 'attic', 'downsiz',
                     'deceased', 'passed', 'moving', 'storage'],
        'description': 'Estate sale seller - often unaware of true values',
        'color': '🟢',
    },
    'THRIFT': {
        'priority': 85,
        'score_modifier': 20,
        'keywords': ['thrift', 'goodwill', 'salvation', 'hospice', 'charity', 'donate',
                     'humane', 'spca', 'restore', 'habitat'],
        'description': 'Thrift/charity store - priced to move',
        'color': '🟢',
    },
    'PICKER': {
        'priority': 80,
        'score_modifier': 15,
        'keywords': ['picked', 'picker', 'finds', 'junque', 'junk', 'barn', 'attic',
                     'garage', 'yard', 'flea'],
        'description': 'Picker/flipper - finds stuff, may not know values',
        'color': '🟡',
    },
    'ANTIQUE': {
        'priority': 50,  # Higher than specific negative signals
        'score_modifier': 5,
        'keywords': ['antique', 'vintage', 'retro', 'collecti', 'classic', 'nostalg'],
        'description': 'Antique/vintage focus - aesthetic pricing',
        'color': '🟡',
    },
    'CASUAL': {
        'priority': 35,  # Lower - fallback when no specific signals match
        'score_modifier': 10,
        'patterns': [
            r'^[a-z]+\d{2,4}$',  # firstname123
            r'^\w{1,8}$',  # short username
            r'\d{4,}$',  # ends with many numbers
        ],
        'description': 'Casual individual seller',
        'color': '🟡',
    },
    'PRO_DEALER': {
        'priority': 42,  # Higher than FLIPPER - more specific negative signal
        'score_modifier': -20,
        'keywords': ['jewelry', 'jeweler', 'gold', 'silver', 'coin', 'pawn', 'metal',
                     'bullion', 'refin', 'scrap', 'melt', 'karat', 'carat', 'dealer',
                     'watch', 'watches', 'timepiece', 'rolex', 'omega'],  # Added watch dealers
        'description': 'Professional dealer - knows exact values',
        'color': '🔴',
    },
    'FLIPPER': {
        'priority': 40,
        'score_modifier': -5,
        'keywords': ['flip', 'resell', 'resale', 'bargain', 'discount', 'cheap'],
        'description': 'Reseller/flipper - may know values',
        'color': '🟠',
    },
    'BUSINESS': {
        'priority': 38,  # Higher than FLIPPER for clear business signals
        'score_modifier': -15,
        'keywords': ['llc', 'inc', 'corp', 'company', 'enterprise', 'outlet', 'store',
                     'shop', 'emporium', 'market', 'wholesale'],
        'description': 'Business account - professional pricing',
        'color': '🔴',
    },
    'UNKNOWN': {
        'priority': 0,
        'score_modifier': 0,
        'description': 'No patterns detected',
        'color': '⚪',
    },
}

# Trusted sellers from purchase history (populated at runtime)
TRUSTED_SELLERS = set()

def load_trusted_sellers():
    """Load sellers with 3+ purchases from purchase_history.db"""
    global TRUSTED_SELLERS
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent / 'purchase_history.db'
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute('''
                SELECT LOWER(seller) FROM purchases
                WHERE seller IS NOT NULL
                GROUP BY LOWER(seller)
                HAVING COUNT(*) >= 3
            ''')
            TRUSTED_SELLERS = {row[0] for row in cursor.fetchall()}
            conn.close()
            logger.info(f"[SELLER] Loaded {len(TRUSTED_SELLERS)} trusted sellers from purchase history")
    except Exception as e:
        logger.warning(f"[SELLER] Could not load trusted sellers: {e}")

# Load on module import
load_trusted_sellers()

def get_seller_avatar(seller: str, ebay_data: dict = None) -> dict:
    """
    Determine the primary avatar/type for a seller.
    Returns the highest-priority matching avatar.
    """
    if not seller:
        return {'avatar': 'UNKNOWN', **SELLER_AVATARS['UNKNOWN']}

    seller_lower = seller.lower().strip()
    matched_avatars = []

    # Check if trusted seller first (highest priority)
    if seller_lower in TRUSTED_SELLERS:
        matched_avatars.append(('TRUSTED', SELLER_AVATARS['TRUSTED']['priority']))

    # Check each avatar's patterns
    for avatar_name, config in SELLER_AVATARS.items():
        if avatar_name in ('TRUSTED', 'UNKNOWN'):
            continue

        matched = False

        # Check keywords
        if 'keywords' in config:
            if any(kw in seller_lower for kw in config['keywords']):
                matched = True

        # Check regex patterns
        if 'patterns' in config:
            for pattern in config['patterns']:
                if re.search(pattern, seller_lower):
                    matched = True
                    break

        if matched:
            matched_avatars.append((avatar_name, config['priority']))

    # Check eBay business data if available
    if ebay_data:
        is_business = str(ebay_data.get('SellerBusiness', '')).lower() == 'true'
        has_store = bool(ebay_data.get('SellerStore', '').strip())
        if is_business or has_store:
            matched_avatars.append(('BUSINESS', SELLER_AVATARS['BUSINESS']['priority']))

    # Return highest priority match
    if matched_avatars:
        matched_avatars.sort(key=lambda x: -x[1])  # Sort by priority descending
        best_avatar = matched_avatars[0][0]
        return {
            'avatar': best_avatar,
            'all_matches': [m[0] for m in matched_avatars],
            **SELLER_AVATARS[best_avatar]
        }

    # Check for casual patterns (fallback)
    if re.search(r'^[a-z]+\d{1,4}$', seller_lower) or len(seller_lower) <= 8:
        return {'avatar': 'CASUAL', **SELLER_AVATARS['CASUAL']}

    return {'avatar': 'UNKNOWN', **SELLER_AVATARS['UNKNOWN']}

# Legacy pattern definitions (still used by analyze_seller_username)
SELLER_PATTERNS = {
    'numbers_suffix': {
        'pattern': r'\d{2,}$',
        'score': 5,
        'description': 'Username ends with numbers (common casual seller pattern)'
    },
    'short_name': {
        'pattern': lambda s: len(s) <= 8,
        'score': 10,
        'description': 'Short username (8 chars or less)'
    },
    'estate_keywords': {
        'keywords': ['estate', 'liquidat', 'auction', 'consign', 'downsiz'],
        'score': 15,
        'description': 'Estate/liquidation keywords in username'
    },
    'pawn_thrift': {
        'keywords': ['pawn', 'resale', 'thrift', 'second', 'picked', 'finds', 'picker'],
        'score': 15,
        'description': 'Pawn/thrift/picker keywords'
    },
    'antique_vintage': {
        'keywords': ['antique', 'vintage', 'retro', 'old', 'classic', 'collecti'],
        'score': 8,
        'description': 'Antique/vintage focus (aesthetics over value)'
    },
    'location_based': {
        'keywords': ['florida', 'texas', 'cali', 'ohio', 'york', 'chicago', 'vegas',
                     'arizona', 'vermont', 'maine', 'jersey', 'carolina', 'georgia'],
        'score': 10,
        'description': 'Location-based name (often estate/picker sellers)'
    },
    'special_chars': {
        'pattern': r'[*_-]',
        'score': 3,
        'description': 'Special characters in username'
    },
    'deals_bargain': {
        'keywords': ['deal', 'bargain', 'discount', 'cheap', 'value', 'save', 'sale'],
        'score': 5,
        'description': 'Deal/bargain keywords'
    },
    'business_formal': {
        'keywords': ['llc', 'inc', 'corp', 'ltd'],
        'score': -20,
        'description': 'Business entity (LLC/Inc/Corp)'
    },
    'precious_metal_dealer': {
        'keywords': ['jewelry', 'jeweler', 'goldand', 'silvershop', 'bullion',
                     'numismatic', 'refinery', 'metalshop', 'pawnshop'],
        'score': -15,
        'description': 'Precious metal/jewelry dealer'
    },
    'coin_dealer': {
        'keywords': ['coinshop', 'coins', 'numis', 'coindealer', 'coinexchange'],
        'score': -15,
        'description': 'Coin dealer (knows precious metal values)'
    },
    'gram_pricing': {
        'keywords': ['pergram', 'per-gram', 'bygram', 'gramgold', 'gramsilver'],
        'score': -20,
        'description': 'Explicitly mentions per-gram pricing'
    }
}


def analyze_seller_username(seller: str) -> Dict[str, Any]:
    """Analyze a seller username and return detected patterns with scores"""
    seller_lower = seller.lower()
    detected_patterns = []
    total_score = 50  # Base score

    for pattern_name, config in SELLER_PATTERNS.items():
        matched = False

        # Check regex patterns
        if 'pattern' in config:
            if callable(config['pattern']):
                matched = config['pattern'](seller)
            else:
                matched = bool(re.search(config['pattern'], seller))

        # Check keyword patterns
        if 'keywords' in config:
            matched = any(kw in seller_lower for kw in config['keywords'])

        if matched:
            detected_patterns.append({
                'pattern': pattern_name,
                'score': config['score'],
                'description': config['description']
            })
            total_score += config['score']

    # Clamp score between 0 and 100
    total_score = max(0, min(100, total_score))

    return {
        'patterns': detected_patterns,
        'score': total_score,
        'pattern_names': [p['pattern'] for p in detected_patterns]
    }


def analyze_seller_titles(titles: List[str], category: str = '') -> Dict[str, Any]:
    """Analyze listing titles from a seller to detect pricing awareness"""
    weight_patterns = [
        r'\d+\.?\d*\s*(g|gram|grams|oz|dwt|ozt|pennyweight)',
        r'\d+g\b',
        r'\d+\s*grams?\b'
    ]

    titles_with_weight = 0
    for title in titles:
        if any(re.search(p, title.lower()) for p in weight_patterns):
            titles_with_weight += 1

    mentions_weight = titles_with_weight > len(titles) * 0.5  # >50% mention weight
    weight_ratio = titles_with_weight / len(titles) if titles else 0

    # Scoring based on weight mentions (for precious metals)
    if category in ('gold', 'silver'):
        if mentions_weight:
            weight_score = -15  # Knows values
        elif weight_ratio > 0.25:
            weight_score = -5  # Sometimes mentions
        else:
            weight_score = 20  # Rarely/never mentions weight = potential mispricing
    else:
        weight_score = 0

    return {
        'mentions_weight': mentions_weight,
        'weight_ratio': weight_ratio,
        'titles_with_weight': titles_with_weight,
        'total_titles': len(titles),
        'weight_score': weight_score
    }


def calculate_seller_score(seller: str, titles: List[str] = None, category: str = '',
                           purchase_count: int = 0, ebay_data: Dict[str, Any] = None,
                           listing_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Calculate comprehensive seller profile score.

    Based on analysis of 24,000+ listings with BUY rate correlation.

    ebay_data can include:
        - SellerBusiness: 'True' or 'False'
        - SellerStore: store name or empty
        - FeedbackScore: number of feedbacks
        - FeedbackRating: percentage positive
        - SellerRegistration: registration date string

    listing_data can include:
        - Condition: item condition string
        - Title: listing title for keyword analysis
        - Description: listing description (empty = casual seller bonus)
        - BestOffer: 'true' if accepts best offer
        - UPC: UPC code if present
        - ConditionDescription: additional condition notes
    """
    # Get seller avatar first (new unified system)
    avatar_info = get_seller_avatar(seller, ebay_data)
    avatar = avatar_info['avatar']
    avatar_modifier = avatar_info.get('score_modifier', 0)

    # Username analysis (legacy patterns still useful for breakdown)
    username_analysis = analyze_seller_username(seller)
    base_score = 50  # Start from neutral, let avatar do the heavy lifting

    # Title analysis (if provided)
    title_analysis = {'weight_score': 0, 'mentions_weight': False}
    if titles:
        title_analysis = analyze_seller_titles(titles, category)
        base_score += title_analysis['weight_score']

    # Repeat purchase bonus (we bought from them multiple times = good source)
    repeat_bonus = 0
    if purchase_count >= 5:
        repeat_bonus = 15
    elif purchase_count >= 3:
        repeat_bonus = 10
    elif purchase_count >= 2:
        repeat_bonus = 5
    base_score += repeat_bonus

    # eBay data analysis (from uBuyFirst)
    ebay_score = 0
    ebay_analysis = {}
    if ebay_data:
        # Business account check
        is_business = str(ebay_data.get('SellerBusiness', '')).lower() == 'true'
        has_store = bool(ebay_data.get('SellerStore', '').strip())

        if is_business and has_store:
            ebay_score -= 15  # Professional seller, likely knows values
            ebay_analysis['business_penalty'] = -15
        elif is_business:
            ebay_score -= 10
            ebay_analysis['business_penalty'] = -10
        elif not has_store:
            ebay_score += 5  # Individual without store = casual seller
            ebay_analysis['individual_bonus'] = 5

        # Feedback score analysis
        try:
            feedback_count = int(ebay_data.get('FeedbackScore', 0))
            if feedback_count < 100:
                ebay_score += 10  # Low feedback = new/casual seller
                ebay_analysis['low_feedback_bonus'] = 10
            elif feedback_count < 500:
                ebay_score += 5
                ebay_analysis['low_feedback_bonus'] = 5
            elif feedback_count > 5000:
                ebay_score -= 5  # High volume seller
                ebay_analysis['high_volume_penalty'] = -5
        except (ValueError, TypeError):
            pass

        # Account age analysis (older casual accounts are good targets)
        reg_date_str = ebay_data.get('SellerRegistration', '')
        if reg_date_str:
            try:
                # Parse date like "1/24/2009+12:00:00+AM+-07:00"
                date_part = reg_date_str.split('+')[0].strip()
                from datetime import datetime
                reg_date = datetime.strptime(date_part, '%m/%d/%Y')
                years_old = (datetime.now() - reg_date).days / 365

                if years_old > 10 and not is_business:
                    ebay_score += 5  # Old individual account = established casual seller
                    ebay_analysis['old_account_bonus'] = 5
            except Exception:
                pass

        # Check for thrift/charity store names (high mispricing potential!)
        store_name = str(ebay_data.get('StoreName', '')).lower()
        seller_lower = seller.lower()
        thrift_keywords = ['svdp', 'goodwill', 'salvation', 'thrift', 'habitat', 'humane', 'charity', 'hospice']
        if any(kw in store_name or kw in seller_lower for kw in thrift_keywords):
            ebay_score += 20  # Charity/thrift stores often misprice
            ebay_analysis['thrift_store_bonus'] = 20

        # Check for dealer patterns in username (these sellers know values!)
        # Based on analysis of seller_profiles: dealers avg 25.8 score vs individuals 56.2
        dealer_patterns = [
            ('llc', -20, 'LLC business entity'),
            ('inc', -15, 'Incorporated business'),
            (' coin', -15, 'Coin dealer'),  # space prefix to avoid "coincidence"
            ('coins', -15, 'Coin dealer'),
            ('goldand', -15, 'Gold dealer'),  # goldandsilver, goldandjewelry
            ('silvershop', -15, 'Silver dealer'),
            ('pawnshop', -15, 'Pawn shop'),
            ('jewelrystore', -12, 'Jewelry store'),
            ('jewelryshop', -12, 'Jewelry shop'),
            ('exchange', -10, 'Exchange/trading business'),
            ('bullion', -15, 'Bullion dealer'),
            ('numismatic', -15, 'Numismatic dealer'),
            ('refinery', -15, 'Precious metal refinery'),
        ]

        # Check store name and seller username for dealer patterns
        check_text = f"{store_name} {seller_lower}"
        for pattern, penalty, reason in dealer_patterns:
            if pattern in check_text:
                ebay_score += penalty  # penalty is negative
                ebay_analysis['dealer_penalty'] = penalty
                ebay_analysis['dealer_reason'] = reason
                break  # Only apply worst match

    base_score += ebay_score

    # === LISTING-BASED SCORING (data-driven from 24K+ listings analysis) ===
    listing_score = 0
    listing_analysis = {}
    if listing_data:
        # --- CONDITION SCORING (BUY rate correlation) ---
        # Like new: 13.3% BUY rate | Good: 7.9% | Pre-owned Excellent: 1.7%
        condition = (listing_data.get('Condition', '') or '').lower().replace('+', ' ')
        condition_scores = {
            'like new': (15, 'Like new condition (13.3% BUY rate)'),
            'good': (10, 'Good condition (7.9% BUY rate)'),
            'unknown': (8, 'Unknown condition (casual seller)'),
            'very good': (5, 'Very good condition'),
            'new': (3, 'New condition'),
            'pre-owned - good': (-5, 'Pre-owned Good (low BUY rate)'),
            'pre-owned - excellent': (-8, 'Pre-owned Excellent (very low BUY rate)'),
            'for parts': (-20, 'For parts/not working'),
        }
        for cond_key, (cond_score, cond_reason) in condition_scores.items():
            if cond_key in condition:
                listing_score += cond_score
                if cond_score != 0:
                    listing_analysis['condition_score'] = cond_score
                    listing_analysis['condition_reason'] = cond_reason
                break

        # --- TITLE KEYWORD SCORING ---
        # Wearable: 12.2% BUY | Scrap: 8.5% | Tested: 6.6% | Lot: 5.8%
        title = (listing_data.get('Title', '') or '').lower()
        title_keywords = {
            'wearable': (15, 'Wearable keyword (12.2% BUY rate)'),
            'scrap': (10, 'Scrap keyword (8.5% BUY rate)'),
            'tested': (8, 'Tested keyword (6.6% BUY rate)'),
            'grams': (8, 'Weight in grams (verifiable)'),
            'dwt': (8, 'Weight in DWT (verifiable)'),
            'lot': (6, 'Lot listing (5.8% BUY rate)'),
            'not scrap': (-10, 'Not scrap (overpriced signal)'),
            'firm': (-5, 'Firm price (no negotiation)'),
            'no offers': (-5, 'No offers accepted'),
        }
        title_bonuses = []
        for keyword, (kw_score, kw_reason) in title_keywords.items():
            if keyword in title:
                listing_score += kw_score
                if kw_score != 0:
                    title_bonuses.append((keyword, kw_score, kw_reason))
        if title_bonuses:
            listing_analysis['title_keywords'] = title_bonuses

        # --- LISTING CHARACTERISTICS ---
        # Best offer: 5.4% vs 4.7% | No description: 3.7% vs 1.7%
        best_offer = str(listing_data.get('BestOffer', '')).lower() in ['true', 'yes', '1']
        if best_offer:
            listing_score += 5
            listing_analysis['best_offer_bonus'] = 5

        upc = listing_data.get('UPC', '')
        if upc and upc not in ['N/A', 'Does not apply', '']:
            listing_score += 8
            listing_analysis['upc_bonus'] = 8  # Verifiable product

        description = listing_data.get('Description', '')
        if not description:
            listing_score += 5
            listing_analysis['no_description_bonus'] = 5  # Casual seller signal

        cond_desc = listing_data.get('ConditionDescription', '')
        if cond_desc:
            listing_score += 3
            listing_analysis['condition_desc_bonus'] = 3

    base_score += listing_score

    # Add avatar modifier (main scoring driver now)
    base_score += avatar_modifier

    # Clamp final score
    final_score = max(0, min(100, base_score))

    # Determine estimated seller type
    patterns = username_analysis['pattern_names']

    # Check eBay data first for more accurate typing
    if ebay_data:
        is_business = str(ebay_data.get('SellerBusiness', '')).lower() == 'true'
        has_store = bool(ebay_data.get('SellerStore', '').strip())
        store_name = str(ebay_data.get('StoreName', '')).lower()

        if any(kw in store_name or kw in seller.lower() for kw in ['svdp', 'goodwill', 'salvation', 'thrift', 'habitat', 'humane', 'charity', 'hospice']):
            estimated_type = 'thrift_charity'
        elif is_business and has_store:
            estimated_type = 'business_store'
        elif is_business:
            estimated_type = 'business'
        elif 'estate_keywords' in patterns or 'pawn_thrift' in patterns:
            estimated_type = 'estate_reseller'
        elif 'antique_vintage' in patterns:
            estimated_type = 'antique_seller'
        elif 'location_based' in patterns:
            estimated_type = 'picker'
        else:
            estimated_type = 'individual'
    else:
        # Fall back to username-only analysis and avatar system
        if 'estate_keywords' in patterns or 'pawn_thrift' in patterns:
            estimated_type = 'estate_reseller'
        elif 'business_formal' in patterns:
            estimated_type = 'dealer'
        elif 'antique_vintage' in patterns:
            estimated_type = 'antique_seller'
        elif 'location_based' in patterns:
            estimated_type = 'picker'
        elif 'short_name' in patterns or 'numbers_suffix' in patterns:
            estimated_type = 'individual'
        elif avatar == 'PRO_DEALER':
            # Avatar system detected pro dealer keywords (jewelry, watches, etc.)
            estimated_type = 'dealer'
        elif avatar == 'ESTATE':
            estimated_type = 'estate_reseller'
        elif avatar == 'THRIFT':
            estimated_type = 'thrift_charity'
        elif avatar == 'PICKER':
            estimated_type = 'picker'
        elif avatar == 'ANTIQUE':
            estimated_type = 'antique_seller'
        elif avatar == 'FLIPPER':
            estimated_type = 'flipper'
        elif avatar == 'BUSINESS':
            estimated_type = 'business'
        elif avatar == 'CASUAL':
            estimated_type = 'individual'
        else:
            estimated_type = 'unknown'

    return {
        'seller': seller,
        'final_score': final_score,
        'avatar': avatar,
        'avatar_color': avatar_info.get('color', '⚪'),
        'avatar_description': avatar_info.get('description', ''),
        'all_avatars': avatar_info.get('all_matches', [avatar]),
        'estimated_type': estimated_type,
        'username_analysis': username_analysis,
        'title_analysis': title_analysis,
        'ebay_analysis': ebay_analysis,
        'listing_analysis': listing_analysis,
        'repeat_bonus': repeat_bonus,
        'score_breakdown': {
            'base': 50,
            'avatar_modifier': avatar_modifier,
            'username_patterns': username_analysis['score'] - 50,
            'weight_mentions': title_analysis.get('weight_score', 0),
            'repeat_bonus': repeat_bonus,
            'ebay_data': ebay_score,
            'listing_data': listing_score
        }
    }


def save_seller_profile(profile_data: Dict[str, Any]):
    """Save or update a seller profile"""
    try:
        seller = profile_data['seller']
        now = datetime.now().isoformat()

        db.execute("""
            INSERT INTO seller_profiles
            (seller_id, profile_score, username_patterns, category_focus, mentions_weight,
             estimated_type, avg_purchase_price, total_purchases, total_spent,
             first_seen, last_seen, score_breakdown, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(seller_id) DO UPDATE SET
                profile_score = excluded.profile_score,
                username_patterns = excluded.username_patterns,
                category_focus = excluded.category_focus,
                mentions_weight = excluded.mentions_weight,
                estimated_type = excluded.estimated_type,
                avg_purchase_price = excluded.avg_purchase_price,
                total_purchases = excluded.total_purchases,
                total_spent = excluded.total_spent,
                last_seen = excluded.last_seen,
                score_breakdown = excluded.score_breakdown,
                updated_at = excluded.updated_at
        """, (
            seller,
            profile_data.get('final_score', 50),
            json.dumps(profile_data.get('username_analysis', {}).get('pattern_names', [])),
            profile_data.get('category_focus', ''),
            1 if profile_data.get('title_analysis', {}).get('mentions_weight', False) else 0,
            profile_data.get('estimated_type', 'unknown'),
            profile_data.get('avg_purchase_price', 0),
            profile_data.get('total_purchases', 0),
            profile_data.get('total_spent', 0),
            profile_data.get('first_seen', now),
            now,
            json.dumps(profile_data.get('score_breakdown', {})),
            now
        ))
        db.commit()
        logger.debug(f"[DB] Saved seller profile: {seller} (score: {profile_data.get('final_score', 50)})")
    except Exception as e:
        logger.error(f"[DB] Error saving seller profile: {e}")


def get_seller_profile(seller_id: str) -> Optional[Dict[str, Any]]:
    """Get a seller profile by ID"""
    row = db.fetchone("SELECT * FROM seller_profiles WHERE seller_id = ?", (seller_id,))
    if row:
        profile = dict(row)
        profile['username_patterns'] = json.loads(profile.get('username_patterns', '[]'))
        profile['score_breakdown'] = json.loads(profile.get('score_breakdown', '{}'))
        return profile
    return None


def get_all_seller_profiles(min_score: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    """Get all seller profiles, optionally filtered by minimum score"""
    rows = db.fetchall("""
        SELECT * FROM seller_profiles
        WHERE profile_score >= ?
        ORDER BY profile_score DESC, total_purchases DESC
        LIMIT ?
    """, (min_score, limit))

    profiles = []
    for row in rows:
        profile = dict(row)
        profile['username_patterns'] = json.loads(profile.get('username_patterns', '[]'))
        profile['score_breakdown'] = json.loads(profile.get('score_breakdown', '{}'))
        profiles.append(profile)
    return profiles


def get_high_value_sellers(min_score: int = 60, limit: int = 50) -> List[Dict[str, Any]]:
    """Get sellers with high mispricing potential"""
    return get_all_seller_profiles(min_score=min_score, limit=limit)


def score_seller_for_listing(seller: str, title: str = '', category: str = '') -> int:
    """Quick score check for a seller - used during listing evaluation"""
    # Check if we have a cached profile
    profile = get_seller_profile(seller)
    if profile:
        return profile['profile_score']

    # Calculate on the fly
    analysis = calculate_seller_score(seller, [title] if title else None, category)
    return analysis['final_score']


def get_seller_profile_stats() -> Dict[str, Any]:
    """Get aggregate stats about seller profiles"""
    try:
        total = db.fetchone("SELECT COUNT(*) as cnt FROM seller_profiles")
        by_type = db.fetchall("""
            SELECT estimated_type, COUNT(*) as cnt, AVG(profile_score) as avg_score
            FROM seller_profiles GROUP BY estimated_type ORDER BY cnt DESC
        """)
        high_score = db.fetchone("SELECT COUNT(*) as cnt FROM seller_profiles WHERE profile_score >= 70")

        return {
            'total_profiles': total['cnt'] if total else 0,
            'high_value_count': high_score['cnt'] if high_score else 0,
            'by_type': [dict(row) for row in by_type] if by_type else []
        }
    except Exception as e:
        logger.error(f"[DB] Error getting seller stats: {e}")
        return {'total_profiles': 0, 'high_value_count': 0, 'by_type': []}


def populate_seller_profiles_from_purchases(purchase_db_path: str = None):
    """
    Populate seller profiles from purchase history database.
    This analyzes all sellers you've bought from and scores them.
    """
    import sqlite3 as sqlite3_local

    if purchase_db_path is None:
        purchase_db_path = str(DB_DIR / "purchase_history.db")

    if not os.path.exists(purchase_db_path):
        logger.error(f"[DB] Purchase history not found: {purchase_db_path}")
        return {'error': 'Purchase history database not found'}

    conn = sqlite3_local.connect(purchase_db_path)
    conn.row_factory = sqlite3_local.Row
    cur = conn.cursor()

    # Get all sellers with their purchase data
    cur.execute("""
        SELECT
            seller,
            COUNT(*) as purchase_count,
            SUM(total) as total_spent,
            AVG(total) as avg_price,
            GROUP_CONCAT(DISTINCT category) as categories,
            GROUP_CONCAT(title, '|||') as titles,
            MIN(purchase_date) as first_purchase,
            MAX(purchase_date) as last_purchase
        FROM purchases
        WHERE seller IS NOT NULL AND seller != ''
        GROUP BY seller
    """)

    sellers = cur.fetchall()
    conn.close()

    profiles_created = 0
    high_value_count = 0

    for seller_row in sellers:
        seller = seller_row['seller']
        titles = seller_row['titles'].split('|||') if seller_row['titles'] else []
        categories = seller_row['categories'] or ''
        primary_category = categories.split(',')[0] if categories else ''

        # Calculate profile score
        profile = calculate_seller_score(
            seller=seller,
            titles=titles,
            category=primary_category,
            purchase_count=seller_row['purchase_count']
        )

        # Add purchase history data
        profile['category_focus'] = categories
        profile['avg_purchase_price'] = seller_row['avg_price'] or 0
        profile['total_purchases'] = seller_row['purchase_count']
        profile['total_spent'] = seller_row['total_spent'] or 0
        profile['first_seen'] = seller_row['first_purchase']
        profile['last_seen'] = seller_row['last_purchase']

        # Save to database
        save_seller_profile(profile)
        profiles_created += 1

        if profile['final_score'] >= 70:
            high_value_count += 1

    logger.info(f"[DB] Populated {profiles_created} seller profiles ({high_value_count} high-value)")

    return {
        'profiles_created': profiles_created,
        'high_value_count': high_value_count,
        'source': purchase_db_path
    }


def analyze_new_seller(seller: str, title: str = '', category: str = '',
                       ebay_data: Dict[str, Any] = None,
                       listing_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Analyze a new seller from a listing and optionally save their profile.
    Returns the analysis with score and recommendations.

    ebay_data can include SellerBusiness, SellerStore, FeedbackScore, etc.
    listing_data can include Condition, Title, Description, BestOffer, UPC, etc.
    """
    # Check if we already have a profile (but still enhance with eBay data if provided)
    existing = get_seller_profile(seller)

    if existing and not ebay_data:
        # Use cached profile if no new eBay data
        # Get fresh avatar info for display
        avatar_info = get_seller_avatar(seller)
        return {
            'seller': seller,
            'score': existing['profile_score'],
            'type': existing['estimated_type'],
            'avatar': avatar_info['avatar'],
            'avatar_color': avatar_info.get('color', '⚪'),
            'avatar_description': avatar_info.get('description', ''),
            'is_cached': True,
            'total_purchases': existing['total_purchases'],
            'recommendation': 'HIGH_PRIORITY' if existing['profile_score'] >= 70 else
                             'MEDIUM_PRIORITY' if existing['profile_score'] >= 55 else 'NORMAL'
        }

    # Calculate fresh analysis with eBay data and listing data
    analysis = calculate_seller_score(
        seller,
        [title] if title else None,
        category,
        purchase_count=existing['total_purchases'] if existing else 0,
        ebay_data=ebay_data,
        listing_data=listing_data
    )

    result = {
        'seller': seller,
        'score': analysis['final_score'],
        'type': analysis['estimated_type'],
        'avatar': analysis['avatar'],
        'avatar_color': analysis['avatar_color'],
        'avatar_description': analysis['avatar_description'],
        'all_avatars': analysis.get('all_avatars', []),
        'is_cached': False,
        'patterns': analysis['username_analysis']['pattern_names'],
        'score_breakdown': analysis['score_breakdown'],
        'recommendation': 'HIGH_PRIORITY' if analysis['final_score'] >= 70 else
                         'MEDIUM_PRIORITY' if analysis['final_score'] >= 55 else 'NORMAL'
    }

    # Include eBay analysis if present
    if analysis.get('ebay_analysis'):
        result['ebay_analysis'] = analysis['ebay_analysis']

    # Include listing analysis if present (data-driven scoring)
    if analysis.get('listing_analysis'):
        result['listing_analysis'] = analysis['listing_analysis']

    return result
