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
        "vacheron constantin", "jaeger-lecoultre", "jaeger lecoultre", "cartier",
        "iwc", "breitling", "panerai", "tudor", "grand seiko"
    ]

    MID_BRANDS = [
        "longines", "tag heuer", "heuer", "zenith", "oris", "hamilton",
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
        fashion_brands = ["michael kors", "mk ", "fossil", "guess", "armani exchange",
                         "dkny", "diesel", "nixon", "mvmt", "daniel wellington",
                         "invicta", "stuhrling", "akribos", "geneva", "timex",
                         "anne klein", "relic", "peugeot", "armitron", "casio g-shock"]
        for brand in fashion_brands:
            if brand in title:
                return (f"FASHION WATCH - has minimal resale value", "PASS")
        if "citizen" in title and "bullhead" not in title:
            return ("LOW-END BRAND - Citizen (not Bullhead)", "PASS")
        has_gold = any(kw in title for kw in ["14k", "18k", "solid gold", "gold case", "14kt", "18kt"])
        is_premium = any(pb in title for pb in self.PREMIUM_BRANDS)
        quartz_keywords = ["quartz", "battery powered", "eco-drive", "solar"]
        is_quartz = any(kw in title for kw in quartz_keywords)
        if is_quartz and not has_gold and not is_premium:
            return ("QUARTZ WATCH - no value unless premium or gold", "PASS")
        broken_keywords = ["for parts", "parts only", "not working", "broken", "as is", "needs repair"]
        is_broken = any(kw in title for kw in broken_keywords)
        if is_broken and is_quartz:
            return ("BROKEN QUARTZ - no repair value", "PASS")
        if price > 200:
            for brand in fashion_brands:
                if brand in title:
                    return (f"OVERPRICED FASHION - at ${price}", "PASS")

        # TIER 0: Premium brand watches should NEVER be auto-BUY
        # Their value is complex (model, condition, papers, service history)
        # Force RESEARCH to require manual verification
        if is_premium and price > 300:
            return (f"PREMIUM WATCH BRAND at ${price:.0f} - requires manual verification (value $500-$50,000+)", "RESEARCH")

        # Gold watches over $500 need manual verification (gold content vs collectible value)
        if has_gold and price > 500:
            return (f"GOLD WATCH at ${price:.0f} - value may be collectible, not just gold weight", "RESEARCH")

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

    def validate_response(self, response: dict) -> dict:
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

        brand = response.get("brand", "").lower()
        rec = response.get("Recommendation", response.get("recommendation", ""))
        is_premium = any(pb in brand for pb in self.PREMIUM_BRANDS)

        # CRITICAL: Premium brand watches should NEVER be auto-BUY
        # Value depends on: model, year, condition, box/papers, service history
        # Even Tier 2 cannot reliably assess this - force RESEARCH for manual review
        if is_premium and rec == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | SERVER: Premium watch brand (Omega/Rolex/etc) - ALWAYS requires manual verification. Cannot auto-BUY."
            response["tier0_block"] = "PREMIUM_WATCH_NO_AUTO_BUY"

        # Gold watches with high market prices - value is collectible, not melt
        market_price = response.get("marketprice", 0)
        if isinstance(market_price, str):
            market_price = float(market_price.replace("$", "").replace(",", "") or 0)
        if market_price > 500 and rec == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value watch (${market_price}) - requires manual verification."

        return response
