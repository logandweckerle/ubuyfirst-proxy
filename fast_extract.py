"""
Fast Extraction Module - Server-side instant calculations for gold/silver
No AI needed - pure regex and math for speed

This runs BEFORE AI and provides:
1. Instant weight extraction from title
2. Instant karat detection
3. Instant melt value calculation
4. HOT flag for obvious deals
"""

import re
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# Get spot prices from config (will be imported in main)
# These are FALLBACKS if live fetch fails - update periodically to stay close to market
DEFAULT_GOLD_OZ = 4500       # Fallback ~Jan 2026 prices
DEFAULT_SILVER_OZ = 82       # Fallback ~Jan 2026 prices
DEFAULT_PLATINUM_OZ = 2412   # Fallback ~Jan 2026 prices
DEFAULT_PALLADIUM_OZ = 1908  # Fallback ~Jan 2026 prices


@dataclass
class FastExtractResult:
    """Result of fast extraction - all fields optional"""
    weight_grams: Optional[float] = None
    weight_source: str = "none"  # "title", "description", "none"
    karat: Optional[int] = None  # 10, 14, 18, 22, 24
    karat_source: str = "none"
    is_plated: bool = False
    plated_reason: str = ""
    melt_value: Optional[float] = None
    max_buy: Optional[float] = None
    is_hot: bool = False  # True if obvious deal based on math alone
    hot_reason: str = ""
    instant_pass: bool = False
    pass_reason: str = ""
    confidence: int = 0  # 0-100 based on extraction quality
    has_non_metal: bool = False  # True if stones/pearls detected (need AI for deductions)
    non_metal_type: str = ""  # What non-metal was detected


# ============================================================
# NON-METAL DETECTION (stones, pearls, watches, etc.)
# Items with non-metal weight need AI for proper deductions
# ============================================================

NON_METAL_INDICATORS = [
    # Gemstones
    'pearl', 'diamond', 'turquoise', 'jade', 'coral', 'opal', 'onyx',
    'amethyst', 'ruby', 'sapphire', 'emerald', 'garnet', 'topaz', 'aquamarine',
    'peridot', 'citrine', 'tanzanite', 'morganite', 'alexandrite',
    # Semi-precious cabochon stones (common in antique/vintage jewelry)
    'agate', 'carnelian', 'jasper', 'lapis', 'malachite', 'moonstone',
    'tiger eye', 'chalcedony', 'aventurine', 'bloodstone', 'quartz', 'cameo',
    # Stone indicators (but NOT 'ct ' alone - too many false positives)
    'stone', 'gemstone', 'gem', 'cttw', 'ctw', 'carat',
    # Watches (have movement/crystal weight)
    'watch', 'movement',
    # Cord/fabric necklaces
    'cord', 'leather', 'silk', 'rubber', 'fabric', 'string',
    # Glass pendants
    'murano', 'glass', 'millefiori', 'crystal',
    # Beaded jewelry
    'bead', 'beaded', 'strand',
    # Weighted/filled items (cement, pitch, plaster inside)
    'weighted', 'cement', 'reinforced', 'filled base',
    # Stainless blade/composite items (only handle is silver)
    'stainless', 'sterling handle', 'silver handle',
    # Handled flatware - knives have stainless blades + weighted/filled sterling handles
    'handled', 'knife', 'knives', 'carving set',
    # Mother of pearl inlays (handle material, not silver)
    'mother of pearl', 'mop handle',
]

# Pattern for carat weight (e.g., "0.5 ct", "1ct", ".25 ct") - requires digit before ct
CARAT_WEIGHT_PATTERN = re.compile(r'\d+\.?\d*\s*ct\b', re.IGNORECASE)

# Items where melt calculation is IMPOSSIBLE for GOLD - instant PASS
# These have partial gold content where you can't calculate value from total weight
INSTANT_PASS_PARTIAL_GOLD = [
    'gold handle',  # Only handle is gold, blade/body is steel
    'stainless blade', 'stainless steel blade',  # Gold-handled with steel blade
]

# Items for SILVER - NOT instant pass, AI will calculate with proper weight
# Knives/handles need AI to apply handle-only weight (~15-20g per knife)
# Previously instant-passed but user wants these analyzed
SILVER_PARTIAL_METAL_INDICATORS = [
    'sterling handle', 'silver handle',
    'handled', 'knife', 'knives', 'carving set',
    'stainless blade', 'stainless steel blade',
]



def detect_non_metal(title: str, description: str = "", item_specifics: dict = None) -> Tuple[bool, str]:
    """
    Detect if item likely has significant non-metal weight.
    These items need AI analysis for proper deductions.
    Returns (has_non_metal, detected_type)

    Args:
        item_specifics: eBay item specifics dict with MainStone, TotalCaratWeight, etc.
    """
    # Check item specifics FIRST (most reliable)
    if item_specifics:
        # MainStone field (e.g., "Diamond", "Ruby", "Sapphire")
        main_stone = str(item_specifics.get('MainStone', '') or '').lower().strip()
        if main_stone and main_stone not in ['no stone', 'none', 'n/a', 'na', '']:
            return True, f"MainStone: {main_stone}"

        # TotalCaratWeight field (e.g., "0.50 ctw", "1.5 ct")
        carat_weight = str(item_specifics.get('TotalCaratWeight', '') or '').strip()
        if carat_weight and carat_weight not in ['0', '0.00', 'n/a', 'na', '']:
            return True, f"TotalCaratWeight: {carat_weight}"

        # SecondaryStone field
        secondary_stone = str(item_specifics.get('SecondaryStone', '') or '').lower().strip()
        if secondary_stone and secondary_stone not in ['no stone', 'none', 'n/a', 'na', '']:
            return True, f"SecondaryStone: {secondary_stone}"

    text = f"{title} {description}".lower()

    # Check simple substring indicators
    for indicator in NON_METAL_INDICATORS:
        if indicator in text:
            return True, indicator

    # Check for carat weight pattern (e.g., "0.5 ct diamond")
    if CARAT_WEIGHT_PATTERN.search(text):
        return True, "carat weight"

    return False, ""
    

# ============================================================
# GOLD FILLED / PLATED DETECTION (Pre-compiled for speed)
# ============================================================

# Pre-compile plated patterns at module load
PLATED_PATTERNS_COMPILED = [
    (re.compile(r'\bgold\s*filled\b', re.IGNORECASE), 'gold filled'),
    (re.compile(r'\bgf\b', re.IGNORECASE), 'GF'),
    (re.compile(r'\b(?:1/20|1/10)\s*\d+k', re.IGNORECASE), 'gold filled fraction'),
    (re.compile(r'\bgold\s*plated\b', re.IGNORECASE), 'gold plated'),
    (re.compile(r'\bgp\b', re.IGNORECASE), 'GP'),
    (re.compile(r'\bhge\b', re.IGNORECASE), 'HGE'),
    (re.compile(r'\brgp\b', re.IGNORECASE), 'RGP'),
    (re.compile(r'\bvermeil\b', re.IGNORECASE), 'vermeil'),
    (re.compile(r'\bgold\s*tone\b', re.IGNORECASE), 'gold tone'),
    (re.compile(r'\bgold\s*overlay\b', re.IGNORECASE), 'gold overlay'),
    (re.compile(r'\belectroplate\b', re.IGNORECASE), 'electroplate'),
    (re.compile(r'\brolled\s*gold\b', re.IGNORECASE), 'rolled gold'),
    # Stainless steel with gold karat = gold-plated stainless (NOT solid gold)
    (re.compile(r'\bstainless\s*steel\b', re.IGNORECASE), 'stainless steel'),
    # "Stamped gold" usually means gold-stamped/plated, not solid
    (re.compile(r'\bstamped\s*gold\b', re.IGNORECASE), 'stamped gold'),
    (re.compile(r'\bgold\s*stamped\b', re.IGNORECASE), 'gold stamped'),
]

# Known gold filled brands - instant PASS (NOT Keystone - good brand)
GOLD_FILLED_BRANDS = [
    'champion dueber', 'dueber', 'wadsworth',
    'star watch case', 'illinois watch', 'elgin watch case',
    'fortune', 'lenox',
]


def detect_plated(title: str, description: str = "") -> Tuple[bool, str]:
    """
    Detect if item is gold plated/filled (not solid gold).
    Returns (is_plated, reason)
    """
    text = f"{title} {description}".lower()

    # Check brand names first (simple string match - very fast)
    for brand in GOLD_FILLED_BRANDS:
        if brand in text:
            return True, f"Gold filled brand: {brand}"

    # Check pre-compiled patterns
    for pattern, name in PLATED_PATTERNS_COMPILED:
        if pattern.search(text):
            return True, f"Plated indicator: {name}"

    return False, ""


# ============================================================
# ITEM SPECIFICS DANGER DETECTION
# Uses eBay item specifics (Metal, Material) to catch fakes
# ============================================================

# Danger metals - NOT solid gold/silver
DANGER_METALS = [
    'stainless', 'steel', 'brass', 'copper', 'bronze', 'alloy',
    'plated', 'filled', 'tone', 'rhodium', 'nickel', 'pewter',
    'titanium', 'tungsten', 'base metal', 'costume'
]

# Danger materials that indicate fake/plated
DANGER_MATERIALS = [
    'stainless', 'steel', 'brass', 'plated', 'filled',
    'base metal', 'alloy', 'costume'
]


def check_item_specifics_danger(data: dict) -> Tuple[bool, str]:
    """
    Check eBay item specifics (Metal, Material) for danger signals.
    Returns (is_danger, reason)

    This catches items like "18K Gold Stainless Steel" where the title
    says gold but the item specifics reveal it's actually stainless steel.
    """
    metal = (data.get('Metal', '') or '').lower()
    material = (data.get('Material', '') or '').lower()

    # Safe multi-tone patterns - these are REAL gold variations, NOT plated
    # "multi-tone gold", "two-tone gold", "tri-tone gold" = real gold in multiple colors
    safe_tone_patterns = ['multi-tone', 'two-tone', 'tri-tone', 'two tone', 'tri tone', 'multi tone']
    is_safe_tone = any(pattern in metal for pattern in safe_tone_patterns)

    # Check Metal field for danger
    for danger in DANGER_METALS:
        if danger in metal:
            # Exception: "yellow gold", "white gold", "rose gold" are fine
            if 'gold' in metal:
                # Skip "tone" check if it's a safe multi-tone pattern
                if danger == 'tone' and is_safe_tone:
                    continue  # multi-tone/two-tone/tri-tone gold is real gold
                # For other dangers with gold, check if danger word is separate from gold
                if danger not in ['plated', 'filled', 'tone']:
                    if danger in metal.replace('gold', '').replace('+', ' '):
                        return True, f"Item specifics Metal='{metal}' contains '{danger}'"
                else:
                    # plated/filled/tone (non-safe) - this is danger
                    if danger == 'tone' and not is_safe_tone:
                        return True, f"Item specifics Metal='{metal}' contains '{danger}'"
                    elif danger != 'tone':
                        return True, f"Item specifics Metal='{metal}' contains '{danger}'"
            else:
                return True, f"Item specifics Metal='{metal}' contains '{danger}'"

    # Check Material field for danger
    for danger in DANGER_MATERIALS:
        if danger in material:
            return True, f"Item specifics Material='{material}' contains '{danger}'"

    return False, ""


# ============================================================
# KARAT EXTRACTION (Pre-compiled for speed)
# ============================================================

# Pre-compile karat patterns at module load
KARAT_PATTERNS_COMPILED = [
    # Standard karat marks - most reliable
    (re.compile(r'\b24\s*k(?:t|arat)?\b', re.IGNORECASE), 24),
    (re.compile(r'\b22\s*k(?:t|arat)?\b', re.IGNORECASE), 22),
    (re.compile(r'\b18\s*k(?:t|arat)?\b', re.IGNORECASE), 18),
    (re.compile(r'\b14\s*k(?:t|arat)?\b', re.IGNORECASE), 14),
    (re.compile(r'\b10\s*k(?:t|arat)?\b', re.IGNORECASE), 10),
    (re.compile(r'\b9\s*k(?:t|arat)?\b', re.IGNORECASE), 9),
    # European fineness marks
    (re.compile(r'\b999\b'), 24),   # Pure gold
    (re.compile(r'\b916\b'), 22),   # 22K
    (re.compile(r'\b750\b'), 18),   # 18K
    (re.compile(r'\b585\b'), 14),   # 14K
    (re.compile(r'\b417\b'), 10),   # 10K
    (re.compile(r'\b375\b'), 9),    # 9K
]


# ============================================================
# PLATINUM PURITY PATTERNS (Pre-compiled for speed)
# ============================================================

PLATINUM_PURITY_PATTERNS_COMPILED = [
    # PT950 = 95% platinum (most common)
    (re.compile(r'\bpt\s*950\b', re.IGNORECASE), 0.950),
    (re.compile(r'\b950\s*plat(?:inum)?\b', re.IGNORECASE), 0.950),
    (re.compile(r'\bplatinum\s*950\b', re.IGNORECASE), 0.950),
    # PT900 = 90% platinum
    (re.compile(r'\bpt\s*900\b', re.IGNORECASE), 0.900),
    (re.compile(r'\b900\s*plat(?:inum)?\b', re.IGNORECASE), 0.900),
    (re.compile(r'\bplatinum\s*900\b', re.IGNORECASE), 0.900),
    # PT850 = 85% platinum
    (re.compile(r'\bpt\s*850\b', re.IGNORECASE), 0.850),
    (re.compile(r'\b850\s*plat(?:inum)?\b', re.IGNORECASE), 0.850),
    (re.compile(r'\bplatinum\s*850\b', re.IGNORECASE), 0.850),
    # Generic "platinum" - assume PT950 (standard jewelry grade)
    (re.compile(r'\bplatinum\b', re.IGNORECASE), 0.950),
    (re.compile(r'\bplat\b', re.IGNORECASE), 0.950),
    # Iridium-platinum alloys (typically 90-95%)
    (re.compile(r'\birid(?:ium)?\s*plat(?:inum)?\b', re.IGNORECASE), 0.900),
    (re.compile(r'\bplat(?:inum)?\s*irid(?:ium)?\b', re.IGNORECASE), 0.900),
]


# ============================================================
# PALLADIUM PURITY PATTERNS (Pre-compiled for speed)
# ============================================================

PALLADIUM_PURITY_PATTERNS_COMPILED = [
    # PD950 = 95% palladium (most common)
    (re.compile(r'\bpd\s*950\b', re.IGNORECASE), 0.950),
    (re.compile(r'\b950\s*pallad(?:ium)?\b', re.IGNORECASE), 0.950),
    (re.compile(r'\bpalladium\s*950\b', re.IGNORECASE), 0.950),
    # PD500 = 50% palladium (common in older jewelry)
    (re.compile(r'\bpd\s*500\b', re.IGNORECASE), 0.500),
    (re.compile(r'\b500\s*pallad(?:ium)?\b', re.IGNORECASE), 0.500),
    (re.compile(r'\bpalladium\s*500\b', re.IGNORECASE), 0.500),
    # Generic "palladium" - assume PD950
    (re.compile(r'\bpalladium\b', re.IGNORECASE), 0.950),
]


def extract_karat(title: str, description: str = "", item_specifics: dict = None) -> Tuple[Optional[int], str]:
    """
    Extract karat from title/description/item_specifics.
    Returns (karat, source) where source is "title", "description", "MetalPurity", or "Fineness"

    Priority order:
    1. Item specifics (MetalPurity, Fineness) - most reliable, from eBay database
    2. Title - seller's main description
    3. Description - additional details
    """
    # Check item specifics FIRST (most reliable - from eBay database)
    if item_specifics:
        # MetalPurity field (e.g., "14K", "18K", "24K", ".925")
        metal_purity = str(item_specifics.get('MetalPurity', '') or '').lower().strip()
        if metal_purity:
            # Parse karat from common formats: "14k", "18kt", "24 karat", etc.
            for pattern, karat in KARAT_PATTERNS_COMPILED:
                if pattern.search(metal_purity):
                    return karat, "MetalPurity"

        # Fineness field (e.g., "585", "750", "999")
        fineness = str(item_specifics.get('Fineness', '') or '').strip()
        if fineness:
            # Fineness to karat mapping
            fineness_map = {
                '999': 24, '9999': 24,
                '916': 22,
                '750': 18,
                '585': 14,
                '417': 10,
                '375': 9,
            }
            # Check for fineness number
            for fin_val, karat in fineness_map.items():
                if fin_val in fineness:
                    return karat, "Fineness"

    # Check title (more reliable than description)
    for pattern, karat in KARAT_PATTERNS_COMPILED:
        if pattern.search(title):
            return karat, "title"

    # Check description
    if description:
        for pattern, karat in KARAT_PATTERNS_COMPILED:
            if pattern.search(description):
                return karat, "description"

    return None, "none"


# ============================================================
# WEIGHT EXTRACTION (Pre-compiled for speed)
# ============================================================

# Pre-compile weight patterns
WEIGHT_GRAM_PATTERN = re.compile(r'(\d*\.?\d+)\s*(?:g(?:ram)?s?)\b', re.IGNORECASE)
WEIGHT_DWT_PATTERN = re.compile(r'(\d+\.?\d*)\s*dwt\b', re.IGNORECASE)
# Troy oz pattern: matches "6.19 oz", "6.19 troy oz", "6.19 TROY OZ", etc.
WEIGHT_OZ_PATTERN = re.compile(r'(\d+\.?\d*)\s*(?:troy\s+)?(?:oz|ounce)s?\b', re.IGNORECASE)
# Fractional oz pattern: matches "1/2 oz", "1/4 troy oz", "1/10 oz", etc.
WEIGHT_FRAC_OZ_PATTERN = re.compile(r'(\d+)/(\d+)\s*(?:troy\s+)?(?:oz|ounce)s?\b', re.IGNORECASE)
# Word fraction patterns: "one half oz", "half ounce", "quarter oz"
WEIGHT_WORD_FRAC_PATTERN = re.compile(
    r'\b(?:one\s+)?(?P<frac>half|quarter|tenth)\s+(?:troy\s+)?(?:oz|ounce)s?\b',
    re.IGNORECASE
)
WORD_FRAC_MAP = {'half': 0.5, 'quarter': 0.25, 'tenth': 0.1}


def extract_weight(title: str, description: str = "", max_weight: float = 3000) -> Tuple[Optional[float], str]:
    """
    Extract weight from title/description.
    Returns (weight_grams, source)

    Handles: grams, dwt (pennyweight), oz
    Uses pre-compiled patterns for speed.

    Args:
        title: Item title
        description: Item description
        max_weight: Maximum valid weight in grams (default 3000g for large silver pieces)
    """
    text_sources = [
        (title, "title"),
        (description, "description")
    ]

    for text, source in text_sources:
        if not text:
            continue

        # Clean text: replace + with space (URL encoding), then lowercase
        text_lower = text.replace('+', ' ').lower()

        # Pattern: "X.Xg" or "X.X grams" or "X.X gram" (pre-compiled)
        gram_match = WEIGHT_GRAM_PATTERN.search(text_lower)
        if gram_match:
            weight = float(gram_match.group(1))
            if 0.1 <= weight <= max_weight:  # Allow up to max_weight for large silver
                return weight, source

        # Pattern: "X.X dwt" (pennyweight) - multiply by 1.555
        dwt_match = WEIGHT_DWT_PATTERN.search(text_lower)
        if dwt_match:
            weight = float(dwt_match.group(1)) * 1.555
            if 0.1 <= weight <= max_weight:
                return weight, source

        # Check fractional patterns FIRST (before regular oz pattern)
        # Pattern: "1/2 oz", "1/4 oz", "1/10 oz" (fractional ounces)
        frac_oz_match = WEIGHT_FRAC_OZ_PATTERN.search(text_lower)
        if frac_oz_match:
            numerator = float(frac_oz_match.group(1))
            denominator = float(frac_oz_match.group(2))
            if denominator > 0:
                weight = (numerator / denominator) * 31.1035
                if 0.1 <= weight <= max_weight:
                    return weight, source

        # Pattern: "one half oz", "half ounce", "quarter oz"
        word_frac_match = WEIGHT_WORD_FRAC_PATTERN.search(text_lower)
        if word_frac_match:
            frac_word = word_frac_match.group('frac').lower()
            if frac_word in WORD_FRAC_MAP:
                weight = WORD_FRAC_MAP[frac_word] * 31.1035
                if 0.1 <= weight <= max_weight:
                    return weight, source

        # Pattern: "X.X oz" (ounces) - multiply by 31.1
        # Check AFTER fractional patterns to avoid matching "2" from "1/2 oz"
        oz_match = WEIGHT_OZ_PATTERN.search(text_lower)
        if oz_match:
            weight = float(oz_match.group(1)) * 31.1035
            if 0.1 <= weight <= max_weight:
                return weight, source

    return None, "none"


# ============================================================
# MELT VALUE CALCULATION
# ============================================================

def calculate_gold_melt(weight_grams: float, karat: int, gold_spot_oz: float) -> Dict:
    """
    Calculate gold melt value, max buy, and sell price.
    """
    # Karat to purity
    purity_map = {
        24: 0.999,
        22: 0.917,
        18: 0.750,
        14: 0.583,
        10: 0.417,
        9: 0.375,
    }
    
    purity = purity_map.get(karat, 0.583)  # Default to 14K if unknown
    gold_per_gram = gold_spot_oz / 31.1035
    
    melt_value = weight_grams * purity * gold_per_gram
    max_buy = melt_value * 0.90  # 90% ceiling for gold
    sell_price = melt_value * 0.96  # What refiner pays
    
    return {
        'melt_value': round(melt_value, 2),
        'max_buy': round(max_buy, 2),
        'sell_price': round(sell_price, 2),
        'rate_per_gram': round(purity * gold_per_gram, 2),
    }


def calculate_silver_melt(weight_grams: float, silver_spot_oz: float, purity: float = 0.925) -> Dict:
    """
    Calculate silver melt value.
    Default purity is sterling (0.925)
    """
    silver_per_gram = silver_spot_oz / 31.1035

    melt_value = weight_grams * purity * silver_per_gram
    max_buy = melt_value * 0.75  # 75% ceiling for silver
    sell_price = melt_value * 0.82  # What refiner pays

    return {
        'melt_value': round(melt_value, 2),
        'max_buy': round(max_buy, 2),
        'sell_price': round(sell_price, 2),
        'rate_per_gram': round(purity * silver_per_gram, 2),
    }


def extract_platinum_purity(title: str, description: str = "") -> Tuple[Optional[float], str]:
    """
    Extract platinum purity from title/description.
    Returns (purity, source) where purity is decimal (0.950, 0.900, 0.850)
    """
    for pattern, purity in PLATINUM_PURITY_PATTERNS_COMPILED:
        if pattern.search(title):
            return purity, "title"

    if description:
        for pattern, purity in PLATINUM_PURITY_PATTERNS_COMPILED:
            if pattern.search(description):
                return purity, "description"

    return None, "none"


def extract_palladium_purity(title: str, description: str = "") -> Tuple[Optional[float], str]:
    """
    Extract palladium purity from title/description.
    Returns (purity, source) where purity is decimal (0.950, 0.500)
    """
    for pattern, purity in PALLADIUM_PURITY_PATTERNS_COMPILED:
        if pattern.search(title):
            return purity, "title"

    if description:
        for pattern, purity in PALLADIUM_PURITY_PATTERNS_COMPILED:
            if pattern.search(description):
                return purity, "description"

    return None, "none"


def calculate_platinum_melt(weight_grams: float, platinum_spot_oz: float, purity: float = 0.950) -> Dict:
    """
    Calculate platinum melt value.
    Default purity is PT950 (95%)
    """
    platinum_per_gram = platinum_spot_oz / 31.1035

    melt_value = weight_grams * purity * platinum_per_gram
    max_buy = melt_value * 0.85  # 85% ceiling for platinum (less liquid market)
    sell_price = melt_value * 0.90  # What refiner pays

    return {
        'melt_value': round(melt_value, 2),
        'max_buy': round(max_buy, 2),
        'sell_price': round(sell_price, 2),
        'rate_per_gram': round(purity * platinum_per_gram, 2),
    }


def calculate_palladium_melt(weight_grams: float, palladium_spot_oz: float, purity: float = 0.950) -> Dict:
    """
    Calculate palladium melt value.
    Default purity is PD950 (95%)
    """
    palladium_per_gram = palladium_spot_oz / 31.1035

    melt_value = weight_grams * purity * palladium_per_gram
    max_buy = melt_value * 0.80  # 80% ceiling for palladium (volatile, less liquid)
    sell_price = melt_value * 0.85  # What refiner pays

    return {
        'melt_value': round(melt_value, 2),
        'max_buy': round(max_buy, 2),
        'sell_price': round(sell_price, 2),
        'rate_per_gram': round(purity * palladium_per_gram, 2),
    }


# ============================================================
# MAIN EXTRACTION FUNCTION
# ============================================================

def fast_extract_gold(
    title: str,
    price: float,
    description: str = "",
    gold_spot_oz: float = DEFAULT_GOLD_OZ,
    item_specifics: dict = None
) -> FastExtractResult:
    """
    Perform instant server-side extraction for gold listings.
    Returns everything we can determine without AI.

    CRITICAL: Does NOT instant-pass items with non-metal indicators
    (pearls, stones, watches) - these need AI for weight deductions.

    Args:
        item_specifics: eBay item specifics dict with fields like Metal, MetalPurity, Fineness, etc.
                       These are more reliable than regex extraction from title.
    """
    result = FastExtractResult()

    # Step 0: Check item specifics for danger signals (plated, stainless, etc.)
    if item_specifics:
        is_danger, danger_reason = check_item_specifics_danger(item_specifics)
        if is_danger:
            result.is_plated = True
            result.plated_reason = danger_reason
            result.instant_pass = True
            result.pass_reason = f"Item specifics reveal not solid gold: {danger_reason}"
            return result

    # Step 1: Check for plated/filled (instant PASS - always safe)
    is_plated, plated_reason = detect_plated(title, description)
    if is_plated:
        result.is_plated = True
        result.plated_reason = plated_reason
        result.instant_pass = True
        result.pass_reason = f"Gold filled/plated: {plated_reason}"
        return result

    # Step 1.5: Check for partial gold items (gold handle only = instant PASS)
    text = f"{title} {description}".lower()
    for indicator in INSTANT_PASS_PARTIAL_GOLD:
        if indicator in text:
            result.instant_pass = True
            result.pass_reason = f"Partial gold only: {indicator}"
            return result

    # Step 2: Check for non-metal components (stones, pearls, watches)
    # These need AI analysis - don't do price-based instant pass!
    has_non_metal, non_metal_type = detect_non_metal(title, description, item_specifics)
    if has_non_metal:
        result.has_non_metal = True
        result.non_metal_type = non_metal_type
        result.confidence -= 20  # Lower confidence, needs AI

    # Step 2.5: Special handling for LADIES GOLD WATCHES
    # Ladies watches have ~3g gold case on average (2-4g range)
    # These are often undervalued opportunities - flag them for attention
    is_ladies_watch = ('ladies' in text or "lady's" in text or 'womens' in text or "women's" in text) and ('watch' in text)
    is_mens_watch = ('mens' in text or "men's" in text) and ('watch' in text)

    if is_ladies_watch and not result.weight_grams:
        # Estimate 3g gold for ladies watch case (conservative middle of 2-4g range)
        result.weight_grams = 3.0
        result.weight_source = "ladies_watch_estimate"
        result.confidence = max(40, result.confidence)  # Moderate confidence
        result.has_non_metal = True
        result.non_metal_type = "ladies_watch"
    elif is_mens_watch and not result.weight_grams:
        # Men's watches are typically 8-12g case, but very variable
        # Don't estimate - too risky, let AI analyze
        result.has_non_metal = True
        result.non_metal_type = "mens_watch"

    # Step 3: Extract karat (uses item_specifics first, then title/description)
    karat, karat_source = extract_karat(title, description, item_specifics)
    if karat:
        result.karat = karat
        result.karat_source = karat_source
        result.confidence += 30

    # Step 4: Extract weight (gold rarely exceeds 500g)
    # Don't overwrite if we already have an estimate (e.g., ladies watch)
    if not result.weight_grams:
        weight, weight_source = extract_weight(title, description, max_weight=500)
        if weight:
            result.weight_grams = weight
            result.weight_source = weight_source
            result.confidence += 40

    # Use result.weight_grams for calculations (may be from stated weight or estimate)
    weight = result.weight_grams

    # Step 5: Calculate melt if we have both karat and weight
    if karat and weight:
        calc = calculate_gold_melt(weight, karat, gold_spot_oz)
        result.melt_value = calc['melt_value']
        result.max_buy = calc['max_buy']

        profit = calc['max_buy'] - price
        margin_pct = (profit / price * 100) if price > 0 else 0

        # CRITICAL: Don't instant-pass if non-metal detected!
        # The stated weight includes stones/pearls - actual gold could be much less
        # OR much more profitable after proper deductions by AI
        # EXCEPTION: Ladies watch estimate is gold-only (case weight), so we CAN be confident
        is_watch_estimate = result.weight_source == "ladies_watch_estimate"

        if has_non_metal and not is_watch_estimate:
            # Just flag for AI, don't make pass/buy decision
            result.confidence = max(30, result.confidence - 20)
            # Still provide the calculations for AI context
        elif is_watch_estimate:
            # Ladies watch with estimated 3g gold case
            # Can make BUY decision if profitable, but don't instant-pass (AI might find more value)
            if profit > 30 and margin_pct > 15:
                result.is_hot = True
                result.hot_reason = f"Ladies watch: est ~3g {karat}K case = ${calc['melt_value']:.0f} melt, max ${calc['max_buy']:.0f}, profit ${profit:.0f}"
                result.confidence = max(50, result.confidence)
            # Don't instant-pass watches - AI might see scale photo with actual weight
        else:
            # Pure gold item - can make instant decisions
            if profit > 50 and margin_pct > 20:
                result.is_hot = True
                result.hot_reason = f"Verified: {weight}g {karat}K = ${calc['melt_value']:.0f} melt, max ${calc['max_buy']:.0f}, profit ${profit:.0f} ({margin_pct:.0f}%)"
                result.confidence += 20
            elif profit < -20:
                # Clear loss on pure gold - instant pass
                result.instant_pass = True
                result.pass_reason = f"Price ${price:.0f} > max buy ${calc['max_buy']:.0f} (loss ${-profit:.0f})"

            # Sanity check: price per gram (only for pure gold)
            price_per_gram = price / weight
            if price_per_gram > 100:
                result.instant_pass = True
                result.pass_reason = f"Price ${price_per_gram:.0f}/gram exceeds $100/gram ceiling"

    return result


# ============================================================
# SILVER PLATED/STERLING DETECTION (Pre-compiled for speed)
# ============================================================

SILVER_PLATED_PATTERNS_COMPILED = [
    (re.compile(r'\bsilver\s*plate\b', re.IGNORECASE), 'silver plate'),
    (re.compile(r'\bepns\b', re.IGNORECASE), 'EPNS'),
    (re.compile(r'\bsilverplate\b', re.IGNORECASE), 'silverplate'),
    (re.compile(r'\bnickel\s*silver\b', re.IGNORECASE), 'nickel silver'),
    (re.compile(r'\brogers\b', re.IGNORECASE), 'Rogers (plated)'),
    (re.compile(r'\b1847\s*rogers\b', re.IGNORECASE), '1847 Rogers'),
    (re.compile(r'\bcommunity\b', re.IGNORECASE), 'Community (plated)'),
    (re.compile(r'\bholmes\s*&?\s*edwards\b', re.IGNORECASE), 'Holmes & Edwards'),
]

STERLING_PATTERNS_COMPILED = [
    re.compile(r'\bsterling\b', re.IGNORECASE),
    re.compile(r'\b925\b'),
    re.compile(r'\b\.925\b'),
]


def fast_extract_silver(
    title: str,
    price: float,
    description: str = "",
    silver_spot_oz: float = DEFAULT_SILVER_OZ,
    item_specifics: dict = None
) -> FastExtractResult:
    """
    Perform instant server-side extraction for silver listings.

    CRITICAL: Does NOT instant-pass items with non-metal indicators
    (stones, beads) - these need AI for weight deductions.

    Args:
        item_specifics: eBay item specifics dict with fields like Metal, MetalPurity, Fineness, etc.
    """
    result = FastExtractResult()

    text = f"{title} {description}".lower()

    # Step 0: Check item specifics for danger signals (plated, stainless, etc.)
    if item_specifics:
        metal = str(item_specifics.get('Metal', '') or '').lower()
        # Check if Metal field indicates plated
        if any(danger in metal for danger in ['plated', 'plate', 'epns', 'nickel']):
            result.is_plated = True
            result.plated_reason = f"Item specifics Metal='{metal}'"
            result.instant_pass = True
            result.pass_reason = f"Item specifics reveal not sterling: Metal='{metal}'"
            return result

    # Step 1: Check for plated indicators (instant PASS - always safe)
    for pattern, name in SILVER_PLATED_PATTERNS_COMPILED:
        if pattern.search(text):
            result.is_plated = True
            result.plated_reason = name
            result.instant_pass = True
            result.pass_reason = f"Silver plated: {name}"
            return result

    # Step 1.5: Check for knife/handle items - NOT instant pass
    # AI will calculate using handle-only weight (~15-20g per knife)
    for indicator in SILVER_PARTIAL_METAL_INDICATORS:
        if indicator in text:
            result.has_non_metal = True
            result.non_metal_type = f"partial_silver:{indicator}"
            result.confidence -= 20  # Lower confidence, needs AI for proper calculation
            # Don't return - continue to let AI handle it

    # Step 2: Check for non-metal components (stones, beads)
    has_non_metal, non_metal_type = detect_non_metal(title, description, item_specifics)
    if has_non_metal:
        result.has_non_metal = True
        result.non_metal_type = non_metal_type
        result.confidence -= 20

    # Step 3: Check for sterling indicators (pre-compiled)
    is_sterling = any(p.search(text) for p in STERLING_PATTERNS_COMPILED)
    if is_sterling:
        result.confidence += 30

    # Step 4: Extract weight (silver can be heavy - up to 3kg for flatware/serving sets)
    weight, weight_source = extract_weight(title, description, max_weight=3000)
    if weight:
        result.weight_grams = weight
        result.weight_source = weight_source
        result.confidence += 40

        # Calculate melt
        calc = calculate_silver_melt(weight, silver_spot_oz)
        result.melt_value = calc['melt_value']
        result.max_buy = calc['max_buy']

        profit = calc['max_buy'] - price
        margin_pct = (profit / price * 100) if price > 0 else 0

        # CRITICAL: Don't instant-pass if non-metal detected!
        if has_non_metal:
            result.confidence = max(30, result.confidence - 20)
        else:
            # Pure silver item - can make instant decisions
            if profit > 30 and margin_pct > 25:
                result.is_hot = True
                result.hot_reason = f"Verified: {weight}g sterling = ${calc['melt_value']:.0f} melt, max ${calc['max_buy']:.0f}, profit ${profit:.0f}"
                result.confidence += 20
            elif profit < -50:
                result.instant_pass = True
                result.pass_reason = f"Price ${price:.0f} > max buy ${calc['max_buy']:.0f} (loss > $50)"

    return result


# ============================================================
# PLATINUM EXTRACTION FUNCTION
# ============================================================

def fast_extract_platinum(
    title: str,
    price: float,
    description: str = "",
    platinum_spot_oz: float = DEFAULT_PLATINUM_OZ
) -> FastExtractResult:
    """
    Perform instant server-side extraction for platinum listings.
    """
    result = FastExtractResult()

    text = f"{title} {description}".lower()

    # Step 1: Check for partial metal items (instant PASS)
    for indicator in INSTANT_PASS_PARTIAL_METAL:
        if indicator in text:
            result.instant_pass = True
            result.pass_reason = f"Partial metal only: {indicator}"
            return result

    # Step 2: Check for non-metal components
    has_non_metal, non_metal_type = detect_non_metal(title, description)
    if has_non_metal:
        result.has_non_metal = True
        result.non_metal_type = non_metal_type
        result.confidence -= 20

    # Step 3: Extract purity
    purity, purity_source = extract_platinum_purity(title, description)
    if purity:
        result.karat = int(purity * 1000)  # Store as PT950 -> 950
        result.karat_source = purity_source
        result.confidence += 30

    # Step 4: Extract weight
    weight, weight_source = extract_weight(title, description, max_weight=500)
    if weight:
        result.weight_grams = weight
        result.weight_source = weight_source
        result.confidence += 40

        # Calculate melt
        calc = calculate_platinum_melt(weight, platinum_spot_oz, purity or 0.950)
        result.melt_value = calc['melt_value']
        result.max_buy = calc['max_buy']

        profit = calc['max_buy'] - price
        margin_pct = (profit / price * 100) if price > 0 else 0

        if has_non_metal:
            result.confidence = max(30, result.confidence - 20)
        else:
            if profit > 50 and margin_pct > 20:
                result.is_hot = True
                purity_str = f"PT{int((purity or 0.950) * 1000)}"
                result.hot_reason = f"Verified: {weight}g {purity_str} = ${calc['melt_value']:.0f} melt, max ${calc['max_buy']:.0f}, profit ${profit:.0f}"
                result.confidence += 20
            elif profit < -30:
                result.instant_pass = True
                result.pass_reason = f"Price ${price:.0f} > max buy ${calc['max_buy']:.0f}"

    return result


# ============================================================
# PALLADIUM EXTRACTION FUNCTION
# ============================================================

def fast_extract_palladium(
    title: str,
    price: float,
    description: str = "",
    palladium_spot_oz: float = DEFAULT_PALLADIUM_OZ
) -> FastExtractResult:
    """
    Perform instant server-side extraction for palladium listings.
    """
    result = FastExtractResult()

    text = f"{title} {description}".lower()

    # Step 1: Check for partial metal items (instant PASS)
    for indicator in INSTANT_PASS_PARTIAL_METAL:
        if indicator in text:
            result.instant_pass = True
            result.pass_reason = f"Partial metal only: {indicator}"
            return result

    # Step 2: Check for non-metal components
    has_non_metal, non_metal_type = detect_non_metal(title, description)
    if has_non_metal:
        result.has_non_metal = True
        result.non_metal_type = non_metal_type
        result.confidence -= 20

    # Step 3: Extract purity
    purity, purity_source = extract_palladium_purity(title, description)
    if purity:
        result.karat = int(purity * 1000)  # Store as PD950 -> 950
        result.karat_source = purity_source
        result.confidence += 30

    # Step 4: Extract weight
    weight, weight_source = extract_weight(title, description, max_weight=500)
    if weight:
        result.weight_grams = weight
        result.weight_source = weight_source
        result.confidence += 40

        # Calculate melt
        calc = calculate_palladium_melt(weight, palladium_spot_oz, purity or 0.950)
        result.melt_value = calc['melt_value']
        result.max_buy = calc['max_buy']

        profit = calc['max_buy'] - price
        margin_pct = (profit / price * 100) if price > 0 else 0

        if has_non_metal:
            result.confidence = max(30, result.confidence - 20)
        else:
            if profit > 50 and margin_pct > 20:
                result.is_hot = True
                purity_str = f"PD{int((purity or 0.950) * 1000)}"
                result.hot_reason = f"Verified: {weight}g {purity_str} = ${calc['melt_value']:.0f} melt, max ${calc['max_buy']:.0f}, profit ${profit:.0f}"
                result.confidence += 20
            elif profit < -30:
                result.instant_pass = True
                result.pass_reason = f"Price ${price:.0f} > max buy ${calc['max_buy']:.0f}"

    return result


# ============================================================
# TEST / DEBUG
# ============================================================

if __name__ == "__main__":
    # Test gold extraction
    test_cases = [
        ("14k Gold Chain 5.5g", 250),
        ("18K Solid Gold Ring 3.2 grams", 400),
        ("Gold Filled Bracelet 10g", 100),
        ("Champion Dueber 14k Pocket Watch", 150),
        ("10K Yellow Gold Necklace 8.5 dwt", 300),
    ]
    
    print("=== GOLD EXTRACTION TESTS ===")
    for title, price in test_cases:
        result = fast_extract_gold(title, price)
        print(f"\nTitle: {title}")
        print(f"Price: ${price}")
        print(f"Karat: {result.karat} (from {result.karat_source})")
        print(f"Weight: {result.weight_grams}g (from {result.weight_source})")
        print(f"Melt: ${result.melt_value}")
        print(f"Max Buy: ${result.max_buy}")
        print(f"HOT: {result.is_hot} - {result.hot_reason}")
        print(f"PASS: {result.instant_pass} - {result.pass_reason}")
        print(f"Confidence: {result.confidence}")
