"""
Knives Agent - Handles collectible knife analysis
"""

from .base import BaseAgent


class KnivesAgent(BaseAgent):
    """Agent for collectible knife analysis"""

    category_name = "knives"

    # Premium brands that should NEVER auto-PASS
    PREMIUM_BRANDS = [
        "chris reeve", "strider", "microtech", "benchmade", "hinderer",
        "zero tolerance", "zt ", "spyderco", "protech", "pro-tech",
        "william henry", "randall", "bark river", "fallkniven",
        "emerson", "hogue", "kershaw", "buck 110", "case xx",
        "cattaraugus", "queen cutlery", "schrade", "ka-bar", "gerber",
        "cold steel", "sog", "crkt", "ontario", "boker", "puma"
    ]

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for knives.
        """
        title = data.get("Title", "").lower()

        # Kitchen knives (not collectible) = PASS
        kitchen_keywords = ["kitchen knife set", "chef knife set", "steak knife set",
                           "cutlery set", "knife block", "bread knife", "paring knife",
                           "santoku", "cleaver", "butcher knife"]
        for kw in kitchen_keywords:
            if kw in title:
                return (f"KITCHEN KNIFE - '{kw}' not collectible", "PASS")

        # Cheap/toy knives = PASS
        cheap_keywords = ["toy knife", "plastic knife", "rubber knife", "training knife",
                         "practice knife", "fake knife", "prop knife"]
        for kw in cheap_keywords:
            if kw in title:
                return (f"NOT COLLECTIBLE - '{kw}' detected", "PASS")

        # Price floor - collectible knives typically $50+
        if price < 30:
            return ("PRICE TOO LOW - Collectible knives typically $50+", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the knife analysis prompt"""
        return """
=== COLLECTIBLE KNIFE ANALYZER ===

We buy collectible and high-end knives to resell. Target: 60-70% of market price.
PRIORITY: Custom makers, limited editions, discontinued models, vintage

=== PRICE TARGETING ===
- Under $50: Usually not worth it (common production knives)
- $50-150: Decent opportunity for mid-range collectibles
- $150-500: SWEET SPOT - best arbitrage opportunities
- $500+: Great for custom makers and rare pieces

=== HIGH VALUE BRANDS (prioritize) ===
CUSTOM/SEMI-CUSTOM MAKERS:
| Maker | Typical Value Range |
| Chris Reeve | $300-600+ |
| Strider | $400-800+ |
| Microtech | $200-500+ |
| Benchmade Gold Class | $400-1000+ |
| William Henry | $500-2000+ |
| Dalibor Bergam | $300-700 |
| Eutsler | $500-1500+ |
| Jason Guthrie | $800-2000+ |
| Borka Blades | $400-1000+ |
| Monterey Bay Knives | $300-600 |

PRODUCTION (high-end):
| Brand | Notable Models |
| Spyderco | PM2, Manix, Military |
| Benchmade | 940, Bugout, Griptilian |
| Zero Tolerance | 0562, 0452 |
| Hinderer | XM-18, XM-24 |
| Pro-Tech | Malibu, Mordax |
| Hogue | Ritter, Deka |

VINTAGE/COLLECTIBLE:
| Brand | Era | Value |
| Randall Made | Any | $300-1500+ |
| Case XX | Pre-1970 | $100-500+ |
| Queen Cutlery | Vintage | $50-300 |
| Schrade | Vintage | $30-200 |
| Camillus | Military | $50-300 |
| Buck 110 | Early | $100-400 |

=== WHAT TO LOOK FOR ===
PREMIUM INDICATORS:
- Damascus steel (pattern welded)
- Carbon fiber, titanium handles
- Mother of pearl, mammoth ivory
- Hand-ground, hand-finished
- Limited edition, numbered
- Original box, papers, sheath

CONDITION MATTERS:
- "NIB" = New in Box (premium)
- "LNIB" = Like New in Box
- "Used" = 60-70% of NIB value
- "Sharpened" = Slight deduction
- "Damaged" = PASS

=== INSTANT PASS ===
- Kitchen knives (chef sets, steak knives)
- No-name Chinese knives
- "Tactical" mall ninja stuff
- Replicas, fantasy knives
- Heavily used/abused
- Missing sheaths on fixed blades
- Under $30 (rarely collectible)

=== FAKE WARNING SIGNS ===
- Price 50%+ below market for customs
- Stock photos only
- Seller in China for US customs
- "Damascus" at unrealistic prices
- Misspelled brand names

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "Brand": "Chris Reeve"/"Spyderco"/"Benchmade"/etc,
  "Model": "Sebenza 21"/"PM2"/etc,
  "KnifeType": "Folder"/"Fixed"/"Automatic"/"Balisong",
  "Maker": "Production"/"Custom"/"Semi-Custom"/"Vintage",
  "Condition": "NIB"/"LNIB"/"Used"/"Damaged",
  "SteelType": "S35VN"/"M390"/"Damascus"/etc if known,
  "HandleMaterial": "Titanium"/"Carbon Fiber"/"G10"/etc if known,
  "marketprice": estimated market value,
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [brand, model, type] | CONDITION: [condition notes] | CONCERNS: [or none] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict, data: dict = None) -> dict:
        """Validate knife response"""

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

        profit = parse_number(response.get("Profit", response.get("Margin", "0")))
        market_price = parse_number(response.get("marketprice", 0))
        listing_price = 0
        title = ""
        if data:
            listing_price = parse_number(data.get("TotalPrice", data.get("Price", 0)))
            title = str(data.get("Title", "")).lower()

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # Custom/high-value knives with BUY = RESEARCH (verify authenticity)
        maker = str(response.get("Maker", "")).lower()
        if maker in ("custom", "semi-custom") and market_price > 400 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High-value custom = RESEARCH (verify authenticity)"

        # === PREMIUM BRAND VALIDATION ===
        # Check if premium brand is in title but got PASS with suspiciously low market price
        detected_brand = None
        for brand in self.PREMIUM_BRANDS:
            if brand in title:
                detected_brand = brand
                break

        if detected_brand:
            # Premium brand + PASS + low market estimate = probably undervalued
            # Strider = $400-800+, Benchmade = $100-400+, etc.
            min_values = {
                "strider": 350, "chris reeve": 300, "microtech": 200, "hinderer": 300,
                "benchmade": 80, "zero tolerance": 100, "zt ": 100, "spyderco": 50,
                "protech": 150, "pro-tech": 150, "william henry": 400, "randall": 250,
                "cattaraugus": 60, "case xx": 40, "buck 110": 50
            }
            min_value = min_values.get(detected_brand, 50)

            if response.get("Recommendation") == "PASS":
                # If market price is below minimum expected, force RESEARCH
                if market_price < min_value and listing_price >= min_value * 0.5:
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: Premium brand '{detected_brand}' detected - market ${market_price:.0f} seems too low (min ~${min_value}), verify manually"

            # Even BUY should be RESEARCH for high-value brands to verify authenticity
            if response.get("Recommendation") == "BUY" and detected_brand in ["strider", "chris reeve", "hinderer", "microtech", "william henry", "randall"]:
                if listing_price > 200:
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: High-value brand '{detected_brand}' at ${listing_price:.0f} = verify authenticity"

        return response
