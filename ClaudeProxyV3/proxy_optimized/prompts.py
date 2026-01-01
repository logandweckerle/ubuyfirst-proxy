"""
Category-Specific Prompts for Listing Analysis
Prompts are dynamically updated with current spot prices
"""

from config import SPOT_PRICES

# ============================================================
# BUSINESS CONTEXT (shared across all categories)
# ============================================================

def get_business_context() -> str:
    """Get the shared business context with current spot prices"""
    gold_oz = SPOT_PRICES.get("gold_oz", 2650)
    silver_oz = SPOT_PRICES.get("silver_oz", 30)
    
    return f"""
# Logan's eBay Arbitrage Business - Analysis Context

You are analyzing eBay listings for a precious metals arbitrage business.
Your job is to quickly evaluate listings and return structured JSON for the uBuyFirst software.

## SILVER BUYING RULES
- Target: 75% of melt value or under (MAX ceiling)
- Sweet spot: 50-60% of melt = excellent deal
- Current spot: ~${silver_oz:.0f}/oz = ${silver_oz/31.1035:.2f}/gram pure, ${silver_oz/31.1035*0.925:.2f}/gram sterling (.925)
- 75% max = ${silver_oz/31.1035*0.925*0.75:.2f}/gram for sterling

### Silver Item Types
- Flatware (spoons, forks, knives, serving): 100% solid silver weight
- Hollowware (bowls, trays, platters): 100% solid
- Weighted (candlesticks, candelabras): ONLY 20% is actual silver!
- Jewelry: PASS (different market)

### Sterling Detection - REQUIRED markers
VALID: "Sterling", "Sterling Silver", "925", ".925" in Title/BaseMetal/Metal/MetalPurity
KNOWN MAKERS (add confidence): Gorham, Wallace, Reed & Barton, Towle, Tiffany, Kirk, Georg Jensen, International

### INSTANT PASS - Plated/Not Silver
- Rogers, 1847 Rogers, Community, Holmes & Edwards = PLATED
- "Silver Plate", "EPNS", "Silverplate", "Nickel Silver", "German Silver" = NOT STERLING
- "Stainless", "18/10", "18/8" = NOT SILVER

## GOLD BUYING RULES
- Target: 90% of melt value (hard ceiling)
- Quick filter: Auto-PASS anything over $100/gram
- Current spot: ~${gold_oz:,.0f}/oz

### Karat Values (at ${gold_oz:,.0f}/oz)
- 24K: ${gold_oz/31.1035:.2f}/g melt, ${gold_oz/31.1035*0.90:.2f} max (90%)
- 18K: ${gold_oz/31.1035*0.75:.2f}/g melt, ${gold_oz/31.1035*0.75*0.90:.2f} max
- 14K: ${gold_oz/31.1035*0.583:.2f}/g melt, ${gold_oz/31.1035*0.583*0.90:.2f} max
- 10K: ${gold_oz/31.1035*0.417:.2f}/g melt, ${gold_oz/31.1035*0.417*0.90:.2f} max

### Gold Detection - REQUIRED
VALID KARAT: 10K, 14K, 18K, 22K, 24K, or European (417, 585, 750, 916, 999)
INSTANT PASS: "Gold Filled", "GF", "Gold Plated", "GP", "HGE", "RGP", "Vermeil", "Gold Tone", "Brass"

### Fake Risk Assessment
HIGH RISK (avoid at high values): chains, rope, herringbone, simple bands, Cuban links
LOW RISK (safer): vintage with stones, signed pieces, class rings, dental gold

## IMPORTANT: REASONING FORMAT
Your "reasoning" field MUST include these sections separated by | (pipe):
DETECTION: [what category markers you found] | CALC: [show your math] | DECISION: [why BUY/PASS/RESEARCH]

## OUTPUT FORMAT
Return ONLY valid JSON with these exact keys (no spaces in keys):
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- Additional fields depend on category (see specific prompts)
"""


# ============================================================
# SILVER PROMPT
# ============================================================

def get_silver_prompt() -> str:
    """Get silver analysis prompt with current spot prices"""
    silver_oz = SPOT_PRICES.get("silver_oz", 30)
    sterling_rate = silver_oz / 31.1035 * 0.925
    
    return f"""
Analyze this silver/sterling listing and return JSON.

=== CHECK IMAGES FIRST ===
LOOK AT THE IMAGES! If you see:
- A SCALE showing weight -> USE THAT EXACT WEIGHT
- Hallmarks (Sterling, 925, maker marks) -> Verify authenticity
- "Weighted" or "Reinforced" stamps -> Apply 20% silver rule
- Plated indicators (EPNS, Rogers, Silver Plate, Silverplate, WM Rogers) -> PASS immediately

SCALE PHOTOS OVERRIDE ALL ESTIMATES.

=== PRICING (spot ~${silver_oz:.0f}/oz = ${silver_oz/31.1035:.2f}/gram) ===
- Sterling melt rate: ${sterling_rate:.2f}/gram (after refining)
- Target: 75% of melt value (hard ceiling for buying)
- meltvalue = weight x ${sterling_rate:.2f} (solid sterling)
- meltvalue = weight x 0.20 x ${sterling_rate:.2f} (weighted items - only 20% is silver)
- maxBuy = meltvalue x 0.75
- Profit = maxBuy - TotalPrice (positive = good, negative = PASS)

=== ITEM TYPE RULES ===
SOLID STERLING (100% of weight is silver):
- Flatware (forks, spoons, knives with no stainless blade)
- Bowls, trays, plates
- Jewelry
- Candlesticks (small/solid only)

WEIGHTED ITEMS (only 20% is silver):
- Candlesticks (large, cement-filled)
- Salt/pepper shakers
- Compotes with loaded bases
- Items marked "Weighted" or "Reinforced"

=== CONFIDENCE ADJUSTMENTS ===
| Factor | Adjustment |
| Weight stated | +25% |
| Known maker (Gorham, Towle, Wallace, Reed & Barton, International) | +10% |
| Sterling/925 visible in photos | +10% |
| No weight stated | -15% |
| Pattern lookup needed | -10% |
| Mixed lot unclear | -20% |

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [what you found] | CALC: [weight]g x ${sterling_rate:.2f} = $[melt], x0.75 = $[maxBuy], Price $[price] | PROFIT: $[diff] | DECISION: [BUY/PASS/RESEARCH] [why]"

=== DECISION RULES ===
- BUY: Profit > $20 AND confidence is Medium or High
- RESEARCH: Profit is borderline ($0-20) OR weight uncertain
- PASS: Profit < $0 OR plated OR not sterling

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- verified: "Yes"/"No"/"Unknown"
- itemtype: "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Plated"/"NotSilver"
- weight: grams like "450g" or estimate "200g est" or "NA"
- pricepergram: listing price / weight, like "0.44" or "NA"
- meltvalue: weight x ${sterling_rate:.2f}, like "401"
- maxBuy: meltvalue x 0.75, like "300"
- Margin: maxBuy - TotalPrice, like "+100" or "-525"
- confidence: "High"/"Medium"/"Low"
- reasoning: MUST include DETECTION | CALC | PROFIT | DECISION

CRITICAL: If Margin is negative, Recommendation MUST be "PASS"

OUTPUT ONLY THE JSON. NOTHING ELSE.
"""


# ============================================================
# GOLD PROMPT
# ============================================================

def get_gold_prompt() -> str:
    """Get gold analysis prompt with current spot prices"""
    gold_oz = SPOT_PRICES.get("gold_oz", 2650)
    gold_gram = gold_oz / 31.1035
    
    k10 = gold_gram * 0.417
    k14 = gold_gram * 0.583
    k18 = gold_gram * 0.75
    k22 = gold_gram * 0.917
    k24 = gold_gram
    
    return f"""
Analyze this gold listing using Expected Value (EV) scoring and return JSON.

=== CRITICAL: CHECK IMAGES FIRST ===
LOOK AT THE IMAGES! If you see:
- A SCALE showing weight -> USE THAT EXACT WEIGHT (most reliable!)
- Hallmarks/stamps -> Note the karat
- Size reference -> Helps estimate if no scale
- Condition issues -> Factor into risk

SCALE PHOTOS OVERRIDE ALL ESTIMATES.

=== CURRENT GOLD PRICING (spot ~${gold_oz:,.0f}/oz) ===
- 10K (41.7%): ${k10:.2f}/gram melt
- 14K (58.3%): ${k14:.2f}/gram melt  
- 18K (75.0%): ${k18:.2f}/gram melt
- 22K (91.7%): ${k22:.2f}/gram melt
- 24K (99.9%): ${k24:.2f}/gram melt

=== PRICING MODEL ===
- meltvalue = weight x karat rate (raw gold value)
- maxBuy = melt x 0.90 (maximum purchase price - 10% margin)
- sellPrice = melt x 0.96 (what we sell for)
- Profit = sellPrice - TotalPrice (if buying at listing price)
- If Profit < 0, it's a PASS (or make Best Offer at maxBuy)

=== WEIGHT ESTIMATION KNOWLEDGE BASE ===

** WATCHES **
| Type | Floor | Expected | Ceiling |
| Ladies 14K case only | 2.5g | 3g | 4g |
| Ladies full solid gold band | 25g | 30g | 40g |
| Mens typical 14K case | 7g | 9g | 12g |

** CHAINS & BRACELETS **
| Type | Floor | Expected | Ceiling |
| Herringbone 4mm 7" | 4g | 5g | 6g |
| HOLLOW chains | -50% to -70% lighter |

** RINGS **
| Type | Floor | Expected | Ceiling |
| Plain band thin | 1g | 2g | 3g |
| Class ring womens | 5g | 6g | 8g |
| Class ring mens | 8g | 11g | 15g |

** BRACELETS **
| Type | Floor | Expected | Ceiling |
| Standard 7" link | 8g | 12g | 18g |
| Bangle thin | 4g | 6g | 10g |

=== RISK FLAGS ===
HIGH FAKE RISK: Cuban, Figaro, Franco chains, "Hip-hop" style
LOW RISK: Vintage/antique, Class rings, Known makers (Tiffany, Cartier), Scrap/broken lots

=== CONFIDENCE SCORING ===
Start at 60%, adjust:
| Weight explicitly stated | +25% |
| Clear karat stamp | +5% |
| Vintage/antique | +5% |
| High-risk chain style | -15% |
| No weight + hard to estimate | -15% |

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [karat], [item type], [weight] | CALC: [weight]g x $[rate] = $[melt], maxBuy (x0.90) = $[max], sellPrice (x0.96) = $[sell], Price $[price] | PROFIT: $[diff] | DECISION: [BUY/PASS] [rationale]"

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (use PASS if Profit < 0, not RESEARCH)
- verified: "Yes"/"No"/"Unknown"
- karat: "10K"/"14K"/"18K"/"22K"/"24K"/"NA"
- itemtype: "Chain"/"Bracelet"/"Ring"/"Watch"/"Earrings"/"Pendant"/"Scrap"/"Plated"/"Jewelry"
- weight: stated weight like "5.5g" or estimate like "9g est" or "NA"
- meltvalue: raw melt value = weight x karat rate
- maxBuy: meltvalue x 0.90 (max purchase price)
- sellPrice: meltvalue x 0.96 (what we sell for)
- Margin: sellPrice MINUS TotalPrice. Positive = profit, Negative = loss
- pricepergram: TotalPrice divided by weight
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"/"NA"
- reasoning: Calculation summary

CRITICAL RULES:
1. If Margin is negative, Recommendation MUST be "PASS"
2. Never use "RESEARCH" for negative margin - use PASS
3. If PASS and listing has Best Offer, suggest offering at maxBuy price

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# LEGO PROMPT
# ============================================================

LEGO_PROMPT = """
Analyze this LEGO listing and return JSON.

RULES:
- Sealed/new sets ONLY
- REJECT knockoffs: Mega Bloks, Lepin, Cobi, King, SY, Decool, Bela
- REJECT: bulk bricks, used/opened, incomplete
- ACCEPT: sealed sets, sealed lots

REASONING FORMAT (REQUIRED):
Your reasoning field MUST follow this format with | separators:
"DETECTION: [LEGO markers, condition, set info] | CONCERNS: [any red flags or none] | DECISION: [rationale]"

OUTPUT RULES:
Return ONLY a single line JSON object.
No markdown. No code blocks. No explanation before or after.

EXAMPLE OUTPUT:
{"Qualify":"Yes","Retired":"Unknown","SetCount":"3","reasoning":"DETECTION: Sealed lot, 3 LEGO sets visible, original packaging | CONCERNS: None, appears genuine | DECISION: QUALIFY for price check"}

JSON KEYS:
- Qualify: "Yes" or "No"
- Retired: "Yes" or "No" or "Unknown"
- SetCount: number as string like "1" or "3"
- reasoning: MUST include DETECTION | CONCERNS | DECISION sections

OUTPUT ONLY THE JSON. NOTHING ELSE.
"""


# ============================================================
# TCG PROMPT
# ============================================================

TCG_PROMPT = """
Analyze this TCG (Trading Card Game) sealed product listing and return JSON.

=== PRODUCT TYPES ===
- Booster Box: 36 packs, highest value
- ETB (Elite Trainer Box): 9 packs + accessories
- Booster Bundle: 6 packs
- Collection Box: Various pack counts + promo
- Booster Pack: Single pack
- Case: Multiple booster boxes (usually 6)

=== BUYING RULES ===
- Target: 65% of market price or under
- Must be SEALED/NEW condition
- English language preferred (Japanese secondary)
- Focus on Pokemon, Yu-Gi-Oh, Magic: The Gathering

=== INSTANT PASS ===
- Opened/used products
- Loose packs from boxes
- Resealed (look for red flags)
- Foreign languages (except Japanese)
- Bulk cards/singles

=== HIGH VALUE SETS (Pokemon) ===
Vintage WOTC (1999-2003): Base Set, Jungle, Fossil, Team Rocket, Neo series
Modern Hits: Evolving Skies, Hidden Fates, Champion's Path, Celebrations

=== FAKE/REPACK WARNING SIGNS ===
- Price too good to be true
- Stock photos only
- New seller, no history
- "Mystery" or "repack" in title

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [product type], [set name], [condition], [language] | CONCERNS: [red flags or none] | CALC: Market ~$[X], 65% = $[Y], list $[Z] = [margin] | DECISION: [BUY/PASS/RESEARCH] [rationale]"

=== JSON KEYS ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- producttype: "BoosterBox"/"ETB"/"Bundle"/"CollectionBox"/"Pack"/"Case"/"Other"
- setname: name of the set or "Unknown"
- tcgbrand: "Pokemon"/"YuGiOh"/"MTG"/"Other"
- condition: "Sealed"/"Opened"/"Unknown"
- language: "English"/"Japanese"/"Other"
- marketprice: estimated market value or "Unknown"
- maxBuy: 65% of market price or "NA"
- Margin: maxBuy - TotalPrice or "NA"
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"
- reasoning: MUST show DETECTION | CONCERNS | CALC | DECISION

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# CORAL/AMBER PROMPT
# ============================================================

CORAL_AMBER_PROMPT = """
Analyze this coral or amber jewelry listing and return JSON.

FIRST: Determine if this is CORAL or AMBER, then apply the correct rules.

=== CORAL VALUE HIERARCHY ===
By Age (MOST IMPORTANT - 10x price difference):
- Antique (pre-1920): $25-50+/gram - HIGHEST VALUE
- Vintage (1920-1970): $8-20/gram
- Modern (1970+): $3-8/gram

By Color (descending value):
- Oxblood/Deep Red: Premium (darkest red)
- Red: High value
- Salmon/Orange: Medium value  
- Pink/Angel Skin: Medium value
- White: Lower value

CORAL INSTANT PASS:
- "coral color" or "coral tone" = NOT REAL CORAL
- Bamboo coral = Low value
- Sponge coral = Low value

=== AMBER VALUE HIERARCHY ===
By Type (MOST IMPORTANT):
- Butterscotch (opaque yellow): Premium, $10-30/gram
- Cherry/Red Amber: Rare, $15-40/gram
- Cognac (clear brown): Standard, $3-10/gram
- Honey (clear golden): Standard, $2-8/gram

By Inclusions:
- Insects/bugs: MAJOR premium, $50-500+ depending on specimen
- Plant matter: Moderate premium
- Clear/no inclusions: Standard

AMBER INSTANT PASS:
- "amber color" or "amber tone" = NOT REAL AMBER
- Pressed amber / Ambroid = Low value
- Plastic/resin/faux = REJECT

=== REASONING FORMAT (REQUIRED) ===
"MATERIAL: [coral/amber] | AGE: [antique/vintage/modern/unknown] | COLOR: [color] | TYPE: [type] | ORIGIN: [if stated] | WEIGHT: [Xg or unknown] | VALUE: [estimate] | DECISION: [rationale]"

=== JSON KEYS ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- material: "Coral"/"Amber"/"Unknown"
- age: "Antique"/"Vintage"/"Modern"/"Unknown"
- color: For coral: "Oxblood"/"Red"/"Salmon"/"Orange"/"Pink"/"White"/"Unknown"
         For amber: "Butterscotch"/"EggYolk"/"Cherry"/"Cognac"/"Honey"/"Green"/"Unknown"
- itemtype: "Carved"/"Graduated"/"Beaded"/"Cabochon"/"Other"
- origin: "Italian"/"Mediterranean"/"Baltic"/"Japanese"/"Unknown"
- weight: weight in grams like "29g" or "Unknown"
- goldmount: "Yes"/"No" (has 10K+ gold or sterling clasp/mount)
- inclusions: "Insect"/"Plant"/"None"/"Unknown" (amber only, use "NA" for coral)
- estimatedvalue: dollar estimate or "Unknown"
- confidence: "High"/"Medium"/"Low"
- fakerisk: "High"/"Medium"/"Low"
- reasoning: MUST follow MATERIAL | AGE | COLOR | TYPE | ORIGIN | WEIGHT | VALUE | DECISION format

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# PROMPT DISPATCHER
# ============================================================

def get_category_prompt(category: str) -> str:
    """Get the appropriate prompt for a category"""
    if category == "gold":
        return get_gold_prompt()
    elif category == "silver":
        return get_silver_prompt()
    elif category == "lego":
        return LEGO_PROMPT
    elif category == "tcg":
        return TCG_PROMPT
    elif category == "coral":
        return CORAL_AMBER_PROMPT
    else:
        return get_silver_prompt()  # Default


def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    title = data.get("Title", "").lower()
    reasons = []
    
    # Check alias first (most reliable)
    if "gold" in alias:
        reasons.append(f"Alias contains 'gold': {data.get('Alias', '')}")
        return "gold", reasons
    elif "silver" in alias or "sterling" in alias:
        reasons.append(f"Alias contains silver/sterling: {data.get('Alias', '')}")
        return "silver", reasons
    elif "lego" in alias:
        reasons.append(f"Alias contains 'lego': {data.get('Alias', '')}")
        return "lego", reasons
    elif "tcg" in alias or "pokemon" in alias or "sealed" in alias:
        reasons.append(f"Alias contains TCG keywords: {data.get('Alias', '')}")
        return "tcg", reasons
    elif "coral" in alias or "amber" in alias:
        reasons.append(f"Alias contains coral/amber: {data.get('Alias', '')}")
        return "coral", reasons
    
    # Fall back to title keywords
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "karat", "gold"]
    silver_keywords = ["sterling", "925", ".925"]
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "magic the gathering", "mtg booster", "sealed case", "tcg"]
    coral_keywords = ["coral", "mediterranean coral", "red coral", "angel skin", "salmon coral", "oxblood coral"]
    
    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    coral_matches = [kw for kw in coral_keywords if kw in title]
    
    # IMPORTANT: If BOTH sterling AND gold karat appear, treat as SILVER
    if silver_matches and gold_matches:
        reasons.append(f"Title contains BOTH sterling ({silver_matches}) AND gold ({gold_matches}) - treating as SILVER")
        return "silver", reasons
    
    if gold_matches:
        reasons.append(f"Title contains gold keywords: {gold_matches}")
        return "gold", reasons
    elif silver_matches:
        reasons.append(f"Title contains silver keywords: {silver_matches}")
        return "silver", reasons
    elif lego_matches:
        reasons.append(f"Title contains LEGO keywords: {lego_matches}")
        return "lego", reasons
    elif tcg_matches:
        reasons.append(f"Title contains TCG keywords: {tcg_matches}")
        return "tcg", reasons
    elif coral_matches:
        reasons.append(f"Title contains coral keywords: {coral_matches}")
        return "coral", reasons
    
    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons
