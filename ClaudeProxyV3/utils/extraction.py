"""
Extraction Utilities

Functions for extracting weight, karat, and other data from listing titles and descriptions.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
# Note: ozt (troy oz) = 31.1g, oz (avoirdupois) = 28.35g
# Pattern (\d*\.?\d+) handles both "0.8" and ".8" formats
WEIGHT_PATTERNS = [
    re.compile(r'(\d*\.?\d+)\s*(?:gram|grams|gr)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*g\b', re.IGNORECASE),  # Handles .8g, 0.8g, 8g
    re.compile(r'(\d*\.?\d+)\s*(?:dwt|DWT)\b', re.IGNORECASE),
    re.compile(r'(\d*\.?\d+)\s*(?:ozt|oz\.t|troy\s*oz)\b', re.IGNORECASE),  # Troy oz = 31.1g
    re.compile(r'(\d*\.?\d+)\s*oz\b', re.IGNORECASE),  # Plain oz = 28.35g (avoirdupois)
]

# Fractional oz patterns (e.g., "3/4 oz", "1/2 oz", "1/10 oz", "1/10 ounce")
FRACTION_OZT_PATTERN = re.compile(r'(\d+)/(\d+)\s*(?:ozt|oz\.t|troy\s*oz|troy\s*ounce)\b', re.IGNORECASE)  # Troy
FRACTION_OZ_PATTERN = re.compile(r'(\d+)/(\d+)\s*(?:oz|ounces?)\b', re.IGNORECASE)  # Plain oz/ounce

KARAT_PATTERNS = [
    (re.compile(r'\b24\s*k(?:t|arat)?\b', re.IGNORECASE), 24),
    (re.compile(r'\b22\s*k(?:t|arat)?\b', re.IGNORECASE), 22),
    (re.compile(r'\b18\s*k(?:t|arat)?\b', re.IGNORECASE), 18),
    (re.compile(r'\b14\s*k(?:t|arat)?\b', re.IGNORECASE), 14),
    (re.compile(r'\b10\s*k(?:t|arat)?\b', re.IGNORECASE), 10),
    (re.compile(r'\b9\s*k(?:t|arat)?\b', re.IGNORECASE), 9),
    (re.compile(r'\b999\b'), 24),
    (re.compile(r'\b916\b'), 22),
    (re.compile(r'\b750\b'), 18),
    (re.compile(r'\b585\b'), 14),
    (re.compile(r'\b417\b'), 10),
    (re.compile(r'\b375\b'), 9),
]

SILVER_PATTERNS = [
    (re.compile(r'\.?999\b'), 0.999),  # Pure silver (bullion, coins)
    (re.compile(r'\.?925\b'), 0.925),
    (re.compile(r'sterling', re.IGNORECASE), 0.925),
    (re.compile(r'\.?900\b'), 0.900),
    (re.compile(r'\.?800\b'), 0.800),
    (re.compile(r'coin\s*silver', re.IGNORECASE), 0.900),
    (re.compile(r'pure\s*silver', re.IGNORECASE), 0.999),  # "Pure Silver" = .999
    (re.compile(r'fine\s*silver', re.IGNORECASE), 0.999),  # "Fine Silver" = .999
    (re.compile(r'silver\s*proof', re.IGNORECASE), 0.999),  # Proof coins are .999
    (re.compile(r'silver\s*bullion', re.IGNORECASE), 0.999),  # Bullion = .999
    (re.compile(r'silver\s*eagle', re.IGNORECASE), 0.999),  # ASE = .999
    (re.compile(r'silver\s*maple', re.IGNORECASE), 0.9999),  # Canadian Maple = .9999
]


def extract_weight_from_title(title: str, description: str = '') -> Optional[float]:
    """
    Extract weight in grams from title or description.
    Returns None if no weight found.

    Conversions:
    - ozt (troy oz) = 31.1 grams (used for precious metals)
    - oz (avoirdupois) = 28.35 grams (standard oz)
    - dwt (pennyweight) = 1.555 grams
    """
    # Normalize - handle URL encoding (+ for spaces, %XX)
    combined = f"{title} {description}"
    text = combined.replace('+', ' ')
    if '%' in text:
        try:
            from urllib.parse import unquote
            text = unquote(text)
        except:
            pass
    text = text.lower()

    # Check for fractional troy oz first (e.g., "3/4 ozt", "1/2 troy oz")
    frac_ozt_match = FRACTION_OZT_PATTERN.search(text)
    if frac_ozt_match:
        numerator = float(frac_ozt_match.group(1))
        denominator = float(frac_ozt_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            grams = oz_value * 31.1  # Troy oz
            logger.info(f"[WEIGHT] Fractional troy oz: {int(numerator)}/{int(denominator)} ozt = {oz_value:.3f} ozt = {grams:.1f}g")
            return grams

    # Check for fractional plain oz (e.g., "3/4 oz", "1/2 oz")
    frac_oz_match = FRACTION_OZ_PATTERN.search(text)
    if frac_oz_match:
        numerator = float(frac_oz_match.group(1))
        denominator = float(frac_oz_match.group(2))
        if denominator > 0:
            oz_value = numerator / denominator
            # For precious metals (silver/gold), use troy oz (31.1g)
            # Check for silver/gold indicators in text
            is_precious_metal = any(kw in text for kw in [
                '.999', '.925', '.900', '.800', 'silver', 'gold', 'platinum',
                'bullion', 'coin', 'bar', 'round', 'eagle', 'maple', 'libertad',
                'krugerrand', 'philharmonic', 'britannia', 'panda'
            ])
            if is_precious_metal:
                grams = oz_value * 31.1  # Troy oz for precious metals
                logger.info(f"[WEIGHT] Fractional oz (precious metal): {int(numerator)}/{int(denominator)} ozt = {oz_value:.3f} ozt = {grams:.1f}g")
            else:
                grams = oz_value * 28.35  # Avoirdupois oz
                logger.info(f"[WEIGHT] Fractional oz: {int(numerator)}/{int(denominator)} oz = {oz_value:.3f} oz = {grams:.1f}g")
            return grams

    for pattern in WEIGHT_PATTERNS:
        match = pattern.search(text)
        if match:
            value = float(match.group(1))
            matched_text = match.group(0).lower()

            # Convert DWT to grams (1 dwt = 1.555 grams)
            if 'dwt' in matched_text:
                value *= 1.555
            # Convert troy oz to grams (1 ozt = 31.1 grams)
            elif 'ozt' in matched_text or 'oz.t' in matched_text or 'troy' in matched_text:
                value *= 31.1
            # Convert plain oz to grams - use TROY oz (31.1g) for precious metals
            elif 'oz' in matched_text:
                # Check for precious metal indicators - these use troy oz
                is_precious_metal = any(kw in text for kw in [
                    '.999', '.925', '.900', '.800', 'silver', 'sterling', 'gold',
                    'platinum', 'bullion', 'coin', 'bar', 'round', 'eagle', 'maple',
                    '10k', '14k', '18k', '22k', '24k', '10kt', '14kt', '18kt'
                ])
                if is_precious_metal:
                    value *= 31.1  # Troy oz for precious metals
                    logger.info(f"[WEIGHT] Plain oz (precious metal context): {match.group(1)} oz = {value:.1f}g (troy)")
                else:
                    value *= 28.35  # Avoirdupois oz for general items
            return value

    return None


def extract_karat_from_title(title: str) -> Optional[int]:
    """
    Extract gold karat from title.
    Returns None if no karat found.
    """
    for pattern, karat in KARAT_PATTERNS:
        if pattern.search(title):
            return karat
    return None


def extract_silver_purity(title: str) -> Optional[float]:
    """
    Extract silver purity from title.
    Returns decimal (0.925 for sterling) or None if not found.
    """
    for pattern, purity in SILVER_PATTERNS:
        if pattern.search(title):
            return purity
    return None


def extract_price(price_str: str) -> float:
    """
    Extract numeric price from string like "$149.99" or "149.99".
    Returns 0.0 if parsing fails.
    """
    try:
        cleaned = str(price_str).replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def contains_non_metal_indicators(title: str) -> Tuple[bool, str]:
    """
    Check if title contains indicators of non-metal value (stones, watches).
    Returns (has_indicator, indicator_type).
    """
    title_lower = title.lower()

    stone_keywords = [
        'diamond', 'ruby', 'emerald', 'sapphire', 'opal', 'tanzanite',
        'aquamarine', 'topaz', 'garnet', 'amethyst', 'pearl', 'turquoise',
        'cameo'  # Shell/coral/stone carving - deduct ~3g for typical cameo
    ]

    for stone in stone_keywords:
        if stone in title_lower:
            return True, stone

    if 'watch' in title_lower and 'band' not in title_lower:
        return True, 'watch'

    return False, ''


def extract_lot_info(title: str) -> Tuple[bool, int]:
    """
    Check if item is a lot and extract count.
    Returns (is_lot, count).
    """
    title_lower = title.lower()

    # Look for lot indicators
    lot_patterns = [
        re.compile(r'lot\s*of\s*(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\s*(?:pc|pcs|pieces?)\s*lot', re.IGNORECASE),
        re.compile(r'bulk\s*lot', re.IGNORECASE),
    ]

    for pattern in lot_patterns:
        match = pattern.search(title)
        if match:
            try:
                count = int(match.group(1)) if match.groups() else 1
                return True, count
            except (ValueError, IndexError):
                return True, 1

    return False, 0


def detect_flatware(title: str) -> Tuple[bool, str, int, float]:
    """
    Detect if listing is for sterling flatware and estimate weight.

    FLATWARE WEIGHT ESTIMATES (solid sterling):
    - Dinner fork: 45g
    - Salad fork: 35g
    - Dinner spoon/Tablespoon: 45g
    - Soup spoon: 35g
    - Teaspoon: 20g
    - Iced tea spoon: 18g
    - Serving fork/spoon: 55g
    - Pickle fork: 10g
    - Butter spreader: 25g

    Returns: (is_flatware, piece_type, quantity, estimated_grams)
    """
    # Normalize title - handle URL encoding (+ for spaces, %XX)
    title_normalized = title.replace('+', ' ')
    if '%' in title_normalized:
        try:
            from urllib.parse import unquote
            title_normalized = unquote(title_normalized)
        except:
            pass
    title_lower = title_normalized.lower()

    # Check for sterling silver indicators
    is_sterling = any(kw in title_lower for kw in ['sterling', '.925', '925'])
    if not is_sterling:
        return False, "", 0, 0

    # Flatware piece types with estimated weights (grams)
    # Format: (keywords, base_weight, piece_name)
    flatware_types = [
        # Forks - check specific types first
        (['dinner fork'], 45, 'dinner_fork'),
        (['salad fork', 'dessert fork', 'luncheon fork'], 35, 'salad_fork'),
        (['serving fork', 'meat fork', 'cold meat fork', 'carving fork'], 55, 'serving_fork'),
        (['pickle fork', 'olive fork', 'cocktail fork', 'seafood fork', 'oyster fork'], 10, 'pickle_fork'),
        (['fork'], 45, 'fork'),  # Default fork = dinner fork size

        # Spoons - check specific types first
        (['tablespoon', 'table spoon', 'serving spoon', 'berry spoon'], 55, 'serving_spoon'),
        (['dinner spoon'], 45, 'dinner_spoon'),
        (['soup spoon', 'gumbo spoon', 'bouillon spoon'], 35, 'soup_spoon'),
        (['teaspoon', 'tea spoon', 'demitasse spoon', 'coffee spoon'], 20, 'teaspoon'),
        (['iced tea spoon', 'ice tea spoon'], 18, 'iced_tea_spoon'),
        (['sugar spoon', 'sugar shell'], 25, 'sugar_spoon'),
        (['spoon'], 35, 'spoon'),  # Default spoon = medium

        # Other flatware
        (['butter spreader', 'butter knife', 'butter server'], 25, 'butter_spreader'),
        (['ladle'], 80, 'ladle'),
        (['tongs', 'sugar tongs', 'ice tongs'], 30, 'tongs'),
        (['server', 'pie server', 'cake server'], 60, 'server'),
    ]

    # Find matching piece type
    matched_type = None
    base_weight = 0
    piece_name = ""

    for keywords, weight, name in flatware_types:
        if any(kw in title_lower for kw in keywords):
            matched_type = keywords[0]
            base_weight = weight
            piece_name = name
            break

    if not matched_type:
        return False, "", 0, 0

    # Check for size hints that modify weight
    size_modifier = 1.0

    # Large/dinner size indicators
    if any(s in title_lower for s in ['7 1/2', '7.5"', '7 1/2"', '7.5 inch', 'large', 'dinner']):
        size_modifier = 1.0  # Full size
    # Medium size
    elif any(s in title_lower for s in ['6 1/2', '6.5"', '6 1/2"', 'luncheon', 'medium']):
        size_modifier = 0.85
    # Small size
    elif any(s in title_lower for s in ['5 1/2', '5.5"', '5 1/2"', 'small', 'cocktail', 'dessert']):
        size_modifier = 0.7

    # Extract quantity
    quantity = 1
    qty_patterns = [
        re.compile(r'(\d+)\s*(?:sterling|silver)', re.IGNORECASE),
        re.compile(r'set\s*of\s*(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\s*(?:pc|pcs|pieces?)', re.IGNORECASE),
        re.compile(r'(\d+)\s*(?:fork|spoon|ladle|tong|server)s?\b', re.IGNORECASE),
        re.compile(r'^(\d+)\s+', re.IGNORECASE),  # Number at start of title
    ]

    for pattern in qty_patterns:
        match = pattern.search(title_lower)
        if match:
            try:
                qty = int(match.group(1))
                if qty > 0 and qty <= 100:  # Sanity check
                    quantity = qty
                    break
            except (ValueError, IndexError):
                pass

    # Calculate estimated weight
    estimated_weight = base_weight * size_modifier * quantity

    logger.info(f"[FLATWARE] Detected {quantity}x {piece_name} ({matched_type}) - est {estimated_weight:.0f}g")

    return True, piece_name, quantity, estimated_weight


def detect_flatware_knives(title: str) -> Tuple[bool, int, float]:
    """
    Detect if listing is for sterling flatware knives and calculate actual silver content.

    Sterling flatware knives have STAINLESS STEEL BLADES - only the hollow handles
    contain silver. Each knife handle only contains ~15-20g of actual silver.

    Returns: (is_knife, quantity, max_silver_grams)
    """
    # Normalize title - handle URL encoding (+ for spaces, %XX)
    title_normalized = title.replace('+', ' ')
    if '%' in title_normalized:
        try:
            from urllib.parse import unquote
            title_normalized = unquote(title_normalized)
        except:
            pass
    title_lower = title_normalized.lower()

    # Check for sterling silver indicators
    is_sterling = any(kw in title_lower for kw in ['sterling', '.925', '925'])
    if not is_sterling:
        return False, 0, 0

    # Knife keywords (flatware knives, not pocket knives)
    knife_keywords = [
        'dinner knife', 'dinner knives',
        'butter knife', 'butter knives',
        'steak knife', 'steak knives',
        'luncheon knife', 'luncheon knives',
        'place knife', 'place knives',
        'knives',  # General knives (after checking for sterling flatware context)
    ]

    is_knife = any(kw in title_lower for kw in knife_keywords)
    if not is_knife:
        return False, 0, 0

    # Extract quantity
    quantity = 1

    # Patterns like "4 Sterling", "Set of 6", "6 knives", etc.
    qty_patterns = [
        re.compile(r'(\d+)\s*(?:sterling|silver)', re.IGNORECASE),
        re.compile(r'set\s*of\s*(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\s*(?:pc|pcs|pieces?)', re.IGNORECASE),
        re.compile(r'(\d+)\s*knives?\b', re.IGNORECASE),
        re.compile(r'^(\d+)\s+', re.IGNORECASE),  # Number at start of title
    ]

    for pattern in qty_patterns:
        match = pattern.search(title_lower)
        if match:
            try:
                qty = int(match.group(1))
                if qty > 0 and qty <= 100:  # Sanity check
                    quantity = qty
                    break
            except (ValueError, IndexError):
                pass

    # Calculate max silver content
    # Each knife handle contains ~15-20g of sterling silver
    # Use conservative 15g estimate (the blade is stainless steel, not silver)
    SILVER_PER_KNIFE = 15  # grams
    max_silver_grams = quantity * SILVER_PER_KNIFE

    logger.info(f"[KNIFE] Detected {quantity} sterling flatware knives = max {max_silver_grams}g silver")

    return True, quantity, max_silver_grams


def normalize_title(title: str) -> str:
    """
    Normalize a title for comparison/matching.
    Removes special characters, extra spaces, and converts to lowercase.
    """
    # Decode URL encoding if present
    if '+' in title or '%' in title:
        try:
            from urllib.parse import unquote_plus
            title = unquote_plus(title)
        except:
            title = title.replace('+', ' ')

    # Remove special characters and normalize
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title)
    return title.strip().lower()
