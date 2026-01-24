"""
Palladium Agent - Handles palladium jewelry/scrap analysis
"""

from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class PalladiumAgent(BaseAgent):
    """Agent for palladium jewelry and scrap analysis"""

    category_name = "palladium"

    # Palladium needs high-detail image analysis for scale reading
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    def get_purity_rates(self) -> dict:
        """Calculate current palladium purity rates from spot price"""
        palladium_oz = SPOT_PRICES.get("palladium_oz", 950)
        palladium_gram = palladium_oz / 31.1035
        return {
            "PD950": palladium_gram * 0.950,
            "PD500": palladium_gram * 0.500,
        }

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for palladium before AI analysis.
        Returns (reason, "PASS"/"RESEARCH") or (None, None) to continue.
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", "").lower()
        combined = f"{title} {description}"

        # ============================================================
        # TIER 0: INSTANT PASS - No value / plated
        # ============================================================
        plated_keywords = ["palladium plated", "palladium tone", "palladium color",
                          "palladium finish"]
        for kw in plated_keywords:
            if kw in title:
                return (f"PLATED - '{kw}' detected in title", "PASS")

        # Fashion jewelry keywords
        fashion_keywords = ["costume", "fashion jewelry", "rhinestone", "cubic zirconia", "cz ",
                          "simulated", "faux", "imitation"]
        for kw in fashion_keywords:
            if kw in title:
                return (f"FASHION/COSTUME - '{kw}' detected", "PASS")

        # Single earring = no value
        if "single earring" in title or "one earring" in title:
            return ("SINGLE EARRING - no resale value", "PASS")

        # ============================================================
        # TIER 0: RESEARCH - Needs manual verification
        # ============================================================
        # UNTESTED palladium = unknown purity
        untested_phrases = [
            "not tested", "untested", "has not been tested", "haven't tested",
            "not verified", "unverified", "purity unknown",
            "may be palladium", "possibly palladium", "might be palladium", "unmarked",
            "no markings", "unstamped"
        ]
        for phrase in untested_phrases:
            if phrase in combined:
                return (f"UNTESTED - '{phrase}' detected, unknown purity", "RESEARCH")

        # High-value items need manual verification
        if price > 2000:
            return (f"HIGH VALUE at ${price:.0f} - manual verification required", "RESEARCH")

        # Diamond-heavy listings - value in stones, not palladium
        diamond_keywords = ["diamond ring", "diamond bracelet", "diamond necklace",
                          "diamond earrings", "diamond pendant", "engagement ring"]
        for kw in diamond_keywords:
            if kw in title:
                if price > 800:
                    return (f"DIAMOND JEWELRY at ${price:.0f} - value may be in stones", "RESEARCH")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the palladium analysis prompt"""
        palladium_oz = SPOT_PRICES.get("palladium_oz", 950)
        palladium_gram = palladium_oz / 31.1035
        source = SPOT_PRICES.get("source", "default")
        last_updated = SPOT_PRICES.get("last_updated", "unknown")

        pd950 = palladium_gram * 0.950
        pd500 = palladium_gram * 0.500

        return f"""
=== PALLADIUM CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of palladium items. We buy palladium to MELT IT.

IMPORTANT: Palladium is RARE in jewelry. Most "white metal" jewelry is white gold or platinum, NOT palladium.
True palladium jewelry will be marked "Pd", "PD950", "PD500", "PALL", or "Palladium".

=== STEP 1: FIND STATED WEIGHT (CRITICAL!) ===
LOOK AT EVERY IMAGE FOR A SCALE PHOTO! Scale photos show digital display with numbers.
If you see ANY scale display in ANY image, USE THAT EXACT WEIGHT - do NOT estimate!

Priority order:
1. SCALE PHOTO - Look at ALL images! If ANY shows a scale display, USE THAT NUMBER
2. DESCRIPTION - If seller states weight in description, USE IT (weightSource="stated")
3. TITLE - If weight mentioned in title, USE IT
4. ESTIMATE - ONLY if NO stated weight exists anywhere

SCALE READING:
- Digital scale display shows numbers like "14.4" with unit indicator
- If scale shows "g" mode: USE THAT EXACT NUMBER as weight
- If scale shows "dwt": Multiply by 1.555 for grams
- WATCH FOR DECIMALS: "1.5g" vs "15g" is 10x difference!

NEVER estimate weight if scale photo exists - this causes OVERVALUATION!

=== STEP 2: STONE/PEARL DEDUCTIONS ===
DIAMONDS, GEMSTONES = $0 VALUE - just deduct their weight!
- Small accent stone: 0.1-0.5g
- Medium stone (5-8mm): 0.5-1.5g
- Large stone (8-12mm): 1.5-3g
- Very large stones: 3-5g+

=== PALLADIUM PURITY MARKINGS ===
- PD950 / 950PD / PALL = 95% palladium (most common)
- PD500 / 500PD = 50% palladium (palladium alloy)
- "Pd" stamp = assume PD950
- "Palladium" with no mark = assume PD950

WARNING: If no palladium mark visible, it's probably NOT palladium!
Palladium is rare - most white metal is white gold or platinum.

=== CURRENT PRICING ({source} - {last_updated}) ===
Palladium spot: ${palladium_oz:,.0f}/oz = ${palladium_gram:.2f}/gram pure

PURITY RATES (what refiners pay):
- PD950: ${pd950:.2f}/gram
- PD500: ${pd500:.2f}/gram

=== PRICING MODEL ===
1. palladiumWeight = totalWeight - stoneWeight (deduct ALL stones)
2. meltValue = palladiumWeight x purityRate
3. maxBuy = meltValue x 0.80 (our ceiling - NEVER pay more, palladium is harder to sell)
4. sellPrice = meltValue x 0.88 (what refiner pays us)
5. Margin = maxBuy - listingPrice (buffer for price changes)
6. If listingPrice > maxBuy = ALWAYS PASS

EXAMPLE - PD950 ring, 6g, listed at $200:
- Melt: 6g x ${pd950:.2f} = ${6 * pd950:.0f}
- maxBuy: ${6 * pd950 * 0.80:.0f} (our ceiling)
- sellPrice: ${6 * pd950 * 0.88:.0f} (what we get)
- Margin: ${6 * pd950 * 0.80:.0f} - $200 = ${6 * pd950 * 0.80 - 200:.0f}
- $200 < maxBuy ${6 * pd950 * 0.80:.0f} = BUY

=== INSTANT PASS CONDITIONS ===
- Single earring (worthless)
- Diamond-focused jewelry (value in stones, not metal)
- Price > melt value
- No palladium mark visible (probably white gold or platinum)
- Plated/Tone keywords

=== UNTESTED = NEVER BUY ===
If description says ANY of these, ALWAYS return RESEARCH (not BUY):
- "not tested", "untested", "purity unknown"
- "may be palladium", "possibly palladium"
Unknown purity = unknown value = RESEARCH required.

=== WEIGHT ESTIMATION ===
| Item Type | Weight Range |
| Thin band ring | 2-4g |
| Standard band | 4-7g |
| Heavy band | 7-10g |
| Stud earrings (pair) | 1-3g |
| Drop earrings (pair) | 2-4g |
| Pendant small | 2-4g |
| Pendant large | 4-8g |

=== ESTIMATED WEIGHT RULE ===
If weightSource = "estimate", Recommendation CANNOT be "BUY"!
- Estimated weight = we're guessing = RESEARCH or PASS only
- BUY requires scale photo or seller-stated weight

=== CONFIDENCE SCORING ===
- Scale photo: Start at 75
- Seller stated weight: Start at 70
- ESTIMATED weight: Start at 45 (MAXIMUM 50!)
- Clear purity mark (PD950): +10
- No purity mark: -15 (palladium is rare - probably misidentified)

=== JSON OUTPUT (ALL REQUIRED) ===
{{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH" (PASS if listingPrice > maxBuy),
  "verified": "Yes"/"No"/"Unknown",
  "karat": "PD950"/"PD500" (purity marking found),
  "itemtype": "Ring"/"Earrings"/"Pendant"/"Bracelet"/"Chain"/"Scrap",
  "weightSource": "scale"/"stated"/"estimate",
  "weight": total weight as string (e.g. "6g"),
  "stoneDeduction": "0.5g diamonds" or "0",
  "palladiumweight": weight after deductions,
  "pricepergram": listing price / palladiumweight,
  "meltvalue": calculated melt value,
  "maxBuy": meltvalue x 0.80,
  "sellPrice": meltvalue x 0.88,
  "Margin": maxBuy - listingPrice,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [purity, item, weight] | CALC: [palladium]g x $[rate] = $[melt] | MARGIN: $[maxBuy] - $[price] = $[margin] | DECISION: [why]"
}}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate and fix palladium response"""
        # Ensure estimated weight can't have BUY recommendation
        if response.get("weightSource") == "estimate" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Estimated weight cannot be BUY"

        # Ensure negative margin = PASS
        try:
            margin = float(str(response.get("Margin", "0")).replace("+", "").replace("$", ""))
            if margin < 0 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative margin = PASS"
        except:
            pass

        # Palladium is rare - if no clear marking, increase fake risk
        karat = response.get("karat", "").upper()
        if not karat or karat not in ["PD950", "PD500"]:
            if response.get("fakerisk") != "High":
                response["fakerisk"] = "High"
                response["reasoning"] = response.get("reasoning", "") + " | WARNING: No clear Pd mark - high fake risk"

        return response
