"""
TCG Agent - Handles Trading Card Game sealed product AND graded card analysis

Now integrates with PriceCharting API for graded card price lookups.
"""

import re
from .base import BaseAgent

# Import PriceCharting graded card functions
try:
    from pricecharting_db import lookup_graded_card, extract_grade_info as pc_extract_grade_info, get_grade_multiplier as pc_get_grade_multiplier
    PRICECHARTING_AVAILABLE = True
except ImportError:
    PRICECHARTING_AVAILABLE = False
    print("[TCG] Warning: pricecharting_db not available for graded card lookups")


# PSA Grade Multipliers (approximate - varies by card rarity/desirability)
# These are multipliers applied to raw card prices
PSA_GRADE_MULTIPLIERS = {
    10: 5.0,    # PSA 10 = ~5x raw (can be 10-20x for vintage chase cards)
    9: 2.0,     # PSA 9 = ~2x raw
    8: 1.3,     # PSA 8 = ~1.3x raw
    7: 1.0,     # PSA 7 = ~raw price
    6: 0.8,     # PSA 6 and below often less than raw
    5: 0.6,
}

# BGS is slightly different - 9.5 is common high grade
BGS_GRADE_MULTIPLIERS = {
    10: 8.0,    # BGS 10 (Black Label) = very rare, huge premium
    9.5: 3.0,   # BGS 9.5 = ~3x raw (common "gem mint")
    9: 1.8,     # BGS 9 = ~1.8x raw
    8.5: 1.3,
    8: 1.1,
}

# CGC similar to PSA
CGC_GRADE_MULTIPLIERS = {
    10: 4.0,    # CGC 10 = ~4x raw (less premium than PSA)
    9.5: 2.5,   # CGC 9.5 = ~2.5x raw
    9: 1.8,
    8.5: 1.2,
    8: 1.0,
}


def extract_grade_info(title: str) -> dict:
    """
    Extract grading company and grade from title.
    Returns dict with: grader, grade, is_graded
    """
    title_lower = title.lower()
    result = {"grader": None, "grade": None, "is_graded": False}

    # PSA patterns: "PSA 10", "PSA10", "PSA-10"
    psa_match = re.search(r'\bpsa[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if psa_match:
        result["grader"] = "PSA"
        result["grade"] = float(psa_match.group(1))
        result["is_graded"] = True
        return result

    # BGS patterns: "BGS 10", "BGS 9.5", "BGS-9.5", "Beckett 10"
    bgs_match = re.search(r'\b(?:bgs|beckett)[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if bgs_match:
        result["grader"] = "BGS"
        result["grade"] = float(bgs_match.group(1))
        result["is_graded"] = True
        return result

    # CGC patterns: "CGC 10", "CGC 9.5"
    cgc_match = re.search(r'\bcgc[\s\-]?(\d+(?:\.\d)?)\b', title_lower)
    if cgc_match:
        result["grader"] = "CGC"
        result["grade"] = float(cgc_match.group(1))
        result["is_graded"] = True
        return result

    return result


def get_grade_multiplier(grader: str, grade: float) -> float:
    """Get the price multiplier for a given grade."""
    if grader == "PSA":
        # Find closest grade
        for g in sorted(PSA_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return PSA_GRADE_MULTIPLIERS[g]
        return 0.5  # Below PSA 5
    elif grader == "BGS":
        for g in sorted(BGS_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return BGS_GRADE_MULTIPLIERS[g]
        return 0.5
    elif grader == "CGC":
        for g in sorted(CGC_GRADE_MULTIPLIERS.keys(), reverse=True):
            if grade >= g:
                return CGC_GRADE_MULTIPLIERS[g]
        return 0.5
    return 1.0  # Unknown grader


class TCGAgent(BaseAgent):
    """Agent for TCG sealed product and graded card analysis"""

    category_name = "tcg"

    def enrich_graded_data(self, data: dict, price: float) -> dict:
        """
        Enrich listing data with PriceCharting graded card lookup.

        This should be called from main.py before AI analysis for graded cards.
        Adds PriceCharting data to the data dict for use in prompts and validation.

        Returns:
            dict with keys: pc_found, pc_card_name, pc_raw_price, pc_graded_price,
                           pc_market_price, pc_buy_target, pc_margin, pc_confidence
        """
        result = {
            'pc_found': False,
            'pc_error': None
        }

        if not PRICECHARTING_AVAILABLE:
            result['pc_error'] = 'PriceCharting not available'
            return result

        title = data.get("Title", "")

        # Check if this is a graded card
        grade_info = extract_grade_info(title)
        if not grade_info["is_graded"]:
            result['pc_error'] = 'Not a graded card'
            return result

        # Call PriceCharting lookup
        try:
            pc_result = lookup_graded_card(title, price)

            if pc_result.get('found'):
                result['pc_found'] = True
                result['pc_card_name'] = pc_result.get('card_name')
                result['pc_set_name'] = pc_result.get('set_name')
                result['pc_raw_price'] = pc_result.get('raw_price')
                result['pc_graded_price'] = pc_result.get('graded_price')
                result['pc_market_price'] = pc_result.get('market_price')
                result['pc_buy_target'] = pc_result.get('buy_target')
                result['pc_margin'] = pc_result.get('margin')
                result['pc_confidence'] = pc_result.get('confidence')
                result['pc_multiplier'] = pc_result.get('multiplier')
                result['pc_grader'] = pc_result.get('grader')
                result['pc_grade'] = pc_result.get('grade')
                result['pc_source'] = pc_result.get('source')

                # Store in data for prompt enhancement
                data['_pc_data'] = result

                print(f"[TCG] PriceCharting enriched: {result['pc_card_name']} @ ${result['pc_market_price']:.2f}")
            else:
                result['pc_error'] = pc_result.get('error', 'Unknown error')
                print(f"[TCG] PriceCharting lookup failed: {result['pc_error']}")

        except Exception as e:
            result['pc_error'] = str(e)
            print(f"[TCG] PriceCharting error: {e}")

        return result

    def quick_pass(self, data: dict, price: float) -> tuple:
        """
        Quick filtering for TCG products.
        """
        title = data.get("Title", "").lower()

        # Not sealed = PASS (but graded cards are OK)
        grade_info = extract_grade_info(title)
        if not grade_info["is_graded"]:
            open_keywords = ["opened", "loose packs", "resealed", "mystery", "repack"]
            for kw in open_keywords:
                if kw in title:
                    return (f"NOT SEALED - '{kw}' detected", "PASS")

        # For graded cards, detect and add context
        if grade_info["is_graded"]:
            grader = grade_info["grader"]
            grade = grade_info["grade"]
            multiplier = get_grade_multiplier(grader, grade)

            # Low grades often not worth it
            if grade < 7:
                return (f"LOW GRADE - {grader} {grade} (below 7 rarely profitable)", "PASS")

            # Store grade info for prompt enhancement
            data["_grade_info"] = grade_info
            data["_grade_multiplier"] = multiplier

        return (None, None)

    def get_prompt(self) -> str:
        """Get the TCG analysis prompt"""
        return """
=== TCG ANALYZER - SEALED PRODUCTS & GRADED CARDS ===

We buy SEALED TCG products AND GRADED CARDS to resell. Target: 70% of market price.
PRIORITY: Vintage/WOTC, high-value items, and PSA/BGS graded cards

=== GRADED CARD ANALYSIS (PSA/BGS/CGC) ===

GRADE MULTIPLIERS (applied to raw card value):
| Grade | PSA | BGS | CGC |
|-------|-----|-----|-----|
| 10 | 5x | 8x (Black Label) | 4x |
| 9.5 | - | 3x | 2.5x |
| 9 | 2x | 1.8x | 1.8x |
| 8 | 1.3x | 1.1x | 1x |
| 7 | 1x | 0.9x | 0.9x |
| <7 | PASS | PASS | PASS |

GRADED CARD PRICING:
1. Identify the card (Pokemon, set, card number/name)
2. Estimate RAW card value (use PriceCharting knowledge)
3. Apply grade multiplier: gradedValue = rawValue x multiplier
4. maxBuy = gradedValue x 0.70

EXAMPLE: PSA 10 Base Set Charizard
- Raw Charizard ~$300-400
- PSA 10 multiplier = 5x
- Graded value = $350 x 5 = $1,750
- maxBuy = $1,750 x 0.70 = $1,225

HIGH-VALUE GRADED CARDS (PSA 10):
| Card | Raw | PSA 10 Est |
| Base Set Charizard | $350 | $1,500-2,500 |
| Base Set Blastoise | $80 | $400-600 |
| Base Set Venusaur | $60 | $300-500 |
| 1st Ed Charizard | $5,000+ | $50,000+ |
| Gold Star cards | $200-500 | $1,000-3,000 |
| Shining cards | $100-200 | $500-1,500 |
| Pikachu Illustrator | N/A | $500,000+ |

GRADED CARD RED FLAGS:
- Price too good for grade = likely fake slab
- Stock photo of slab = verify cert number
- New seller + high value graded = RESEARCH
- Cert number not visible = RESEARCH
- PSA 10 vintage under market = RESEARCH

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
  "ProductType": "BoosterBox"/"ETB"/"Bundle"/"CollectionBox"/"Pack"/"Case"/"GradedCard",
  "SetName": "Evolving Skies" or "Base Set" for cards,
  "isVintage": "Yes"/"No" (WOTC era or pre-2010),
  "ItemCount": number of items,
  "lotItems": ["Product 1", "Product 2"] (if lot - list each product with set name),

  // GRADED CARD FIELDS (include if ProductType = "GradedCard"):
  "isGraded": "Yes"/"No",
  "grader": "PSA"/"BGS"/"CGC"/null,
  "grade": 10/9.5/9/8/etc or null,
  "cardName": "Charizard" or card name,
  "cardNumber": "4/102" or card number if visible,
  "rawValue": estimated raw card value,
  "gradeMultiplier": multiplier applied (e.g., 5 for PSA 10),

  "marketprice": estimated value (for graded = rawValue x multiplier),
  "maxBuy": 70% of market,
  "Profit": maxBuy minus listing,
  "confidence": INTEGER 0-100,
  "fakerisk": "High"/"Medium"/"Low",
  "reasoning": "DETECTION: [product/card, set, grade] | GRADED: [grader grade, multiplier] | CALC: Raw $X x Yxmult = $Z, 70% = $maxBuy | DECISION: [why]"
}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""

    def validate_response(self, response: dict, data: dict = None) -> dict:
        """
        Validate TCG response.

        If PriceCharting data is available (from enrich_graded_data), use it to
        verify/override AI pricing for graded cards.
        """

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

        # === PRICECHARTING OVERRIDE FOR GRADED CARDS ===
        # If we have PriceCharting data, use it instead of AI estimates
        pc_data = None
        if data:
            pc_data = data.get('_pc_data')

        if pc_data and pc_data.get('pc_found'):
            pc_market = pc_data.get('pc_market_price', 0)
            pc_buy_target = pc_data.get('pc_buy_target', 0)
            pc_margin = pc_data.get('pc_margin', 0)
            ai_market = parse_number(response.get('marketprice', 0))

            # Override AI pricing with PriceCharting data
            if pc_market > 0:
                response['marketprice'] = pc_market
                response['maxBuy'] = pc_buy_target
                response['pc_source'] = pc_data.get('pc_source', 'pricecharting')
                response['pc_card_name'] = pc_data.get('pc_card_name')
                response['rawValue'] = pc_data.get('pc_raw_price', 0)
                response['gradeMultiplier'] = pc_data.get('pc_multiplier', 1)

                # Recalculate profit with listing price
                listing_price = parse_number(response.get('listing_price', 0))
                if listing_price == 0 and data:
                    # Try to get from data
                    listing_price = parse_number(data.get('TotalPrice', data.get('Price', 0)))

                if listing_price > 0:
                    response['Profit'] = pc_buy_target - listing_price

                # Log the override
                override_note = f" | PRICECHARTING: {pc_data.get('pc_card_name')} @ ${pc_market:.0f} (raw ${pc_data.get('pc_raw_price', 0):.0f} x {pc_data.get('pc_multiplier', 1)}x)"
                response['reasoning'] = response.get('reasoning', '') + override_note

                # Adjust confidence based on PriceCharting source
                if pc_data.get('pc_confidence') == 'High':
                    response['confidence'] = max(int(response.get('confidence', 50)), 70)
                elif pc_data.get('pc_confidence') == 'Medium':
                    response['confidence'] = max(int(response.get('confidence', 50)), 55)

                print(f"[TCG] PriceCharting override: AI ${ai_market:.0f} -> PC ${pc_market:.0f}")

        # Check both Margin and Profit fields (for compatibility)
        profit = parse_number(response.get("Profit", response.get("Margin", "0")))

        # Ensure negative profit = PASS
        if profit < 0 and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "PASS"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Negative profit = PASS"

        # High fake risk + BUY = RESEARCH (especially important for vintage and graded)
        if response.get("fakerisk") == "High" and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High fake risk = RESEARCH"

        # === GRADED CARD VALIDATION ===
        is_graded = str(response.get("isGraded", "No")).lower() == "yes"
        product_type = str(response.get("ProductType", "")).lower()

        if is_graded or product_type == "gradedcard":
            grader = response.get("grader")
            grade = parse_number(response.get("grade", 0))
            raw_value = parse_number(response.get("rawValue", 0))

            # Validate grade multiplier was applied correctly
            if grader and grade and raw_value > 0:
                expected_multiplier = get_grade_multiplier(grader, grade)
                market_price = parse_number(response.get("marketprice", 0))
                expected_market = raw_value * expected_multiplier

                # If AI's market price is way off from expected, flag it
                if market_price > 0 and abs(market_price - expected_market) / expected_market > 0.5:
                    response["reasoning"] = response.get("reasoning", "") + f" | NOTE: Market ${market_price:.0f} vs expected ${expected_market:.0f} (raw ${raw_value:.0f} x {expected_multiplier}x)"

            # High-value graded cards (>$500) should be RESEARCH for verification
            market_price = parse_number(response.get("marketprice", 0))
            if market_price > 500 and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "RESEARCH"
                response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: High-value graded card = RESEARCH (verify authenticity)"

            # PSA 10 vintage with BUY = always RESEARCH (too easy to fake)
            if grader == "PSA" and grade == 10:
                is_vintage = str(response.get("isVintage", "No")).lower() == "yes"
                if is_vintage and response.get("Recommendation") == "BUY":
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: PSA 10 vintage = RESEARCH (verify cert)"

        # Non-vintage (current retail) + BUY = slightly lower confidence (was too aggressive)
        is_vintage = str(response.get("isVintage", "No")).lower()
        if is_vintage == "no" and response.get("Recommendation") == "BUY" and not is_graded:
            try:
                confidence = int(response.get("confidence", 50))
                if confidence > 75:
                    response["confidence"] = 75  # Cap at 75 for current retail (was 60)
                    response["reasoning"] = response.get("reasoning", "") + " | NOTE: Current retail = capped confidence"
            except:
                pass

        # Price floor check: under $60 for non-vintage non-graded = RESEARCH
        market_price = parse_number(response.get("marketprice", 0))
        if market_price < 60 and is_vintage != "yes" and not is_graded and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Very low value = RESEARCH"

        return response
