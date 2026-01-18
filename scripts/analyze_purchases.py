"""Analyze purchase history for scoring insights"""
import sqlite3
from collections import defaultdict

conn = sqlite3.connect('purchase_history.db')
c = conn.cursor()

c.execute('SELECT title, price, total FROM purchases')
rows = c.fetchall()

print(f'Analyzing {len(rows)} purchase titles...\n')

# Keyword analysis
keyword_counts = defaultdict(lambda: {'count': 0, 'total_spent': 0})
keywords_to_check = [
    'scrap', 'lot', 'grams', 'dwt', 'oz', 'tested', 'wearable',
    'vintage', 'antique', 'estate', 'ring', 'necklace', 'bracelet',
    'earring', 'pendant', 'brooch', 'flatware', 'spoon', 'fork',
    'sterling', '925', '14k', '10k', '18k', '24k', 'gold', 'silver',
    'broken', 'parts', 'repair', 'diamond', 'gemstone', 'pearl',
    'watch', 'rolex', 'omega', 'seiko', 'pokemon', 'psa', 'cgc'
]

for title, price, total in rows:
    title_lower = (title or '').lower()
    spent = float(total or price or 0)
    for kw in keywords_to_check:
        if kw in title_lower:
            keyword_counts[kw]['count'] += 1
            keyword_counts[kw]['total_spent'] += spent

print('=== KEYWORDS IN PURCHASED ITEMS ===')
sorted_kw = sorted(keyword_counts.items(), key=lambda x: x[1]['count'], reverse=True)
for kw, data in sorted_kw[:25]:
    if data['count'] > 0:
        avg = data['total_spent'] / data['count']
        pct = data['count'] / len(rows) * 100
        print(f"  {kw:<12} | {data['count']:>4} ({pct:>4.1f}%) | Avg ${avg:>6.0f}")

# Category breakdown
print('\n=== CATEGORY BREAKDOWN ===')
categories = defaultdict(lambda: {'count': 0, 'spent': 0})

for title, price, total in rows:
    title_lower = (title or '').lower()
    spent = float(total or price or 0)

    if 'pokemon' in title_lower or 'psa' in title_lower or 'cgc' in title_lower:
        categories['tcg']['count'] += 1
        categories['tcg']['spent'] += spent
    elif 'nintendo' in title_lower or 'playstation' in title_lower or 'xbox' in title_lower:
        categories['videogames']['count'] += 1
        categories['videogames']['spent'] += spent
    elif 'watch' in title_lower or 'rolex' in title_lower or 'omega' in title_lower:
        categories['watch']['count'] += 1
        categories['watch']['spent'] += spent
    elif '14k' in title_lower or '10k' in title_lower or '18k' in title_lower or '24k' in title_lower:
        categories['gold']['count'] += 1
        categories['gold']['spent'] += spent
    elif 'sterling' in title_lower or '925' in title_lower or 'silver' in title_lower:
        categories['silver']['count'] += 1
        categories['silver']['spent'] += spent

for cat, data in sorted(categories.items(), key=lambda x: x[1]['count'], reverse=True):
    if data['count'] > 0:
        avg = data['spent'] / data['count']
        pct = data['count'] / len(rows) * 100
        print(f"  {cat:<12} | {data['count']:>4} ({pct:>4.1f}%) | Avg ${avg:>6.0f} | Total ${data['spent']:>10.0f}")

# Item type analysis (from title patterns)
print('\n=== ITEM TYPES (from titles) ===')
type_counts = defaultdict(lambda: {'count': 0, 'spent': 0})
types = ['ring', 'necklace', 'bracelet', 'earring', 'pendant', 'brooch',
         'flatware', 'spoon', 'fork', 'chain', 'charm', 'pin', 'watch']

for title, price, total in rows:
    title_lower = (title or '').lower()
    spent = float(total or price or 0)
    for t in types:
        if t in title_lower:
            type_counts[t]['count'] += 1
            type_counts[t]['spent'] += spent
            break  # Only count first match

for t, data in sorted(type_counts.items(), key=lambda x: x[1]['count'], reverse=True):
    if data['count'] >= 5:
        avg = data['spent'] / data['count']
        pct = data['count'] / len(rows) * 100
        print(f"  {t:<12} | {data['count']:>4} ({pct:>4.1f}%) | Avg ${avg:>6.0f}")

# Price range analysis
print('\n=== PRICE RANGES ===')
price_ranges = {'<$50': 0, '$50-100': 0, '$100-250': 0, '$250-500': 0, '$500-1000': 0, '$1000+': 0}
for title, price, total in rows:
    p = float(total or price or 0)
    if p < 50: price_ranges['<$50'] += 1
    elif p < 100: price_ranges['$50-100'] += 1
    elif p < 250: price_ranges['$100-250'] += 1
    elif p < 500: price_ranges['$250-500'] += 1
    elif p < 1000: price_ranges['$500-1000'] += 1
    else: price_ranges['$1000+'] += 1

for pr, count in price_ranges.items():
    pct = count / len(rows) * 100
    print(f"  {pr:<12} | {count:>4} ({pct:>4.1f}%)")

# Top purchases
print('\n=== TOP 20 PURCHASES BY VALUE ===')
c.execute('''SELECT title, total, seller FROM purchases
WHERE total > 200 ORDER BY total DESC LIMIT 20''')
for title, total, seller in c.fetchall():
    print(f"  ${total:>7.0f} | {seller[:12]:<12} | {title[:50]}")

# Ring analysis - are rings actually bad?
print('\n=== RING PURCHASES ANALYSIS ===')
c.execute('SELECT title, total FROM purchases WHERE lower(title) LIKE "%ring%"')
ring_rows = c.fetchall()
ring_values = [float(r[1] or 0) for r in ring_rows]
if ring_values:
    print(f"  Total ring purchases: {len(ring_rows)}")
    print(f"  Avg value: ${sum(ring_values)/len(ring_values):.0f}")
    print(f"  High value (>$300): {len([v for v in ring_values if v > 300])}")
    print(f"  Rings ARE being purchased at good value - maybe penalty too harsh?")

# Vintage analysis
print('\n=== VINTAGE ANALYSIS ===')
c.execute('SELECT COUNT(*) FROM purchases WHERE lower(title) LIKE "%vintage%"')
vintage_count = c.fetchone()[0]
print(f"  Vintage purchases: {vintage_count} ({vintage_count/len(rows)*100:.1f}%)")
print(f"  You buy plenty of vintage items - penalty may be wrong")

conn.close()
