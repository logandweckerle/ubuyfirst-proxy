"""
Pipeline Validation Module

Server-side validation of AI analysis results.
Recalculates margins, validates weights, and catches AI hallucinations.

Functions:
- validate_and_fix_margin: Main validation for gold/silver/TCG items
"""

import re
import logging
import traceback
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION - Set by main.py at startup
# ============================================================
class ValidationConfig:
    """Configuration container for validation module"""
    # Spot prices function
    get_spot_prices = None
    
    # Spot prices dict reference
    SPOT_PRICES: Dict = {}
    
    # Rate constants
    GOLD_SELL_RATE: float = 0.96
    GOLD_MAX_BUY_RATE: float = 0.90
    SILVER_SELL_RATE: float = 0.82
    SILVER_MAX_BUY_RATE: float = 0.70

    # Native American jewelry max multiplier (4x melt value cap)
    NATIVE_MAX_MELT_MULTIPLIER: float = 4.0


# Global config instance
config = ValidationConfig()


def configure_validation(
    get_spot_prices,
    spot_prices: Dict,
    gold_sell_rate: float = 0.96,
    gold_max_buy_rate: float = 0.90,
    silver_sell_rate: float = 0.82,
    silver_max_buy_rate: float = 0.70,
):
    """Configure validation module with dependencies from main.py"""
    config.get_spot_prices = get_spot_prices
    config.SPOT_PRICES = spot_prices
    config.GOLD_SELL_RATE = gold_sell_rate
    config.GOLD_MAX_BUY_RATE = gold_max_buy_rate
    config.SILVER_SELL_RATE = silver_sell_rate
    config.SILVER_MAX_BUY_RATE = silver_max_buy_rate
    logger.info(f"[VALIDATION] Configured: gold rates {gold_sell_rate}/{gold_max_buy_rate}, silver rates {silver_sell_rate}/{silver_max_buy_rate}")


# Gold weight extraction from reasoning (pre-compiled for performance)
# Gold weight extraction from reasoning (for validate_and_fix_margin)

GOLD_WEIGHT_PATTERNS = [

    re.compile(r'(?:leaving\s+)?only\s*~?\s*(\d+(?:\.\d+)?)\s*g(?:rams?)?\s*(?:of\s+)?(?:\d+k\s+)?(?:gold)?', re.IGNORECASE),

    re.compile(r'~(\d+(?:\.\d+)?)\s*g(?:rams?)?\s*(?:of\s+)?(?:\d+k\s+)?gold', re.IGNORECASE),

    re.compile(r'(?:approximately|approx\.?|about)\s*(\d+(?:\.\d+)?)\s*g(?:rams?)?\s*(?:of\s+)?gold', re.IGNORECASE),

    re.compile(r'(?:equals?|=|leaves?|net|actual)\s*(\d+(?:\.\d+)?)\s*g(?:rams?)?\s*(?:gold|actual|net)?', re.IGNORECASE),

    re.compile(r'(?:deduction\s+)?leaves?\s*(\d+(?:\.\d+)?)\s*g', re.IGNORECASE),

    re.compile(r'(\d+(?:\.\d+)?)\s*g(?:rams?)?\s*(?:gold|actual|net)\s*(?:weight)?', re.IGNORECASE),

    re.compile(r'gold\s*(?:weight)?[:\s]*(\d+(?:\.\d+)?)\s*g', re.IGNORECASE),

    re.compile(r'(\d+(?:\.\d+)?)\s*g(?:rams?)?\s+(?:in\s+the\s+)?bail', re.IGNORECASE),

    re.compile(r'bail\s+(?:is\s+)?(?:only\s+)?~?(\d+(?:\.\d+)?)\s*g', re.IGNORECASE),

]


# Helper to get spot prices with fallback
def get_spot_prices():
    """Get current spot prices from config or fallback"""
    if config.get_spot_prices:
        return config.get_spot_prices()
    return config.SPOT_PRICES


# ============================================================
# WEIGHT SANITY CHECK
# ============================================================
# Typical weight ranges by item type (in grams)
WEIGHT_LIMITS = {
    # Gold jewelry - lighter due to expense
    'ring': {'gold': 30, 'silver': 50},
    'earring': {'gold': 20, 'silver': 40},
    'pendant': {'gold': 40, 'silver': 80},
    'charm': {'gold': 20, 'silver': 40},
    'necklace': {'gold': 150, 'silver': 300},  # Heavy chains exist but rare
    'chain': {'gold': 150, 'silver': 300},
    'bracelet': {'gold': 100, 'silver': 200},
    'bangle': {'gold': 80, 'silver': 150},
    'brooch': {'gold': 50, 'silver': 100},
    'pin': {'gold': 30, 'silver': 60},
    # Silver-specific items can be heavier
    'flatware': {'silver': 800},  # Full set can be heavy
    'spoon': {'silver': 80},
    'fork': {'silver': 80},
    'knife': {'silver': 100},
    'ladle': {'silver': 200},
    'tray': {'silver': 1500},
    'bowl': {'silver': 500},
    'cup': {'silver': 200},
    'candlestick': {'silver': 400},
    'vase': {'silver': 500},
}


def check_weight_sanity(weight: float, title: str, category: str) -> tuple:
    """
    Check if weight is realistic for the item type.

    Returns: (is_sane, message)
    - is_sane: True if weight seems reasonable, False if suspicious
    - message: Explanation if weight is suspicious
    """
    if not weight or weight <= 0:
        return True, ""  # No weight to check

    title_lower = title.lower()

    # Detect item type from title
    detected_type = None
    for item_type in WEIGHT_LIMITS.keys():
        if item_type in title_lower:
            detected_type = item_type
            break

    # Also check for plurals
    if not detected_type:
        for item_type in WEIGHT_LIMITS.keys():
            if item_type + 's' in title_lower or item_type + 'es' in title_lower:
                detected_type = item_type
                break

    if not detected_type:
        # Can't determine item type, allow it but with a general limit
        if category == 'gold' and weight > 200:
            return False, f"SUSPICIOUS WEIGHT: {weight}g is very heavy for gold jewelry (unknown type)"
        elif category == 'silver' and weight > 1000:
            return False, f"SUSPICIOUS WEIGHT: {weight}g is very heavy for silver (unknown type)"
        return True, ""

    # Get limit for this item type and category
    limits = WEIGHT_LIMITS.get(detected_type, {})
    max_weight = limits.get(category) or limits.get('silver', 500)  # Default to silver limit

    if weight > max_weight:
        return False, f"SUSPICIOUS WEIGHT: {weight}g exceeds typical {detected_type} limit ({max_weight}g for {category})"

    return True, ""


def validate_and_fix_margin(result: dict, listing_price, category: str, title: str = "", data: dict = None) -> dict:

    """

    Server-side validation of AI's math.

    Recalculates melt, maxBuy, sellPrice, and Profit.

    PASS if listingPrice > maxBuy.

    

    GOLD: maxBuy = melt x 0.90, sellPrice = melt x 0.96

    SILVER: maxBuy = melt x 0.70, sellPrice = melt x 0.82

    Profit = sellPrice - listingPrice

    """

    if data is None:

        data = {}

    

    # FIX: Initialize max_buy to prevent UnboundLocalError in edge cases

    max_buy = 0

    melt_value = 0

    metal_weight = 0

    

    # =================================================================

    # CRITICAL FIX: Extract weight from title and validate AI's weight

    # AI often hallucinates weights - if title has stated weight, use it!

    # =================================================================

    if category in ['gold', 'silver'] and title:

        try:


            # Clean title: replace + with space, decode URL encoding

            title_clean = title.replace('+', ' ').lower()

            

            # Extract weight from title using various patterns

            title_weight = None

            title_weight_source = None

            

            # Pattern: "16 grams", "16g", "16 gram", "16.5g", ".28 grams", "0.28g"
            # Support leading decimal (e.g., ".28" = 0.28)
            gram_match = re.search(r'(\d*\.?\d+)\s*(?:g(?:ram)?s?)\b', title_clean)

            if gram_match:

                title_weight = float(gram_match.group(1))

                title_weight_source = "title (grams)"

            

            # Pattern: "10.5 dwt", ".5 dwt"

            if not title_weight:

                dwt_match = re.search(r'(\d*\.?\d+)\s*dwt\b', title_clean)

                if dwt_match:

                    title_weight = float(dwt_match.group(1)) * 1.555

                    title_weight_source = "title (dwt)"

            

            # Pattern: "1.5 oz", ".8 oz", "0.8 oz"
            # Use (\d*\.?\d+) to support leading decimal like ".8"

            if not title_weight:

                oz_match = re.search(r'(\d*\.?\d+)\s*(?:oz|ounce)s?\b', title_clean)

                if oz_match:

                    title_weight = float(oz_match.group(1)) * 31.1035

                    title_weight_source = "title (oz)"

            # If no weight in title, check description
            if not title_weight and data:
                desc = str(data.get('Description', data.get('description', ''))).lower()
                if desc:
                    # Try grams in description
                    desc_gram = re.search(r'(\d*\.?\d+)\s*(?:g(?:ram)?s?)\b', desc)
                    if desc_gram:
                        title_weight = float(desc_gram.group(1))
                        title_weight_source = "description (grams)"
                    # Try oz in description
                    if not title_weight:
                        desc_oz = re.search(r'(\d*\.?\d+)\s*(?:oz|ounce)s?\b', desc)
                        if desc_oz:
                            title_weight = float(desc_oz.group(1)) * 31.1035
                            title_weight_source = "description (oz)"
                    # Try dwt in description
                    if not title_weight:
                        desc_dwt = re.search(r'(\d*\.?\d+)\s*dwt\b', desc)
                        if desc_dwt:
                            title_weight = float(desc_dwt.group(1)) * 1.555
                            title_weight_source = "description (dwt)"

            # Gold rarely exceeds 500g, but silver flatware can be 1-3kg+
            max_weight = 3000 if category == 'silver' else 500

            # === CARVED JADE PENDANT CHECK ===
            # For jade/jadeite pendants, the stated weight includes the jade stone!
            # Only the bail is gold (~1-2g), NOT the full weight
            is_jade_pendant = (
                ('jade' in title_clean or 'jadeite' in title_clean) and
                any(term in title_clean for term in ['pendant', 'carved', 'charm', 'disc', 'rabbit', 'buddha', 'dragon'])
            )
            if is_jade_pendant and category == 'gold':
                logger.info(f"[CALC] JADE PENDANT DETECTED: Stated weight {title_weight}g includes jade stone")
                logger.info(f"[CALC] JADE PENDANT: Using bail-only weight (1.5g default) - jade value is subjective")
                title_weight = 1.5  # Only the bail is gold
                title_weight_source = "jade pendant (bail only)"
                result['itemtype'] = 'JadePendant(carved)'
                result['Recommendation'] = 'RESEARCH'
                result['reasoning'] = f"JADE PENDANT: Stated weight includes jade stone - only bail (~1.5g) is gold. Jade value is subjective. " + result.get('reasoning', '')

            if title_weight and 0.1 <= title_weight <= max_weight:  # Lowered min from 0.5 to 0.1 for small items

                logger.info(f"[CALC] Title weight extracted: {title_weight}g from {title_weight_source}")

                

                # Get AI's weight

                ai_weight_str = result.get('weight', result.get('goldweight', result.get('silverweight', '')))

                ai_weight = None

                if ai_weight_str:

                    try:

                        ai_weight = float(str(ai_weight_str).replace('g', '').replace('G', '').strip())

                    except:

                        pass

                

                # CRITICAL FIX: If title has explicit weight, ALWAYS mark as 'stated'
                # This ensures we trust seller-stated weights in titles like "6 Grams"

                if ai_weight and title_weight:
                    ratio = ai_weight / title_weight if title_weight > 0 else 999

                    # ALWAYS use title/description weight over AI weight - seller stated weight is authoritative
                    # AI often hallucinates higher weights (e.g., 110g vs stated 62g)
                    if ratio > 1.3 or ratio < 0.7:
                        # AI weight differs by more than 30% from stated - clear hallucination
                        logger.warning(f"[CALC] WEIGHT HALLUCINATION: AI={ai_weight}g vs stated={title_weight}g (ratio={ratio:.1f}x) - using stated weight")
                    else:
                        logger.info(f"[CALC] AI weight {ai_weight}g ~= stated weight {title_weight}g - using stated weight")

                    # ALWAYS use stated weight - it's authoritative
                    if category == 'gold':
                        result['goldweight'] = str(title_weight)
                        result['weight'] = f"{title_weight}g"
                    else:
                        result['silverweight'] = str(title_weight)
                        result['weight'] = f"{title_weight}g"

                    result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Using stated weight {title_weight}g from {title_weight_source}]"

                    # ALWAYS mark as 'stated' since weight is explicitly in title/description
                    result['weightSource'] = 'stated'

                # Even if AI didn't provide weight, if title has it, use it
                elif title_weight and not ai_weight:

                    logger.info(f"[CALC] Using title weight: {title_weight}g from {title_weight_source}")

                    if category == 'gold':

                        result['goldweight'] = str(title_weight)

                        result['weight'] = f"{title_weight}g"

                    else:

                        result['silverweight'] = str(title_weight)

                        result['weight'] = f"{title_weight}g"

                    result['weightSource'] = 'stated'

        

        except Exception as e:

            logger.debug(f"[CALC] Title weight extraction error: {e}")

    

    try:

        # === UNCERTAINTY CHECK (applies to all categories) ===

        # If AI expresses doubt/uncertainty but still says BUY, force RESEARCH

        reasoning_text = str(result.get('reasoning', '')).lower()

        

        uncertainty_phrases = [

            'cannot verify', 'without images', 'need visual', 'unable to confirm',

            'need verification', 'seems optimistic', 'uncertain', 'hard to tell',

            'cannot determine', 'impossible to verify', 'no images', 'missing images',

            'requires inspection', 'need actual images', 'need to see', 'break-even or loss'

        ]

        

        # Check confidence value

        conf_raw = result.get('confidence', 50)

        if isinstance(conf_raw, str):

            if conf_raw.lower().startswith('high'):

                conf_val = 80

            elif conf_raw.lower().startswith('med'):

                conf_val = 60

            elif conf_raw.lower().startswith('low'):

                conf_val = 40

            else:

                try:

                    conf_val = int(conf_raw.split()[0])

                except:

                    conf_val = 50

        else:

            conf_val = int(conf_raw) if conf_raw else 50

        

        has_uncertainty = any(phrase in reasoning_text for phrase in uncertainty_phrases)

        

        if result.get('Recommendation') == 'BUY' and (conf_val <= 50 or has_uncertainty):

            logger.warning(f"[CALC] UNCERTAINTY DETECTED: conf={conf_val}, phrases={has_uncertainty}")

            result['Recommendation'] = 'RESEARCH'

            result['reasoning'] = result.get('reasoning', '') + " | SERVER: Low confidence/uncertainty - downgraded to RESEARCH"

            logger.info(f"[CALC] Override: BUY->RESEARCH (uncertainty detected)")

    

    except Exception as e:

        logger.debug(f"[CALC] Uncertainty check error: {e}")

    

    try:

        # Clean listing price (handle strings like "$1499" or "1499")

        if isinstance(listing_price, str):

            listing_price = float(listing_price.replace('$', '').replace(',', ''))

        else:

            listing_price = float(listing_price)

        

        # Get spot prices

        gold_oz = config.SPOT_PRICES.get("gold_oz", 2650)

        silver_oz = config.SPOT_PRICES.get("silver_oz", 30)

        

        # Karat rates

        karat_rates = {

            "10K": gold_oz / 31.1035 * 0.417,

            "14K": gold_oz / 31.1035 * 0.583,

            "18K": gold_oz / 31.1035 * 0.75,

            "22K": gold_oz / 31.1035 * 0.917,

            "24K": gold_oz / 31.1035,

        }

        sterling_rate = silver_oz / 31.1035 * 0.925

        # Note: Rate constants (GOLD_SELL_RATE, GOLD_MAX_BUY_RATE, etc.) imported from utils.constants

        # Get metal weight (after deductions) - PRIORITIZE goldweight/silverweight!

        if category == "gold":

            # For gold, MUST use goldweight (after stone/pearl deductions), not total weight

            weight_str = str(result.get('goldweight', '0'))

            total_weight_str = str(result.get('weight', '0'))

            itemtype = str(result.get('itemtype', '')).lower()

            reasoning_text = str(result.get('reasoning', '')).lower()

            

            # Parse total weight

            total_weight_clean = total_weight_str.replace('g', '').replace(' est', '').replace('NA', '0').replace('--', '0').strip()

            if ' ' in total_weight_clean:

                total_weight_clean = total_weight_clean.split()[0]

            try:

                total_weight = float(total_weight_clean) if total_weight_clean else 0

            except:

                total_weight = 0

            

            # === REASONING VS FIELD CONSISTENCY CHECK ===

            # AI sometimes calculates correctly in reasoning but puts wrong value in field

            

            # Use pre-compiled GOLD_WEIGHT_PATTERNS for performance

            reasoning_gold_weight = None

            for pattern in GOLD_WEIGHT_PATTERNS:

                match = pattern.search(reasoning_text)

                if match:

                    extracted_weight = float(match.group(1))

                    # Sanity check: if extracted weight is very small (<3g) and field weight is much larger,

                    # this is likely the "real" gold weight (bail only, clasp only, etc.)

                    if extracted_weight < 3 and reasoning_gold_weight is None:

                        reasoning_gold_weight = extracted_weight

                        logger.info(f"[CALC] Extracted small gold weight from reasoning: {extracted_weight}g")

                        break

                    elif reasoning_gold_weight is None:

                        reasoning_gold_weight = extracted_weight

                        break

            

            if reasoning_gold_weight is not None:

                field_gold_weight = float(weight_str.replace('g', '').strip()) if weight_str.replace('g', '').strip().replace('.', '').isdigit() else 0

                

                # If reasoning says different weight than field, trust reasoning calculation

                if field_gold_weight > 0 and abs(reasoning_gold_weight - field_gold_weight) > 0.5:

                    logger.warning(f"[CALC] MISMATCH: Reasoning says {reasoning_gold_weight}g gold, field shows {field_gold_weight}g - using reasoning value!")

                    result['goldweight'] = f"{reasoning_gold_weight:.1f}"

                    weight_str = f"{reasoning_gold_weight}"

                    # Update metal_weight for later calculations

                    metal_weight = reasoning_gold_weight

            

            # === COLLECTIBLE/NON-SCRAP VALUE DETECTION ===

            # If AI says the item's value is based on collectible/shell/carved/artistic value

            # and NOT gold content, it should be PASS (we only buy for scrap)

            non_scrap_indicators = [

                'collectible value', 'carved shell', 'shell value', 'artistic value',

                'not gold content', 'relies entirely on', 'antique value', 'cameo value',

                'decorative value', 'collector value', 'numismatic', 'not scrap',

                '8x over scrap', '10x over scrap', '5x over scrap', 'over scrap value'

            ]

            

            is_collectible_priced = any(indicator in reasoning_text for indicator in non_scrap_indicators)

            

            if is_collectible_priced:

                logger.warning(f"[CALC] COLLECTIBLE PRICING DETECTED - value not based on gold content")

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + " [SERVER: Price based on collectible value, not scrap - PASS]"

            

            # === WATCH-SPECIFIC: Check if scale shows case without movement ===

            is_watch = 'watch' in itemtype or 'watch' in title.lower()

            if is_watch:

                # Look for scale weight in reasoning

                scale_match = re.search(r'(?:scale|weighs?|shows?)\s*(\d+(?:\.\d+)?)\s*g', reasoning_text)

                movement_removed = 'movement removed' in reasoning_text or 'without movement' in reasoning_text or 'case only' in reasoning_text

                

                if scale_match and movement_removed:

                    scale_weight = float(scale_match.group(1))

                    # Scale shows case without movement - only deduct glass (~0.4g)

                    glass_deduct = 0.4

                    actual_gold = scale_weight - glass_deduct

                    logger.info(f"[CALC] WATCH: Scale shows {scale_weight}g (movement already removed), glass {glass_deduct}g = {actual_gold}g gold")

                    result['goldweight'] = f"{actual_gold:.1f}"

                    weight_str = f"{actual_gold}"

            

            # === BEADED NECKLACE DETECTION ===

            # Beaded necklaces (pearl, gemstone, spinel, jade, coral, turquoise, etc.)

            # have 90-95% bead weight - only clasp + spacer beads are gold (2-8g max)

            

            # Bead/stone types that indicate beaded construction

            bead_stones = ['pearl', 'spinel', 'jade', 'coral', 'turquoise', 'onyx', 'agate', 

                          'lapis', 'malachite', 'amber', 'garnet', 'amethyst', 'quartz',

                          'carnelian', 'obsidian', 'hematite', 'tiger eye', 'opal bead']

            

            # Check title and reasoning for beaded necklace indicators

            title_lower = title.lower() if title else ""

            is_bead_necklace = False

            detected_bead_type = None

            

            # Check for bead stone types + necklace/bracelet/strand

            for stone in bead_stones:

                if stone in title_lower or stone in reasoning_text:

                    if any(item in title_lower for item in ['necklace', 'bracelet', 'strand', 'bead']):

                        is_bead_necklace = True

                        detected_bead_type = stone

                        break

            

            # Also check itemtype and reasoning for explicit indicators

            is_bead_necklace = is_bead_necklace or any(term in itemtype for term in [

                'pearlnecklace', 'pearl necklace', 'pearlstrand', 'pearl strand', 'pearlbracelet',

                'beadnecklace', 'bead necklace', 'beaded necklace', 'gemstone necklace', 'stone necklace'

            ])

            

            # Check reasoning for AI identifying it as beaded/clasp-only

            is_bead_necklace = is_bead_necklace or any(term in reasoning_text for term in [

                'pearl strand', 'pearl necklace', 'pearl weight dominates', 

                'clasp only', 'gold clasp', 'only the clasp', 'just the clasp',

                'bead necklace', 'beaded necklace', 'gemstone bead', 'stone bead',

                'most weight is', 'worthless for scrap', 'gold content likely',

                'spacer beads', 'only gold is', 'gold is only'

            ])

            

            if is_bead_necklace:

                logger.info(f"[CALC] BEAD NECKLACE DETECTED: {detected_bead_type or 'unknown type'}")

                

                # Try to extract clasp/gold weight from reasoning

                # Patterns: "clasp ~2-3g", "Gold clasp ~2g", "1-2g maximum", "gold content likely 1-2g"

                clasp_match = re.search(r'(?:clasp|gold content|actual gold)[^\d]*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*g', reasoning_text)

                weight_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*g\s*(?:max|only|gold|clasp)', reasoning_text)

                

                extracted_weight = None

                if clasp_match:

                    # If range given (e.g., "1-2g"), use lower value for safety

                    low = float(clasp_match.group(1))

                    high = float(clasp_match.group(2)) if clasp_match.group(2) else low

                    extracted_weight = low  # Conservative - use lower bound

                    logger.info(f"[CALC] BEAD NECKLACE: Extracted gold weight {low}-{high}g from reasoning, using {extracted_weight}g")

                elif weight_match:

                    low = float(weight_match.group(1))

                    high = float(weight_match.group(2)) if weight_match.group(2) else low

                    extracted_weight = low

                    logger.info(f"[CALC] BEAD NECKLACE: Extracted gold weight {extracted_weight}g from reasoning")

                

                if extracted_weight and extracted_weight > 0:

                    metal_weight = min(extracted_weight, 8.0)  # Cap at 8g max for safety

                else:

                    # Default: assume clasp only = 2-3g

                    logger.info(f"[CALC] BEAD NECKLACE: Using default clasp weight 2.5g (total was {total_weight}g)")

                    metal_weight = 2.5

                

                result['goldweight'] = f"{metal_weight:.1f}"

                result['itemtype'] = f'BeadNecklace({detected_bead_type or "gem"})'

                

                # Recalculate melt value with correct weight

                spots = get_spot_prices()

                karat_str = str(result.get('karat', '14K')).upper().replace('K', '').replace('KT', '')

                try:

                    karat_num = int(karat_str) if karat_str.isdigit() else 14

                except:

                    karat_num = 14

                

                karat_purity = {9: 0.375, 10: 0.417, 14: 0.583, 18: 0.75, 22: 0.916, 24: 1.0}.get(karat_num, 0.583)

                gold_price_per_gram = spots.get('gold_oz', 2650) / 31.1035

                

                correct_melt = metal_weight * gold_price_per_gram * karat_purity

                correct_sell = correct_melt * 0.96

                correct_buy = correct_melt * 0.90

                listing_price_float = float(str(listing_price).replace('$', '').replace(',', '') or 0)

                correct_margin = correct_buy - listing_price_float

                

                logger.info(f"[CALC] BEAD NECKLACE RECALC: {metal_weight}g {karat_num}K = ${correct_melt:.0f} melt, ${correct_buy:.0f} buy, margin ${correct_margin:.0f}")

                

                # Update result with corrected values

                result['melt'] = f"${correct_melt:.0f}"

                result['sell96'] = f"${correct_sell:.0f}"

                result['maxBuy'] = f"${correct_buy:.0f}"

                result['Margin'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"

                result['Profit'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"

                

                # Force PASS if negative margin

                if correct_margin < 0:

                    logger.info(f"[CALC] BEAD NECKLACE: Forcing PASS due to negative margin ${correct_margin:.0f}")

                    result['Recommendation'] = 'PASS'

                    result['reasoning'] = f"BEAD NECKLACE OVERRIDE: Gold is only clasp ({metal_weight}g), melt ${correct_melt:.0f}, listing ${listing_price_float:.0f} = LOSS. " + result.get('reasoning', '')

                

                # Skip the normal calculation flow

                stone_deduct = 0  # Already handled


            # === CARVED JADE/JADEITE PENDANT DETECTION ===
            # Carved jade pendants have stone as the main mass - only the bail is gold (1-3g max)
            # Jadeite value is subjective/gemological - can't assess from melt value

            elif ('jade' in title_lower or 'jadeite' in title_lower) and any(term in title_lower for term in ['pendant', 'carved', 'charm', 'disc', 'donut', 'pi disc']):
                logger.info(f"[CALC] CARVED JADE PENDANT DETECTED")

                # Common jade pendant types with carved stone
                jade_types = ['rabbit', 'buddha', 'dragon', 'horse', 'pi disc', 'donut', 'disc', 'carving', 'carved', 'animal', 'figure']
                is_carved = any(jt in title_lower for jt in jade_types) or 'carved' in reasoning_text or 'jadeite' in reasoning_text

                if is_carved:
                    # For carved jade, only the bail/frame is gold - typically 1-3g max
                    # Check if reasoning mentions bail weight
                    bail_match = re.search(r'(?:bail|frame|gold)[^\d]*(\d+(?:\.\d+)?)\s*g', reasoning_text)

                    if bail_match:
                        metal_weight = min(float(bail_match.group(1)), 5.0)  # Cap at 5g
                        logger.info(f"[CALC] JADE PENDANT: Extracted bail weight {metal_weight}g from reasoning")
                    else:
                        # Default: assume bail only = 1.5g (conservative)
                        metal_weight = 1.5
                        logger.info(f"[CALC] JADE PENDANT: Using default bail weight 1.5g (total was {total_weight}g)")

                    result['goldweight'] = f"{metal_weight:.1f}"
                    result['itemtype'] = 'JadePendant(carved)'

                    # Recalculate melt value with correct weight
                    spots = get_spot_prices()
                    karat_str = str(result.get('karat', '14K')).upper().replace('K', '').replace('KT', '')
                    try:
                        karat_num = int(karat_str) if karat_str.isdigit() else 14
                    except:
                        karat_num = 14

                    karat_purity = {9: 0.375, 10: 0.417, 14: 0.583, 18: 0.75, 22: 0.916, 24: 1.0}.get(karat_num, 0.583)
                    gold_price_per_gram = spots.get('gold_oz', 2650) / 31.1035

                    correct_melt = metal_weight * gold_price_per_gram * karat_purity
                    correct_sell = correct_melt * 0.96
                    correct_buy = correct_melt * 0.90
                    listing_price_float = float(str(listing_price).replace('$', '').replace(',', '') or 0)
                    correct_margin = correct_buy - listing_price_float

                    logger.info(f"[CALC] JADE PENDANT RECALC: {metal_weight}g {karat_num}K = ${correct_melt:.0f} melt, ${correct_buy:.0f} buy, margin ${correct_margin:.0f}")

                    # Update result with corrected values
                    result['melt'] = f"${correct_melt:.0f}"
                    result['sell96'] = f"${correct_sell:.0f}"
                    result['maxBuy'] = f"${correct_buy:.0f}"
                    result['Margin'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"
                    result['Profit'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"

                    # Force RESEARCH - jade value is subjective, needs gemological assessment
                    result['Recommendation'] = 'RESEARCH'
                    result['reasoning'] = f"JADE PENDANT: Carved jade/jadeite - gold is only bail (~{metal_weight}g), melt ${correct_melt:.0f}. Jade value is subjective (color, translucency, carving quality). " + result.get('reasoning', '')

                    stone_deduct = 0  # Already handled

            # === POCKET WATCH DETECTION ===

            # Pocket watches have heavy steel/brass movements - gold case is only ~33% of total weight

            # Hunter cases (with cover) have more gold than open-face

            elif 'pocket' in title_lower and 'watch' in title_lower:

                logger.info(f"[CALC] POCKET WATCH DETECTED")

                

                # Determine case style for gold percentage

                is_hunter_case = any(term in title_lower for term in ['hunter', 'hunting', 'full hunter', 'half hunter', 'demi-hunter'])

                is_open_face = 'open face' in title_lower or 'open-face' in title_lower or 'openface' in title_lower

                

                # Gold percentages by case type (of total weight)

                # Hunter case: ~35-40% gold (front and back covers)

                # Open face: ~25-33% gold (back only)

                # Default to conservative 33%

                if is_hunter_case:

                    gold_percentage = 0.38  # Hunter cases have more gold

                    case_type = "Hunter"

                elif is_open_face:

                    gold_percentage = 0.28  # Open face has less gold

                    case_type = "Open Face"

                else:

                    gold_percentage = 0.33  # Default

                    case_type = "Standard"

                

                # Check if AI already accounted for movement in goldweight

                ai_gold = 0

                if weight_str not in ['0', '', 'NA', 'None', '--']:

                    try:

                        ai_gold = float(weight_str.replace('g', '').replace(' est', '').strip().split()[0])

                    except:

                        ai_gold = 0

                

                # If AI's goldweight is already much less than total, they may have accounted for movement

                if ai_gold > 0 and ai_gold < total_weight * 0.5:

                    # AI already deducted - trust their number

                    metal_weight = ai_gold

                    logger.info(f"[CALC] POCKET WATCH: Using AI goldweight {ai_gold}g (already deducted movement)")

                elif total_weight > 0:

                    # Calculate gold as percentage of total

                    metal_weight = total_weight * gold_percentage

                    logger.info(f"[CALC] POCKET WATCH ({case_type}): {total_weight}g total {gold_percentage:.0%} = {metal_weight:.1f}g gold")

                    result['goldweight'] = f"{metal_weight:.1f}"

                    result['reasoning'] = f"POCKET WATCH: Movement deducted ({case_type} case = {gold_percentage:.0%} gold). " + result.get('reasoning', '')

                else:

                    metal_weight = ai_gold if ai_gold > 0 else 0

                

                # Recalculate with corrected weight

                if metal_weight > 0:

                    spots = get_spot_prices()

                    karat_str = str(result.get('karat', '14K')).upper().replace('K', '').replace('KT', '')

                    try:

                        karat_num = int(karat_str) if karat_str.isdigit() else 14

                    except:

                        karat_num = 14

                    

                    karat_purity = {9: 0.375, 10: 0.417, 14: 0.583, 18: 0.75, 22: 0.916, 24: 1.0}.get(karat_num, 0.583)

                    gold_price_per_gram = spots.get('gold_oz', 2650) / 31.1035

                    

                    correct_melt = metal_weight * gold_price_per_gram * karat_purity

                    correct_sell = correct_melt * 0.96

                    correct_buy = correct_melt * 0.90

                    listing_price_float = float(str(listing_price).replace('$', '').replace(',', '') or 0)

                    correct_margin = correct_buy - listing_price_float

                    

                    logger.info(f"[CALC] POCKET WATCH RECALC: {metal_weight:.1f}g {karat_num}K = ${correct_melt:.0f} melt, ${correct_buy:.0f} buy, margin ${correct_margin:.0f}")

                    

                    # Update result with corrected values

                    result['melt'] = f"${correct_melt:.0f}"

                    result['sell96'] = f"${correct_sell:.0f}"

                    result['maxBuy'] = f"${correct_buy:.0f}"

                    result['Margin'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"

                    result['Profit'] = f"{'+' if correct_margin >= 0 else ''}{correct_margin:.0f}"

                    result['itemtype'] = f'PocketWatch({case_type})'

                    

                    # Force PASS if negative margin

                    if correct_margin < 0:

                        logger.info(f"[CALC] POCKET WATCH: Forcing PASS due to negative margin ${correct_margin:.0f}")

                        result['Recommendation'] = 'PASS'

                

                stone_deduct = 0  # Already handled

            # === COMPASS DETECTION ===
            # Compasses have heavy non-precious-metal components:
            # - Glass dome/crystal cover
            # - Compass mechanism (needle, pivot, magnets)
            # - Internal backing plate
            # Sterling silver case is typically only ~25-35% of total weight
            elif 'compass' in title_lower and category == 'silver':
                logger.info(f"[CALC] COMPASS DETECTED - significant non-silver weight from mechanism")

                # Compass types:
                # Pocket compass (hinged case): ~30-35% silver case
                # Open compass: ~25% silver
                is_pocket_compass = any(term in title_lower for term in ['pocket', 'hinged', 'case', 'lid', 'cover'])

                if is_pocket_compass:
                    silver_percentage = 0.32  # Hinged cases have more silver
                    compass_type = "Pocket/Hinged"
                else:
                    silver_percentage = 0.25  # Open compasses have less silver
                    compass_type = "Open"

                # Check if AI already accounted for mechanism weight
                ai_silver = 0
                if weight_str not in ['0', '', 'NA', 'None', '--']:
                    try:
                        ai_silver = float(weight_str.replace('g', '').replace(' est', '').strip().split()[0])
                    except:
                        ai_silver = 0

                # If AI's silverweight is already much less than total, they may have accounted for mechanism
                if ai_silver > 0 and ai_silver < total_weight * 0.5:
                    metal_weight = ai_silver
                    logger.info(f"[CALC] COMPASS: Using AI silverweight {ai_silver}g (already deducted mechanism)")
                elif total_weight > 0:
                    # Calculate silver as percentage of total
                    metal_weight = total_weight * silver_percentage
                    logger.info(f"[CALC] COMPASS ({compass_type}): {total_weight}g total  {silver_percentage:.0%} = {metal_weight:.1f}g silver")
                    result['silverweight'] = f"{metal_weight:.1f}"
                    result['reasoning'] = f"COMPASS: Mechanism deducted ({compass_type} = {silver_percentage:.0%} silver). " + result.get('reasoning', '')
                else:
                    metal_weight = ai_silver if ai_silver > 0 else 0

                # Recalculate with corrected weight
                if metal_weight > 0:
                    correct_melt = metal_weight * sterling_price
                    correct_buy = correct_melt * 0.90
                    correct_margin = correct_buy - price_val

                    result['meltvalue'] = f"${correct_melt:.0f}"
                    result['maxBuy'] = f"${correct_buy:.0f}"
                    result['Profit'] = int(correct_margin)
                    result['Margin'] = f"${correct_margin:.0f}"

                    logger.info(f"[CALC] COMPASS RECALC: {metal_weight:.1f}g sterling = ${correct_melt:.0f} melt, ${correct_buy:.0f} buy, margin ${correct_margin:.0f}")

                    # Force PASS if negative margin
                    if correct_margin < 0:
                        logger.info(f"[CALC] COMPASS: Forcing PASS due to negative margin ${correct_margin:.0f}")
                        result['Recommendation'] = 'PASS'
                    elif correct_margin < 30:
                        # Thin margin - force RESEARCH for manual verification
                        logger.info(f"[CALC] COMPASS: Thin margin ${correct_margin:.0f} - forcing RESEARCH")
                        result['Recommendation'] = 'RESEARCH'
                        result['reasoning'] = f"COMPASS: Thin margin after mechanism deduction. " + result.get('reasoning', '')

                stone_deduct = 0  # Already handled

            else:

                # Normal gold item - parse stone deduction

                stone_deduct_str = str(result.get('stoneDeduction', '0'))

                stone_deduct = 0

                if stone_deduct_str and stone_deduct_str not in ['0', 'NA', 'None', '', '--']:

                    # Extract number from strings like "1g stone", "2.5g pearl", etc.

                    match = re.search(r'([\d.]+)', stone_deduct_str)

                    if match:

                        try:

                            stone_deduct = float(match.group(1))

                        except:

                            stone_deduct = 0

                

                # SERVER CALCULATES goldweight = total - deductions

                if total_weight > 0 and stone_deduct > 0:

                    calculated_gold = total_weight - stone_deduct

                    logger.info(f"[CALC] Server goldweight: {total_weight}g - {stone_deduct}g deduction = {calculated_gold}g")

                    metal_weight = calculated_gold

                    result['goldweight'] = f"{calculated_gold:.1f}"  # Update for display

                elif weight_str not in ['0', '', 'NA', 'None', '--']:

                    # Use AI's goldweight if no deduction to calculate

                    weight_str = weight_str.replace('g', '').replace(' est', '').replace('NA', '0').replace('--', '0').strip()

                    if ' ' in weight_str:

                        weight_str = weight_str.split()[0]

                    try:

                        metal_weight = float(weight_str) if weight_str else 0

                    except:

                        metal_weight = 0

                else:

                    # Fall back to total weight only if goldweight not available

                    logger.warning(f"[CALC] No goldweight, using total weight: {total_weight}g")

                    metal_weight = total_weight

        elif category == "silver":

            weight_str = str(result.get('silverweight', result.get('weight', '0')))

            weight_str = weight_str.replace('g', '').replace(' est', '').replace('NA', '0').replace('--', '0').strip()

            if ' ' in weight_str:

                weight_str = weight_str.split()[0]

            try:

                metal_weight = float(weight_str) if weight_str else 0

            except:

                metal_weight = 0

            # === FLATWARE WEIGHT ESTIMATION (when AI returns weight=0) ===
            # If AI couldn't determine weight, try server-side estimation for flatware
            if metal_weight == 0 and title:
                try:
                    from utils.extraction import detect_flatware
                    is_flatware_est, piece_type, flat_qty, estimated_weight = detect_flatware(title)
                    if is_flatware_est and estimated_weight > 0:
                        metal_weight = estimated_weight
                        result['weight'] = f"{estimated_weight:.0f}"
                        result['silverweight'] = f"{estimated_weight:.0f}"
                        result['weightSource'] = 'estimate'
                        result['itemtype'] = 'Flatware'
                        logger.info(f"[FLATWARE-EST] Server estimated {flat_qty}x {piece_type} = {estimated_weight:.0f}g")
                except Exception as e:
                    logger.warning(f"[FLATWARE-EST] Error: {e}")



            # === FLATWARE WEIGHT VALIDATION (IMPROVED) ===

            # AI often overestimates flatware weight - knives have hollow handles!

            itemtype = str(result.get('itemtype', '')).lower()

            title_lower = title.lower() if title else ''

            weight_source = str(result.get('weightSource', 'estimate')).lower()

            

            # Expanded flatware detection

            is_flatware = 'flatware' in itemtype or 'flatware' in title_lower or any(

                kw in title_lower for kw in ['sterling silver set', 'place setting', 'silverware', 'cutlery', 'sterling set']

            )

            

            if is_flatware:

                # Try to extract piece count from title - multiple patterns

                piece_count = 0

                piece_patterns = [

                    r'(\d+)\s*(?:piece|pc|pcs|pieces)',

                    r'(?:set of |lot of |service for )?(\d+)\s*(?:fork|spoon|knife|knives|piece|item|place)',

                    r'(\d+)\s*(?:pc|pcs)\s*(?:set|lot)',

                    r'service\s+(?:for\s+)?(\d+)',

                ]

                

                for pattern in piece_patterns:

                    piece_match = re.search(pattern, title_lower)

                    if piece_match:

                        extracted = int(piece_match.group(1))

                        # "Service for 8" means 8 place settings x 5 pieces = 40 pieces

                        if 'service' in pattern and extracted <= 12:

                            piece_count = extracted * 5

                        else:

                            piece_count = extracted

                        break

                

                # Store original weight for logging

                original_weight = metal_weight

                weight_was_corrected = False

                

                # === FIX 1: Absolute weight cap for estimated flatware ===

                # No flatware set should be estimated over 2000g without a scale photo

                MAX_ESTIMATED_FLATWARE = 2000

                

                if weight_source == 'estimate' and metal_weight > MAX_ESTIMATED_FLATWARE:

                    logger.warning(f"[CALC] FLATWARE WEIGHT CAP: {metal_weight:.0f}g estimated exceeds {MAX_ESTIMATED_FLATWARE}g max!")

                    

                    if piece_count > 0:

                        corrected_weight = piece_count * 38

                        logger.warning(f"[CALC] Using {piece_count} x 38g = {corrected_weight:.0f}g instead")

                    else:

                        corrected_weight = MAX_ESTIMATED_FLATWARE

                        logger.warning(f"[CALC] No piece count found - capping at {corrected_weight:.0f}g")

                    

                    metal_weight = corrected_weight

                    result['weight'] = f"{corrected_weight:.0f}"

                    result['silverweight'] = f"{corrected_weight:.0f}"

                    weight_was_corrected = True

                


                # === WEIGHTED SILVER DETECTION ===
                # Weighted sterling (candlesticks, etc.) is only ~15% actual silver
                # Check BOTH title AND description for weighted indicators
                weighted_keywords = ['weighted', 'candlestick', 'candelabra', 'candle holder', 'candleholder',
                                    'salt shaker', 'pepper shaker', 'compote', 'reinforced', 'cement filled']
                desc_text = str(data.get('description', '') or data.get('Description', '')).lower()
                combined_text_weighted = f"{title_lower} {desc_text}"
                is_weighted_silver = any(kw in combined_text_weighted for kw in weighted_keywords)

                # Log if weighted detected in description but not title
                if is_weighted_silver and not any(kw in title_lower for kw in weighted_keywords):
                    logger.warning(f"[WEIGHTED] Detected in DESCRIPTION, not title! Check description for 'weighted'")

                # === HOLLOW-HANDLED KNIFE DETECTION ===
                # Sterling flatware knives have HOLLOW handles filled with cement/steel
                # Only the thin sterling shell (~15-25g per knife) is actual silver
                # Pattern names (Chateau Rose, Chantilly, etc.) indicate weighted flatware
                is_sterling_knife = (
                    category == 'silver' and
                    ('knife' in title_lower or 'knives' in title_lower) and
                    any(kw in title_lower for kw in ['sterling', '925', 'butter', 'dinner', 'steak'])
                )

                if is_sterling_knife and piece_count > 0:
                    weight_per_knife = metal_weight / piece_count if piece_count > 0 else metal_weight
                    # Solid sterling butter knife: ~30-40g max
                    # If weight per knife > 50g, it's definitely hollow-handled
                    if weight_per_knife > 50:
                        # Hollow handled: only ~20g of actual silver per knife (the shell)
                        actual_silver_per_knife = 20
                        corrected_weight = piece_count * actual_silver_per_knife
                        logger.warning(f"[HOLLOW-HANDLE] Detected! {piece_count} knives @ {weight_per_knife:.0f}g each = hollow handles")
                        logger.warning(f"[HOLLOW-HANDLE] Using {piece_count} x {actual_silver_per_knife}g shell = {corrected_weight:.0f}g actual silver")
                        metal_weight = corrected_weight
                        result['weight'] = f"{corrected_weight:.0f}"
                        result['silverweight'] = f"{corrected_weight:.0f}"
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: HOLLOW-HANDLE KNIVES - {piece_count} @ {weight_per_knife:.0f}g each means cement-filled handles, actual silver ~{actual_silver_per_knife}g shell per knife = {corrected_weight}g total]"
                        result['itemtype'] = 'HollowHandleKnives'
                        weight_was_corrected = True
                        is_weighted_silver = False  # Don't double-apply weighted rule

                if is_weighted_silver and category == 'silver':
                    # Weighted items: actual silver is only 15% of stated weight
                    # 85% is cement/pitch/filler material
                    WEIGHTED_PCT = 0.15  # 15% of gross weight is actual silver
                    max_silver = original_weight * WEIGHTED_PCT

                    if metal_weight > max_silver:
                        logger.warning(f"[WEIGHTED] Weighted silver item! Using 15% rule: {original_weight:.0f}g gross -> {max_silver:.0f}g actual silver")
                        metal_weight = max_silver
                        result['weight'] = f"{max_silver:.0f}"
                        result['silverweight'] = f"{max_silver:.0f}"
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Weighted item - actual silver ~15% of {original_weight:.0f}g = {max_silver:.0f}g]"
                        result['itemtype'] = 'Weighted'
                        weight_was_corrected = True


                # === FIX 2: Per-piece validation with LOWER threshold ===

                elif piece_count > 0 and weight_source == 'estimate':

                    ai_per_piece = metal_weight / piece_count

                    

                    # LOWERED from 45 to 40 - catches overestimates like 42.75g/piece

                    MAX_PER_PIECE = 40

                    REALISTIC_PER_PIECE = 38

                    

                    if ai_per_piece > MAX_PER_PIECE:

                        corrected_weight = piece_count * REALISTIC_PER_PIECE

                        logger.warning(f"[CALC] FLATWARE OVERRIDE: {piece_count} pieces x {ai_per_piece:.0f}g/pc = {metal_weight:.0f}g too high!")

                        logger.warning(f"[CALC] Using {piece_count} x {REALISTIC_PER_PIECE}g = {corrected_weight:.0f}g instead")

                        metal_weight = corrected_weight

                        result['weight'] = f"{corrected_weight:.0f}"

                        result['silverweight'] = f"{corrected_weight:.0f}"

                        weight_was_corrected = True

                

                # === FIX 3: High-value estimated flatware = RESEARCH ===

                # $1500+ listings with estimated weight are too risky for auto-BUY

                if weight_source == 'estimate':

                    try:

                        list_price = float(str(listing_price).replace('$', '').replace(',', ''))

                    except:

                        list_price = 0

                    

                    if list_price > 1500 and result.get('Recommendation') == 'BUY':

                        logger.warning(f"[CALC] FLATWARE SAFETY: ${list_price:.0f} with estimated weight - forcing RESEARCH")

                        result['Recommendation'] = 'RESEARCH'

                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: ${list_price:.0f} listing with estimated weight needs scale verification]"

                    elif weight_was_corrected and result.get('Recommendation') == 'BUY':

                        # Weight was corrected - recalculate margin to see if still a BUY

                        new_melt = metal_weight * sterling_rate

                        new_max_buy = new_melt * 0.70

                        if list_price > new_max_buy:

                            logger.warning(f"[CALC] FLATWARE: After correction, ${list_price:.0f} > maxBuy ${new_max_buy:.0f} - PASS")

                            result['Recommendation'] = 'PASS'

                            result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Corrected weight {metal_weight:.0f}g = ${new_melt:.0f} melt, ${new_max_buy:.0f} maxBuy < ${list_price:.0f} list]"

                

                # Add correction note to reasoning if weight was changed

                if weight_was_corrected:

                    result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Weight corrected from {original_weight:.0f}g to {metal_weight:.0f}g]"

            else:
                # === NON-FLATWARE SILVER (candlesticks, candelabra, hollowware, etc.) ===
                # Check for weighted items and apply 15% rule
                title_lower_check = title.lower() if title else ''
                desc_text = str(data.get('description', '') or data.get('Description', '')).lower()
                combined_check = f"{title_lower_check} {desc_text}"

                weighted_kw = ['weighted', 'candlestick', 'candelabra', 'candle holder', 'candleholder',
                              'salt shaker', 'pepper shaker', 'compote', 'reinforced', 'cement filled']
                is_weighted_item = any(kw in combined_check for kw in weighted_kw)

                if is_weighted_item and metal_weight > 0:
                    # Get title weight (gross weight) for 15% calculation
                    title_gross_weight = None
                    # Try to extract weight from title
                    gram_m = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:grams?|g)', title_lower_check)
                    if gram_m:
                        title_gross_weight = float(gram_m.group(1).replace(',', ''))
                    else:
                        oz_m = re.search(r'([\d.]+)\s*(?:oz|ounce)', title_lower_check)
                        if oz_m:
                            title_gross_weight = float(oz_m.group(1)) * 31.1035

                    # Use title weight if available, otherwise use AI's weight
                    gross_weight = title_gross_weight if title_gross_weight else metal_weight
                    WEIGHTED_PCT = 0.15  # 15% of gross weight is actual silver
                    max_silver = gross_weight * WEIGHTED_PCT

                    if metal_weight > max_silver:
                        logger.warning(f"[WEIGHTED] Non-flatware weighted item detected! Using 15% rule: {gross_weight:.0f}g gross -> {max_silver:.0f}g actual silver")
                        metal_weight = max_silver
                        result['weight'] = f"{max_silver:.0f}"
                        result['silverweight'] = f"{max_silver:.0f}"
                        result['itemtype'] = 'Weighted'
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: WEIGHTED ITEM - actual silver ~15% of {gross_weight:.0f}g = {max_silver:.0f}g]"


        else:

            weight_str = str(result.get('weight', '0'))

            weight_str = weight_str.replace('g', '').replace(' est', '').replace('NA', '0').replace('--', '0').strip()

            if ' ' in weight_str:

                weight_str = weight_str.split()[0]

            try:

                metal_weight = float(weight_str) if weight_str else 0

            except:

                metal_weight = 0

            # === WEIGHTED SILVER DETECTION (NON-FLATWARE) ===
            # Candlesticks, candelabra, etc. are NOT flatware but still weighted!
            # Must apply 15% rule here for non-flatware weighted items
            if category == 'silver':
                title_lower_check = title.lower() if title else ''
                desc_text = str(data.get('description', '') or data.get('Description', '')).lower()
                combined_check = f"{title_lower_check} {desc_text}"

                weighted_kw = ['weighted', 'candlestick', 'candelabra', 'candle holder', 'candleholder',
                              'salt shaker', 'pepper shaker', 'compote', 'reinforced', 'cement filled']
                is_weighted_item = any(kw in combined_check for kw in weighted_kw)

                if is_weighted_item and metal_weight > 0:
                    # Get title weight (gross weight) for 15% calculation
                    title_gross_weight = None
                    # Try to extract weight from title
                    gram_m = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:grams?|g\b)', title_lower_check)
                    if gram_m:
                        title_gross_weight = float(gram_m.group(1).replace(',', ''))
                    else:
                        oz_m = re.search(r'([\d.]+)\s*(?:oz|ounce)', title_lower_check)
                        if oz_m:
                            title_gross_weight = float(oz_m.group(1)) * 31.1035

                    # Use title weight if available, otherwise use AI's weight
                    gross_weight = title_gross_weight if title_gross_weight else metal_weight
                    WEIGHTED_PCT = 0.15  # 15% of gross weight is actual silver
                    max_silver = gross_weight * WEIGHTED_PCT

                    if metal_weight > max_silver:
                        logger.warning(f"[WEIGHTED] Non-flatware weighted item detected! Using 15% rule: {gross_weight:.0f}g gross -> {max_silver:.0f}g actual silver")
                        metal_weight = max_silver
                        result['weight'] = f"{max_silver:.0f}"
                        result['silverweight'] = f"{max_silver:.0f}"
                        result['itemtype'] = 'Weighted'
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: WEIGHTED ITEM - actual silver ~15% of {gross_weight:.0f}g = {max_silver:.0f}g]"



        # Get karat for gold category - normalize to uppercase with K suffix
        karat_raw = result.get('karat', '14K')
        # Normalize: "10k" -> "10K", "10" -> "10K", "10kt" -> "10K"
        karat_clean = str(karat_raw).upper().replace('KT', 'K').replace('KARAT', 'K')
        # Extract just the number and add K
        karat_match = re.search(r'(\d+)', karat_clean)
        karat = f"{karat_match.group(1)}K" if karat_match else "14K"
        if str(karat_raw) != karat:
            logger.info(f"[CALC] Karat normalized: '{karat_raw}' -> '{karat}'")



        # For GOLD: ALWAYS recalculate melt from goldweight - don't trust AI's calculation!

        # AI often calculates melt from total weight instead of goldweight

        if category == "gold" and metal_weight > 0:

            rate = karat_rates.get(karat, karat_rates["14K"])

            melt_value = metal_weight * rate

            

            # Check if AI's melt was significantly different (indicates they used wrong weight)

            ai_melt_str = str(result.get('meltvalue', '0'))

            try:

                ai_melt = float(ai_melt_str.replace('$', '').replace(',', ''))

            except:

                ai_melt = 0

            

            if ai_melt > 0 and abs(ai_melt - melt_value) > melt_value * 0.15:

                logger.warning(f"[CALC] MELT OVERRIDE: AI=${ai_melt:.0f} vs Server=${melt_value:.0f} (using goldweight {metal_weight}g)")

            

            result['meltvalue'] = f"{melt_value:.0f}"

            logger.info(f"[CALC] Gold melt: {metal_weight}g x ${rate:.2f} = ${melt_value:.0f}")

        

        # For SILVER and others: recalculate if missing or invalid

        elif category == "silver" and metal_weight > 0:

            melt_value = metal_weight * sterling_rate

            

            # === NATIVE AMERICAN / NAVAJO PREMIUM ===

            # Native American jewelry (especially with turquoise) gets 15% premium

            native_keywords = ['navajo', 'native american', 'zuni', 'hopi', 'santo domingo', 

                              'southwestern', 'squash blossom', 'concho', 'signed native']

            turquoise_keywords = ['turquoise', 'kingman', 'sleeping beauty', 'morenci', 'bisbee', 

                                 'royston', 'number 8', 'lone mountain']

            

            title_lower = title.lower() if title else ""

            reasoning_lower = str(result.get('reasoning', '')).lower()

            check_text = f"{title_lower} {reasoning_lower}"

            

            is_native = any(kw in check_text for kw in native_keywords)

            has_turquoise = any(kw in check_text for kw in turquoise_keywords)

            

            if is_native or (has_turquoise and 'silver' in check_text):

                premium_rate = 1.15  # 15% premium

                original_melt = melt_value

                melt_value = melt_value * premium_rate

                result['nativePremium'] = 'Yes'

                logger.info(f"[CALC] NATIVE AMERICAN PREMIUM: ${original_melt:.0f} x 1.15 = ${melt_value:.0f}")

                result['reasoning'] = result.get('reasoning', '') + f" [+15% Native American premium: ${original_melt:.0f} -> ${melt_value:.0f}]"

                # HARD CAP: Native American jewelry max 4x melt value
                # Even with collector value, we don't pay more than 4x base melt
                max_native_price = original_melt * config.NATIVE_MAX_MELT_MULTIPLIER
                if listing_price > max_native_price:
                    result['Recommendation'] = 'PASS'
                    result['reasoning'] = result.get('reasoning', '') + f" [NATIVE CAP: Price ${listing_price:.0f} > 4x melt ${max_native_price:.0f} - TOO EXPENSIVE]"
                    logger.warning(f"[CALC] NATIVE 4x CAP: ${listing_price:.0f} > ${max_native_price:.0f} (4x ${original_melt:.0f}) - PASS")



            result['meltvalue'] = f"{melt_value:.0f}"

            logger.info(f"[CALC] Silver melt: {metal_weight}g x ${sterling_rate:.2f} = ${melt_value:.0f}")

        else:

            # Try to use AI's melt value

            melt_str = str(result.get('meltvalue', '0'))

            try:

                melt_value = float(melt_str.replace('$', '').replace(',', ''))

            except:

                melt_value = 0

        

        # Calculate all values from melt

        if melt_value > 0:

            if category == "gold":

                correct_max_buy = melt_value * config.GOLD_MAX_BUY_RATE

                correct_sell_price = melt_value * config.GOLD_SELL_RATE

            elif category == "silver":

                correct_max_buy = melt_value * config.SILVER_MAX_BUY_RATE

                correct_sell_price = melt_value * config.SILVER_SELL_RATE

            else:

                correct_max_buy = 0

                correct_sell_price = 0

            

            # Get AI's maxBuy

            max_buy_str = str(result.get('maxBuy', '0'))

            try:

                ai_max_buy = float(max_buy_str.replace('$', '').replace(',', ''))

            except:

                ai_max_buy = 0

            

            # Fix maxBuy if off by more than 5%

            if ai_max_buy == 0 or abs(ai_max_buy - correct_max_buy) > correct_max_buy * 0.05:

                logger.warning(f"[CALC] maxBuy fix: AI=${ai_max_buy:.0f}, correct=${correct_max_buy:.0f}")

                result['maxBuy'] = f"{correct_max_buy:.0f}"

                max_buy = correct_max_buy

            else:

                max_buy = ai_max_buy

            

            # Always set/fix sellPrice

            result['sellPrice'] = f"{correct_sell_price:.0f}"

            

            # Calculate correct Profit (maxBuy - listingPrice = our buffer)

            # We use maxBuy, not sellPrice, because the 6% above maxBuy is our cushion

            # for price fluctuations before we can melt

            correct_profit = max_buy - listing_price

            

            # Get AI's reported Profit/Margin for comparison

            ai_profit_str = str(result.get('Profit', result.get('Margin', '0')))

            try:

                ai_profit = float(ai_profit_str.replace('$', '').replace('+', '').replace(',', ''))

                if '-' in ai_profit_str:

                    ai_profit = -abs(ai_profit)

            except:

                ai_profit = 0

            

            # Fix Profit if AI got it wrong

            if abs(correct_profit - ai_profit) > 5:

                logger.warning(f"[CALC] Profit fix: AI=${ai_profit:.0f}, correct=${correct_profit:.0f} (maxBuy ${max_buy:.0f} - list ${listing_price:.0f})")

                result['Profit'] = f"{correct_profit:+.0f}"

                result['reasoning'] = result.get('reasoning', '') + f" [SERVER: maxBuy ${max_buy:.0f} - list ${listing_price:.0f} = ${correct_profit:.0f} margin]"

            else:

                result['Profit'] = f"{correct_profit:+.0f}"

            

            # Also keep Margin for backwards compatibility (but Profit is the real number)

            result['Margin'] = result['Profit']

            

            # Override recommendation based on corrected calculations

            current_rec = result.get('Recommendation', 'PASS').upper().strip()  # Normalize to uppercase

            result['Recommendation'] = current_rec  # Ensure stored version is normalized

            reasoning_lower = result.get('reasoning', '').lower()

            itemtype_lower = str(result.get('itemtype', '')).lower()

            title_lower = title.lower() if title else ''

            weight_source = str(result.get('weightSource', 'estimate')).lower()

            # CRITICAL: API listings have NO IMAGES - AI cannot read scales or verify weight
            # Force weight_source to 'estimate' for all API listings to prevent hallucination BUYs
            is_from_api = data.get('source') == 'ebay_api'
            if is_from_api and weight_source in ['scale', 'stated']:
                logger.warning(f"[API OVERRIDE] API listing claimed '{weight_source}' weight but has no images - forcing to 'estimate'")
                weight_source = 'estimate'
                result['weightSource'] = 'estimate'  # Update the result too

            

            # =================================================================

            # CRITICAL: NO VERIFIED WEIGHT + BUY = FORCE TO RESEARCH/PASS

            # Estimated weight = NEVER BUY, only RESEARCH or PASS

            # This prevents AI hallucination BUYs on items without stated weight

            # EXCEPTION: High confidence (>=85%) from AI = trust weight verification

            # =================================================================

            # Get AI's confidence for bypass check
            ai_confidence = 0
            try:
                ai_confidence = int(result.get('confidence', 0))
            except:
                pass

            # HIGH CONFIDENCE BYPASS: If AI is >=85% confident, it likely verified weight from scale photo
            # Trust Tier 2's verification instead of forcing RESEARCH
            high_confidence_verified = ai_confidence >= 85 and correct_profit >= 50

            if current_rec == 'BUY' and weight_source == 'estimate' and category in ['gold', 'silver']:

                if high_confidence_verified:
                    logger.info(f"[CALC] ESTIMATED WEIGHT + BUY: HIGH CONFIDENCE ({ai_confidence}%) - trusting AI weight verification (profit ${correct_profit:.0f})")
                    # Don't override - let BUY stand

                # ABSOLUTE RULE: Estimated weight cannot be BUY (unless high confidence)

                # If profit is thin or negative, PASS. Otherwise RESEARCH.

                elif correct_profit < 30:

                    logger.warning(f"[CALC] ESTIMATED WEIGHT + BUY: Forcing PASS (profit ${correct_profit:.0f} too thin)")

                    result['Recommendation'] = 'PASS'

                    result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Weight estimated + thin margin ${correct_profit:.0f} - PASS]"

                    current_rec = 'PASS'

                else:

                    logger.warning(f"[CALC] ESTIMATED WEIGHT + BUY: Forcing RESEARCH (profit ${correct_profit:.0f})")

                    result['Recommendation'] = 'RESEARCH'

                    result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Weight estimated - verify before buying (est profit ${correct_profit:.0f})]"

                    current_rec = 'RESEARCH'

            # SAFETY: Scale readings from images are unreliable - require Tier 2 verification
            # If AI claims "scale" reading but weight isn't in title, force RESEARCH
            # EXCEPTION: High confidence (>=85%) = trust it
            if current_rec == 'BUY' and weight_source == 'scale' and category in ['gold', 'silver']:
                # Check if weight is actually stated in title
                title_has_weight = any(pattern in title_lower for pattern in [
                    'gram', ' g ', 'dwt', ' oz', 'ounce'
                ]) or re.search(r'\d+\.?\d*\s*g\b', title_lower)

                if not title_has_weight and not high_confidence_verified:
                    logger.warning(f"[CALC] SCALE READING NOT VERIFIED: AI claims scale read but no weight in title - forcing RESEARCH")
                    result['Recommendation'] = 'RESEARCH'
                    result['reasoning'] = result.get('reasoning', '') + " [SERVER: Scale reading unverified - weight not in title, needs manual verification]"
                    current_rec = 'RESEARCH'
                elif not title_has_weight and high_confidence_verified:
                    logger.info(f"[CALC] SCALE READING: HIGH CONFIDENCE ({ai_confidence}%) - trusting AI scale verification")

            # SAFETY: Detect bead/pearl items - NEVER trust server math on these

            is_bead_item = any(word in reasoning_lower for word in [

                'pearl strand', 'pearl necklace', 'pearl bracelet', 'pearl weight dominates', 

                'clasp only', 'only the clasp', 'just the clasp', 'bead necklace',

                'most weight is', 'worthless for scrap', 'gold content likely', 'gold is only'

            ])

            is_bead_item = is_bead_item or 'pearl' in itemtype_lower or 'bead' in itemtype_lower

            is_bead_item = is_bead_item or any(stone in title_lower for stone in [

                'spinel', 'jade', 'coral', 'turquoise', 'onyx', 'agate', 'lapis', 'malachite'

            ]) and any(item in title_lower for item in ['necklace', 'bracelet', 'strand'])

            

            # === WATCH WEIGHT VALIDATION ===

            # Ladies watches typically 3-8g gold, if AI estimates higher it probably didn't read scale

            is_watch = 'watch' in itemtype_lower or 'watch' in title_lower

            is_ladies_watch = is_watch and any(word in title_lower for word in ['lady', 'ladies', 'womens', "women's", 'petite'])

            

            if is_watch and weight_source == 'estimate':

                # AI estimated weight instead of reading scale - flag as suspicious

                logger.warning(f"[CALC] WATCH with ESTIMATED weight - AI may have missed scale photo!")

                result['reasoning'] = result.get('reasoning', '') + " [WARNING: Weight was estimated, verify scale photo]"

            

            if is_ladies_watch and metal_weight >= 7:

                # Ladies watch with >=7g gold is suspicious (typical is 3-6g)

                logger.warning(f"[CALC] LADIES WATCH: {metal_weight}g seems high (typical 3-6g) - AI may not have read scale!")

                result['reasoning'] = result.get('reasoning', '') + f" [WARNING: {metal_weight}g high for ladies watch, verify scale]"

                # Don't auto-correct, but flag for manual review

                if current_rec == 'BUY':

                    result['Recommendation'] = 'RESEARCH'

                    current_rec = 'RESEARCH'  # Update for later checks

                    logger.info(f"[CALC] Downgrading BUY[PASS] [PASS] for suspicious ladies watch weight")

            

            # === NATIVE AMERICAN JEWELRY LOT VALIDATION ===

            # NA jewelry has heavy turquoise/coral stones - AI often overestimates weight

            is_na_jewelry = any(word in title_lower for word in [

                'native american', 'navajo', 'zuni', 'hopi', 'santo domingo',

                'southwestern', 'squash blossom'

            ])

            has_heavy_stones = any(stone in title_lower for stone in [

                'turquoise', 'coral', 'onyx', 'lapis', 'malachite'

            ])

            

            if is_na_jewelry and has_heavy_stones and weight_source == 'estimate':

                ai_weight = metal_weight

                if ai_weight >= 50:

                    logger.warning(f"[CALC] NA JEWELRY with estimated {ai_weight}g - likely overestimated!")

                    result['reasoning'] = result.get('reasoning', '') + f" [WARNING: {ai_weight}g estimated on NA jewelry with stones - verify weight!]"

                    if current_rec == 'BUY':

                        result['Recommendation'] = 'RESEARCH'

                        current_rec = 'RESEARCH'

                        logger.info(f"[CALC] Downgrading BUY to RESEARCH for NA jewelry estimated weight")



            # Also check for deduction mentions

            has_deduction_mention = any(word in reasoning_lower for word in ['pearl', 'deduction', 'stone', 'diamond', 'gem', 'bead', 'clasp'])

            

            # Check if seller accepts offers (from data)

            accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']

            

            # === BEST OFFER / NEAR-PROFITABLE LOGIC ===

            # Check if this is Native American jewelry (looser restrictions)

            is_native_jewelry = result.get('nativePremium') == 'Yes'



            # Calculate how close we are to profitability

            if correct_profit < 0 and max_buy > 0:

                gap_to_profitable = listing_price - max_buy

                gap_percent = (gap_to_profitable / listing_price) * 100 if listing_price > 0 else 100



                # Native American jewelry: allow up to 20% gap (collector value beyond melt)

                # Regular items: allow up to 10% gap if best offer available

                max_gap = 20 if is_native_jewelry else 10



                if gap_percent <= max_gap:

                    offer_price = int(max_buy * 0.95)  # Offer 5% below our max



                    if accepts_offers:

                        result['Recommendation'] = 'RESEARCH'

                        result['suggestedOffer'] = f"${offer_price}"

                        if is_native_jewelry:

                            result['reasoning'] = result.get('reasoning', '') + f" [NATIVE JEWELRY: ${listing_price:.0f} is {gap_percent:.1f}% over max. Has collector value - MAKE OFFER at ${offer_price}]"

                            logger.info(f"[CALC] NATIVE JEWELRY MAKE OFFER: List ${listing_price:.0f}, maxBuy ${max_buy:.0f}, gap {gap_percent:.1f}%, suggest offer ${offer_price}")

                        else:

                            result['reasoning'] = result.get('reasoning', '') + f" [BEST OFFER: ${listing_price:.0f} is {gap_percent:.1f}% over max. MAKE OFFER at ${offer_price}]"

                            logger.info(f"[CALC] BEST OFFER AVAILABLE: List ${listing_price:.0f}, maxBuy ${max_buy:.0f}, gap {gap_percent:.1f}%, suggest offer ${offer_price}")

                        current_rec = 'RESEARCH'

                    elif is_native_jewelry:

                        # Native American without best offer - still worth researching due to collector value

                        result['Recommendation'] = 'RESEARCH'

                        result['suggestedOffer'] = f"${offer_price}"

                        result['reasoning'] = result.get('reasoning', '') + f" [NATIVE JEWELRY: ${listing_price:.0f} is {gap_percent:.1f}% over max. Collector value - try offer ${offer_price}]"

                        logger.info(f"[CALC] NATIVE JEWELRY RESEARCH: List ${listing_price:.0f}, gap {gap_percent:.1f}%, collector value potential")

                        current_rec = 'RESEARCH'

                    elif listing_price >= 500:

                        # High-value item without best offer - still worth noting

                        result['Recommendation'] = 'RESEARCH'

                        result['suggestedOffer'] = f"${offer_price}"

                        result['reasoning'] = result.get('reasoning', '') + f" [HIGH-VALUE: ${listing_price:.0f} is {gap_percent:.1f}% over max. Worth ${offer_price} - check if offers accepted]"

                        logger.info(f"[CALC] HIGH-VALUE NEAR-PROFITABLE: List ${listing_price:.0f}, gap {gap_percent:.1f}%, worth researching")

                        current_rec = 'RESEARCH'

            # === LARGE SILVER LOT RESEARCH FLAG ===
            # Large silver jewelry lots (500g+ and $1000+) should be RESEARCH even if over buy limit
            # These often contain designer pieces worth more than melt value
            if category == 'silver' and metal_weight >= 500 and listing_price >= 1000:
                lot_keywords = ['lot', 'huge', 'bulk', 'collection', 'mixed', 'assorted', 'scrap']
                title_lower = title.lower() if title else ""
                if any(kw in title_lower for kw in lot_keywords):
                    if current_rec == 'PASS':
                        result['Recommendation'] = 'RESEARCH'
                        result['suggestedOffer'] = f"${int(max_buy * 0.95)}" if max_buy > 0 else ""
                        result['reasoning'] = result.get('reasoning', '') + f" [LARGE LOT: {metal_weight:.0f}g @ ${listing_price:.0f} - Check for designer pieces (Tiffany, Gorham, Georg Jensen)]"
                        logger.info(f"[CALC] LARGE SILVER LOT: {metal_weight:.0f}g @ ${listing_price:.0f} - flagging RESEARCH for designer piece check")
                        current_rec = 'RESEARCH'


            # HIGH-VALUE NEAR-MISS: If listing > $500 AND within 10% of max buy, flag RESEARCH
            # These are worth looking at even if slightly unprofitable - negotiation possible
            gap_percent = ((listing_price - max_buy) / listing_price * 100) if listing_price > 0 and max_buy > 0 else 100
            is_high_value_near_miss = (
                listing_price > 500 and
                max_buy > 0 and
                gap_percent <= 10 and  # Within 10% of max buy
                category in ['gold', 'silver'] and
                not is_bead_item
            )

            if is_high_value_near_miss and correct_profit < 15:
                # High value item close to profitable - worth a look
                logger.warning(f"[CALC] HIGH-VALUE NEAR-MISS: ${listing_price:.0f} listing, ${max_buy:.0f} max buy, gap {gap_percent:.1f}% - forcing RESEARCH")
                result['Recommendation'] = 'RESEARCH'
                result['reasoning'] = result.get('reasoning', '') + f" [SERVER: High-value ${listing_price:.0f} within {gap_percent:.1f}% of max buy ${max_buy:.0f} - worth reviewing]"
                current_rec = 'RESEARCH'

            # CRITICAL: Force PASS if profit is NEGATIVE (regardless of other factors)
            # But skip for high-value near-misses (already handled above)
            elif correct_profit < 0 and current_rec == 'BUY' and not is_bead_item:

                logger.warning(f"OVERRIDE: PASS (negative profit ${correct_profit:.0f})")

                result['Recommendation'] = 'PASS'

                result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Negative profit ${correct_profit:.0f} - PASS]"

                current_rec = 'PASS'

            # MARGINAL PROFIT: If profit is $0-15, flag as RESEARCH (too thin, any error = loss)
            # This catches items priced at 70-75% of melt where margins are razor thin
            elif 0 <= correct_profit < 15 and current_rec == 'BUY' and category in ['gold', 'silver']:
                logger.warning(f"[CALC] MARGINAL PROFIT: ${correct_profit:.0f} < $15 - forcing RESEARCH")
                result['Recommendation'] = 'RESEARCH'
                result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Marginal profit ${correct_profit:.0f} - verify weight/purity before buying]"
                current_rec = 'RESEARCH'

            # BEAD ITEMS: NEVER override AI's PASS - they know the gold is just the clasp

            elif is_bead_item and current_rec == 'PASS':

                logger.info(f"[CALC] KEEPING AI's PASS for bead/pearl item (server math unreliable for bead strands)")

                # Don't change recommendation

            

            # === TRUST AI's PASS DECISION ===

            # If AI said PASS with estimated weight, it likely means the price is too high

            # for the item type regardless of what server calculates.

            # Only override PASS to BUY if weight is VERIFIED (scale/stated).

            elif correct_profit > 0 and current_rec == 'PASS':

                # Log everything for debugging
                title_lower = title.lower() if title else ""

                logger.info(f"[CALC] Positive profit ${correct_profit:.0f} but AI said PASS - checking if we should override...")

                logger.info(f"[CALC]   weight_source: {weight_source}")

                

                # CRITICAL FIX: If weight is estimated, TRUST AI's PASS

                # AI knows the item type and judged price is too high

                if weight_source == 'estimate':
                    # SPECIAL CASE: Flatware with server-estimated weight
                    # Flatware weight estimates are reliable based on piece type
                    # If profit is substantial, override to RESEARCH
                    itemtype_lower = str(result.get('itemtype', '')).lower()
                    is_flatware_item = itemtype_lower == 'flatware' or 'fork' in itemtype_lower or 'spoon' in itemtype_lower

                    if is_flatware_item and correct_profit > 30:
                        logger.warning(f"[FLATWARE-OVERRIDE] Server-estimated flatware shows ${correct_profit:.0f} profit - overriding PASS to RESEARCH")
                        result['Recommendation'] = 'RESEARCH'
                        result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Flatware estimated at {metal_weight:.0f}g shows ${correct_profit:.0f} profit - verify piece type/weight]"
                        current_rec = 'RESEARCH'
                    else:
                        logger.info(f"[CALC] KEEPING AI's PASS - weight is estimated, trusting AI's judgment on price vs item type")
                        # Keep the PASS - don't override

                # Only consider overriding if weight is verified

                elif weight_source in ['scale', 'stated']:

                    # Verified weight - check if AI had specific concerns

                    ai_reasoning = str(result.get('reasoning', '')).lower()

                    doubt_phrases = [

                        'overvaluation', 'overestimate', 'seems off', 'uncertain', 

                        'not confident', 'verify', 'caution', 'risky', 'unreliable',

                        'cannot confirm', 'unable to verify', 'questionable',

                        'plated', 'filled', 'fake', 'suspicious'

                    ]

                    ai_has_doubt = any(phrase in ai_reasoning for phrase in doubt_phrases)

                    

                    if ai_has_doubt:

                        # AI expressed doubt even with verified weight - trust it

                        logger.info(f"[CALC] AI expressed doubt with verified weight - keeping PASS")

                    # SAFEGUARD: Don't override if Tier 2 also said PASS
                    elif result.get('tier2') == 'PASS' or result.get('tier2_override') == 'BUY_TO_PASS':
                        logger.info(f"[CALC] KEEPING PASS - Tier 2 also recommended PASS (both AI tiers agree)")

                    # SAFEGUARD: Don't override for items with significant gemstones or semi-precious stones
                    # Semi-precious stones like onyx, turquoise, jade can be heavy and skew weight calculations
                    # Also catch generic "gemstone" keyword and "inlay" (stone/shell inlaid in metal)
                    # EXCEPTION: Wedding bands with small accent diamonds (channel set, 1-5 diamonds) - gold dominates value
                    elif any(gem in title_lower for gem in [
                        'diamond', 'emerald', 'ruby', 'sapphire', 'tcw', 'ctw', 'carat',
                        'onyx', 'turquoise', 'jade', 'coral', 'amber', 'opal', 'amethyst',
                        'garnet', 'topaz', 'peridot', 'citrine', 'aquamarine', 'malachite',
                        'lapis', 'mother of pearl', 'mop', 'pearl', 'moonstone', 'agate',
                        'carnelian', 'jasper', 'obsidian', 'tiger eye', 'tigers eye',
                        'gemstone', 'gem stone', 'multi gem', 'inlay', 'inlaid'
                    ]):
                        # Check for wedding band exception - small accent diamonds don't dominate value
                        is_wedding_band = any(w in title_lower for w in ['wedding band', 'band ring', 'wedding ring'])
                        is_channel_set = 'channel' in title_lower
                        # Check for small diamond count (1-5 diamonds)
                        small_diamond_match = re.search(r'\b([1-5])\s*diamonds?\b', title_lower)

                        # Check for explicit weight in title (grams, dwt, oz)
                        weight_in_title = re.search(r'(\d+\.?\d*)\s*(gram|grams|gm|g|dwt|oz)\b', title_lower)
                        # Check for gold karat in title
                        has_karat = bool(re.search(r'\b(10k|14k|18k|22k|24k|10kt|14kt|18kt|22kt|24kt)\b', title_lower))

                        # EXCEPTION 1: Wedding bands with small accent diamonds
                        if (is_wedding_band or is_channel_set) and small_diamond_match and weight_in_title and category == 'gold':
                            # Small accent diamonds in a gold wedding band - gold dominates, allow override
                            logger.info(f"[CALC] ALLOWING override - wedding band with small accent diamonds ({small_diamond_match.group(0)}), gold value dominates")

                        # EXCEPTION 2: Gold with explicit weight stated in title
                        # If seller explicitly states weight (e.g., "10.36 Grams") AND karat, we can calculate gold value
                        # The gemstones add value but don't negate the gold - we're buying for gold value
                        elif weight_in_title and has_karat and category == 'gold' and weight_source == 'stated':
                            stated_weight = float(weight_in_title.group(1))
                            # Only allow if weight is substantial enough (at least 3 grams for gold)
                            if stated_weight >= 3.0:
                                logger.info(f"[CALC] ALLOWING override - gold with explicit weight ({stated_weight}g) + karat in title, gemstones don't negate gold value")
                            else:
                                logger.info(f"[CALC] KEEPING PASS - gold weight too low ({stated_weight}g), gemstones may dominate value")

                        # EXCEPTION 3: Lab-created stones (lab diamond, lab emerald, simulated, moissanite)
                        # Lab-created stones are much cheaper than natural - gold value likely dominates
                        elif any(lab_term in title_lower for lab_term in [
                            'lab created', 'lab-created', 'lab grown', 'lab-grown',
                            'created diamond', 'created emerald', 'created sapphire', 'created ruby',
                            'simulated', 'simulant', 'moissanite', 'cz', 'cubic zirconia',
                            'synthetic', 'man made', 'man-made'
                        ]) and category == 'gold' and has_karat:
                            logger.info(f"[CALC] ALLOWING override - lab-created/simulated stones (cheap), gold value dominates")

                        else:
                            logger.info(f"[CALC] KEEPING PASS - item has gemstones/semi-precious stones (weight may include stones)")

                    # SAFEGUARD: Don't override for jewelry lots marked "for resale" or "no scrap"
                    # These are wearable pieces with stones - weight includes non-silver components
                    elif ('resale' in title_lower or 'no scrap' in title_lower or 'not scrap' in title_lower) and 'jewelry' in title_lower:
                        logger.info(f"[CALC] KEEPING PASS - jewelry lot marked 'for resale/no scrap' (weight includes stones)")

                    # SAFEGUARD: Don't override for jewelry lots - weight often includes stones
                    # EXCEPTION: "Scrap" in title indicates melt intent - stones already removed
                    elif 'lot' in title_lower and 'jewelry' in title_lower and category == 'silver' and 'scrap' not in title_lower:
                        logger.info(f"[CALC] KEEPING PASS - silver jewelry lot (weight likely includes stones/components)")

                    # SAFEGUARD: Don't override for items with major non-metal components
                    # Crystal bowls, glass items, etc. - scale shows TOTAL weight, not just silver
                    elif any(nm in title_lower for nm in ['crystal', 'glass', 'bowl', 'vase', 'pitcher', 'dish', 'plate', 'candlestick', 'candelabra', 'porcelain', 'ceramic', 'wood', 'wooden']):
                        logger.info(f"[CALC] KEEPING PASS - item has non-metal component (crystal/glass/wood) - scale weight includes non-silver")

                    else:
                        # WEIGHT SANITY CHECK - catch implausible weights before overriding to BUY
                        weight_is_sane, sanity_msg = check_weight_sanity(metal_weight, title, category)

                        if not weight_is_sane:
                            # Weight seems unrealistic - force RESEARCH instead of BUY
                            logger.warning(f"[CALC] {sanity_msg} - forcing RESEARCH")
                            result['Recommendation'] = 'RESEARCH'
                            result['reasoning'] = f"{sanity_msg}. Manual verification needed. " + result.get('reasoning', '')
                            current_rec = 'RESEARCH'

                        elif correct_profit > 50:

                            # Verified weight + significant profit + no AI concerns + no gemstones = override to BUY

                            logger.warning(f"[CALC] OVERRIDE: PASS -> BUY (verified weight, profit ${correct_profit:.0f} > $50)")

                            result['Recommendation'] = 'BUY'

                            result['reasoning'] = result.get('reasoning', '') + f" [SERVER: Verified weight shows ${correct_profit:.0f} profit - BUY]"

                            current_rec = 'BUY'

                        else:

                            # Verified weight but modest profit - keep PASS

                            logger.info(f"[CALC] Keeping PASS - verified weight but profit only ${correct_profit:.0f}")

                else:

                    # Unknown weight source - trust AI

                    logger.info(f"[CALC] KEEPING AI's PASS - unknown weight source '{weight_source}'")

        

    except (ValueError, TypeError) as e:

        logger.error(f"Could not validate: {e}")

        traceback.print_exc()

    

    # === CONFIDENCE ADJUSTMENT ===

    # Adjust confidence based on weight source and other factors

    try:

        # Get current confidence

        conf_raw = result.get('confidence', 50)

        

        # Convert word to number if needed

        if isinstance(conf_raw, str):

            conf_lower = conf_raw.lower().strip()

            if conf_lower in ['high', 'h']:

                conf_num = 80

            elif conf_lower in ['medium', 'med', 'm']:

                conf_num = 60

            elif conf_lower in ['low', 'l']:

                conf_num = 40

            else:

                try:

                    conf_num = int(conf_raw.replace('%', '').strip())

                except:

                    conf_num = 50

        else:

            conf_num = int(conf_raw) if conf_raw else 50

        

        # Adjust based on weight source

        weight_source = result.get('weightSource', 'estimate').lower()

        if weight_source == 'scale':

            conf_num = min(100, conf_num + 15)  # Bonus for scale photo

            logger.info(f"[CONF] +15 for scale photo [PASS] [PASS] {conf_num}")

        elif weight_source == 'stated':

            conf_num = min(100, conf_num + 10)  # Bonus for stated weight

            logger.info(f"[CONF] +10 for stated weight [PASS] [PASS] {conf_num}")

        elif weight_source == 'estimate':

            conf_num = max(20, conf_num - 20)  # Penalty for estimated weight

            logger.info(f"[CONF] -20 for estimated weight [PASS] [PASS] {conf_num}")

        

        # Store numeric confidence

        result['confidence'] = conf_num

        

    except Exception as e:

        logger.error(f"[CONF] Confidence adjustment error: {e}")

    

    return result