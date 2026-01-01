"""
Database Module - Optimized SQLite with connection pooling and WAL mode
"""

import sqlite3
import threading
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
from config import DB_PATH, DATABASE, STOP_WORDS

# ============================================================
# CONNECTION POOL
# ============================================================

class DatabasePool:
    """Thread-safe SQLite connection pool with WAL mode"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._local = threading.local()
        self._initialized = True
        self._init_database()
        print(f"[DB] Database pool initialized at {DB_PATH}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(
                str(DB_PATH),
                check_same_thread=False,
                timeout=DATABASE.busy_timeout / 1000
            )
            conn.row_factory = sqlite3.Row
            
            # Apply optimizations
            if DATABASE.wal_mode:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA cache_size={DATABASE.cache_size}")
            conn.execute(f"PRAGMA synchronous={DATABASE.synchronous}")
            conn.execute(f"PRAGMA journal_size_limit={DATABASE.journal_size_limit}")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
            
            self._local.conn = conn
            
        return self._local.conn
    
    @contextmanager
    def get_cursor(self):
        """Context manager for cursor with auto-commit"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query and return cursor"""
        conn = self._get_connection()
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor
    
    def executemany(self, query: str, params_list: List[tuple]) -> sqlite3.Cursor:
        """Execute many with single commit (batch operations)"""
        conn = self._get_connection()
        cursor = conn.executemany(query, params_list)
        conn.commit()
        return cursor
    
    def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Fetch single row"""
        return self._get_connection().execute(query, params).fetchone()
    
    def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Fetch all rows"""
        return self._get_connection().execute(query, params).fetchall()
    
    def _init_database(self):
        """Initialize database tables"""
        conn = self._get_connection()
        c = conn.cursor()
        
        # Main listings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                title TEXT,
                category TEXT,
                total_price REAL,
                recommendation TEXT,
                margin REAL,
                confidence TEXT,
                reasoning TEXT,
                raw_response TEXT,
                input_data TEXT,
                user_action TEXT,
                actual_paid REAL,
                sold_price REAL,
                actual_profit REAL,
                notes TEXT,
                flagged INTEGER DEFAULT 0
            )
        ''')
        
        # Outcomes tracking
        c.execute('''
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT,
                ai_said TEXT,
                user_did TEXT,
                outcome TEXT,
                profit_loss REAL,
                notes TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            )
        ''')
        
        # Daily stats
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_analyzed INTEGER DEFAULT 0,
                buy_count INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                research_count INTEGER DEFAULT 0,
                total_bought INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                api_cost REAL DEFAULT 0
            )
        ''')
        
        # Keyword performance
        c.execute('''
            CREATE TABLE IF NOT EXISTS keyword_performance (
                keyword TEXT PRIMARY KEY,
                times_seen INTEGER DEFAULT 0,
                times_bought INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                avg_margin REAL DEFAULT 0,
                last_seen DATETIME
            )
        ''')
        
        # Seller tracking
        c.execute('''
            CREATE TABLE IF NOT EXISTS sellers (
                seller_name TEXT PRIMARY KEY,
                times_seen INTEGER DEFAULT 0,
                times_bought INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                avg_deal_quality REAL DEFAULT 0,
                last_seen DATETIME,
                notes TEXT
            )
        ''')
        
        # Incoming listings log
        c.execute('''
            CREATE TABLE IF NOT EXISTS incoming_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                title TEXT,
                total_price REAL,
                category TEXT,
                alias TEXT,
                status TEXT DEFAULT 'queued',
                recommendation TEXT,
                metal TEXT,
                metal_purity TEXT,
                brand TEXT,
                style TEXT,
                item_type TEXT,
                condition_desc TEXT,
                feedback_rating REAL,
                seller_country TEXT,
                title_keywords TEXT,
                input_json TEXT
            )
        ''')
        
        # Keyword patterns
        c.execute('''
            CREATE TABLE IF NOT EXISTS keyword_patterns (
                keyword TEXT PRIMARY KEY,
                category TEXT,
                times_seen INTEGER DEFAULT 0,
                times_analyzed INTEGER DEFAULT 0,
                buy_count INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                research_count INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0,
                pass_rate REAL DEFAULT 0,
                last_seen DATETIME,
                notes TEXT
            )
        ''')
        
        # Item spec patterns
        c.execute('''
            CREATE TABLE IF NOT EXISTS itemspec_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_name TEXT,
                field_value TEXT,
                category TEXT,
                times_seen INTEGER DEFAULT 0,
                buy_count INTEGER DEFAULT 0,
                pass_count INTEGER DEFAULT 0,
                pass_rate REAL DEFAULT 0,
                avg_margin REAL DEFAULT 0,
                last_seen DATETIME,
                UNIQUE(field_name, field_value, category)
            )
        ''')
        
        # Create indexes for common queries
        c.execute('CREATE INDEX IF NOT EXISTS idx_listings_timestamp ON listings(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(category)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_listings_recommendation ON listings(recommendation)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_incoming_timestamp ON incoming_listings(timestamp)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_keyword_patterns_category ON keyword_patterns(category)')
        
        # Auto-migrate: Add missing columns to existing tables
        self._migrate_columns(c, 'listings', {
            'raw_response': 'TEXT',
            'input_data': 'TEXT',
            'confidence': 'TEXT',
            'reasoning': 'TEXT',
            'margin': 'REAL',
            'flagged': 'INTEGER DEFAULT 0'
        })
        
        conn.commit()
        print("[DB] Tables and indexes initialized")
    
    def _migrate_columns(self, cursor, table: str, columns: dict):
        """Add missing columns to existing table"""
        # Get existing columns
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        
        # Add missing columns
        for col_name, col_type in columns.items():
            if col_name not in existing:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    print(f"[DB] Added missing column: {table}.{col_name}")
                except Exception as e:
                    print(f"[DB] Column {col_name} might already exist: {e}")


# Global pool instance
db = DatabasePool()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def extract_title_keywords(title: str) -> List[str]:
    """Extract meaningful keywords from a listing title"""
    if not title:
        return []
    
    title = title.lower()
    title = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in title)
    words = title.split()
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    
    # Extract bigrams with important terms
    bigrams = []
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i+1]}"
        if any(term in bigram for term in ['14k', '18k', '10k', '925', 'sterling', 'gold', 'silver']):
            bigrams.append(bigram)
    
    return list(set(keywords + bigrams))


def save_listing(listing: Dict[str, Any]) -> bool:
    """Save a listing to the database"""
    try:
        db.execute('''
            INSERT OR REPLACE INTO listings 
            (id, timestamp, title, category, total_price, recommendation, margin, 
             confidence, reasoning, raw_response, input_data, flagged)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            listing.get('id'),
            listing.get('timestamp', datetime.now().isoformat()),
            listing.get('title'),
            listing.get('category'),
            listing.get('total_price'),
            listing.get('recommendation'),
            listing.get('margin'),
            listing.get('confidence'),
            listing.get('reasoning'),
            listing.get('raw_response'),
            str(listing.get('input_data', {})),
            1 if listing.get('flagged') else 0
        ))
        
        # Update daily stats
        today = datetime.now().strftime('%Y-%m-%d')
        rec = listing.get('recommendation', 'RESEARCH')
        
        db.execute('''
            INSERT INTO daily_stats (date, total_analyzed, buy_count, pass_count, research_count)
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_analyzed = total_analyzed + 1,
                buy_count = buy_count + ?,
                pass_count = pass_count + ?,
                research_count = research_count + ?
        ''', (
            today,
            1 if rec == 'BUY' else 0,
            1 if rec == 'PASS' else 0,
            1 if rec == 'RESEARCH' else 0,
            1 if rec == 'BUY' else 0,
            1 if rec == 'PASS' else 0,
            1 if rec == 'RESEARCH' else 0
        ))
        
        return True
    except Exception as e:
        print(f"[DB] Error saving listing: {e}")
        return False


def log_incoming_listing(data: Dict, category: str, status: str = 'queued') -> Optional[int]:
    """Log every incoming listing for pattern analysis"""
    try:
        import json
        title = data.get('Title', '')
        keywords = extract_title_keywords(title)
        
        cursor = db.execute('''
            INSERT INTO incoming_listings 
            (title, total_price, category, alias, status, metal, metal_purity, 
             brand, style, item_type, condition_desc, feedback_rating, 
             seller_country, title_keywords, input_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            title,
            data.get('TotalPrice', data.get('ItemPrice', 0)),
            category,
            data.get('Alias', ''),
            status,
            data.get('Metal', ''),
            data.get('Metal Purity', ''),
            data.get('Brand', ''),
            data.get('Style', ''),
            data.get('Type', ''),
            data.get('Condition', ''),
            data.get('FeedbackScore', 0),
            data.get('SellerCountry', ''),
            ','.join(keywords),
            json.dumps({k: v for k, v in data.items() if k != 'images'})
        ))
        
        # Update keyword patterns
        for kw in keywords:
            db.execute('''
                INSERT INTO keyword_patterns (keyword, category, times_seen, last_seen)
                VALUES (?, ?, 1, datetime('now'))
                ON CONFLICT(keyword) DO UPDATE SET
                    times_seen = times_seen + 1,
                    last_seen = datetime('now')
            ''', (kw, category))
        
        return cursor.lastrowid
    except Exception as e:
        print(f"[DB] Error logging incoming: {e}")
        return None


def update_pattern_outcome(title: str, category: str, recommendation: str) -> None:
    """Update keyword patterns with analysis outcome"""
    try:
        keywords = extract_title_keywords(title)
        
        for kw in keywords:
            buy_inc = 1 if recommendation == 'BUY' else 0
            pass_inc = 1 if recommendation == 'PASS' else 0
            research_inc = 1 if recommendation == 'RESEARCH' else 0
            
            db.execute('''
                UPDATE keyword_patterns 
                SET times_analyzed = times_analyzed + 1,
                    buy_count = buy_count + ?,
                    pass_count = pass_count + ?,
                    research_count = research_count + ?,
                    pass_rate = CAST(pass_count + ? AS REAL) / CAST(times_analyzed + 1 AS REAL)
                WHERE keyword = ?
            ''', (buy_inc, pass_inc, research_inc, pass_inc, kw))
    except Exception as e:
        print(f"[DB] Error updating patterns: {e}")


def get_analytics() -> Dict[str, Any]:
    """Get comprehensive analytics from the database"""
    try:
        analytics = {}
        
        # Overall stats
        row = db.fetchone('SELECT COUNT(*) as total FROM listings')
        analytics['total_listings'] = row['total'] if row else 0
        
        row = db.fetchone('SELECT COUNT(*) as total FROM listings WHERE recommendation = "BUY"')
        analytics['total_buys'] = row['total'] if row else 0
        
        row = db.fetchone('SELECT COUNT(*) as total FROM listings WHERE recommendation = "PASS"')
        analytics['total_passes'] = row['total'] if row else 0
        
        row = db.fetchone('SELECT COUNT(*) as total FROM outcomes WHERE user_did = "BOUGHT"')
        analytics['actual_purchases'] = row['total'] if row else 0
        
        row = db.fetchone('SELECT SUM(profit_loss) as total FROM outcomes WHERE outcome = "WIN"')
        analytics['total_profit'] = row['total'] if row and row['total'] else 0
        
        # By category
        rows = db.fetchall('''
            SELECT category, 
                   COUNT(*) as count,
                   SUM(CASE WHEN recommendation = "BUY" THEN 1 ELSE 0 END) as buys
            FROM listings 
            GROUP BY category
        ''')
        analytics['by_category'] = [dict(row) for row in rows]
        
        # Last 7 days trend
        rows = db.fetchall('''
            SELECT date, total_analyzed, buy_count, pass_count, total_profit, api_cost
            FROM daily_stats 
            ORDER BY date DESC 
            LIMIT 7
        ''')
        analytics['daily_trend'] = [dict(row) for row in rows]
        
        # Recent listings
        rows = db.fetchall('''
            SELECT id, timestamp, title, category, recommendation, margin
            FROM listings 
            ORDER BY timestamp DESC 
            LIMIT 20
        ''')
        analytics['recent'] = [dict(row) for row in rows]
        
        analytics['top_wins'] = []
        analytics['ai_accuracy'] = 'N/A'
        
        return analytics
    except Exception as e:
        print(f"[DB] Analytics error: {e}")
        return {
            "total_listings": 0, "total_buys": 0, "total_passes": 0,
            "actual_purchases": 0, "total_profit": 0, "ai_accuracy": "N/A",
            "by_category": [], "daily_trend": [], "recent": [], "top_wins": []
        }


def get_pattern_analytics() -> Dict[str, Any]:
    """Get keyword pattern analytics"""
    try:
        # High-pass keywords (candidates for negative filters)
        high_pass = db.fetchall('''
            SELECT keyword, category, times_seen, times_analyzed, 
                   pass_count, pass_rate
            FROM keyword_patterns
            WHERE times_analyzed >= 5 AND pass_rate >= 0.8
            ORDER BY pass_rate DESC, times_analyzed DESC
            LIMIT 50
        ''')
        
        # High-buy keywords (good indicators)
        high_buy = db.fetchall('''
            SELECT keyword, category, times_seen, times_analyzed, 
                   buy_count, 
                   CAST(buy_count AS REAL) / CAST(times_analyzed AS REAL) as buy_rate
            FROM keyword_patterns
            WHERE times_analyzed >= 3 AND buy_count >= 1
            ORDER BY buy_rate DESC, buy_count DESC
            LIMIT 50
        ''')
        
        # Category breakdown
        by_category = db.fetchall('''
            SELECT category, 
                   COUNT(*) as total_keywords,
                   SUM(times_seen) as total_seen,
                   SUM(times_analyzed) as total_analyzed
            FROM keyword_patterns
            GROUP BY category
        ''')
        
        return {
            'high_pass_keywords': [dict(r) for r in high_pass],
            'high_buy_keywords': [dict(r) for r in high_buy],
            'by_category': [dict(r) for r in by_category]
        }
    except Exception as e:
        print(f"[DB] Pattern analytics error: {e}")
        return {'high_pass_keywords': [], 'high_buy_keywords': [], 'by_category': []}
