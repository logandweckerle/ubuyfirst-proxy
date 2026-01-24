"""
PriceCharting Validation Module

Provides validation functions for TCG, LEGO, and video game listings
using PriceCharting and Bricklink data.

Now includes graded card (PSA/BGS/CGC) support via lookup_graded_card.

Extracted from main.py for better organization.
"""

import re
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Import graded card lookup function
try:
    from pricecharting_db import lookup_graded_card, extract_grade_info
    GRADED_LOOKUP_AVAILABLE = True
except ImportError:
    GRADED_LOOKUP_AVAILABLE = False
    logger.warning("[PC-VAL] Graded card lookup not available")

# Import normalize function from utils.validation
try:
    from utils.validation import normalize_tcg_lego_keys as utils_normalize_tcg_lego_keys
except ImportError:
    # Fallback: define inline if utils.validation not available
    def utils_normalize_tcg_lego_keys(result: dict, category: str) -> dict:
        """Normalize keys for TCG/LEGO results (fallback implementation)"""
        # Map of AI keys to expected keys
        key_map = {
            'setNumber': 'SetNumber',
            'setName': 'SetName',
            'marketPrice': 'marketprice',
            'maxbuy': 'maxBuy',
            'margin': 'Margin',
            'profit': 'Profit',
            'recommendation': 'Recommendation',
            'qualify': 'Qualify',
        }
        normalized = {}
        for key, value in result.items():
            new_key = key_map.get(key.lower(), key) if key.lower() in [k.lower() for k in key_map] else key
            normalized[new_key] = value
        return normalized

# Module configuration (set by configure_pricecharting_validation)
_config = {
    'pc_lookup': None,
    'bricklink_lookup': None,
    'pricecharting_available': False,
    'bricklink_available': False,
    'category_thresholds': {
        'lego': 0.70,
        'tcg': 0.70,
        'videogames': 0.65,
        'default': 0.65,
    },
}


def configure_pricecharting_validation(
    pc_lookup=None,
    bricklink_lookup=None,
    pricecharting_available: bool = False,
    bricklink_available: bool = False,
    category_thresholds: dict = None,
):
    """Configure the pricecharting validation module with dependencies."""
    if pc_lookup:
        _config['pc_lookup'] = pc_lookup
    if bricklink_lookup:
        _config['bricklink_lookup'] = bricklink_lookup
    _config['pricecharting_available'] = pricecharting_available
    _config['bricklink_available'] = bricklink_available
    if category_thresholds:
        _config['category_thresholds'].update(category_thresholds)


def get_category_threshold(category: str) -> float:
    """Get the buy threshold for a category."""
    return _config['category_thresholds'].get(category, _config['category_thresholds']['default'])


# Helper to access config values (used by functions below)
def _get_pc_lookup():
    return _config['pc_lookup']

def _get_bricklink_lookup():
    return _config['bricklink_lookup']

# Compatibility - these will be replaced by the function references from config
PRICECHARTING_AVAILABLE = property(lambda self: _config['pricecharting_available'])
BRICKLINK_AVAILABLE = property(lambda self: _config['bricklink_available'])

def get_pricecharting_context(title: str, total_price: float, category: str, upc: str = None, quantity: int = 1, condition: str = None) -> tuple:
    import re  # Explicit import to avoid "cannot access local variable 're'" error

    """

    Get PriceCharting data for TCG/LEGO/Video Games listings

    Tries UPC first (most accurate), then falls back to title search.

    Handles multi-quantity listings by calculating per-item price.

    Handles multi-set LEGO lots by looking up each set and summing values.

    Applies language discounts for Korean/Japanese products.

    Uses condition to select appropriate price tier (new/cib/loose).

    NEW: Handles graded cards (PSA/BGS/CGC) with specialized lookup.

    Returns: (pc_result dict, context_string for prompt)

    """

    if not _config['pricecharting_available']:

        return None, ""

    if category not in ["tcg", "lego", "videogames"]:

        return None, ""

    title_lower = title.lower()

    # === GRADED CARD DETECTION (PSA/BGS/CGC) ===
    # Check if this is a graded card and use specialized lookup
    if category == "tcg" and GRADED_LOOKUP_AVAILABLE:
        grade_info = extract_grade_info(title)
        if grade_info.get('is_graded'):
            logger.info(f"[PC-GRADED] Detected graded card: {grade_info['grader']} {grade_info['grade']}")

            graded_result = lookup_graded_card(title, total_price)

            if graded_result.get('found') and graded_result.get('market_price'):
                market_price = graded_result['market_price']
                buy_target = graded_result['buy_target']
                margin = graded_result['margin']
                confidence = graded_result.get('confidence', 'Medium')

                # Build context for AI prompt
                context = f"""
=== PRICECHARTING GRADED CARD DATA ===
Grader: {graded_result.get('grader')} | Grade: {graded_result.get('grade')}
Card: {graded_result.get('card_name', 'Unknown')}
Set: {graded_result.get('set_name', 'Unknown')}

Raw Card Value: ${graded_result.get('raw_price', 0):.2f}
Grade Multiplier: {graded_result.get('multiplier', 1)}x
Graded Value: ${market_price:.2f}

Buy Target (70%): ${buy_target:.2f}
Listing Price: ${total_price:.2f}
Margin: ${margin:.2f}

Match Confidence: {confidence}
Source: {graded_result.get('source', 'PriceCharting')}
=== END GRADED CARD DATA ===

IMPORTANT: Use the graded value above for pricing.
If margin is NEGATIVE, recommendation MUST be PASS.
High-value graded cards (>$500) should be RESEARCH for authenticity verification.
"""

                logger.info(f"[PC-GRADED] Found: {graded_result.get('card_name')} @ ${market_price:.0f} (margin ${margin:.0f})")

                # Format result to match expected structure
                pc_result = {
                    'found': True,
                    'product_name': f"{graded_result.get('grader')} {graded_result.get('grade')} {graded_result.get('card_name', 'Card')}",
                    'product_id': graded_result.get('product_id'),
                    'console_name': graded_result.get('set_name', 'Graded Card'),
                    'category': 'tcg',
                    'market_price': market_price,
                    'buy_target': buy_target,
                    'margin': margin,
                    'confidence': confidence,
                    'source': graded_result.get('source', 'pricecharting_graded'),
                    'is_graded': True,
                    'grader': graded_result.get('grader'),
                    'grade': graded_result.get('grade'),
                    'raw_price': graded_result.get('raw_price'),
                    'multiplier': graded_result.get('multiplier'),
                }

                return pc_result, context

            else:
                # Graded card detected but lookup failed - return context noting this
                logger.warning(f"[PC-GRADED] Lookup failed: {graded_result.get('error', 'Unknown error')}")
                context = f"""
=== GRADED CARD DETECTED (NO PRICE DATA) ===
Grader: {grade_info['grader']} | Grade: {grade_info['grade']}
ERROR: {graded_result.get('error', 'Card not found in database')}

Use your knowledge to estimate raw card value, then apply grade multiplier:
- PSA 10: ~5x raw value
- PSA 9: ~2x raw value
- BGS 9.5: ~3x raw value
- CGC 9.5: ~2.5x raw value

Recommend RESEARCH for high-value graded cards without verified pricing.
=== END ===
"""
                return None, context

    # === MULTI-SET LEGO LOT DETECTION ===

    # Look for multiple set numbers in the title (e.g., "40803 and 40804" or "75192, 75252")

    if category == "lego":

        # Find all 4-6 digit numbers that look like LEGO set numbers
        # Include 910xxx Bricklink Designer Program sets

        set_numbers = re.findall(r'\b((?:4|5|6|7|8)\d{4}|91\d{4})\b', title)

        # Remove duplicates while preserving order

        set_numbers = list(dict.fromkeys(set_numbers))

        if len(set_numbers) >= 2:

            logger.info(f"[PC] MULTI-SET LOT DETECTED: {set_numbers}")

            # Look up each set

            total_market = 0

            set_details = []

            all_found = True

            for set_num in set_numbers:

                # Try Bricklink first for ALL sets, then fall back to PriceCharting
                set_result = None
                if _config['bricklink_available']:
                    logger.info(f"[BRICKLINK] Looking up set {set_num}")
                    bl_result = _config['bricklink_lookup'](set_num, listing_price=0, condition="new")
                    if bl_result and bl_result.get('found') and bl_result.get('market_price', 0) > 0:
                        set_result = {
                            'found': True,
                            'product_name': bl_result.get('name', f'Set {set_num}'),
                            'market_price': bl_result.get('market_price', 0),
                            'buy_target': bl_result.get('buy_target', 0),
                            'source': 'bricklink'
                        }

                # Fall back to PriceCharting if Bricklink didn't find it
                if not set_result:
                    set_result = _config['pc_lookup'](f"LEGO {set_num}", category="lego", listing_price=0)

                if set_result and set_result.get('found') and set_result.get('market_price', 0) > 0:

                    market = set_result.get('market_price', 0)

                    name = set_result.get('product_name', f'Set {set_num}')

                    total_market += market

                    set_details.append({

                        'set_number': set_num,

                        'name': name,

                        'market_price': market

                    })

                    logger.info(f"[PC]   Set {set_num}: {name} = ${market:.0f}")

                else:

                    logger.warning(f"[PC]   Set {set_num}: NOT FOUND")

                    all_found = False

            if set_details:

                # Calculate combined values using category threshold
                threshold = get_category_threshold('lego')
                total_buy_target = total_market * threshold

                total_margin = total_buy_target - total_price

                # Build combined result

                combined_result = {

                    'found': True,

                    'product_name': f"LOT: {', '.join([d['name'][:30] for d in set_details])}",

                    'market_price': total_market,

                    'buy_target': total_buy_target,

                    'margin': total_margin,

                    'confidence': 'High' if all_found else 'Medium',

                    'multi_set': True,

                    'set_count': len(set_details),

                    'set_details': set_details,

                    'all_sets_found': all_found

                }

                # Build context string

                set_breakdown = "\n".join([f"  - {d['set_number']}: {d['name']} = ${d['market_price']:.0f}" for d in set_details])

                if not all_found:

                    set_breakdown += f"\n  - {len(set_numbers) - len(set_details)} set(s) NOT FOUND in database"

                context = f"""

=== PRICECHARTING DATA (MULTI-SET LOT) ===

Sets Found: {len(set_details)}/{len(set_numbers)}

{set_breakdown}

COMBINED VALUES:

Total Market Value: ${total_market:.0f}

Max Buy ({int(threshold*100)}%): ${total_buy_target:.0f}

Listing Price: ${total_price:.0f}

Combined Margin: ${total_margin:+.0f}

{"NOTE: Not all sets found - be conservative with pricing" if not all_found else "All sets verified in database"}

=== END PRICECHARTING DATA ===

"""

                logger.info(f"[PC] MULTI-SET TOTAL: ${total_market:.0f} market, ${total_buy_target:.0f} max buy, ${total_margin:+.0f} margin")

                return combined_result, context

            else:

                # No sets found

                logger.warning(f"[PC] Multi-set lot but NO sets found in database")

                return None, f"""

=== PRICECHARTING DATA ===

MULTI-SET LOT DETECTED: {set_numbers}

WARNING: None of these sets found in database.

Manual pricing research required.

=== END ===

"""

    # Handle quantity - calculate per-item price

    quantity = max(1, quantity)  # Ensure at least 1

    per_item_price = total_price / quantity

    if quantity > 1:

        logger.info(f"[PC] Multi-quantity listing: {quantity}x @ ${total_price:.2f} total = ${per_item_price:.2f} each")

    # === LANGUAGE DETECTION FOR TCG ===

    title_lower = title.lower()

    detected_language = "english"  # Default

    language_discount = 1.0  # No discount for English

    if category == "tcg":

        # === UNSUPPORTED TCG BRANDS - Skip PriceCharting lookup ===

        # These brands are not in our pricing database

        unsupported_tcg = ['marvel', 'upper deck', 'dc', 'dragon ball', 'dbz', 'naruto', 'my hero academia', 

                          'weiss schwarz', 'cardfight vanguard', 'flesh and blood', 'metazoo', 'star wars',

                          'digimon', 'union arena', 'grand archive', 'sorcery']

        if any(brand in title_lower for brand in unsupported_tcg):

            detected_brand = next((b for b in unsupported_tcg if b in title_lower), 'unknown')

            logger.info(f"[PC] UNSUPPORTED TCG: {detected_brand.upper()} - skipping PriceCharting lookup")

            return None, f"""

=== UNSUPPORTED TCG BRAND ===

Detected: {detected_brand.upper()}

This brand is NOT in our pricing database.

You must manually research pricing on eBay sold listings.

=== END ===

"""

        if any(word in title_lower for word in ['korean', 'korea', 'kor ', ' kor']):

            detected_language = "korean"

            language_discount = 0.25  # Korean = 25% of English value (very aggressive - Korean is cheap!)

            logger.info(f"[PC] KOREAN detected - applying 75% discount (Korean products sell for ~25% of English)")

        elif any(word in title_lower for word in ['japanese', 'japan', 'jpn', ' jp ', 'japanese version']):

            detected_language = "japanese"

            # Japanese TCG booster boxes/ETBs are worth MUCH less than English
        # Also detect Japanese-exclusive products (using product codes, NOT set names)
        # IMPORTANT: Most set names like "Phantasmal Flames", "Crimson Haze" etc have English releases
        # Only use Japanese-specific product codes and truly exclusive product names
        elif any(jp_code in title_lower for jp_code in [
            # Japanese product codes (these ARE Japan-exclusive)
            'sv5k', 'sv5m', 'sv4k', 'sv4m', 'sv3s', 'sv2a', 'sv2d', 'sv1s', 'sv1v',
            's12', 's11', 's10', 's9', 's8', 's7', 's6', 's5', 's4', 's3', 's2', 's1',
            # True Japan-exclusive products
            'vstar universe', 'shiny star v', 'vmax climax', 'eevee heroes',
            'shiny treasure ex', 'clay burst jp', 'snow hazard jp',
        ]):
            detected_language = "japanese"
            logger.info(f"[PC] JAPANESE-EXCLUSIVE SET NAME detected in title")

            # Japanese TCG booster boxes/ETBs are worth MUCH less than English
            # Booster boxes: ~25-35% of English price
            # ETBs: ~30-40% of English price
            # Singles: ~40-50% of English price
            is_sealed_product = any(kw in title_lower for kw in ['booster box', 'booster case', 'etb', 'elite trainer', 'premium collection', 'sealed'])
            if is_sealed_product:
                language_discount = 0.30  # Japanese sealed = 30% of English (more aggressive)
                logger.info(f"[PC] JAPANESE SEALED PRODUCT detected - applying 70% discount (Japanese sealed sells for ~30% of English)")
            else:
                language_discount = 0.45  # Japanese singles = 45% of English value
                logger.info(f"[PC] JAPANESE detected - applying 55% discount")

        elif any(word in title_lower for word in ['chinese', 'china', 'simplified', 'traditional']):

            detected_language = "chinese"

            language_discount = 0.20  # Chinese = 20% of English value (lowest demand)

            logger.info(f"[PC] CHINESE detected - applying 80% discount")

    try:

        # Map our category names to PC database categories

        pc_category = category

        if category == "tcg":

            # Will auto-detect pokemon/mtg/yugioh from title

            pc_category = None  

        # === FOR KOREAN/JAPANESE: Try to match regional set names first ===

        search_title = title

        if category == "tcg" and detected_language in ["korean", "japanese"]:

            # Map English set names to Japanese/Korean equivalents

            set_name_map = {

                'evolving skies': 'eevee heroes',

                'fusion strike': 'fusion arts',

                'brilliant stars': 'star birth',

                'lost origin': 'lost abyss',

                'silver tempest': 'paradigm trigger',

                'crown zenith': 'vstar universe',

                'obsidian flames': 'ruler of the black flame',

                'paldea evolved': 'snow hazard clay burst',

                '151': '151',  # Same name

                'paradox rift': 'ancient roar future flash',

                'temporal forces': 'wild force cyber judge',

            }

            title_lower = title.lower()

            for eng_name, jp_name in set_name_map.items():

                if eng_name in title_lower and jp_name not in title_lower:

                    # Replace English name with Japanese name for better matching

                    search_title = title_lower.replace(eng_name, jp_name)

                    logger.info(f"[PC] Remapped set name: '{eng_name}' ƒÆ’‚[PASS] ¢[PASS] ¢'{jp_name}' for {detected_language} search")

                    break

        # Use per-item price for margin calculation
        # Check for Bricklink Designer Program sets (910xxx) first
        pc_result = None
        bricklink_used = False

        if category == "lego" and _config['bricklink_available']:
            # Extract set number from title - try ALL set numbers, not just Designer Program
            # Common LEGO set number patterns: 4-6 digits
            set_match = re.search(r'\b(\d{4,6})\b', title)
            if set_match:
                set_num = set_match.group(1)
                # Validate it looks like a real LEGO set number (not a year like 2023)
                is_year = 1990 <= int(set_num) <= 2030
                is_valid_set = len(set_num) >= 4 and not is_year

                if is_valid_set:
                    logger.info(f"[BRICKLINK] Attempting lookup for set #{set_num}")
                    bl_result = _config['bricklink_lookup'](set_num, listing_price=per_item_price, condition=condition or "new")
                    if bl_result and bl_result.get('found') and bl_result.get('market_price', 0) > 0:
                        pc_result = {
                            'found': True,
                            'product_name': f"{bl_result.get('name', '')} #{set_num}",
                            'product_id': set_num,
                            'console_name': 'Bricklink',
                            'category': 'lego',
                            'market_price': bl_result.get('market_price', 0),
                            'buy_target': bl_result.get('buy_target', 0),
                            'margin': bl_result.get('profit', 0),
                            'confidence': bl_result.get('confidence', 'Medium'),
                            'source': 'bricklink',
                            'new_price': bl_result.get('market_price', 0),
                            'cib_price': bl_result.get('market_price', 0) * 0.85,
                            'loose_price': bl_result.get('market_price', 0) * 0.70,
                        }
                        bricklink_used = True
                        logger.info(f"[BRICKLINK] Found: {pc_result['product_name']} @ ${pc_result['market_price']:.2f}")
                    else:
                        logger.info(f"[BRICKLINK] No data for #{set_num}, falling back to PriceCharting")

        # Fall back to PriceCharting if Bricklink didn't find it
        if not pc_result:
            pc_result = _config['pc_lookup'](search_title, category=pc_category, listing_price=per_item_price, upc=upc)

        # === CONDITION-BASED PRICING (Critical for Video Games!) ===

        # PriceCharting returns: new_price, cib_price, loose_price

        # We must use the correct price based on the eBay listing condition

        if pc_result and pc_result.get('found'):

            condition_lower = str(condition or '').lower()

            new_price = pc_result.get('new_price', 0) or 0

            cib_price = pc_result.get('cib_price', 0) or 0

            loose_price = pc_result.get('loose_price', 0) or 0

            original_market = pc_result.get('market_price', 0)

            # Determine which price tier to use based on condition AND title
            # Title keywords often override eBay's condition field (more accurate)

            # eBay condition values: New, Like New, Very Good, Good, Acceptable, For Parts

            condition_price = None

            condition_tier = None

            # === TITLE-BASED CONDITION DETECTION (Priority - more reliable than eBay field) ===
            # Check title first for explicit condition keywords
            title_condition = None

            # NEW/SEALED indicators in title (highest priority)
            new_keywords = ['factory sealed', 'brand new sealed', 'new sealed', 'still sealed',
                           'shrink wrapped', 'shrinkwrapped', 'unopened', 'mint sealed', 'bnib',
                           'new in box', 'nib', 'nisb', 'new in shrink']
            if any(kw in title_lower for kw in new_keywords):
                title_condition = 'New'
                logger.info(f"[PC] TITLE indicates NEW/SEALED condition")

            # CIB/COMPLETE indicators in title
            elif any(kw in title_lower for kw in ['complete in box', 'cib', 'complete w/', 'complete with',
                                                   'w/ box', 'with box', 'w/ manual', 'with manual',
                                                   'box and manual', 'complete set', 'in box']):
                title_condition = 'CIB'
                logger.info(f"[PC] TITLE indicates CIB/COMPLETE condition")

            # LOOSE indicators in title
            elif any(kw in title_lower for kw in ['loose', 'cart only', 'cartridge only', 'disc only',
                                                   'game only', 'no box', 'no manual', 'no case',
                                                   'disk only', 'no instructions']):
                title_condition = 'Loose'
                logger.info(f"[PC] TITLE indicates LOOSE condition")

            # Use title condition if detected, otherwise fall back to eBay condition field
            effective_condition = title_condition or condition_lower

            if title_condition:
                logger.info(f"[PC] Using TITLE-based condition: {title_condition} (eBay field was: '{condition}')")

            if any(term in str(effective_condition).lower() for term in ['new', 'sealed', 'factory sealed', 'brand new', 'unopened']):

                # New/Sealed items - use new price

                condition_price = new_price if new_price > 0 else cib_price

                condition_tier = 'New'

            elif any(term in str(effective_condition).lower() for term in ['like new', 'complete', 'cib', 'mint', 'excellent']):

                # Complete/CIB items - use CIB price

                condition_price = cib_price if cib_price > 0 else loose_price

                condition_tier = 'CIB'

            elif any(term in str(effective_condition).lower() for term in ['very good', 'good', 'acceptable', 'used', 'loose', 'cart', 'disc only']):

                # Used/Loose items - use loose price

                condition_price = loose_price if loose_price > 0 else cib_price

                condition_tier = 'Loose'

            else:

                # Unknown condition - use the most conservative (lowest) available price

                if loose_price > 0:

                    condition_price = loose_price

                    condition_tier = 'Loose (default)'

                elif cib_price > 0:

                    condition_price = cib_price

                    condition_tier = 'CIB (default)'

                else:

                    condition_price = new_price

                    condition_tier = 'New (default)'

            # Only update if we determined a condition-appropriate price

            if condition_price and condition_price > 0:

                old_market = pc_result.get('market_price', 0)
                cat_threshold = get_category_threshold(category)

                pc_result['market_price'] = condition_price

                pc_result['buy_target'] = condition_price * cat_threshold

                pc_result['margin'] = pc_result['buy_target'] - per_item_price

                pc_result['condition_tier'] = condition_tier

                pc_result['price_breakdown'] = f"New: ${new_price:.0f} | CIB: ${cib_price:.0f} | Loose: ${loose_price:.0f}"

                if old_market != condition_price:

                    logger.info(f"[PC] CONDITION ADJUSTMENT: '{condition}' [PASS] ¢¢{condition_tier} pricing")

                    logger.info(f"[PC] Price: ${old_market:.0f} (default) [PASS] ¢¢${condition_price:.0f} ({condition_tier})")

                # === CONDITION ARBITRAGE DETECTION (Video Games) ===
                # Flag when sealed items have large premium over CIB - possible mispricing
                if category == 'videogames' and condition_tier == 'New' and new_price > 0 and cib_price > 0:
                    sealed_premium_pct = ((new_price - cib_price) / cib_price) * 100 if cib_price > 0 else 0
                    # If sealed is 40%+ more than CIB and listing is under sealed price, flag it
                    if sealed_premium_pct >= 40 and per_item_price < new_price * 0.75:
                        pc_result['condition_arbitrage'] = True
                        pc_result['sealed_premium'] = sealed_premium_pct
                        logger.warning(f"[PC] CONDITION ARBITRAGE: Sealed {sealed_premium_pct:.0f}% over CIB!")
                        logger.warning(f"[PC] Sealed: ${new_price:.0f} vs CIB: ${cib_price:.0f} - List: ${per_item_price:.0f}")
                        logger.warning(f"[PC] >>> POSSIBLE MISPRICED SEALED - CHECK PHOTOS! <<<")

        # === LEGO SET NUMBER VALIDATION ===

        # Verify that returned product actually matches the set number in title

        if category == "lego" and pc_result and pc_result.get('found'):

            # Extract set number from title (5-digit numbers like 75187, 75192, etc.)

            title_set_match = re.search(r'\b(7\d{4}|1\d{4}|4\d{4}|6\d{4})\b', title)

            if title_set_match:

                title_set_number = title_set_match.group(1)

                product_name = str(pc_result.get('product_name', '')).lower()

                # Check if the returned product contains our set number

                if title_set_number not in product_name:

                    logger.warning(f"[PC] LEGO MISMATCH: Title has set #{title_set_number}, but PC returned '{product_name}'")

                    logger.warning(f"[PC] REJECTING PC result - wrong set matched!")

                    # Return no match instead of wrong data

                    pc_result = {

                        'found': False,

                        'error': f'PC returned wrong set (wanted {title_set_number})',

                        'market_price': None,

                        'buy_target': None,

                        'margin': None,

                    }

                else:

                    logger.info(f"[PC] LEGO set #{title_set_number} validated in product name")

            # === LEGO PRICE SANITY CHECK ===

            # Most LEGO sets are under $500. Only UCS sets go higher.

            # If PC returns >$1000 but listing is under $300, it's probably a wrong match

            if pc_result.get('found') and pc_result.get('market_price'):

                pc_market = pc_result.get('market_price', 0)

                # Known expensive keywords (UCS, Ultimate, etc.)

                is_known_expensive = any(term in title_lower for term in ['ucs', 'ultimate collector', '10179', '10221', '75192', '75252', '75313', '10276'])

                if pc_market > 1000 and per_item_price < 300 and not is_known_expensive:

                    logger.warning(f"[PC] LEGO PRICE SANITY FAIL: PC says ${pc_market:.0f} but listing is ${per_item_price:.0f}")

                    logger.warning(f"[PC] This looks like a wrong match - rejecting")

                    pc_result = {

                        'found': False,

                        'error': f'Price mismatch (PC=${pc_market:.0f}, list=${per_item_price:.0f})',

                        'market_price': None,

                        'buy_target': None,

                        'margin': None,

                    }

        # Add quantity info to result

        if pc_result:

            pc_result['quantity'] = quantity

            pc_result['total_price'] = total_price

            pc_result['per_item_price'] = per_item_price

            pc_result['detected_language'] = detected_language

            pc_result['language_discount'] = language_discount

        # === VIDEO GAME MATCH VALIDATION ===

        # Verify that returned product actually matches the game title

        if category == "videogames" and pc_result and pc_result.get('found'):

            product_name = str(pc_result.get('product_name', '')).lower()

            # Decode URL encoding and replace + with space
            search_title_clean = title_lower.replace('+', ' ').replace('%20', ' ')

            # Remove common junk from the search title for comparison
            junk_patterns = [

                r'\bcomplete\b', r'\bcib\b', r'\bauthentic\b', r'\bsealed\b', r'\bmint\b',

                r'\bgreat\b', r'\bgood\b', r'\bexcellent\b', r'\bcondition\b',

                r'\bnintendo\b', r'\bds\b', r'\b3ds\b', r'\bswitch\b', r'\bps[1-5]\b',

                r'\bplaystation\b', r'\bxbox\b', r'\bsega\b', r'\bgenesis\b',

                r'\bnes\b', r'\bsnes\b', r'\bgamecube\b', r'\bwii\b', r'\bn64\b',

                r'\d{4}',  # Years like 2011

            ]

            for pattern in junk_patterns:

                search_title_clean = re.sub(pattern, ' ', search_title_clean)

            search_title_clean = ' '.join(search_title_clean.split()).strip()

            # Get significant words (3+ chars) from the cleaned search title
            # Also strip punctuation like brackets [], parens (), etc.
            import string
            punct_table = str.maketrans('', '', string.punctuation + '[](){}')

            search_words = set(
                word.translate(punct_table)
                for word in search_title_clean.split()
                if len(word.translate(punct_table)) >= 3
            )
            product_words = set(
                word.translate(punct_table)
                for word in product_name.split()
                if len(word.translate(punct_table)) >= 3
            )

            # === CRITICAL: Check for VARIANT MISMATCH ===

            # If PC result has important words NOT in the title, it's likely wrong variant

            # Example: Title "Mighty Morphin Power Rangers" but PC returns "...The Movie" version

            variant_keywords = {
                'movie', 'deluxe', 'special', 'edition', 'gold', 'platinum', 'limited',
                'collectors', 'collector', 'goty', 'definitive', 'ultimate', 'complete',
                'anthology', 'trilogy', 'collection', 'remastered', 'remake', 'hd',
                'anniversary', 'classic', 'original', 'enhanced', 'expanded', 'directors',
                # Premium/special editions
                'premium', 'steelbook', 'launch', 'day', 'pre-order', 'preorder',
                # Version variants (Ultra, Plus, etc.)
                'ultra', 'plus', 'pro', 'turbo', 'super', 'hyper', 'mega', 'dual',
                # Budget re-releases (often MORE valuable due to rarity)
                'player', 'choice', 'players', 'greatest', 'hits', 'selects', 'essentials',
                'favorites', 'classics', 'budget', 'best'
            }

            # Words in PC result but NOT in title

            extra_words = product_words - search_words

            # Check if any extra words are variant indicators

            variant_mismatch = extra_words & variant_keywords

            if variant_mismatch:

                logger.warning(f"[PC] ️ VARIANT MISMATCH DETECTED!")

                logger.warning(f"[PC] Title: '{search_title_clean}'")

                logger.warning(f"[PC] PC returned: '{product_name}'")

                logger.warning(f"[PC] Extra variant words in PC result: {variant_mismatch}")

                logger.warning(f"[PC] REJECTING - likely wrong game variant (e.g., 'The Movie' vs regular)")

                # Reject this match - it's the wrong variant

                pc_result = {

                    'found': False,

                    'error': f'Variant mismatch - PC has "{variant_mismatch}" not in title',

                    'market_price': None,

                    'buy_target': None,

                    'margin': None,

                    'rejected_product': product_name,

                    'rejected_reason': f'Title missing variant keywords: {variant_mismatch}'

                }

            else:

                # Calculate match ratio for remaining validation

                if search_words:

                    matching = search_words & product_words

                    match_ratio = len(matching) / len(search_words)

                    logger.info(f"[PC] Video game validation: '{search_title_clean}' vs '{product_name}'")

                    logger.info(f"[PC] Matching words: {matching} ({match_ratio:.0%})")

                    if match_ratio < 0.2 and len(search_words) >= 3:

                        # Only reject if VERY low match (under 20%) - likely completely wrong game

                        logger.warning(f"[PC] VIDEO GAME VERY LOW MATCH: Only {match_ratio:.0%} word match")

                        logger.warning(f"[PC] Title words: {search_words}")

                        logger.warning(f"[PC] PC words: {product_words}")

                        logger.info(f"[PC] Keeping result but flagging low confidence")

                        # Don't reject - just flag as lower confidence

                        if pc_result:

                            pc_result['confidence'] = 'Medium'

                            pc_result['match_warning'] = f'Low word match ({match_ratio:.0%})'

                    else:

                        logger.info(f"[PC] Video game match validated: {product_name}")

            # === VIDEO GAME PLATFORM VALIDATION ===
            # Ensure the PC result matches the platform in the listing title
            if pc_result.get('found') and pc_result.get('console_name'):
                pc_console = pc_result.get('console_name', '').lower()

                # Platform detection from listing title
                platform_patterns = {
                    '3ds': ['3ds', 'nintendo 3ds'],
                    'ds': ['nintendo ds'],
                    'switch': ['switch', 'nintendo switch'],
                    'wii u': ['wii u', 'wiiu'],
                    'wii': ['wii'],
                    'gamecube': ['gamecube', 'gc', 'game cube'],
                    'n64': ['n64', 'nintendo 64'],
                    'snes': ['snes', 'super nintendo'],
                    'nes': ['nes'],
                    'xbox 360': ['xbox 360', 'xbox360', 'x360'],
                    'xbox one': ['xbox one', 'xbone', 'xb1'],
                    'xbox': ['xbox'],
                    'playstation 3': ['ps3', 'playstation 3'],
                    'playstation 4': ['ps4', 'playstation 4'],
                    'playstation 5': ['ps5', 'playstation 5'],
                    'playstation 2': ['ps2', 'playstation 2'],
                    'playstation': ['ps1', 'playstation', 'psx'],
                    'psp': ['psp'],
                    'vita': ['vita', 'ps vita'],
                    'genesis': ['genesis', 'mega drive'],
                    'dreamcast': ['dreamcast'],
                    'saturn': ['saturn'],
                }

                detected_platform = None
                for pc_platform, keywords in platform_patterns.items():
                    for kw in keywords:
                        if kw in title_lower:
                            detected_platform = pc_platform
                            break
                    if detected_platform:
                        break

                # Check if platforms match
                if detected_platform:
                    # Normalize PC console name for comparison
                    pc_console_normalized = pc_console.replace('nintendo', '').strip()

                    # Check if PC console contains the detected platform
                    platform_matches = (
                        detected_platform in pc_console or
                        pc_console in detected_platform or
                        (detected_platform == '3ds' and '3ds' in pc_console) or
                        (detected_platform == 'ds' and 'ds' in pc_console and '3ds' not in pc_console) or
                        (detected_platform == 'wii' and 'wii' in pc_console and 'wii u' not in pc_console) or
                        (detected_platform == 'xbox' and 'xbox' in pc_console) or
                        (detected_platform == 'gamecube' and 'gamecube' in pc_console)
                    )

                    if not platform_matches:
                        logger.warning(f"[PC] PLATFORM MISMATCH: Title says '{detected_platform}' but PC has '{pc_console}'")
                        logger.warning(f"[PC] Rejecting match to avoid cross-platform price confusion")
                        pc_result = {
                            'found': False,
                            'error': f'Platform mismatch: title={detected_platform}, PC={pc_console}',
                            'market_price': None,
                            'buy_target': None,
                            'margin': None,
                            'rejected_product': pc_result.get('product_name'),
                            'rejected_reason': f'Platform mismatch: {detected_platform} vs {pc_console}'
                        }

            # === VIDEO GAME PRICE SANITY CHECK ===
            # Most games are under $200. Only rare titles go higher.
            if pc_result.get('found') and pc_result.get('market_price'):
                pc_market = pc_result.get('market_price', 0)

                # If PC returns >$500 but listing is under $100, probably wrong match
                if pc_market > 500 and per_item_price < 100:
                    logger.warning(f"[PC] VIDEO GAME PRICE SANITY FAIL: PC says ${pc_market:.0f} but listing is ${per_item_price:.0f}")
                    logger.warning(f"[PC] This looks like a wrong match - rejecting")
                    pc_result = {
                        'found': False,
                        'error': f'Price mismatch (PC=${pc_market:.0f}, list=${per_item_price:.0f})',
                        'market_price': None,
                        'buy_target': None,
                        'margin': None,
                    }

        # Re-add quantity info if we validated successfully

        if pc_result and 'quantity' not in pc_result:

            pc_result['quantity'] = quantity

            pc_result['total_price'] = total_price

            pc_result['per_item_price'] = per_item_price

            pc_result['detected_language'] = detected_language

            pc_result['language_discount'] = language_discount

            # === APPLY LANGUAGE DISCOUNT TO PRICES ===

            if detected_language != "english" and pc_result.get('found') and pc_result.get('market_price'):

                original_market = pc_result['market_price']

                adjusted_market = original_market * language_discount
                cat_threshold = get_category_threshold(category)

                pc_result['market_price'] = adjusted_market

                pc_result['buy_target'] = adjusted_market * cat_threshold

                pc_result['margin'] = pc_result['buy_target'] - per_item_price

                lang_upper = detected_language.upper() if detected_language else "UNKNOWN"

                logger.info(f"[PC] Language adjustment: ${original_market:.0f} English -> ${adjusted_market:.0f} {lang_upper}")

            # Recalculate total margin if we have a match

            if pc_result.get('found') and pc_result.get('margin') is not None:

                per_item_margin = pc_result['margin']

                pc_result['total_margin'] = per_item_margin * quantity

        # Check if we got a valid result

        if pc_result and pc_result.get('found') and pc_result.get('market_price'):

            market_price = pc_result.get('market_price', 0)

            buy_target = pc_result.get('buy_target', 0)

            margin = pc_result.get('margin', 0)

            confidence = pc_result.get('confidence', 'Unknown')

            product_name = pc_result.get('product_name', 'Unknown')

            # Language adjustment note

            lang_note = ""

            if detected_language != "english":

                lang_note = f"\nLANGUAGE: {detected_language.upper() if detected_language else 'UNKNOWN'} - Price adjusted to {language_discount*100:.0f}% of English value"

            # Build quantity-aware context

            # Add condition tier note

            condition_note = ""

            if pc_result.get('condition_tier'):

                condition_note = f"\nCONDITION: Using {pc_result['condition_tier']} pricing"

                if pc_result.get('price_breakdown'):

                    condition_note += f" ({pc_result['price_breakdown']})"

            if quantity > 1:

                total_margin = margin * quantity

                context = f"""

=== PRICECHARTING DATA (USE THIS FOR PRICING) ===

Matched Product: {product_name}

Category: {pc_result.get('category', category).upper()}

Console: {pc_result.get('console_name', 'N/A')}{lang_note}{condition_note}

QUANTITY: {quantity} items

Market Price (each): ${market_price:,.2f}

Buy Target (65% each): ${buy_target:,.2f}

Listing Price (total): ${total_price:,.2f}

Per-Item Price: ${per_item_price:,.2f}

Margin (per item): ${margin:,.2f}

TOTAL MARGIN: ${total_margin:,.2f}

Match Confidence: {confidence}

Source: PriceCharting Database

=== END PRICECHARTING DATA ===

IMPORTANT: This is a {quantity}-item lot. Use PER-ITEM margin for decision.

If per-item margin is NEGATIVE, recommendation MUST be PASS.

If match confidence is Low, recommend RESEARCH instead of BUY.

"""

            else:

                context = f"""

=== PRICECHARTING DATA (USE THIS FOR PRICING) ===

Matched Product: {product_name}

Category: {pc_result.get('category', category).upper()}

Console: {pc_result.get('console_name', 'N/A')}{lang_note}{condition_note}

Market Price: ${market_price:,.2f}

Buy Target (65%): ${buy_target:,.2f}

Listing Price: ${total_price:,.2f}

Margin: ${margin:,.2f}

Match Confidence: {confidence}

Source: PriceCharting Database

=== END PRICECHARTING DATA ===

IMPORTANT: Use the market price above for your calculations. 

If margin is NEGATIVE, recommendation MUST be PASS.

If match confidence is Low, recommend RESEARCH instead of BUY.

"""

            lang_suffix = f" [{detected_language.upper()}]" if detected_language != "english" else ""

            if quantity > 1:

                logger.info(f"[PC] Found: {product_name}{lang_suffix} @ ${market_price:,.0f} x{quantity} = ${market_price * quantity:,.0f} total (conf: {confidence})")

            else:

                logger.info(f"[PC] Found: {product_name}{lang_suffix} @ ${market_price:,.0f} (conf: {confidence})")

            return pc_result, context

        else:

            error_msg = pc_result.get('error', 'No match found') if pc_result else 'Lookup failed'

            logger.info(f"[PC] No match for: {title[:50]}... ({error_msg})")

            return None, f"""

=== NO PRICECHARTING MATCH ===

Product not found in price database: {error_msg}

Use your knowledge to estimate value, or recommend RESEARCH for verification.

=== END ===

"""

    except Exception as e:

        logger.error(f"[PC] Lookup error: {e}")

        return None, ""

# NOTE: normalize_tcg_lego_keys moved to utils/validation.py
# Wrapper for backward compatibility
def normalize_tcg_lego_keys(result: dict, category: str) -> dict:
    """Wrapper for utils.validation.normalize_tcg_lego_keys"""
    return utils_normalize_tcg_lego_keys(result, category)

def validate_tcg_lego_result(result: dict, pc_result: dict, total_price: float, category: str, title: str = "") -> dict:

    """

    Server-side validation for TCG/LEGO results

    Override AI calculations with PriceCharting data

    Now includes graded card (PSA/BGS/CGC) validation.

    """

    # First normalize keys (AI sometimes returns wrong case/spacing)

    result = normalize_tcg_lego_keys(result, category)

    # === GRADED CARD VALIDATION ===
    # If pc_result contains graded card data, use it for validation
    if pc_result and pc_result.get('is_graded'):
        grader = pc_result.get('grader')
        grade = pc_result.get('grade')
        market_price = pc_result.get('market_price', 0)
        buy_target = pc_result.get('buy_target', 0)
        margin = pc_result.get('margin', 0)
        confidence = pc_result.get('confidence', 'Medium')

        logger.info(f"[TCG-GRADED] Validating: {grader} {grade} @ ${market_price:.0f}, margin ${margin:.0f}")

        # Override AI values with PriceCharting graded data
        result['marketprice'] = str(int(market_price))
        result['maxBuy'] = str(int(buy_target))
        result['Margin'] = f"+{int(margin)}" if margin >= 0 else str(int(margin))
        result['Profit'] = result['Margin']
        result['pcMatch'] = 'Yes'
        result['pcProduct'] = pc_result.get('product_name', '')[:50]
        result['pcConfidence'] = confidence
        result['isGraded'] = 'Yes'
        result['grader'] = grader
        result['grade'] = grade
        result['rawValue'] = pc_result.get('raw_price', 0)
        result['gradeMultiplier'] = pc_result.get('multiplier', 1)

        # Graded card recommendation logic
        ai_rec = result.get('Recommendation', 'RESEARCH')

        # CRITICAL: PASS if negative margin
        if margin < 0 and ai_rec == 'BUY':
            result['Recommendation'] = 'PASS'
            result['Qualify'] = 'No'
            result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative margin (${margin:.0f}) on graded card - PASS"
            logger.info(f"[TCG-GRADED] Override: BUY->PASS (margin ${margin:.0f})")

        # High-value graded cards (>$500) should be RESEARCH for authenticity verification
        elif market_price > 500 and ai_rec == 'BUY':
            result['Recommendation'] = 'RESEARCH'
            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: High-value graded card (${market_price:.0f}) - verify authenticity before buying"
            logger.info(f"[TCG-GRADED] Override: BUY->RESEARCH (high-value graded card)")

        # === ALL GRADED CARDS: FORCE RESEARCH (NO BUY SIGNALS) ===
        # PSA/BGS/CGC values are highly variable and matching is error-prone
        # Fake slabs are common - always verify before buying
        elif ai_rec == 'BUY':
            result['Recommendation'] = 'RESEARCH'
            result['Qualify'] = 'Maybe'
            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: ALL graded cards require manual verification - fake slabs common, values variable"
            logger.warning(f"[TCG-GRADED] Override: BUY->RESEARCH (graded cards always need verification)")

        # Moderate margin with PASS = upgrade to RESEARCH (so user can review)
        elif margin >= 20 and ai_rec == 'PASS':
            result['Recommendation'] = 'RESEARCH'
            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Margin +${margin:.0f} warrants manual review"
            logger.info(f"[TCG-GRADED] Override: PASS->RESEARCH (margin +${margin:.0f})")

        return result

    # === LEGO CONDITION CHECK - SERVER OVERRIDE ===

    # Force PASS for opened/no-box LEGO even if AI says BUY

    if category == 'lego':

        reasoning_text = str(result.get('reasoning', '')).lower()

        title_lower = title.lower() if title else ""

        check_text = f"{title_lower} {reasoning_text}"

        # Terms that indicate NOT sealed/new - INSTANT PASS

        lego_pass_terms = [

            'no box', 'missing box', 'without box', 'box only',

            'open box', 'opened', 'box opened',

            'used', 'played with', 'pre-owned', 'previously owned',

            'built', 'assembled', 'displayed', 'complete build',

            'incomplete', 'partial', 'missing pieces', 'missing parts',

            'bulk', 'loose', 'bricks only', 'parts only',

            'damaged box', 'box damage', 'crushed', 'dented', 'torn',

            'minifigures only', 'minifig lot', 'figures only',

            'bags only', 'sealed bags', 'numbered bags'  # Bags without box = not complete

        ]

        # KNOCKOFF/FAKE LEGO DETECTION - these are NOT real LEGO
        lego_knockoff_terms = [
            'alt of lego', 'alternative of lego', 'generic bricks', 'generic blocks',
            'compatible with lego', 'lego compatible', 'building blocks',
            'mould king', 'lepin', 'bela', 'lele', 'decool', 'sy blocks',
            'king blocks', 'lion king', 'xinlexin', 'lari', 'nuogao',
            'not lego', 'non-lego', 'third party', '3rd party bricks',
            'clone', 'knockoff', 'replica blocks', 'off-brand'
        ]

        for knockoff_term in lego_knockoff_terms:
            if knockoff_term in check_text:
                logger.warning(f"[LEGO] KNOCKOFF DETECTED: '{knockoff_term}' in title - INSTANT PASS")
                result['Recommendation'] = 'PASS'
                result['Qualify'] = 'No'
                result['reasoning'] = f"SERVER OVERRIDE: FAKE/KNOCKOFF LEGO detected ('{knockoff_term}') - NOT authentic LEGO - PASS"
                return result

        # Check both title and reasoning for pass terms
        for term in lego_pass_terms:

            if term in check_text:

                # Check if it's actually missing box (not just mentioning it exists)

                if term in ['sealed bags', 'numbered bags', 'bags only']:

                    # Only PASS if there's NO box mentioned positively

                    if 'with box' not in check_text and 'box included' not in check_text and 'complete' not in check_text:

                        logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected - bags without box")

                        result['Recommendation'] = 'PASS'

                        result['Qualify'] = 'No'

                        result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' = not factory sealed with box - PASS"

                        return result

                elif term == 'missing box' or term == 'no box':

                    logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected in listing")

                    result['Recommendation'] = 'PASS'

                    result['Qualify'] = 'No'

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' - we only buy sealed with box - PASS"

                    return result

                else:

                    logger.warning(f"[LEGO] CONDITION FAIL: '{term}' detected - not sealed/new")

                    result['Recommendation'] = 'PASS'

                    result['Qualify'] = 'No'

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: '{term}' = not sealed - PASS"

                    return result

    # === REASONING VS FIELD CONSISTENCY CHECK ===

    # AI sometimes calculates correctly in reasoning but puts wrong value in Profit field

    reasoning_text = str(result.get('reasoning', '')).lower()

    # Look for margin patterns in reasoning: "+$101 margin", "= +$101", "$101 margin"

    margin_patterns = [

        r'[=\s]\+?\$?(\d+(?:\.\d+)?)\s*margin',      # "= $101 margin" or "+$101 margin"

        r'margin[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "margin: $101" or "margin $101"

        r'profit[:\s]+\+?\$?(\d+(?:\.\d+)?)',         # "profit: $101"

        r'\+\$(\d+(?:\.\d+)?)\s*(?:margin|profit)',   # "+$101 margin"

    ]

    reasoning_margin = None

    for pattern in margin_patterns:

        match = re.search(pattern, reasoning_text)

        if match:

            reasoning_margin = float(match.group(1))

            break

    # If NO PriceCharting match, be conservative - don't trust AI pricing

    if not pc_result or not pc_result.get('found') or not pc_result.get('market_price'):

        ai_rec = result.get('Recommendation', 'RESEARCH')

        # Without verified pricing, downgrade BUY to RESEARCH

        if ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: No PriceCharting match - verify pricing manually before buying"

            result['pcMatch'] = 'No'

            logger.info(f"[PC] Override: BUY->RESEARCH (no PC match, unverified pricing)")

        # For expensive LEGO/TCG items without PC match, upgrade PASS to RESEARCH
        # These could be valuable items not in database (new sets, rare items)
        elif ai_rec == 'PASS' and category in ['lego', 'tcg'] and total_price >= 75:

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Expensive {category.upper()} (${total_price:.0f}) not in database - verify value manually"

            result['pcMatch'] = 'No'

            logger.warning(f"[PC] Override: PASS->RESEARCH (expensive {category} ${total_price:.0f} not in database)")

        # If we found margin in reasoning, use that instead of NA

        if reasoning_margin is not None:

            margin_display = f"+{int(reasoning_margin)}" if reasoning_margin >= 0 else str(int(reasoning_margin))

            result['Profit'] = margin_display

            result['Margin'] = margin_display

            logger.info(f"[PC] Using reasoning margin ${reasoning_margin:.0f} (no PC data)")

        else:

            # Clear AI's potentially wrong profit/margin values when no PC data

            result['Profit'] = 'NA'

            result['Margin'] = 'NA'

        return result

    try:

        # Server is source of truth for prices

        server_market = pc_result.get('market_price', 0)

        server_buy_target = pc_result.get('buy_target', 0)

        # === CRITICAL: ALWAYS RECALCULATE MARGIN FROM ACTUAL LISTING PRICE ===

        # AI sometimes hallucinates quantities and divides the price incorrectly

        # Use the ACTUAL total_price passed from the listing

        server_margin = server_buy_target - total_price

        confidence = pc_result.get('confidence', 'Low')

        product_name = pc_result.get('product_name', 'Unknown')

        # === MULTI-SET LOT HANDLING ===

        is_multi_set = pc_result.get('multi_set', False)

        if is_multi_set:

            set_count = pc_result.get('set_count', 1)

            set_details = pc_result.get('set_details', [])

            all_found = pc_result.get('all_sets_found', False)

            logger.info(f"[PC] MULTI-SET LOT: {set_count} sets, market ${server_market:.0f}, margin ${server_margin:.0f}")

            # Build set breakdown for display

            set_breakdown = ", ".join([f"{d['set_number']}" for d in set_details])

            result['SetNumber'] = f"[{set_breakdown}]"

            result['SetName'] = f"LOT of {set_count} sets"

            result['SetCount'] = str(set_count)

            result['marketprice'] = str(int(server_market))

            result['maxBuy'] = str(int(server_buy_target))

            result['Margin'] = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            result['Profit'] = result['Margin']

            result['pcMatch'] = 'Yes'

            result['pcProduct'] = f"LOT: {set_count} sets"

            result['pcConfidence'] = confidence

            # Recommendation based on margin

            if server_margin >= 30:

                result['Recommendation'] = 'BUY'

                result['Qualify'] = 'Yes'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot worth ${server_market:.0f}, margin ${server_margin:+.0f}"

            elif server_margin >= 0:

                result['Recommendation'] = 'RESEARCH'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot thin margin ${server_margin:+.0f}"

            else:

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Multi-set lot negative margin ${server_margin:.0f}"

            if not all_found:

                result['reasoning'] = result.get('reasoning', '') + " | WARNING: Not all sets found in database"

                result['Recommendation'] = 'RESEARCH'  # Be conservative when some sets missing

            return result

        # Get quantity from AI but VERIFY it makes sense

        ai_quantity = pc_result.get('quantity', 1)

        # Log the actual calculation

        logger.info(f"[PC] SERVER CALC: maxBuy ${server_buy_target:.0f} - listPrice ${total_price:.0f} = margin ${server_margin:.0f}")

        # Check if AI might have divided the price by quantity

        ai_margin_str = str(result.get('Margin', result.get('Profit', '0')))

        try:

            ai_margin = float(ai_margin_str.replace('$', '').replace('+', '').replace(',', ''))

        except:

            ai_margin = 0

        # If AI margin is positive but server margin is negative, AI likely divided price wrong

        if ai_margin > 0 and server_margin < -20:

            logger.warning(f"[PC] AI MARGIN ERROR: AI says +${ai_margin:.0f} but server calc = ${server_margin:.0f}")

            logger.warning(f"[PC] AI may have divided price by quantity - using server calculation")

            # AI hallucinated - reset quantity to 1

            ai_quantity = 1

        quantity = ai_quantity

        # === SANITY CHECK: Compare server margin to reasoning margin ===

        if reasoning_margin is not None:

            # If server and reasoning margins differ significantly, log it

            if abs(server_margin - reasoning_margin) > 50:

                logger.warning(f"[PC] MARGIN MISMATCH: Server ${server_margin:.0f} vs Reasoning ${reasoning_margin:.0f}")

                # Only trust reasoning if server margin is POSITIVE but reasoning is negative

                # (means server may have matched wrong product)

                # If server is negative, trust it - the listing price is definitive

                if server_margin > 0 and reasoning_margin < 0:

                    logger.warning(f"[PC] Server positive but reasoning negative - possible wrong PC match")

                    # Keep server_margin but flag for research

                elif server_margin < 0 and reasoning_margin > 0:

                    # AI likely did bad math (divided price by quantity, etc.)

                    logger.warning(f"[PC] AI positive but server negative - AI likely hallucinated quantity")

                    # Keep server_margin (it's calculated from actual listing price)

        # For multi-quantity, show per-item values but note the quantity

        if quantity > 1:

            total_margin = server_margin * quantity

            logger.info(f"[PC] Validating: {product_name} x{quantity} | Market ${server_market:.0f}/ea | Margin ${server_margin:.0f}/ea (${total_margin:.0f} total)")

            result['quantity'] = str(quantity)

            result['perItemMargin'] = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            margin_display = f"+{int(total_margin)}" if total_margin >= 0 else str(int(total_margin))

            result['Margin'] = margin_display

            result['Profit'] = margin_display  # Also set Profit so display uses correct value

        else:

            logger.info(f"[PC] Validating: {product_name} | Market ${server_market:.0f} | Buy ${server_buy_target:.0f} | List ${total_price:.0f} | Margin ${server_margin:.0f}")

            margin_display = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))

            result['Margin'] = margin_display

            result['Profit'] = margin_display  # Also set Profit so display uses correct value

        # Override AI values with server-calculated values

        result['marketprice'] = str(int(server_market))

        result['maxBuy'] = str(int(server_buy_target))

        # Add PriceCharting match info

        result['pcMatch'] = 'Yes'

        result['pcProduct'] = pc_result.get('product_name', '')[:50]

        result['pcConfidence'] = confidence

        # Override recommendation if AI got it wrong

        ai_rec = result.get('Recommendation', 'RESEARCH')

        # For multi-quantity lots, use TOTAL margin for thresholds

        # (a 10-item lot with $5/item = $50 total is worth it)

        decision_margin = server_margin * quantity if quantity > 1 else server_margin

        # CRITICAL: PASS if negative margin (AI sometimes misses this)

        if server_margin < 0 and ai_rec == 'BUY':

            result['Recommendation'] = 'PASS'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative per-item margin (${server_margin:.0f}/ea) - PASS"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative margin (${server_margin:.0f}) - PASS"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(margin ${server_margin:.0f})")

        # CRITICAL: PASS if total margin too thin (< $20 profit not worth it)

        elif decision_margin < 20 and ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Thin total margin (${decision_margin:.0f} for {quantity}x) - verify manually"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Thin margin (${server_margin:.0f}) - verify manually"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(thin margin ${decision_margin:.0f})")

        # Upgrade to BUY if strong margin and AI was too conservative

        elif decision_margin >= 50 and confidence in ['High', 'Medium'] and ai_rec == 'RESEARCH':

            result['Recommendation'] = 'BUY'

            if quantity > 1:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Strong total margin (${decision_margin:.0f} for {quantity}x) - BUY"

            else:

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Strong margin (${server_margin:.0f}) - BUY"

            logger.info(f"[PC] Override: RESEARCH->BUY (margin ${decision_margin:.0f})")

        # CRITICAL: Override PASS→BUY when AI made arithmetic error (margin is actually positive)
        elif decision_margin >= 25 and confidence in ['High', 'Medium'] and ai_rec == 'PASS':

            result['Recommendation'] = 'BUY'
            result['Qualify'] = 'Yes'

            if quantity > 1:
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: AI error - margin is +${decision_margin:.0f} for {quantity}x - BUY"
            else:
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: AI arithmetic error - margin is +${server_margin:.0f} - BUY"

            logger.info(f"[PC] Override: PASS->BUY (margin actually +${decision_margin:.0f})")

        # Moderate positive margin with PASS = upgrade to RESEARCH
        elif decision_margin >= 10 and ai_rec == 'PASS':

            result['Recommendation'] = 'RESEARCH'
            result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Margin +${decision_margin:.0f} warrants review"
            logger.info(f"[PC] Override: PASS->RESEARCH (margin +${decision_margin:.0f})")

        # Low confidence = always RESEARCH

        elif confidence == 'Low' and ai_rec == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: Low confidence match - verify product"

            logger.info(f"[PC] Override: BUYƒÆ’‚[PASS] ¢[PASS] ¢(low confidence)")

    except Exception as e:

        logger.error(f"[PC] Validation error: {e}")

    return result

def validate_videogame_result(result: dict, pc_result: dict, total_price: float, data: dict) -> dict:

    """

    Server-side validation for video game results.

    Checks math, professional sellers, and applies PriceCharting data.

    NOTE: Uses standard 65% threshold. Sonnet verification catches pricing issues

    like wrong condition tier from PriceCharting.

    """

    try:
        # Set category for threshold lookup
        category = 'videogames'

        reasoning_text = str(result.get('reasoning', '')).lower()

        # === LOT ITEM LOOKUP ===
        # If AI identified individual games in a lot, look them up in PriceCharting
        lot_items = result.get('lotItems', [])
        if lot_items and isinstance(lot_items, list) and len(lot_items) > 0:
            logger.info(f"[VG-LOT] Identified {len(lot_items)} games in lot: {lot_items[:5]}...")  # Show first 5

            console = result.get('console', '')
            lot_total_value = 0
            lot_items_found = 0

            for game_title in lot_items[:20]:  # Limit to 20 games to avoid API spam
                if not game_title or len(str(game_title)) < 3:
                    continue

                # Look up in PriceCharting
                search_query = f"{game_title} {console}".strip() if console else game_title
                game_pc = _config['pc_lookup'](search_query, category="videogames", listing_price=0)

                if game_pc and game_pc.get('found') and game_pc.get('market_price', 0) > 0:
                    game_value = game_pc.get('market_price', 0)
                    lot_total_value += game_value
                    lot_items_found += 1
                    logger.info(f"[VG-LOT]   {game_title}: ${game_value:.0f}")

            if lot_items_found > 0:
                # Update market price with summed values
                logger.info(f"[VG-LOT] Total lot value: ${lot_total_value:.0f} from {lot_items_found} identified games")
                result['marketprice'] = str(int(lot_total_value))
                result['lotValueMethod'] = 'itemized'
                result['lotItemsFound'] = lot_items_found

                # Recalculate margin
                cat_threshold = get_category_threshold(category)
                lot_maxbuy = lot_total_value * cat_threshold
                lot_margin = lot_maxbuy - total_price
                result['maxBuy'] = str(int(lot_maxbuy))
                result['Margin'] = str(int(lot_margin))
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Itemized lot - {lot_items_found} games = ${lot_total_value:.0f}, maxBuy ${lot_maxbuy:.0f}"

                # Update recommendation based on new margin
                if lot_margin >= 20 and result.get('Recommendation') == 'RESEARCH':
                    result['Recommendation'] = 'BUY'
                    result['reasoning'] += " | Upgraded to BUY (positive itemized margin)"
                elif lot_margin < 0 and result.get('Recommendation') == 'BUY':
                    result['Recommendation'] = 'PASS'
                    result['reasoning'] += " | PASS (negative margin after itemization)"

        # === FALLBACK LOT VALUATION ===
        # If we have a lot count but no/few itemized games, apply minimum per-game estimate
        is_lot = str(result.get('isLot', '')).lower() == 'yes'
        lot_count = 0
        try:
            lot_count = int(result.get('lotCount', 0))
        except:
            pass

        lot_items_found = result.get('lotItemsFound', 0)

        if is_lot and lot_count >= 5 and lot_items_found < lot_count * 0.3:
            # Less than 30% of games identified - apply conservative floor estimate
            console = str(result.get('console', '')).lower()

            # Conservative per-game minimums by console
            per_game_min = {
                'ds': 3, 'nintendo ds': 3, '3ds': 4, 'nintendo 3ds': 4,
                'gba': 5, 'game boy advance': 5, 'game boy': 4,
                'snes': 8, 'super nintendo': 8, 'nes': 5,
                'n64': 10, 'nintendo 64': 10,
                'gamecube': 12, 'gcn': 12,
                'wii': 3, 'wii u': 5,
                'ps1': 3, 'ps2': 3, 'ps3': 4,
                'xbox': 3, 'xbox 360': 3,
                'genesis': 4, 'sega genesis': 4,
            }.get(console, 4)  # Default $4/game if console unknown

            floor_value = lot_count * per_game_min
            current_market = 0
            try:
                current_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))
            except:
                pass

            # Only apply floor if current estimate is less than floor
            if floor_value > current_market:
                logger.warning(f"[VG-LOT] Floor estimate: {lot_count} games x ${per_game_min} = ${floor_value} (was ${current_market:.0f})")
                result['marketprice'] = str(int(floor_value))
                result['lotValueMethod'] = 'floor_estimate'

                # Recalculate margin with floor value
                cat_threshold = get_category_threshold(category)
                floor_maxbuy = floor_value * cat_threshold
                floor_margin = floor_maxbuy - total_price
                result['maxBuy'] = str(int(floor_maxbuy))
                result['Margin'] = str(int(floor_margin))
                result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Floor estimate {lot_count} games x ${per_game_min} = ${floor_value}, maxBuy ${floor_maxbuy:.0f}"

                # Update recommendation if now profitable
                if floor_margin >= 30:
                    result['Recommendation'] = 'RESEARCH'
                    result['reasoning'] += " | Needs verification but floor value suggests profitable"

        # === LOW CONFIDENCE CHECK ===

        # If confidence is Low or reasoning shows uncertainty, cannot be BUY

        confidence = result.get('confidence', 'Low')

        if isinstance(confidence, (int, float)):

            confidence_val = int(confidence)

        elif isinstance(confidence, str):

            if confidence.isdigit():

                confidence_val = int(confidence)

            else:

                confidence_val = {'high': 80, 'medium': 60, 'low': 40}.get(confidence.lower().split()[0], 40)

        else:

            confidence_val = 40

        # Uncertainty indicators in reasoning

        uncertainty_phrases = [

            'cannot verify', 'without images', 'need visual', 'unable to confirm',

            'need verification', 'optimistic', 'seems high', 'uncertain',

            'cannot determine', 'hard to tell', 'impossible to verify',

            'no images', 'missing images', 'requires inspection'

        ]

        has_uncertainty = any(phrase in reasoning_text for phrase in uncertainty_phrases)

        if result.get('Recommendation') == 'BUY' and (confidence_val <= 30 or has_uncertainty):

            logger.warning(f"[VG] LOW CONFIDENCE BUY: conf={confidence_val}, uncertainty={has_uncertainty}")

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER OVERRIDE: Low confidence/uncertainty - cannot BUY without verification"

            logger.info(f"[VG] Override: BUY->RESEARCH (low confidence or uncertainty in reasoning)")

        # === PROFESSIONAL SELLER DETECTION ===

        seller_id = str(data.get('Seller', data.get('seller', ''))).lower()

        professional_keywords = [

            'games', 'gaming', 'retro', 'vintage', 'collectibles', 'collector',

            'video', 'game', 'shop', 'store', 'entertainment', 'media'

        ]

        is_professional = any(kw in seller_id for kw in professional_keywords)

        if is_professional:

            logger.info(f"[VG] Professional seller detected: {seller_id}")

            # Lower confidence if AI said High

            if result.get('confidence') == 'High':

                result['confidence'] = 'Medium'

            # Add to reasoning

            result['reasoning'] = result.get('reasoning', '') + f" | WARNING: Professional seller '{seller_id}' - prices likely at/above market"

        # === MATH VALIDATION (category-specific threshold) ===
        cat_threshold = get_category_threshold(category)
        threshold_pct = int(cat_threshold * 100)

        try:

            ai_market = float(str(result.get('marketprice', '0')).replace('$', '').replace(',', ''))

            ai_maxbuy = float(str(result.get('maxBuy', '0')).replace('$', '').replace(',', '').replace('NA', '0'))

            if ai_market > 0:

                correct_maxbuy = ai_market * cat_threshold

                correct_margin = correct_maxbuy - total_price

                # Check if AI got the threshold calculation wrong

                if ai_maxbuy > 0 and abs(ai_maxbuy - correct_maxbuy) > 5:  # More than $5 off

                    logger.warning(f"[VG] MATH ERROR: AI maxBuy ${ai_maxbuy:.0f} vs correct ${correct_maxbuy:.0f}")

                    result['maxBuy'] = str(int(correct_maxbuy))

                    result['Margin'] = f"+{int(correct_margin)}" if correct_margin >= 0 else str(int(correct_margin))

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER: Corrected maxBuy to ${correct_maxbuy:.0f} ({threshold_pct}% of ${ai_market:.0f})"

                # If margin is actually negative but AI said BUY, force PASS

                if correct_margin < 0 and result.get('Recommendation') == 'BUY':

                    logger.warning(f"[VG] Forcing PASS: Margin is actually ${correct_margin:.0f}")

                    result['Recommendation'] = 'PASS'

                    result['Margin'] = str(int(correct_margin))

                    result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: Negative margin (${correct_margin:.0f}) - PASS"

        except (ValueError, TypeError) as e:

            logger.debug(f"[VG] Math validation skipped: {e}")

        # === PRICECHARTING DATA OVERRIDE ===

        if pc_result and pc_result.get('found') and pc_result.get('market_price'):

            pc_market = pc_result['market_price']

            pc_maxbuy = pc_market * cat_threshold  # Use category-specific threshold

            pc_margin = pc_maxbuy - total_price

            logger.info(f"[VG] PriceCharting: Market ${pc_market:.0f}, maxBuy ${pc_maxbuy:.0f}, margin ${pc_margin:.0f}")

            # Override AI values with PriceCharting data

            result['marketprice'] = str(int(pc_market))

            result['maxBuy'] = str(int(pc_maxbuy))

            result['Margin'] = f"+{int(pc_margin)}" if pc_margin >= 0 else str(int(pc_margin))

            result['pcMatch'] = 'Yes'

            result['pcProduct'] = pc_result.get('product_name', '')[:50]

            # Add condition arbitrage flag if detected
            if pc_result.get('condition_arbitrage'):
                result['conditionArbitrage'] = 'SEALED MISPRICED?'
                result['sealedPremium'] = f"{pc_result.get('sealed_premium', 0):.0f}%"
                result['reasoning'] = result.get('reasoning', '') + f" | CONDITION ARBITRAGE: Sealed is {pc_result.get('sealed_premium', 0):.0f}% over CIB - may be mispriced!"

            # Force PASS if PriceCharting shows negative margin

            if pc_margin < 0 and result.get('Recommendation') == 'BUY':

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + f" | SERVER OVERRIDE: PriceCharting shows ${pc_margin:.0f} margin - PASS"

                logger.info(f"[VG] Override: BUY->PASS (PC margin ${pc_margin:.0f})")

        # Downgrade to RESEARCH if no PC match and AI said BUY

        elif result.get('Recommendation') == 'BUY':

            result['Recommendation'] = 'RESEARCH'

            result['pcMatch'] = 'No'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: No PriceCharting match - verify pricing manually"

            logger.info(f"[VG] Override: BUY->RESEARCH (no PC match)")

    except Exception as e:

        logger.error(f"[VG] Validation error: {e}")

    return result
