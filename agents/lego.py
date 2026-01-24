"""
LEGO Agent - Handles LEGO set analysis
"""

from .base import BaseAgent


class LegoAgent(BaseAgent):
    """Agent for LEGO set analysis"""

    category_name = "lego"

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for LEGO.
        """
        title = data.get("Title", "").lower()

        # === NOT SEALED/INCOMPLETE ===
        open_keywords = ["open box", "opened", "no box", "missing box", "incomplete",
                        "used", "played with", "built", "assembled", "displayed",
                        "bulk", "loose", "bricks only", "parts only", "no minifigures",
                        "missing pieces", "missing bags", "partial set", "99% complete"]
        for kw in open_keywords:
            if kw in title:
                return (f"NOT SEALED - '{kw}' detected", "PASS")

        # === KNOCKOFFS ===
        knockoff_keywords = ["mega bloks", "lepin", "cobi", "king", "sy ", "decool",
                            "bela", "kazi", "compatible with lego", "like lego",
                            "not lego", "moc", "custom", "knock off", "knockoff",
                            "alternative brand", "off brand", "brick building"]
        for kw in knockoff_keywords:
            if kw in title:
                return (f"KNOCKOFF - '{kw}' detected", "PASS")

        # === INSTRUCTIONS/MANUALS ONLY ===
        instruction_keywords = ["instructions only", "manual only", "booklet only",
                               "directions only", "instructions book", "no bricks",
                               "no pieces", "paper only"]
        for kw in instruction_keywords:
            if kw in title:
                return (f"INSTRUCTIONS ONLY - '{kw}' (no actual LEGO)", "PASS")

        # === EMPTY BOX ONLY ===
        box_keywords = ["box only", "empty box", "no lego", "no set", "packaging only",
                       "display box", "outer box only"]
        for kw in box_keywords:
            if kw in title:
                return (f"EMPTY BOX - '{kw}' (no actual LEGO)", "PASS")

        # === STICKER SHEETS ONLY ===
        sticker_keywords = ["sticker sheet", "stickers only", "decals only",
                           "replacement stickers"]
        for kw in sticker_keywords:
            if kw in title:
                return (f"STICKERS ONLY - '{kw}' (no value)", "PASS")

        # === SEVERELY DAMAGED BOX ===
        damage_keywords = ["crushed box", "dented box", "damaged box", "torn box",
                         "water damage", "mold", "smoke damage", "fire damage"]
        for kw in damage_keywords:
            if kw in title:
                return (f"DAMAGED - '{kw}' (reduces value significantly)", "PASS")

        # === MINIFIGS ONLY (under price threshold) ===
        minifig_keywords = ["minifigure only", "minifig only", "minifigures only",
                          "minifigs only", "figure only", "mini figure only",
                          "cmf", "collectible minifigure"]
        is_minifig_only = any(kw in title for kw in minifig_keywords)
        if is_minifig_only and price < 50:
            return (f"MINIFIG ONLY - at ${price:.0f} (too low for reliable profit)", "PASS")

        # === POLYBAGS (under price threshold) ===
        polybag_keywords = ["polybag", "poly bag", "foil bag", "promo bag"]
        is_polybag = any(kw in title for kw in polybag_keywords)
        if is_polybag and price < 15:
            return (f"POLYBAG - at ${price:.0f} (too cheap, no margin)", "PASS")

        # === LOW VALUE CURRENT THEMES ===
        # Small sets from common current themes - no margin
        low_value_themes = ["friends set", "city set", "classic set", "duplo",
                          "dots", "hidden side"]
        if price < 30:
            for theme in low_value_themes:
                if theme in title:
                    return (f"LOW VALUE CURRENT - '{theme}' at ${price:.0f}", "PASS")

        # === ACCESSORIES ONLY ===
        accessory_keywords = ["baseplate only", "base plate only", "storage only",
                            "container only", "bin only", "mat only"]
        for kw in accessory_keywords:
            if kw in title:
                return (f"ACCESSORY ONLY - '{kw}' (no LEGO sets)", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the LEGO analysis prompt"""
        return """
=== LEGO ANALYZER - RETIRED & HIGH VALUE FOCUS ===

We buy SEALED LEGO sets to resell. Target: 65% of market price.
PRIORITY: Retired sets and high-value items ($200-500+ sweet spot)

=== PRICE TARGETING ===
- Under $100: BE SKEPTICAL - likely current retail with thin margins
- $100-200: Acceptable if retired or high-demand theme
- $200-500: SWEET SPOT - best arbitrage opportunities
- $500+: Great for UCS, Modular, and long-retired sets

=== RETIRED vs CURRENT ===
RETIRED SETS = OUR FOCUS (no longer in production):
- Check if set number is still on LEGO.com
- Retired sets appreciate 10-30% per year
- Long-retired (5+ years) can be 2-5x original retail

CURRENT RETAIL = LOW PRIORITY:
- Available at Target, Walmart, Amazon, LEGO.com
- Everyone knows these prices = no arbitrage
- Only buy if significantly below retail (40%+ off)

=== HIGH VALUE RETIRED SETS ===
| Set | Name | Retired Value |
| 75192 | UCS Millennium Falcon | $800-1200 |
| 10179 | UCS Millennium Falcon (original) | $3000-5000 |
| 10294 | Titanic | $600-900 |
| 71043 | Hogwarts Castle | $500-700 |
| 10256 | Taj Mahal | $400-600 |
| 10255 | Assembly Square | $350-500 |
| 70620 | Ninjago City | $400-600 |
| 21322 | Pirates of Barracuda Bay | $300-450 |
| 10261 | Roller Coaster | $400-600 |
| 42083 | Bugatti Chiron | $400-550 |

=== HIGH VALUE THEMES (prioritize these) ===
1. UCS Star Wars (Ultimate Collector Series)
2. Modular Buildings (Creator Expert)
3. Large Technic vehicles
4. Ideas/Cuusoo retired sets
5. Harry Potter large sets
6. Ninjago City series
7. Disney Castle sets

=== CURRENT RETAIL WARNING ===
PASS or low confidence if:
- Set is currently available at major retailers
- Price is at or near current retail
- Recently released (within 1 year)
- Common themes: City, Friends, basic Creator

=== INSTANT PASS ===
CONDITION (we only buy sealed):
- "open box", "opened", "no box"
- "incomplete", "missing pieces"
- "used", "played with", "built", "displayed"
- "bulk", "loose", "parts only"
- "damaged box", "crushed", "dented"
- "minifigures only"

KNOCKOFFS (not real LEGO):
- Mega Bloks, Lepin, Cobi, King, Decool, Bela
- "compatible with LEGO", "like LEGO"
- "MOC", "custom"

OTHER:
- Current retail sets at MSRP (no margin)
- Under $100 unless clearly retired/valuable

=== FAKE WARNING SIGNS ===
- Price 50%+ below market on retired sets = LIKELY FAKE
- Stock photos only
- Seller in China for retired sets
- Missing LEGO logo in photos
- Poor print quality on box

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "SetNumber": LEGO set number like "75192",
  "SetName": "Millennium Falcon",
  "Theme": "Star Wars"/"Harry Potter"/"Marvel"/"Technic"/"Creator"/etc,
  "Retired": "Yes"/"No"/"Unknown",
  "YearsRetired": number or "Current" or "Unknown",
  "SetCount": number of sets,
  "marketprice": estimated market value,
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [set info] | RETIRED: [yes/no, years] | CONCERNS: [or none] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate LEGO response"""

        # Parse profit/margin robustly (handles strings, integers, symbols)
        def parse_number(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace("$", "").replace(",", "").replace("(", "-").replace(")", "").replace("+", "").strip()
            try:
                return float(s)
            except:
                return 0

        # Check both Margin and Profit fields (for compatibility)
        profit = parse_number(response.get("Profit", response.get("Margin", "0")))

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # Current retail (not retired) + BUY = lower confidence or RESEARCH
        retired = str(response.get("Retired", "Unknown")).lower()
        if retired == "no" and response.get("Recommendation") == "BUY":
            # Current retail - be skeptical
            try:
                confidence = int(response.get("confidence", 50))
                if confidence > 60:
                    response["confidence"] = 60  # Cap confidence for current retail
                    response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Current retail = capped confidence"
            except:
                pass

        # Price floor check: under $100 for non-retired = RESEARCH
        market_price = parse_number(response.get("marketprice", 0))
        if market_price < 100 and retired != "yes" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Low value current retail = RESEARCH"

        return response
