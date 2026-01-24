"""
Platinum Agent - Handles platinum jewelry/scrap analysis
"""

from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class PlatinumAgent(BaseAgent):
    """Agent for platinum jewelry and scrap analysis"""

    category_name = "platinum"

    # Platinum needs high-detail image analysis for scale reading
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    def get_purity_rates(self) -> dict:
        """Calculate current platinum purity rates from spot price"""
        platinum_oz = SPOT_PRICES.get("platinum_oz", 950)
        platinum_gram = platinum_oz / 31.1035
        return {
            "PT950": platinum_gram * 0.950,
            "PT900": platinum_gram * 0.900,
            "PT850": platinum_gram * 0.850,
        }

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for platinum before AI analysis.
        Returns (reason, "PASS"/"RESEARCH") or (None, None) to continue.
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", "").lower()
        combined = f"{title} {description}"

        # ============================================================
        # TIER 0: INSTANT PASS - No value / plated
        # ============================================================
        plated_keywords = ["platinum plated", "platinum tone", "platinum color",
                          "platinum finish", "rhodium plated", "white gold plated"]
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
        # UNTESTED platinum = unknown purity, could be plated white gold
        untested_phrases = [
            "not tested", "untested", "has not been tested", "haven't tested",
            "not verified", "unverified", "purity unknown",
            "may be platinum", "possibly platinum", "might be platinum", "unmarked",
            "no markings", "unstamped"
        ]
        for phrase in untested_phrases:
            if phrase in combined:
                return (f"UNTESTED - '{phrase}' detected, unknown purity", "RESEARCH")

        # High-value items need manual verification
        if price > 3000:
            return (f"HIGH VALUE at ${price:.0f} - manual verification required", "RESEARCH")

        # Diamond-heavy listings - value in stones, not platinum
        diamond_keywords = ["diamond ring", "diamond bracelet", "diamond necklace",
                          "diamond earrings", "diamond pendant", "engagement ring"]
        for kw in diamond_keywords:
            if kw in title:
                if price > 1000:
                    return (f"DIAMOND JEWELRY at ${price:.0f} - value may be in stones", "RESEARCH")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the platinum analysis prompt"""
        platinum_oz = SPOT_PRICES.get("platinum_oz", 950)
        platinum_gram = platinum_oz / 31.1035
        source = SPOT_PRICES.get("source", "default")
        last_updated = SPOT_PRICES.get("last_updated", "unknown")

        pt950 = platinum_gram * 0.950
        pt900 = platinum_gram * 0.900
        pt850 = platinum_gram * 0.850

        return f"""
=== PLATINUM CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of platinum items. We buy platinum to MELT IT.

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

=== PLATINUM PURITY MARKINGS ===
- PT950 / 950 / PLAT = 95% platinum (most common)
- PT900 / 900 = 90% platinum
- PT850 / 850 = 85% platinum
- IRIDPLAT = Iridium-Platinum alloy (treat as PT900)
- "Platinum" with no mark = assume PT950

=== CURRENT PRICING ({source} - {last_updated}) ===
Platinum spot: ${platinum_oz:,.0f}/oz = ${platinum_gram:.2f}/gram pure

PURITY RATES (what refiners pay):
- PT950: ${pt950:.2f}/gram
- PT900: ${pt900:.2f}/gram
- PT850: ${pt850:.2f}/gram

=== PRICING MODEL ===
1. platinumWeight = totalWeight - stoneWeight (deduct ALL stones)
2. meltValue = platinumWeight x purityRate
3. maxBuy = meltValue x 0.85 (our ceiling - NEVER pay more)
4. sellPrice = meltValue x 0.92 (what refiner pays us)
5. Margin = maxBuy - listingPrice (buffer for price changes)
6. If listingPrice > maxBuy = ALWAYS PASS

EXAMPLE - PT950 ring, 8.2g, listed at $400:
- Melt: 8.2g x ${pt950:.2f} = ${8.2 * pt950:.0f}
- maxBuy: ${8.2 * pt950 * 0.85:.0f} (our ceiling)
- sellPrice: ${8.2 * pt950 * 0.92:.0f} (what we get)
- Margin: ${8.2 * pt950 * 0.85:.0f} - $400 = ${8.2 * pt950 * 0.85 - 400:.0f}
- $400 < maxBuy ${8.2 * pt950 * 0.85:.0f} = BUY

=== INSTANT PASS CONDITIONS ===
- Single earring (worthless)
- Diamond-focused jewelry (value in stones, not metal)
- Price > melt value
- Plated/Tone keywords
- "White gold" without platinum markings

=== UNTESTED = NEVER BUY ===
If description says ANY of these, ALWAYS return RESEARCH (not BUY):
- "not tested", "untested", "purity unknown"
- "may be platinum", "possibly platinum"
These could be white gold! Unknown purity = unknown value = RESEARCH required.

=== WEIGHT ESTIMATION ===
| Item Type | Weight Range |
| Thin band ring | 2-4g |
| Standard band | 4-8g |
| Heavy band | 8-12g |
| Stud earrings (pair) | 1-3g |
| Drop earrings (pair) | 2-5g |
| Pendant small | 2-5g |
| Pendant large | 5-10g |
| Bracelet | 15-40g |

=== ESTIMATED WEIGHT RULE ===
If weightSource = "estimate", Recommendation CANNOT be "BUY"!
- Estimated weight = we're guessing = RESEARCH or PASS only
- BUY requires scale photo or seller-stated weight

=== CONFIDENCE SCORING ===
- Scale photo: Start at 75
- Seller stated weight: Start at 70
- ESTIMATED weight: Start at 45 (MAXIMUM 50!)
- Clear purity mark (PT950): +10
- No purity mark: -10

=== JSON OUTPUT (ALL REQUIRED) ===
{{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH" (PASS if listingPrice > maxBuy),
  "verified": "Yes"/"No"/"Unknown",
  "karat": "PT950"/"PT900"/"PT850" (purity marking found),
  "itemtype": "Ring"/"Earrings"/"Pendant"/"Bracelet"/"Chain"/"Scrap",
  "weightSource": "scale"/"stated"/"estimate",
  "weight": total weight as string (e.g. "8.2g"),
  "stoneDeduction": "0.5g diamonds" or "0",
  "platinumweight": weight after deductions,
  "pricepergram": listing price / platinumweight,
  "meltvalue": calculated melt value,
  "maxBuy": meltvalue x 0.85,
  "sellPrice": meltvalue x 0.92,
  "Margin": maxBuy - listingPrice,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [purity, item, weight] | CALC: [platinum]g x $[rate] = $[melt] | MARGIN: $[maxBuy] - $[price] = $[margin] | DECISION: [why]"
}}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate and fix platinum response"""
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

        return response
