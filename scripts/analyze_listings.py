"""Analyze listings for seller profiling insights"""
import sqlite3
import json
from collections import Counter, defaultdict

conn = sqlite3.connect('arbitrage_data.db')
cursor = conn.cursor()

cursor.execute('''
SELECT recommendation, category, input_data, title, total_price
FROM listings
WHERE timestamp > "2026-01-01"
AND input_data IS NOT NULL
''')
rows = cursor.fetchall()

print(f'Analyzing {len(rows)} listings...\n')

# Listing characteristics
listing_stats = {
    'best_offer': {'buy': 0, 'total': 0},
    'no_best_offer': {'buy': 0, 'total': 0},
    'has_upc': {'buy': 0, 'total': 0},
    'no_upc': {'buy': 0, 'total': 0},
}

# Condition analysis
condition_stats = defaultdict(lambda: {'buy': 0, 'total': 0})

# Description presence
desc_stats = {
    'has_description': {'buy': 0, 'total': 0},
    'no_description': {'buy': 0, 'total': 0},
    'has_cond_desc': {'buy': 0, 'total': 0},
    'no_cond_desc': {'buy': 0, 'total': 0},
}

# Title word patterns
title_patterns = {
    'scrap': {'buy': 0, 'total': 0},
    'lot': {'buy': 0, 'total': 0},
    'vintage': {'buy': 0, 'total': 0},
    'antique': {'buy': 0, 'total': 0},
    'estate': {'buy': 0, 'total': 0},
    'tested': {'buy': 0, 'total': 0},
    'grams': {'buy': 0, 'total': 0},
    'dwt': {'buy': 0, 'total': 0},
    'not scrap': {'buy': 0, 'total': 0},
    'wearable': {'buy': 0, 'total': 0},
}

# Price range analysis
price_by_cat = defaultdict(lambda: defaultdict(lambda: {'buy': 0, 'total': 0}))

for rec, cat, input_data, title, price in rows:
    try:
        data = json.loads(input_data)
        is_buy = rec == 'BUY'
        title_lower = (title or '').lower()

        # Best offer
        best_offer = str(data.get('BestOffer', data.get('bestoffer', ''))).lower()
        if best_offer in ['true', 'yes', '1']:
            listing_stats['best_offer']['total'] += 1
            if is_buy: listing_stats['best_offer']['buy'] += 1
        else:
            listing_stats['no_best_offer']['total'] += 1
            if is_buy: listing_stats['no_best_offer']['buy'] += 1

        # UPC
        upc = data.get('UPC', data.get('upc', ''))
        if upc and upc not in ['N/A', 'Does not apply']:
            listing_stats['has_upc']['total'] += 1
            if is_buy: listing_stats['has_upc']['buy'] += 1
        else:
            listing_stats['no_upc']['total'] += 1
            if is_buy: listing_stats['no_upc']['buy'] += 1

        # Condition
        condition = (data.get('Condition', '') or 'Unknown').replace('+', ' ')
        condition_stats[condition[:25]]['total'] += 1
        if is_buy: condition_stats[condition[:25]]['buy'] += 1

        # Description
        desc = data.get('Description', '')
        if desc:
            desc_stats['has_description']['total'] += 1
            if is_buy: desc_stats['has_description']['buy'] += 1
        else:
            desc_stats['no_description']['total'] += 1
            if is_buy: desc_stats['no_description']['buy'] += 1

        cond_desc = data.get('ConditionDescription', '')
        if cond_desc:
            desc_stats['has_cond_desc']['total'] += 1
            if is_buy: desc_stats['has_cond_desc']['buy'] += 1
        else:
            desc_stats['no_cond_desc']['total'] += 1
            if is_buy: desc_stats['no_cond_desc']['buy'] += 1

        # Title patterns
        for pattern, pdata in title_patterns.items():
            if pattern in title_lower:
                pdata['total'] += 1
                if is_buy: pdata['buy'] += 1

        # Price ranges
        try:
            p = float(price)
            if p < 100:
                bucket = '<$100'
            elif p < 250:
                bucket = '$100-250'
            elif p < 500:
                bucket = '$250-500'
            elif p < 1000:
                bucket = '$500-1000'
            else:
                bucket = '$1000+'
            price_by_cat[cat][bucket]['total'] += 1
            if is_buy: price_by_cat[cat][bucket]['buy'] += 1
        except:
            pass

    except:
        pass

print('=== LISTING CHARACTERISTICS ===')
for lname, ldata in listing_stats.items():
    if ldata['total'] > 100:
        rate = (ldata['buy'] / ldata['total'] * 100) if ldata['total'] > 0 else 0
        print(f'{lname:<18} | BUY:{ldata["buy"]:>4} | Total:{ldata["total"]:>6} | Rate: {rate:>5.1f}%')

print()
print('=== DESCRIPTION PRESENCE ===')
for dname, ddata in desc_stats.items():
    rate = (ddata['buy'] / ddata['total'] * 100) if ddata['total'] > 0 else 0
    print(f'{dname:<18} | BUY:{ddata["buy"]:>4} | Total:{ddata["total"]:>6} | Rate: {rate:>5.1f}%')

print()
print('=== CONDITION BREAKDOWN (Top 12) ===')
for cond, cdata in sorted(condition_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:12]:
    rate = (cdata['buy'] / cdata['total'] * 100) if cdata['total'] > 0 else 0
    print(f'{cond:<25} | BUY:{cdata["buy"]:>4} | Total:{cdata["total"]:>6} | Rate: {rate:>5.1f}%')

print()
print('=== TITLE KEYWORDS ===')
for pattern, pdata in sorted(title_patterns.items(), key=lambda x: x[1]['buy'], reverse=True):
    if pdata['total'] > 50:
        rate = (pdata['buy'] / pdata['total'] * 100) if pdata['total'] > 0 else 0
        print(f'{pattern:<15} | BUY:{pdata["buy"]:>4} | Total:{pdata["total"]:>6} | Rate: {rate:>5.1f}%')

print()
print('=== PRICE RANGES BY CATEGORY ===')
for cat in ['gold', 'silver', 'tcg', 'watch']:
    if cat in price_by_cat:
        print(f'\n{cat.upper()}:')
        for bucket in ['<$100', '$100-250', '$250-500', '$500-1000', '$1000+']:
            bdata = price_by_cat[cat].get(bucket, {'buy': 0, 'total': 0})
            if bdata['total'] > 20:
                rate = (bdata['buy'] / bdata['total'] * 100) if bdata['total'] > 0 else 0
                print(f'  {bucket:<12} | BUY:{bdata["buy"]:>4} | Total:{bdata["total"]:>5} | Rate: {rate:>5.1f}%')

conn.close()
