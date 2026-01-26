"""
Watch Agent - Handles watch analysis (separate from gold scrap)
Watches have collectible value beyond just metal content.
"""

from .base import BaseAgent, Tier1Model, Tier2Model
from config import SPOT_PRICES


class WatchAgent(BaseAgent):
    """Agent for watch analysis - values watches as collectibles, not scrap"""

    category_name = "watch"

    # Watches are complex - use smarter model for Tier 1
    # The value depends on brand, model, condition, papers, service history
    default_tier1_model = Tier1Model.GPT4O_MINI  # Could upgrade to GPT4O for better accuracy
    default_tier2_model = Tier2Model.GPT4O

    PREMIUM_BRANDS = [
        "rolex", "omega", "patek philippe", "patek", "audemars piguet", "ap ",
        "vacheron constantin", "jaeger-lecoultre", "jaeger lecoultre", "lecoultre", "cartier",
        "iwc", "breitling", "panerai", "tudor", "grand seiko",
        "ulysse nardin", "a. lange", "lange & sohne", "lange sohne",
        "piaget", "chopard", "blancpain", "glashutte", "zenith"
    ]

    # Floor prices for premium watch brands/models - anything below = potential BUY
    # These are minimum values even in poor/non-working condition
    PREMIUM_FLOOR_PRICES = {
        # Omega models
        "constellation": 500,
        "seamaster": 400,
        "speedmaster": 1500,
        "de ville": 300,
        "omega": 300,  # Generic Omega floor
        # Rolex models
        "submariner": 5000,
        "datejust": 3000,
        "daytona": 15000,
        "gmt": 5000,
        "explorer": 4000,
        "rolex": 2000,  # Generic Rolex floor
        # Tudor
        "tudor": 800,
        # Cartier
        "tank": 1000,
        "santos": 1500,
        "cartier": 800,
        # Other premium
        "breitling": 800,
        "iwc": 1000,
        "panerai": 2000,
        "patek": 5000,
    }

    # Premium dial/feature keywords that add value
    PREMIUM_FEATURES = [
        "pie pan", "piepan",  # Omega Constellation dial style
        "tropical", "gilt", "patina",  # Desirable aging
        "salmon", "sector dial",  # Rare dials
        "military", "mil-spec",  # Military issue
        "chronograph", "chrono",  # Complications
        "moon phase", "moonphase",  # Complications
    ]

    # Vintage chronograph floor prices - these are collectible regardless of brand
    # Even "entry" brands like Benrus have valuable vintage chronographs
    # Floors are MINIMUM values (for parts/non-working) - working worth 50-100% more
    VINTAGE_CHRONOGRAPH_FLOORS = {
        # Specific collectible chronographs
        "sky chief": 1200,      # Benrus Sky Chief - $1200-1500 parts, $2000+ working
        "ultra deep": 600,      # Benrus Ultra Deep
        "type xx": 2000,        # Breguet/military chronographs
        "type 20": 1500,        # French military chronos
        "dato compax": 3000,    # Universal Geneve
        "compax": 1500,         # Universal Geneve chronos
        "carrera": 1500,        # Heuer Carrera
        "autavia": 2000,        # Heuer Autavia
        "monaco": 3000,         # Heuer Monaco
        "el primero": 2000,     # Zenith
        "navitimer": 1500,      # Breitling
        "valjoux": 400,         # Any Valjoux movement chrono
        "landeron": 300,        # Landeron movement chrono
        "venus": 300,           # Venus movement chrono
        # Generic vintage chrono floor (if none of the above match)
        "chronograph": 300,
        "chrono": 300,
    }

    MID_BRANDS = [
        "longines", "tag heuer", "heuer", "oris", "hamilton",
        "tissot", "mido", "rado", "movado", "bulova", "wittnauer",
        "zodiac", "glycine", "eterna", "girard perregaux", "universal geneve"
    ]

    ENTRY_BRANDS = [
        "seiko", "citizen", "orient", "timex", "casio", "fossil",
        "elgin", "waltham", "gruen", "benrus", "helbros", "croton"
    ]

    FILLED_BRANDS = [
        "dueber", "wadsworth", "keystone", "star watch case", "champion",
        "illinois", "fahys", "crescent", "boss", "royal"
    ]

    def quick_pass(self, data: dict, price: float) -> tuple:
        title = data.get("Title", "").lower()

        # === SMART WATCHES - Not collectible, depreciate fast ===
        smart_watch_keywords = ["apple watch", "fitbit", "garmin", "samsung galaxy watch",
                               "galaxy watch", "amazfit", "huawei watch", "wear os",
                               "smartwatch", "smart watch", "fitness tracker"]
        for kw in smart_watch_keywords:
            if kw in title:
                return (f"SMART WATCH - '{kw}' (not collectible, fast depreciation)", "PASS")

        # === WATCH BANDS/STRAPS ONLY ===
        band_keywords = ["band only", "strap only", "bracelet only", "watch band",
                        "replacement band", "replacement strap", "leather strap",
                        "nato strap", "silicone band", "metal band", "jubilee band",
                        "oyster bracelet", "no watch"]
        for kw in band_keywords:
            if kw in title:
                return (f"BAND/STRAP ONLY - '{kw}' (no watch)", "PASS")

        # === WATCH PARTS ONLY ===
        parts_keywords = ["watch crown", "watch crystal", "movement only", "dial only",
                        "watch hands", "watch case only", "bezel only", "clasp only",
                        "watch parts lot", "parts watch", "movement parts"]
        for kw in parts_keywords:
            if kw in title:
                return (f"WATCH PARTS - '{kw}' (parts only, not complete watch)", "PASS")

        # === CLOCKS (not watches) ===
        clock_keywords = ["wall clock", "desk clock", "mantle clock", "alarm clock",
                        "grandfather clock", "cuckoo clock", "travel clock",
                        "table clock", "shelf clock"]
        for kw in clock_keywords:
            if kw in title:
                return (f"CLOCK - '{kw}' (not a watch)", "PASS")

        # === WATCH ACCESSORIES (no watch) ===
        accessory_keywords = ["watch box only", "watch case only", "watch roll",
                            "watch winder", "watch display", "watch holder",
                            "watch storage", "empty box"]
        for kw in accessory_keywords:
            if kw in title:
                return (f"ACCESSORY ONLY - '{kw}' (no watch included)", "PASS")

        # === FASHION/LOW-END BRANDS ===
        fashion_brands = ["michael kors", "mk ", "fossil", "guess", "armani exchange",
                         "dkny", "diesel", "nixon", "mvmt", "daniel wellington",
                         "invicta", "stuhrling", "akribos", "geneva", "timex",
                         "anne klein", "relic", "peugeot", "armitron", "casio g-shock"]
        for brand in fashion_brands:
            if brand in title:
                return (f"FASHION WATCH - has minimal resale value", "PASS")
        if "citizen" in title and "bullhead" not in title:
            return ("LOW-END BRAND - Citizen (not Bullhead)", "PASS")

        # Flexible gold detection - handles "14k", "14 k", "14kt", "14 kt", "14 karat", etc.
        import re
        gold_pattern = re.compile(r'\b(10|14|18|22|24)\s*(k|kt|karat|carat)\b', re.IGNORECASE)
        has_gold = bool(gold_pattern.search(title)) or any(kw in title for kw in ["solid gold", "gold case", "yellow gold", "rose gold", "white gold"])
        is_premium = any(pb in title for pb in self.PREMIUM_BRANDS)
        is_mid_tier = any(mb in title for mb in self.MID_BRANDS)
        is_valuable_brand = is_premium or is_mid_tier  # Both tiers have significant resale value

        # === FLOOR PRICE CHECK - Premium watches priced below floor = BUY ===
        if is_premium:
            floor_price = 0
            matched_model = None
            # Check for specific model floors (more specific = higher priority)
            for model, floor in sorted(self.PREMIUM_FLOOR_PRICES.items(), key=lambda x: -len(x[0])):
                if model in title:
                    floor_price = floor
                    matched_model = model
                    break

            # Check for premium features that add value
            has_premium_feature = any(feat in title for feat in self.PREMIUM_FEATURES)
            if has_premium_feature:
                floor_price = int(floor_price * 1.25)  # 25% premium for special features

            if floor_price > 0 and price < floor_price * 0.6:  # Priced at 60% or less of floor = clear BUY
                feature_note = " with premium features" if has_premium_feature else ""
                return (f"UNDERPRICED PREMIUM WATCH: {matched_model}{feature_note} floor ${floor_price}, listed ${price:.0f} ({price/floor_price*100:.0f}% of floor) = BUY", "BUY")
            elif floor_price > 0 and price < floor_price * 0.8:  # 60-80% of floor = RESEARCH
                return (f"POTENTIAL DEAL: {matched_model} floor ${floor_price}, listed ${price:.0f} ({price/floor_price*100:.0f}% of floor)", "RESEARCH")

        # === VINTAGE CHRONOGRAPH FLOOR CHECK ===
        # Vintage chronographs are collectible regardless of brand
        # Even "entry" brands like Benrus have valuable chronographs
        is_chrono = any(kw in title for kw in ["chronograph", "chrono"])
        if is_chrono:
            chrono_floor = 0
            matched_chrono = None
            # Check specific chronograph models (more specific = higher priority)
            for model, floor in sorted(self.VINTAGE_CHRONOGRAPH_FLOORS.items(), key=lambda x: -len(x[0])):
                if model in title:
                    chrono_floor = floor
                    matched_chrono = model
                    break

            if chrono_floor > 0 and price < chrono_floor * 0.6:
                return (f"UNDERPRICED VINTAGE CHRONOGRAPH: {matched_chrono} floor ${chrono_floor}, listed ${price:.0f} ({price/chrono_floor*100:.0f}% of floor) = BUY", "BUY")
            elif chrono_floor > 0 and price < chrono_floor * 0.85:  # Slightly higher threshold for chronos (85%)
                return (f"POTENTIAL CHRONO DEAL: {matched_chrono} floor ${chrono_floor}, listed ${price:.0f} ({price/chrono_floor*100:.0f}% of floor)", "RESEARCH")

        # === MODERN/NEW LUXURY WATCHES ===
        # These could still be opportunities if priced well below market
        # Changed from PASS to RESEARCH - let user evaluate
        modern_indicators = [
            "2020", "2021", "2022", "2023", "2024", "2025", "2026",  # Recent years
            "lnib", "bnib", "unworn", "brand new", "new in box",     # New condition
            "full set", "complete set", "box papers", "box & papers",  # Complete sets
            "factory warranty", "ad purchase", "authorized dealer",   # Retail indicators
        ]
        is_modern = any(ind in title for ind in modern_indicators)

        # Modern valuable brand watches - RESEARCH (not PASS) - they sell fast when priced right
        if is_valuable_brand and is_modern and price > 1500:
            return (f"MODERN VALUABLE WATCH at ${price:.0f} - check if priced below market (Chrono24/eBay comps)", "RESEARCH")

        # Valuable watch with box/papers over $2500 - still RESEARCH, could be a deal
        if is_valuable_brand and price > 2500 and any(kw in title for kw in ["box", "papers", "full set"]):
            return (f"VALUABLE COMPLETE SET at ${price:.0f} - verify against market (Chrono24/WatchCharts)", "RESEARCH")

        quartz_keywords = ["quartz", "battery powered", "eco-drive", "solar"]
        is_quartz = any(kw in title for kw in quartz_keywords)
        if is_quartz and not has_gold and not is_premium:
            return ("QUARTZ WATCH - no value unless premium or gold", "PASS")

        broken_keywords = ["for parts", "parts only", "not working", "broken", "as is", "needs repair"]
        is_broken = any(kw in title for kw in broken_keywords)
        # Broken quartz with no gold = no value
        if is_broken and is_quartz and not has_gold:
            return ("BROKEN QUARTZ - no repair value", "PASS")
        # Broken gold watch still has melt value - flag for RESEARCH
        if is_broken and has_gold:
            return (f"BROKEN GOLD WATCH at ${price:.0f} - still has gold melt value", "RESEARCH")

        if price > 200:
            for brand in fashion_brands:
                if brand in title:
                    return (f"OVERPRICED FASHION - at ${price}", "PASS")

        # Vintage watch indicators - these are OPPORTUNITIES
        vintage_indicators = ["vintage", "antique", "estate", "1940", "1950", "1960", "1970", "1980",
                            "cal.", "caliber", "manual wind", "hand wind", "bumper", "pre-owned",
                            "art deco", "mid century", "tank style", "ladies", "lady's"]
        is_vintage = any(vi in title for vi in vintage_indicators)

        # === GOLD WATCHES WITH EXPLICIT WEIGHT = HIGH PRIORITY ===
        # If seller states weight in title OR description, we can calculate melt value
        weight_pattern = re.compile(r'(\d+\.?\d*)\s*(gram|grams|gm|g|dwt|oz)\b', re.IGNORECASE)
        weight_match = weight_pattern.search(title)

        # Also check description for weight (often listed there, not in title)
        description = data.get("description", data.get("Description", "")).lower()
        if not weight_match:
            weight_match = weight_pattern.search(description)

        if has_gold and weight_match:
            stated_weight = float(weight_match.group(1))
            unit = weight_match.group(2).lower()
            # Convert to grams
            if unit in ['dwt']:
                stated_weight = stated_weight * 1.555
            elif unit in ['oz']:
                stated_weight = stated_weight * 31.1035

            # Deduct movement weight (watches have non-gold movement inside)
            # Ladies watch movement: ~2-3g, Men's: ~3-5g
            is_ladies = any(kw in title for kw in ["ladies", "lady", "women", "womens", "woman's"])
            movement_deduction = 3 if is_ladies else 4  # Conservative deduction
            gold_weight = max(stated_weight - movement_deduction, stated_weight * 0.7)  # At least 70% is gold

            # Calculate estimated melt value based on karat
            karat_match = gold_pattern.search(title)
            if karat_match:
                karat = int(karat_match.group(1))
                purity = karat / 24.0
                gold_gram_price = SPOT_PRICES.get("gold_oz", 2650) / 31.1035
                melt_value = gold_weight * purity * gold_gram_price
                max_buy = melt_value * 0.90  # 90% of melt = max buy

                price_to_melt_ratio = price / melt_value if melt_value > 0 else 999

                # Clear BUY if price is <=90% of melt (our threshold)
                if price <= max_buy:
                    return (f"GOLD WATCH BUY: {stated_weight:.1f}g stated - {movement_deduction}g movement = {gold_weight:.1f}g gold @ {karat}K. Melt ${melt_value:.0f}, maxBuy ${max_buy:.0f}, price ${price:.0f} ({price_to_melt_ratio*100:.0f}% of melt)", "BUY")
                elif price_to_melt_ratio <= 0.95:  # Within 5% of max buy - worth a look
                    return (f"GOLD WATCH CLOSE: {gold_weight:.1f}g {karat}K = ${melt_value:.0f} melt. Price ${price:.0f} is {price_to_melt_ratio*100:.0f}% of melt (maxBuy ${max_buy:.0f})", "RESEARCH")
                elif melt_value > price:
                    return (f"GOLD WATCH with STATED WEIGHT ({stated_weight:.1f}g {karat}K) - melt ~${melt_value:.0f} vs ${price:.0f} list = RESEARCH", "RESEARCH")

        # === VINTAGE GOLD WATCHES = OPPORTUNITY ===
        # Vintage gold watches have value from gold content AND potential collector value
        # Flag these for RESEARCH - they're exactly what we're looking for
        if has_gold and is_vintage:
            return (f"VINTAGE GOLD WATCH at ${price:.0f} - potential opportunity (gold + collector value)", "RESEARCH")

        # Gold watches in general - could be gold scrap opportunity (lowered threshold from $200)
        if has_gold and price > 100:
            return (f"GOLD WATCH at ${price:.0f} - needs valuation (gold content vs collector)", "RESEARCH")

        # Premium and mid-tier brands need manual review (even without gold)
        # Hamilton, Tag Heuer, Longines, etc. all have significant resale value
        if is_valuable_brand and price > 200:
            brand_tier = "PREMIUM" if is_premium else "MID-TIER"
            return (f"{brand_tier} WATCH BRAND at ${price:.0f} - requires market verification", "RESEARCH")

        # Vintage mechanical watches from unknown brands - could be valuable
        if is_vintage and price > 100:
            mechanical_indicators = ["automatic", "self-winding", "self winding", "17 jewel", "21 jewel", "swiss"]
            is_mechanical = any(mi in title for mi in mechanical_indicators)
            if is_mechanical:
                return (f"VINTAGE MECHANICAL at ${price:.0f} - potential collector value", "RESEARCH")

        return (None, None)

    def get_prompt(self) -> str:
        gold_oz = SPOT_PRICES.get("gold_oz", 2650)
        gold_gram = gold_oz / 31.1035
        k14 = gold_gram * 0.583
        k18 = gold_gram * 0.75
        return f"""
=== WATCH ANALYZER ===

Analyze watches for RESALE VALUE. Return JSON with these EXACT fields:

{{
    "Qualify": "Yes" or "No",
    "Recommendation": "BUY" or "PASS" or "RESEARCH",
    "verified": true or false,
    "gold": true or false,
    "karat": "10K"/"14K"/"18K"/"N/A"/"Gold-Filled",
    "itemtype": "Watch"/"PocketWatch"/"WatchParts",
    "weight": case weight in grams (number),
    "pricepergram": 0,
    "Margin": maxBuy minus listingPrice (number),
    "maxBuy": max price to pay (number),
    "confidence": 0-100 (number),
    "fakerisk": "low"/"medium"/"high",
    "reasoning": "Brand: X, Model: Y. Analysis...",
    "marketprice": estimated market value (number),
    "brand": "brand name",
    "model": "model if known"
}}

BRAND TIERS:
- PREMIUM (00+): Rolex, Omega, Patek, Cartier, Breitling, Tudor
- MID (00-500): Longines, Hamilton, Tissot, Movado, Bulova, Wittnauer
- ENTRY (0-150): Seiko, Elgin, Waltham, Gruen, Benrus

GOLD VALUES: 14K=${k14:.2f}/g, 18K=${k18:.2f}/g
Gold-filled = minimal value (<0)

RULES:
- Negative Margin = PASS
- Premium brands = default RESEARCH
- confidence must be NUMBER 0-100

CRITICAL - NO HALLUCINATED VALUES:
- If you cannot cite specific comparable sales or verified reference prices for this exact model, set confidence to 40 and Recommendation to RESEARCH
- Do NOT estimate market values without evidence. Use 0 for marketprice if unknown
- NEVER set marketprice above 3x listing price unless you cite specific comparable model references
- For unknown/obscure brands, assume marketprice equals listing price unless you have evidence otherwise
- "I think it might be worth..." is NOT evidence. You need actual sold comparables or known model pricing
"""

    def validate_response(self, response: dict, data: dict = None) -> dict:
        if "recommendation" in response and "Recommendation" not in response:
            response["Recommendation"] = response["recommendation"]
        if "brand" not in response:
            response["brand"] = "Unknown"
        if "Qualify" not in response:
            response["Qualify"] = "Yes" if response.get("Recommendation") != "PASS" else "No"
        if "confidence" not in response:
            response["confidence"] = 50
        if "itemtype" not in response:
            response["itemtype"] = "Watch"
        if "fakerisk" not in response:
            response["fakerisk"] = "medium"
        if "verified" not in response:
            response["verified"] = False

        # Get title and price from data if available
        title = ""
        listing_price = 0
        if data:
            title = data.get("Title", "").lower().replace('+', ' ')
            listing_price = float(str(data.get("TotalPrice", data.get("Price", data.get("_listing_price", 0)))).replace('$', '').replace(',', '') or 0)

        brand = response.get("brand", "").lower()
        rec = response.get("Recommendation", response.get("recommendation", ""))

        # Check brand from both response and title
        is_premium = any(pb in brand for pb in self.PREMIUM_BRANDS) or any(pb in title for pb in self.PREMIUM_BRANDS)
        is_mid_tier = any(mb in brand for mb in self.MID_BRANDS) or any(mb in title for mb in self.MID_BRANDS)
        is_valuable_brand = is_premium or is_mid_tier

        # CRITICAL: Valuable brand watches should NEVER be auto-BUY for COLLECTIBLE value
        # But GOLD MELT value BUYs are OK - brand doesn't matter when buying for scrap
        # Check if this is a melt-based BUY (reasoning contains gold weight calculation)
        reasoning = response.get("reasoning", "")
        is_melt_buy = "GOLD WATCH BUY" in reasoning or "melt" in reasoning.lower() and "gold" in reasoning.lower()

        if is_valuable_brand and rec == "BUY" and not is_melt_buy:
            response["Recommendation"] = "RESEARCH"
            brand_tier = "Premium" if is_premium else "Mid-tier"
            response["reasoning"] = reasoning + f" | SERVER: {brand_tier} watch brand - ALWAYS requires manual verification. Cannot auto-BUY."
            response["tier0_block"] = "VALUABLE_WATCH_NO_AUTO_BUY"

        # CRITICAL: High-value watches should NEVER be auto-PASS
        # A $25,000 Rolex Daytona might be a deal if market is $30,000!
        # Force RESEARCH for expensive premium brand watches even if AI says PASS
        if is_premium and listing_price > 1000 and rec == "PASS":
            response["Recommendation"] = "RESEARCH"
            response["Qualify"] = "Maybe"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Premium watch at ${listing_price:.0f} - AI said PASS but needs manual verification (could be priced below market)"
            print(f"[WATCH] OVERRIDE: PASS->RESEARCH for premium watch at ${listing_price:.0f}")

        # Mid-tier brands over $500 that got PASS - also worth a look
        if is_mid_tier and listing_price > 500 and rec == "PASS":
            response["Recommendation"] = "RESEARCH"
            response["Qualify"] = "Maybe"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Mid-tier watch at ${listing_price:.0f} - verify market value"

        # Gold watches with high market prices - value is collectible, not melt
        market_price = response.get("marketprice", 0)
        if isinstance(market_price, str):
            market_price = float(market_price.replace("$", "").replace(",", "") or 0)
        if market_price > 500 and rec == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value watch (${market_price}) - requires manual verification."
            rec = "RESEARCH"

        # === HALLUCINATION GUARD ===
        # If AI claims marketprice > 3x listing price with low confidence = likely hallucinated
        confidence_val = 50
        try:
            conf = response.get("confidence", 50)
            confidence_val = int(conf) if isinstance(conf, (int, float)) else int(str(conf).replace('%', '') or 50)
        except (ValueError, TypeError):
            confidence_val = 50

        rec = response.get("Recommendation", rec)  # Re-read in case changed above

        if market_price > 0 and listing_price > 0:
            price_ratio = market_price / listing_price
            if price_ratio > 3.0 and confidence_val < 85 and rec == "BUY":
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Market ${market_price:.0f} is {price_ratio:.1f}x listing ${listing_price:.0f} with confidence {confidence_val}% - likely hallucinated."
                response["hallucination_guard"] = True
                rec = "RESEARCH"

        # === HIGH-PRICE WATCH GUARD ===
        # For expensive watches (>$5000), we need MUCH higher evidence bar
        # These are frequently overpriced and AI hallucinates values
        if listing_price > 5000 and rec in ("BUY", "RESEARCH"):
            # If market < listing, this is overpriced - PASS
            if market_price > 0 and market_price < listing_price:
                response["Recommendation"] = "PASS"
                response["Qualify"] = "No"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: OVERPRICED - AI market ${market_price:.0f} < listing ${listing_price:.0f}. PASS."
                print(f"[WATCH] OVERPRICED: market ${market_price:.0f} < listing ${listing_price:.0f} - PASS")
                rec = "PASS"
            # If confidence < 90 on expensive watch, don't trust it
            elif confidence_val < 90 and rec == "BUY":
                response["Recommendation"] = "PASS"
                response["Qualify"] = "No"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value watch ${listing_price:.0f} with confidence {confidence_val}% < 90% required. PASS."
                print(f"[WATCH] LOW CONFIDENCE: ${listing_price:.0f} watch at {confidence_val}% confidence - PASS")
                rec = "PASS"

        # === ENTRY-LEVEL BRAND BLOCK ===
        is_entry = any(eb in brand for eb in self.ENTRY_BRANDS) or any(eb in title for eb in self.ENTRY_BRANDS)
        if is_entry and rec == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | SERVER: Entry-level brand - needs manual verification."
            rec = "RESEARCH"

        # === NO-REFERENCE DETECTION ===
        # If reasoning doesn't cite comparable sales and this isn't a known valuable brand
        reasoning_text = response.get("reasoning", "").lower()
        has_reference = any(term in reasoning_text for term in [
            "comparable", "comps", "sold for", "sells for", "market value",
            "chrono24", "watchrecon", "ebay sold", "similar models sell",
            "typically sell", "valued at", "reference price"
        ])
        if not has_reference and rec == "BUY" and not is_valuable_brand:
            response["Recommendation"] = "RESEARCH"
            response["confidence"] = min(40, confidence_val)
            response["reasoning"] = response.get("reasoning", "") + " | SERVER: No comparable sales cited - forcing RESEARCH."
            rec = "RESEARCH"

        # === MARKET CAP ENFORCEMENT ===
        # Hard caps on maxBuy based on brand tier and gold content
        import re as _re
        gold_pattern_check = _re.compile(r'\b(10|14|18|22|24)\s*(k|kt|karat|carat)\b', _re.IGNORECASE)
        has_gold_cap = response.get("gold", False) or bool(gold_pattern_check.search(title)) or any(
            kw in title for kw in ["solid gold", "gold case", "yellow gold", "rose gold", "white gold"]
        )
        is_filled = "gold filled" in title or "gold-filled" in title or response.get("karat", "").lower() == "gold-filled" or any(
            fb in title for fb in self.FILLED_BRANDS
        )
        is_unknown_brand = not is_premium and not is_mid_tier and not is_entry

        rec = response.get("Recommendation", rec)
        max_buy_val = 0
        try:
            max_buy_val = float(str(response.get("maxBuy", 0)).replace("$", "").replace(",", "") or 0)
        except (ValueError, TypeError):
            pass

        if rec in ("BUY", "RESEARCH") and max_buy_val > 0:
            cap = None
            cap_reason = ""

            if is_filled:
                cap = 30
                cap_reason = "Gold-filled (minimal gold content)"
            elif is_unknown_brand and not has_gold_cap:
                cap = 50
                cap_reason = "Unknown brand, no gold"
            elif is_entry and not has_gold_cap:
                cap = 75
                cap_reason = "Entry-level brand, no gold"
            elif not is_premium and not is_mid_tier and not has_gold_cap:
                cap = 150
                cap_reason = "Non-premium, no gold"

            if cap and max_buy_val > cap:
                response["maxBuy"] = str(cap)
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER CAP: Max buy capped at ${cap} ({cap_reason}). AI suggested ${max_buy_val:.0f}."
                new_margin = cap - listing_price
                if new_margin < 0:
                    response["Recommendation"] = "PASS"
                    response["Margin"] = str(int(new_margin))
                    response["Profit"] = str(int(new_margin))
                else:
                    response["Margin"] = str(int(new_margin))
                    response["Profit"] = f"+{int(new_margin)}"

        return response
