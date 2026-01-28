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

        # Gold filled watch case brands (NOT Keystone - that's a good brand)
        filled_brands = ["dueber", "wadsworth", "star watch case", "champion",
                        "fahys", "crescent", "boss", "royal", "illinois"]
        for brand in filled_brands:
            if brand in title and "watch" in title:
                return (f"FILLED WATCH CASE - '{brand}' brand detected", "PASS")

        # 10K watches are ALWAYS gold filled, never solid gold
        # Only 14K and 18K watches can potentially be solid gold cases
        if "watch" in title and ("10k" in title or "10kt" in title):
            return ("10K WATCH = GOLD FILLED - 10K watches are always gold filled, not solid", "PASS")

        # GOLD WATCHES: Historical data shows -24% ROI on gold watches
        # They are often overvalued, gold-filled mislabeled as solid, or have movement issues
        # Force RESEARCH for ALL gold watches to verify manually
        if "watch" in title and any(k in title for k in ["14k", "18k", "gold"]):
            return ("GOLD WATCH - Historical data shows negative ROI on gold watches. Manual verification required.", "RESEARCH")

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

        # Fashion jewelry keywords - only PASS if NOT a costume search
        # Costume searches may have hidden precious metals in lots
        alias = data.get("Alias", "").lower()
        is_costume_search = "costume" in alias or "fashion" in alias

        if not is_costume_search:
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

        # ============================================================
        # DIAMOND ITEMS - Historical data shows diamonds are FREE UPSIDE
        # If gold weight is stated and price < 90% of gold melt, BUY IT
        # Diamonds add value when selling but sellers often price at melt
        # ============================================================
        import re
        has_diamond = 'diamond' in title or re.search(r'\b\d*\.?\d+\s*(?:cttw|ctw|ct\s*tw)\b', title, re.IGNORECASE)

        if has_diamond:
            # Check if gold weight is stated in title
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?)\b', title, re.IGNORECASE)
            karat_match = re.search(r'\b(10|14|18|22|24)\s*k', title, re.IGNORECASE)

            if weight_match and karat_match:
                gold_weight = float(weight_match.group(1))
                karat = int(karat_match.group(1))
                gold_gram = SPOT_PRICES.get("gold_oz", 2650) / 31.1035
                karat_mult = karat / 24
                melt_value = gold_weight * gold_gram * karat_mult
                max_buy = melt_value * 0.90

                if price <= max_buy:
                    # HISTORICAL DATA: Diamond items bought at <90% melt = 40-540% ROI
                    # Diamonds are $0 for scrap but add massive upside when selling
                    return (f"DIAMOND + GOLD DEAL: {gold_weight}g {karat}K = ${melt_value:.0f} melt. Price ${price:.0f} < maxBuy ${max_buy:.0f}. Diamonds are FREE upside!", "BUY")
                elif price <= melt_value * 1.1:
                    # Slightly over but still potentially good
                    return (f"DIAMOND JEWELRY: {gold_weight}g {karat}K = ${melt_value:.0f} melt. Price ${price:.0f} is near melt. Could negotiate.", "RESEARCH")

            # No stated weight - need AI to estimate
            if price > 500:
                return (f"DIAMOND JEWELRY at ${price:.0f} - need AI to estimate gold weight", "RESEARCH")

        # Wedding bands often have diamonds even without "diamond" in title
        wedding_keywords = ["wedding band", "wedding ring", "bridal ring", "bridal band",
                          "anniversary band", "eternity band", "princess cut", "round cut"]
        for kw in wedding_keywords:
            if kw in title:
                if price > 500:
                    return (f"WEDDING/BRIDAL JEWELRY at ${price:.0f} - likely has diamonds, value in stones", "RESEARCH")

        # CORAL/JADE items - coral is HEAVY, often 50-70% of total weight
        # This drastically reduces gold content - needs careful analysis
        coral_keywords = ["coral", "angel skin", "carved jade", "jadeite"]
        for kw in coral_keywords:
            if kw in title:
                # Coral/jade items need careful weight deduction - flag for research
                return (f"CORAL/JADE DETECTED - stone weight can be 50-70% of total, needs careful deduction", "RESEARCH")

        # POCKET WATCH SCRAP RULE
        # Pocket watches have approximately 30% of their weight in gold (case only)
        # The remaining 70% is movement, crystal, dial, crown, etc.
        # If we can find weight in description, calculate if overpriced based on 30% gold
        if "pocket watch" in combined or "pocket-watch" in combined:
            import re
            # Extract weight from description (grams or dwt)
            weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?|dwt)\b', combined, re.IGNORECASE)
            if weight_match:
                weight_str = weight_match.group(0).lower()
                weight_val = float(weight_match.group(1))
                # Convert dwt to grams if needed
                if 'dwt' in weight_str:
                    weight_val = weight_val * 1.555

                # Calculate gold value assuming 30% of weight is gold
                gold_weight = weight_val * 0.30

                # Determine karat from title
                karat_rate = 0
                gold_gram = SPOT_PRICES.get("gold_oz", 2650) / 31.1035
                if "18k" in title or "18 k" in title or "18kt" in title:
                    karat_rate = gold_gram * 0.75
                elif "14k" in title or "14 k" in title or "14kt" in title:
                    karat_rate = gold_gram * 0.583
                elif "10k" in title or "10 k" in title or "10kt" in title:
                    karat_rate = gold_gram * 0.417

                if karat_rate > 0:
                    melt_value = gold_weight * karat_rate
                    max_buy = melt_value * 0.90

                    # If price is more than max_buy, it's overpriced for scrap
                    if price > max_buy:
                        return (f"POCKET WATCH - {weight_val:.1f}g total but only ~30% ({gold_weight:.1f}g) is gold. Melt ${melt_value:.0f}, maxBuy ${max_buy:.0f}, listing ${price:.0f} = OVERPRICED for scrap", "RESEARCH")

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

AGATE/CARNELIAN/JASPER/CHALCEDONY (dense cabochon stones ~2.6g/cm³)
- Small cabochon (<10mm): 1-2g
- Medium cabochon (10-15mm): 2-4g
- LARGE cabochon (15-25mm): 4-8g
- VERY LARGE (25mm+ / 1"+): 8-15g

CAMEO (CRITICAL - MOST WEIGHT IS SHELL!)
- Cameos are carved shell/stone with a thin gold FRAME only
- The shell/stone is 80-90% of total weight!
- Small cameo pendant: Frame ~2-3g gold
- Medium cameo brooch: Frame ~3-4g gold
- Large cameo brooch: Frame ~4-6g gold
- RULE: If cameo, estimate gold = 10-20% of total weight (frame only)
- Example: "18g cameo brooch" = ~3g gold frame + 15g shell

BROOCH WITH LARGE STONE (CRITICAL!)
- Brooch frame is THIN METAL around the stone!
- A 1.5" brooch with large stone: Frame is only 2-4g gold
- Example: "8.87g Edwardian agate brooch" = ~5-6g agate + 2-3g gold frame
- RULE: If brooch features a large stone, deduct 50-70% for stone weight!

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

=== POCKET WATCH RULE (CRITICAL!) ===
POCKET WATCHES have only ~30% of their weight in gold (the case).
The other 70% is movement, dial, crystal, crown, hands, etc.
- If description states total weight, multiply by 0.30 to get gold weight
- Example: 57.2g pocket watch = ~17.2g of gold (30%)
- Many sellers list total weight thinking it's all gold - IT'S NOT!
- If price > (goldWeight * karatRate * 0.80), item is OVERPRICED for scrap
- ALWAYS flag overpriced pocket watches as RESEARCH, not BUY

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

=== LUXURY DESIGNER JEWELRY (VALUE = BRAND, NOT MELT!) ===
These brands sell for DESIGN/BRAND VALUE, not gold weight! Compare to RESALE prices, not melt.

BRAND RESALE VALUES (typical used/pre-owned):
| Brand | Collection | Retail | Resale Range | Buy Target |
|-------|------------|--------|--------------|------------|
| Van Cleef & Arpels | Alhambra Single Motif Earrings | $4,500 | $2,000-3,000 | <$1,500 |
| Van Cleef & Arpels | Alhambra 10 Motif Necklace | $15,000 | $8,000-11,000 | <$6,000 |
| Van Cleef & Arpels | Alhambra 5 Motif Bracelet | $6,500 | $3,500-5,000 | <$2,800 |
| Van Cleef & Arpels | Alhambra Pendant | $3,000 | $1,500-2,200 | <$1,200 |
| Cartier | Love Bracelet (no diamonds) | $7,000 | $4,000-5,500 | <$3,200 |
| Cartier | Love Bracelet (4 diamonds) | $11,000 | $6,500-8,500 | <$5,000 |
| Cartier | Love Ring | $1,800 | $1,000-1,400 | <$800 |
| Cartier | Juste un Clou Bracelet | $7,500 | $4,500-6,000 | <$3,500 |
| Cartier | Trinity Ring | $1,500 | $800-1,100 | <$650 |
| Cartier | Panthere Ring | $3,500 | $2,000-2,800 | <$1,600 |
| Bulgari | Serpenti Bracelet | $15,000 | $8,000-11,000 | <$6,500 |
| Bulgari | B.Zero1 Ring | $1,500 | $800-1,100 | <$650 |
| David Yurman | Cable Bracelet | $2,500 | $1,200-1,800 | <$900 |
| Roberto Coin | Primavera Bracelet | $3,000 | $1,500-2,200 | <$1,200 |

LUXURY BRAND RULE:
1. If title contains luxury brand name (Van Cleef, Cartier, Bulgari, etc.):
   - DO NOT calculate melt value - it's meaningless
   - Estimate RESALE VALUE based on brand/collection (see table above)
   - maxBuy = resaleValue x 0.70 (need 30% margin for fees/risk)
   - If listing > maxBuy = PASS (overpriced)
   - If listing < maxBuy = BUY opportunity

2. Example: Van Cleef Alhambra Earrings listed at $5000
   - Resale value: $2,000-3,000 (avg ~$2,500)
   - maxBuy: $2,500 x 0.70 = $1,750
   - $5000 > $1,750 = PASS (OVERPRICED by $3,250!)

3. Example: Cartier Love Bracelet listed at $2,800
   - Resale value: $4,000-5,500 (avg ~$4,750)
   - maxBuy: $4,750 x 0.70 = $3,325
   - $2,800 < $3,325 = BUY (potential $525 profit)

CRITICAL: Luxury brand at/above retail = ALWAYS PASS!
- If listing price >= retail price, it's not a deal
- Pre-owned should be 40-70% of retail

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

    def validate_response(self, response: dict, data: dict = None) -> dict:
        """Validate and fix gold response"""

        def parse_price(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace("$", "").replace(",", "").replace("+", "").strip()
            try:
                return float(s)
            except:
                return 0

        # Get listing price from data
        listing_price = 0
        title = ""
        if data:
            listing_price = parse_price(
                data.get("TotalPrice") or data.get("Price") or
                data.get("CurrentPrice") or data.get("_listing_price") or 0
            )
            title = str(data.get("Title", "")).lower()

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

        # === PRICE RANGE PERFORMANCE ADJUSTMENTS ===
        # Historical data shows strong correlation between price and success rate:
        # - $0-50: 96% win rate, 508% ROI (BOOST)
        # - $50-100: 85% win rate, 272% ROI (BOOST)
        # - $100-200: 83% win rate, 141% ROI (NEUTRAL)
        # - $200-500: 59% win rate, 73% ROI (CAUTION)
        # - $500-1000: 75% win rate, 35% ROI (CAUTION)
        # - $1000+: 67% win rate, 8% ROI (AVOID AUTO-BUY)
        current_confidence = response.get("confidence", 50)
        if isinstance(current_confidence, str):
            current_confidence = int(current_confidence.replace('%', '') or 50)

        if listing_price <= 50:
            response["confidence"] = min(current_confidence + 15, 95)
            response["reasoning"] = response.get("reasoning", "") + f" | BOOST: Under $50 items have 96% win rate (+15 confidence)"
        elif listing_price <= 100:
            response["confidence"] = min(current_confidence + 10, 95)
            response["reasoning"] = response.get("reasoning", "") + f" | BOOST: $50-100 items have 85% win rate (+10 confidence)"
        elif listing_price > 500:
            response["confidence"] = max(current_confidence - 10, 30)
            response["reasoning"] = response.get("reasoning", "") + f" | CAUTION: Over $500 items have lower win rates (-10 confidence)"

        # === KARAT PERFORMANCE ADJUSTMENTS ===
        # Historical data: 14K has best ROI at 103% (66 items)
        # 18K: 48% ROI, 10K: 33% ROI
        karat = response.get("karat", "").upper()
        if "14K" in karat or "14K" in title.upper():
            current_conf = response.get("confidence", 50)
            if isinstance(current_conf, str):
                current_conf = int(current_conf.replace('%', '') or 50)
            response["confidence"] = min(current_conf + 5, 95)
            response["reasoning"] = response.get("reasoning", "") + " | BOOST: 14K gold has best historical ROI (103%) (+5 confidence)"

        # HIGH-VALUE GOLD: BUY over $1000 = RESEARCH (too risky for auto-buy)
        if listing_price > 1000 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: High-value gold (${listing_price:.0f}) = RESEARCH (verify before buying)"
            print(f"[GOLD] HIGH VALUE OVERRIDE: ${listing_price:.0f} BUY -> RESEARCH")

        # LUXURY BRANDS: Validate pricing is based on resale, not melt
        # AI should now value these by brand - verify it makes sense
        LUXURY_BRAND_MIN_RESALE = {
            # brand_keyword: (min_resale, typical_resale) - used to catch obvious overpricing
            'alhambra': (1500, 3000),  # Van Cleef Alhambra pieces
            'van cleef': (1500, 5000),
            'cartier': (800, 4000),
            'love bracelet': (3500, 5000),
            'juste un clou': (3000, 5000),
            'bulgari': (800, 5000),
            'bvlgari': (800, 5000),
            'serpenti': (5000, 10000),
            'david yurman': (500, 1500),
            'roberto coin': (800, 2000),
            'harry winston': (3000, 15000),
            'chopard': (2000, 8000),
            'graff': (5000, 20000),
            'piaget': (2000, 8000),
        }

        detected_brand = None
        brand_resale_range = None
        if title:
            for brand, resale_range in LUXURY_BRAND_MIN_RESALE.items():
                if brand in title:
                    detected_brand = brand
                    brand_resale_range = resale_range
                    break

        if detected_brand and brand_resale_range:
            min_resale, typical_resale = brand_resale_range
            max_buy_brand = typical_resale * 0.70  # 70% of typical resale

            # If listing is way above typical resale, it's overpriced - PASS
            if listing_price > typical_resale and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: '{detected_brand}' listing ${listing_price:.0f} > typical resale ${typical_resale:.0f} = OVERPRICED"
                print(f"[GOLD] LUXURY OVERPRICED: '{detected_brand}' ${listing_price:.0f} > resale ${typical_resale:.0f} -> PASS")

            # If listing is above our max buy target but AI said BUY, force PASS
            elif listing_price > max_buy_brand and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: '{detected_brand}' listing ${listing_price:.0f} > maxBuy ${max_buy_brand:.0f} (70% of ${typical_resale:.0f}) = NO MARGIN"
                print(f"[GOLD] LUXURY NO MARGIN: '{detected_brand}' ${listing_price:.0f} > maxBuy ${max_buy_brand:.0f} -> PASS")

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
