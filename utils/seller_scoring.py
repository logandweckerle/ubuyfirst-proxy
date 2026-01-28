"""
Seller and Listing Scoring System

Based on analysis of 24,000+ listings, this module provides a scoring system
to identify high-value opportunities based on seller patterns, listing characteristics,
and item specifics.

Score Range: 0-100
- 80+: HIGH PRIORITY (estate sellers, casual individuals, great signals)
- 60-79: MEDIUM PRIORITY (decent signals, worth analyzing)
- 40-59: NORMAL (no strong signals either way)
- <40: LOW PRIORITY (professional sellers, poor signals)
"""

import re
import logging
from typing import Dict, Tuple, List

logger = logging.getLogger(__name__)


# ============================================================
# SCORING WEIGHTS (based on BUY rate analysis)
# ============================================================

# Seller name patterns
SELLER_PATTERNS = {
    # HIGH VALUE - these seller types have better BUY rates
    'thrift': {'pattern': r'thrift|goodwill|salvation|hospice|charity|resale', 'score': 15, 'reason': 'Thrift/charity seller'},
    'estate': {'pattern': r'estate|inherited|grandma|attic|downsizing|deceased', 'score': 12, 'reason': 'Estate seller'},
    'antique_store': {'pattern': r'antique|vintage.*(shop|store|dealer)', 'score': 8, 'reason': 'Antique dealer'},
    'liquidator': {'pattern': r'liquidat|storage|moving|closeout|auction', 'score': 10, 'reason': 'Liquidator'},

    # LOW VALUE - professional sellers who know prices
    'jewelry_pro': {'pattern': r'jewel|diamond|gem|precious|luxury|fine.?jewel', 'score': -15, 'reason': 'Jewelry professional'},
    'pawn_coin': {'pattern': r'pawn|coin|gold.?buyer|cash.?for|we.?buy', 'score': -10, 'reason': 'Pawn/coin dealer'},
    'dealer': {'pattern': r'dealer|wholesale|trade|broker', 'score': -8, 'reason': 'Professional dealer'},
}

# Username characteristics (updated with historical transaction data)
USERNAME_SCORING = {
    'has_numbers': {'check': lambda s: any(c.isdigit() for c in s), 'score': 3, 'reason': 'Casual username (has numbers)'},
    'short_name': {'check': lambda s: len(s) < 10, 'score': 2, 'reason': 'Short username'},
    'has_underscore': {'check': lambda s: '_' in s, 'score': 4, 'reason': 'Username with underscore'},
    'has_dash': {'check': lambda s: '-' in s, 'score': -5, 'reason': 'Username with dash (55% win rate - below baseline)'},
    'long_name': {'check': lambda s: len(s) > 20, 'score': 5, 'reason': 'Long username (67% win rate - above baseline)'},
    'has_vintage': {'check': lambda s: 'vintage' in s.lower(), 'score': 10, 'reason': 'Vintage in username (100% historical win rate)'},
}

# Feedback score buckets
FEEDBACK_SCORING = {
    (0, 50): {'score': 8, 'reason': 'Low feedback (casual seller)'},
    (51, 200): {'score': 5, 'reason': 'Low-medium feedback'},
    (201, 1000): {'score': 2, 'reason': 'Medium feedback'},
    (1001, 5000): {'score': 0, 'reason': 'Established seller'},
    (5001, 999999): {'score': -8, 'reason': 'High-volume seller'},
}

# Listing characteristic scoring
LISTING_SCORING = {
    'best_offer': {'value': True, 'score': 5, 'reason': 'Accepts best offer'},
    'has_upc': {'value': True, 'score': 8, 'reason': 'Has UPC (verifiable product)'},
    'no_description': {'value': True, 'score': 5, 'reason': 'No description (casual seller)'},
    'has_cond_desc': {'value': True, 'score': 3, 'reason': 'Has condition description'},
}

# Condition scoring (BUY rate analysis)
CONDITION_SCORING = {
    'like new': {'score': 15, 'reason': 'Like new condition (13.3% BUY rate)'},
    'like+new': {'score': 15, 'reason': 'Like new condition'},
    'good': {'score': 10, 'reason': 'Good condition (7.9% BUY rate)'},
    'unknown': {'score': 8, 'reason': 'Unknown condition (casual seller)'},
    'very good': {'score': 5, 'reason': 'Very good condition'},
    'new': {'score': 3, 'reason': 'New condition'},
    'used': {'score': 0, 'reason': 'Used condition'},
    'pre-owned excellent': {'score': 2, 'reason': 'Pre-owned excellent'},
    'pre-owned - good': {'score': -5, 'reason': 'Pre-owned - Good (low BUY rate)'},
    'pre-owned - excellent': {'score': -8, 'reason': 'Pre-owned - Excellent (very low BUY rate)'},
    'for parts': {'score': -20, 'reason': 'For parts/not working'},
    'for parts or not working': {'score': -20, 'reason': 'For parts/not working'},
}

# Title keyword scoring - based on BUY rate + actual purchases
TITLE_SCORING = {
    'wearable': {'score': 15, 'reason': 'Wearable (12.2% BUY rate)'},
    'charm bracelet': {'score': 12, 'reason': 'Charm bracelet (high value - $5500 purchase!)'},
    'scrap': {'score': 10, 'reason': 'Scrap (8.5% BUY rate, 17.7% of purchases)'},
    'tested': {'score': 8, 'reason': 'Tested (6.6% BUY rate)'},
    'grams': {'score': 8, 'reason': 'Weight stated in grams (26.5% of purchases)'},
    'dwt': {'score': 8, 'reason': 'Weight stated in DWT'},
    'gram': {'score': 8, 'reason': 'Weight stated (singular)'},
    'lot': {'score': 6, 'reason': 'Lot listing (21% of purchases)'},
    'charm': {'score': 5, 'reason': 'Charm (often high value)'},
    'not scrap': {'score': -10, 'reason': 'Not scrap (overpriced)'},
    'firm': {'score': -5, 'reason': 'Firm price (no negotiation)'},
    'no offers': {'score': -5, 'reason': 'No offers accepted'},
}

# ============================================================
# NEW DATA-DRIVEN SCORING (from 24K+ listing analysis)
# ============================================================

# Item Type scoring (eBay "Type" field) - based on BUY rate + actual purchase data
ITEM_TYPE_SCORING = {
    # SILVER GOLDMINE - flatware has incredible BUY rates
    'serving fork': {'score': 20, 'reason': 'Serving fork (22.7% BUY rate!)'},
    'flatware': {'score': 18, 'reason': 'Flatware (16.1% BUY rate)'},
    'ladle': {'score': 15, 'reason': 'Ladle (12.1% BUY rate)'},
    'serving spoon': {'score': 12, 'reason': 'Serving spoon (6.5% BUY rate)'},
    'spoon': {'score': 10, 'reason': 'Spoon (7.9% BUY rate)'},
    'knife': {'score': 10, 'reason': 'Knife (7.9% BUY rate)'},
    'fork': {'score': 8, 'reason': 'Fork'},
    'mixed lot': {'score': 8, 'reason': 'Mixed lot (5.7% BUY rate)'},

    # GOLD/JEWELRY - validated by actual purchase data
    'bracelet': {'score': 10, 'reason': 'Bracelet (avg $816 purchase - best type!)'},
    'chain': {'score': 8, 'reason': 'Chain (avg $555 purchase)'},
    'solid gold': {'score': 12, 'reason': 'Solid gold type (9.4% BUY rate)'},
    'brooch': {'score': 10, 'reason': 'Brooch (8.3% BUY rate)'},
    'pendant': {'score': 6, 'reason': 'Pendant (4.7% BUY rate)'},
    'pocket watch': {'score': 15, 'reason': 'Pocket watch (11.8% BUY rate)'},
    'necklace': {'score': 4, 'reason': 'Necklace (avg $353 purchase)'},
    'ring': {'score': 0, 'reason': 'Ring (neutral - 110 purchased at avg $404)'},

    # STILL AVOID - engagement/wedding rings specifically
    'engagement ring': {'score': -15, 'reason': 'Engagement ring (0% BUY rate!)'},
    'wedding': {'score': -8, 'reason': 'Wedding jewelry (low BUY rate)'},
    'pin': {'score': -5, 'reason': 'Pin (low BUY rate)'},
    'earrings': {'score': -2, 'reason': 'Earrings (1.9% BUY rate)'},
}

# Day of Week scoring - Tuesday/Monday/Sunday are gold!
DAY_SCORING = {
    'Tuesday': {'score': 10, 'reason': 'Tuesday (6.8% BUY rate - best day!)'},
    'Monday': {'score': 8, 'reason': 'Monday (5.7% BUY rate)'},
    'Sunday': {'score': 6, 'reason': 'Sunday (5.4% BUY rate)'},
    'Wednesday': {'score': 3, 'reason': 'Wednesday (4.6% BUY rate)'},
    'Thursday': {'score': 0, 'reason': 'Thursday (2.6% BUY rate)'},
    'Saturday': {'score': -3, 'reason': 'Saturday (2.0% BUY rate)'},
    'Friday': {'score': -8, 'reason': 'Friday (1.8% BUY rate - pros dominate)'},
}

# Photo count scoring - 2-3 photos = casual seller
PHOTO_COUNT_SCORING = {
    2: {'score': 10, 'reason': '2 photos (6.1% BUY rate - casual seller)'},
    3: {'score': 6, 'reason': '3 photos (4.5% BUY rate)'},
    1: {'score': 0, 'reason': '1 photo'},
    4: {'score': 3, 'reason': '4 photos'},
    5: {'score': 0, 'reason': '5 photos'},
    6: {'score': -2, 'reason': '6 photos'},
    0: {'score': -5, 'reason': '0 photos (1.4% BUY rate - suspicious)'},
    'many': {'score': -5, 'reason': '9+ photos (2.7% BUY rate - pro seller)'},
}

# Brand scoring - updated with historical transaction data (287 transactions)
BRAND_SCORING = {
    # HIGH VALUE - brands that correlate with good deals
    'omega': {'score': 15, 'reason': 'Omega (19% BUY rate!)'},
    'trifari': {'score': 15, 'reason': 'Trifari (78% historical win rate, 451% avg ROI)'},
    'fashion jewelry': {'score': 10, 'reason': 'Fashion jewelry (11.8% BUY rate)'},
    'rolex': {'score': 8, 'reason': 'Rolex (9.4% BUY rate)'},
    'seiko': {'score': 5, 'reason': 'Seiko (4.8% BUY rate)'},
    'handmade': {'score': 3, 'reason': 'Handmade (casual seller)'},
    'unbranded': {'score': 5, 'reason': 'Unbranded (casual seller)'},

    # HISTORICAL WINNERS - Updated based on real transaction data
    'taxco': {'score': 10, 'reason': 'Taxco (86-100% historical win rate, 404% ROI)'},
    'native american': {'score': 10, 'reason': 'Native American (80%+ historical win rate)'},
    'georg jensen': {'score': 12, 'reason': 'Georg Jensen (544% historical avg ROI)'},
    'antonio pineda': {'score': 12, 'reason': 'Antonio Pineda (premium Mexican silver)'},

    # AVOID - premium silver brands where sellers know value
    'gorham': {'score': -15, 'reason': 'Gorham (0% BUY rate - premium brand)'},
    'towle': {'score': -15, 'reason': 'Towle (0% BUY rate - premium brand)'},
    'reed & barton': {'score': -12, 'reason': 'Reed & Barton (premium brand)'},
    'wallace': {'score': -10, 'reason': 'Wallace (premium brand)'},
    'international silver': {'score': -8, 'reason': 'International Silver (known brand)'},
}

# Title length scoring - short titles = casual sellers
TITLE_LENGTH_SCORING = {
    'short': {'max_len': 30, 'score': 5, 'reason': 'Short title (4.4% BUY rate - casual)'},
    'medium': {'max_len': 60, 'score': 3, 'reason': 'Medium title (3.9% BUY rate)'},
    'long': {'max_len': 80, 'score': 0, 'reason': 'Long title'},
    'very_long': {'max_len': 999, 'score': -2, 'reason': 'Very long title (pro seller)'},
}

# Vintage flag - NEUTRAL (27% of actual purchases are vintage!)
# The BUY rate data showed 2.2% vs 3.7%, but purchase history shows we buy plenty of vintage
VINTAGE_SCORING = {
    True: {'score': 0, 'reason': 'Vintage (neutral - 27% of purchases)'},
    False: {'score': 0, 'reason': 'Not vintage'},
}

# ============================================================
# HISTORICAL SELLER DATA (from 287 real transactions)
# ============================================================

# Trusted sellers - 100% win rate with 2+ purchases
HISTORICAL_TRUSTED_SELLERS = {
    'seconhandtreasures2u',  # 2tx, $892 profit
    'gosps',                 # 2tx, $336 profit
}

# Problematic sellers - 50%+ loss rate with 2+ purchases
HISTORICAL_PROBLEMATIC_SELLERS = {
    'itagirl76': {'reason': '100% loss rate on sterling lots', 'loss_rate': 100},
    'jacal-8745': {'reason': '50% loss rate on gold rings', 'loss_rate': 50},
    'lisaannmary': {'reason': '50% loss rate on sterling lots', 'loss_rate': 50},
}

# Seller patterns that correlate with losses (from historical data)
HISTORICAL_LOSS_PATTERNS = {
    # Sterling lot sellers with high loss rates
    'lot_seller_pattern': {
        'title_keywords': ['sterling lot', 'silver lot', '925 lot'],
        'seller_indicators': ['lot', 'bulk', 'wholesale'],
        'reason': 'Sterling lot sellers have 25% win rate historically',
        'score_modifier': -10,
    },
}


def score_seller(data: Dict) -> Tuple[int, List[str]]:
    """
    Score a seller based on their profile and listing characteristics.

    Returns: (score 0-100, list of reasons)
    """
    score = 50  # Start at neutral
    reasons = []

    seller_name = (data.get('SellerName', '') or data.get('StoreName', '') or '').lower()
    feedback = data.get('FeedbackScore', data.get('feedbackScore', ''))

    # === HISTORICAL SELLER CHECKS (highest priority) ===
    if seller_name in HISTORICAL_TRUSTED_SELLERS:
        score += 25
        reasons.append(f"HISTORICAL TRUSTED SELLER (+25)")
        logger.info(f"[SELLER] Historical trusted seller: {seller_name}")

    if seller_name in HISTORICAL_PROBLEMATIC_SELLERS:
        prob_data = HISTORICAL_PROBLEMATIC_SELLERS[seller_name]
        penalty = -20 if prob_data['loss_rate'] >= 75 else -10
        score += penalty
        reasons.append(f"HISTORICAL PROBLEMATIC SELLER: {prob_data['reason']} ({penalty})")
        logger.info(f"[SELLER] Historical problematic seller: {seller_name} - {prob_data['reason']}")
    condition = (data.get('Condition', '') or '').lower().replace('+', ' ')
    title = (data.get('Title', '') or '').lower()
    description = data.get('Description', '')
    cond_desc = data.get('ConditionDescription', '')
    best_offer = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']
    upc = data.get('UPC', data.get('upc', ''))
    has_upc = bool(upc and upc not in ['N/A', 'Does not apply', ''])

    # === SELLER NAME PATTERNS ===
    for pattern_name, pattern_data in SELLER_PATTERNS.items():
        if re.search(pattern_data['pattern'], seller_name, re.I):
            score += pattern_data['score']
            reasons.append(f"{pattern_data['reason']} ({pattern_data['score']:+d})")

    # === USERNAME CHARACTERISTICS ===
    if seller_name:
        for char_name, char_data in USERNAME_SCORING.items():
            if char_data['check'](seller_name):
                score += char_data['score']
                if char_data['score'] != 0:
                    reasons.append(f"{char_data['reason']} ({char_data['score']:+d})")

    # === FEEDBACK SCORE ===
    try:
        fb = int(float(str(feedback).replace(',', '')))
        for (low, high), fb_data in FEEDBACK_SCORING.items():
            if low <= fb <= high:
                score += fb_data['score']
                if fb_data['score'] != 0:
                    reasons.append(f"{fb_data['reason']} ({fb_data['score']:+d})")
                break
    except:
        pass

    # === LISTING CHARACTERISTICS ===
    if best_offer:
        score += LISTING_SCORING['best_offer']['score']
        reasons.append(f"{LISTING_SCORING['best_offer']['reason']} (+5)")

    if has_upc:
        score += LISTING_SCORING['has_upc']['score']
        reasons.append(f"{LISTING_SCORING['has_upc']['reason']} (+8)")

    if not description:
        score += LISTING_SCORING['no_description']['score']
        reasons.append(f"{LISTING_SCORING['no_description']['reason']} (+5)")

    if cond_desc:
        score += LISTING_SCORING['has_cond_desc']['score']
        reasons.append(f"{LISTING_SCORING['has_cond_desc']['reason']} (+3)")

    # === CONDITION ===
    for cond_key, cond_data in CONDITION_SCORING.items():
        if cond_key in condition:
            score += cond_data['score']
            if cond_data['score'] != 0:
                reasons.append(f"{cond_data['reason']} ({cond_data['score']:+d})")
            break

    # === TITLE KEYWORDS ===
    for keyword, kw_data in TITLE_SCORING.items():
        if keyword in title:
            score += kw_data['score']
            if kw_data['score'] != 0:
                reasons.append(f"{kw_data['reason']} ({kw_data['score']:+d})")

    # === NEW DATA-DRIVEN SCORING ===

    # --- ITEM TYPE (eBay Type field) ---
    item_type = (data.get('Type', '') or '').lower().replace('+', ' ')
    for type_key, type_data in ITEM_TYPE_SCORING.items():
        if type_key in item_type:
            score += type_data['score']
            if type_data['score'] != 0:
                reasons.append(f"{type_data['reason']} ({type_data['score']:+d})")
            break

    # --- BRAND ---
    brand = (data.get('Brand', '') or '').lower().replace('+', ' ')
    for brand_key, brand_data in BRAND_SCORING.items():
        if brand_key in brand:
            score += brand_data['score']
            if brand_data['score'] != 0:
                reasons.append(f"{brand_data['reason']} ({brand_data['score']:+d})")
            break

    # --- PHOTO COUNT ---
    images = data.get('images', [])
    if isinstance(images, list):
        photo_count = len(images)
        if photo_count >= 9:
            pd = PHOTO_COUNT_SCORING.get('many', {'score': 0, 'reason': ''})
        else:
            pd = PHOTO_COUNT_SCORING.get(photo_count, {'score': 0, 'reason': ''})
        if pd['score'] != 0:
            score += pd['score']
            reasons.append(f"{pd['reason']} ({pd['score']:+d})")

    # --- TITLE LENGTH ---
    title_len = len(title.replace('+', ' '))
    for len_key, len_data in TITLE_LENGTH_SCORING.items():
        if title_len <= len_data['max_len']:
            if len_data['score'] != 0:
                score += len_data['score']
                reasons.append(f"{len_data['reason']} ({len_data['score']:+d})")
            break

    # --- VINTAGE FLAG ---
    vintage = data.get('Vintage', '')
    is_vintage = vintage and str(vintage).lower() in ['yes', 'true', '1']
    vd = VINTAGE_SCORING.get(is_vintage, {'score': 0, 'reason': ''})
    if vd['score'] != 0:
        score += vd['score']
        reasons.append(f"{vd['reason']} ({vd['score']:+d})")

    # --- DAY OF WEEK (if timestamp provided) ---
    timestamp = data.get('timestamp', data.get('PostedTime', ''))
    if timestamp:
        try:
            from datetime import datetime
            if isinstance(timestamp, str):
                # Parse ISO format
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00').split('+')[0])
                day_name = dt.strftime('%A')
                dd = DAY_SCORING.get(day_name, {'score': 0, 'reason': ''})
                if dd['score'] != 0:
                    score += dd['score']
                    reasons.append(f"{dd['reason']} ({dd['score']:+d})")
        except:
            pass

    # Clamp score to 0-100
    score = max(0, min(100, score))

    return score, reasons


def get_priority_level(score: int) -> str:
    """Get priority level from score."""
    if score >= 80:
        return "HIGH"
    elif score >= 60:
        return "MEDIUM"
    elif score >= 40:
        return "NORMAL"
    else:
        return "LOW"


def format_score_summary(score: int, reasons: List[str]) -> str:
    """Format score and reasons for display."""
    priority = get_priority_level(score)
    summary = f"Seller Score: {score}/100 ({priority} priority)"
    if reasons:
        summary += "\n  " + "\n  ".join(reasons[:5])  # Top 5 reasons
    return summary


# Test function
if __name__ == "__main__":
    # Test cases
    test_cases = [
        {
            'SellerName': 'grandmas_estate_sales',
            'FeedbackScore': '45',
            'Condition': 'Used',
            'Title': 'Scrap Gold 14K 5 grams tested',
            'Description': '',
            'BestOffer': 'true',
        },
        {
            'SellerName': 'fine_jewelry_unlimited',
            'FeedbackScore': '15000',
            'Condition': 'Pre-owned - Excellent',
            'Title': 'Beautiful 14K Gold Diamond Ring',
            'Description': 'Long professional description here...',
            'BestOffer': 'false',
        },
        {
            'SellerName': 'bob_123',
            'FeedbackScore': '23',
            'Condition': 'Like new',
            'Title': 'Sterling silver lot wearable',
            'Description': '',
            'BestOffer': 'true',
        },
    ]

    for i, test in enumerate(test_cases):
        score, reasons = score_seller(test)
        print(f"\nTest {i+1}: {test['SellerName']}")
        print(format_score_summary(score, reasons))
