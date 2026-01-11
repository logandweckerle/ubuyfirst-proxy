"""
Silver Agent - Handles sterling silver/scrap analysis
"""

from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class SilverAgent(BaseAgent):
    """Agent for sterling silver analysis"""

    category_name = "silver"

    # Silver uses same models as gold for scale reading
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    def get_sterling_rate(self) -> float:
        """Get current sterling silver rate per gram"""
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        return silver_oz / 31.1035 * 0.925

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

        # Costume/fashion
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

        # Native American jewelry - collectible value beyond melt
        native_keywords = ["navajo", "zuni", "hopi", "native american", "southwest",
                         "squash blossom", "turquoise cluster"]
        for kw in native_keywords:
            if kw in title:
                if price > 200:
                    return (f"NATIVE AMERICAN at ${price:.0f} - collectible value", "RESEARCH")

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

        return (None, None)

    def get_prompt(self) -> str:
        """Get the silver analysis prompt"""
        silver_oz = SPOT_PRICES.get("silver_oz", 30)
        sterling_rate = silver_oz / 31.1035 * 0.925
        source = SPOT_PRICES.get("source", "default")
        last_updated = SPOT_PRICES.get("last_updated", "unknown")

        return f"""
=== SILVER CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of sterling silver. We buy silver to MELT IT.

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
Sterling melt rate: ${sterling_rate:.2f}/gram

=== PRICING MODEL ===
1. silverWeight = totalWeight - stoneWeight
2. meltValue = silverWeight x ${sterling_rate:.2f}
3. maxBuy = meltValue x 0.75 (our ceiling - NEVER pay more)
4. sellPrice = meltValue x 0.82 (what refiner pays us)
5. Profit = maxBuy - listingPrice (buffer for price changes)
6. If listingPrice > maxBuy = ALWAYS PASS

EXAMPLE - 100g sterling flatware at $60:
- Melt: 100g x ${sterling_rate:.2f} = ${100 * sterling_rate:.0f}
- maxBuy: ${100 * sterling_rate * 0.75:.0f}
- sellPrice: ${100 * sterling_rate * 0.82:.0f}
- Profit: ${100 * sterling_rate * 0.75:.0f} - $60 = ${100 * sterling_rate * 0.75 - 60:.0f}
- $60 < maxBuy ${100 * sterling_rate * 0.75:.0f} = BUY

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

SERVERS WITH STAINLESS BLADES (cake server, pie server, cheese server):
  - "Sterling handle" + "stainless" = ONLY HANDLE IS SILVER!
  - Handle = 25-40g actual silver, blade is worthless stainless
  - Example: "103g cake server, sterling handle stainless" = 30g silver, NOT 103g!

=== FLATWARE WEIGHT ESTIMATION ===
| Piece Type | Weight |
| Dinner fork | 40-50g |
| Salad fork | 30-40g |
| Teaspoon | 25-35g |
| Tablespoon | 45-55g |
| Dinner knife | 15-25g SILVER (hollow!) |

Average per piece: ~38g (knives drag down average)

=== HOLLOWWARE WEIGHT (SOLID BOWLS) ===
| Size | Weight |
| Small dish 3-4" | 30-50g |
| Medium bowl 5-6" | 60-100g |
| Large bowl 7-8" | 120-200g |
| Bread tray 10-12" | 150-250g |
| Serving tray 12-14" | 250-400g |

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
  "Recommendation": "BUY"/"PASS",
  "verified": "Yes"/"No"/"Unknown",
  "itemtype": "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Beaded",
  "weightSource": "scale"/"stated"/"estimate",
  "weight": total weight,
  "stoneDeduction": "4g turquoise" or "0",
  "silverweight": weight after deductions,
  "pricepergram": listing price / silverweight,
  "meltvalue": silverweight x ${sterling_rate:.2f},
  "maxBuy": meltvalue x 0.75,
  "sellPrice": meltvalue x 0.82,
  "Profit": maxBuy - listingPrice,
  "confidence": INTEGER 0-100,
  "confidenceBreakdown": "Base 70 + scale 10 = 80",
  "reasoning": "DETECTION: [what] | STONES: [deduction] | CALC: [wt]g x $[rate] = $[melt] | PROFIT: $[sell] - $[price] = $[profit] | DECISION: [why]"
}}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate and fix silver response"""
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

        return response
