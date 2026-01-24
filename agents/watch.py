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
        # If seller states weight in title (e.g., "57 Grams", "19.2 Grams"), we can calculate melt value
        weight_pattern = re.compile(r'(\d+\.?\d*)\s*(gram|grams|gm|g|dwt|oz)\b', re.IGNORECASE)
        weight_match = weight_pattern.search(title)

        if has_gold and weight_match:
            stated_weight = float(weight_match.group(1))
            unit = weight_match.group(2).lower()
            # Convert to grams
            if unit in ['dwt']:
                stated_weight = stated_weight * 1.555
            elif unit in ['oz']:
                stated_weight = stated_weight * 31.1035

            # Calculate estimated melt value based on karat
            karat_match = gold_pattern.search(title)
            if karat_match:
                karat = int(karat_match.group(1))
                purity = karat / 24.0
                gold_gram_price = SPOT_PRICES.get("gold_oz", 2650) / 31.1035
                melt_value = stated_weight * purity * gold_gram_price * 0.90  # 90% of melt

                if melt_value > price * 1.2:  # 20%+ margin
                    return (f"GOLD WATCH with STATED WEIGHT ({stated_weight:.1f}g {karat}K) - melt ~${melt_value:.0f} vs ${price:.0f} list = HIGH PRIORITY", "RESEARCH")
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

        # CRITICAL: Valuable brand watches should NEVER be auto-BUY
        # Value depends on: model, year, condition, box/papers, service history
        # Even Tier 2 cannot reliably assess this - force RESEARCH for manual review
        if is_valuable_brand and rec == "BUY":
            response["Recommendation"] = "RESEARCH"
            brand_tier = "Premium" if is_premium else "Mid-tier"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: {brand_tier} watch brand - ALWAYS requires manual verification. Cannot auto-BUY."
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

        return response
