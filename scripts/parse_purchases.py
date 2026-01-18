"""Parse purchasehistory.html and create SQLite database"""
from bs4 import BeautifulSoup
import sqlite3
import re
from datetime import datetime

def parse_purchase_history():
    with open('purchasehistory.html', 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    # Get all td elements
    tds = soup.find_all('td')
    print(f'Total td elements: {len(tds)}')

    # 9 columns per row
    cols_per_row = 9
    num_purchases = len(tds) // cols_per_row
    print(f'Estimated purchases: {num_purchases}')

    # Parse into records
    purchases = []
    for i in range(num_purchases):
        start = i * cols_per_row
        row_tds = tds[start:start + cols_per_row]
        if len(row_tds) == 9:
            purchases.append({
                'date': row_tds[0].get_text(strip=True),
                'item_id': row_tds[1].get_text(strip=True),
                'title': row_tds[2].get_text(strip=True),
                'price': row_tds[3].get_text(strip=True),
                'quantity': row_tds[4].get_text(strip=True),
                'shipping': row_tds[5].get_text(strip=True),
                'total': row_tds[6].get_text(strip=True),
                'currency': row_tds[7].get_text(strip=True),
                'seller': row_tds[8].get_text(strip=True)
            })

    print(f'Parsed purchases: {len(purchases)}')
    return purchases

def categorize_purchase(title):
    """Categorize purchase based on title keywords"""
    title_lower = title.lower()

    # Gold indicators
    gold_keywords = ['14k', '18k', '10k', '22k', '24k', '9k', '8k', '14kt', '18kt', '10kt',
                     'gold', '585', '750', '417', '375', 'karat']
    if any(kw in title_lower for kw in gold_keywords) and 'gold' in title_lower or any(kw in title_lower for kw in ['14k', '18k', '10k', '22k', '24k', '9k', '8k', '14kt', '18kt', '10kt', '585', '750', '417', '375']):
        return 'gold'

    # Silver indicators
    silver_keywords = ['sterling', '925', 'silver', '800 silver', '900 silver', 'gorham',
                       'towle', 'wallace', 'reed barton', 'flatware', 'silverware']
    if any(kw in title_lower for kw in silver_keywords):
        return 'silver'

    # Native/Turquoise
    native_keywords = ['navajo', 'zuni', 'hopi', 'turquoise', 'squash blossom', 'native american',
                       'southwestern', 'pueblo', 'old pawn', 'taxco']
    if any(kw in title_lower for kw in native_keywords):
        return 'native'

    # Watches
    watch_keywords = ['watch', 'omega', 'rolex', 'breitling', 'hamilton', 'seiko', 'bulova',
                      'girard', 'longines', 'tissot', 'wristwatch', 'pocket watch']
    if any(kw in title_lower for kw in watch_keywords):
        return 'watches'

    # TCG
    tcg_keywords = ['pokemon', 'charizard', 'booster', 'tcg', 'mtg', 'magic gathering',
                    'yugioh', 'trading card', 'sealed box']
    if any(kw in title_lower for kw in tcg_keywords):
        return 'tcg'

    # Video Games
    game_keywords = ['nintendo', 'snes', 'nes', 'n64', 'gamecube', 'playstation', 'xbox',
                     'cib', 'complete in box', 'game boy', 'genesis', 'sega']
    if any(kw in title_lower for kw in game_keywords):
        return 'videogames'

    # Lego
    if 'lego' in title_lower:
        return 'lego'

    # Costume jewelry
    costume_keywords = ['trifari', 'costume', 'bakelite', 'rhinestone']
    if any(kw in title_lower for kw in costume_keywords):
        return 'costume'

    # Coral/Amber
    coral_amber = ['coral', 'amber', 'baltic']
    if any(kw in title_lower for kw in coral_amber):
        return 'coral_amber'

    # Coins/Bullion
    coin_keywords = ['coin', 'bullion', 'morgan', 'peace dollar', 'silver eagle', 'gold eagle',
                     'krugerrand', 'maple leaf', 'bar', 'round', '.999']
    if any(kw in title_lower for kw in coin_keywords):
        return 'coins'

    return 'other'

def extract_keywords(title):
    """Extract significant keywords from title"""
    # Remove common words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                  'of', 'with', 'by', 'from', 'is', 'it', 'as', 'be', 'this', 'that',
                  'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had', 'do',
                  'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
                  'must', 'can', 'not', 'no', 'so', 'if', 'then', 'than', 'too', 'very',
                  'just', 'only', 'also', 'new', 'used', 'vintage', 'antique', 'lot'}

    # Clean and tokenize
    title_clean = re.sub(r'[^\w\s]', ' ', title.lower())
    words = title_clean.split()

    # Filter and return unique keywords
    keywords = [w for w in words if w not in stop_words and len(w) > 1 and not w.isdigit()]
    return list(set(keywords))

def create_database(purchases):
    """Create SQLite database with purchase history"""
    conn = sqlite3.connect('purchase_history.db')
    cur = conn.cursor()

    # Create purchases table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_date TEXT,
            item_id TEXT UNIQUE,
            title TEXT,
            price REAL,
            quantity INTEGER,
            shipping REAL,
            total REAL,
            currency TEXT,
            seller TEXT,
            category TEXT,
            keywords TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create keywords analysis table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS keyword_stats (
            keyword TEXT PRIMARY KEY,
            category TEXT,
            times_purchased INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            last_purchased TEXT
        )
    ''')

    # Insert purchases
    inserted = 0
    for p in purchases:
        try:
            price = float(p['price'].replace(',', '')) if p['price'] else 0
            shipping = float(p['shipping'].replace(',', '')) if p['shipping'] else 0
            total = float(p['total'].replace(',', '')) if p['total'] else 0
            quantity = int(p['quantity']) if p['quantity'] else 1

            category = categorize_purchase(p['title'])
            keywords = ','.join(extract_keywords(p['title']))

            cur.execute('''
                INSERT OR IGNORE INTO purchases
                (purchase_date, item_id, title, price, quantity, shipping, total, currency, seller, category, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (p['date'], p['item_id'], p['title'], price, quantity, shipping, total,
                  p['currency'], p['seller'], category, keywords))

            if cur.rowcount > 0:
                inserted += 1

        except Exception as e:
            print(f"Error inserting {p['title'][:50]}: {e}")

    conn.commit()
    print(f'Inserted {inserted} purchases into database')

    # Update keyword stats
    cur.execute('DELETE FROM keyword_stats')
    cur.execute('''
        SELECT keywords, category, total, purchase_date FROM purchases
    ''')

    keyword_data = {}
    for row in cur.fetchall():
        keywords = row[0].split(',') if row[0] else []
        category = row[1]
        total = row[2]
        date = row[3]

        for kw in keywords:
            if kw:
                if kw not in keyword_data:
                    keyword_data[kw] = {'category': category, 'count': 0, 'total_spent': 0, 'last_date': date}
                keyword_data[kw]['count'] += 1
                keyword_data[kw]['total_spent'] += total
                keyword_data[kw]['last_date'] = date

    for kw, data in keyword_data.items():
        avg = data['total_spent'] / data['count'] if data['count'] > 0 else 0
        cur.execute('''
            INSERT INTO keyword_stats (keyword, category, times_purchased, total_spent, avg_price, last_purchased)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (kw, data['category'], data['count'], data['total_spent'], avg, data['last_date']))

    conn.commit()
    print(f'Updated {len(keyword_data)} keyword stats')

    # Print summary
    print('\n=== PURCHASE SUMMARY BY CATEGORY ===')
    cur.execute('''
        SELECT category, COUNT(*) as count, SUM(total) as total_spent, AVG(total) as avg_price
        FROM purchases
        GROUP BY category
        ORDER BY total_spent DESC
    ''')
    for row in cur.fetchall():
        print(f'{row[0]}: {row[1]} purchases, ${row[2]:.2f} total, ${row[3]:.2f} avg')

    print('\n=== TOP KEYWORDS BY PURCHASE COUNT ===')
    cur.execute('''
        SELECT keyword, times_purchased, total_spent, avg_price
        FROM keyword_stats
        ORDER BY times_purchased DESC
        LIMIT 30
    ''')
    for row in cur.fetchall():
        print(f'"{row[0]}": {row[1]} purchases, ${row[2]:.2f} spent, ${row[3]:.2f} avg')

    conn.close()

if __name__ == '__main__':
    purchases = parse_purchase_history()

    print('\n=== FIRST 20 PURCHASES ===')
    for p in purchases[:20]:
        print(f"${p['total']:>8} | {p['title'][:65]}")

    print('\n=== CREATING DATABASE ===')
    create_database(purchases)
