"""
Silver Agent - Handles sterling silver/scrap analysis

Two analysis paths:
1. STATED WEIGHT: Weight in title/description/scale photo -> calculate melt directly
2. NO WEIGHT: Visual estimation required -> more photos, different prompt
"""

import re
from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class SilverAgent(BaseAgent):
    """Agent for sterling silver analysis"""

    category_name = "silver"

    # Silver uses same models as gold for scale reading
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    # ============================================================
    # QUALITY MARKERS - Indicate genuine sterling vs plated
    # ============================================================
    QUALITY_GOOD = {
        "925": 15,             # Sterling hallmark
        "sterling": 10,        # Stated sterling
        "mexico": 10,          # Mexican silver often heavy
        "taxco": 15,           # Taxco Mexico - known for quality
        "danish": 10,          # Danish silver well-made
        "georg jensen": 20,    # Premium maker
        "native american": 15, # Often heavy sterling
        "navajo": 15,
        "zuni": 15,
    }

    QUALITY_BAD = {
        "thin": -10,
        "lightweight": -10,
        "light weight": -10,
        "hollow": -15,
    }

    # ============================================================
    # WEIGHT ESTIMATES BY ITEM TYPE (grams)
    # Sterling is typically heavier than gold items
    # ============================================================
    WEIGHT_ESTIMATES = {
        # Chains
        "chain_thin": (10, 20),
        "chain_medium": (25, 50),
        "chain_thick": (60, 120),

        # Bracelets
        "bracelet_thin": (15, 30),
        "bracelet_medium": (35, 60),
        "bracelet_thick": (70, 120),
        "cuff_bracelet": (30, 80),
        "bangle": (20, 50),

        # Rings
        "ring_thin": (3, 6),
        "ring_medium": (6, 12),
        "ring_thick": (12, 25),

        # Native American
        "squash_blossom": (150, 300),
        "concho_belt": (200, 500),
        "cuff_na": (50, 150),

        # Flatware (per piece)
        "fork": (30, 50),
        "knife": (40, 70),
        "spoon": (25, 45),
        "tablespoon": (50, 80),
        "serving_piece": (60, 120),
    }

    def get_sterling_rate(self) -> float:
        """Get current sterling silver rate per gram"""
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        return silver_oz / 31.1035 * 0.925

    def has_stated_weight(self, data: dict) -> tuple:
        """
        Check if weight is explicitly stated in title or description.
        Returns (has_weight: bool, weight_grams: float or None, source: str)
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", data.get("description", "")).lower()
        combined = f"{title} {description}"

        # Weight patterns
        weight_patterns = [
            r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b',
            r'(\d+\.?\d*)\s*(?:oz|ounce)',
            r'(\d+\.?\d*)\s*dwt\b',
        ]

        for pattern in weight_patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                weight = float(match.group(1))
                if 'oz' in match.group(0).lower():
                    weight = weight * 31.1035
                elif 'dwt' in match.group(0).lower():
                    weight = weight * 1.555

                if re.search(pattern, title, re.IGNORECASE):
                    return (True, weight, "title")
                else:
                    return (True, weight, "description")

        return (False, None, None)

    def analyze_no_weight_indicators(self, data: dict, price: float) -> dict:
        """
        Analyze listings without stated weight for visual indicators.
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", data.get("description", "")).lower()
        combined = f"{title} {description}"

        analysis = {
            "quality_score": 50,
            "quality_notes": [],
            "weight_estimate_low": 0,
            "weight_estimate_high": 0,
            "item_type": None,
            "green_flags": [],
            "red_flags": [],
            "confidence_boost": 0,
            "requires_photos": True,
            "recommended_images": 6,
        }

        # === QUALITY MARKERS ===
        for marker, score in self.QUALITY_GOOD.items():
            if marker in combined:
                analysis["quality_score"] += score
                analysis["quality_notes"].append(f"+{score}: {marker}")
                if marker in ["taxco", "georg jensen", "navajo"]:
                    analysis["green_flags"].append(f"Premium maker: {marker}")

        for marker, score in self.QUALITY_BAD.items():
            if marker in combined:
                analysis["quality_score"] += score
                analysis["quality_notes"].append(f"{score}: {marker}")

        # === ITEM TYPE DETECTION ===
        if "squash blossom" in combined:
            analysis["item_type"] = "squash_blossom"
            analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 150, 300
        elif "concho belt" in combined:
            analysis["item_type"] = "concho_belt"
            analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 200, 500
        elif "cuff" in combined:
            if any(kw in combined for kw in ["navajo", "native", "zuni", "turquoise"]):
                analysis["item_type"] = "cuff_na"
                analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 50, 150
            else:
                analysis["item_type"] = "cuff_bracelet"
                analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 30, 80
        elif "bracelet" in combined or "bangle" in combined:
            analysis["item_type"] = "bracelet"
            analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 25, 60
        elif "chain" in combined or "necklace" in combined:
            if "thick" in combined or "heavy" in combined:
                analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 60, 120
            else:
                analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 20, 50
            analysis["item_type"] = "chain"
        elif "ring" in combined:
            analysis["item_type"] = "ring"
            analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 5, 15
        elif any(kw in combined for kw in ["fork", "spoon", "knife", "flatware"]):
            analysis["item_type"] = "flatware"
            analysis["weight_estimate_low"], analysis["weight_estimate_high"] = 30, 60

        # === GREEN FLAGS ===
        has_sterling = "sterling" in combined or "925" in combined
        has_weight, _, _ = self.has_stated_weight(data)
        if has_sterling and not has_weight:
            analysis["green_flags"].append("Sterling stated but NO WEIGHT = opportunity")
            analysis["confidence_boost"] += 10

        # === CALCULATE POTENTIAL VALUE ===
        if analysis["weight_estimate_low"] > 0:
            rate = self.get_sterling_rate()
            analysis["melt_estimate_low"] = analysis["weight_estimate_low"] * rate
            analysis["melt_estimate_high"] = analysis["weight_estimate_high"] * rate
            analysis["max_buy_conservative"] = analysis["melt_estimate_low"] * 0.75

            if price < analysis["max_buy_conservative"]:
                analysis["green_flags"].append(
                    f"Price ${price:.0f} < conservative maxBuy ${analysis['max_buy_conservative']:.0f}"
                )
                analysis["confidence_boost"] += 15

        return analysis

    def get_no_weight_prompt(self) -> str:
        """Specialized prompt for listings WITHOUT stated weight."""
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        sterling_gram = silver_oz / 31.1035 * 0.925

        return f"""
=== SILVER VISUAL WEIGHT ESTIMATION ===

This listing has NO STATED WEIGHT. You must ESTIMATE weight from photos.

=== PHOTO ANALYSIS ===
1. Check ALL images for a scale photo first
2. If no scale, estimate by:
   - Item thickness and size
   - Comparison to hand/wrist if shown
   - Construction (solid vs hollow)

=== WEIGHT ESTIMATION GUIDE ===
JEWELRY:
| Item | Weight Range |
|------|-------------|
| Thin chain | 10-25g |
| Medium chain | 30-60g |
| Heavy chain | 70-150g |
| Thin bracelet | 15-30g |
| Medium bracelet | 35-60g |
| Cuff bracelet | 40-100g |

NATIVE AMERICAN:
| Item | Weight Range |
|------|-------------|
| Squash blossom | 150-300g |
| Concho belt | 200-500g |
| Heavy cuff | 50-150g |

FLATWARE (per piece):
| Item | Weight |
|------|--------|
| Fork | 30-50g |
| Knife | 40-70g |
| Spoon | 25-45g |

=== CURRENT PRICING ===
Sterling (925): ${sterling_gram:.2f}/gram

=== CONSERVATIVE PRICING ===
1. Use LOW weight estimate
2. meltValue = lowEstimate × ${sterling_gram:.2f}
3. maxBuy = meltValue × 0.75 (conservative for estimates)
4. Profit = maxBuy - listingPrice

=== OUTPUT FORMAT ===
{{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"RESEARCH"/"PASS",
  "verified": "No",
  "purity": "Sterling 925",
  "itemtype": item type,
  "weightSource": "estimate",
  "weightEstimateLow": number,
  "weightEstimateHigh": number,
  "weight": "~X-Yg (estimated)",
  "silverweight": use low estimate,
  "meltvalue": calculated,
  "maxBuy": meltvalue × 0.75,
  "Profit": maxBuy - listingPrice,
  "confidence": 40-60 MAX,
  "visualAnalysis": "What you observed",
  "reasoning": "VISUAL: [observations] | EST: ~Xg | CALC | DECISION"
}}

Confidence CANNOT exceed 60 for estimates.
"""

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for silver before AI analysis.
        Returns (reason, "PASS"/"RESEARCH") or (None, None) to continue.
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", "").lower()
        combined = f"{title} {description}"

        # ============================================================
        # TIER 0: INSTANT PASS - Plated / No value
        # ============================================================
        plated_keywords = ["silver plate", "silverplate", "silver plated", "epns",
                          "nickel silver", "alpaca", "rogers", "1847 rogers",
                          "community", "holmes & edwards", "wm rogers", "oneida plate",
                          "quadruple plate", "triple plate", "electroplate",
                          "silver tone", "silvertone", "silver color"]
        for kw in plated_keywords:
            if kw in title:
                return (f"PLATED - '{kw}' detected in title", "PASS")

        # Common plated manufacturer marks
        plated_marks = ["epns", "a1", "ep", "e.p.", "ep copper", "ns", "n.s."]
        for mark in plated_marks:
            if f" {mark} " in f" {title} " or title.startswith(f"{mark} "):
                return (f"PLATED MARK - '{mark}' indicates electroplate", "PASS")

        # Costume/fashion - only PASS if NOT a costume search
        # Costume searches may have hidden precious metals in lots
        alias = data.get("Alias", "").lower()
        is_costume_search = "costume" in alias or "fashion" in alias

        if not is_costume_search:
            if any(kw in title for kw in ["costume", "fashion jewelry", "imitation"]):
                return ("COSTUME/FASHION - not real silver", "PASS")

        # ============================================================
        # TIER 0: RESEARCH - Needs manual verification
        # ============================================================
        # UNTESTED silver = unknown purity, could be plated
        untested_phrases = [
            "not tested", "untested", "has not been tested", "haven't tested",
            "not verified", "unverified", "content unknown", "purity unknown",
            "may be silver", "possibly silver", "might be silver", "unmarked",
            "no hallmark", "no markings"
        ]
        for phrase in untested_phrases:
            if phrase in combined:
                return (f"UNTESTED - '{phrase}' detected, unknown purity", "RESEARCH")

        # High-value items need manual verification
        if price > 1000:
            return (f"HIGH VALUE at ${price:.0f} - manual verification required", "RESEARCH")

        # LOTS and MIXED ITEMS: Historical data shows -44% ROI on silver lots
        # Lots are often overvalued, mixed quality, or have plated items included
        lot_keywords = ["lot", "mixed lot", "jewelry lot", "bulk", "mixed jewelry"]
        for kw in lot_keywords:
            if kw in title:
                return (f"SILVER LOT - Historical data shows negative ROI on lots. '{kw}' detected, manual verification required.", "RESEARCH")

        # ============================================================
        # NATIVE AMERICAN / TURQUOISE - Historical data shows HIGH ROI
        # Cuffs: 80% win rate, 199% avg ROI
        # Squash Blossom: 83% win rate, 253% avg ROI
        # Key: If price < 150% of sterling melt, turquoise is FREE upside
        # ============================================================
        import re
        is_native = any(kw in title for kw in ['navajo', 'zuni', 'hopi', 'native american', 'southwest'])
        has_turquoise = 'turquoise' in title
        is_cuff = 'cuff' in title
        is_squash = 'squash' in title or 'squash blossom' in title

        if (is_native or has_turquoise) and (is_cuff or is_squash):
            # Check for stated weight
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', title, re.IGNORECASE)
            if weight_match:
                weight = float(weight_match.group(1))
                sterling_rate = self.get_sterling_rate()
                melt_value = weight * sterling_rate
                max_buy_melt = melt_value * 1.5  # Allow up to 150% of melt for turquoise premium

                style = "SQUASH BLOSSOM" if is_squash else "CUFF"
                if weight >= 50 and price <= max_buy_melt:
                    # HISTORICAL DATA: Heavy turquoise cuffs/squash bought at <150% melt = high ROI
                    return (f"NATIVE {style} DEAL: {weight}g sterling = ${melt_value:.0f} melt. Price ${price:.0f} is good. Turquoise adds collector premium!", "BUY")
                elif weight >= 30 and price <= melt_value * 2:
                    return (f"NATIVE {style}: {weight}g = ${melt_value:.0f} melt. Price ${price:.0f} may have upside.", "RESEARCH")

        # Other Native American jewelry - still flag for research
        native_keywords = ["navajo", "zuni", "hopi", "native american", "southwest",
                         "squash blossom", "turquoise cluster"]
        for kw in native_keywords:
            if kw in title:
                if price > 200:
                    return (f"NATIVE AMERICAN at ${price:.0f} - collectible value", "RESEARCH")

        # ============================================================
        # TAXCO / MEXICO SILVER - Historical 86-100% win rate, 123-148% avg ROI
        # Mexican silver has collector value beyond melt
        # ============================================================
        is_taxco = 'taxco' in title
        is_mexico = 'mexico' in title or 'mexican' in title

        if is_taxco or is_mexico:
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', title, re.IGNORECASE)
            if weight_match:
                weight = float(weight_match.group(1))
                sterling_rate = self.get_sterling_rate()
                melt_value = weight * sterling_rate
                origin = "TAXCO" if is_taxco else "MEXICAN"

                # Taxco/Mexico at <200% melt with decent weight = BUY
                if weight >= 30 and price <= melt_value * 2.0:
                    return (f"{origin} SILVER DEAL: {weight}g = ${melt_value:.0f} melt. Price ${price:.0f} - Historical 86-100% win rate!", "BUY")
                elif weight >= 20 and price <= melt_value * 2.5:
                    return (f"{origin} SILVER: {weight}g = ${melt_value:.0f} melt. Price ${price:.0f} may have collector upside.", "RESEARCH")

        # ============================================================
        # JAMES AVERY - Historical 25% win rate, -20% avg ROI
        # Overpriced for silver content, collectors pay retail not wholesale
        # ============================================================
        if 'james avery' in title:
            if price > 100:
                return (f"JAMES AVERY at ${price:.0f} - Historical 25% win rate, -20% ROI. Overpriced for melt.", "PASS")
            else:
                return (f"JAMES AVERY at ${price:.0f} - usually overpriced, verify carefully", "RESEARCH")

        # ============================================================
        # DEAD PAWN - High-priced dead pawn items are often overvalued
        # Historical data shows major losses on expensive dead pawn
        # ============================================================
        if 'dead pawn' in title and price > 250:
            return (f"DEAD PAWN at ${price:.0f} - High-priced dead pawn often overvalued. Historical losses.", "PASS")

        # ============================================================
        # STERLING CUFFS - Historical 85% win rate, 250% avg ROI
        # Even without turquoise, sterling cuffs perform well
        # ============================================================
        is_cuff = 'cuff' in title
        if is_cuff and not (is_native or has_turquoise):
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', title, re.IGNORECASE)
            if weight_match:
                weight = float(weight_match.group(1))
                sterling_rate = self.get_sterling_rate()
                melt_value = weight * sterling_rate
                if weight >= 25 and price <= melt_value * 1.5:
                    return (f"STERLING CUFF DEAL: {weight}g = ${melt_value:.0f} melt. Price ${price:.0f} - Historical 85% win rate!", "BUY")
            else:
                # Cuffs without stated weight still win big - flag for research
                if price < 75:
                    return (f"STERLING CUFF at ${price:.0f} - No weight stated but cuffs have 85% win rate. Worth checking!", "RESEARCH")

        # ============================================================
        # STERLING NECKLACES - Historical 93% win rate, 345% avg ROI
        # Heavy sterling necklaces are very profitable
        # ============================================================
        is_necklace = 'necklace' in title
        if is_necklace:
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', title, re.IGNORECASE)
            if weight_match:
                weight = float(weight_match.group(1))
                sterling_rate = self.get_sterling_rate()
                melt_value = weight * sterling_rate
                if weight >= 30 and price <= melt_value * 1.3:
                    return (f"STERLING NECKLACE DEAL: {weight}g = ${melt_value:.0f} melt. Price ${price:.0f} - Historical 93% win rate!", "BUY")

        # Tiffany or designer silver - may have collectible premium
        if "tiffany" in title and price > 300:
            return (f"TIFFANY at ${price:.0f} - may have collectible premium", "RESEARCH")

        # WEIGHTED BASES - Sugar/creamer sets, candlesticks, etc.
        # These are MOSTLY CEMENT/FILLER - need careful weight analysis
        weighted_keywords = ["sugar", "creamer", "cream and sugar", "sugar and creamer",
                           "candlestick", "candle holder", "compote", "footed",
                           "weighted base", "weighted bottom", "reinforced"]
        for kw in weighted_keywords:
            if kw in title:
                return (f"WEIGHTED ITEM '{kw}' - base is mostly cement/filler, use fixed silver amounts from prompt", "RESEARCH")

        # FLATWARE KNIVES - Stainless blade with hollow sterling handle
        # The blade is worthless stainless, handle is 15-25g actual silver
        # Stated weight is MEANINGLESS - handle is hollow/filled!
        knife_keywords = ["dinner knife", "butter knife", "steak knife", "knife set",
                        "knives", "knife handle", "gorham knife", "luncheon knife"]
        for kw in knife_keywords:
            if kw in title:
                return (f"FLATWARE KNIFE '{kw}' - hollow handle with stainless blade, use 15-25g per knife not stated weight", "RESEARCH")

        # PLACE SETTINGS / FLATWARE WITH STAINLESS MENTIONED
        # If description mentions "stainless steel" + flatware, the knives have stainless blades
        # Total weight INCLUDES stainless which is worthless - must deduct ~85g per knife
        flatware_keywords = ["place setting", "flatware", "silverware", "cutlery"]
        stainless_in_desc = "stainless" in description
        if stainless_in_desc and any(kw in title for kw in flatware_keywords):
            return ("FLATWARE WITH STAINLESS - description mentions stainless steel, knife blades are NOT sterling. Deduct 85g per knife from total weight!", "RESEARCH")

        # FILIGREE - Extremely lightweight delicate lacework metal
        # A "large" filigree brooch might only be 3-8g total!
        if "filigree" in title:
            return ("FILIGREE - extremely lightweight delicate metalwork, small items only 3-8g", "RESEARCH")

        # Small brooches/pins without stated weight - typically very light
        small_jewelry_keywords = ["brooch", "pin", "butterfly", "dragonfly", "flower pin"]
        if any(kw in title for kw in small_jewelry_keywords):
            # Only flag if no weight stated and price seems high for small item
            if price > 30:
                return (f"SMALL JEWELRY (brooch/pin) at ${price:.0f} - verify weight, small items typically 3-10g", "RESEARCH")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the silver analysis prompt"""
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        sterling_rate = silver_oz / 31.1035 * 0.925
        silver_800_rate = silver_oz / 31.1035 * 0.800
        source = SPOT_PRICES.get("source", "default")
        last_updated = SPOT_PRICES.get("last_updated", "unknown")

        return f"""
=== SILVER CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of silver items. We buy silver to MELT IT.

=== STEP 1: FIND STATED WEIGHT (CRITICAL!) ===
LOOK AT EVERY IMAGE FOR A SCALE PHOTO! Scale photos show digital display with numbers.
If you see ANY scale display in ANY image, USE THAT EXACT WEIGHT - do NOT estimate!

Priority order:
1. SCALE PHOTO - Look at ALL images! If ANY shows a scale display, USE THAT NUMBER (weightSource="scale")
2. DESCRIPTION - If seller states weight, USE IT (weightSource="stated")
3. TITLE - If weight mentioned in title, USE IT (weightSource="stated")
4. ESTIMATE - ONLY if NO stated weight exists anywhere (weightSource="estimate")

NEVER estimate weight if scale photo exists - this causes OVERVALUATION!

=== STEP 2: CHECK FOR STONES/BEADS ===
GEMSTONES = $0 VALUE - deduct their weight!
| Stone Type | Deduct |
| Small accent (<5mm) | 0.5-1g |
| Medium cabochon | 1-3g |
| Large cabochon (10-20mm) | 3-6g |
| Turquoise cluster | 5-15g |

BEADED JEWELRY = MOSTLY BEADS, NOT SILVER!
- Heavy bead necklace: Only 10-15% is silver
- Mixed bead with spacers: 20-30% silver
- Charm bracelet with beads: 50-70% silver

=== CURRENT PRICING ({source}) ===
Silver spot: ${silver_oz:.2f}/oz (updated: {last_updated})

PURITY RATES (what refiners pay per gram):
- Sterling (.925): ${sterling_rate:.2f}/gram
- 800 Silver (.800): ${silver_800_rate:.2f}/gram (Continental European)

USE THE CORRECT RATE! 800 silver is NOT sterling - it's only 80% pure!

=== PRICING MODEL ===
1. silverWeight = totalWeight - stoneWeight
2. meltValue = silverWeight x ${sterling_rate:.2f}
3. maxBuy = meltValue x 0.70 (our ceiling - NEVER pay more)
4. sellPrice = meltValue x 0.82 (what refiner pays us)
5. Profit = maxBuy - listingPrice (buffer for price changes)
6. If listingPrice > maxBuy = ALWAYS PASS

EXAMPLE - 100g sterling flatware at $60:
- Melt: 100g x ${sterling_rate:.2f} = ${100 * sterling_rate:.0f}
- maxBuy: ${100 * sterling_rate * 0.70:.0f}
- sellPrice: ${100 * sterling_rate * 0.82:.0f}
- Profit: ${100 * sterling_rate * 0.70:.0f} - $60 = ${100 * sterling_rate * 0.70 - 60:.0f}
- $60 < maxBuy ${100 * sterling_rate * 0.70:.0f} = BUY

=== ITEM TYPE RULES ===

SOLID STERLING (100% weight is silver):
- Flatware (forks, spoons)
- Bowls, trays (non-weighted)
- Simple jewelry

WEIGHTED ITEMS (cement/pitch filled - use FIXED silver amounts):
CRITICAL: "weighted", "cement", "footed", "reinforced" = MOSTLY FILLER, NOT SILVER!
| Item | ACTUAL SILVER |
| Small candlestick (each) | 25g |
| Medium candlestick (each) | 35-45g |
| Large candlestick (each) | 50-75g |
| Cream/sugar SET | 90g total |
| Salt/pepper shaker (each) | 15-25g |
| Weighted bowl 8-10" | 150-200g |
| Footed compote dish (each) | 40-80g |
| Weighted base items | 15% of stated weight (85% is cement/filler!) |

WARNING: If description mentions "cement", "weighted base", "footed" = REDUCE WEIGHT!

FLATWARE KNIVES: Deduct 85g per knife (stainless blade)
KNIFE HANDLES ONLY (no blade): 15-25g ACTUAL silver per handle (hollow/weighted!)
  - Total weight is MEANINGLESS for handles - they're filled with cement/pitch
  - Example: "596g 9 handles" = 9 x 15-20g = 135-180g ACTUAL silver, NOT 596g!

PLACE SETTINGS WITH KNIVES (CRITICAL!):
  - "4 piece place setting 180g" with knife = DEDUCT 85g for the stainless blade!
  - If description mentions "stainless steel knife blade" = blade is NOT sterling!
  - Example: "180g includes stainless steel knife blade" = only ~95g actual sterling
  - ALWAYS check description for "stainless" when flatware includes knives!

SERVERS WITH STAINLESS BLADES (cake server, pie server, cheese server):
  - "Sterling handle" + "stainless" = ONLY HANDLE IS SILVER!
  - Handle = 25-40g actual silver, blade is worthless stainless
  - Example: "103g cake server, sterling handle stainless" = 30g silver, NOT 103g!

=== FLATWARE WEIGHT ESTIMATION ===
| Piece Type | Weight |
| Dinner fork | 45g |
| Salad fork | 35g |
| Dinner spoon/Tablespoon | 45g |
| Soup spoon | 35g |
| Teaspoon | 20g |
| Iced tea spoon | 18g |
| Flat butter knife | 20g |
| Dinner knife (filled handle) | 15-20g SILVER ONLY |
| Serving fork/spoon | 50-60g |
| Small pickle fork | 10g |

Average per piece: ~30-35g (knives and teaspoons drag down average)

=== HOLLOWWARE WEIGHT (SOLID BOWLS) ===
| Size | Weight |
| Small dish 3-4" | 30-50g |
| Medium bowl 5-6" | 60-100g |
| Large bowl 7-8" | 120-200g |
| Bread tray 10-12" | 150-250g |
| Serving tray 12-14" | 250-400g |

=== FILIGREE & SMALL JEWELRY (VERY LIGHTWEIGHT!) ===
FILIGREE = delicate lacework metal, EXTREMELY LIGHT!
| Item | Weight |
| Small filigree brooch/pin | 2-5g |
| Medium filigree brooch 1-1.5" | 4-8g |
| Large filigree brooch 2"+ | 6-12g |
| Filigree bracelet | 8-15g |
| Filigree pendant | 2-6g |

SMALL JEWELRY (pins, brooches):
| Item | Weight |
| Butterfly/insect pin | 3-8g |
| Small bar pin | 2-4g |
| Cameo brooch (stone is heavy!) | 3-6g SILVER only |
| Flower brooch | 4-10g |

CRITICAL: "Antique" + "Filigree" + "Brooch" = typically 3-8g total!
A $50 filigree brooch at 5g 800 silver = $12 melt = PASS!

=== INSTANT PASS ===
- Rogers, 1847 Rogers, Community, EPNS = PLATED
- "Silver Plate", "Silverplate" = NOT STERLING
- Stone jewelry priced for the stone, not the silver
- Price > $3/gram of silver weight

=== UNTESTED = NEVER BUY ===
If description says ANY of these, ALWAYS return RESEARCH (not BUY):
- "not tested", "untested", "content unknown"
- "has not been tested", "silver content not verified"
- "may be silver", "possibly silver", "might be silver"
These could be plated! Unknown purity = unknown value = RESEARCH required.

=== ESTIMATED WEIGHT RULE ===
If weightSource = "estimate", Recommendation CANNOT be "BUY"!
- PASS if price too high for any reasonable weight
- RESEARCH if could be profitable at higher weight
- BUY only with VERIFIED weight (scale or stated)

=== CONFIDENCE SCORING ===
- Scale photo: Start at 75
- Seller stated: Start at 70
- ESTIMATED: Start at 45 (MAX 50!)

=== JSON OUTPUT ===
{{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "verified": "Yes"/"No"/"Unknown",
  "purity": "925"/"800" (use correct rate!),
  "itemtype": "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Filigree"/"Beaded",
  "weightSource": "scale"/"stated"/"estimate",
  "weight": total weight,
  "stoneDeduction": "4g turquoise" or "0",
  "silverweight": weight after deductions,
  "pricepergram": listing price / silverweight,
  "meltvalue": silverweight x rate (925=${sterling_rate:.2f}, 800=${silver_800_rate:.2f}),
  "maxBuy": meltvalue x 0.70,
  "sellPrice": meltvalue x 0.82,
  "Profit": maxBuy - listingPrice,
  "confidence": INTEGER 0-100,
  "confidenceBreakdown": "Base 70 + scale 10 = 80",
  "reasoning": "DETECTION: [what] | STONES: [deduction] | CALC: [wt]g x $[rate] = $[melt] | PROFIT: $[sell] - $[price] = $[profit] | DECISION: [why]"
}}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    # Premium silver brands with collector value beyond melt
    PREMIUM_BRANDS = [
        "gorham", "towle", "wallace", "reed barton", "reed & barton", "kirk stieff",
        "international", "alvin", "shreve", "whiting", "durgin", "georg jensen",
        "tiffany", "buccellati", "cartier", "christofle"
    ]

    def validate_response(self, response: dict, data: dict = None) -> dict:
        """Validate and fix silver response"""

        # Get title and price from data
        title = ""
        listing_price = 0
        if data:
            title = data.get("Title", "").lower().replace('+', ' ')
            listing_price = float(str(data.get("TotalPrice", data.get("Price", data.get("_listing_price", 0)))).replace('$', '').replace(',', '') or 0)

        # Ensure estimated weight can't have BUY recommendation
        if response.get("weightSource") == "estimate" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Estimated weight cannot be BUY"

        # Ensure negative profit = PASS
        try:
            profit = float(str(response.get("Profit", "0")).replace("+", "").replace("$", ""))
            if profit < 0 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"
        except:
            pass

        # Check for premium silver brands
        is_premium = any(brand in title for brand in self.PREMIUM_BRANDS)

        # === HISTORICAL PERFORMANCE BOOSTS ===
        # Based on analysis of matched buy/sell transactions:
        # - Cuffs: 136% ROI, 85% win rate (33 items, $5,089 profit)
        # - Necklaces: 260% ROI, 93% win rate (14 items, $3,971 profit)
        # - Bracelets: 114% ROI (18 items, $2,523 profit)
        current_confidence = response.get("confidence", 50)
        if isinstance(current_confidence, str):
            conf_lower = current_confidence.lower().replace('%', '').strip()
            if conf_lower in ('high', 'very high'):
                current_confidence = 85
            elif conf_lower in ('medium', 'moderate'):
                current_confidence = 60
            elif conf_lower in ('low', 'very low'):
                current_confidence = 35
            else:
                try:
                    current_confidence = int(conf_lower or 50)
                except ValueError:
                    current_confidence = 50

        if "cuff" in title:
            response["confidence"] = min(current_confidence + 10, 95)
            response["reasoning"] = response.get("reasoning", "") + " | BOOST: Silver cuffs have 136% historical ROI (+10 confidence)"

        if "necklace" in title:
            response["confidence"] = min(current_confidence + 8, 95)
            response["reasoning"] = response.get("reasoning", "") + " | BOOST: Silver necklaces have 260% historical ROI (+8 confidence)"

        # Navajo/Native American turquoise items perform well
        if any(kw in title for kw in ["navajo", "zuni", "native american"]) and "turquoise" in title:
            response["confidence"] = min(current_confidence + 5, 95)
            response["reasoning"] = response.get("reasoning", "") + " | BOOST: Native American turquoise has strong resale (+5 confidence)"

        # CRITICAL: High-value silver items should NOT auto-PASS
        # Gorham Chantilly, Towle French Provincial etc. have collector value
        rec = response.get("Recommendation", "")

        # Premium brand silver over $200 that got PASS - verify
        if is_premium and listing_price > 200 and rec == "PASS":
            response["Recommendation"] = "RESEARCH"
            response["Qualify"] = "Maybe"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Premium silver brand at ${listing_price:.0f} - verify collector value beyond melt"
            print(f"[SILVER] OVERRIDE: PASS->RESEARCH for premium brand at ${listing_price:.0f}")

        # Any silver over $500 that got PASS - worth verifying
        if listing_price > 500 and rec == "PASS":
            response["Recommendation"] = "RESEARCH"
            response["Qualify"] = "Maybe"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value silver at ${listing_price:.0f} - verify weight/value"

        # Large flatware sets over $300 - often undervalued
        flatware_keywords = ["flatware", "place setting", "service for", "silverware set"]
        if any(kw in title for kw in flatware_keywords) and listing_price > 300 and rec == "PASS":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Flatware set at ${listing_price:.0f} - verify piece count and weight"

        return response
