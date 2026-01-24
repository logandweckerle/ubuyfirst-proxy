"""
Pens Agent - Handles fountain pen and luxury pen analysis
"""

from .base import BaseAgent


class PensAgent(BaseAgent):
    """Agent for fountain pen and luxury pen analysis"""

    category_name = "pens"

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for pens.
        """
        title = data.get("Title", "").lower()

        # Cheap/disposable pens = PASS
        cheap_keywords = ["ballpoint set", "gel pen set", "pen pack", "office pens",
                         "bic pen", "papermate", "sharpie", "marker set", "highlighter"]
        for kw in cheap_keywords:
            if kw in title:
                return (f"NOT COLLECTIBLE - '{kw}' detected", "PASS")

        # Price floor - collectible pens typically $50+
        if price < 25:
            return ("PRICE TOO LOW - Collectible pens typically $50+", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the pen analysis prompt"""
        return """
=== FOUNTAIN PEN & LUXURY PEN ANALYZER ===

We buy collectible fountain pens and luxury writing instruments to resell.
Target: 60-70% of market price.
PRIORITY: Vintage, limited editions, gold nibs, luxury brands

=== PRICE TARGETING ===
- Under $50: Usually not worth it (modern cheap pens)
- $50-200: Good for vintage and mid-range
- $200-500: SWEET SPOT - best arbitrage opportunities
- $500+: Great for Montblanc, vintage gold, limited editions

=== HIGH VALUE BRANDS ===
LUXURY TIER ($200-5000+):
| Brand | Notable Models | Typical Value |
| Montblanc | Meisterstuck 149, 146 | $300-800 |
| Montblanc | Limited Editions | $500-5000+ |
| Pelikan | M800, M1000 | $300-600 |
| Visconti | Homo Sapiens, Opera | $400-1000+ |
| Aurora | 88, Optima | $300-600 |
| S.T. Dupont | Ligne 2, Olympio | $200-500 |
| Caran d'Ache | Leman, Varius | $300-800 |

MID-TIER ($100-400):
| Brand | Notable Models |
| Waterman | Carene, Expert |
| Parker | Duofold, Sonnet, 51 |
| Sheaffer | Triumph, PFM, Legacy |
| Sailor | 1911, Pro Gear |
| Pilot/Namiki | Custom 823, Falcon |

VINTAGE (HIGH VALUE):
| Brand | Era | Value Range |
| Parker 51 | 1941-1972 | $100-400 |
| Parker Duofold | 1920s-30s | $200-1000+ |
| Montblanc | Pre-1990 | $200-1500+ |
| Sheaffer Snorkel | 1950s | $100-300 |
| Waterman | 1920s-40s | $100-500 |
| Conklin | Crescent | $200-600 |

=== WHAT TO LOOK FOR ===
PREMIUM INDICATORS:
- 18K or 14K gold nib (MAJOR value add)
- Limited edition, numbered
- Original box, papers
- Celluloid, ebonite bodies (vintage)
- Maki-e (Japanese lacquer art)
- Sterling silver or gold overlay

NIB GRADES:
- 18K gold = Premium ($50-200 value)
- 14K gold = Good value
- Steel/Iridium = Base value
- Flex nib = Collector premium

CONDITION:
- NOS (New Old Stock) = Premium
- Mint = Full value
- User grade = 60-70%
- Cracked, repaired = 30-50%

=== INSTANT PASS ===
- Disposable/office pens
- Chinese knockoffs
- "Inspired by" or replica
- Cracked barrels/caps
- Missing parts (caps, clips)
- Dried out, not working
- Under $25 (rarely collectible)

=== FAKE WARNING SIGNS ===
- Montblanc at suspiciously low prices
- Stock photos only
- Seller in China for luxury brands
- Misspelled brand names
- "Montblanc style" or "like Montblanc"
- Serial numbers that don't verify

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "Brand": "Montblanc"/"Pelikan"/"Parker"/etc,
  "Model": "Meisterstuck 149"/"M800"/etc,
  "PenType": "Fountain"/"Rollerball"/"Ballpoint"/"Mechanical Pencil",
  "Era": "Vintage"/"Modern"/"Limited Edition",
  "NibMaterial": "18K Gold"/"14K Gold"/"Steel"/etc,
  "NibSize": "F"/"M"/"B"/"Flex" if known,
  "Condition": "NOS"/"Mint"/"Excellent"/"User"/"Parts",
  "HasBox": "Yes"/"No"/"Unknown",
  "marketprice": estimated market value,
  "maxBuy": 65% of market,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [brand, model, type] | NIB: [material/size if known] | CONCERNS: [or none] | CALC: Market ~$X, 65% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate pen response"""

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

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH (especially important for Montblanc)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # Montblanc with BUY = RESEARCH (high counterfeit rate)
        brand = str(response.get("Brand", "")).lower()
        market_price = parse_number(response.get("marketprice", 0))
        if "montblanc" in brand and market_price > 200 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Montblanc = RESEARCH (verify authenticity)"

        # Limited editions with high value = RESEARCH
        era = str(response.get("Era", "")).lower()
        if "limited" in era and market_price > 500 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Limited edition = RESEARCH (verify)"

        return response
