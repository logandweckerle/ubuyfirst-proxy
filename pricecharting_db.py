"""
PriceCharting Database Module
SQLite-based price lookups with Full-Text Search (FTS5)

Features:
- Downloads CSV from PriceCharting subscription
- Stores in SQLite with FTS5 for fast fuzzy title matching
- Auto-refreshes daily in background
- Supports: Pokemon, LEGO, MTG, Yu-Gi-Oh, One Piece, Lorcana

Usage:
    from pricecharting_db import lookup_product, get_db_stats, refresh_database
    
    # Lookup a product
    result = lookup_product("Pokemon Evolving Skies Booster Box", "pokemon")
    
    # Manual refresh
    refresh_database()
"""

import os
import re
import csv
import json
import sqlite3
import threading
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from io import StringIO

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on system environment

# ============================================================
# CONFIGURATION
# ============================================================

# API key from environment
PRICECHARTING_API_KEY = os.getenv("PRICECHARTING_API_KEY", "")

# Database path
DB_PATH = Path(__file__).parent / "pricecharting_prices.db"

# CSV Download base URL
CSV_BASE_URL = "https://www.pricecharting.com/price-guide/download-custom"

# Categories to download (PriceCharting console/category names)
# Format: { "internal_category": ["pricecharting-console-slug", ...] }
CATEGORIES = {
    # Trading Card Games - use correct PriceCharting slugs
    "pokemon": ["pokemon-cards"],  # Fixed: was "pokemon" (console games), now "pokemon-cards" (TCG)
    "mtg": ["magic-cards"],  # Fixed: was "magic-the-gathering"
    "yugioh": ["yugioh-cards"],  # Fixed: was "yu-gi-oh"
    "onepiece": ["one-piece-card-game"],
    "lorcana": ["disney-lorcana"],

    # LEGO
    "lego": ["lego"],

    # Video Games - Nintendo
    "videogames": [
        "nes",
        "super-nintendo",
        "nintendo-64",
        "gamecube",
        "wii",
        "wii-u",
        "nintendo-switch",
        "game-boy",
        "game-boy-color",
        "game-boy-advance",
        "nintendo-ds",
        "nintendo-3ds",
        # Sony
        "playstation",
        "playstation-2",
        "playstation-3",
        "playstation-4",
        "playstation-5",
        "psp",
        "playstation-vita",
        # Microsoft
        "xbox",
        "xbox-360",
        "xbox-one",
        "xbox-series-x",
        # Sega
        "sega-genesis",
        "sega-cd",
        "sega-saturn",
        "sega-dreamcast",
        "game-gear",
    ],
}

# Buy threshold - use category-specific thresholds from constants
# TCG/Pokemon: 70%, LEGO: 70%, VideoGames: 65%
from utils.constants import get_category_threshold, CATEGORY_THRESHOLDS
# Default fallback (only used if category not specified)
BUY_THRESHOLD = 0.65

# Refresh interval (24 hours) - not used since we're using API
REFRESH_INTERVAL_HOURS = 24

# ============================================================
# DATABASE SETUP
# ============================================================

def get_db_connection() -> sqlite3.Connection:
    """Get database connection with row factory"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize database tables"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Main products table
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            console_name TEXT,
            category TEXT,
            loose_price INTEGER DEFAULT 0,
            cib_price INTEGER DEFAULT 0,
            new_price INTEGER DEFAULT 0,
            graded_price INTEGER DEFAULT 0,
            upc TEXT,
            asin TEXT,
            release_date TEXT,
            updated_at TEXT
        )
    ''')
    
    # Create indexes for fast lookups
    c.execute('CREATE INDEX IF NOT EXISTS idx_console ON products(console_name)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_category ON products(category)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_upc ON products(upc)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_new_price ON products(new_price)')
    
    # FTS5 virtual table for fuzzy text search
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
            product_name,
            console_name,
            category,
            content='products',
            content_rowid='rowid'
        )
    ''')
    
    # Triggers to keep FTS in sync
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
            INSERT INTO products_fts(rowid, product_name, console_name, category)
            VALUES (new.rowid, new.product_name, new.console_name, new.category);
        END
    ''')
    
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, product_name, console_name, category)
            VALUES('delete', old.rowid, old.product_name, old.console_name, old.category);
        END
    ''')
    
    c.execute('''
        CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, product_name, console_name, category)
            VALUES('delete', old.rowid, old.product_name, old.console_name, old.category);
            INSERT INTO products_fts(rowid, product_name, console_name, category)
            VALUES (new.rowid, new.product_name, new.console_name, new.category);
        END
    ''')
    
    # Metadata table for tracking refreshes
    c.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("[PC-DB] Database initialized")


# ============================================================
# CSV DOWNLOAD & PARSING
# ============================================================

def download_csv(category_id: str) -> Optional[str]:
    """Download CSV for a specific category from PriceCharting"""
    if not PRICECHARTING_API_KEY:
        print(f"[PC-DB] ERROR: No API key configured")
        return None
    
    # FIXED: Use 'category=' not 'console=' for PriceCharting API
    url = f"{CSV_BASE_URL}?t={PRICECHARTING_API_KEY}&category={category_id}"
    
    try:
        print(f"[PC-DB] Downloading: {category_id}...")
        req = urllib.request.Request(url, headers={
            'User-Agent': 'eBayArbitrage/1.0'
        })
        
        with urllib.request.urlopen(req, timeout=60) as response:
            content = response.read().decode('utf-8-sig')
            return content
            
    except urllib.error.HTTPError as e:
        print(f"[PC-DB] HTTP Error {e.code} downloading {category_id}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"[PC-DB] URL Error downloading {category_id}: {e.reason}")
        return None
    except Exception as e:
        print(f"[PC-DB] Error downloading {category_id}: {e}")
        return None



def detect_category_from_console(console_name: str) -> str:
    """Detect internal category from PriceCharting console name"""
    console_lower = console_name.lower()

    # TCG categories
    if 'pokemon' in console_lower:
        return 'pokemon'
    elif 'magic' in console_lower:
        return 'mtg'
    elif 'yugioh' in console_lower or 'yu-gi-oh' in console_lower:
        return 'yugioh'
    elif 'one piece' in console_lower:
        return 'onepiece'
    elif 'lorcana' in console_lower:
        return 'lorcana'
    elif 'lego' in console_lower:
        return 'lego'
    else:
        # Default to videogames for consoles
        return 'videogames'


def parse_csv_and_insert(csv_content: str, category: str, conn: sqlite3.Connection) -> int:
    """Parse CSV content and insert/update products in database"""
    if not csv_content:
        return 0
    
    c = conn.cursor()
    count = 0
    
    # Debug: Print first few lines of CSV to verify content
    lines = csv_content.split('\n')[:5]
    print(f"[PC-DB] CSV Preview for {category}:")
    for line in lines:
        print(f"  {line[:100]}...")
    
    try:
        reader = csv.DictReader(StringIO(csv_content))
        
        for row in reader:
            try:
                # Extract fields (CSV column names match API response)
                product_id = row.get('id', '')
                if not product_id:
                    continue
                
                product_name = row.get('product-name', '')
                console_name = row.get('console-name', '')
                
                # Parse prices - handle both dollar strings and penny integers
                def parse_price(val):
                    if not val:
                        return 0
                    val_str = str(val).strip()
                    if val_str.startswith('$'):
                        try:
                            return int(float(val_str.replace('$', '').replace(',', '')) * 100)
                        except:
                            return 0
                    else:
                        try:
                            return int(float(val_str))
                        except:
                            return 0

                loose_price = parse_price(row.get('loose-price', 0))
                cib_price = parse_price(row.get('cib-price', 0))
                new_price = parse_price(row.get('new-price', 0))
                graded_price = parse_price(row.get('graded-price', 0))
                
                upc = row.get('upc', '')
                asin = row.get('asin', '')
                release_date = row.get('release-date', '')
                
                # Upsert product
                # Auto-detect category from console name
                detected_category = detect_category_from_console(console_name)

                c.execute('''
                    INSERT OR REPLACE INTO products
                    (id, product_name, console_name, category, loose_price, cib_price,
                     new_price, graded_price, upc, asin, release_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    product_id, product_name, console_name, detected_category,
                    loose_price, cib_price, new_price, graded_price,
                    upc, asin, release_date, datetime.now().isoformat()
                ))
                
                count += 1
                
            except Exception as e:
                # Skip bad rows
                continue
        
        conn.commit()
        
    except Exception as e:
        print(f"[PC-DB] CSV parsing error: {e}")
    
    return count


def refresh_database(force: bool = False) -> Dict:
    """
    Download fresh data from PriceCharting and update database
    
    Args:
        force: If True, refresh even if recently updated
    
    Returns:
        Dict with refresh statistics
    """
    stats = {
        "success": False,
        "categories_updated": 0,
        "products_total": 0,
        "errors": [],
        "timestamp": datetime.now().isoformat()
    }
    
    if not PRICECHARTING_API_KEY:
        stats["errors"].append("No PRICECHARTING_API_KEY in environment")
        print("[PC-DB] ERROR: Set PRICECHARTING_API_KEY in .env file")
        return stats
    
    # Check if refresh needed
    if not force:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM metadata WHERE key = 'last_refresh'")
        row = c.fetchone()
        conn.close()
        
        if row:
            last_refresh = datetime.fromisoformat(row['value'])
            hours_since = (datetime.now() - last_refresh).total_seconds() / 3600
            
            if hours_since < REFRESH_INTERVAL_HOURS:
                print(f"[PC-DB] Skipping refresh - last updated {hours_since:.1f}h ago")
                stats["success"] = True
                stats["skipped"] = True
                return stats
    
    print("[PC-DB] Starting database refresh...")
    init_database()
    
    conn = get_db_connection()
    
    # Download each category
    for category, console_ids in CATEGORIES.items():
        for console_id in console_ids:
            csv_content = download_csv(console_id)
            
            if csv_content:
                count = parse_csv_and_insert(csv_content, category, conn)
                stats["products_total"] += count
                print(f"[PC-DB] {console_id}: {count:,} products loaded")
            else:
                stats["errors"].append(f"Failed to download {console_id}")
        
        stats["categories_updated"] += 1
    
    # Update last refresh timestamp
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_refresh', ?)
    ''', (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    
    stats["success"] = len(stats["errors"]) == 0
    print(f"[PC-DB] Refresh complete: {stats['products_total']:,} total products")
    
    return stats


# ============================================================
# PRODUCT LOOKUP
# ============================================================

def normalize_search_title(title: str) -> str:
    """Normalize title for better FTS matching"""
    title = title.lower()
    
    # Remove common eBay noise
    noise = [
        'new', 'sealed', 'factory sealed', 'brand new', 'mint', 'nm',
        'authentic', 'official', 'genuine', 'real', 'legit', '100%',
        'free shipping', 'fast ship', 'ships fast', 'same day',
        'lot', 'bundle', 'collection', 'rare', 'vintage', 'hot',
        'no reserve', 'nr', 'l@@k', 'look', 'wow', '!!!', 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â¥',
        'great deal', 'must see', 'invest', 'psa', 'cgc', 'bgs',
    ]
    
    for word in noise:
        title = title.replace(word, ' ')
    
    # Standardize common terms
    replacements = {
        'pokemon': 'pokemon',
        'pokÃƒÆ’Ã‚Â©mon': 'pokemon',
        'pkmn': 'pokemon',
        'mtg': 'magic',
        'magic the gathering': 'magic',
        'yu-gi-oh': 'yugioh',
        'yu gi oh': 'yugioh',
        'yugi-oh': 'yugioh',
        'booster box': 'booster box',
        'bb': 'booster box',
        'etb': 'elite trainer box',
        'elite trainer': 'elite trainer box',
    }
    
    for old, new in replacements.items():
        title = title.replace(old, new)
    
    # Remove special characters but keep spaces
    title = re.sub(r'[^\w\s]', ' ', title)
    
    # Collapse whitespace
    title = ' '.join(title.split())
    
    return title.strip()


def detect_category_from_title(title: str) -> Optional[str]:
    """Detect product category from eBay title"""
    title_lower = title.lower()
    
    if any(x in title_lower for x in ['pokemon', 'pkmn', 'pikachu', 'charizard', 'pokÃƒÆ’Ã‚Â©mon']):
        return 'pokemon'
    elif any(x in title_lower for x in ['magic', 'mtg', 'wizards of the coast']):
        return 'mtg'
    elif any(x in title_lower for x in ['yugioh', 'yu-gi-oh', 'yu gi oh', 'konami']):
        return 'yugioh'
    elif any(x in title_lower for x in ['one piece', 'onepiece', 'op-0', 'op0', 'op01', 'op02', 'op03', 'op04', 'op05', 'op06', 'op07', 'op08', 'op09', 'op10', 'op11', 'op12', 'op13', 'op14', 'op15', 'op16', 'op17', 'op18', 'op19', 'op20']):
        return 'onepiece'
    elif any(x in title_lower for x in ['lorcana', 'disney lorcana']):
        return 'lorcana'
    elif 'lego' in title_lower:
        return 'lego'
    
    return None


def load_price_overrides() -> Dict:
    """Load local price overrides from JSON file"""
    override_path = Path(__file__).parent / "price_overrides.json"
    try:
        if override_path.exists():
            with open(override_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[PC] Warning: Could not load price overrides: {e}")
    return {}


def check_local_override(title: str, category: str, listing_price: float) -> Optional[Dict]:
    """
    Check if we have a local price override for this product.
    Returns result dict if found, None otherwise.
    """
    overrides = load_price_overrides()
    title_lower = title.lower()

    if category == 'lego':
        # Extract LEGO set number
        set_match = re.search(r'\b(\d{4,5})\b', title)
        if set_match:
            set_number = set_match.group(1)
            lego_overrides = overrides.get('lego', {})
            if set_number in lego_overrides:
                data = lego_overrides[set_number]
                market_price = data['market_price']
                buy_target = market_price * get_category_threshold('lego')  # 70%
                margin = buy_target - listing_price
                print(f"[PC] LOCAL OVERRIDE: LEGO {set_number} @ ${market_price} ({data.get('notes', '')})")
                return {
                    'found': True,
                    'product_name': f"LEGO #{set_number}",
                    'product_id': f"local_{set_number}",
                    'console_name': 'LEGO',
                    'category': 'lego',
                    'market_price': market_price,
                    'buy_target': buy_target,
                    'margin': margin,
                    'confidence': 'High',
                    'source': 'local_override',
                    'notes': data.get('notes', ''),
                    'updated': data.get('updated', '')
                }

    elif category in ['pokemon', 'tcg']:
        pokemon_overrides = overrides.get('pokemon', {})
        # Build lookup key from title
        # Format: setname_producttype (e.g., "evolving_skies_booster_box")

        # TCG abbreviation expansions - check both abbreviation and full form
        tcg_expansions = {
            'etb': ['etb', 'elite trainer box'],
            'bb': ['bb', 'booster box'],
            'upc': ['upc', 'ultra premium collection'],
            'pc': ['pc', 'premium collection'],
        }

        def part_matches(part, text):
            """Check if part matches - handles abbreviation expansion"""
            if part in tcg_expansions:
                return any(exp in text for exp in tcg_expansions[part])
            return part in text

        for key, data in pokemon_overrides.items():
            if key.startswith('_'):  # Skip metadata
                continue
            key_parts = key.replace('_', ' ').split()
            if all(part_matches(part, title_lower) for part in key_parts):
                market_price = data['market_price']
                buy_target = market_price * get_category_threshold('tcg')  # 70%
                margin = buy_target - listing_price
                print(f"[PC] LOCAL OVERRIDE: Pokemon '{key}' @ ${market_price} ({data.get('notes', '')})")
                return {
                    'found': True,
                    'product_name': key.replace('_', ' ').title(),
                    'product_id': f"local_{key}",
                    'console_name': 'Pokemon',
                    'category': 'pokemon',
                    'market_price': market_price,
                    'buy_target': buy_target,
                    'margin': margin,
                    'confidence': 'High',
                    'source': 'local_override',
                    'notes': data.get('notes', ''),
                    'updated': data.get('updated', '')
                }

    elif category == 'videogames':
        videogame_overrides = overrides.get('videogames', {})
        # Format: console_title_condition (e.g., "snes_chrono_trigger_cib")
        for key, data in videogame_overrides.items():
            if key.startswith('_'):  # Skip metadata keys like _example
                continue
            key_parts = key.replace('_', ' ').split()
            # All parts must be present in title
            if all(part in title_lower for part in key_parts):
                market_price = data['market_price']
                buy_target = market_price * get_category_threshold('videogames')  # 65%
                margin = buy_target - listing_price
                # Extract console from key (first part)
                console = key.split('_')[0].upper()
                print(f"[PC] LOCAL OVERRIDE: VideoGame '{key}' @ ${market_price} ({data.get('notes', '')})")
                return {
                    'found': True,
                    'product_name': key.replace('_', ' ').title(),
                    'product_id': f"local_{key}",
                    'console_name': console,
                    'category': 'videogames',
                    'market_price': market_price,
                    'buy_target': buy_target,
                    'margin': margin,
                    'confidence': 'High',
                    'source': 'local_override',
                    'notes': data.get('notes', ''),
                    'updated': data.get('updated', '')
                }

    return None


def lookup_product(title: str, category: Optional[str] = None, listing_price: float = 0, upc: str = None) -> Dict:
    """
    Look up product price - tries local overrides first, then UPC, then title search.

    Args:
        title: eBay listing title
        category: Optional category hint (pokemon, lego, mtg, etc.)
        listing_price: Current listing price for margin calculation
        upc: Optional UPC barcode for direct lookup

    Returns:
        Dict with: found, product_name, market_price, buy_target, margin, confidence, etc.
    """
    # Auto-detect category if not provided
    if not category:
        category = detect_category_from_title(title)

    # CHECK LOCAL OVERRIDES FIRST (fastest, most accurate)
    local_result = check_local_override(title, category, listing_price)
    if local_result:
        return local_result
    
    # LEGO: Skip UPC lookup entirely - set number search is more reliable
    # UPC lookups for LEGO often fail (404) and waste time
    if category == 'lego':
        print(f"[PC] LEGO detected - skipping UPC, using set number search")
        result = api_lookup_product(title, listing_price, category)
        result['category'] = category
        return result
    
    # TRY UPC FIRST for non-LEGO categories - most accurate method
    if upc and len(str(upc)) >= 8:
        print(f"[PC] Trying UPC lookup first: {upc}")
        upc_result = api_lookup_by_upc(upc, listing_price)
        if upc_result.get('found') and upc_result.get('market_price'):
            upc_result['category'] = category or upc_result.get('category', 'tcg')
            return upc_result
        else:
            print(f"[PC] UPC lookup failed: {upc_result.get('error', 'unknown')}, falling back to title search")
    
    # FALL BACK TO TITLE SEARCH
    supported_categories = ['lego', 'pokemon', 'mtg', 'yugioh', 'onepiece', 'lorcana', 'tcg', 'videogames']
    
    if category in supported_categories:
        result = api_lookup_product(title, listing_price, category)
        result['category'] = category
        return result
    
    # For unsupported categories, return not found
    return {
        'found': False,
        'product_name': None,
        'product_id': None,
        'console_name': None,
        'category': category,
        'market_price': None,
        'buy_target': None,
        'margin': None,
        'confidence': 'None',
        'source': 'api',
        'error': f'Category {category} not supported for price lookup'
    }


def lookup_by_upc(upc: str, listing_price: float = 0) -> Dict:
    """Look up product by UPC code"""
    result = {
        'found': False,
        'error': None
    }
    
    if not upc:
        result['error'] = 'No UPC provided'
        return result
    
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT * FROM products WHERE upc = ?', (upc,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            result['error'] = 'UPC not found'
            return result
        
        # Same price calculation as lookup_product
        new_price = row['new_price'] / 100 if row['new_price'] else 0
        cib_price = row['cib_price'] / 100 if row['cib_price'] else 0
        loose_price = row['loose_price'] / 100 if row['loose_price'] else 0

        # VIDEO GAMES: Use CIB price by default (most eBay listings are CIB, not sealed)
        console_name = row['console_name'].lower() if row['console_name'] else ''
        is_videogame = any(x in console_name for x in [
            'nintendo', 'playstation', 'xbox', 'sega', 'game boy', 'gamecube',
            'wii', 'switch', 'nes', 'snes', 'n64', 'genesis', 'dreamcast', 'saturn',
            'ps1', 'ps2', 'ps3', 'ps4', 'ps5', 'psp', 'vita', '3ds', 'ds', 'gba'
        ])
        if is_videogame:
            market_price = cib_price or loose_price or new_price  # CIB first for games
        else:
            market_price = new_price or cib_price or loose_price  # New first for TCG/LEGO

        # Use category-specific threshold
        cat_threshold = get_category_threshold(row['category'])
        buy_target = market_price * cat_threshold
        margin = buy_target - listing_price if listing_price > 0 else None

        result.update({
            'found': True,
            'product_name': row['product_name'],
            'product_id': row['id'],
            'console_name': row['console_name'],
            'category': row['category'],
            'market_price': market_price,
            'buy_target': buy_target,
            'margin': margin,
            'confidence': 'High',  # UPC match is definitive
            'source': 'database_upc',
        })
        
    except Exception as e:
        result['error'] = str(e)
    
    return result


# ============================================================
# REAL-TIME API LOOKUP (for LEGO and products not in CSV)
# ============================================================

def api_lookup_by_upc(upc: str, listing_price: float = 0) -> Dict:
    """
    Direct product lookup by UPC - most accurate method.
    
    Args:
        upc: UPC barcode number
        listing_price: Current listing price for margin calculation
    
    Returns:
        Dict with product details and pricing
    """
    result = {
        'found': False,
        'product_name': None,
        'product_id': None,
        'console_name': None,
        'category': None,
        'market_price': None,
        'buy_target': None,
        'margin': None,
        'confidence': 'None',
        'source': 'api_upc',
        'error': None
    }
    
    if not PRICECHARTING_API_KEY:
        result['error'] = 'No API key configured'
        return result
    
    if not upc or len(upc) < 8:
        result['error'] = 'Invalid UPC'
        return result
    
    # Clean UPC - remove any non-digits
    clean_upc = re.sub(r'[^\d]', '', str(upc))
    
    url = f"https://www.pricecharting.com/api/product?t={PRICECHARTING_API_KEY}&upc={clean_upc}"
    
    try:
        print(f"[PC-API] UPC Lookup: {clean_upc}")
        req = urllib.request.Request(url, headers={
            'User-Agent': 'eBayArbitrage/1.0'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get('status') != 'success':
                result['error'] = data.get('error-message', 'UPC not found')
                return result
            
            # Prices are in pennies
            new_price = int(data.get('new-price', 0) or 0) / 100
            cib_price = int(data.get('cib-price', 0) or 0) / 100
            loose_price = int(data.get('loose-price', 0) or 0) / 100

            # Get console name first so we can determine correct price priority
            console_name = data.get('console-name', '').lower()

            # VIDEO GAMES: Use CIB price by default (most eBay listings are CIB, not sealed)
            is_videogame = any(x in console_name for x in [
                'nintendo', 'playstation', 'xbox', 'sega', 'game boy', 'gamecube',
                'wii', 'switch', 'nes', 'snes', 'n64', 'genesis', 'dreamcast', 'saturn',
                'ps1', 'ps2', 'ps3', 'ps4', 'ps5', 'psp', 'vita', '3ds', 'ds', 'gba'
            ])

            if is_videogame:
                market_price = cib_price or loose_price or new_price  # CIB first for games
                print(f"[PC-API] Video game detected - using CIB price: ${cib_price} (new: ${new_price})")
            else:
                market_price = new_price or cib_price or loose_price  # New first for TCG/sealed

            if market_price == 0:
                result['error'] = 'No price data for UPC'
                result['found'] = True
                result['product_name'] = data.get('product-name', '')
                result['console_name'] = data.get('console-name', '')
                result['confidence'] = 'Low'
                return result

            # Determine category first for threshold calculation
            if 'pokemon' in console_name:
                category = 'pokemon'
            elif 'lego' in console_name:
                category = 'lego'
            elif 'magic' in console_name:
                category = 'mtg'
            elif 'yugioh' in console_name or 'yu-gi-oh' in console_name:
                category = 'yugioh'
            elif 'one piece' in console_name:
                category = 'onepiece'
            elif 'lorcana' in console_name:
                category = 'lorcana'
            else:
                category = 'tcg'

            # Use category-specific threshold (TCG/Pokemon: 70%, LEGO: 70%, etc)
            cat_threshold = get_category_threshold(category)
            buy_target = market_price * cat_threshold
            margin = buy_target - listing_price if listing_price > 0 else None

            result.update({
                'found': True,
                'product_name': data.get('product-name', ''),
                'product_id': data.get('id', ''),
                'console_name': data.get('console-name', ''),
                'category': category,
                'market_price': market_price,
                'buy_target': buy_target,
                'margin': margin,
                'confidence': 'High',  # UPC match is definitive
                'new_price': new_price,
                'cib_price': cib_price,
                'loose_price': loose_price,
                'upc': clean_upc,
            })
            
            print(f"[PC-API] UPC Match: {result['product_name']} @ ${market_price:,.0f}")
            
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result['error'] = 'UPC not found in database'
        else:
            result['error'] = f'HTTP Error {e.code}'
    except urllib.error.URLError as e:
        result['error'] = f'URL Error: {e.reason}'
    except Exception as e:
        result['error'] = str(e)
    
    return result


def api_lookup_product(query: str, listing_price: float = 0, category: str = None) -> Dict:
    """
    Real-time API lookup for products (LEGO sets and TCG).
    Uses PriceCharting /api/products endpoint.
    
    Args:
        query: Search query (e.g., "LEGO Star Wars 75192" or "Pokemon Evolving Skies Booster Box")
        listing_price: Current listing price for margin calculation
        category: Category hint (lego, pokemon, mtg, yugioh, etc.)
    
    Returns:
        Dict with: found, product_name, market_price, buy_target, margin, etc.
    """
    result = {
        'found': False,
        'product_name': None,
        'product_id': None,
        'console_name': None,
        'category': category or 'unknown',
        'market_price': None,
        'buy_target': None,
        'margin': None,
        'confidence': 'None',
        'source': 'api',
        'error': None
    }
    
    if not PRICECHARTING_API_KEY:
        result['error'] = 'No API key configured'
        return result
    
    if not query or len(query) < 3:
        result['error'] = 'Query too short'
        return result
    
    # Clean query
    clean_query = re.sub(r'[^\w\s\-]', ' ', query)
    clean_query = ' '.join(clean_query.split())[:100]
    
    # Build search queries based on category
    search_queries = []
    
    if category == 'lego':
        # Extract LEGO set number if present (4-5 digit numbers)
        set_number_match = re.search(r'\b(\d{4,5})\b', query)
        set_number = set_number_match.group(1) if set_number_match else None
        
        if set_number:
            search_queries.append(f"LEGO {set_number}")
        search_queries.append(clean_query)
        
        # Filter function for LEGO
        def filter_products(products):
            return [p for p in products 
                    if 'lego' in p.get('console-name', '').lower() 
                    and 'playstation' not in p.get('console-name', '').lower()
                    and '3do' not in p.get('console-name', '').lower()
                    and 'xbox' not in p.get('console-name', '').lower()
                    and 'nintendo' not in p.get('console-name', '').lower()
                    and 'wii' not in p.get('console-name', '').lower()]
    
    elif category in ['pokemon', 'tcg']:
        # For Pokemon, extract set name and product type for cleaner search
        title_lower = clean_query.lower()

        # Common product types to look for (ordered by value - prefer boxes over packs)
        product_types = ['booster box', 'elite trainer box', 'etb', 'booster bundle',
                        'collection box', 'premium collection', 'ultra premium', 'case',
                        'tin', 'booster pack', 'blister']

        # Find product type
        found_type = None
        for pt in product_types:
            if pt in title_lower:
                found_type = pt
                break

        # Comprehensive set names (WOTC vintage + modern)
        set_names = [
            # WOTC Vintage (1999-2003) - highest value
            'base set', 'jungle', 'fossil', 'team rocket', 'gym heroes', 'gym challenge',
            'neo genesis', 'neo discovery', 'neo revelation', 'neo destiny',
            'legendary collection', 'expedition', 'aquapolis', 'skyridge',
            # Modern valuable sets
            'prismatic evolutions', 'surging sparks', 'stellar crown', 'shrouded fable',
            'phantasmal flames', 'twilight masquerade', 'temporal forces', 'paldean fates', 'paradox rift',
            'obsidian flames', '151', 'paldea evolved', 'scarlet violet',
            'crown zenith', 'silver tempest', 'lost origin', 'evolving skies',
            'celebrations', 'fusion strike', 'chilling reign', 'battle styles',
            'shining fates', 'vivid voltage', 'champions path', 'hidden fates',
            'cosmic eclipse', 'unified minds', 'unbroken bonds', 'team up',
            'burning shadows', 'guardians rising', 'sun moon', 'evolutions',
            'breakthrough', 'ancient origins', 'roaring skies', 'phantom forces',
            'flashfire', 'xy base', 'legendary treasures', 'plasma', 'boundaries crossed',
            'dragons exalted', 'dark explorers', 'next destinies', 'noble victories'
        ]

        # Find set name
        found_set = None
        for sn in set_names:
            if sn in title_lower:
                found_set = sn
                break

        # Build targeted search queries - most specific first
        if found_set and found_type:
            # Best case: have both set and product type
            search_queries.append(f"{found_set} {found_type}")  # Don't prefix with Pokemon
            search_queries.append(f"Pokemon {found_set} {found_type}")
        if found_set:
            search_queries.append(found_set)  # Just set name
            search_queries.append(f"Pokemon {found_set}")
        if found_type:
            search_queries.append(f"Pokemon {found_type}")

        # Fall back to cleaned query
        search_queries.append(clean_query)

        # Add "Pokemon" prefix if not present
        if 'pokemon' not in clean_query.lower():
            search_queries.append(f"Pokemon {clean_query}")

        print(f"[PC-API] Pokemon search: set='{found_set}', type='{found_type}'")
        print(f"[PC-API] Pokemon search queries: {search_queries[:3]}")

        # Store found_set and found_type for scoring
        _pokemon_set = found_set
        _pokemon_type = found_type

        def filter_products(products):
            return [p for p in products
                    if 'pokemon' in p.get('console-name', '').lower()]
    
    elif category == 'mtg':
        search_queries.append(clean_query)
        if 'magic' not in clean_query.lower():
            search_queries.append(f"Magic {clean_query}")
        
        def filter_products(products):
            return [p for p in products 
                    if 'magic' in p.get('console-name', '').lower()]
    
    elif category == 'yugioh':
        search_queries.append(clean_query)
        if 'yugioh' not in clean_query.lower() and 'yu-gi-oh' not in clean_query.lower():
            search_queries.append(f"Yu-Gi-Oh {clean_query}")
        
        def filter_products(products):
            return [p for p in products 
                    if 'yugioh' in p.get('console-name', '').lower() 
                    or 'yu-gi-oh' in p.get('console-name', '').lower()]
    
    elif category == 'onepiece':
        search_queries.append(clean_query)
        if 'one piece' not in clean_query.lower():
            search_queries.append(f"One Piece {clean_query}")
        
        def filter_products(products):
            return [p for p in products 
                    if 'one piece' in p.get('console-name', '').lower()]
    
    elif category == 'lorcana':
        search_queries.append(clean_query)
        if 'lorcana' not in clean_query.lower():
            search_queries.append(f"Lorcana {clean_query}")
        
        def filter_products(products):
            return [p for p in products 
                    if 'lorcana' in p.get('console-name', '').lower()]
    
    elif category == 'videogames':
        # Video games need special handling - clean the title aggressively
        title_lower = clean_query.lower()
        
        # Remove common junk words that eBay sellers add
        junk_words = [
            'complete', 'great condition', 'good condition', 'excellent condition',
            'mint condition', 'like new', 'brand new', 'factory sealed', 'sealed',
            'tested', 'works', 'working', 'cleaned', 'resurfaced', 'authentic',
            'genuine', 'original', 'rare', 'vintage', 'classic', 'retro',
            'free shipping', 'fast shipping', 'cib', 'manual', 'case', 'cart only',
            'disc only', 'game only', 'no manual', 'with manual', 'w/ manual',
            'ntsc', 'pal', 'ntsc-j', 'usa', 'us version',
            'black label', 'greatest hits', 'players choice', 'platinum',
            'lot', 'bundle', 'set', 'collection', 'read description', 'see photos',
            'box', 'cartridge', 'cart', 'disc', 'disk'
        ]
        
        cleaned_title = title_lower
        for junk in junk_words:
            cleaned_title = cleaned_title.replace(junk, ' ')
        
        # Remove extra spaces and special chars (but keep hyphens for game names like "Pac-Man")
        cleaned_title = re.sub(r'[^\w\s\-]', ' ', cleaned_title)
        cleaned_title = ' '.join(cleaned_title.split())
        
        # Detect console from title - ORDER MATTERS! More specific patterns first
        # Each entry: (pc_console_name, [patterns], [pc_api_console_variations])
        console_patterns = [
            # Nintendo handhelds - most specific first
            ('Nintendo 3DS', [r'\b3ds\b', r'\bnew 3ds\b', r'\bnintendo 3ds\b'], ['nintendo 3ds', '3ds']),
            ('Nintendo DS', [r'\bnintendo ds\b', r'\bnds\b', r'\bds\b(?!\s*lite)'], ['nintendo ds', 'ds']),
            ('Nintendo Switch', [r'\bswitch\b', r'\bnintendo switch\b', r'\bnsw\b'], ['nintendo switch', 'switch']),
            ('Game Boy Advance', [r'\bgba\b', r'\bgame\s*boy\s*advance\b', r'\bgameboy\s*advance\b'], ['game boy advance', 'gba', 'gameboy advance']),
            ('Game Boy Color', [r'\bgbc\b', r'\bgame\s*boy\s*color\b'], ['game boy color', 'gbc']),
            ('Game Boy', [r'\bgame\s*boy\b', r'\bgameboy\b'], ['game boy', 'gameboy', 'gb']),
            
            # Sony - most specific first
            ('Playstation 5', [r'\bps5\b', r'\bplaystation\s*5\b'], ['playstation 5', 'ps5']),
            ('Playstation 4', [r'\bps4\b', r'\bplaystation\s*4\b'], ['playstation 4', 'ps4']),
            ('Playstation 3', [r'\bps3\b', r'\bplaystation\s*3\b'], ['playstation 3', 'ps3']),
            ('Playstation 2', [r'\bps2\b', r'\bplaystation\s*2\b'], ['playstation 2', 'ps2']),
            ('Playstation Vita', [r'\bvita\b', r'\bps\s*vita\b'], ['playstation vita', 'vita', 'psvita']),
            ('PSP', [r'\bpsp\b'], ['psp', 'playstation portable']),
            ('Playstation', [r'\bps1\b', r'\bpsx\b', r'\bpsone\b', r'\bplaystation\b(?!\s*[2345])'], ['playstation', 'ps1', 'psx']),
            
            # Microsoft - most specific first
            ('Xbox Series X', [r'\bxbox\s*series\b', r'\bseries\s*[xs]\b'], ['xbox series x', 'xbox series']),
            ('Xbox One', [r'\bxbox\s*one\b', r'\bxb1\b'], ['xbox one', 'xbone']),
            ('Xbox 360', [r'\bxbox\s*360\b', r'\bx360\b'], ['xbox 360', 'x360']),
            ('Xbox', [r'\bxbox\b(?!\s*(one|360|series))'], ['xbox', 'original xbox']),
            
            # Sega
            ('Sega Genesis', [r'\bgenesis\b', r'\bsega\s*genesis\b', r'\bmega\s*drive\b'], ['sega genesis', 'genesis', 'mega drive']),
            ('Sega Dreamcast', [r'\bdreamcast\b'], ['dreamcast', 'sega dreamcast']),
            ('Sega Saturn', [r'\bsaturn\b', r'\bsega\s*saturn\b'], ['sega saturn', 'saturn']),
            ('Sega CD', [r'\bsega\s*cd\b'], ['sega cd']),
            ('Game Gear', [r'\bgame\s*gear\b'], ['game gear', 'sega game gear']),
            
            # Nintendo consoles - most specific first
            ('Nintendo 64', [r'\bn64\b', r'\bnintendo\s*64\b'], ['nintendo 64', 'n64']),
            ('GameCube', [r'\bgamecube\b', r'\bgcn\b', r'\bngc\b'], ['gamecube', 'nintendo gamecube']),
            ('Wii U', [r'\bwii\s*u\b', r'\bwiiu\b'], ['wii u', 'wiiu']),
            ('Wii', [r'\bwii\b(?!\s*u)'], ['wii', 'nintendo wii']),
            ('Super Nintendo', [r'\bsnes\b', r'\bsuper\s*nintendo\b', r'\bsuper\s*nes\b'], ['super nintendo', 'snes']),
            ('NES', [r'\bnes\b(?!s)', r'\bnintendo\s*entertainment\s*system\b'], ['nes', 'nintendo']),  # \bnes\b but not 'ness' or 'japanese'
        ]
        
        detected_console = None
        detected_console_pc_names = []
        for pc_name, patterns, pc_variations in console_patterns:
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    detected_console = pc_name
                    detected_console_pc_names = pc_variations
                    # Remove console name from search to clean it up
                    cleaned_title = re.sub(pattern, ' ', cleaned_title)
                    break
            if detected_console:
                break
        
        # Clean up again after removing console
        cleaned_title = ' '.join(cleaned_title.split()).strip()
        
        # Remove "japan" and "japanese" AFTER console detection (so we don't mess up NES detection)
        cleaned_title = re.sub(r'\bjapan(ese)?\b', ' ', cleaned_title)
        cleaned_title = ' '.join(cleaned_title.split()).strip()
        
        # Build search queries - most specific first
        if detected_console and cleaned_title:
            # Search with just the game name (most likely to match)
            search_queries.append(cleaned_title)
            # Then try with console name
            search_queries.append(f"{cleaned_title} {detected_console}")
        elif cleaned_title:
            search_queries.append(cleaned_title)
        else:
            search_queries.append(clean_query)
        
        print(f"[PC-API] Video game search queries: {search_queries}")
        print(f"[PC-API] Detected console: {detected_console} (matching: {detected_console_pc_names})")
        
        # Filter function for video games - STRICT console matching
        def filter_products(products):
            if not detected_console:
                return products
            
            filtered = []
            
            for p in products:
                pc_console = p.get('console-name', '').lower()
                
                # STRICT match: only accept exact console matches from our variation list
                matched = False
                for variation in detected_console_pc_names:
                    if variation.lower() in pc_console or pc_console in variation.lower():
                        matched = True
                        break
                
                if matched:
                    filtered.append(p)
                    print(f"[PC-API] âœ“ Console match: {p.get('product-name', '')} ({pc_console})")
                else:
                    print(f"[PC-API] âœ— Console mismatch: {p.get('product-name', '')} ({pc_console}) - want {detected_console}")
            
            print(f"[PC-API] Found {len(filtered)} results matching {detected_console}")
            return filtered
    
    else:
        # Generic search - no filtering
        search_queries.append(clean_query)
        def filter_products(products):
            return products
    
    # Try each search query
    for search_query in search_queries:
        encoded_query = urllib.parse.quote(search_query)
        url = f"https://www.pricecharting.com/api/products?t={PRICECHARTING_API_KEY}&q={encoded_query}"
        
        try:
            print(f"[PC-API] Searching: {search_query[:50]}...")
            req = urllib.request.Request(url, headers={
                'User-Agent': 'eBayArbitrage/1.0'
            })
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('status') != 'success':
                    continue
                
                products = data.get('products', [])
                
                if not products:
                    continue
                
                # === GLOBAL EXCLUSION: Remove coins/bullion from ALL searches ===
                # PriceCharting has coins indexed alongside games, which pollutes results
                excluded_consoles = ['coins', 'coin', 'bullion', 'proof', 'currency']
                products = [p for p in products 
                           if not any(exc in p.get('console-name', '').lower() for exc in excluded_consoles)]
                
                if not products:
                    print(f"[PC-API] All results were coins/bullion - skipping")
                    continue
                
                # Apply category-specific filter
                filtered_products = filter_products(products)
                
                if not filtered_products:
                    # If no matches after filtering, try remaining products (coins already excluded)
                    filtered_products = products
                
                # For LEGO, try to match exact set number
                best = None
                if category == 'lego':
                    set_number_match = re.search(r'\b(\d{4,5})\b', query)
                    if set_number_match:
                        set_number = set_number_match.group(1)
                        for p in filtered_products:
                            product_name = p.get('product-name', '')
                            if set_number in product_name or f"#{set_number}" in product_name:
                                best = p
                                print(f"[PC-API] Exact set number match: {product_name}")
                                break
                
                # For TCG, avoid "case" products unless title mentions case
                if category in ['pokemon', 'tcg', 'mtg', 'yugioh', 'onepiece', 'lorcana']:
                    query_lower = query.lower()
                    is_looking_for_case = 'case' in query_lower or 'x6' in query_lower or 'x 6' in query_lower
                    
                    if not is_looking_for_case:
                        # Filter out case/bulk products
                        non_case_products = [p for p in filtered_products 
                                            if 'case' not in p.get('product-name', '').lower()]
                        if non_case_products:
                            filtered_products = non_case_products
                            print(f"[PC-API] Filtered to {len(non_case_products)} non-case products")
                
                # For video games, try to find best title match with improved scoring
                if category == 'videogames' and not best:
                    # CRITICAL: Filter out console/hardware products when searching for games
                    # These match on platform words like "Nintendo 3DS" but are not games
                    console_keywords = ['console', 'system', 'hardware', 'controller', 'adapter',
                                       'charger', 'stylus', 'case', 'stand', 'dock', 'grip']
                    # Also detect console products by pattern: "New Nintendo 3DS", "Nintendo Switch", etc.
                    console_patterns = ['new nintendo 3ds', 'nintendo 3ds xl', 'nintendo 3ds ll',
                                       'nintendo switch', 'nintendo wii', 'playstation', 'xbox',
                                       'sega genesis', 'sega saturn', 'sega dreamcast']

                    game_products = []
                    for p in filtered_products:
                        pname = p.get('product-name', '').lower()
                        is_console = any(ck in pname for ck in console_keywords)
                        # Check if product name IS the console (e.g., "New Nintendo 3DS LL Pink + White")
                        is_console_hardware = any(pname.startswith(cp) for cp in console_patterns)
                        if not is_console and not is_console_hardware:
                            game_products.append(p)
                        else:
                            print(f"[PC-API] Excluding console/hardware: {pname[:50]}")

                    if game_products:
                        filtered_products = game_products
                        print(f"[PC-API] Filtered to {len(game_products)} game products (excluded consoles)")

                    # Score each product by how well it matches
                    search_words = set(word for word in search_query.lower().split() if len(word) > 2)
                    best_score = 0
                    best_product = None

                    for p in filtered_products:
                        product_name = p.get('product-name', '').lower()
                        product_words = set(word for word in product_name.split() if len(word) > 2)
                        
                        score = 0
                        
                        # Count matching significant words
                        matching_words = search_words & product_words
                        score += len(matching_words) * 2
                        
                        # Bonus for exact substring match (game name fully contained)
                        if search_query.lower() in product_name:
                            score += 10
                        
                        # Bonus if first word matches (usually game name starts same)
                        search_first = search_query.lower().split()[0] if search_query else ''
                        product_first = product_name.split()[0] if product_name else ''
                        if search_first and product_first and search_first == product_first:
                            score += 3
                        
                        # Penalty for length mismatch (avoid matching "Mario" to "Super Mario Bros 3")
                        len_diff = abs(len(search_words) - len(product_words))
                        score -= len_diff * 0.5
                        
                        print(f"[PC-API] Score {score:.1f}: {p.get('product-name', '')} (matched: {matching_words})")
                        
                        if score > best_score:
                            best_score = score
                            best_product = p
                    
                    # Require minimum match quality - at least 2 words must match
                    if best_product and best_score >= 2:
                        best = best_product
                        print(f"[PC-API] Best video game match (score {best_score:.1f}): {best.get('product-name', '')}")
                    elif best_product:
                        print(f"[PC-API] âš ï¸ Best match score {best_score:.1f} too low - rejecting: {best_product.get('product-name', '')}")
                
                # For Pokemon/TCG, score products by set name and product type match
                if category in ['pokemon', 'tcg'] and not best:
                    best_score = -100
                    best_product = None
                    query_lower = query.lower()

                    # Extract set name and type from original query
                    tcg_set_names = [
                        'base set', 'jungle', 'fossil', 'team rocket', 'gym heroes', 'gym challenge',
                        'neo genesis', 'neo discovery', 'neo revelation', 'neo destiny',
                        'legendary collection', 'expedition', 'aquapolis', 'skyridge',
                        'prismatic evolutions', 'surging sparks', 'stellar crown', 'shrouded fable',
                        'phantasmal flames', 'twilight masquerade', 'temporal forces', 'paldean fates', 'paradox rift',
                        'obsidian flames', '151', 'paldea evolved', 'scarlet violet',
                        'crown zenith', 'silver tempest', 'lost origin', 'evolving skies',
                        'celebrations', 'fusion strike', 'chilling reign', 'battle styles',
                        'shining fates', 'vivid voltage', 'champions path', 'hidden fates'
                    ]
                    target_set = None
                    for sn in tcg_set_names:
                        if sn in query_lower:
                            target_set = sn
                            break

                    # Check for product type
                    target_type = None
                    if 'booster box' in query_lower:
                        target_type = 'booster box'
                    elif 'elite trainer' in query_lower or 'etb' in query_lower:
                        target_type = 'elite trainer'
                    elif 'booster pack' in query_lower:
                        target_type = 'booster pack'

                    print(f"[PC-API] Pokemon scoring: set='{target_set}', type='{target_type}'")

                    for p in filtered_products:
                        product_name = p.get('product-name', '').lower()
                        score = 0

                        # Set name matching
                        if target_set:
                            if target_set in product_name:
                                score += 20
                            else:
                                score -= 10

                        # Product type matching
                        if target_type:
                            if target_type in product_name:
                                score += 15
                            elif target_type == 'booster box' and 'box' in product_name and 'pack' not in product_name:
                                score += 10
                            elif target_type == 'booster box' and 'pack' in product_name:
                                score -= 15

                        # Variant/character matching - extract key words from query and match
                        variant_keywords = ['lucario', 'charizard', 'pikachu', 'mewtwo', 'mew', 'eevee',
                                          'gardevoir', 'gengar', 'rayquaza', 'umbreon', 'espeon',
                                          'pokemon center', 'mega', 'ex', 'vmax', 'vstar', 'gx',
                                          'moltres', 'articuno', 'zapdos', 'team rocket',
                                          'ultra premium', 'upc', 'special collection',
                                          'arceus', 'dialga', 'palkia', 'giratina', 'darkrai',
                                          'celebi', 'ho-oh', 'lugia', 'entei', 'suicune', 'raikou']
                        variant_matches = 0
                        for vk in variant_keywords:
                            if vk in query_lower and vk in product_name:
                                variant_matches += 1
                                score += 10  # Bonus for each matching variant keyword

                        # CRITICAL: Check for variant keyword in query that's MISSING from product
                        # If user searches for "Arceus" but product doesn't have it, that's a WRONG match
                        for vk in variant_keywords:
                            if vk in query_lower and vk not in product_name:
                                score -= 25  # Severe penalty - wrong product!

                        variant_info = f" [{variant_matches} variants]" if variant_matches > 0 else ""
                        print(f"[PC-API] Score {score}: {product_name[:40]}{variant_info}")

                        if score > best_score:
                            best_score = score
                            best_product = p

                    if best_product and best_score >= 10:
                        best = best_product
                        print(f"[PC-API] Best Pokemon match (score {best_score}): {best.get('product-name', '')}")
                    elif best_product and best_score > -10:
                        best = best_product
                        print(f"[PC-API] Acceptable Pokemon match (score {best_score}): {best.get('product-name', '')}")
                    elif best_product and best_score > -30:
                        best = best_product
                        print(f"[PC-API] Low-confidence Pokemon match (score {best_score}): {best.get('product-name', '')}")
                    else:
                        print(f"[PC-API] No acceptable Pokemon match found (best score: {best_score})")

                # Use first result only if we had no specific matching criteria
                if not best and category not in ['videogames', 'pokemon', 'tcg']:
                    best = filtered_products[0]
                    print(f"[PC-API] Selected first result: {best.get('product-name', '')}")
                
                product_id = best.get('id')

                # For video games, detect condition from original title
                condition_hint = None
                if category == 'videogames':
                    query_lower = query.lower()
                    if any(x in query_lower for x in ['sealed', 'factory sealed', 'brand new', 'new in box', 'nib']):
                        condition_hint = 'new'
                    elif any(x in query_lower for x in ['loose', 'cart only', 'disc only', 'game only', 'no case', 'no box']):
                        condition_hint = 'loose'
                    else:
                        # Default to CIB for video games (most common on eBay)
                        condition_hint = 'cib'
                    print(f"[PC-API] Video game condition detected: {condition_hint}")

                # Get full product details with prices
                price_result = api_get_product_details(product_id, listing_price, condition_hint)
                if price_result.get('found'):
                    price_result['category'] = category
                    return price_result
                
        except urllib.error.HTTPError as e:
            result['error'] = f'HTTP Error {e.code}'
        except urllib.error.URLError as e:
            result['error'] = f'URL Error: {e.reason}'
        except Exception as e:
            result['error'] = str(e)
    
    result['error'] = f'No matching {category} products found'
    return result


def api_get_product_details(product_id: str, listing_price: float = 0, condition_hint: str = None) -> Dict:
    """
    Get full product details including prices from PriceCharting API.

    Args:
        product_id: PriceCharting product ID
        listing_price: Current listing price for margin calculation
        condition_hint: Optional condition hint ("new", "cib", "loose") to select correct price

    Returns:
        Dict with product details and pricing
    """
    result = {
        'found': False,
        'product_name': None,
        'product_id': product_id,
        'console_name': None,
        'category': 'lego',
        'market_price': None,
        'buy_target': None,
        'margin': None,
        'confidence': 'None',
        'source': 'api',
        'error': None
    }
    
    if not PRICECHARTING_API_KEY or not product_id:
        result['error'] = 'Missing API key or product ID'
        return result
    
    url = f"https://www.pricecharting.com/api/product?t={PRICECHARTING_API_KEY}&id={product_id}"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'eBayArbitrage/1.0'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            import json
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get('status') != 'success':
                result['error'] = data.get('error-message', 'API error')
                return result
            
            # Prices are in pennies
            new_price = int(data.get('new-price', 0) or 0) / 100
            cib_price = int(data.get('cib-price', 0) or 0) / 100
            loose_price = int(data.get('loose-price', 0) or 0) / 100
            console_name = data.get('console-name', '').lower()
            product_name = data.get('product-name', '').lower()

            # TCG Booster Box special handling:
            # If new_price=0 and loose_price is very high (>$500), it's likely
            # the sum of 36 individual pack values, not the sealed box price
            is_tcg_booster_box = (
                ('pokemon' in console_name or 'magic' in console_name or 'yugioh' in console_name)
                and ('booster box' in product_name or product_name == 'booster box')
            )

            if is_tcg_booster_box and new_price == 0 and loose_price > 500:
                # Estimate sealed box value: loose_price / 36 packs * ~4 (box discount factor)
                # Individual packs trade at 2-3x premium over box price per pack
                estimated_box_value = (loose_price / 36) * 4
                print(f"[PC-API] TCG Box estimate: loose ${loose_price:.0f} (36 packs) -> sealed box ~${estimated_box_value:.0f}")
                market_price = estimated_box_value
                result['price_estimated'] = True
                result['confidence'] = 'Medium'  # Lower confidence for estimates
            else:
                # VIDEO GAMES: Use condition-appropriate price (fixes overvaluation bug!)
                # Default to CIB for video games since most eBay listings are CIB
                is_videogame = any(x in console_name for x in [
                    'nintendo', 'playstation', 'xbox', 'sega', 'game boy', 'gamecube',
                    'wii', 'switch', 'nes', 'snes', 'n64', 'genesis', 'dreamcast', 'saturn',
                    'ps1', 'ps2', 'ps3', 'ps4', 'ps5', 'psp', 'vita', '3ds', 'ds', 'gba'
                ])

                if is_videogame:
                    # Use condition hint if provided, otherwise default to CIB
                    if condition_hint == 'new' or condition_hint == 'sealed':
                        market_price = new_price or cib_price or loose_price
                        result['price_used'] = 'new'
                    elif condition_hint == 'loose':
                        market_price = loose_price or cib_price or new_price
                        result['price_used'] = 'loose'
                    else:
                        # Default to CIB for video games (most common condition on eBay)
                        market_price = cib_price or loose_price or new_price
                        result['price_used'] = 'cib'
                    print(f"[PC-API] Video game: using {result.get('price_used', 'cib')} price ${market_price:.0f} (new=${new_price:.0f}, cib=${cib_price:.0f}, loose=${loose_price:.0f})")
                else:
                    # TCG/LEGO: prefer new-price (sealed products)
                    market_price = new_price or cib_price or loose_price
            
            if market_price == 0:
                result['error'] = 'No price data available'
                result['found'] = True
                result['product_name'] = data.get('product-name', '')
                result['console_name'] = data.get('console-name', '')
                result['confidence'] = 'Low'
                return result
            
            # Use category-specific threshold (LEGO: 70%)
            buy_target = market_price * get_category_threshold('lego')
            margin = buy_target - listing_price if listing_price > 0 else None

            result.update({
                'found': True,
                'product_name': data.get('product-name', ''),
                'product_id': product_id,
                'console_name': data.get('console-name', ''),
                'market_price': market_price,
                'buy_target': buy_target,
                'margin': margin,
                'confidence': 'High',  # Direct API match
                'new_price': new_price,
                'cib_price': cib_price,
                'loose_price': loose_price,
            })
            
            print(f"[PC-API] Found: {result['product_name']} @ ${market_price:,.0f}")
            
    except Exception as e:
        result['error'] = str(e)
    
    return result


# ============================================================
# GRADED CARD LOOKUP (PSA/BGS/CGC Integration)
# ============================================================

# PSA Grade Multipliers (approximate - varies by card rarity)
PSA_GRADE_MULTIPLIERS = {
    10: 5.0,    # PSA 10 = ~5x raw (can be 10-20x for vintage chase cards)
    9: 2.0,     # PSA 9 = ~2x raw
    8: 1.3,     # PSA 8 = ~1.3x raw
    7: 1.0,     # PSA 7 = ~raw price
    6: 0.8,     # PSA 6 and below often less than raw
    5: 0.6,
}

BGS_GRADE_MULTIPLIERS = {
    10: 8.0,    # BGS 10 (Black Label) = very rare, huge premium
    9.5: 3.0,   # BGS 9.5 = ~3x raw (common "gem mint")
    9: 1.8,     # BGS 9 = ~1.8x raw
    8.5: 1.3,
    8: 1.1,
}

CGC_GRADE_MULTIPLIERS = {
    10: 4.0,    # CGC 10 = ~4x raw (less premium than PSA)
    9.5: 2.5,   # CGC 9.5 = ~2.5x raw
    9: 1.8,
    8.5: 1.2,
    8: 1.0,
}


def extract_grade_info(title: str) -> dict:
    """
    Extract grading company and grade from title.
    Returns dict with: grader, grade, is_graded
    """
    title_lower = title.lower()
    result = {"grader": None, "grade": None, "is_graded": False}

    # PSA patterns: "PSA 10", "PSA10", "PSA-10"
    psa_match = re.search(r'\bpsa[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if psa_match:
        result["grader"] = "PSA"
        result["grade"] = float(psa_match.group(1))
        result["is_graded"] = True
        return result

    # BGS patterns: "BGS 10", "BGS 9.5", "BGS-9.5", "Beckett 10"
    bgs_match = re.search(r'\b(?:bgs|beckett)[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if bgs_match:
        result["grader"] = "BGS"
        result["grade"] = float(bgs_match.group(1))
        result["is_graded"] = True
        return result

    # CGC patterns: "CGC 10", "CGC 9.5"
    cgc_match = re.search(r'\bcgc[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if cgc_match:
        result["grader"] = "CGC"
        result["grade"] = float(cgc_match.group(1))
        result["is_graded"] = True
        return result

    return result


def get_grade_multiplier(grader: str, grade: float) -> float:
    """Get the price multiplier for a given grade."""
    if grader == "PSA":
        for g in sorted(PSA_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return PSA_GRADE_MULTIPLIERS[g]
        return 0.5  # Below PSA 5
    elif grader == "BGS":
        for g in sorted(BGS_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return BGS_GRADE_MULTIPLIERS[g]
        return 0.5
    elif grader == "CGC":
        for g in sorted(CGC_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return CGC_GRADE_MULTIPLIERS[g]
        return 0.5
    return 1.0  # Unknown grader


def normalize_card_title(title: str) -> str:
    """
    Normalize a graded card title for searching.
    Removes grading info but keeps card name and set info.
    """
    title_lower = title.lower()

    # Remove grading company and grade
    title_lower = re.sub(r'\bpsa[\s\-]?\d+(?:\.\d)?\b', ' ', title_lower)
    title_lower = re.sub(r'\b(?:bgs|beckett)[\s\-]?\d+(?:\.\d)?\b', ' ', title_lower)
    title_lower = re.sub(r'\bcgc[\s\-]?\d+(?:\.\d)?\b', ' ', title_lower)

    # Remove common graded card noise
    noise = [
        'graded', 'gem mint', 'mint', 'perfect', 'pristine',
        'authentic', 'certified', 'encapsulated', 'slab',
        'free shipping', 'fast ship', 'look', 'wow', 'rare',
        'investment', 'pop', 'population', 'low pop',
    ]
    for word in noise:
        title_lower = title_lower.replace(word, ' ')

    # Remove special characters but keep spaces
    title_lower = re.sub(r'[^\w\s\-/]', ' ', title_lower)

    # Collapse whitespace
    title_lower = ' '.join(title_lower.split())

    return title_lower.strip()


def lookup_graded_card(title: str, listing_price: float = 0) -> Dict:
    """
    Look up a graded card's value using PriceCharting API.

    This function:
    1. Extracts grade info (PSA/BGS/CGC and grade number)
    2. Searches PriceCharting for the card (without grade keywords)
    3. Returns graded_price if available, or calculates using multipliers

    Args:
        title: eBay listing title with grading info (e.g., "PSA 10 Charizard Base Set")
        listing_price: Current listing price for margin calculation

    Returns:
        Dict with: found, grader, grade, card_name, raw_price, graded_price,
                   market_price, buy_target, margin, confidence, etc.
    """
    result = {
        'found': False,
        'is_graded': False,
        'grader': None,
        'grade': None,
        'card_name': None,
        'set_name': None,
        'raw_price': None,
        'graded_price': None,
        'market_price': None,
        'buy_target': None,
        'margin': None,
        'multiplier': None,
        'confidence': 'None',
        'source': 'pricecharting_graded',
        'error': None
    }

    # Extract grade info
    grade_info = extract_grade_info(title)
    if not grade_info['is_graded']:
        result['error'] = 'No grading info found in title'
        return result

    result['is_graded'] = True
    result['grader'] = grade_info['grader']
    result['grade'] = grade_info['grade']

    # Get multiplier for this grade
    multiplier = get_grade_multiplier(grade_info['grader'], grade_info['grade'])
    result['multiplier'] = multiplier

    # Normalize title for search (remove grading info)
    search_title = normalize_card_title(title)
    print(f"[PC-GRADED] Searching for: '{search_title}' (was: {title[:50]}...)")

    # Detect TCG type
    title_lower = title.lower()
    if any(x in title_lower for x in ['pokemon', 'charizard', 'pikachu', 'mewtwo', 'blastoise']):
        category = 'pokemon'
    elif any(x in title_lower for x in ['yugioh', 'yu-gi-oh', 'blue-eyes', 'dark magician']):
        category = 'yugioh'
    elif any(x in title_lower for x in ['magic', 'mtg', 'black lotus']):
        category = 'mtg'
    else:
        category = 'pokemon'  # Default to Pokemon (most common)

    # Search PriceCharting API
    if not PRICECHARTING_API_KEY:
        result['error'] = 'No API key configured'
        return result

    encoded_query = urllib.parse.quote(search_title[:100])
    url = f"https://www.pricecharting.com/api/products?t={PRICECHARTING_API_KEY}&q={encoded_query}"

    try:
        print(f"[PC-GRADED] API search: {search_title[:50]}...")
        req = urllib.request.Request(url, headers={'User-Agent': 'eBayArbitrage/1.0'})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

            if data.get('status') != 'success':
                result['error'] = 'API search failed'
                return result

            products = data.get('products', [])
            if not products:
                result['error'] = 'No matching cards found'
                return result

            # Filter to cards only (not sealed products)
            # PriceCharting uses console-name like "Pokemon Cards" for individual cards
            card_products = [p for p in products
                           if 'card' in p.get('console-name', '').lower()
                           or category in p.get('console-name', '').lower()]

            if not card_products:
                card_products = products  # Fall back to all results

            # Score products by matching keywords from search
            search_words = set(word for word in search_title.split() if len(word) > 2)
            best_product = None
            best_score = -100

            for p in card_products[:10]:  # Check top 10
                product_name = p.get('product-name', '').lower()
                product_words = set(word for word in product_name.split() if len(word) > 2)

                score = len(search_words & product_words) * 2

                # Bonus for key card identifiers
                if any(x in search_title for x in ['charizard', 'pikachu', 'mewtwo', 'blastoise']):
                    for card in ['charizard', 'pikachu', 'mewtwo', 'blastoise']:
                        if card in search_title.lower() and card in product_name:
                            score += 10

                # Bonus for set name match
                set_names = ['base set', 'jungle', 'fossil', 'team rocket', 'neo genesis',
                            'neo discovery', 'neo revelation', 'neo destiny', 'legendary collection',
                            'evolving skies', 'hidden fates', 'celebrations', '151']
                for set_name in set_names:
                    if set_name in search_title.lower() and set_name in product_name:
                        score += 5

                if score > best_score:
                    best_score = score
                    best_product = p

            if not best_product or best_score < 2:
                result['error'] = f'No good match found (best score: {best_score})'
                return result

            # Get full product details
            product_id = best_product.get('id')
            detail_url = f"https://www.pricecharting.com/api/product?t={PRICECHARTING_API_KEY}&id={product_id}"

            req2 = urllib.request.Request(detail_url, headers={'User-Agent': 'eBayArbitrage/1.0'})
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                detail_data = json.loads(resp2.read().decode('utf-8'))

                if detail_data.get('status') != 'success':
                    result['error'] = 'Failed to get card details'
                    return result

                # Extract prices (in pennies)
                loose_price = int(detail_data.get('loose-price', 0) or 0) / 100  # Raw/ungraded
                graded_price = int(detail_data.get('graded-price', 0) or 0) / 100  # Graded (usually PSA 9/10)

                result['card_name'] = detail_data.get('product-name', '')
                result['set_name'] = detail_data.get('console-name', '')
                result['raw_price'] = loose_price
                result['graded_price'] = graded_price
                result['product_id'] = product_id
                result['found'] = True

                print(f"[PC-GRADED] Found: {result['card_name']} | Raw: ${loose_price:.2f}, Graded: ${graded_price:.2f}")

                # Determine market price for this specific grade
                # PriceCharting's graded-price is typically for PSA 9-10
                # We need to adjust based on actual grade

                if graded_price > 0 and grade_info['grade'] >= 9:
                    # Use PriceCharting's graded price directly for PSA 9+
                    if grade_info['grade'] == 10 and grade_info['grader'] == 'PSA':
                        # PSA 10 is premium over graded-price (which is often PSA 9 average)
                        market_price = graded_price * 1.5  # PSA 10 typically 1.5x of avg graded
                    elif grade_info['grade'] >= 9.5 and grade_info['grader'] == 'BGS':
                        # BGS 9.5 is similar to PSA 10
                        market_price = graded_price * 1.3
                    else:
                        market_price = graded_price

                    result['confidence'] = 'High'
                    result['source'] = 'pricecharting_graded_direct'

                elif loose_price > 0:
                    # Calculate from raw price using multiplier
                    market_price = loose_price * multiplier
                    result['confidence'] = 'Medium'
                    result['source'] = 'pricecharting_calculated'
                    print(f"[PC-GRADED] Calculated: ${loose_price:.2f} raw x {multiplier}x = ${market_price:.2f}")

                else:
                    result['error'] = 'No pricing data available'
                    return result

                result['market_price'] = market_price

                # Calculate buy target (70% for TCG)
                buy_target = market_price * get_category_threshold('tcg')
                margin = buy_target - listing_price if listing_price > 0 else None

                result['buy_target'] = buy_target
                result['margin'] = margin

                print(f"[PC-GRADED] Market: ${market_price:.2f}, Buy@70%: ${buy_target:.2f}, Margin: ${margin:.2f if margin else 0}")

                return result

    except urllib.error.HTTPError as e:
        result['error'] = f'HTTP Error {e.code}'
    except urllib.error.URLError as e:
        result['error'] = f'URL Error: {e.reason}'
    except Exception as e:
        result['error'] = str(e)

    return result


# ============================================================
# STATISTICS & UTILITIES
# ============================================================

def get_db_stats() -> Dict:
    """Get database statistics"""
    stats = {
        'total_products': 0,
        'by_category': {},
        'last_refresh': None,
        'db_size_mb': 0,
    }
    
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Total products
        c.execute('SELECT COUNT(*) FROM products')
        stats['total_products'] = c.fetchone()[0]
        
        # By category
        c.execute('SELECT category, COUNT(*) FROM products GROUP BY category')
        for row in c.fetchall():
            stats['by_category'][row[0]] = row[1]
        
        # Last refresh
        c.execute("SELECT value FROM metadata WHERE key = 'last_refresh'")
        row = c.fetchone()
        if row:
            stats['last_refresh'] = row[0]
        
        conn.close()
        
        # DB file size
        if DB_PATH.exists():
            stats['db_size_mb'] = DB_PATH.stat().st_size / (1024 * 1024)
        
    except Exception as e:
        stats['error'] = str(e)
    
    return stats


def search_products(query: str, category: Optional[str] = None, limit: int = 10) -> List[Dict]:
    """Search products and return multiple results"""
    results = []
    
    search_title = normalize_search_title(query)
    search_terms = search_title.split()[:8]
    fts_query = ' '.join(f'"{term}"*' for term in search_terms if len(term) > 2)
    
    if not fts_query:
        return results
    
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        if category:
            c.execute('''
                SELECT p.*, bm25(products_fts) as rank
                FROM products p
                JOIN products_fts ON p.rowid = products_fts.rowid
                WHERE products_fts MATCH ? AND p.category = ?
                ORDER BY rank
                LIMIT ?
            ''', (fts_query, category, limit))
        else:
            c.execute('''
                SELECT p.*, bm25(products_fts) as rank
                FROM products p
                JOIN products_fts ON p.rowid = products_fts.rowid
                WHERE products_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            ''', (fts_query, limit))
        
        for row in c.fetchall():
            new_price = row['new_price'] / 100 if row['new_price'] else 0
            results.append({
                'product_name': row['product_name'],
                'product_id': row['id'],
                'console_name': row['console_name'],
                'category': row['category'],
                'new_price': new_price,
                'rank': row['rank'],
            })
        
        conn.close()
        
    except Exception as e:
        print(f"[PC-DB] Search error: {e}")
    
    return results


def rebuild_fts_index() -> Dict:
    """Rebuild the FTS5 index from products table"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check current counts
        c.execute("SELECT COUNT(*) FROM products")
        products_count = c.fetchone()[0]
        
        # Drop and recreate FTS table
        c.execute("DROP TABLE IF EXISTS products_fts")
        
        c.execute('''
            CREATE VIRTUAL TABLE products_fts USING fts5(
                product_name,
                console_name,
                category,
                content='products',
                content_rowid='rowid'
            )
        ''')
        
        # Populate FTS from products table
        c.execute('''
            INSERT INTO products_fts(rowid, product_name, console_name, category)
            SELECT rowid, product_name, console_name, category FROM products
        ''')
        
        conn.commit()
        
        # Verify FTS count
        c.execute("SELECT COUNT(*) FROM products_fts")
        fts_count = c.fetchone()[0]
        
        conn.close()
        
        print(f"[PC-DB] Rebuilt FTS index: {fts_count} products indexed")
        return {
            "success": True,
            "products_count": products_count,
            "fts_count": fts_count,
            "message": f"Rebuilt FTS index with {fts_count} products"
        }
    except Exception as e:
        print(f"[PC-DB] FTS rebuild error: {e}")
        return {"success": False, "error": str(e)}


def debug_search(query: str, category: str = None) -> Dict:
    """Debug search to see what's happening"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Check FTS table exists and has data
        try:
            c.execute("SELECT COUNT(*) FROM products_fts")
            fts_count = c.fetchone()[0]
        except:
            fts_count = 0
        
        # Check products table
        c.execute("SELECT COUNT(*) FROM products")
        products_count = c.fetchone()[0]
        
        # Normalize query
        search_title = normalize_search_title(query)
        search_terms = search_title.split()[:8]
        fts_query = ' '.join(f'"{term}"*' for term in search_terms if len(term) > 2)
        
        # Sample products
        if category:
            c.execute("SELECT product_name, console_name, category FROM products WHERE category = ? LIMIT 5", (category,))
        else:
            c.execute("SELECT product_name, console_name, category FROM products LIMIT 5")
        sample_products = [dict(row) for row in c.fetchall()]
        
        # Try direct LIKE search as fallback
        like_results = []
        if search_terms:
            like_pattern = f"%{search_terms[0]}%"
            if category:
                c.execute("""
                    SELECT product_name, console_name, category, new_price 
                    FROM products 
                    WHERE product_name LIKE ? AND category = ?
                    LIMIT 5
                """, (like_pattern, category))
            else:
                c.execute("""
                    SELECT product_name, console_name, category, new_price 
                    FROM products 
                    WHERE product_name LIKE ?
                    LIMIT 5
                """, (like_pattern,))
            like_results = [dict(row) for row in c.fetchall()]
        
        # Try FTS search
        fts_results = []
        fts_error = None
        if fts_query and fts_count > 0:
            try:
                if category:
                    c.execute('''
                        SELECT p.product_name, p.console_name, p.category, p.new_price
                        FROM products p
                        JOIN products_fts ON p.rowid = products_fts.rowid
                        WHERE products_fts MATCH ? AND p.category = ?
                        LIMIT 5
                    ''', (fts_query, category))
                else:
                    c.execute('''
                        SELECT p.product_name, p.console_name, p.category, p.new_price
                        FROM products p
                        JOIN products_fts ON p.rowid = products_fts.rowid
                        WHERE products_fts MATCH ?
                        LIMIT 5
                    ''', (fts_query,))
                fts_results = [dict(row) for row in c.fetchall()]
            except Exception as e:
                fts_error = str(e)
        
        conn.close()
        
        return {
            "original_query": query,
            "normalized_query": search_title,
            "fts_query": fts_query,
            "category_filter": category,
            "products_count": products_count,
            "fts_count": fts_count,
            "sample_products": sample_products,
            "like_results": like_results,
            "fts_results": fts_results,
            "fts_error": fts_error
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# BACKGROUND REFRESH
# ============================================================

_refresh_thread = None
_refresh_stop = threading.Event()


def start_background_refresh(interval_hours: int = 24):
    """Start background thread to refresh database daily"""
    global _refresh_thread, _refresh_stop
    
    if _refresh_thread and _refresh_thread.is_alive():
        print("[PC-DB] Background refresh already running")
        return
    
    _refresh_stop.clear()
    
    def refresh_loop():
        while not _refresh_stop.is_set():
            try:
                refresh_database()
            except Exception as e:
                print(f"[PC-DB] Background refresh error: {e}")
            
            # Wait for interval or stop signal
            _refresh_stop.wait(interval_hours * 3600)
    
    _refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
    _refresh_thread.start()
    print(f"[PC-DB] Background refresh started (every {interval_hours}h)")


def stop_background_refresh():
    """Stop background refresh thread"""
    global _refresh_stop
    _refresh_stop.set()
    print("[PC-DB] Background refresh stopped")


# ============================================================
# INITIALIZATION
# ============================================================

# Initialize database on import
init_database()

# Check if we have data, if not trigger initial load message
_conn = get_db_connection()
_c = _conn.cursor()
_c.execute('SELECT COUNT(*) FROM products')
_count = _c.fetchone()[0]
_conn.close()

if _count == 0:
    print("[PC-DB] Database is empty!")
    print("[PC-DB] Set PRICECHARTING_API_KEY in .env and call refresh_database()")
else:
    print(f"[PC-DB] Loaded with {_count:,} products")


# ============================================================
# CLI FOR TESTING
# ============================================================

if __name__ == "__main__":
    import sys
    
    print("\n" + "=" * 60)
    print("PriceCharting Database Module")
    print("=" * 60)
    
    if len(sys.argv) < 2:
        print("\nCommands:")
        print("  python pricecharting_db.py refresh      - Download fresh data")
        print("  python pricecharting_db.py stats        - Show database stats")
        print("  python pricecharting_db.py search <q>   - Search products")
        print("  python pricecharting_db.py lookup <q>   - Lookup single product")
        print("\nExample:")
        print("  python pricecharting_db.py lookup 'Pokemon Evolving Skies Booster Box'")
        
    elif sys.argv[1] == 'refresh':
        print("\nRefreshing database...")
        result = refresh_database(force=True)
        print(f"\nResult: {result}")
        
    elif sys.argv[1] == 'stats':
        stats = get_db_stats()
        print(f"\nDatabase Statistics:")
        print(f"  Total Products: {stats['total_products']:,}")
        print(f"  DB Size: {stats['db_size_mb']:.2f} MB")
        print(f"  Last Refresh: {stats['last_refresh']}")
        print(f"\n  By Category:")
        for cat, count in stats.get('by_category', {}).items():
            print(f"    {cat}: {count:,}")
            
    elif sys.argv[1] == 'search' and len(sys.argv) >= 3:
        query = ' '.join(sys.argv[2:])
        print(f"\nSearching: {query}")
        print("-" * 50)
        results = search_products(query)
        for r in results:
            print(f"  ${r['new_price']:>8.2f} | {r['product_name'][:50]}")
            
    elif sys.argv[1] == 'lookup' and len(sys.argv) >= 3:
        query = ' '.join(sys.argv[2:])
        print(f"\nLooking up: {query}")
        print("-" * 50)
        result = lookup_product(query, listing_price=100)
        for k, v in result.items():
            print(f"  {k}: {v}")
    
    elif sys.argv[1] == 'rebuild-fts':
        print("\nRebuilding FTS index...")
        result = rebuild_fts_index()
        print(f"Result: {result}")
    
    elif sys.argv[1] == 'debug' and len(sys.argv) >= 3:
        query = ' '.join(sys.argv[2:])
        print(f"\nDebug search: {query}")
        print("-" * 50)
        result = debug_search(query)
        import json
        print(json.dumps(result, indent=2))
