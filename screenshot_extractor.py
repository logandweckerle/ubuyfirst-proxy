"""
Screenshot Price Extractor
Extracts sold listing data from eBay screenshots using GPT-4o vision.

Usage:
    python screenshot_extractor.py allen_bradley
    python screenshot_extractor.py breakers
    python screenshot_extractor.py --all
    python screenshot_extractor.py --deals              # Show potential deals
    python screenshot_extractor.py --deals allen_bradley  # Deals in category
    python screenshot_extractor.py --analyze            # Full market analysis

Screenshots go in: price_screenshots/<category>/
Database output: price_data.db
"""

import os
import sys
import json
import base64
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from statistics import median, stdev

# Load environment
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Paths
SCRIPT_DIR = Path(__file__).parent
SCREENSHOTS_DIR = SCRIPT_DIR / "price_screenshots"
DATABASE_PATH = SCRIPT_DIR / "price_data.db"

# Thresholds
DEAL_THRESHOLD = 0.70  # Items below 70% of avg = potential deal
PRO_SELLER_FEEDBACK = 1000  # 1000+ feedback = professional seller
CASUAL_SELLER_FEEDBACK = 100  # Under 100 = casual/new seller

# Pro seller keywords - these sellers price at retail/market ceiling
PRO_SELLER_KEYWORDS = [
    'radwell', 'plc-mart', 'plcmart', 'supply', 'supplier', 'parts',
    'industrial', 'automation', 'direct', 'warehouse', 'wholesale',
    'distributor', 'controls', 'electric', 'equipment', 'store',
    'outlet', 'depot', 'mart', 'pro', 'llc', 'inc', 'corp',
    'international', 'global', 'usa', 'us stock', 'expedited'
]


def is_pro_seller_by_name(seller_name: str) -> bool:
    """Check if seller name contains professional seller keywords"""
    if not seller_name:
        return False
    name_lower = seller_name.lower()
    return any(kw in name_lower for kw in PRO_SELLER_KEYWORDS)


def init_database():
    """Initialize the price database with seller tracking and corrections"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Price corrections table - stores user-provided market prices
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords TEXT NOT NULL,
            market_price REAL NOT NULL,
            category TEXT,
            notes TEXT,
            source TEXT DEFAULT 'user',
            created_at TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_keywords ON price_corrections(keywords)
    """)

    # Check if we need to migrate (add new columns)
    cursor.execute("PRAGMA table_info(sold_items)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'seller_name' not in columns:
        # Table exists but needs migration
        try:
            cursor.execute("ALTER TABLE sold_items ADD COLUMN seller_name TEXT")
            cursor.execute("ALTER TABLE sold_items ADD COLUMN seller_feedback INTEGER")
            print("[DB] Migrated: Added seller columns")
        except:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sold_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            part_number TEXT,
            title TEXT,
            sold_price REAL,
            condition TEXT,
            sold_date TEXT,
            seller_name TEXT,
            seller_feedback INTEGER,
            screenshot_file TEXT,
            extracted_at TEXT,
            raw_data TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_part_number ON sold_items(part_number)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_category ON sold_items(category)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_seller ON sold_items(seller_name)
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized: {DATABASE_PATH}")


def encode_image(image_path: str) -> str:
    """Encode image to base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_type(image_path: str) -> str:
    """Get MIME type from file extension"""
    ext = Path(image_path).suffix.lower()
    types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return types.get(ext, "image/png")


def get_seller_type(feedback: int, seller_name: str = None) -> str:
    """Classify seller by feedback count AND name keywords"""
    # Check name keywords first - these are always pro regardless of feedback
    if seller_name and is_pro_seller_by_name(seller_name):
        return "professional"

    if feedback is None:
        return "unknown"
    if feedback >= PRO_SELLER_FEEDBACK:
        return "professional"
    elif feedback >= CASUAL_SELLER_FEEDBACK:
        return "established"
    else:
        return "casual"


def is_deal_seller(feedback: int, seller_name: str = None) -> bool:
    """Check if this is a potential deal seller (casual/individual)"""
    seller_type = get_seller_type(feedback, seller_name)
    return seller_type in ("casual", "unknown")


async def extract_from_screenshot(image_path: str, category: str) -> List[Dict]:
    """Extract sold listing data from a screenshot using GPT-4o vision"""

    if not OPENAI_API_KEY:
        print("[ERROR] OPENAI_API_KEY not set")
        return []

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("[ERROR] openai package not installed")
        return []

    # Encode image
    base64_image = encode_image(image_path)
    image_type = get_image_type(image_path)

    # Base extraction fields for all categories
    base_prompt = """
ALSO extract for EACH item:
- seller_name: The seller's username (visible next to feedback score)
- seller_feedback: The seller's feedback NUMBER only (e.g., if "seller123 99.5% positive (1.2K)" extract 1200, if "(185K)" extract 185000, if "(391)" extract 391)

"""

    # Build prompt based on category
    if category == "allen_bradley":
        extraction_prompt = """
You are extracting sold listing data from an eBay screenshot showing Allen Bradley / Rockwell Automation industrial parts.

For EACH sold item visible in the screenshot, extract:
1. part_number: The Allen Bradley catalog number (e.g., "1756-L72", "2711P-T10C4D8", "22C-D030N103")
2. title: Full listing title
3. sold_price: The SOLD price in USD (number only, no $ sign)
4. condition: "New", "Used", "Refurbished", or "Unknown"
5. sold_date: Date sold if visible (format: YYYY-MM-DD or "Unknown")
6. seller_name: The seller's username
7. seller_feedback: The seller's feedback count as a number (convert K to thousands, e.g., 1.2K = 1200, 185K = 185000)

Return a JSON array of objects. Example:
[
    {"part_number": "1756-L72", "title": "Allen Bradley 1756-L72 ControlLogix Controller", "sold_price": 1250.00, "condition": "Used", "sold_date": "2024-01-15", "seller_name": "industrial_parts", "seller_feedback": 5200},
    {"part_number": "2711P-T10C4D8", "title": "PanelView Plus 7", "sold_price": 890.00, "condition": "Refurbished", "sold_date": "Unknown", "seller_name": "estate_finds", "seller_feedback": 45}
]

IMPORTANT:
- Extract ALL visible sold items
- The catalog number is critical - look for patterns like 1756-XXX, 2711X-XXX, 22X-XXX, 1769-XXX, etc.
- If you can't determine the part number, use the most specific identifier from the title
- Convert feedback K notation to actual numbers (185K = 185000)
- Return ONLY valid JSON array, no other text
"""
    elif category == "breakers":
        extraction_prompt = """
You are extracting sold listing data from an eBay screenshot showing electrical circuit breakers.

For EACH sold item visible in the screenshot, extract:
1. part_number: The breaker model/part number (e.g., "QO120", "HOM115", "BQ2B060")
2. title: Full listing title
3. sold_price: The SOLD price in USD (number only, no $ sign)
4. condition: "New", "Used", or "Unknown"
5. sold_date: Date sold if visible (format: YYYY-MM-DD or "Unknown")
6. brand: Manufacturer (Square D, Siemens, Eaton, Cutler-Hammer, GE, etc.)
7. amperage: Amp rating if visible (e.g., "20A", "60A")
8. seller_name: The seller's username
9. seller_feedback: The seller's feedback count as a number

Return a JSON array of objects. Example:
[
    {"part_number": "QO120", "brand": "Square D", "amperage": "20A", "title": "Square D QO120 20A Single Pole Breaker", "sold_price": 12.50, "condition": "New", "sold_date": "2024-01-15", "seller_name": "breaker_outlet", "seller_feedback": 15000}
]

IMPORTANT:
- Extract ALL visible sold items
- Convert feedback K notation to actual numbers
- Return ONLY valid JSON array, no other text
"""
    else:
        extraction_prompt = f"""
You are extracting sold listing data from an eBay screenshot for category: {category}

For EACH sold item visible in the screenshot, extract:
1. part_number: Primary identifier/model number
2. title: Full listing title
3. sold_price: The SOLD price in USD (number only, no $ sign)
4. condition: "New", "Used", "Refurbished", or "Unknown"
5. sold_date: Date sold if visible (format: YYYY-MM-DD or "Unknown")
6. seller_name: The seller's username
7. seller_feedback: The seller's feedback count as a number (convert K to thousands)

Return a JSON array of objects.
IMPORTANT: Return ONLY valid JSON array, no other text
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": extraction_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_type};base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=4000,
            temperature=0.1,
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up response - remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        result_text = result_text.strip()

        # Parse JSON
        items = json.loads(result_text)

        if not isinstance(items, list):
            items = [items]

        print(f"  [OK] Extracted {len(items)} items")
        return items

    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse error: {e}")
        print(f"  Response was: {result_text[:200]}...")
        return []
    except Exception as e:
        print(f"  [ERROR] Extraction failed: {e}")
        return []


def save_items_to_db(items: List[Dict], category: str, screenshot_file: str):
    """Save extracted items to database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    for item in items:
        cursor.execute("""
            INSERT INTO sold_items (category, part_number, title, sold_price, condition, sold_date, seller_name, seller_feedback, screenshot_file, extracted_at, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            category,
            item.get("part_number", ""),
            item.get("title", ""),
            item.get("sold_price", 0),
            item.get("condition", "Unknown"),
            item.get("sold_date", "Unknown"),
            item.get("seller_name", ""),
            item.get("seller_feedback"),
            screenshot_file,
            datetime.now().isoformat(),
            json.dumps(item)
        ))

    conn.commit()
    conn.close()


async def process_category(category: str):
    """Process all screenshots in a category folder"""
    category_dir = SCREENSHOTS_DIR / category

    if not category_dir.exists():
        print(f"[ERROR] Category folder not found: {category_dir}")
        return

    # Find all image files
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    images = [f for f in category_dir.iterdir() if f.suffix.lower() in image_extensions]

    if not images:
        print(f"[INFO] No screenshots found in {category_dir}")
        return

    print(f"\n[{category.upper()}] Processing {len(images)} screenshots...")

    total_items = 0
    for i, image_path in enumerate(images, 1):
        print(f"  [{i}/{len(images)}] {image_path.name}")

        items = await extract_from_screenshot(str(image_path), category)

        if items:
            save_items_to_db(items, category, image_path.name)
            total_items += len(items)

    print(f"\n[{category.upper()}] Complete! Extracted {total_items} total items")


def show_stats():
    """Show database statistics"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("PRICE DATABASE STATISTICS")
    print("=" * 60)

    # Items by category
    cursor.execute("""
        SELECT category, COUNT(*) as count,
               ROUND(AVG(sold_price), 2) as avg_price
        FROM sold_items
        GROUP BY category
    """)

    rows = cursor.fetchall()
    if rows:
        print("\nItems by Category:")
        for row in rows:
            print(f"  {row[0]}: {row[1]} items, avg ${row[2]}")

    # Top 10 most tracked parts
    cursor.execute("""
        SELECT part_number, COUNT(*) as count,
               ROUND(AVG(sold_price), 2) as avg_price,
               category
        FROM sold_items
        WHERE part_number != ''
        GROUP BY part_number
        ORDER BY count DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()
    if rows:
        print("\nTop 10 Most Tracked Parts:")
        for row in rows:
            print(f"  {row[0]}: {row[1]} sales, avg ${row[2]} [{row[3]}]")

    # Seller breakdown
    cursor.execute("""
        SELECT
            CASE
                WHEN seller_feedback >= 1000 THEN 'Professional (1000+)'
                WHEN seller_feedback >= 100 THEN 'Established (100-999)'
                WHEN seller_feedback > 0 THEN 'Casual (<100)'
                ELSE 'Unknown'
            END as seller_type,
            COUNT(*) as count,
            ROUND(AVG(sold_price), 2) as avg_price
        FROM sold_items
        GROUP BY seller_type
        ORDER BY avg_price DESC
    """)

    rows = cursor.fetchall()
    if rows:
        print("\nPricing by Seller Type:")
        for row in rows:
            print(f"  {row[0]}: {row[1]} items, avg ${row[2]}")

    conn.close()


def find_deals(category: str = None):
    """Find potential deals - items priced below market average"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("DEAL DETECTION REPORT")
    print("=" * 70)

    # Get parts with multiple data points for comparison
    query = """
        SELECT part_number,
               COUNT(*) as count,
               AVG(sold_price) as avg_price,
               MIN(sold_price) as min_price,
               MAX(sold_price) as max_price,
               category
        FROM sold_items
        WHERE part_number != '' AND sold_price > 0
    """
    if category:
        query += f" AND category = '{category}'"
    query += " GROUP BY part_number HAVING count >= 1 ORDER BY avg_price DESC"

    cursor.execute(query)
    parts = cursor.fetchall()

    print(f"\nAnalyzing {len(parts)} unique parts...")

    # Categorize findings
    confirmed_deals = []  # Multiple data points, clear discount
    potential_deals = []  # Single data point but from casual seller at low price
    pro_prices = []       # Professional seller baseline prices

    for part in parts:
        part_number, count, avg_price, min_price, max_price, cat = part

        # Get individual sales for this part
        cursor.execute("""
            SELECT sold_price, seller_name, seller_feedback, condition, sold_date
            FROM sold_items
            WHERE part_number = ? AND sold_price > 0
            ORDER BY sold_price ASC
        """, (part_number,))

        sales = cursor.fetchall()

        for sale in sales:
            price, seller, feedback, condition, date = sale
            seller_type = get_seller_type(feedback, seller)

            # Calculate discount from average
            if avg_price > 0:
                discount = (avg_price - price) / avg_price
            else:
                discount = 0

            item_info = {
                'part_number': part_number,
                'price': price,
                'avg_price': avg_price,
                'discount': discount,
                'seller': seller,
                'feedback': feedback,
                'seller_type': seller_type,
                'condition': condition,
                'date': date,
                'data_points': count,
                'category': cat
            }

            # Classify the sale
            if count >= 2 and discount >= (1 - DEAL_THRESHOLD):
                # Multiple data points and significant discount
                confirmed_deals.append(item_info)
            elif seller_type in ('casual', 'unknown') and price < avg_price:
                # Casual seller below average - worth watching
                potential_deals.append(item_info)
            elif seller_type == 'professional':
                # Pro seller = market baseline (ceiling price)
                pro_prices.append(item_info)
            elif seller_type == 'established' and discount > 0.15:
                # Established seller with 15%+ discount - also worth noting
                potential_deals.append(item_info)

    # Display confirmed deals
    if confirmed_deals:
        print("\n" + "-" * 70)
        print("CONFIRMED DEALS (Multiple data points, significant discount)")
        print("-" * 70)
        for deal in sorted(confirmed_deals, key=lambda x: x['discount'], reverse=True)[:20]:
            discount_pct = deal['discount'] * 100
            print(f"\n  {deal['part_number']}")
            print(f"    Price: ${deal['price']:.2f} vs Avg: ${deal['avg_price']:.2f} ({discount_pct:.0f}% below)")
            print(f"    Seller: {deal['seller']} ({deal['feedback'] or '?'} fb) - {deal['seller_type']}")
            print(f"    Condition: {deal['condition']} | Date: {deal['date']}")
            print(f"    Data points: {deal['data_points']}")

    # Display potential deals from casual sellers
    if potential_deals:
        print("\n" + "-" * 70)
        print("CASUAL SELLER DEALS (Low feedback sellers, below average price)")
        print("-" * 70)
        casual_sorted = sorted(potential_deals, key=lambda x: (x['feedback'] or 999999, -x['discount']))
        for deal in casual_sorted[:15]:
            discount_pct = deal['discount'] * 100
            print(f"\n  {deal['part_number']}")
            print(f"    Price: ${deal['price']:.2f} vs Avg: ${deal['avg_price']:.2f} ({discount_pct:.0f}% below)")
            print(f"    Seller: {deal['seller']} ({deal['feedback'] or '?'} fb) - CASUAL SELLER")
            print(f"    Condition: {deal['condition']}")

    # Price ranges by seller type
    print("\n" + "-" * 70)
    print("MARKET ANALYSIS BY SELLER TYPE")
    print("-" * 70)

    cursor.execute("""
        SELECT
            CASE
                WHEN seller_feedback >= 1000 THEN 'Professional'
                WHEN seller_feedback >= 100 THEN 'Established'
                WHEN seller_feedback > 0 THEN 'Casual'
                ELSE 'Unknown'
            END as seller_type,
            COUNT(*) as sales,
            ROUND(AVG(sold_price), 2) as avg,
            ROUND(MIN(sold_price), 2) as min,
            ROUND(MAX(sold_price), 2) as max
        FROM sold_items
        WHERE sold_price > 0
    """ + (f" AND category = '{category}'" if category else "") + """
        GROUP BY seller_type
    """)

    for row in cursor.fetchall():
        print(f"\n  {row[0]} Sellers:")
        print(f"    Sales: {row[1]} | Avg: ${row[2]} | Range: ${row[3]} - ${row[4]}")

    # High-value parts to watch
    print("\n" + "-" * 70)
    print("HIGH-VALUE PARTS (Worth monitoring for deals)")
    print("-" * 70)

    cursor.execute("""
        SELECT part_number,
               ROUND(AVG(sold_price), 2) as avg_price,
               COUNT(*) as count,
               category
        FROM sold_items
        WHERE sold_price > 500
    """ + (f" AND category = '{category}'" if category else "") + """
        GROUP BY part_number
        ORDER BY avg_price DESC
        LIMIT 15
    """)

    for row in cursor.fetchall():
        print(f"  ${row[1]:>8.2f}  {row[0]:<30} ({row[2]} sales) [{row[3]}]")

    conn.close()


def lookup_price(part_number: str) -> Optional[Dict]:
    """Look up average price for a part number with deal detection"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            part_number,
            COUNT(*) as sale_count,
            ROUND(AVG(sold_price), 2) as avg_price,
            ROUND(MIN(sold_price), 2) as min_price,
            ROUND(MAX(sold_price), 2) as max_price,
            category
        FROM sold_items
        WHERE part_number LIKE ?
        GROUP BY part_number
    """, (f"%{part_number}%",))

    row = cursor.fetchone()

    if row:
        result = {
            "part_number": row[0],
            "sale_count": row[1],
            "avg_price": row[2],
            "min_price": row[3],
            "max_price": row[4],
            "category": row[5],
        }

        # Get individual sales with seller info
        cursor.execute("""
            SELECT sold_price, seller_name, seller_feedback, condition, sold_date
            FROM sold_items
            WHERE part_number LIKE ?
            ORDER BY sold_price ASC
        """, (f"%{part_number}%",))

        result["sales"] = []
        for sale in cursor.fetchall():
            result["sales"].append({
                "price": sale[0],
                "seller": sale[1],
                "feedback": sale[2],
                "seller_type": get_seller_type(sale[2], sale[1]),
                "condition": sale[3],
                "date": sale[4]
            })

        # Calculate deal threshold
        result["deal_price"] = round(result["avg_price"] * DEAL_THRESHOLD, 2)

        conn.close()
        return result

    conn.close()
    return None


def log_price_correction(keywords: str, market_price: float, category: str = None, notes: str = None) -> bool:
    """Log a user-provided price correction for future reference"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Normalize keywords for matching
    keywords_lower = keywords.lower().strip()
    now = datetime.now().isoformat()

    # Check if we already have this keyword
    cursor.execute("""
        SELECT id FROM price_corrections WHERE LOWER(keywords) = ?
    """, (keywords_lower,))

    existing = cursor.fetchone()

    if existing:
        # Update existing
        cursor.execute("""
            UPDATE price_corrections
            SET market_price = ?, category = ?, notes = ?, updated_at = ?
            WHERE id = ?
        """, (market_price, category, notes, now, existing[0]))
        print(f"[UPDATED] '{keywords}' -> ${market_price}")
    else:
        # Insert new
        cursor.execute("""
            INSERT INTO price_corrections (keywords, market_price, category, notes, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'user', ?, ?)
        """, (keywords_lower, market_price, category, notes, now, now))
        print(f"[LOGGED] '{keywords}' -> ${market_price}")

    conn.commit()
    conn.close()
    return True


def check_price_correction(title: str) -> Optional[Dict]:
    """Check if we have a user-provided price for keywords in the title"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    title_lower = title.lower()

    # Get all corrections and check for keyword matches
    cursor.execute("SELECT keywords, market_price, category, notes, updated_at FROM price_corrections")

    best_match = None
    for row in cursor.fetchall():
        keywords, price, cat, notes, updated = row
        # Check if all keywords appear in the title
        keyword_parts = keywords.split()
        if all(kw in title_lower for kw in keyword_parts):
            # Prefer longer keyword matches (more specific)
            if best_match is None or len(keywords) > len(best_match['keywords']):
                best_match = {
                    'keywords': keywords,
                    'market_price': price,
                    'category': cat,
                    'notes': notes,
                    'updated_at': updated
                }

    conn.close()
    return best_match


def show_corrections():
    """Display all logged price corrections"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT keywords, market_price, category, notes, updated_at
        FROM price_corrections
        ORDER BY updated_at DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("\nNo price corrections logged yet.")
        return

    print("\n" + "=" * 70)
    print("LOGGED PRICE CORRECTIONS (Your Market Knowledge)")
    print("=" * 70)

    for row in rows:
        keywords, price, cat, notes, updated = row
        cat_str = f" [{cat}]" if cat else ""
        notes_str = f" - {notes}" if notes else ""
        print(f"\n  ${price:<8.2f}  {keywords}{cat_str}{notes_str}")
        print(f"            Last updated: {updated[:10] if updated else 'Unknown'}")

    print(f"\nTotal: {len(rows)} corrections logged")


def analyze_market():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("FULL MARKET ANALYSIS")
    print("=" * 70)

    # Overall stats
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT part_number), COUNT(DISTINCT category) FROM sold_items")
    total, parts, cats = cursor.fetchone()
    print(f"\nDatabase: {total} sales | {parts} unique parts | {cats} categories")

    # Price distribution
    cursor.execute("""
        SELECT
            CASE
                WHEN sold_price < 50 THEN 'Under $50'
                WHEN sold_price < 100 THEN '$50-100'
                WHEN sold_price < 250 THEN '$100-250'
                WHEN sold_price < 500 THEN '$250-500'
                WHEN sold_price < 1000 THEN '$500-1000'
                ELSE 'Over $1000'
            END as price_range,
            COUNT(*) as count
        FROM sold_items
        WHERE sold_price > 0
        GROUP BY price_range
        ORDER BY MIN(sold_price)
    """)

    print("\nPrice Distribution:")
    for row in cursor.fetchall():
        bar = "#" * (row[1] * 2)
        print(f"  {row[0]:<15} {row[1]:>4} {bar}")

    # Seller concentration
    cursor.execute("""
        SELECT seller_name, COUNT(*) as count, ROUND(AVG(sold_price), 2) as avg
        FROM sold_items
        WHERE seller_name != ''
        GROUP BY seller_name
        ORDER BY count DESC
        LIMIT 10
    """)

    print("\nTop Sellers in Database:")
    for row in cursor.fetchall():
        print(f"  {row[0]:<30} {row[1]:>3} sales, avg ${row[2]}")

    conn.close()

    # Run deal detection
    find_deals()


async def main():
    """Main entry point"""
    init_database()

    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAdditional commands:")
        print("  --log <keywords> <price>     Log a price correction")
        print("  --corrections                Show all logged corrections")
        print("  --check <title>              Check if we have price data for a title")
        show_stats()
        return

    arg = sys.argv[1]

    if arg == "--log" and len(sys.argv) >= 4:
        # Log a price correction: --log "nyko worm light gameboy" 40
        keywords = sys.argv[2]
        try:
            price = float(sys.argv[3])
            category = sys.argv[4] if len(sys.argv) >= 5 else None
            notes = sys.argv[5] if len(sys.argv) >= 6 else None
            log_price_correction(keywords, price, category, notes)
        except ValueError:
            print(f"[ERROR] Invalid price: {sys.argv[3]}")
        return

    elif arg == "--corrections":
        show_corrections()
        return

    elif arg == "--check" and len(sys.argv) >= 3:
        # Check if we have price data for a title
        title = " ".join(sys.argv[2:])
        correction = check_price_correction(title)
        if correction:
            print(f"\n[MATCH FOUND] Keywords: '{correction['keywords']}'")
            print(f"  Market Price: ${correction['market_price']}")
            if correction['category']:
                print(f"  Category: {correction['category']}")
            if correction['notes']:
                print(f"  Notes: {correction['notes']}")
        else:
            print(f"\nNo price correction found for: {title}")

            # Also check screenshot database
            result = lookup_price(title.split()[0] if title.split() else "")
            if result:
                print(f"\n[SCREENSHOT DATA] Found in sold items database:")
                print(f"  Avg Price: ${result['avg_price']}")
        return

    elif arg == "--all":
        # Process all categories
        for category_dir in SCREENSHOTS_DIR.iterdir():
            if category_dir.is_dir():
                await process_category(category_dir.name)
    elif arg == "--stats":
        show_stats()
    elif arg == "--deals":
        category = sys.argv[2] if len(sys.argv) >= 3 else None
        find_deals(category)
    elif arg == "--analyze":
        analyze_market()
    elif arg == "--lookup" and len(sys.argv) >= 3:
        part = sys.argv[2]
        result = lookup_price(part)
        if result:
            print(f"\nPrice data for '{part}':")
            print(f"  Part Number: {result['part_number']}")
            print(f"  Sales Count: {result['sale_count']}")
            print(f"  Avg Price: ${result['avg_price']}")
            print(f"  Range: ${result['min_price']} - ${result['max_price']}")
            print(f"  Deal Price (buy below): ${result['deal_price']}")

            if result.get('sales'):
                print(f"\n  Individual Sales:")
                for sale in result['sales']:
                    seller_info = f"{sale['seller']} ({sale['feedback'] or '?'})"
                    print(f"    ${sale['price']:<10.2f} {sale['seller_type']:<12} {seller_info}")
        else:
            print(f"No data found for '{part}'")
    else:
        await process_category(arg)

    show_stats()


if __name__ == "__main__":
    asyncio.run(main())
