"""
Gold Agent - Handles gold jewelry/scrap analysis
"""

from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class GoldAgent(BaseAgent):
    """Agent for gold jewelry and scrap analysis"""

    category_name = "gold"

    # Gold needs high-detail image analysis for scale reading
    default_tier1_model = Tier1Model.GPT4O_MINI
    default_tier2_model = Tier2Model.GPT4O

    def get_karat_rates(self) -> dict:
        """Calculate current karat rates from spot price"""
        gold_oz = SPOT_PRICES.get("gold_oz", 2650)
        gold_gram = gold_oz / 31.1035
        return {
            "10K": gold_gram * 0.417,
            "14K": gold_gram * 0.583,
            "18K": gold_gram * 0.75,
            "22K": gold_gram * 0.917,
            "24K": gold_gram,
        }

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for gold before AI analysis.
        Returns (reason, "PASS"/"RESEARCH") or (None, None) to continue.
        """
        title = data.get("Title", "").lower()
        description = data.get("Description", "").lower()
        combined = f"{title} {description}"

        # ============================================================
        # TIER 0: INSTANT PASS - No value / plated
        # ============================================================
        plated_keywords = ["gold filled", "gf ", " gf", "gold plated", "gp ", " gp",
                          "hge", "rgp", "vermeil", "gold tone", "gold over",
                          "rolled gold", "gold flash", "electroplate", "bonded gold"]
        for kw in plated_keywords:
            if kw in title:
                return (f"PLATED - '{kw}' detected in title", "PASS")

        # Gold filled watch case brands
        filled_brands = ["dueber", "wadsworth", "keystone", "star watch case", "champion",
                        "fahys", "crescent", "boss", "royal", "illinois"]
        for brand in filled_brands:
            if brand in title and "watch" in title:
                return (f"FILLED WATCH CASE - '{brand}' brand detected", "PASS")

        # Ladies/Women's watches - almost always gold-filled or plated, never solid gold
        # Even marked "10K" or "14K" is usually gold-filled for vintage ladies watches
        ladies_watch_keywords = ["ladies watch", "women watch", "women's watch", "womens watch",
                                "lady's watch", "ladys watch", "vintage watch women",
                                "hamilton women", "bulova women", "elgin women", "gruen women",
                                "waltham women", "longines women", "wittnauer women"]
        for kw in ladies_watch_keywords:
            if kw in title:
                return (f"LADIES WATCH - '{kw}' detected, almost always gold-filled not solid", "RESEARCH")

        # Single earring = no value
        if "single earring" in title or "one earring" in title:
            return ("SINGLE EARRING - no resale value", "PASS")

        # Fashion jewelry keywords
        fashion_keywords = ["costume", "fashion jewelry", "rhinestone", "cubic zirconia", "cz ",
                           "simulated", "faux gold", "imitation", "gold color"]
        for kw in fashion_keywords:
            if kw in title:
                return (f"FASHION/COSTUME - '{kw}' detected", "PASS")

        # Broken/damaged items with no gold content
        if any(kw in title for kw in ["empty mount", "setting only", "mountings only"]):
            return ("EMPTY SETTING - likely minimal gold", "PASS")

        # ============================================================
        # TIER 0: RESEARCH - Needs manual verification
        # ============================================================
        # UNTESTED gold = unknown karat, could be plated
        untested_phrases = [
            "not tested", "untested", "has not been tested", "haven't tested",
            "not verified", "unverified", "karat unknown", "gold content unknown",
            "may be gold", "possibly gold", "might be gold", "unmarked gold",
            "no markings", "unstamped"
        ]
        for phrase in untested_phrases:
            if phrase in combined:
                return (f"UNTESTED - '{phrase}' detected, unknown karat/purity", "RESEARCH")

        # High-value items need manual verification
        if price > 2000:
            return (f"HIGH VALUE at ${price:.0f} - manual verification required", "RESEARCH")

        # Diamond-heavy listings - value in stones, not gold
        diamond_keywords = ["diamond ring", "diamond bracelet", "diamond necklace",
                          "diamond earrings", "diamond pendant", "engagement ring"]
        for kw in diamond_keywords:
            if kw in title:
                # Only research if price suggests diamond value
                if price > 500:
                    return (f"DIAMOND JEWELRY at ${price:.0f} - value may be in stones", "RESEARCH")

        # CORAL/JADE items - coral is HEAVY, often 50-70% of total weight
        # This drastically reduces gold content - needs careful analysis
        coral_keywords = ["coral", "angel skin", "carved jade", "jadeite"]
        for kw in coral_keywords:
            if kw in title:
                # Coral/jade items need careful weight deduction - flag for research
                return (f"CORAL/JADE DETECTED - stone weight can be 50-70% of total, needs careful deduction", "RESEARCH")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the gold analysis prompt"""
        gold_oz = SPOT_PRICES.get("gold_oz", 2650)
        gold_gram = gold_oz / 31.1035
        source = SPOT_PRICES.get("source", "default")
        last_updated = SPOT_PRICES.get("last_updated", "unknown")

        k10 = gold_gram * 0.417
        k14 = gold_gram * 0.583
        k18 = gold_gram * 0.75
        k22 = gold_gram * 0.917
        k24 = gold_gram

        return f"""
=== GOLD CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of gold items. We buy gold to MELT IT.

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
- If scale shows "ct" or "CT": This is GEMSTONE weight, NOT gold!
- WATCH FOR DECIMALS: "1.5g" vs "15g" is 10x difference!

NEVER estimate weight if scale photo exists - this causes OVERVALUATION!

=== STEP 2: STONE/PEARL DEDUCTIONS ===
DIAMONDS, GEMSTONES, PEARLS, CORAL = $0 VALUE - just deduct their weight!
- Small accent stone: 0.1-0.5g
- Medium stone (5-8mm): 0.5-1.5g
- Large pearl (8-10mm): 1.7-3g
- Pearl strands: Gold is ONLY the clasp (2-4g max)

CORAL (CRITICAL - HEAVY!)
- Small coral cabochon (<10mm): 1-3g
- Medium carved coral (10-20mm): 5-10g
- LARGE CARVED CORAL (20-50mm): 10-20g (MOST OF THE WEIGHT!)
- "Angel skin coral" brooch/pendant: Often 50-70% is coral by weight
- Example: "20g coral brooch 2x1 inch" = deduct 12-15g for coral, only 5-8g gold

JADE/JADEITE (also heavy)
- Small cabochon: 1-2g
- Medium carved piece: 3-8g
- Large carved piece: 10-20g

=== CURRENT PRICING ({source} - {last_updated}) ===
Gold spot: ${gold_oz:,.0f}/oz = ${gold_gram:.2f}/gram pure

KARAT RATES (what refiners pay):
- 10K: ${k10:.2f}/gram
- 14K: ${k14:.2f}/gram
- 18K: ${k18:.2f}/gram
- 22K: ${k22:.2f}/gram
- 24K: ${k24:.2f}/gram

=== PRICING MODEL ===
1. goldWeight = totalWeight - stoneWeight (deduct ALL stones/pearls)
2. meltValue = goldWeight x karatRate
3. maxBuy = meltValue x 0.90 (our ceiling - NEVER pay more)
4. sellPrice = meltValue x 0.96 (what refiner pays us)
5. Profit = maxBuy - listingPrice (buffer for price changes)
6. If listingPrice > maxBuy = ALWAYS PASS

EXAMPLE - 14K pendant, 8.2g, listed at $500:
- Melt: 8.2g x ${k14:.2f} = ${8.2 * k14:.0f}
- maxBuy: ${8.2 * k14 * 0.90:.0f} (our ceiling)
- sellPrice: ${8.2 * k14 * 0.96:.0f} (what we get)
- Profit: ${8.2 * k14 * 0.96:.0f} - $500 = ${8.2 * k14 * 0.96 - 500:.0f}
- ${500} < maxBuy ${8.2 * k14 * 0.90:.0f} = BUY

=== INSTANT PASS CONDITIONS ===
- Single earring (worthless)
- Diamond-focused jewelry (value in stones, not gold)
- Price > $100/gram of gold weight
- Plated/Filled: GF, GP, HGE, RGP, Vermeil
- RESIN CORE / HOLLOW CORE: Almost no gold
- Pearl strands: Gold is only clasp (2-4g)

=== UNTESTED = NEVER BUY ===
If description says ANY of these, ALWAYS return RESEARCH (not BUY):
- "not tested", "untested", "karat unknown"
- "has not been tested", "gold content unknown"
- "may be gold", "possibly gold", "might be gold"
These could be plated! Unknown karat = unknown value = RESEARCH required.

=== HOLLOW GOLD ===
- "HOLLOW" = 20% of normal weight estimate
- "SEMI-HOLLOW" = 55% of normal weight
- "SOLID" = normal weight (confidence boost)

=== WATCH DEDUCTIONS ===
- Movement inside (quartz): Deduct 3-5g
- Movement inside (mechanical): Deduct 5-8g
- Crystal/glass: Deduct 0.5-1.5g
- Empty case (no movement): Only deduct crystal

=== WEIGHT ESTIMATION ===
| Item Type | Weight Range |
| Thin chain 18" | 1-3g |
| Medium chain 18" | 3-6g |
| Heavy chain 18" | 6-15g+ |
| Thin band ring | 1-2g |
| Standard band | 2-4g |
| Class ring (F) | 5-8g |
| Class ring (M) | 8-15g |
| Stud earrings (pair) | 0.5-2g |
| Drop earrings with stones | 1-2g GOLD (stones dominate weight) |

=== ESTIMATED WEIGHT RULE ===
If weightSource = "estimate", Recommendation CANNOT be "BUY"!
- Estimated weight = we're guessing = RESEARCH or PASS only
- BUY requires scale photo or seller-stated weight

=== CONFIDENCE SCORING ===
- Scale photo: Start at 75
- Seller stated weight: Start at 70
- ESTIMATED weight: Start at 45 (MAXIMUM 50!)

=== JSON OUTPUT (ALL REQUIRED) ===
{{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS" (PASS if listingPrice > maxBuy),
  "verified": "Yes"/"No"/"Unknown",
  "karat": "10K"/"14K"/"18K"/"22K"/"24K" or "10K/14K/18K" for mixed,
  "itemtype": "Ring"/"Chain"/"Bracelet"/"Earrings"/"Pendant"/"Watch"/"Scrap",
  "weightSource": "scale"/"stated"/"estimate",
  "weight": total weight as string,
  "stoneDeduction": "2g pearls" or "0",
  "watchDeduction": "3g movement" or "0",
  "goldweight": weight after deductions,
  "meltvalue": calculated melt value,
  "maxBuy": meltvalue x 0.90,
  "sellPrice": meltvalue x 0.96,
  "Profit": maxBuy - listingPrice,
  "confidence": INTEGER 0-100,
  "confidenceBreakdown": "Base 70 + scale 10 = 80",
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [karat, item, weight] | CALC: [gold]g x $[rate] = $[melt] | PROFIT: $[sell] - $[price] = $[profit] | DECISION: [why]"
}}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate and fix gold response"""
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

        # SANITY CHECK: If high-priced item gets PASS with estimated weight,
        # flag as RESEARCH since the weight estimate might be wrong
        # This catches cases where scale was hard to read and AI defaulted to low estimate
        try:
            if response.get("Recommendation") == "PASS" and response.get("weightSource") == "estimate":
                # Get the listing price from context (stored during analysis)
                melt_value = float(str(response.get("meltvalue", "0")).replace("$", "").replace(",", ""))
                # If calculated melt is very low compared to what we'd expect from the item type,
                # and this isn't an obvious plated/fashion item, flag for review
                if melt_value > 0 and melt_value < 500:
                    # Item type check - chains and bracelets can be heavy
                    item_type = response.get("itemtype", "").lower()
                    heavy_types = ["chain", "bracelet", "necklace", "scrap", "lot"]
                    if any(ht in item_type for ht in heavy_types):
                        response["Recommendation"] = "RESEARCH"
                        response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High-value item type with estimated weight - verify weight manually"
        except:
            pass

        return response
