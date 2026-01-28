"""
Instant Pass Module

Rule-based instant pass logic for listings that don't need AI analysis.
Saves API costs by immediately passing listings that match certain criteria.

Extracted from main.py for better organization.
"""

import re
import logging
import asyncio
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Ollama integration for fallback extraction
_ollama_module = None
_ollama_checked = False

def _get_ollama():
    """Lazy load Ollama module."""
    global _ollama_module, _ollama_checked
    if not _ollama_checked:
        _ollama_checked = True
        try:
            from ollama_extract import extract_gold_silver_info, is_available, check_ollama_available
            _ollama_module = {
                'extract': extract_gold_silver_info,
                'is_available': is_available,
                'check': check_ollama_available,
            }
            # Trigger availability check
            asyncio.create_task(check_ollama_available())
            logger.info("[OLLAMA] Module loaded for fallback extraction")
        except ImportError as e:
            logger.debug(f"[OLLAMA] Not available: {e}")
            _ollama_module = None
    return _ollama_module

# Pre-compiled regex patterns for weight extraction
# IMPORTANT: Word boundaries \b prevent matching years like "1997" as "1997g"
# when followed by words starting with 'g'
WEIGHT_PATTERNS = [
    re.compile(r'(\d*\.?\d+)\s*(?:gram|grams|gr)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*g\b', re.IGNORECASE),  # Added \b to prevent false matches
    re.compile(r'(\d*\.?\d+)\s*(?:dwt|DWT)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*(?:ozt|oz\.t|troy\s*oz)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*oz\b', re.IGNORECASE),
]

# Years that should NOT be treated as weights (1900-2030)
YEAR_RANGE = range(1900, 2031)

# Fractional oz patterns
FRACTION_OZT_PATTERN = re.compile(r'(\d+)/(\d+)\s*(?:ozt|oz\.t|troy\s*oz)', re.IGNORECASE)
FRACTION_OZ_PATTERN = re.compile(r'(\d+)/(\d+)\s*oz', re.IGNORECASE)

# Karat extraction patterns (pattern, karat_value)
KARAT_PATTERNS = [
    (re.compile(r'24\s*k(?:t|arat)?', re.IGNORECASE), 24),
    (re.compile(r'22\s*k(?:t|arat)?', re.IGNORECASE), 22),
    (re.compile(r'18\s*k(?:t|arat)?', re.IGNORECASE), 18),
    (re.compile(r'14\s*k(?:t|arat)?', re.IGNORECASE), 14),
    (re.compile(r'10\s*k(?:t|arat)?', re.IGNORECASE), 10),
    (re.compile(r'9\s*k(?:t|arat)?', re.IGNORECASE), 9),
    (re.compile(r'999'), 24),
    (re.compile(r'916'), 22),
    (re.compile(r'750'), 18),
    (re.compile(r'585'), 14),
    (re.compile(r'417'), 10),
    (re.compile(r'375'), 9),
]

# Chain type weight estimation (grams per inch for 14K)
HEAVY_CHAIN_TYPES = {
    'byzantine': 2.5,
    'miami cuban': 2.5,
    'cuban link': 2.0,
    'cuban': 2.0,
    'rope': 1.5,
    'herringbone': 1.5,
    'franco': 1.8,
    'figaro': 1.2,
    'mariner': 1.2,
    'anchor': 1.0,
    'wheat': 1.0,
    'snake': 1.0,
    'box chain': 0.8,
}

# Length extraction patterns
LENGTH_PATTERNS = [
    re.compile(r'(\d+)\s*(?:1/2|\.5)\s*(?:inch|in(?:ch)?|")', re.IGNORECASE),
    re.compile(r'(\d+)\s*(?:inch|in(?:ch)?|")', re.IGNORECASE),
]


def estimate_chain_weight(title: str) -> tuple:
    """
    Estimate weight for heavy chain types based on chain type and length.
    Returns (estimated_weight_grams, chain_type, length_inches) or (None, None, None).

    Only for gold items without stated weight. Uses conservative estimates.
    """
    title_lower = title.lower()

    # Detect chain type (check longer patterns first to avoid partial matches)
    detected_type = None
    grams_per_inch = 0
    for chain_type in sorted(HEAVY_CHAIN_TYPES.keys(), key=len, reverse=True):
        if chain_type in title_lower:
            detected_type = chain_type
            grams_per_inch = HEAVY_CHAIN_TYPES[chain_type]
            break

    if not detected_type:
        return None, None, None

    # Extract length
    length_inches = None
    for pattern in LENGTH_PATTERNS:
        match = pattern.search(title_lower)
        if match:
            length_inches = float(match.group(1))
            # Check for "1/2" in the matched text
            full_match = match.group(0)
            if '1/2' in full_match or '.5' in full_match:
                length_inches += 0.5
            break

    if not length_inches:
        # Default lengths based on item type
        if 'bracelet' in title_lower:
            length_inches = 7.5
        elif 'necklace' in title_lower or 'chain' in title_lower:
            length_inches = 20  # Conservative necklace default
        else:
            return None, None, None

    estimated_weight = grams_per_inch * length_inches
    return estimated_weight, detected_type, length_inches


# Module configuration
_config = {
    'instant_pass_keywords': [],
    'get_spot_prices': None,
}


def configure_instant_pass(
    instant_pass_keywords: list = None,
    get_spot_prices=None,
):
    """Configure the instant pass module with dependencies."""
    if instant_pass_keywords:
        _config['instant_pass_keywords'] = instant_pass_keywords
    if get_spot_prices:
        _config['get_spot_prices'] = get_spot_prices


def get_spot_prices():
    """Get spot prices from configured function."""
    if _config['get_spot_prices']:
        return _config['get_spot_prices']()
    return {}


def extract_weight_from_title(title: str, description: str = '') -> tuple:
    """
    Extract weight from title OR description if explicitly stated.
    Returns (weight_grams, source) or (None, None) if not found.

    IMPORTANT: Checks BOTH title AND description for weight!
    Many sellers put weight in description like "weighs 2.5 grams"

    ONLY extracts clearly stated weights like "2.5g", "2.5 grams", "1/2 oz"
    Does NOT estimate - that's for AI to do.

    Conversions:
    - ozt (troy oz) = 31.1 grams (used for precious metals)
    - oz (avoirdupois) = 28.35 grams (standard oz)
    - dwt (pennyweight) = 1.555 grams

    Uses pre-compiled patterns for performance.
    """
    # Check BOTH title and description for weight
    combined_text = f"{title} {description}".lower()

    # Check for fractional troy oz first (e.g., "1/2 ozt", "1/4 troy oz")
    frac_ozt_match = FRACTION_OZT_PATTERN.search(combined_text)
    if frac_ozt_match:
        numerator = float(frac_ozt_match.group(1))
        denominator = float(frac_ozt_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            grams = oz_value * 31.1  # Troy oz
            return grams, "stated"

    # Check for fractional plain oz (e.g., "1/2 oz", "1/4 oz")
    frac_oz_match = FRACTION_OZ_PATTERN.search(combined_text)
    if frac_oz_match:
        numerator = float(frac_oz_match.group(1))
        denominator = float(frac_oz_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            # For precious metals (silver/gold coins/bullion), use troy oz (31.1g)
            # Check for silver/gold indicators in text
            is_precious_metal = any(kw in combined_text for kw in [
                '.999', '.925', '.900', '.800', 'silver', 'gold', 'platinum',
                'bullion', 'coin', 'bar', 'round', 'eagle', 'maple', 'libertad',
                'krugerrand', 'philharmonic', 'britannia', 'panda', 'kookaburra',
                'lunar', 'koala', 'kangaroo', 'buffalo', 'proof'
            ])
            if is_precious_metal:
                grams = oz_value * 31.1  # Troy oz for precious metals
            else:
                grams = oz_value * 28.35  # Avoirdupois oz for non-precious
            return grams, "stated"

    # Use pre-compiled patterns (ordered by specificity)
    for pattern in WEIGHT_PATTERNS:
        match = pattern.search(combined_text)
        if match:
            raw_weight = float(match.group(1))
            matched_text = match.group(0).lower()

            # YEAR CHECK: Reject numbers that look like years (1900-2030)
            # These are often in titles like "1997 NFC Champions" and shouldn't be weights
            if int(raw_weight) in YEAR_RANGE and raw_weight == int(raw_weight):
                logger.debug(f"[WEIGHT] Skipping year-like number: {int(raw_weight)}")
                continue  # Try next pattern

            weight = raw_weight

            # Convert to grams based on the MATCHED unit
            if 'dwt' in matched_text:
                weight *= 1.555  # pennyweight to grams
            elif 'ozt' in matched_text or 'oz.t' in matched_text or 'troy' in matched_text:
                weight *= 31.1  # troy oz to grams
            elif 'oz' in matched_text:
                weight *= 28.35  # avoirdupois oz to grams
            # 'g', 'gram', 'grams', 'gr' are already in grams

            return weight, "stated"

    return None, None


async def extract_with_ollama(title: str, description: str = "") -> Tuple[Optional[float], Optional[int]]:
    """
    Use Ollama local LLM to extract weight and karat when regex fails.

    Returns (weight_grams, karat) or (None, None) on failure.
    Takes ~200-400ms on RTX 2070.
    """
    ollama = _get_ollama()
    if not ollama or not ollama['is_available']():
        return None, None

    try:
        result = await ollama['extract'](title, description)
        if result:
            weight = result.get('weight_grams')
            karat = result.get('karat')
            if weight or karat:
                logger.info(f"[OLLAMA] Extracted: weight={weight}g, karat={karat}K")
                return weight, karat
    except Exception as e:
        logger.debug(f"[OLLAMA] Extraction error: {e}")

    return None, None


def extract_karat_from_title(title: str) -> int:

    """

    Extract karat from title. Returns karat number or None.

    Uses pre-compiled KARAT_PATTERNS for performance.

    """

    title_lower = title.lower()

    # Use pre-compiled patterns

    for pattern, karat in KARAT_PATTERNS:

        if pattern.search(title_lower):

            return karat

    return None

def check_instant_pass(title: str, price: any, category: str, data: dict) -> tuple:

    """

    Check if listing should be instantly passed without AI analysis.

    Returns:

        (reason, "PASS") if instant pass

        None if AI analysis needed

    """

    # Normalize title - handle URL encoding from different sources
    # uBuyFirst may send URL-encoded titles with + or %20 for spaces
    from urllib.parse import unquote
    title_normalized = title.replace('+', ' ')
    if '%' in title_normalized:
        try:
            title_normalized = unquote(title_normalized)
        except:
            pass
    title_lower = title_normalized.lower()

    try:

        price_float = float(str(price).replace('$', '').replace(',', ''))

    except:

        price_float = 0

    # ============================================================
    # HIGH-VALUE PATTERN EXCEPTIONS (Skip adaptive rules for known winners)
    # These patterns have proven historical win rates and should go to agent quick_pass
    # ============================================================
    skip_adaptive = False
    if category == 'costume':
        # Jelly Belly: 75% win rate, 228% avg ROI
        if 'jelly belly' in title_lower:
            skip_adaptive = True
            logger.info(f"[HIGH-VALUE] Jelly Belly detected - skipping adaptive rules")
        # Crown Trifari: 78% win rate
        elif 'crown' in title_lower and 'trifari' in title_lower:
            skip_adaptive = True
            logger.info(f"[HIGH-VALUE] Crown Trifari detected - skipping adaptive rules")
        # Alfred Philippe: 309% avg ROI
        elif 'philippe' in title_lower or 'phillipe' in title_lower:
            skip_adaptive = True
            logger.info(f"[HIGH-VALUE] Alfred Philippe detected - skipping adaptive rules")

    elif category == 'watch':
        # Premium watches for repair: 89-100% win rate, 324-377% avg ROI
        premium_watch_brands = ['rolex', 'omega', 'patek', 'cartier', 'breitling', 'iwc',
                               'tudor', 'longines', 'hamilton', 'bulova', 'lecoultre',
                               'jaeger', 'audemars', 'vacheron', 'zenith', 'tag heuer']
        is_premium_watch = any(b in title_lower for b in premium_watch_brands)
        is_for_repair = any(kw in title_lower for kw in ['for parts', 'for repair', 'needs repair', 'as is'])

        if is_premium_watch and is_for_repair:
            skip_adaptive = True
            logger.info(f"[HIGH-VALUE] Premium watch for repair detected - skipping adaptive rules")

    elif category == 'silver':
        # Taxco/Mexico silver: 86-100% win rate
        if 'taxco' in title_lower or 'mexico' in title_lower:
            skip_adaptive = True
            logger.info(f"[HIGH-VALUE] Taxco/Mexico silver detected - skipping adaptive rules")

    # ============================================================
    # ADAPTIVE RULES (Learned from Tier2 corrections + Historical data)
    # ============================================================
    if not skip_adaptive:
        try:
            from utils.adaptive_rules import check_learned_pattern, check_historical_pass, get_buy_boost

            # Check historical losers first (high confidence from real transactions)
            historical_result = check_historical_pass(title_normalized, price_float)
            if historical_result and historical_result.get("action") == "PASS":
                logger.info(f"[HISTORICAL] PASS - {historical_result.get('reason', 'historical loser')}")
                return (historical_result.get("reason", "Historical loser pattern"), "PASS")

            # Check learned patterns from training overrides
            adaptive_result = check_learned_pattern(title_normalized, category, price_float)
            if adaptive_result and adaptive_result.get("action") == "PASS":
                logger.info(f"[ADAPTIVE] PASS - {adaptive_result.get('reason', 'learned pattern')}")
                return (adaptive_result.get("reason", "Adaptive rule match"), "PASS")

            # Store buy boost for later use by AI
            buy_boost = get_buy_boost(title_normalized, category, price_float)
            if buy_boost:
                if '_adaptive' not in data:
                    data['_adaptive'] = {}
                data['_adaptive']['buy_boost'] = buy_boost.get('confidence_boost', 0)
                data['_adaptive']['boost_reason'] = buy_boost.get('reason', '')
                logger.info(f"[ADAPTIVE] BUY BOOST +{buy_boost.get('confidence_boost', 0)} - {buy_boost.get('reason', '')}")
        except Exception as e:
            logger.debug(f"[ADAPTIVE] Check failed: {e}")

    # ============================================================
    # CATEGORY-BASED INSTANT PASS (Filter noise from broad searches)
    # ============================================================
    category_name = str(data.get('CategoryName', '')).lower().replace('+', ' ')

    # Fashion Jewelry - NOT real precious metal, instant PASS
    # BUT: If title mentions karat markings, seller may have miscategorized real gold
    if 'fashion jewelry' in category_name or 'fashion+jewelry' in category_name.replace(' ', '+'):
        karat_patterns = ['10k', '14k', '18k', '24k', '22k', '9k', '8k', '417', '585', '750', '916', '375']
        has_karat_marking = any(k in title_lower for k in karat_patterns)
        if has_karat_marking:
            logger.info(f"[INSTANT] Fashion Jewelry BUT title has karat marking - sending to AI")
            # Don't instant pass - let AI analyze
        else:
            logger.info(f"[INSTANT] PASS - Fashion Jewelry category (not precious metal)")
            return ("Fashion Jewelry category - not real precious metal", "PASS")

    # Non-jewelry categories that slip through
    noise_categories = ['tapestries', 'tapestry', 'toys', 'educational', 'rugs', 'linens', 'textiles',
                        'display stands', 'jewelry boxes', 'storage', 'craft supplies', 'beads']
    for noise in noise_categories:
        if noise in category_name:
            logger.info(f"[INSTANT] PASS - Non-jewelry category: {noise}")
            return (f"Non-jewelry category ({noise})", "PASS")

    # ============================================================
    # BRAND-BASED INSTANT PASS (Overpriced relative to melt)
    # ============================================================
    # Pandora - branded silver, always priced way above melt
    if 'pandora' in title_lower:
        logger.info(f"[INSTANT] PASS - Pandora branded item (priced for brand, not melt)")
        return ("Pandora branded item - priced for brand, not silver melt", "PASS")

    # Gucci/designer costume jewelry - usually plated, not solid
    gucci_costume_brands = ['gucci', 'louis vuitton', 'chanel', 'prada', 'hermes', 'dior', 'givenchy', 'ysl', 'versace', 'fendi', 'balenciaga', 'monet', 'napier', 'sarah coventry', 'lisner', 'coro']
    metal_purity = str(data.get('MetalPurity', '')).lower()
    for brand in gucci_costume_brands:
        if brand in title_lower:
            # Only pass if no verified metal purity (14k, 18k, etc.)
            if not any(k in metal_purity for k in ['14k', '18k', '10k', '750', '585', '417']):
                logger.info(f"[INSTANT] PASS - {brand.title()} without verified gold purity (likely plated)")
                return (f"{brand.title()} without verified metal purity - likely plated", "PASS")

    # Stainless steel - no melt value (but EXCLUDE watches - they have collectible value)
    if 'stainless steel' in title_lower or 'stainless' in title_lower:
        # Don't instant-pass stainless steel WATCHES - value is collectible, not metal
        if 'watch' not in title_lower:
            logger.info(f"[INSTANT] PASS - Stainless steel item (no precious metal)")
            return ("Stainless steel - no precious metal content", "PASS")
        else:
            logger.info(f"[INSTANT] Stainless steel WATCH - skipping metal check, value is collectible")

    # ============================================================
    # COIN NOISE FILTERS
    # ============================================================
    # Pokemon coins - not real coins!
    if 'pokemon' in title_lower and 'coin' in title_lower:
        logger.info(f"[INSTANT] PASS - Pokemon coin (not real precious metal)")
        return ("Pokemon coin - not real precious metal", "PASS")

    # Challenge coins, casino tokens - no precious metal
    challenge_coin_keywords = ['challenge coin', 'casino token', 'casino chip', 'poker chip',
                               'commemorative coin', 'novelty coin', 'souvenir coin', 'fantasy coin']
    for kw in challenge_coin_keywords:
        if kw in title_lower:
            logger.info(f"[INSTANT] PASS - {kw} (not precious metal)")
            return (f"{kw} - not precious metal", "PASS")

    # Coin holders/albums/cases - not actual coins
    coin_accessories = ['coin holder', 'coin album', 'coin case', 'coin display', 'coin folder',
                        'coin storage', 'coin tube', 'coin capsule', 'coin slab']
    for acc in coin_accessories:
        if acc in title_lower:
            logger.info(f"[INSTANT] PASS - {acc} (accessory, not coin)")
            return (f"{acc} - accessory, not actual coin", "PASS")

    # Graded modern bullion at high premiums (NGC/PCGS MS69/MS70)
    # These have collector premiums way above melt
    if ('ngc' in title_lower or 'pcgs' in title_lower) and ('ms69' in title_lower or 'ms70' in title_lower):
        if price_float > 100:  # Only filter high-priced graded coins
            logger.info(f"[INSTANT] PASS - Graded bullion MS69/MS70 @ ${price_float:.0f} (collector premium)")
            return (f"Graded bullion MS69/MS70 @ ${price_float:.0f} - collector premium above melt", "PASS")

    # Junk drawer / mystery lots with coins mentioned
    junk_lot_keywords = ['junk drawer', 'mystery lot', 'grab bag', 'estate lot', 'grandma']
    if 'coin' in title_lower:
        for junk in junk_lot_keywords:
            if junk in title_lower:
                logger.info(f"[INSTANT] PASS - {junk} with coins (unpredictable content)")
                return (f"{junk} with coins - unpredictable content", "PASS")

    # ============================================================

    # KEYWORD-BASED INSTANT PASS (All categories)
    # Skip for high-value patterns that have proven win rates

    # ============================================================

    if not skip_adaptive:
        for keyword in _config['instant_pass_keywords']:

            if keyword in title_lower:

                return (f"Title contains '{keyword}'", "PASS")

    # ============================================================
    # HISTORICAL LOSERS - Patterns with poor performance
    # ============================================================

    # James Avery - Historical 25% win rate, -20% avg ROI
    # Collectors pay retail, not wholesale - overpriced for melt
    if 'james avery' in title_lower and price_float > 100:
        logger.info(f"[INSTANT] PASS - James Avery @ ${price_float:.0f} (historical 25% win rate)")
        return (f"JAMES AVERY at ${price_float:.0f} - Historical 25% win rate, -20% ROI. Overpriced for melt.", "PASS")

    # Dead Pawn at high prices - Historical major losses
    if 'dead pawn' in title_lower and price_float > 250:
        logger.info(f"[INSTANT] PASS - Dead Pawn @ ${price_float:.0f} (historical losers)")
        return (f"DEAD PAWN at ${price_float:.0f} - High-priced dead pawn often overvalued. Historical losses.", "PASS")

    # Large sterling lots (200-500g) - Historical 25% win rate
    # Heavy lots are often overvalued or have hidden plated items
    if category == 'silver':
        weight_match = re.search(r'(\d+)\s*(?:gram|grams|g)\b', title_lower)
        if weight_match:
            weight = int(weight_match.group(1))
            if 200 <= weight <= 600 and 'lot' in title_lower and price_float > 200:
                logger.info(f"[INSTANT] PASS - Large sterling lot {weight}g @ ${price_float:.0f}")
                return (f"LARGE STERLING LOT: {weight}g at ${price_float:.0f} - Historical 25% win rate on 200-500g lots. Often overvalued.", "PASS")

    # ============================================================
    # DIAMOND/STONE JEWELRY FILTERS (Gold category)
    # Items priced for stone value, not gold melt value
    # Based on learning_patterns PASS data analysis
    # ============================================================
    if category == 'gold':
        has_diamond = 'diamond' in title_lower
        has_wedding_band = 'wedding band' in title_lower or 'wedding ring' in title_lower
        has_engagement = 'engagement' in title_lower

        # 1. Diamond Wedding Bands > $500 - Always priced for stone value
        if has_diamond and has_wedding_band and price_float > 500:
            logger.info(f"[INSTANT] PASS - Diamond wedding band @ ${price_float:.0f} (stone-priced)")
            return (f"Diamond wedding band @ ${price_float:.0f} - priced for stones, not gold melt", "PASS")

        # 2. Diamond Engagement Rings > $300 - Stone value dominates
        if has_diamond and has_engagement and price_float > 300:
            logger.info(f"[INSTANT] PASS - Diamond engagement ring @ ${price_float:.0f} (stone-priced)")
            return (f"Diamond engagement ring @ ${price_float:.0f} - priced for stones, not gold melt", "PASS")

        # 5. Designer Names - Priced for brand, not melt
        designer_brands = [
            'van cleef', 'cartier', 'tiffany', 'john hardy', 'bvlgari', 'bulgari',
            'david yurman', 'roberto coin', 'chopard', 'buccellati', 'harry winston',
            'graff', 'piaget', 'pomellato', 'marco bicego'
        ]
        for brand in designer_brands:
            if brand in title_lower:
                logger.info(f"[INSTANT] PASS - Designer brand '{brand}' @ ${price_float:.0f}")
                return (f"Designer jewelry ({brand}) - priced for brand, not gold melt", "PASS")

        # 6. High-price diamond items > $2000 - Definitely stone-priced
        if has_diamond and price_float > 2000:
            logger.info(f"[INSTANT] PASS - High-price diamond jewelry @ ${price_float:.0f}")
            return (f"Diamond jewelry @ ${price_float:.0f} - price indicates stone value, not gold melt", "PASS")

        # 7. Lab-created stones - No melt value in the stones, and items priced for stone appearance
        if 'lab created' in title_lower or 'lab-created' in title_lower:
            logger.info(f"[INSTANT] PASS - Lab-created stones @ ${price_float:.0f}")
            return (f"Lab-created stones - priced for stone appearance, not gold melt", "PASS")

    # ============================================================
    # WEIGHTED STERLING CHECK (Title + Description)
    # "Sterling weighted" = cement/pitch filled, use 15% of stated weight
    # NOT an instant pass - AI will calculate with reduced weight
    # ============================================================
    if category == 'silver':
        description = str(data.get('description', '')).lower()
        combined_text = f"{title_lower} {description}"

        # Check for weighted indicators - just log, don't pass
        # AI prompt tells it to calculate at 15% of stated weight for weighted items
        if 'sterling weighted' in combined_text or 'weighted sterling' in combined_text:
            logger.info(f"[WEIGHTED] Sterling weighted detected - AI will calculate at 15% weight")

        if 'weighted' in description and 'weighted' not in title_lower:
            logger.info(f"[WEIGHTED] Description says weighted - AI will calculate at 15% weight")

        # Candlesticks are ALWAYS weighted unless explicitly solid
        if ('candlestick' in title_lower or 'candelabra' in title_lower) and 'solid' not in combined_text:
            logger.info(f"[WEIGHTED] Candlestick detected - AI will apply weighted reduction")

    # ============================================================
    # STERLING HANDLE CHECK (pie servers, cake servers, etc.)
    # "Sterling Handle" = only the handle is silver, blade is stainless
    # Each handle ~15g of silver
    # ============================================================
    if category == 'silver':
        from utils.extraction import detect_sterling_handle
        is_handle, handle_qty, handle_max_silver = detect_sterling_handle(title)
        if is_handle and handle_qty > 0:
            spots = get_spot_prices()
            sterling_rate = spots.get('sterling', 2.50)
            max_melt = handle_max_silver * sterling_rate
            max_buy = max_melt * 0.70

            if price_float > max_buy:
                logger.info(f"[HANDLE] PASS - {handle_qty} sterling handles = max {handle_max_silver}g silver = ${max_melt:.0f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f}")
                return (f"STERLING HANDLES: {handle_qty} handles = max {handle_max_silver}g silver (handles only, blades are steel). Max buy ${max_buy:.0f}, listing ${price_float:.0f}", "PASS")
            else:
                logger.info(f"[HANDLE] Potential buy - {handle_qty} handles @ ${price_float:.0f}, max silver {handle_max_silver}g = ${max_buy:.0f} max buy")

    # ============================================================
    # FLATWARE KNIVES CHECK
    # Sterling flatware knives have STAINLESS STEEL BLADES!
    # Only the hollow handles contain silver (~15-20g per knife)
    # ============================================================
    if category == 'silver':
        from utils.extraction import detect_flatware_knives
        is_knife, knife_qty, knife_max_silver = detect_flatware_knives(title)
        if is_knife and knife_qty > 0:
            # Calculate max value based on actual silver content
            spots = get_spot_prices()
            sterling_rate = spots.get('sterling', 2.50)
            max_melt = knife_max_silver * sterling_rate
            max_buy = max_melt * 0.70  # 70% of melt for silver

            if price_float > max_buy:
                margin = max_buy - price_float
                logger.info(f"[KNIFE] PASS - {knife_qty} knives = max {knife_max_silver}g silver = ${max_melt:.0f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f}")
                return (f"STERLING KNIVES: {knife_qty} knives = max {knife_max_silver}g silver (handles only, blades are steel). Max buy ${max_buy:.0f}, listing ${price_float:.0f}", "PASS")
            else:
                logger.info(f"[KNIFE] Potential buy - {knife_qty} knives @ ${price_float:.0f}, max silver {knife_max_silver}g = ${max_buy:.0f} max buy")
                # Continue to AI for verification

    # ============================================================
    # FLATWARE WEIGHT ESTIMATION (forks, spoons, etc.)
    # If no weight in title, estimate based on piece type
    # ============================================================
    if category == 'silver':
        from utils.extraction import detect_flatware, extract_weight_from_title as extract_weight_title

        # Only estimate if NO weight stated in title
        stated_weight_check = extract_weight_title(title)
        if not stated_weight_check:
            is_flatware, piece_type, flat_qty, estimated_weight = detect_flatware(title)
            if is_flatware and estimated_weight > 0:
                # Calculate melt value based on estimated weight
                spots = get_spot_prices()
                sterling_rate = spots.get('sterling', 2.50)
                est_melt = estimated_weight * sterling_rate
                max_buy_est = est_melt * 0.70  # 70% of melt for silver

                profit_est = max_buy_est - price_float
                margin_pct = (profit_est / price_float * 100) if price_float > 0 else 0

                if price_float > max_buy_est * 1.3:
                    # More than 30% over max buy - instant PASS
                    logger.info(f"[FLATWARE] PASS - {flat_qty}x {piece_type} = est {estimated_weight:.0f}g = ${est_melt:.0f} melt, max ${max_buy_est:.0f}, listing ${price_float:.0f}")
                    return (f"STERLING FLATWARE: {flat_qty}x {piece_type} = est {estimated_weight:.0f}g. Max buy ${max_buy_est:.0f}, listing ${price_float:.0f}. Weight is ESTIMATED - verify before buying.", "PASS")
                elif profit_est > 0:
                    # Potential profit - continue to AI for verification
                    logger.info(f"[FLATWARE] Potential BUY - {flat_qty}x {piece_type} = est {estimated_weight:.0f}g, est profit ${profit_est:.0f} ({margin_pct:.0f}%)")
                    # Pass the estimated weight to AI context (will be handled in prompt/analysis)
                else:
                    # Marginal/break-even - let AI decide
                    logger.info(f"[FLATWARE] RESEARCH - {flat_qty}x {piece_type} = est {estimated_weight:.0f}g, listing near max buy")

    # ============================================================

    # GOLD/SILVER: Price vs Stated Weight Check

    # Only if weight is EXPLICITLY STATED in title

    # SKIP if item likely has non-metal weight (stones, pearls, etc.)

    # ============================================================

    if category in ['gold', 'silver']:
        # Combine all description fields - weight might be in ConditionDescription
        combined_desc = ' '.join(filter(None, [
            data.get('description', ''),
            data.get('Description', ''),
            data.get('ConditionDescription', ''),
        ]))
        stated_weight, weight_source = extract_weight_from_title(title, combined_desc)

        if stated_weight and weight_source == "stated":

            # CRITICAL: Skip instant pass for items where stated weight includes non-metal

            # These need AI analysis to properly deduct stone/pearl/component weight

            non_metal_indicators = [

                'pearl', 'diamond', 'stone', 'turquoise', 'jade', 'coral', 'opal',

                'amethyst', 'ruby', 'sapphire', 'emerald', 'garnet', 'onyx', 'topaz',

                'jasper', 'agate', 'quartz', 'lapis', 'malachite', 'carnelian', 'obsidian',  # Semi-precious stones

                'carved',  # "Carved" anything = substantial stone weight

                'watch', 'movement', 'crystal',  # Watches have movement weight

                'cord', 'leather', 'silk', 'rubber', 'fabric',  # Cord necklaces

                'murano', 'glass', 'millefiori',  # Glass pendants

                'bead', 'beaded',  # Beaded jewelry is mostly beads

                'gemstone', 'gem', 'cttw', 'ctw',  # Gemstone indicators

                'cameo',  # Cameos are shell/coral/stone - deduct 3-5g for typical cameo

            ]

            has_non_metal = any(indicator in title_lower for indicator in non_metal_indicators)

            if has_non_metal:

                # Don't instant pass - let AI analyze and deduct properly

                logger.info(f"[INSTANT] Skipping weight check - title contains non-metal indicators: {title[:60]}...")

            else:

                spots = get_spot_prices()

                if category == 'gold':

                    karat = extract_karat_from_title(title)

                    if karat:

                        # Get rate for this karat

                        karat_key = f"{karat}K"

                        rate = spots.get(karat_key, spots.get('14K', 50))

                        melt_value = stated_weight * rate

                        max_buy = melt_value * 0.95  # 95% of melt

                        # If listing price > 95% of melt, check for best offer before instant PASS

                        if price_float > max_buy:

                            margin = max_buy - price_float

                            gap_percent = ((price_float - max_buy) / price_float) * 100 if price_float > 0 else 100

                            accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']

                            # If best offer available and within 10%, let AI analyze so we can suggest offer

                            if accepts_offers and gap_percent <= 10:

                                logger.info(f"[INSTANT] Skipping PASS - has best offer, gap only {gap_percent:.1f}%: {stated_weight}g {karat}K @ ${price_float:.0f}")

                                # Don't return - let AI process and best offer logic handle it

                            else:

                                logger.info(f"[INSTANT] PASS - overpriced: {stated_weight}g {karat}K @ ${price_float:.0f}")

                                return (f"OVERPRICED: {stated_weight}g {karat}K = ${melt_value:.0f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f} = ${margin:.0f} loss", "PASS", {
                                    "karat": f"{karat}K", "weight": str(stated_weight),
                                    "goldweight": str(stated_weight), "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)), "sellPrice": str(int(melt_value * 0.96)),
                                    "listingPrice": str(int(price_float)), "Profit": str(int(margin)),
                                })

                        # Check if margin is strong enough for instant BUY
                        margin = max_buy - price_float
                        margin_pct = (margin / price_float * 100) if price_float > 0 else 0

                        # === GOLD WATCH PENALTY (Historical data: -24% ROI) ===
                        # Gold watches should NEVER instant BUY - too many are gold-filled mislabeled as solid
                        if 'watch' in title_lower and margin_pct >= 30:
                            logger.info(f"[INSTANT] GOLD WATCH - blocking instant BUY, needs manual verification")
                            return (
                                f"GOLD WATCH - Historical data shows -24% ROI on gold watches. {stated_weight}g {karat}K = ${melt_value:.0f} melt, but needs manual verification (gold-filled risk).",
                                "RESEARCH",
                                {
                                    "karat": f"{karat}K",
                                    "weight": str(stated_weight),
                                    "goldweight": str(stated_weight),
                                    "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)),
                                    "sellPrice": str(int(melt_value * 0.96)),
                                    "listingPrice": str(int(price_float)),
                                    "Profit": f"+{int(margin)}",
                                    "confidence": 60,
                                    "weightSource": "stated",
                                    "verified": "needs-manual",
                                    "instantBuy": False,
                                    "goldWatchPenalty": True,
                                }
                            )

                        if margin_pct >= 30 and margin >= 20:
                            # Strong margin on stated weight - instant BUY
                            logger.info(f"[INSTANT BUY] Gold: {stated_weight}g {karat}K = ${melt_value:.0f} melt, listing ${price_float:.0f}, margin +${margin:.0f} ({margin_pct:.0f}%)")
                            return (
                                f"INSTANT BUY: {stated_weight}g {karat}K = ${melt_value:.0f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f} = +${margin:.0f} ({margin_pct:.0f}%)",
                                "BUY",
                                {
                                    "karat": f"{karat}K",
                                    "weight": str(stated_weight),
                                    "goldweight": str(stated_weight),
                                    "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)),
                                    "sellPrice": str(int(melt_value * 0.96)),
                                    "listingPrice": str(int(price_float)),
                                    "Profit": f"+{int(margin)}",
                                    "Margin": f"+{int(margin)}",
                                    "confidence": 90,
                                    "weightSource": "stated",
                                    "verified": "rule-based-instant",
                                    "instantBuy": True,
                                }
                            )

                        # Margin exists but not strong enough for instant BUY - let AI verify
                        logger.info(f"[INSTANT] Weight check OK: {stated_weight}g {karat}K @ ${price_float:.0f} - margin ${margin:.0f} ({margin_pct:.0f}%) - needs AI verification")

                elif category == 'silver':

                    # Sterling silver

                    rate = spots.get('sterling', 0.89)

                    # WEIGHTED STERLING: Only ~15% of total weight is actual silver
                    # (rest is cement/plaster/plite filler in base)
                    weighted_keywords = ['weighted', 'reinforced', 'filled base', 'cement filled',
                                        'weighted base', 'loaded', 'pedestal', 'candlestick',
                                        'candelabra', 'compote']
                    is_weighted = any(kw in title_lower for kw in weighted_keywords)

                    if is_weighted:
                        actual_silver_weight = stated_weight * 0.15  # Only 15% is silver
                        melt_value = actual_silver_weight * rate
                        logger.info(f"[WEIGHTED] Adjusted: {stated_weight}g total -> {actual_silver_weight:.1f}g actual silver")
                    else:
                        melt_value = stated_weight * rate

                    max_buy = melt_value * 0.70  # 70% of melt for silver

                    # Check for Native American jewelry (gets looser restrictions)

                    native_keywords = ['navajo', 'native american', 'zuni', 'hopi', 'squash blossom',

                                      'southwestern', 'turquoise', 'concho', 'old pawn']

                    is_native = any(kw in title_lower for kw in native_keywords)

                    if price_float > max_buy:

                        margin = max_buy - price_float

                        gap_percent = ((price_float - max_buy) / price_float) * 100 if price_float > 0 else 100

                        accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']

                        # Native American: allow 20% gap (collector value)

                        # Regular with best offer: allow 10% gap

                        max_gap = 20 if is_native else 10

                        if (accepts_offers or is_native) and gap_percent <= max_gap:

                            if is_native:

                                logger.info(f"[INSTANT] Skipping PASS - Native American jewelry, gap {gap_percent:.1f}%: {stated_weight}g @ ${price_float:.0f}")

                            else:

                                logger.info(f"[INSTANT] Skipping PASS - has best offer, gap only {gap_percent:.1f}%: {stated_weight}g @ ${price_float:.0f}")

                            # Don't return - let AI process

                        else:

                            if is_weighted:
                                logger.info(f"[INSTANT] PASS - weighted silver overpriced: {stated_weight}g total ({actual_silver_weight:.1f}g silver) @ ${price_float:.0f}")
                                return (f"OVERPRICED WEIGHTED: {stated_weight}g total = ~{actual_silver_weight:.0f}g silver = ${melt_value:.2f} melt, listing ${price_float:.0f} = loss", "PASS", {
                                    "karat": "925", "weight": str(stated_weight),
                                    "silverweight": f"{actual_silver_weight:.1f}",
                                    "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)), "sellPrice": str(int(melt_value * 0.82)),
                                    "listingPrice": str(int(price_float)), "Profit": str(int(max_buy - price_float)),
                                    "itemtype": "Weighted Sterling (15%)",
                                })
                            else:
                                logger.info(f"[INSTANT] PASS - silver overpriced: {stated_weight}g @ ${price_float:.0f}")
                                return (f"OVERPRICED: {stated_weight}g sterling = ${melt_value:.2f} melt, listing ${price_float:.0f} = loss", "PASS", {
                                    "karat": "925", "weight": str(stated_weight),
                                    "silverweight": str(stated_weight), "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)), "sellPrice": str(int(melt_value * 0.82)),
                                    "listingPrice": str(int(price_float)), "Profit": str(int(max_buy - price_float)),
                                    "itemtype": "Sterling Silver",
                                })

                    else:
                        # Price is below max_buy - check for instant BUY
                        margin = max_buy - price_float
                        margin_pct = (margin / price_float * 100) if price_float > 0 else 0

                        # Skip instant BUY for weighted items - let AI analyze
                        if is_weighted:
                            actual_silver_weight = stated_weight * 0.15
                            logger.info(f"[INSTANT] Weighted silver - letting AI analyze: {stated_weight}g total (~{actual_silver_weight:.0f}g silver) @ ${price_float:.0f}")
                            # Fall through to AI

                        # === SILVER LOT PENALTY (Historical data: -44% ROI) ===
                        # Silver lots should NEVER instant BUY - too many have plated/mixed items
                        lot_keywords = ['lot', 'mixed', 'bulk', 'assorted', 'collection']
                        is_lot = any(kw in title_lower for kw in lot_keywords)
                        if is_lot and margin_pct >= 25:
                            logger.info(f"[INSTANT] SILVER LOT - blocking instant BUY, needs manual verification")
                            return (
                                f"SILVER LOT - Historical data shows -44% ROI on silver lots. {stated_weight}g stated, but lots often have plated/mixed items. Manual verification required.",
                                "RESEARCH",
                                {
                                    "karat": "925",
                                    "weight": str(stated_weight),
                                    "silverweight": str(stated_weight),
                                    "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)),
                                    "sellPrice": str(int(melt_value * 0.82)),
                                    "listingPrice": str(int(price_float)),
                                    "Profit": f"+{int(margin)}",
                                    "confidence": 50,
                                    "weightSource": "stated",
                                    "verified": "needs-manual",
                                    "instantBuy": False,
                                    "silverLotPenalty": True,
                                }
                            )

                        elif margin_pct >= 25 and margin >= 15:
                            # Strong margin on stated weight - instant BUY
                            logger.info(f"[INSTANT BUY] Silver: {stated_weight}g sterling = ${melt_value:.0f} melt, listing ${price_float:.0f}, margin +${margin:.0f} ({margin_pct:.0f}%)")
                            return (
                                f"INSTANT BUY: {stated_weight}g sterling = ${melt_value:.2f} melt, max buy ${max_buy:.0f}, listing ${price_float:.0f} = +${margin:.0f} ({margin_pct:.0f}%)",
                                "BUY",
                                {
                                    "karat": "925",
                                    "weight": str(stated_weight),
                                    "silverweight": str(stated_weight),
                                    "meltvalue": str(int(melt_value)),
                                    "maxBuy": str(int(max_buy)),
                                    "sellPrice": str(int(melt_value * 0.82)),
                                    "listingPrice": str(int(price_float)),
                                    "Profit": f"+{int(margin)}",
                                    "Margin": f"+{int(margin)}",
                                    "confidence": 85,
                                    "weightSource": "stated",
                                    "verified": "rule-based-instant",
                                    "instantBuy": True,
                                    "itemtype": "Sterling Silver",
                                }
                            )

                        # Margin exists but not strong enough - let AI verify
                        logger.info(f"[INSTANT] Silver weight check OK: {stated_weight}g @ ${price_float:.0f} - margin ${margin:.0f} ({margin_pct:.0f}%) - needs AI verification")

    # ============================================================
    # GOLD CHAIN WEIGHT HEURISTIC (no stated weight)
    # For heavy chain types (byzantine, cuban, etc.) we can estimate weight
    # from chain type + length. Don't instant BUY (estimated), but flag as
    # is_hot to skip images and use fast model.
    # ============================================================
    if category == 'gold':
        # Combine all description fields for weight extraction
        combined_desc_gold = ' '.join(filter(None, [
            data.get('description', ''),
            data.get('Description', ''),
            data.get('ConditionDescription', ''),
        ]))
        stated_weight_check, _ = extract_weight_from_title(title, combined_desc_gold)
        if not stated_weight_check:
            karat = extract_karat_from_title(title)
            if karat:
                est_weight, chain_type, length = estimate_chain_weight(title)
                if est_weight and est_weight > 5:  # Only substantial estimates
                    spots = get_spot_prices()
                    rate = spots.get(f"{karat}K", spots.get('14K', 50))
                    est_melt = est_weight * rate
                    est_max_buy = est_melt * 0.90  # Conservative 90% for estimates
                    margin = est_max_buy - price_float
                    margin_pct = (margin / price_float * 100) if price_float > 0 else 0

                    if margin_pct >= 100:  # 2x+ estimated return = hot
                        logger.info(f"[HEURISTIC] HOT: {chain_type} ~{length}in {karat}K = est {est_weight:.0f}g, est melt ${est_melt:.0f}, listing ${price_float:.0f}, margin {margin_pct:.0f}%")
                        if '_heuristic' not in data:
                            data['_heuristic'] = {}
                        data['_heuristic']['is_hot'] = True
                        data['_heuristic']['chain_type'] = chain_type
                        data['_heuristic']['est_weight'] = est_weight
                        data['_heuristic']['est_melt'] = est_melt
                        data['_heuristic']['est_margin'] = margin
                        # Don't return - let AI verify, but orchestrator will skip images
                    elif margin_pct >= 30:
                        logger.info(f"[HEURISTIC] Promising: {chain_type} ~{length}in {karat}K = est {est_weight:.0f}g, margin {margin_pct:.0f}%")

    # ============================================================
    # CARVED STONE INSTANT PASS - "Carved [stone]" items
    # When title says "Carved Jasper", "Carved Jade", etc. the item is
    # primarily a decorative stone piece. The gold/silver is typically
    # just a small bail, bezel, or chain connector (1-5g max).
    # These ALWAYS get PASS regardless of any scale weight shown.
    # ============================================================
    if category in ['gold', 'silver']:
        carved_stone_patterns = [
            'carved jasper', 'carved jade', 'carved coral', 'carved agate',
            'carved quartz', 'carved stone', 'carved malachite', 'carved lapis',
            'carved turquoise', 'carved onyx', 'carved obsidian', 'carved carnelian',
            'jasper pendant', 'jade pendant', 'carved pendant',
        ]
        is_carved_stone = any(pattern in title_lower for pattern in carved_stone_patterns)

        if is_carved_stone:
            logger.info(f"[CARVED STONE] INSTANT PASS - Carved stone piece, metal is minimal: {title[:60]}")
            return (f"CARVED STONE: Item is primarily decorative stone (jasper, jade, etc.). Metal content is minimal (bail/bezel only). Cannot profit from melt.", "PASS")

    # ============================================================
    # SEED/BEAD JEWELRY - Mostly decorative, minimal metal
    # Huayruro, acai, kukui, etc. are decorative seeds with tiny silver links
    # ============================================================
    if category in ['silver', 'gold']:
        seed_bead_keywords = ['huayruro', 'acai seed', 'kukui nut', 'seed bead',
                              'seed bracelet', 'seed necklace', 'wooden bead',
                              'bone bead', 'horn bead', 'shell bead']
        for seed in seed_bead_keywords:
            if seed in title_lower:
                logger.info(f"[INSTANT] PASS - Seed/bead jewelry: {seed}")
                return (f"Seed/bead jewelry ({seed}) - mostly decorative material, minimal silver content", "PASS")

    # ============================================================
    # MIXED MATERIAL LOTS - Weight includes non-silver materials
    # "Lucite Sterling Metal" = weight is ALL materials combined
    # ============================================================
    if category == 'silver':
        mixed_material_keywords = ['lucite', 'plastic', 'acrylic', 'resin', 'bakelite',
                                   'wood', 'leather', 'fabric', 'cloth', 'rope']
        has_mixed = any(mat in title_lower for mat in mixed_material_keywords)
        is_lot = 'lot' in title_lower or 'lbs' in title_lower or 'pounds' in title_lower

        if has_mixed and is_lot:
            logger.info(f"[INSTANT] PASS - Mixed material lot (weight includes non-silver)")
            return ("Mixed material lot - stated weight includes lucite/plastic/etc, not just silver", "PASS")

    # ============================================================
    # ANTIQUE DECORATIVE SILVER - Priced for collectible value, not melt
    # Edwardian, Victorian, Art Nouveau buckles, accessories, etc.
    # ============================================================
    if category == 'silver':
        antique_periods = ['edwardian', 'victorian', 'art nouveau', 'georgian', 'regency']
        decorative_items = ['buckle', 'nurses buckle', 'belt buckle', 'chatelaine',
                           'card case', 'vinaigrette', 'snuff box', 'vesta case',
                           'thimble', 'needle case', 'patch box', 'pill box',
                           'reynolds', 'cherub', 'cherubs', 'repousse']

        is_antique = any(period in title_lower for period in antique_periods)
        is_decorative = any(item in title_lower for item in decorative_items)

        if is_antique and is_decorative:
            logger.info(f"[INSTANT] PASS - Antique decorative silver (collectible value)")
            return ("Antique decorative silver - priced for collectible/antique value, not melt", "PASS")

    # ============================================================
    # JADE/STONE CHECK - High non-metal value items
    # These items are valued for the stone, NOT the metal
    # Without stated weight, we can't verify metal content
    # EXCEPTION: Native American turquoise - 71% win rate even without weight
    # ============================================================
    if category in ['silver', 'gold']:
        high_nonmetal_keywords = ['jade', 'coral', 'jasper', 'lapis', 'malachite']
        # Note: Turquoise is handled separately below for Native American items
        has_high_nonmetal = any(kw in title_lower for kw in high_nonmetal_keywords)

        # Check if this is Native American turquoise (historical 71% win rate)
        is_native_turquoise = 'turquoise' in title_lower and any(
            kw in title_lower for kw in ['navajo', 'zuni', 'hopi', 'native', 'southwest', 'american indian', 'squash', 'cuff']
        )

        if has_high_nonmetal and not is_native_turquoise:
            # Combine all description fields for weight extraction
            combined_desc_stone = ' '.join(filter(None, [
                data.get('description', ''),
                data.get('Description', ''),
                data.get('ConditionDescription', ''),
            ]))
            stated_weight, _ = extract_weight_from_title(title, combined_desc_stone)
            if not stated_weight:
                logger.info(f"[JADE/STONE] PASS - High non-metal value item without stated weight: {title[:60]}")
                return (f"JADE/CARVED STONE: Item valued for stone, not metal. No weight stated - cannot verify metal content.", "PASS")

        # Native American turquoise without weight -> RESEARCH (not PASS)
        # Historical data: 71% win rate, value is in craftsmanship + turquoise
        if is_native_turquoise:
            combined_desc_stone = ' '.join(filter(None, [
                data.get('description', ''),
                data.get('Description', ''),
                data.get('ConditionDescription', ''),
            ]))
            stated_weight, _ = extract_weight_from_title(title, combined_desc_stone)
            if not stated_weight and price_float < 200:
                logger.info(f"[NATIVE TURQUOISE] RESEARCH - No weight but historical 71% win rate: {title[:60]}")
                return (f"NATIVE TURQUOISE: No weight stated, but historical data shows 71% win rate on Native American turquoise. Worth researching.", "RESEARCH")

    # ============================================================
    # WATCH CATEGORY FILTERS
    # Strategy: Only buy vintage, parts, lots at good prices
    # PASS on: market-priced working luxury watches, new watches, smartwatches
    # ============================================================
    if category == 'watch':
        # Smartwatches and fitness trackers - no arbitrage value
        smartwatch_keywords = ['smartwatch', 'smart watch', 'apple watch', 'galaxy watch',
                               'fitbit', 'garmin', 'fitness tracker', 'activity tracker',
                               'samsung watch', 'google watch', 'pixel watch', 'amazfit']
        for kw in smartwatch_keywords:
            if kw in title_lower:
                logger.info(f"[WATCH] PASS - Smartwatch/fitness tracker: {kw}")
                return (f"Smartwatch/fitness tracker ({kw}) - no arbitrage value", "PASS")

        # Fashion watches with no resale value
        fashion_watch_brands = ['michael kors', 'kate spade', 'fossil', 'guess', 'nixon',
                                'invicta', 'stuhrling', 'akribos', 'geneva', 'anne klein',
                                'betsey johnson', 'coach watch', 'marc jacobs', 'dkny',
                                'armani exchange', 'diesel watch', 'skagen']
        for brand in fashion_watch_brands:
            if brand in title_lower:
                logger.info(f"[WATCH] PASS - Fashion watch brand: {brand}")
                return (f"Fashion watch brand ({brand}) - no resale value", "PASS")

        # Working luxury watches at HIGH prices = market-priced, no arbitrage
        # Only PASS if clearly working AND high-priced
        luxury_brands = ['rolex', 'omega', 'breitling', 'cartier', 'patek', 'audemars',
                         'vacheron', 'jaeger', 'iwc', 'panerai', 'hublot', 'tag heuer']
        is_luxury = any(brand in title_lower for brand in luxury_brands)

        # Signs of non-working/parts/project (GOOD - we want these)
        parts_keywords = ['parts', 'repair', 'not working', 'broken', 'as is', 'for parts',
                          'needs work', 'project', 'doesn\'t run', 'won\'t run', 'spares',
                          'movement only', 'case only', 'dial only', 'band only']
        is_parts = any(kw in title_lower for kw in parts_keywords)

        # Signs of lot/estate (GOOD - we want these)
        lot_keywords = ['lot', 'collection', 'estate', 'vintage lot', 'watch lot', 'watchmaker']
        is_lot = any(kw in title_lower for kw in lot_keywords)

        if is_luxury and not is_parts and not is_lot:
            # Working luxury watch - check price
            if price_float > 2000:
                logger.info(f"[WATCH] PASS - Working luxury watch @ ${price_float:.0f} (market-priced)")
                return (f"Working luxury watch @ ${price_float:.0f} - market-priced, no arbitrage", "PASS")

        # New condition watches - always market-priced
        condition = str(data.get('Condition', data.get('condition', ''))).lower()
        if condition in ['new', 'new with tags', 'new without tags', 'new with box']:
            if price_float > 200:  # Allow cheap new watches through for analysis
                logger.info(f"[WATCH] PASS - New condition watch @ ${price_float:.0f}")
                return (f"New condition watch @ ${price_float:.0f} - market-priced", "PASS")

    # ============================================================

    # PRICE SANITY CHECK

    # ============================================================

    # Ultra-high prices unlikely to be arbitrage opportunities

    if price_float > 10000 and category in ['gold', 'silver']:

        return (f"Price ${price_float:.0f} too high for arbitrage", "PASS")

    # No instant pass - needs AI analysis

    return None