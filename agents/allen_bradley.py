"""
Allen Bradley Agent - Handles industrial automation equipment analysis
Allen Bradley / Rockwell Automation PLCs, HMIs, Drives, I/O modules
"""

from .base import BaseAgent


class AllenBradleyAgent(BaseAgent):
    """Agent for Allen Bradley industrial automation equipment"""

    category_name = "allen_bradley"

    # High-value product series
    PREMIUM_SERIES = {
        "controllogix": {"prefix": "1756", "min_value": 200, "max_value": 8000},
        "compactlogix": {"prefix": "1769", "min_value": 100, "max_value": 3000},
        "micrologix": {"prefix": "1761|1762|1763|1764", "min_value": 50, "max_value": 500},
        "powerflex": {"prefix": "20F|25B|25A|20G|22F|22A", "min_value": 150, "max_value": 5000},
        "panelview": {"prefix": "2711", "min_value": 300, "max_value": 5000},
        "kinetix": {"prefix": "2198|2093|2094", "min_value": 200, "max_value": 4000},
        "point_io": {"prefix": "1734", "min_value": 30, "max_value": 300},
        "flex_io": {"prefix": "1794", "min_value": 40, "max_value": 400},
        "guardlogix": {"prefix": "1756-L7SP|1756-L6", "min_value": 500, "max_value": 6000},
    }

    # Known fake/clone risk catalog numbers
    HIGH_FAKE_RISK = [
        "1756-L61", "1756-L62", "1756-L63",  # Popular ControlLogix CPUs
        "1769-L33ER", "1769-L30ER",  # Popular CompactLogix
        "2711P-T10", "2711P-T7",  # Popular PanelViews
    ]

    def quick_pass(self, data: dict, price: float) -> tuple:
        """Quick filtering for Allen Bradley items"""
        title = data.get("Title", "").lower()
        from_country = data.get("FromCountry", "").lower()
        import re

        # === CHINA ORIGIN = HIGH FAKE RISK ===
        if "china" in from_country or "hong kong" in from_country:
            if price > 50:
                return ("HIGH FAKE RISK - Ships from China/HK (clones common)", "RESEARCH")

        # === CHECK FOR HIGH-VALUE CATALOG NUMBERS FIRST ===
        # These should ALWAYS go to AI analysis, never quick-passed
        high_value_patterns = [
            r'1756-L\d',      # ControlLogix CPUs ($500-6000)
            r'1769-L\d',      # CompactLogix CPUs ($400-2000)
            r'2711P-',        # PanelView Plus HMIs ($500-3000)
            r'20F-',          # PowerFlex 753 drives ($500-3000)
            r'25B-',          # PowerFlex 525 drives ($200-800)
            r'2198-',         # Kinetix servo drives ($500-4000)
            r'2094-',         # Kinetix servo modules ($300-2000)
            r'1756-EN',       # Ethernet modules ($200-600)
            r'1756-IB\d',     # Digital I/O ($100-400)
            r'1756-OB\d',     # Digital output ($100-400)
            r'1756-IF\d',     # Analog input ($200-600)
            r'1756-OF\d',     # Analog output ($200-600)
        ]
        for pattern in high_value_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                return (f"HIGH-VALUE CATALOG NUMBER detected - route to AI", None)  # Continue to AI

        # === MANUALS/DOCUMENTATION ONLY ===
        doc_keywords = ["manual only", "instruction manual", "user guide only",
                       "cd only", "software cd", "documentation only"]
        for kw in doc_keywords:
            if kw in title:
                return (f"DOCUMENTATION ONLY - '{kw}'", "PASS")

        # === VERY LOW VALUE ACCESSORIES ===
        # Only pass truly low-value items - be conservative
        low_value_accessories = ["mounting bracket", "terminal block", "1492-",
                                "keyswitch", "blank cover", "filler module"]
        for kw in low_value_accessories:
            if kw in title and price < 20:
                return (f"LOW VALUE ACCESSORY - '{kw}' under $20", "PASS")

        # === DAMAGED/FOR PARTS - STILL VALUABLE ===
        damage_keywords = ["for parts", "parts only", "not working", "broken",
                         "damaged", "as-is", "as is", "defective", "bad"]
        for kw in damage_keywords:
            if kw in title:
                # Damaged Allen Bradley can still be valuable - route to RESEARCH
                if price > 50:
                    return (f"DAMAGED ITEM at ${price:.0f} - '{kw}' (verify salvage value)", "RESEARCH")
                # Only pass very low-priced damaged items
                if price < 25:
                    return (f"DAMAGED/PARTS - '{kw}' under $25", "PASS")
                # Otherwise let AI evaluate
                return (None, None)

        # === OBSOLETE BUT STILL HAS MARKET ===
        # SLC 500 and PLC-5 still have market for legacy systems
        obsolete_keywords = ["slc 500", "slc500", "plc-5", "plc5", "1747-", "1785-"]
        for kw in obsolete_keywords:
            if kw in title:
                # These still sell - send to AI unless very cheap
                if price > 75:
                    return (f"OBSOLETE SERIES - '{kw}' at ${price:.0f} (still has market)", "RESEARCH")
                if price < 30:
                    return (f"OBSOLETE - '{kw}' under $30", "PASS")
                return (None, None)  # Let AI evaluate

        # === PRICE FLOOR - VERY LOW ===
        if price < 15:
            return ("PRICE TOO LOW - Industrial parts typically $15+", "PASS")

        # === ANYTHING ELSE WITH AB KEYWORDS = EVALUATE ===
        # If we got here with Allen Bradley content, let the AI analyze it
        ab_keywords = ["allen bradley", "allen-bradley", "rockwell", "1756", "1769",
                      "1734", "1794", "2711", "powerflex", "controllogix", "compactlogix",
                      "panelview", "kinetix", "micrologix", "guardlogix"]
        for kw in ab_keywords:
            if kw in title:
                return (f"ALLEN BRADLEY detected at ${price:.0f} - route to AI analysis", None)  # Continue to AI

        return (None, None)

    def get_prompt(self) -> str:
        """Get the Allen Bradley analysis prompt"""
        return """
=== ALLEN BRADLEY / ROCKWELL AUTOMATION ANALYZER ===

We buy Allen Bradley industrial automation equipment to resell. Target: 50-60% of market price.
PRIORITY: ControlLogix, CompactLogix, PowerFlex drives, PanelView HMIs

=== PRODUCT IDENTIFICATION ===

CRITICAL: Extract the CATALOG NUMBER (e.g., 1756-L72, 2711P-T10C4D8)
The catalog number determines the exact product and value.

SERIES IDENTIFICATION:
| Prefix | Series | Typical Value |
|--------|--------|---------------|
| 1756- | ControlLogix (high-end PLC) | $200-8000+ |
| 1769- | CompactLogix (mid PLC) | $100-3000 |
| 1761/62/63/64 | MicroLogix (small PLC) | $50-500 |
| 20F/25B/22F | PowerFlex Drives | $150-5000 |
| 2711P- | PanelView Plus (HMI) | $300-5000 |
| 2711- | PanelView (older HMI) | $100-1500 |
| 1734- | Point I/O | $30-300 |
| 1794- | Flex I/O | $40-400 |
| 2198/2093 | Kinetix Servo | $200-4000 |

=== CONDITION MATTERS ===
| Condition | Value Multiplier |
|-----------|------------------|
| NIB/Factory Sealed | 100% (premium) |
| New (open box) | 85-95% |
| Refurbished | 60-75% |
| Used/Tested | 40-60% |
| For Parts | 10-30% |

=== FAKE/CLONE WARNING ===
Chinese clones are VERY common for popular modules!

RED FLAGS:
- Ships from China/Hong Kong
- Price 50%+ below market
- Stock photos only
- No box/documentation for "new" items
- Seller has mixed inventory (not industrial specialist)

HIGH FAKE RISK catalog numbers:
- 1756-L61, L62, L63, L71, L72 (ControlLogix CPUs)
- 1769-L33ER, L30ER (CompactLogix)
- 2711P-T10, T7 (PanelViews)

=== PRICING GUIDANCE ===

ControlLogix CPUs (1756-Lxx):
| Model | New | Used |
|-------|-----|------|
| 1756-L71 | $2500-3500 | $1200-1800 |
| 1756-L72 | $3500-4500 | $1800-2500 |
| 1756-L73 | $4500-6000 | $2500-3500 |

CompactLogix (1769-Lxx):
| Model | New | Used |
|-------|-----|------|
| 1769-L33ER | $1500-2000 | $800-1200 |
| 1769-L30ER | $1200-1600 | $600-900 |

PowerFlex Drives:
- Value depends heavily on HP rating and features
- 525 series: $200-800
- 755 series: $1000-5000+

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "ProductType": "PLC"/"HMI"/"Drive"/"IO-Module"/"Power Supply"/"Servo"/"Communication",
  "CatalogNumber": "1756-L72" (extract from title),
  "Series": "ControlLogix"/"CompactLogix"/"PowerFlex"/"PanelView"/etc,
  "Condition": "NIB"/"New"/"Refurbished"/"Used"/"For Parts",
  "Sealed": "Yes"/"No",
  "FirmwareVersion": version if stated or "Unknown",
  "marketprice": estimated market value,
  "maxBuy": 55% of market for used, 65% for NIB,
  "Profit": maxBuy minus listing price,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [catalog#, series, condition] | CONCERNS: [fakes, damage, or none] | CALC: Market ~$X, 55% = $Y, list $Z = profit | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict, data: dict = None) -> dict:
        """Validate Allen Bradley response"""

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

        title = ""
        from_country = ""
        listing_price = 0
        if data:
            title = str(data.get("Title", "")).lower()
            from_country = str(data.get("FromCountry", "")).lower()
            listing_price = parse_number(data.get("TotalPrice", data.get("Price", 0)))

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # China/HK origin + BUY = RESEARCH (clones very common)
        if ("china" in from_country or "hong kong" in from_country) and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: China/HK origin = RESEARCH (verify authenticity)"

        # High-value items (>$500) with BUY = RESEARCH
        if listing_price > 500 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High-value item = RESEARCH (verify before buying)"

        # Check for premium series in title
        import re
        catalog_match = None
        for series, info in self.PREMIUM_SERIES.items():
            if re.search(info["prefix"], title, re.IGNORECASE):
                catalog_match = series
                break

        # If premium series detected but PASS with low market estimate, flag for review
        if catalog_match and response.get("Recommendation") == "PASS":
            min_val = self.PREMIUM_SERIES[catalog_match]["min_value"]
            if market_price < min_val and listing_price >= min_val * 0.4:
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: {catalog_match} detected - market ${market_price:.0f} seems low (min ~${min_val})"

        # CRITICAL: High-value industrial items should NEVER auto-PASS
        # Allen Bradley CPUs, drives, HMIs can be worth thousands - always worth verifying
        # If AI says PASS but price is significant, force RESEARCH
        if response.get("Recommendation") == "PASS" and listing_price >= 200:
            # Check if it's a potentially valuable item
            high_value_keywords = ["1756", "1769", "2711", "powerflex", "controllogix",
                                   "compactlogix", "panelview", "kinetix", "servo", "drive",
                                   "cpu", "processor", "1336", "20f-", "25b-"]
            if any(kw in title for kw in high_value_keywords):
                response["Recommendation"] = "RESEARCH"
                response["Qualify"] = "Maybe"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value AB component at ${listing_price:.0f} - AI said PASS but verify market value"
                print(f"[AB] OVERRIDE: PASS->RESEARCH for ${listing_price:.0f} item: {title[:50]}")

        # Also catch drives by model number pattern (1336 series are PowerFlex)
        if response.get("Recommendation") == "PASS" and listing_price >= 100:
            drive_patterns = [r'1336[A-Z]-', r'20[A-Z]\d{2,}', r'25[AB]-']
            for pattern in drive_patterns:
                if re.search(pattern, title, re.IGNORECASE):
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Drive detected at ${listing_price:.0f} - verify value"
                    break

        return response
