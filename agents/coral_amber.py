"""
Coral/Amber Agent - Handles coral and amber jewelry analysis
"""

from .base import BaseAgent


class CoralAmberAgent(BaseAgent):
    """Agent for coral and amber jewelry analysis"""

    category_name = "coral"

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for coral/amber.
        """
        title = data.get("Title", "").lower()

        # Fake indicators = PASS
        fake_keywords = ["coral color", "coral tone", "amber color", "amber tone",
                        "faux", "plastic", "resin", "imitation"]
        for kw in fake_keywords:
            if kw in title:
                return (f"FAKE - '{kw}' indicates not genuine", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the coral/amber analysis prompt"""
        return """
=== CORAL & AMBER ANALYZER ===

First determine if this is CORAL or AMBER, then apply correct rules.
NOTE: Coral/amber values are subjective - be conservative. Target: 50% of estimated value.

=== PRICING MODEL ===
1. Estimate value based on material, age, color, weight
2. maxBuy = estimatedvalue x 0.50 (conservative for subjective items)
3. Profit = maxBuy - listingPrice
4. If listingPrice > maxBuy = PASS
5. If uncertain about authenticity = RESEARCH (never BUY)

=== CORAL VALUE HIERARCHY ===

BY AGE (most important - 10x price difference):
| Age | Era | Value/gram |
| Antique | pre-1920 | $25-50+ |
| Vintage | 1920-1970 | $8-20 |
| Modern | 1970+ | $3-8 |

BY COLOR (descending value):
1. Oxblood/Deep Red - Premium ($40-100/g antique)
2. Red - High ($20-50/g antique)
3. Salmon/Orange - Medium
4. Pink/Angel Skin - Medium (Japanese highly valued)
5. White - Lower

CORAL INSTANT PASS:
- "coral color" or "coral tone" = NOT REAL
- Bamboo coral = Low value ($2-5/g)
- Sponge coral = Low value

=== AMBER VALUE HIERARCHY ===

BY TYPE (most important):
| Type | Value/gram |
| Butterscotch (opaque) | $10-30 |
| Cherry/Red | $15-40 (rare) |
| Cognac (clear brown) | $3-10 |
| Honey (clear golden) | $2-8 |

BY INCLUSIONS:
- Insects/bugs: MAJOR premium $50-500+ per piece
- Plant matter: Moderate premium
- Clear/none: Standard

AMBER INSTANT PASS:
- "amber color" or "amber tone" = NOT REAL
- Pressed amber / Ambroid = Low value
- Plastic/resin = REJECT
- Copal (young amber) = Lower value

=== AUTHENTICITY WARNING ===
Coral and amber are heavily faked. Be skeptical:
- If price seems too good = likely fake
- Unknown origin = increase fakerisk
- No photos of texture/translucency = RESEARCH
- Modern looking = probably not antique

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "material": "Coral"/"Amber"/"Unknown",
  "age": "Antique"/"Vintage"/"Modern"/"Unknown",
  "color": for coral: "Oxblood"/"Red"/"Salmon"/"Pink"/"White"
           for amber: "Butterscotch"/"Cherry"/"Cognac"/"Honey",
  "itemtype": "Carved"/"Graduated"/"Beaded"/"Cabochon",
  "origin": "Italian"/"Mediterranean"/"Baltic"/"Japanese"/"Unknown",
  "weight": weight in grams or "Unknown",
  "goldmount": "Yes"/"No" (has 10K+ gold or sterling mount),
  "inclusions": for amber: "Insect"/"Plant"/"None"
                for coral: "NA",
  "estimatedvalue": dollar estimate,
  "maxBuy": estimatedvalue x 0.50,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "MATERIAL: [type] | AGE: [era] | COLOR: [color] | WEIGHT: [Xg] | CALC: value $X, 50% = $Y, profit $Z | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate coral/amber response"""

        # Parse numbers robustly
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

        profit = parse_number(response.get("Profit", "0"))

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH (coral/amber heavily faked)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # Unknown material + BUY = RESEARCH
        material = str(response.get("material", "Unknown")).lower()
        if material == "unknown" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Unknown material = RESEARCH"

        # Low confidence (< 50) + BUY = RESEARCH
        try:
            confidence = int(response.get("confidence", 50))
            if confidence < 50 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Low confidence = RESEARCH"
        except:
            pass

        # Unknown age + BUY = RESEARCH (age is critical for coral value)
        age = str(response.get("age", "Unknown")).lower()
        if age == "unknown" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Unknown age = RESEARCH"

        return response
