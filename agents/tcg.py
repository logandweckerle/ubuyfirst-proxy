"""
TCG Agent - Handles Trading Card Game sealed product analysis
"""

from .base import BaseAgent


class TCGAgent(BaseAgent):
    """Agent for TCG sealed product analysis"""

    category_name = "tcg"

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for TCG products.
        """
        title = data.get("Title", "").lower()

        # Not sealed = PASS
        open_keywords = ["opened", "loose packs", "resealed", "mystery", "repack"]
        for kw in open_keywords:
            if kw in title:
                return (f"NOT SEALED - '{kw}' detected", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the TCG analysis prompt"""
        return """
=== TCG ANALYZER - VINTAGE & HIGH VALUE FOCUS ===

We buy SEALED TCG products to resell. Target: 65% of market price.
PRIORITY: Vintage/WOTC and high-value items ($200-500+ sweet spot)

=== PRICE TARGETING ===
- Under $100: BE SKEPTICAL - likely current retail with thin margins
- $100-200: Acceptable if vintage or high-demand modern
- $200-500: SWEET SPOT - best arbitrage opportunities
- $500+: Great if verified authentic vintage

=== VINTAGE PRIORITY (Pokemon) ===
WOTC ERA (1999-2003) = HIGHEST VALUE:
| Set | Era | Booster Box Value |
| Base Set (Unlimited) | 1999 | $8,000-15,000+ |
| Base Set (1st Ed) | 1999 | $100,000+ |
| Jungle | 1999 | $6,000-10,000 |
| Fossil | 1999 | $5,000-8,000 |
| Team Rocket | 2000 | $5,000-8,000 |
| Gym Heroes/Challenge | 2000 | $6,000-12,000 |
| Neo Genesis | 2000 | $8,000-15,000 |
| Neo Discovery | 2001 | $6,000-10,000 |
| Neo Revelation | 2001 | $8,000-12,000 |
| Neo Destiny | 2002 | $15,000-25,000 |
| Legendary Collection | 2002 | $3,000-6,000 |

HIGH-VALUE MODERN (still worth targeting):
- Hidden Fates ETB: $150-250
- Champion's Path ETB: $80-150
- Evolving Skies BB: $200-350
- Celebrations UPC: $300-500
- 151 Booster Box: $150-250

=== CURRENT RETAIL WARNING ===
PASS or low confidence if:
- Item is currently in production and available at Target/Walmart/Amazon
- Price is at or near MSRP (no margin)
- Common current sets: Scarlet & Violet base, Paldea Evolved, Obsidian Flames
- Everyone knows these prices = no arbitrage

=== QUANTITY DETECTION ===
DEFAULT TO 1 ITEM unless title EXPLICITLY states multiple:
- "x2", "x3", "2x", "3x"
- "lot of 2", "bundle of 2"
- "2 boxes", "3 ETBs"

DO NOT assume multiple from:
- Pack counts (36 packs = 1 booster box)
- Card counts (9 packs in ETB = 1 ETB)

=== LOT HANDLING (CRITICAL!) ===
If listing contains MULTIPLE different products:
1. Count each product type separately
2. List each product in "lotItems" field with set name
3. Calculate total value by summing individual values
Example: "2x Evolving Skies ETB + 1x Celebrations BB" = lotItems: ["Evolving Skies ETB", "Evolving Skies ETB", "Celebrations Booster Box"]

=== PRODUCT TYPES ===
| Type | Contents |
| Booster Box | 36 packs, highest value |
| ETB | 9 packs + accessories |
| Booster Bundle | 6 packs |
| Collection Box | Various packs + promo |
| Case | Multiple boxes (usually 6) |

=== INSTANT PASS ===
- Opened/used products
- Loose packs from boxes
- Resealed indicators
- Foreign languages (except Japanese)
- "Mystery" or "repack" products
- Current retail sets at MSRP (no margin)
- Under $100 unless clearly vintage

=== FAKE/REPACK WARNING ===
- Price 50%+ below market on vintage = LIKELY FAKE
- Stock photos only
- New seller with vintage product
- "Mystery" or "repack"
- Shrink wrap looks wrong
- WOTC product from China = FAKE

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "TCG": "Pokemon"/"YuGiOh"/"MTG"/"OnePiece"/"Lorcana",
  "ProductType": "BoosterBox"/"ETB"/"Bundle"/"CollectionBox"/"Pack"/"Case",
  "SetName": "Evolving Skies",
  "isVintage": "Yes"/"No" (WOTC era or pre-2010),
  "ItemCount": number of items,
  "lotItems": ["Product 1", "Product 2"] (if lot - list each product with set name),
  "marketprice": estimated value,
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [product, set, condition] | VINTAGE: [yes/no, era] | CONCERNS: [or none] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate TCG response"""

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

        # High fake risk + BUY = RESEARCH (especially important for vintage)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # Non-vintage (current retail) + BUY = slightly lower confidence (was too aggressive)
        is_vintage = str(response.get("isVintage", "No")).lower()
        if is_vintage == "no" and response.get("Recommendation") == "BUY":
            try:
                confidence = int(response.get("confidence", 50))
                if confidence > 75:
                    response["confidence"] = 75  # Cap at 75 for current retail (was 60)
                    response["reasoning"] = response.get("reasoning", "") + " | NOTE: Current retail = capped confidence"
            except:
                pass

        # Price floor check: under $60 for non-vintage = RESEARCH (was $100 - too aggressive)
        market_price = parse_number(response.get("marketprice", 0))
        if market_price < 60 and is_vintage != "yes" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Very low value = RESEARCH"

        return response
