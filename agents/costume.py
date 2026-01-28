"""
Costume Jewelry Agent - Handles vintage costume jewelry analysis
"""

from .base import BaseAgent


class CostumeAgent(BaseAgent):
    """Agent for costume jewelry analysis"""

    category_name = "costume"

    # Designer tiers for quick reference
    TIER_1 = ["trifari", "eisenberg original", "miriam haskell", "schreiner", "hobe"]
    TIER_2 = ["weiss", "juliana", "delizza", "coro", "eisenberg ice", "kramer", "lisner", "vendome", "sherman"]
    TIER_3 = ["monet", "napier", "sarah coventry", "avon", "emmons", "coventry"]
    TIER_4 = ["forever 21", "h&m", "claire's", "icing", "fashion"]

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for costume jewelry.
        """
        title = data.get("Title", "").lower()

        # ============================================================
        # TRIFARI / JELLY BELLY - Historical data shows HIGH ROI
        # Crown Trifari: 78% win rate, 272% avg ROI
        # Jelly Belly: 75% win rate, 228% avg ROI
        # Alfred Philippe: 75% win rate, 309% avg ROI
        # Sweet spot: Under $200 cost
        # ============================================================
        is_trifari = 'trifari' in title
        is_crown = 'crown' in title and is_trifari
        is_jelly_belly = 'jelly belly' in title
        is_philippe = 'philippe' in title or 'phillipe' in title

        if is_jelly_belly and price < 150:
            # HISTORICAL DATA: Jelly Belly under $150 = 75% win rate, 228% avg ROI
            return (f"JELLY BELLY DEAL at ${price:.0f} - Historical 75% win rate, 228% avg ROI!", "BUY")

        if is_philippe and price < 250:
            # HISTORICAL DATA: Alfred Philippe pieces = 309% avg ROI
            return (f"ALFRED PHILIPPE at ${price:.0f} - Historical 309% avg ROI, designer collectible!", "BUY")

        if is_crown and price < 100:
            # Crown Trifari under $100 = strong buy
            return (f"CROWN TRIFARI at ${price:.0f} - Premium vintage mark, 78% win rate!", "BUY")

        if is_trifari and price < 50:
            # Any Trifari under $50 is likely underpriced
            return (f"TRIFARI DEAL at ${price:.0f} - Vintage costume brand, strong collector market", "BUY")

        # Modern fashion brands = instant PASS
        for brand in self.TIER_4:
            if brand in title:
                return (f"MODERN FASHION - '{brand}' brand has no vintage value", "PASS")

        # Mystery/grab bags = PASS
        if "mystery" in title or "grab bag" in title:
            return ("MYSTERY LOT - never buy blind", "PASS")

        # Generic variety/mixed lots = almost no value
        junk_indicators = ["vintage to modern", "vintage to now", "variety", "mixed lot", "assorted",
                          "craft lot", "wearable lot", "resale lot", "junk drawer", "destash",
                          "unsorted", "bulk lot", "random", "wholesale"]
        for indicator in junk_indicators:
            if indicator in title:
                # Earring lots especially have no value
                if "earring" in title:
                    return (f"GENERIC EARRING LOT - '{indicator}' = nearly worthless", "PASS")
                # Other generic lots need very low price
                if price > 20:
                    return (f"GENERIC LOT - '{indicator}' not worth over $20", "PASS")

        # Generic earring lots without designer names = PASS
        if "earring" in title and "lot" in title:
            # Check if any premium designer is mentioned
            has_designer = any(d in title for d in self.TIER_1 + self.TIER_2)
            if not has_designer and price > 15:
                return (f"GENERIC EARRING LOT - no designer names, not worth over $15", "PASS")

        # Costume jewelry lots in general need very low prices to be worth it
        if "lot" in title and "costume" in title:
            has_designer = any(d in title for d in self.TIER_1 + self.TIER_2)
            if not has_designer and price > 25:
                return (f"GENERIC COSTUME LOT - no designer names, not worth over $25", "PASS")

        return (None, None)

    def get_prompt(self) -> str:
        """Get the costume jewelry analysis prompt"""
        return """
=== COSTUME JEWELRY ANALYZER ===

We buy THREE types:
1. TRIFARI - Premium vintage costume brand (our specialty)
2. QUALITY LOTS - High piece count with visible quality indicators
3. SPECIAL ITEMS - Bakelite, quality cameos, rare designers

DEFAULT: RESEARCH - Costume jewelry requires careful visual analysis.

=== TRIFARI IDENTIFICATION ===

TRIFARI MARKS (HOW TO DATE):
| Mark | Era | Value |
| Crown over T | 1940s-1960s | $40-300+ |
| Crown Trifari (c) | 1950s-1968 | $35-200 |
| Trifari (c) | 1960s-1970s | $20-80 |
| Trifari TM | Post-1975 | $15-40 |

VALUABLE TRIFARI COLLECTIONS:
| Collection | Value | Look For |
| Jelly Belly | $100-500+ | Lucite bellies on animals |
| Fruit Salad | $80-300+ | Colored carved glass |
| Sterling Trifari | $50-200+ | WWII era, marked STERLING |

JELLY BELLY VALUES:
| Animal | Value |
| Rooster | $200-400 |
| Fish | $150-350 |
| Duck/Bird | $150-300 |
| Frog/Spider | $300-600+ |

TRIFARI RED FLAGS:
- "Trifari style" = NOT authentic
- "Unsigned but Trifari" = SKIP
- Missing stones = deduct 50%

=== DESIGNER TIERS ===

TIER 1 - PREMIUM ($40-500+):
Trifari, Eisenberg Original, Miriam Haskell, Schreiner, Hobe

TIER 2 - GOOD VALUE ($20-100):
Weiss, Juliana, Coro, Eisenberg Ice, Kramer, Lisner, Vendome, Sherman

TIER 3 - VOLUME ONLY ($5-25):
Monet, Napier, Sarah Coventry, Avon (buy in lots only)

TIER 4 - PASS:
Modern fashion brands (no value)

=== LOT QUALITY SCORING ===

POSITIVE (+points):
| Factor | Points |
| Signed pieces visible | +15 |
| Vintage construction | +10 |
| Rhinestones intact | +10 |
| Brooches present | +10 |
| Aurora borealis stones | +5 |
| Enamel work | +5 |
| Bakelite pieces | +15 |

NEGATIVE (-points):
| Factor | Points |
| Tarnish/green patina | -10 |
| Missing stones | -15 |
| Broken pieces | -10 |
| Cheap chain necklaces | -10 |
| Modern look | -15 |
| Poor photos | -10 |
| Mystery lot | -20 |
| "Variety" or "Assorted" | -25 |
| "Vintage to Modern" mix | -25 |
| Generic earring lot | -30 |
| "Craft lot" or "Destash" | -25 |

=== GENERIC LOTS = WORTHLESS ===
INSTANT PASS if title contains:
- "Vintage to Modern" = random junk mix
- "Variety" or "Assorted" = unsorted leftovers
- "Craft lot" or "Destash" = seller's rejects
- Generic earring lots = $0.25-0.50 per pair MAX
- "Mixed lot" without designer names = junk

These lots sell for $5-15 total regardless of piece count!

LOT DECISION:
| Quality Score | Price/Piece | Decision |
| 30+ | Under $2.00 | BUY |
| 30+ | $2-3.00 | RESEARCH |
| 20-29 | Under $1.50 | BUY |
| 20-29 | $1.50-2.50 | RESEARCH |
| Under 10 | Any | PASS |

=== BAKELITE ===
Genuine vintage Bakelite: $25-150+ per piece
- Red/Cherry: $40-150+
- Apple Juice (transparent): $30-100+
- Butterscotch: $25-80
- "Bakelite style" = NOT Bakelite

=== INSTANT PASS ===
- Modern fashion brands
- Single unsigned pieces
- Price > $60 without premium indicators
- "Mystery" lots
- Quality score under 10

=== INSTANT BUY ===
- Crown Trifari under $40 (good condition)
- Jelly Belly under $100
- Sterling Trifari under $60
- Confirmed Bakelite under $30
- Quality lot (30+ score) under $1.50/piece

=== JSON OUTPUT ===
{
  "Qualify": "Yes"/"No",
  "Recommendation": "BUY"/"PASS"/"RESEARCH",
  "itemtype": "Trifari"/"Lot"/"Cameo"/"Bakelite"/"Designer"/"Other",
  "pieceCount": number as string,
  "pricePerPiece": calculated,
  "designer": specific designer or "Various",
  "designerTier": "1"/"2"/"3"/"4"/"Unknown",
  "hasTrifari": "Yes"/"No"/"Maybe",
  "trifariCollection": "Jelly Belly"/"Crown"/"Standard"/"NA",
  "qualityScore": lot score as number,
  "positiveIndicators": what good you see,
  "negativeIndicators": concerns,
  "estimatedvalue": resale estimate,
  "Profit": expected profit (estimatedvalue minus listing price),
  "confidence": INTEGER 0-100,
  "reasoning": "DETECTION: [what] | QUALITY: [score breakdown] | CALC: value $X - list $Y = profit $Z | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict) -> dict:
        """Validate costume response"""

        def parse_number(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace("$", "").replace(",", "").replace("+", "").strip()
            try:
                return float(s)
            except:
                return 0

        # Ensure quality score under 10 = PASS
        try:
            score = int(response.get("qualityScore", 0))
            if score < 10 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Quality score < 10"
        except:
            pass

        # Quality score under 20 = RESEARCH, not BUY
        try:
            score = int(response.get("qualityScore", 0))
            if score < 20 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Quality score < 20 needs verification"
        except:
            pass

        # Profit must be at least $10 for costume BUY
        profit = parse_number(response.get("Profit", 0))
        if profit < 10 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: Thin margin (${profit:.0f}) for costume"

        # Generic lots (no designer tier 1 or 2) should never be BUY
        designer_tier = str(response.get("designerTier", "Unknown"))
        item_type = str(response.get("itemtype", "")).lower()
        if item_type == "lot" and designer_tier not in ["1", "2"]:
            if response.get("Recommendation") == "BUY":
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Non-designer lots need manual verification"

        # High price per piece = PASS (costume jewelry shouldn't exceed $5/piece for lots)
        try:
            price_per_piece = parse_number(response.get("pricePerPiece", 0))
            if price_per_piece > 5 and item_type == "lot":
                if response.get("Recommendation") == "BUY":
                    response["Recommendation"] = "PASS"
                    response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: ${price_per_piece:.2f}/piece too high for costume lot"
        except:
            pass

        return response
