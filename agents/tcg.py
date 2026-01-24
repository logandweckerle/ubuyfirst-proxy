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

# CGC sells for LESS than PSA - typically 65-75% of PSA prices
CGC_GRADE_MULTIPLIERS = {
    10: 3.5,    # CGC 10 = ~3.5x raw (70% of PSA 10's 5.0x)
    9.5: 2.0,   # CGC 9.5 = ~2.0x raw (less than PSA 9.5)
    9: 1.5,     # CGC 9 = ~1.5x raw
    8.5: 1.1,
    8: 0.9,
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
        CRITICAL: Always extract grade info FIRST for graded cards.
        """
        title = data.get("Title", "").lower()

        # === GRADED CARD DETECTION - ALWAYS CHECK FIRST ===
        # Extract grade info before any PASS checks to ensure we don't miss graded cards
        grade_info = extract_grade_info(title)
        if grade_info["is_graded"]:
            grader = grade_info["grader"]
            grade = grade_info["grade"]
            multiplier = get_grade_multiplier(grader, grade)

            # Store grade info for later enrichment
            data["_grade_info"] = grade_info
            data["_grade_multiplier"] = multiplier

            # Low grades (< 7) - usually not profitable
            if grade < 7:
                return (f"LOW GRADE - {grader} {grade} (below 7 rarely profitable)", "PASS")

            # Detect vintage indicators for graded cards
            vintage_indicators = ["base set", "jungle", "fossil", "team rocket",
                                 "gym heroes", "gym challenge", "neo", "1st edition",
                                 "shadowless", "wotc", "1999", "2000", "2001", "2002"]
            is_vintage = any(vi in title for vi in vintage_indicators)

            # High-value graded cards - route to RESEARCH for price lookup
            # PSA 9+ and BGS 9+ are valuable enough to warrant research
            if grade >= 9:
                return (f"HIGH GRADE {grader} {grade} at ${price:.0f} - route to AI for PriceCharting lookup", None)

            # Vintage graded cards of any grade 7+ - worth researching
            if is_vintage and grade >= 7:
                return (f"VINTAGE GRADED {grader} {grade} at ${price:.0f} - route to AI for valuation", None)

            # Mid-grade (7-8.5) modern cards - still worth checking if price is right
            if price > 50:
                return (f"GRADED {grader} {grade} at ${price:.0f} - route to AI for valuation", None)

            # Low-priced mid-grade - probably not worth it but let AI decide
            if grade >= 8:
                return (f"GRADED {grader} {grade} at ${price:.0f} - needs verification", None)

        # === INSTANT PASS - Low/no value items (ONLY for non-graded) ===

        # Code cards (digital game codes)
        code_keywords = ["ptcgo", "ptcgl", "code card", "tcg code", "online code",
                        "digital code", "redemption code", "tcg live code"]
        for kw in code_keywords:
            if kw in title:
                return (f"CODE CARD - '{kw}' has no resale value", "PASS")

        # Bulk/commons/energy cards - but NOT if graded
        bulk_keywords = ["bulk", "common lot", "commons lot", "energy cards",
                        "energy lot", "trainer lot", "bulk lot", "100 cards",
                        "200 cards", "500 cards", "1000 cards", "random cards",
                        "random lot", "mixed lot", "grab bag", "mystery box"]
        for kw in bulk_keywords:
            if kw in title:
                return (f"BULK/COMMONS - '{kw}' has minimal value", "PASS")

        # Damaged cards - but graded cards with damage are already graded for condition
        damage_keywords = ["damaged", "heavily played", "hp ", " hp", "creased",
                         "water damage", "bent", "torn", "scratched"]
        for kw in damage_keywords:
            if kw in title:
                return (f"DAMAGED - '{kw}' detected", "PASS")

        # Non-English (except Japanese which has collector value)
        foreign_keywords = ["german", "french", "italian", "spanish", "portuguese",
                          "korean", "chinese", "thai", "indonesian"]
        for kw in foreign_keywords:
            if kw in title:
                return (f"FOREIGN LANGUAGE - '{kw}' (non-Japanese = lower demand)", "PASS")

        # Accessories only (not actual cards/products)
        accessory_keywords = ["sleeves only", "binder only", "deck box only",
                            "playmat only", "dice only", "coin only", "pins only",
                            "figure only", "empty tin", "empty box", "tin only"]
        for kw in accessory_keywords:
            if kw in title:
                return (f"ACCESSORY ONLY - '{kw}' (no cards)", "PASS")

        # Wrappers/packaging (no product)
        wrapper_keywords = ["wrapper only", "empty wrapper", "booster wrapper",
                          "pack wrapper", "wrappers lot", "artwork only",
                          "packaging only", "box only"]
        for kw in wrapper_keywords:
            if kw in title:
                return (f"WRAPPER/PACKAGING - '{kw}' (no product)", "PASS")

        # Jumbo/oversized cards (low collector demand)
        jumbo_keywords = ["jumbo card", "oversized card", "promo jumbo", "giant card"]
        for kw in jumbo_keywords:
            if kw in title and "lot" not in title:
                return (f"JUMBO CARD - '{kw}' (low resale value)", "PASS")

        # Dollar store repacks (no value)
        dollar_keywords = ["dollar tree", "dollar general", "fairfield",
                         "mystery power", "walgreens repack"]
        for kw in dollar_keywords:
            if kw in title:
                return (f"DOLLAR STORE REPACK - '{kw}' (negative value)", "PASS")

        # === OPENED/NOT SEALED CHECK ===
        # Not sealed = PASS (but graded cards are OK)
        if not grade_info["is_graded"]:
            open_keywords = ["opened", "loose packs", "resealed", "mystery", "repack",
                           "no packs", "packs removed", "cards only", "opened box"]
            for kw in open_keywords:
                if kw in title:
                    return (f"NOT SEALED - '{kw}' detected", "PASS")

        # === JAPANESE GRADED CARDS FLAG ===
        # Japanese cards have different pricing - flag for RESEARCH in validate_response
        if grade_info["is_graded"]:
            japanese_indicators = ["japanese", "japan", " jp ", " jpn ", "jp version", "japanese version"]
            for jp in japanese_indicators:
                if jp in title:
                    data["_is_japanese"] = True
                    break

        # === PRICE FLOOR CHECKS ===
        # Raw singles under $20 without being graded - minimal margin
        if price < 20 and not grade_info["is_graded"]:
            single_indicators = ["holo", "rare", "ultra rare", "full art", "secret rare",
                               "vmax", "vstar", "ex card", "gx card"]
            is_single = any(si in title for si in single_indicators)
            # Check it's not a sealed product
            sealed_indicators = ["booster box", "etb", "elite trainer", "collection box",
                               "booster pack", "sealed"]
            is_sealed = any(si in title for si in sealed_indicators)
            if is_single and not is_sealed:
                return (f"LOW VALUE SINGLE - ${price:.0f} (margins too thin on raw singles)", "PASS")

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

                # Recalculate profit with listing price - try ALL possible price field names
                listing_price = parse_number(response.get('listing_price', 0))
                if listing_price == 0 and data:
                    # Try ALL possible price field names
                    listing_price = parse_number(
                        data.get('TotalPrice') or
                        data.get('Price') or
                        data.get('CurrentPrice') or
                        data.get('listingPrice') or
                        data.get('total_price') or
                        data.get('_listing_price') or  # Set by analysis route
                        data.get('price') or  # lowercase variants
                        data.get('totalPrice') or
                        0
                    )

                # CRITICAL: Always recalculate profit with PriceCharting data
                if listing_price > 0:
                    actual_profit = pc_buy_target - listing_price
                    response['Profit'] = actual_profit

                    # CRITICAL FIX: If listing >= maxBuy (no margin), force PASS immediately
                    if listing_price >= pc_buy_target and response.get("Recommendation") == "BUY":
                        response["Recommendation"] = "PASS"
                        response["reasoning"] = response.get("reasoning", "") + f" | PRICECHARTING OVERRIDE: Listing ${listing_price:.0f} >= maxBuy ${pc_buy_target:.0f} (profit ${actual_profit:.0f}) = PASS"
                        print(f"[TCG] PC PRICE CHECK: ${listing_price:.0f} >= ${pc_buy_target:.0f} -> PASS")

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

        # Also detect PSA/BGS/CGC from title if AI didn't flag it
        title = ""
        listing_price = 0
        if data:
            title = str(data.get("Title", "")).lower()
            # Try multiple price field names - uBuyFirst uses different keys
            listing_price = parse_number(
                data.get("TotalPrice") or
                data.get("Price") or
                data.get("CurrentPrice") or
                data.get("listingPrice") or
                data.get("total_price") or
                data.get("_listing_price") or  # Set by analysis route
                0
            )
        has_psa_in_title = "psa" in title or "bgs" in title or "cgc" in title
        if has_psa_in_title:
            is_graded = True

        # === CRITICAL: PRICE PROXIMITY CHECK ===
        # If listing price >= maxBuy (70% of market), there's no margin - PASS
        # This catches cards priced AT or NEAR market value
        max_buy = parse_number(response.get("maxBuy", 0))
        if max_buy > 0 and listing_price > 0:
            # Recalculate actual margin from server data
            actual_margin = max_buy - listing_price
            # Update margin in response to be accurate
            response["Profit"] = f"{int(actual_margin):+d}" if actual_margin != 0 else "0"

            if listing_price >= max_buy and response.get("Recommendation") == "BUY":
                response["Recommendation"] = "PASS"
                response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: Listing ${listing_price:.0f} >= maxBuy ${max_buy:.0f} (margin ${actual_margin:.0f}) - PASS"
                print(f"[TCG] PRICE CHECK OVERRIDE: ${listing_price:.0f} >= maxBuy ${max_buy:.0f}, margin ${actual_margin:.0f} -> PASS")

        # === JAPANESE CARDS = RESEARCH ===
        # Japanese cards have different pricing - databases don't price them correctly
        is_japanese = data.get("_is_japanese", False) if data else False
        if not is_japanese:
            japanese_indicators = ["japanese", "japan", " jp ", " jpn ", "jp version"]
            is_japanese = any(jp in title for jp in japanese_indicators)
        if is_japanese and is_graded and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: Japanese card = RESEARCH (pricing differs from English)"

        # === 2025 POKEMON = LIKELY FAKE/UNRELEASED ===
        # Pokemon cards from "2025" are either unreleased or fake - don't auto-buy
        if "2025" in title and "pokemon" in title and response.get("Recommendation") == "BUY":
            response["Recommendation"] = "RESEARCH"
            response["reasoning"] = response.get("reasoning", "") + " | OVERRIDE: 2025 Pokemon = unreleased/suspicious, verify authenticity"

        if is_graded or product_type == "gradedcard":
            grader = response.get("grader")
            grade = parse_number(response.get("grade", 0))
            raw_value = parse_number(response.get("rawValue", 0))

            # Detect grader from title if not set
            if not grader and has_psa_in_title:
                if "psa" in title:
                    grader = "PSA"
                elif "bgs" in title:
                    grader = "BGS"
                elif "cgc" in title:
                    grader = "CGC"

            # CRITICAL: ALL PSA/BGS/CGC cards with BUY = RESEARCH
            # Graded cards are too easy to fake and hard to value without reference data
            has_pc_data = pc_data and pc_data.get('pc_found')
            if grader in ["PSA", "BGS", "CGC"] and response.get("Recommendation") == "BUY":
                if not has_pc_data:
                    response["Recommendation"] = "RESEARCH"
                    response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: {grader} card without PriceCharting data = RESEARCH (verify pricing manually)"
                else:
                    # Even with PC data, PSA 10s should be RESEARCH (high fake risk)
                    if grade and grade >= 10:
                        response["Recommendation"] = "RESEARCH"
                        response["reasoning"] = response.get("reasoning", "") + f" | OVERRIDE: {grader} 10 = RESEARCH (verify slab authenticity)"

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

            # CRITICAL: High-value graded cards should NEVER auto-PASS
            # A $5000 PSA 10 Charizard might be priced below market!
            # Force RESEARCH for expensive graded cards even if AI says PASS
            if listing_price > 500 and response.get("Recommendation") == "PASS":
                response["Recommendation"] = "RESEARCH"
                response["Qualify"] = "Maybe"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: High-value graded card at ${listing_price:.0f} - AI said PASS but verify market value"
                print(f"[TCG] OVERRIDE: PASS->RESEARCH for graded card at ${listing_price:.0f}")

            # Even higher threshold for very expensive cards
            if listing_price > 2000 and response.get("Recommendation") == "PASS":
                response["Recommendation"] = "RESEARCH"
                response["Qualify"] = "Maybe"
                response["reasoning"] = response.get("reasoning", "") + f" | SERVER: Very high-value graded at ${listing_price:.0f} - always verify"

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
