"""
Parse eBay Purchase and Selling History HTML exports
Import into SQLite database and analyze profit/loss
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from dataclasses import dataclass
from typing import List, Optional, Tuple
import json

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "ebay_history.db"


@dataclass
class Purchase:
    date: datetime
    item_id: str
    title: str
    price: float
    quantity: int
    shipping: float
    total: float
    currency: str
    seller: str


@dataclass
class Sale:
    date: datetime
    item_id: str
    title: str
    price: float
    quantity: int
    shipping: float
    currency: str
    buyer: str


class EbayHTMLParser(HTMLParser):
    """Parse eBay HTML export tables - handles malformed HTML missing <tr> tags"""

    def __init__(self, cols_per_row: int = 9):
        super().__init__()
        self.in_td = False
        self.all_cells = []  # Collect ALL td values
        self.rows = []
        self.current_data = ""
        self.cols_per_row = cols_per_row

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.in_td = True
            self.current_data = ""

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_td = False
            self.all_cells.append(self.current_data.strip())

    def handle_data(self, data):
        if self.in_td:
            self.current_data += data

    def get_rows(self) -> List[List[str]]:
        """Batch cells into rows of cols_per_row each"""
        rows = []
        for i in range(0, len(self.all_cells), self.cols_per_row):
            row = self.all_cells[i:i + self.cols_per_row]
            if len(row) == self.cols_per_row:
                rows.append(row)
        return rows


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse eBay date format: 'Oct 07, 2023 04:16 PM'"""
    try:
        return datetime.strptime(date_str.strip(), "%b %d, %Y %I:%M %p")
    except:
        try:
            return datetime.strptime(date_str.strip(), "%b %d, %Y")
        except:
            return None


def parse_float(val: str) -> float:
    """Parse price string to float"""
    try:
        return float(val.replace(",", "").replace("$", "").strip())
    except:
        return 0.0


def parse_purchase_html(filepath: Path) -> List[Purchase]:
    """Parse purchase history HTML"""
    print(f"Parsing purchases from {filepath}...")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 9 columns: Date, Item Id, Title, Price, Qty, Shipping, Total, Currency, Seller
    parser = EbayHTMLParser(cols_per_row=9)
    parser.feed(content)

    purchases = []
    for row in parser.get_rows():
        date = parse_date(row[0])
        if date:
            purchases.append(Purchase(
                date=date,
                item_id=row[1].strip(),
                title=row[2].strip(),
                price=parse_float(row[3]),
                quantity=int(row[4]) if row[4].strip().isdigit() else 1,
                shipping=parse_float(row[5]),
                total=parse_float(row[6]),
                currency=row[7].strip(),
                seller=row[8].strip()
            ))

    print(f"  Found {len(purchases)} purchases")
    return purchases


def parse_selling_html(filepath: Path) -> List[Sale]:
    """Parse selling history HTML"""
    print(f"Parsing sales from {filepath}...")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 8 columns: Date, Item Id, Title, Price, Qty, Shipping, Currency, Buyer
    parser = EbayHTMLParser(cols_per_row=8)
    parser.feed(content)

    sales = []
    for row in parser.get_rows():
        date = parse_date(row[0])
        if date:
            sales.append(Sale(
                date=date,
                item_id=row[1].strip(),
                title=row[2].strip(),
                price=parse_float(row[3]),
                quantity=int(row[4]) if row[4].strip().isdigit() else 1,
                shipping=parse_float(row[5]),
                currency=row[6].strip(),
                buyer=row[7].strip()
            ))

    print(f"  Found {len(sales)} sales")
    return sales


def init_database(db_path: Path):
    """Create database tables"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            item_id TEXT,
            title TEXT,
            price REAL,
            quantity INTEGER,
            shipping REAL,
            total REAL,
            currency TEXT,
            seller TEXT,
            UNIQUE(item_id, date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            item_id TEXT,
            title TEXT,
            price REAL,
            quantity INTEGER,
            shipping REAL,
            currency TEXT,
            buyer TEXT,
            UNIQUE(item_id, date)
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchases_item_id ON purchases(item_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_item_id ON sales(item_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(date)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)
    """)

    conn.commit()
    return conn


def import_purchases(conn: sqlite3.Connection, purchases: List[Purchase]) -> int:
    """Import purchases into database"""
    c = conn.cursor()
    imported = 0

    for p in purchases:
        try:
            c.execute("""
                INSERT OR IGNORE INTO purchases
                (date, item_id, title, price, quantity, shipping, total, currency, seller)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p.date.isoformat(),
                p.item_id,
                p.title,
                p.price,
                p.quantity,
                p.shipping,
                p.total,
                p.currency,
                p.seller
            ))
            if c.rowcount > 0:
                imported += 1
        except Exception as e:
            print(f"  Error importing purchase {p.item_id}: {e}")

    conn.commit()
    return imported


def import_sales(conn: sqlite3.Connection, sales: List[Sale]) -> int:
    """Import sales into database"""
    c = conn.cursor()
    imported = 0

    for s in sales:
        try:
            c.execute("""
                INSERT OR IGNORE INTO sales
                (date, item_id, title, price, quantity, shipping, currency, buyer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.date.isoformat(),
                s.item_id,
                s.title,
                s.price,
                s.quantity,
                s.shipping,
                s.currency,
                s.buyer
            ))
            if c.rowcount > 0:
                imported += 1
        except Exception as e:
            print(f"  Error importing sale {s.item_id}: {e}")

    conn.commit()
    return imported


def analyze_data(conn: sqlite3.Connection):
    """Analyze purchase and sales data"""
    c = conn.cursor()

    print("\n" + "="*60)
    print("EBAY HISTORY ANALYSIS")
    print("="*60)

    # Purchase stats
    c.execute("SELECT COUNT(*), SUM(total + shipping), MIN(date), MAX(date) FROM purchases")
    p_count, p_total, p_min_date, p_max_date = c.fetchone()
    p_total = p_total or 0

    print(f"\n[PURCHASES]")
    print(f"   Total items: {p_count:,}")
    print(f"   Total spent: ${p_total:,.2f}")
    print(f"   Date range: {p_min_date[:10] if p_min_date else 'N/A'} to {p_max_date[:10] if p_max_date else 'N/A'}")

    # Sales stats
    c.execute("SELECT COUNT(*), SUM(price), MIN(date), MAX(date) FROM sales")
    s_count, s_total, s_min_date, s_max_date = c.fetchone()
    s_total = s_total or 0

    print(f"\n[SALES]")
    print(f"   Total items: {s_count:,}")
    print(f"   Total revenue: ${s_total:,.2f}")
    print(f"   Date range: {s_min_date[:10] if s_min_date else 'N/A'} to {s_max_date[:10] if s_max_date else 'N/A'}")

    # Gross profit
    gross_profit = s_total - p_total
    print(f"\n[GROSS PROFIT/LOSS]")
    print(f"   Revenue - Cost = ${s_total:,.2f} - ${p_total:,.2f}")
    print(f"   Gross: ${gross_profit:,.2f}")

    # Top sellers bought from
    print(f"\n[TOP 10 SELLERS] (by spend)")
    c.execute("""
        SELECT seller, COUNT(*) as items, SUM(total + shipping) as spent
        FROM purchases
        GROUP BY seller
        ORDER BY spent DESC
        LIMIT 10
    """)
    for seller, items, spent in c.fetchall():
        print(f"   {seller[:25]:<25} {items:>4} items  ${spent:>10,.2f}")

    # Top buyers
    print(f"\n[TOP 10 BUYERS] (by revenue)")
    c.execute("""
        SELECT buyer, COUNT(*) as items, SUM(price) as revenue
        FROM sales
        GROUP BY buyer
        ORDER BY revenue DESC
        LIMIT 10
    """)
    for buyer, items, revenue in c.fetchall():
        print(f"   {buyer[:25]:<25} {items:>4} items  ${revenue:>10,.2f}")

    # Monthly purchase breakdown
    print(f"\n[MONTHLY PURCHASES] (last 12 months)")
    c.execute("""
        SELECT strftime('%Y-%m', date) as month, COUNT(*), SUM(total + shipping)
        FROM purchases
        WHERE date >= date('now', '-12 months')
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    for month, count, total in c.fetchall():
        print(f"   {month}: {count:>4} items  ${total:>10,.2f}")

    # Monthly sales breakdown
    print(f"\n[MONTHLY SALES] (last 12 months)")
    c.execute("""
        SELECT strftime('%Y-%m', date) as month, COUNT(*), SUM(price)
        FROM sales
        WHERE date >= date('now', '-12 months')
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    for month, count, total in c.fetchall():
        total = total or 0
        print(f"   {month}: {count:>4} items  ${total:>10,.2f}")

    # Category analysis (based on keywords)
    print(f"\n[PURCHASE CATEGORIES] (estimated)")
    categories = {
        'Gold/Jewelry': ['gold', '14k', '10k', '18k', '24k', 'karat', 'jewelry', 'ring', 'bracelet', 'necklace', 'pendant'],
        'Silver/Sterling': ['silver', 'sterling', '925', 'silverware', 'flatware'],
        'Video Games': ['game', 'nintendo', 'playstation', 'xbox', 'sega', 'atari', 'pokemon', 'ps1', 'ps2', 'ps3', 'ps4', 'ps5', 'wii', 'gamecube'],
        'LEGO': ['lego', 'minifig'],
        'Electronics': ['camera', 'phone', 'laptop', 'computer', 'monitor', 'tv', 'speaker'],
        'Watches': ['watch', 'seiko', 'citizen', 'timex', 'casio', 'rolex', 'omega'],
        'Coins': ['coin', 'penny', 'quarter', 'dollar', 'mint', 'bullion'],
    }

    for cat_name, keywords in categories.items():
        conditions = ' OR '.join([f"LOWER(title) LIKE '%{kw}%'" for kw in keywords])
        c.execute(f"""
            SELECT COUNT(*), SUM(total + shipping)
            FROM purchases
            WHERE {conditions}
        """)
        count, total = c.fetchone()
        total = total or 0
        if count > 0:
            print(f"   {cat_name:<20} {count:>5} items  ${total:>12,.2f}")

    # Find matched buy/sell pairs (same item_id or similar title)
    print(f"\n[MATCHED BUY/SELL] (same item_id)")
    c.execute("""
        SELECT p.title, p.total + p.shipping as cost, s.price as sold,
               s.price - (p.total + p.shipping) as profit,
               p.date as bought, s.date as sold_date
        FROM purchases p
        INNER JOIN sales s ON p.item_id = s.item_id
        ORDER BY profit DESC
        LIMIT 15
    """)
    matches = c.fetchall()
    if matches:
        total_profit = 0
        for title, cost, sold, profit, bought, sold_date in matches:
            total_profit += profit
            print(f"   ${profit:>8,.2f} profit | ${cost:.2f} -> ${sold:.2f} | {title[:40]}")
        print(f"\n   Total matched profit: ${total_profit:,.2f}")
    else:
        print("   No exact item_id matches found (items may have been relisted)")

    print("\n" + "="*60)


def normalize_title(title: str) -> str:
    """Normalize title for matching"""
    import re
    t = title.lower()
    # Remove common noise words
    noise = ['vintage', 'antique', 'estate', 'beautiful', 'nice', 'great', 'excellent',
             'rare', 'authentic', 'genuine', 'real', 'solid', 'heavy', 'thick',
             'free shipping', 'fast shipping', 'new', 'pre-owned', 'used']
    for word in noise:
        t = t.replace(word, '')
    # Remove special chars, keep alphanumeric and spaces
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    # Collapse whitespace
    t = ' '.join(t.split())
    return t


def get_title_tokens(title: str) -> set:
    """Get significant tokens from title"""
    t = normalize_title(title)
    # Filter short words
    tokens = {w for w in t.split() if len(w) > 2}
    return tokens


def title_similarity(t1: str, t2: str) -> float:
    """Calculate Jaccard similarity between two titles"""
    tokens1 = get_title_tokens(t1)
    tokens2 = get_title_tokens(t2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)


import csv

def match_by_title(conn: sqlite3.Connection, min_similarity: float = 0.5, export_csv: bool = True):
    """Match purchases to sales by title similarity"""
    c = conn.cursor()

    print("\n" + "="*70)
    print("TITLE-BASED MATCHING (Purchase -> Sale)")
    print("="*70)

    # Get all purchases and sales
    c.execute("""
        SELECT id, date, item_id, title, price, shipping, total, seller
        FROM purchases ORDER BY date
    """)
    purchases = c.fetchall()

    c.execute("""
        SELECT id, date, item_id, title, price, shipping, buyer
        FROM sales ORDER BY date
    """)
    sales = c.fetchall()

    print(f"\nAnalyzing {len(purchases)} purchases and {len(sales)} sales...")
    print(f"Minimum similarity threshold: {min_similarity*100:.0f}%")

    matches = []
    used_sales = set()

    for p_id, p_date, p_item_id, p_title, p_price, p_ship, p_total, p_seller in purchases:
        p_cost = (p_total or p_price) + (p_ship or 0)
        p_date_dt = datetime.fromisoformat(p_date)

        best_match = None
        best_sim = 0

        for s_id, s_date, s_item_id, s_title, s_price, s_ship, s_buyer in sales:
            if s_id in used_sales:
                continue

            s_date_dt = datetime.fromisoformat(s_date)

            # Sale must be after purchase
            if s_date_dt <= p_date_dt:
                continue

            sim = title_similarity(p_title, s_title)
            if sim > best_sim and sim >= min_similarity:
                best_sim = sim
                best_match = (s_id, s_date, s_title, s_price, s_ship, s_buyer)

        if best_match:
            s_id, s_date, s_title, s_price, s_ship, s_buyer = best_match
            used_sales.add(s_id)
            profit = s_price - p_cost
            hold_days = (datetime.fromisoformat(s_date) - p_date_dt).days
            matches.append({
                'p_title': p_title,
                's_title': s_title,
                'cost': p_cost,
                'sold': s_price,
                'profit': profit,
                'similarity': best_sim,
                'p_date': p_date[:10],
                's_date': s_date[:10],
                'hold_days': hold_days,
                'seller': p_seller,
                'buyer': s_buyer
            })

    # Sort by profit
    matches.sort(key=lambda x: x['profit'], reverse=True)

    total_cost = sum(m['cost'] for m in matches)
    total_revenue = sum(m['sold'] for m in matches)
    total_profit = sum(m['profit'] for m in matches)

    print(f"\n[MATCHED TRANSACTIONS]: {len(matches)} pairs found")
    print(f"   Total cost:    ${total_cost:,.2f}")
    print(f"   Total revenue: ${total_revenue:,.2f}")
    print(f"   Total profit:  ${total_profit:,.2f}")
    if total_cost > 0:
        print(f"   ROI:           {(total_profit/total_cost)*100:.1f}%")

    # Show top profitable matches
    print(f"\n[TOP 20 PROFITABLE MATCHES]")
    print("-"*70)
    for m in matches[:20]:
        print(f"   +${m['profit']:>8,.2f} | ${m['cost']:.2f} -> ${m['sold']:.2f} | {m['hold_days']:>3}d | {m['similarity']*100:.0f}%")
        print(f"      BUY:  {m['p_title'][:60]}")
        print(f"      SELL: {m['s_title'][:60]}")
        print()

    # Show worst matches (losses)
    losses = [m for m in matches if m['profit'] < 0]
    if losses:
        losses.sort(key=lambda x: x['profit'])
        print(f"\n[TOP 20 LOSSES]")
        print("-"*70)
        for m in losses[:20]:
            print(f"   ${m['profit']:>9,.2f} | ${m['cost']:.2f} -> ${m['sold']:.2f} | {m['hold_days']:>3}d | {m['similarity']*100:.0f}%")
            print(f"      BUY:  {m['p_title'][:60]}")
            print(f"      SELL: {m['s_title'][:60]}")
            print()

    # Category breakdown of matched items
    print(f"\n[PROFIT BY CATEGORY]")
    categories = {
        'Gold': ['gold', '14k', '10k', '18k', '24k', '22k', '9k'],
        'Silver': ['silver', 'sterling', '925'],
        'Watch': ['watch'],
        'Other': []
    }

    cat_stats = {cat: {'count': 0, 'cost': 0, 'revenue': 0, 'profit': 0} for cat in categories}

    for m in matches:
        title_lower = m['p_title'].lower()
        matched_cat = 'Other'
        for cat, keywords in categories.items():
            if cat == 'Other':
                continue
            if any(kw in title_lower for kw in keywords):
                matched_cat = cat
                break

        cat_stats[matched_cat]['count'] += 1
        cat_stats[matched_cat]['cost'] += m['cost']
        cat_stats[matched_cat]['revenue'] += m['sold']
        cat_stats[matched_cat]['profit'] += m['profit']

    print(f"   {'Category':<12} {'Count':>6} {'Cost':>12} {'Revenue':>12} {'Profit':>12} {'ROI':>8}")
    print("   " + "-"*64)
    for cat, stats in cat_stats.items():
        if stats['count'] > 0:
            roi = (stats['profit'] / stats['cost'] * 100) if stats['cost'] > 0 else 0
            print(f"   {cat:<12} {stats['count']:>6} ${stats['cost']:>11,.2f} ${stats['revenue']:>11,.2f} ${stats['profit']:>11,.2f} {roi:>7.1f}%")

    # Average hold time
    if matches:
        avg_hold = sum(m['hold_days'] for m in matches) / len(matches)
        print(f"\n[TIMING]")
        print(f"   Average hold time: {avg_hold:.0f} days")
        print(f"   Fastest flip: {min(m['hold_days'] for m in matches)} days")
        print(f"   Longest hold: {max(m['hold_days'] for m in matches)} days")

    # Unmatched analysis
    unmatched_purchases = len(purchases) - len(matches)
    unmatched_sales = len(sales) - len(used_sales)

    print(f"\n[UNMATCHED]")
    print(f"   Purchases without matching sale: {unmatched_purchases} (likely still in inventory)")
    print(f"   Sales without matching purchase: {unmatched_sales} (bought before export period or different source)")

    # Calculate estimated inventory value
    c.execute("""
        SELECT SUM(total + shipping) FROM purchases
    """)
    total_purchased = c.fetchone()[0] or 0

    inventory_cost = total_purchased - total_cost
    print(f"\n[ESTIMATED INVENTORY]")
    print(f"   Unsold inventory cost basis: ${inventory_cost:,.2f}")
    if total_cost > 0 and total_profit > 0:
        est_inventory_value = inventory_cost * (1 + total_profit/total_cost)
        print(f"   Estimated value (at matched ROI): ${est_inventory_value:,.2f}")

    # Export to CSV
    if export_csv and matches:
        csv_path = BASE_DIR / "matched_transactions.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Purchase Title', 'Sale Title', 'Cost', 'Sold', 'Profit',
                'ROI %', 'Similarity %', 'Purchase Date', 'Sale Date',
                'Hold Days', 'Seller', 'Buyer', 'Category'
            ])

            for m in matches:
                # Determine category
                title_lower = m['p_title'].lower()
                if any(kw in title_lower for kw in ['gold', '14k', '10k', '18k', '24k', '22k', '9k']):
                    cat = 'Gold'
                elif any(kw in title_lower for kw in ['silver', 'sterling', '925']):
                    cat = 'Silver'
                elif 'watch' in title_lower:
                    cat = 'Watch'
                else:
                    cat = 'Other'

                roi_pct = (m['profit'] / m['cost'] * 100) if m['cost'] > 0 else 0

                writer.writerow([
                    m['p_title'],
                    m['s_title'],
                    f"{m['cost']:.2f}",
                    f"{m['sold']:.2f}",
                    f"{m['profit']:.2f}",
                    f"{roi_pct:.1f}",
                    f"{m['similarity']*100:.0f}",
                    m['p_date'],
                    m['s_date'],
                    m['hold_days'],
                    m['seller'],
                    m['buyer'],
                    cat
                ])

        print(f"\n[EXPORTED] Matched transactions saved to: {csv_path}")

        # Also export unmatched purchases (inventory)
        inventory_csv_path = BASE_DIR / "unmatched_inventory.csv"
        c.execute("""
            SELECT date, item_id, title, price, shipping, total, seller
            FROM purchases
            ORDER BY date DESC
        """)
        all_purchases = c.fetchall()

        matched_titles = {normalize_title(m['p_title']) for m in matches}

        with open(inventory_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Purchase Date', 'Item ID', 'Title', 'Price', 'Shipping', 'Total Cost', 'Seller', 'Category'])

            for p_date, p_item_id, p_title, p_price, p_ship, p_total, p_seller in all_purchases:
                if normalize_title(p_title) not in matched_titles:
                    title_lower = p_title.lower()
                    if any(kw in title_lower for kw in ['gold', '14k', '10k', '18k', '24k', '22k', '9k']):
                        cat = 'Gold'
                    elif any(kw in title_lower for kw in ['silver', 'sterling', '925']):
                        cat = 'Silver'
                    elif 'watch' in title_lower:
                        cat = 'Watch'
                    else:
                        cat = 'Other'

                    total_cost = (p_total or p_price) + (p_ship or 0)
                    writer.writerow([
                        p_date[:10],
                        p_item_id,
                        p_title,
                        f"{p_price:.2f}",
                        f"{p_ship:.2f}",
                        f"{total_cost:.2f}",
                        p_seller,
                        cat
                    ])

        print(f"[EXPORTED] Unmatched inventory saved to: {inventory_csv_path}")

    return matches


def main():
    purchase_file = BASE_DIR / "purchaseHistoryextensive1.html"
    selling_file = BASE_DIR / "sellingHistory.html"

    # Parse HTML files
    purchases = parse_purchase_html(purchase_file)
    sales = parse_selling_html(selling_file)

    # Initialize database
    print(f"\nInitializing database at {DB_PATH}...")
    conn = init_database(DB_PATH)

    # Import data
    print("\nImporting data...")
    p_imported = import_purchases(conn, purchases)
    s_imported = import_sales(conn, sales)
    print(f"  Imported {p_imported} purchases, {s_imported} sales")

    # Analyze
    analyze_data(conn)

    # Match by title
    match_by_title(conn, min_similarity=0.4)

    conn.close()
    print(f"\nDatabase saved to: {DB_PATH}")


if __name__ == "__main__":
    main()
