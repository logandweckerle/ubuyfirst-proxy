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


@dataclass
class MixedMetalResult:
    """Result of mixed metal extraction (sterling + gold combo)"""
    is_mixed: bool = False
    total_weight_grams: Optional[float] = None
    gold_weight_grams: Optional[float] = None
    gold_karat: Optional[int] = None
    silver_weight_grams: Optional[float] = None  # Calculated: total - gold
    gold_melt_value: Optional[float] = None
    silver_melt_value: Optional[float] = None
    total_melt_value: Optional[float] = None
    max_buy: Optional[float] = None
    confidence: int = 0
    extraction_notes: str = ""


# ============================================================
# NON-METAL DETECTION (stones, pearls, watches, etc.)
# Split into HEAVY (affects weight) vs LIGHT (negligible weight)
# ============================================================

# HEAVY non-metals - these significantly affect stated weight
# Stated weight includes substantial non-gold material
NON_METAL_HEAVY = [
    # Pearls are heavy (1g per pearl typical)
    'pearl', 'pearls',
    # Coral/jade/turquoise can be heavy chunks
    'coral', 'jade', 'turquoise',
    # Cameos - shell/stone with thin gold frame (3-4g gold typical)
    'cameo', 'shell cameo', 'carved cameo', 'hand carved',
    # Watches (have movement/crystal weight)
    'watch', 'movement',
    # Cord/fabric necklaces - gold is just clasp
    'cord', 'leather', 'silk', 'rubber', 'fabric', 'string',
    # Glass pendants
    'murano', 'glass', 'millefiori',
    # Beaded jewelry - beads are the weight
    'bead', 'beaded', 'strand',
    # Weighted/filled items (cement, pitch, plaster inside)
    'weighted', 'cement', 'reinforced', 'filled base',
    # Stainless blade/composite items (only handle is silver)
    'stainless', 'sterling handle', 'silver handle',
    # Handled flatware - knives have stainless blades + weighted/filled sterling handles
    'handled', 'knife', 'knives', 'carving set',
    # Mother of pearl inlays (handle material, not silver)
    'mother of pearl', 'mop handle',
    # Amber pendants - amber is the weight, gold is just bail
    'amber', 'baltic amber',
]

# LIGHT non-metals - negligible weight, stated weight IS the gold weight
# Diamonds: 1 carat = 0.2g (5 carats of diamonds = only 1g)
# These don't add value but also don't reduce gold weight significantly
NON_METAL_LIGHT = [
    # Diamonds and precious gems (tiny weight)
    'diamond', 'diamonds',
    'ruby', 'sapphire', 'emerald',
    'amethyst', 'garnet', 'topaz', 'aquamarine',
    'peridot', 'citrine', 'tanzanite', 'morganite', 'alexandrite',
    # Semi-precious stones (typically small accent stones)
    'opal', 'onyx', 'agate', 'carnelian', 'jasper', 'lapis', 'malachite',
    'moonstone', 'tiger eye', 'chalcedony', 'aventurine', 'bloodstone', 'quartz',
    # Carat indicators
    'cttw', 'ctw', 'carat', 'ct',
    # Generic stone terms (usually small accent stones)
    'stone', 'gemstone', 'gem', 'crystal',
]

# Combined for backwards compatibility (but heavy is what matters for deductions)
NON_METAL_INDICATORS = NON_METAL_HEAVY + NON_METAL_LIGHT

# Pattern for carat weight (e.g., "0.5 ct", "1ct", ".25 ct") - requires digit before ct
CARAT_WEIGHT_PATTERN = re.compile(r'\d+\.?\d*\s*ct\b', re.IGNORECASE)

# Items where melt calculation is IMPOSSIBLE for GOLD - instant PASS
# These have partial gold content where you can't calculate value from total weight
INSTANT_PASS_PARTIAL_GOLD = [
    'gold handle',  # Only handle is gold, blade/body is steel
    'stainless blade', 'stainless steel blade',  # Gold-handled with steel blade
]

# Items where melt calculation is IMPOSSIBLE for SILVER - instant PASS
# Clasp-only items: stated weight is beads/cord/stones, NOT silver
# Silver clasp typically weighs 1-5g regardless of total weight
INSTANT_PASS_SILVER_CLASP = [
    'silver clasp', '925 clasp', 'sterling clasp', '.925 clasp',
    '925 silver clasp', 'sterling silver clasp',
    'clasp 925', 'clasp sterling', 'clasp silver',
]

# Beaded necklaces with silver clasp - the weight is beads, not silver
INSTANT_PASS_BEADED_SILVER = [
    'beaded necklace', 'bead necklace', 'beaded bracelet',
    'pearl necklace 925', 'pearl strand 925', 'pearl strand sterling',
    'gemstone necklace 925', 'stone necklace 925',
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
    Detect if item has HEAVY non-metal that affects weight calculation.

    HEAVY non-metals (pearls, coral, beads) = True (need weight deduction)
    LIGHT non-metals (diamonds, gems) = False (negligible weight, stated weight IS gold weight)

    Returns (has_heavy_non_metal, detected_type)
    """
    text = f"{title} {description}".lower()

    # Helper to check if a stone is heavy or light
    def is_heavy_stone(stone_name: str) -> bool:
        stone_lower = stone_name.lower()
        for heavy in NON_METAL_HEAVY:
            if heavy in stone_lower:
                return True
        return False

    # Check item specifics for MainStone
    if item_specifics:
        main_stone = str(item_specifics.get('MainStone', '') or '').lower().strip()
        if main_stone and main_stone not in ['no stone', 'none', 'n/a', 'na', '']:
            # Only flag as non-metal if it's HEAVY
            if is_heavy_stone(main_stone):
                return True, f"MainStone: {main_stone}"
            # Light stones (diamond, ruby, etc.) - don't flag, weight IS gold weight
            # Just note it for reference but don't require weight deduction

    # Check for HEAVY non-metal indicators in text
    for indicator in NON_METAL_HEAVY:
        if indicator in text:
            return True, indicator

    # LIGHT non-metals (diamonds, gems) - stated weight IS the gold weight
    # These don't add value but don't need weight deduction
    # Return False - no weight deduction needed

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
WEIGHT_GRAM_PATTERN = re.compile(r'(\d*\.?\d+)\s*(?:g(?:ram)?s?|gm|gms)\b', re.IGNORECASE)
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
# MIXED METAL EXTRACTION (Sterling + Gold combos)
# ============================================================

# Patterns for detecting explicit gold weight in mixed metal items
# e.g., "12 Grams 14K", "14K 12g", "12g of 14K gold"
MIXED_GOLD_WEIGHT_PATTERN = re.compile(
    r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\s*(?:of\s+)?(\d{1,2})\s*k(?:t|arat)?|'  # "12 grams 14K" or "12g of 14K"
    r'(\d{1,2})\s*k(?:t|arat)?\s*(?:gold\s+)?(\d+\.?\d*)\s*(?:g(?:ram)?s?)',  # "14K 12g" or "14K gold 12g"
    re.IGNORECASE
)

# Pattern for total weight indicator
TOTAL_WEIGHT_PATTERN = re.compile(
    r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)?\s*(?:total\s*weight|total|tw|gtw)|'  # "48.48g total weight"
    r'(?:total\s*weight|total|tw|gtw)\s*(?:of\s+)?(\d+\.?\d*)\s*(?:g(?:ram)?s?)?',  # "total weight 48.48g"
    re.IGNORECASE
)


def extract_mixed_metal_weights(title: str, description: str = "") -> MixedMetalResult:
    """
    Extract weights from mixed sterling+gold items where both weights are explicitly stated.

    Example: "48.48 Grams Total Weight Sterling Silver Rope Twist Cuff Bracelet 12 Grams 14K"
    - Total: 48.48g
    - Gold (14K): 12g
    - Silver (calculated): 48.48 - 12 = 36.48g

    Returns MixedMetalResult with breakdown.
    """
    result = MixedMetalResult()
    text = f"{title} {description}".replace('+', ' ').lower()

    # Check if this looks like a mixed metal item (has both sterling/silver AND gold karat)
    has_silver = any(p.search(text) for p in [
        re.compile(r'\bsterling\b', re.IGNORECASE),
        re.compile(r'\b925\b'),
        re.compile(r'\b\.925\b'),
    ])
    has_gold_karat = bool(re.search(r'\b(10|14|18|22|24)\s*k(?:t|arat)?\b', text, re.IGNORECASE))

    if not (has_silver and has_gold_karat):
        return result  # Not a mixed metal item

    # Try to find explicit gold weight with karat
    gold_weight = None
    gold_karat = None

    gold_match = MIXED_GOLD_WEIGHT_PATTERN.search(text)
    if gold_match:
        groups = gold_match.groups()
        if groups[0] and groups[1]:  # "12 grams 14K" pattern
            gold_weight = float(groups[0])
            gold_karat = int(groups[1])
        elif groups[2] and groups[3]:  # "14K 12g" pattern
            gold_karat = int(groups[2])
            gold_weight = float(groups[3])

    if not gold_weight or not gold_karat:
        return result  # Couldn't extract explicit gold weight

    # Try to find total weight
    total_weight = None

    total_match = TOTAL_WEIGHT_PATTERN.search(text)
    if total_match:
        groups = total_match.groups()
        total_weight = float(groups[0]) if groups[0] else (float(groups[1]) if groups[1] else None)

    # If no "total" indicator, look for the first/largest weight that's bigger than gold weight
    if not total_weight:
        all_weights = re.findall(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', text)
        for w in all_weights:
            w_float = float(w)
            if w_float > gold_weight and w_float < 5000:  # Must be larger than gold, sanity check
                total_weight = w_float
                break

    if not total_weight or total_weight <= gold_weight:
        return result  # Invalid weights

    # Calculate silver weight
    silver_weight = total_weight - gold_weight

    if silver_weight < 0.5:  # Sanity check - at least 0.5g silver
        return result

    # Success - populate result
    result.is_mixed = True
    result.total_weight_grams = total_weight
    result.gold_weight_grams = gold_weight
    result.gold_karat = gold_karat
    result.silver_weight_grams = silver_weight
    result.confidence = 80
    result.extraction_notes = f"Total {total_weight}g = {gold_weight}g {gold_karat}K gold + {silver_weight:.2f}g sterling"

    return result


def fast_extract_mixed_metal(
    title: str,
    price: float,
    description: str = "",
    gold_spot_oz: float = DEFAULT_GOLD_OZ,
    silver_spot_oz: float = DEFAULT_SILVER_OZ,
) -> Optional[FastExtractResult]:
    """
    Extract and calculate value for mixed sterling+gold items with explicit weight breakdown.

    Returns FastExtractResult with combined melt value, or None if not a valid mixed metal item.
    """
    mixed = extract_mixed_metal_weights(title, description)

    if not mixed.is_mixed:
        return None

    # Calculate gold melt
    gold_calc = calculate_gold_melt(mixed.gold_weight_grams, mixed.gold_karat, gold_spot_oz)
    mixed.gold_melt_value = gold_calc['melt_value']

    # Calculate silver melt (sterling = 0.925 purity)
    silver_calc = calculate_silver_melt(mixed.silver_weight_grams, silver_spot_oz, purity=0.925)
    mixed.silver_melt_value = silver_calc['melt_value']

    # Combined value
    mixed.total_melt_value = mixed.gold_melt_value + mixed.silver_melt_value
    mixed.max_buy = mixed.total_melt_value * 0.90  # 90% of melt

    # Build FastExtractResult
    result = FastExtractResult()
    result.weight_grams = mixed.total_weight_grams
    result.weight_source = "mixed_metal_extraction"
    result.karat = mixed.gold_karat
    result.karat_source = "mixed_metal_extraction"
    result.melt_value = mixed.total_melt_value
    result.max_buy = mixed.max_buy
    result.confidence = mixed.confidence

    profit = mixed.max_buy - price
    margin_pct = (profit / price * 100) if price > 0 else 0

    if profit > 50 and margin_pct > 15:
        result.is_hot = True
        result.hot_reason = (
            f"MIXED METAL: {mixed.gold_weight_grams}g {mixed.gold_karat}K (${mixed.gold_melt_value:.0f}) + "
            f"{mixed.silver_weight_grams:.1f}g sterling (${mixed.silver_melt_value:.0f}) = "
            f"${mixed.total_melt_value:.0f} total, max ${mixed.max_buy:.0f}, profit ${profit:.0f}"
        )
    elif profit < -30:
        result.instant_pass = True
        result.pass_reason = f"Mixed metal: price ${price:.0f} > max buy ${mixed.max_buy:.0f}"

    return result


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
    max_buy = melt_value * 0.70  # 70% ceiling for silver
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

    # Step 1.6: LUXURY JEWELRY BRANDS - flag for brand-based valuation, NOT melt
    # These brands are valued by design/brand, NOT gold weight
    # Don't instant-pass (could be underpriced), but prevent melt-based BUY decisions
    LUXURY_JEWELRY_BRANDS = [
        'van cleef', 'vancleef', 'vca ',  # Van Cleef & Arpels
        'cartier',
        'bulgari', 'bvlgari',
        'harry winston',
        'chopard',
        'graff',
        'piaget',
        'boucheron',
        'david yurman',
        'roberto coin',
        'pomellato',
        'mikimoto',
        'fred leighton',
        'jar ',  # Joel Arthur Rosenthal (with space to avoid false matches)
        'chaumet',
        'mauboussin',
        'messika',
        'buccellati',
        'verdura',
        'belperron',
        'suzanne belperron',
        'alhambra',  # Van Cleef signature collection
        'juste un clou',  # Cartier signature
        'love bracelet',  # Cartier signature
        'trinity',  # Cartier signature ring/bracelet
        'panthere',  # Cartier signature
        'serpenti',  # Bulgari signature
    ]

    for brand in LUXURY_JEWELRY_BRANDS:
        if brand in text:
            # Flag as luxury - prevents melt-based instant decisions
            result.has_non_metal = True  # Reuse this flag to prevent instant BUY
            result.non_metal_type = f"LUXURY_BRAND:{brand}"
            result.confidence = 30  # Low confidence - needs brand expertise
            # Don't return - let AI analyze for brand value
            break

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

    # Step 2.6: GOLD JEWELRY WEIGHT ESTIMATION
    # For items without stated weight, estimate based on item type
    # Heavy indicators flag items that may be large/valuable
    HEAVY_GOLD_INDICATORS = [
        'signet', 'shield', 'chunky', 'thick', 'heavy', 'massive', 'wide band',
        'solid', 'substantial', 'large', 'big', 'oversized', 'mens ring',
        "men's ring", 'class ring', 'college ring', 'championship', 'nugget',
        'cuban', 'miami cuban', 'rope chain', 'franco', 'herringbone',
        'byzantine', 'figaro', 'mariner', 'anchor', 'box chain',
        'tennis bracelet', 'bangle', 'cuff bracelet', 'id bracelet',
    ]

    # Gold jewelry weight estimates (grams) - conservative estimates
    GOLD_WEIGHT_ESTIMATES = {
        # Rings
        'signet ring': 12,      # Signet/shield rings are heavy (10-20g)
        'shield ring': 12,
        'class ring': 15,       # Class rings are very heavy
        'college ring': 15,
        'mens ring': 8,         # Men's rings heavier than ladies
        "men's ring": 8,
        'wedding band': 4,      # Standard wedding bands
        'ring': 3,              # Default ring (ladies)

        # Chains (per inch, multiply by length if known)
        'cuban chain': 0.8,     # Cuban links are heavy (per inch)
        'miami cuban': 1.0,     # Miami Cuban even heavier
        'rope chain': 0.4,      # Rope chains moderate
        'franco chain': 0.5,
        'herringbone': 0.3,
        'figaro chain': 0.3,
        'box chain': 0.2,
        'chain': 0.15,          # Default thin chain

        # Bracelets
        'tennis bracelet': 12,  # Tennis bracelets have gold between stones
        'cuban bracelet': 15,   # Cuban link bracelets heavy
        'bangle': 10,           # Solid bangles
        'cuff bracelet': 15,    # Cuff bracelets heavy
        'id bracelet': 12,      # ID bracelets
        'bracelet': 8,          # Default bracelet

        # Necklaces (total weight)
        'cuban necklace': 25,   # Cuban link necklaces heavy
        'rope necklace': 15,
        'herringbone necklace': 12,
        'necklace': 8,          # Default necklace

        # Other
        'pendant': 3,
        'earrings': 2,          # Per pair
        'nugget': 5,            # Gold nugget jewelry
    }

    # Check for heavy indicators (flag for AI attention)
    is_potentially_heavy = False
    heavy_reason = ""
    for indicator in HEAVY_GOLD_INDICATORS:
        if indicator in text:
            is_potentially_heavy = True
            heavy_reason = indicator
            break

    # Estimate weight if none found and we can identify item type
    if not result.weight_grams and not has_non_metal:
        estimated_weight = None
        estimate_type = None

        # Check if this is a SET or LOT (multiple items) - sum all found items
        is_set = any(kw in text for kw in ['set', 'lot', 'collection', 'suite'])

        if is_set:
            # For sets: sum weights of all items found
            total_weight = 0
            found_items = []
            used_categories = set()  # Avoid double-counting (e.g., 'bracelet' and 'cuban bracelet')

            for item_type, weight in sorted(GOLD_WEIGHT_ESTIMATES.items(), key=lambda x: -len(x[0])):
                if item_type in text:
                    # Check if we already counted a more specific version
                    base_type = item_type.split()[-1]  # 'cuban bracelet' -> 'bracelet'
                    if base_type in used_categories:
                        continue
                    used_categories.add(base_type)
                    used_categories.add(item_type)
                    total_weight += weight
                    found_items.append(f"{item_type}:{weight}g")

            if total_weight >= 5:  # Sets should have meaningful weight
                estimated_weight = total_weight
                estimate_type = f"set({'+'.join(found_items)})"
        else:
            # Single item: pick first (most specific) match
            for item_type, weight in sorted(GOLD_WEIGHT_ESTIMATES.items(), key=lambda x: -len(x[0])):
                if item_type in text:
                    estimated_weight = weight
                    estimate_type = item_type
                    break

        # For chains, try to detect length and multiply
        if estimate_type and 'chain' in estimate_type and 'set' not in estimate_type:
            # Look for length indicators
            length_match = re.search(r'(\d+)\s*(?:inch|in|")', text)
            if length_match:
                length = int(length_match.group(1))
                if 14 <= length <= 30:  # Reasonable necklace length
                    estimated_weight = estimated_weight * length
                    estimate_type = f"{estimate_type} {length}in"

        if estimated_weight and estimated_weight >= 2:  # Only estimate if >= 2g
            result.weight_grams = estimated_weight
            result.weight_source = f"estimate:{estimate_type}"
            result.confidence = min(45, result.confidence)  # Cap at 45 for estimates

    # Flag potentially heavy items for AI attention (even if we couldn't estimate)
    if is_potentially_heavy and price > 200:
        result.hot_reason = f"HEAVY GOLD INDICATOR: '{heavy_reason}' @ ${price:.0f} - may be large/valuable"

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

    # Step 4.5: WEIGHT SANITY CHECK for dainty/thin items
    # A "dainty 1mm 18" chain" should weigh ~1-2g, NOT 8g
    # If title describes very light item but weight is high, flag as suspicious
    DAINTY_INDICATORS = [
        'dainty', 'delicate', 'thin', 'petite', 'tiny', 'mini',
        '1mm', '0.5mm', '0.8mm', '.5mm', '.8mm',  # Very thin chains
        'baby chain', 'child chain', "children's",
    ]
    DAINTY_MAX_WEIGHT = 3.5  # Max grams for truly dainty items

    text = f"{title} {description}".lower()
    is_dainty = any(indicator in text for indicator in DAINTY_INDICATORS)

    if is_dainty and weight and weight > DAINTY_MAX_WEIGHT:
        # Weight is suspicious for a dainty item - don't trust it
        result.has_non_metal = True  # Flag to prevent instant decisions
        result.non_metal_type = f"SUSPICIOUS_WEIGHT: '{weight}g' too heavy for dainty item"
        result.confidence = min(40, result.confidence)  # Cap confidence
        # Store the weight discrepancy for AI review
        result.weight_source = f"SUSPICIOUS:{result.weight_source}:stated_{weight}g_but_dainty"

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

            # Price/gram ceiling removed - gold prices have risen significantly
            # Let AI make the decision based on current spot prices

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

    # Step 1.2: Check for clasp-only items (instant PASS)
    # Stated weight is beads/cord/stones, silver clasp is only 1-5g
    for indicator in INSTANT_PASS_SILVER_CLASP:
        if indicator in text:
            result.instant_pass = True
            result.pass_reason = f"Clasp only - stated weight is not silver: {indicator}"
            return result

    # Step 1.3: Check for beaded necklaces with silver clasp (instant PASS)
    for indicator in INSTANT_PASS_BEADED_SILVER:
        if indicator in text:
            result.instant_pass = True
            result.pass_reason = f"Beaded item - stated weight is beads, not silver: {indicator}"
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
