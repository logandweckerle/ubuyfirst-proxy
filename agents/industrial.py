"""
Industrial Agent - Handles Allen Bradley and industrial automation equipment analysis
"""

from .base import BaseAgent


class IndustrialAgent(BaseAgent):
    """Agent for industrial automation equipment analysis (Allen Bradley, Siemens, etc.)"""

    category_name = "industrial"

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for industrial equipment.
        """
        title = data.get("Title", "").lower()

        # Manuals/software only = PASS
        doc_keywords = ["manual only", "software only", "cd only", "documentation",
                       "instruction book", "user guide"]
        for kw in doc_keywords:
            if kw in title:
                return (f"DOCUMENTATION ONLY - '{kw}' detected", "PASS")

        # Broken/parts = lower priority but don't auto-pass (parts can be valuable)

        # Price floor
        if price < 20:
            return ("PRICE TOO LOW - Industrial parts typically $50+", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the industrial equipment analysis prompt"""
        return """
=== INDUSTRIAL AUTOMATION ANALYZER ===

We buy industrial automation equipment (PLCs, drives, HMIs) to resell.
Target: 50-60% of market price (lower margin due to testing/warranty concerns).
PRIORITY: Allen Bradley, Siemens, current production parts

=== PRICE TARGETING ===
- Under $50: Usually commodity parts, thin margins
- $50-200: Good for common modules, I/O cards
- $200-1000: SWEET SPOT - processors, drives, HMIs
- $1000+: Great for servo drives, large PLCs

=== HIGH VALUE BRANDS ===
TIER 1 (HIGHEST DEMAND):
| Brand | Product Lines | Typical Value |
| Allen Bradley/Rockwell | ControlLogix, CompactLogix | $200-5000+ |
| Allen Bradley | PanelView HMIs | $300-3000+ |
| Allen Bradley | PowerFlex Drives | $200-5000+ |
| Siemens | S7-1500, S7-1200 | $200-3000+ |
| Siemens | SINAMICS Drives | $300-5000+ |

TIER 2 (GOOD DEMAND):
| Brand | Product Lines |
| Mitsubishi | MELSEC PLCs |
| Omron | CJ/NJ Series |
| ABB | Drives, PLCs |
| Fanuc | Servo drives, CNC |
| Yaskawa | Servo drives |

=== ALLEN BRADLEY PART NUMBERS ===
HIGH VALUE SERIES:
- 1756-L* = ControlLogix processors ($500-3000)
- 1769-L* = CompactLogix processors ($400-2000)
- 2711P-* = PanelView Plus HMIs ($500-3000)
- 20F-* = PowerFlex 753 drives ($500-3000)
- 22F-* = PowerFlex 4M drives ($200-800)
- 1756-IB/OB = I/O modules ($100-400)

COMMODITY (lower margins):
- 1492-* = Terminal blocks
- 1746-* = SLC 500 (older, less demand)
- 1771-* = PLC-5 (legacy, declining)

=== WHAT TO LOOK FOR ===
PREMIUM INDICATORS:
- Factory sealed/new in box
- Current production (not obsolete)
- Complete with cables, keys
- Firmware updated
- Original packaging

CONDITION:
- New/Sealed = Full value
- Tested working = 70-80%
- Used untested = 50-60%
- For parts/repair = 20-40%
- Obsolete = 30-50%

=== INSTANT PASS ===
- Manuals/documentation only
- Software/license only
- Obviously damaged/burnt
- Legacy obsolete with no demand
- Chinese counterfeit parts
- Under $20 (commodity)

=== COUNTERFEIT WARNING ===
Industrial counterfeits are COMMON and DANGEROUS:
- Price way below market = suspect
- Seller in China = high risk
- Wrong fonts/labels in photos
- "Compatible" or "replacement"
- Missing holographic stickers
- Serial numbers that don't verify

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "Brand": "Allen Bradley"/"Siemens"/"Mitsubishi"/etc,
  "PartNumber": "1756-L72" or similar,
  "ProductType": "PLC"/"Drive"/"HMI"/"I/O"/"Servo"/"Other",
  "Series": "ControlLogix"/"CompactLogix"/"PowerFlex"/etc,
  "Condition": "New Sealed"/"New Open"/"Used Tested"/"Used Untested"/"Parts",
  "Obsolete": "Yes"/"No"/"Unknown",
  "Quantity": number if lot,
  "marketprice": estimated market value,
  "maxBuy": 55% of market (lower for untested),
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [brand, part#, type] | CONDITION: [new/used/tested] | CONCERNS: [counterfeit risk, obsolete, etc.] | CALC: Market ~$X, 55% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate industrial response"""

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

        # High fake risk = always RESEARCH (counterfeits are dangerous)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High counterfeit risk = RESEARCH"

        # Untested equipment with BUY = RESEARCH
        condition = str(response.get("Condition", "")).lower()
        if "untested" in condition and response.get("Recommendation") == "BUY":
            market_price = parse_number(response.get("marketprice", 0))
            if market_price > 200:
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Untested high-value = RESEARCH"

        # Obsolete parts with BUY = lower confidence
        obsolete = str(response.get("Obsolete", "")).lower()
        if obsolete == "yes" and response.get("Recommendation") == "BUY":
            try:
                confidence = int(response.get("confidence", 50))
                if confidence > 60:
                    response["confidence"] = 60
                    response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Obsolete = capped confidence"
            except:
                pass

        return response
