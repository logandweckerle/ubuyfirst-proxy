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

You are analyzing eBay listings for a precious metals SCRAP/MELT arbitrage business.
We buy gold and silver to MELT for scrap value, not to resell as jewelry.

## CORE PRINCIPLE: SCRAP VALUE ONLY
- DIAMONDS = $0 (we cannot sell them, only the metal matters)
- GEMSTONES = $0 (deduct their weight, they add no value)
- DESIGNER NAMES = $0 (Tiffany, Cartier = same as generic, we're melting it)
- SINGLE EARRINGS = PASS (no resale market)

If the listing price only makes sense because of stones/designer/collectible value,
and the METAL ALONE doesn't justify the price = PASS

## GOLD BUYING RULES (Scrap Only)
- Target: 90% of melt value (hard ceiling)
- Quick filter: Auto-PASS anything over $100/gram of gold
- Current spot: ~${gold_oz:,.0f}/oz
- Diamonds/gemstones = $0 added value (just deduct weight)

### Karat Rates (at ${gold_oz:,.0f}/oz)
- 24K: ${gold_oz/31.1035:.2f}/g, max buy ${gold_oz/31.1035*0.90:.2f}
- 18K: ${gold_oz/31.1035*0.75:.2f}/g, max buy ${gold_oz/31.1035*0.75*0.90:.2f}
- 14K: ${gold_oz/31.1035*0.583:.2f}/g, max buy ${gold_oz/31.1035*0.583*0.90:.2f}
- 10K: ${gold_oz/31.1035*0.417:.2f}/g, max buy ${gold_oz/31.1035*0.417*0.90:.2f}

### Gold INSTANT PASS
- Single earring (worthless)
- Diamond-focused jewelry (value in stones, not gold)
- "Gold Filled", "GF", "Gold Plated", "GP", "HGE", "RGP", "Vermeil", "Gold Tone"
- Price > $100/gram of actual gold weight

## SILVER BUYING RULES
- Target: 75% of melt value or under (MAX ceiling)
- Sweet spot: 50-60% of melt = excellent deal
- Current spot: ~${silver_oz:.0f}/oz = ${silver_oz/31.1035:.2f}/gram pure, ${silver_oz/31.1035*0.925:.2f}/gram sterling

### Silver Item Types
- Flatware (spoons, forks): 100% solid silver weight
- Hollowware (bowls, trays): 100% solid
- Weighted (candlesticks): ONLY 20% is actual silver!
- Knives: Deduct 85g per knife (stainless blade)

### Sterling INSTANT PASS
- Rogers, 1847 Rogers, Community, Holmes & Edwards = PLATED
- "Silver Plate", "EPNS", "Silverplate", "Nickel Silver" = NOT STERLING

## OUTPUT FORMAT
Return ONLY valid JSON. Negative margin = ALWAYS PASS.
"""


# ============================================================
# SILVER PROMPT
# ============================================================

def get_silver_prompt() -> str:
    """Get silver analysis prompt with current spot prices"""
    silver_oz = SPOT_PRICES.get("silver_oz", 30)
    sterling_rate = silver_oz / 31.1035 * 0.925
    source = SPOT_PRICES.get("source", "default")
    last_updated = SPOT_PRICES.get("last_updated", "unknown")
    
    return f"""
=== SILVER CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of sterling silver. This is NOT a jewelry appraisal.
We buy silver to MELT IT, not to resell as jewelry.

=== CRITICAL RULE: SCRAP VALUE ONLY ===
GEMSTONES = $0 VALUE (turquoise, coral, onyx, etc. - deduct weight, add no value)
DECORATIVE STONES = $0 VALUE (just reduces silver weight)
DESIGNER NAMES = $0 PREMIUM (we're melting it)

If the listing price only makes sense because of stones/design/collectible value,
and the SILVER ALONE doesn't justify the price = INSTANT PASS

=== CHECK IMAGES FIRST ===
- SCALE showing weight -> USE THAT EXACT WEIGHT
- Hallmarks (Sterling, 925) -> Verify authenticity
- Large stones visible -> DEDUCT STONE WEIGHT
- "Weighted" or "Reinforced" -> Apply 20% silver rule
- Plated indicators (EPNS, Rogers, Silverplate) -> INSTANT PASS

=== CURRENT PRICING ({source}) ===
- Silver spot: ${silver_oz:.2f}/oz (updated: {last_updated})
- Sterling melt rate: ${sterling_rate:.2f}/gram
- Target: 75% of melt value (hard ceiling)

=== PRICING MODEL (SIMPLE) ===
1. silverWeight = totalWeight - stoneWeight (DEDUCT ALL STONES)
2. meltValue = silverWeight × ${sterling_rate:.2f}
3. maxBuy = meltValue × 0.75
4. Margin = maxBuy - listingPrice
5. If Margin < 0 = PASS (no exceptions!)

=== STONE DEDUCTIONS ===
Stones add ZERO value - only deduct their weight!

| Stone Type | Deduct |
| Small accent stone (<5mm) | 0.5-1g |
| Medium cabochon (5-10mm) | 1-3g |
| Large cabochon (10-20mm) | 3-6g |
| Very large stone (20mm+) | 6-10g+ |
| Turquoise cluster | 5-15g depending on size |
| Coral/amber beads | Estimate by size |

EXAMPLE - Stone Ring:
- Listing: "Sterling 925 turquoise ring, 12g total"
- Stone deduction: Large turquoise ~4g
- Silver weight: 12g - 4g = 8g
- Melt: 8g × ${sterling_rate:.2f} = ${8 * sterling_rate:.2f}
- Max buy: ${8 * sterling_rate * 0.75:.2f}
- The turquoise adds $0 to our calculation!

=== ITEM TYPE RULES ===
SOLID STERLING (100% of weight is silver):
- Flatware (forks, spoons)
- Bowls, trays, plates
- Simple jewelry (no stones)

WEIGHTED ITEMS (only 20% is silver):
- Large candlesticks (cement-filled)
- Salt/pepper shakers
- Items marked "Weighted" or "Reinforced"

FLATWARE KNIVES: Deduct 85g per knife (stainless blade)

=== INSTANT PASS CONDITIONS ===
- Negative margin (no exceptions!)
- Plated: Rogers, 1847 Rogers, Community, EPNS, Silverplate
- Stone jewelry priced for the stone, not the silver
- Price > $3/gram of actual silver weight (overpriced)

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [what you found] | STONES: [deduction or None] | CALC: [silver weight]g x ${sterling_rate:.2f} = $[melt], x0.75 = $[maxBuy], list $[price] | MARGIN: $[+/-amount] | DECISION: [BUY/PASS] [why]"

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (PASS if margin negative - never RESEARCH for negative margin)
- verified: "Yes"/"No"/"Unknown"
- itemtype: "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Plated"/"NotSilver"
- weight: total weight like "12g" or "NA"
- stoneDeduction: "4g turquoise" or "0" or "NA"
- silverweight: weight after deduction
- pricepergram: listing price / silverweight
- meltvalue: silverweight x ${sterling_rate:.2f}
- maxBuy: meltvalue x 0.75
- Margin: maxBuy - TotalPrice (positive = profit, negative = loss)
- confidence: "High"/"Medium"/"Low"
- reasoning: MUST show DETECTION | STONES | CALC | MARGIN | DECISION

=== FINAL RULES ===
1. Negative margin = ALWAYS PASS (no exceptions, no RESEARCH)
2. Stones = $0 value, just deduct weight
3. We pay for SILVER WEIGHT ONLY
4. When in doubt, estimate LOW on silver weight, HIGH on stone weight

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# GOLD PROMPT
# ============================================================

def get_gold_prompt() -> str:
    """Get gold analysis prompt with current spot prices - SCRAP VALUE ONLY"""
    gold_oz = SPOT_PRICES.get("gold_oz", 2650)
    gold_gram = gold_oz / 31.1035
    source = SPOT_PRICES.get("source", "default")
    last_updated = SPOT_PRICES.get("last_updated", "unknown")
    
    k10 = gold_gram * 0.417
    k14 = gold_gram * 0.583
    k18 = gold_gram * 0.75
    k22 = gold_gram * 0.917
    k24 = gold_gram
    
    return f"""
=== GOLD CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of gold items. This is NOT a jewelry appraisal.
We buy gold to MELT IT, not to resell as jewelry.

=== CRITICAL: PHOTOS OVERRIDE ITEM SPECIFICS ===
ALWAYS TRUST THE PHOTOS OVER ITEM SPECIFICS!
- If item specifics say "no stone" but you SEE a stone in photos = DEDUCT FOR THE STONE
- If item specifics say "no weight" but scale photo shows weight = USE THE SCALE WEIGHT
- If photos show pearl/crystal/gemstone = DEDUCT IT regardless of what seller claims
- SCALE PHOTOS ARE THE MOST RELIABLE SOURCE

=== CRITICAL RULE: SCRAP VALUE ONLY ===
DIAMONDS = $0 VALUE (we can't sell them, only the gold matters)
GEMSTONES = $0 VALUE (same - they add weight we must deduct, not value)
PEARLS = $0 VALUE (deduct 1-3g depending on size)
DESIGNER NAMES = $0 PREMIUM (Tiffany, Cartier, etc. = same as generic gold)
COLLECTIBLE VALUE = $0 (we're melting it)

If the listing price only makes sense because of diamonds/gemstones/designer name,
and the GOLD ALONE doesn't justify the price = INSTANT PASS

=== INSTANT PASS CONDITIONS ===
- Single earring (no resale market, worthless)
- Diamond-focused listings (value is in stones, not gold)
- Gemstone jewelry where stone is the selling point
- Price exceeds $100/gram of gold weight (overpriced for scrap)
- Any plated/filled: GF, GP, HGE, RGP, Vermeil, Gold Tone

=== CURRENT GOLD PRICING ({source} - {last_updated}) ===
Gold spot: ${gold_oz:,.2f}/oz = ${gold_gram:.2f}/gram pure

SCRAP RATES (what refiners pay) - USE THESE EXACT VALUES:
- 10K (41.7%): ${k10:.2f}/gram
- 14K (58.3%): ${k14:.2f}/gram  
- 18K (75.0%): ${k18:.2f}/gram
- 22K (91.7%): ${k22:.2f}/gram
- 24K (99.9%): ${k24:.2f}/gram

=== PRICING MODEL (SHOW YOUR WORK) ===
1. goldWeight = totalWeight - stoneWeight (deduct ALL stones/pearls/diamonds)
2. meltValue = goldWeight × karatRate (CALCULATE THIS NUMBER!)
3. maxBuy = meltValue × 0.90 (our max purchase - 10% margin)
4. Margin = maxBuy - listingPrice
5. If Margin < 0 = PASS (no exceptions!)

EXAMPLE - 14K chain with pearl pendant, 4.84g total:
- Stone deduction: pearl ~1.5g
- Gold weight: 4.84 - 1.5 = 3.34g
- Melt: 3.34g × ${k14:.2f} = ${3.34 * k14:.0f}
- maxBuy: ${3.34 * k14:.0f} × 0.90 = ${3.34 * k14 * 0.90:.0f}
- If list price $300: Margin = ${3.34 * k14 * 0.90:.0f} - $300 = ${3.34 * k14 * 0.90 - 300:.0f} = PASS

=== WEIGHT ESTIMATION ===

** SINGLE STUD EARRING **
PASS IMMEDIATELY - Single earrings have NO resale value
(If you must estimate: 0.3-0.8g gold, but PASS anyway)

** PAIR OF STUD EARRINGS **
| Type | Gold Weight |
| Small studs | 0.5-1g total |
| Medium studs | 1-2g total |
| Large studs | 2-4g total |

** RINGS **
| Type | Gold Weight |
| Thin band | 1-2g |
| Standard band | 2-4g |
| Class ring womens | 5-8g |
| Class ring mens | 8-15g |
| Heavy/chunky ring | 6-12g |

** CHAINS **
| Type | Per Inch |
| Thin chain | 0.3-0.5g/inch |
| Medium chain | 0.5-1g/inch |
| Heavy chain | 1-2g/inch |
| HOLLOW chains | 50-70% LESS than solid |

** BRACELETS **
| Type | Total Weight |
| Thin 7" | 4-8g |
| Standard 7" | 8-15g |
| Heavy 7" | 15-25g |

** WATCHES - CRITICAL DEDUCTIONS **
Gold watch CASES are valuable, but movements and crystals are NOT gold!

IF MOVEMENT/CRYSTAL STILL INSIDE (visible in photos):
| Component | Deduct |
| Movement (mechanism inside) | 2-3g |
| Crystal (glass face) | 0.5-1g |
| Movement + Crystal together | 3-4g |

EMPTY CASE (movement removed): No deduction needed

| Watch Type | Case Only Weight |
| Ladies small case | 2-4g |
| Ladies medium case | 4-6g |
| Mens small/thin case | 5-8g |
| Mens standard case | 8-12g |
| Mens heavy case | 12-18g |

EXAMPLE - Watch with movement:
- Listing shows 14K Hamilton watch, scale reads 9g total
- Movement + crystal visible = deduct 3g
- Gold weight: 9g - 3g = 6g actual gold
- Melt: 6g × $49.67 = $298

LOOK FOR: If watch face is intact and you can see hands/dial, the movement is inside!

=== STONE/PEARL DEDUCTIONS ===
Stones and pearls add ZERO value - only deduct their weight!

CRITICAL: If you SEE a stone/pearl in photos, DEDUCT IT even if item specifics say "no stone"

| Stone/Pearl Size | Deduct |
| Tiny accent (<3mm) | 0.1-0.2g each |
| Small (3-5mm) | 0.2-0.5g each |
| Medium pearl/stone (5-8mm) | 0.5-1.5g each |
| Large pearl/cabochon (8-12mm) | 1.5-3g each |
| Very large (12mm+) | 3-5g+ each |
| Mother of pearl/crystal pendant | 1-3g |

EXAMPLE - 14K chain with pearl pendant (like in photos):
- Scale shows 4.84g total WITH the pearl
- Pearl visible ~10mm = deduct 2g
- Gold weight: 4.84 - 2 = 2.84g
- Melt: 2.84g × ${k14:.2f} = ${2.84 * k14:.0f}
- maxBuy: ${2.84 * k14 * 0.90:.0f}
- At $300 list: Margin = ${2.84 * k14 * 0.90:.0f} - $300 = -${300 - 2.84 * k14 * 0.90:.0f} = PASS

=== CONFIDENCE SCORING ===
Start at 60%, then adjust:

INCREASE confidence:
| Factor | Adjustment |
| Weight stated on scale photo | +25% |
| Clear karat stamp visible | +10% |
| Vintage/antique piece | +5% |
| Known maker visible | +5% |

DECREASE confidence:
| Factor | Adjustment |
| No weight stated, hard to estimate | -15% |
| High-risk chain style (Cuban, Rope) | -15% |
| New seller (<50 feedback) | -10% |
| Stock photos only | -10% |
| Stone visible but size uncertain | -10% |

Final confidence:
- 75%+ = "High"
- 50-74% = "Medium"  
- Below 50% = "Low"

=== RISK FLAGS ===
HIGH FAKE RISK (be extra cautious):
- Cuban, Figaro, Franco, Rope chains
- "Hip-hop" style jewelry
- Too-good-to-be-true prices
- New sellers, stock photos

LOWER RISK:
- Class rings, dental gold, broken scrap
- Vintage pieces with obvious wear
- Known brand markings (but no premium!)

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [karat], [item type], [total weight] | STONES: [deduction or None] | CALC: [gold weight]g × ${k14:.2f} = $[melt], ×0.90 = $[maxBuy], list $[price] | MARGIN: $[+/-amount] | DECISION: [BUY/PASS] [why]"

=== JSON OUTPUT (ALL REQUIRED - MUST HAVE ACTUAL VALUES) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (PASS if margin negative or instant pass condition)
- verified: "Yes"/"No"/"Unknown"
- karat: "10K"/"14K"/"18K"/"22K"/"24K"/"NA"
- itemtype: "Ring"/"Chain"/"Bracelet"/"Earrings"/"Pendant"/"Watch"/"Scrap"/"Plated"
- weight: total weight like "4.84" (number, not string with 'g')
- stoneDeduction: "2g pearl" or "0" or "NA"
- watchDeduction: "3g movement+crystal" or "0" or "NA"
- goldweight: weight after ALL deductions (MUST BE A NUMBER like "2.84")
- meltvalue: goldweight × karat rate (MUST BE A NUMBER like "141" - ALWAYS CALCULATE THIS!)
- maxBuy: meltvalue × 0.90 (MUST BE A NUMBER like "127")
- Margin: maxBuy - TotalPrice (MUST BE A NUMBER like "-173" or "+50")
- confidence: "High"/"Medium"/"Low" (based on confidence scoring above)
- fakerisk: "High"/"Medium"/"Low"
- reasoning: MUST show DETECTION | STONES | CALC | MARGIN | DECISION

CRITICAL: meltvalue, maxBuy, and Margin MUST be actual calculated numbers, NOT "$--" or "NA"!

=== FINAL RULES ===
1. Negative margin = ALWAYS PASS (no exceptions)
2. Single earring = ALWAYS PASS
3. Diamond jewelry where gold alone doesn't justify price = PASS
4. We pay for GOLD WEIGHT ONLY, never for stones or designer names
5. When in doubt, estimate LOW on gold weight
6. Watches with movement/crystal inside = DEDUCT 3g

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
# COSTUME JEWELRY PROMPT
# ============================================================

COSTUME_PROMPT = """
Analyze this costume jewelry listing and return JSON.

=== STRATEGY: EV (Expected Value) APPROACH ===
We buy costume jewelry for:
1. DESIGNER PIECES - Known signed makers with resale value
2. CHEAP LOTS - High piece count at low prices with hidden potential
3. HIDDEN METALS - Gold/silver pieces mixed into "costume" lots

This is a GAMBLE PLAY - cheap + high potential = BUY

=== DESIGNER HIERARCHY (High to Low Value) ===

** TIER 1 - HIGH VALUE ($50-500+) **
- Miriam Haskell (hand-wired, baroque pearls)
- Schreiner (inverted stones, high-dome)
- Eisenberg Original (not just "Eisenberg Ice")
- Hattie Carnegie
- Schiaparelli
- Boucher (numbered pieces)

** TIER 2 - GOOD VALUE ($20-100) **
- Trifari (especially Crown Trifari, jelly bellies, sterling pieces)
- Coro/Corocraft (especially Duettes)
- Weiss (quality rhinestones)
- Kramer
- Lisner
- Regency
- Juliana (DeLizza & Elster - usually unsigned but distinctive)
- Vendome
- Napier (especially sterling or mechanical pieces)
- Monet (heavier pieces)

** TIER 3 - MODERATE VALUE ($10-40) **
- Sarah Coventry
- Avon (vintage only)
- Emmons
- Gerry's
- JJ (Jonette Jewelry)
- Trifari newer pieces

** INSTANT PASS MAKERS (Low/No Value) **
- Fashion jewelry store brands (Forever 21, H&M, Claire's)
- Unbranded modern costume
- Obvious plastic/acrylic junk
- Broken beyond repair

=== LOT ANALYSIS - KEY FACTORS ===

** PIECE COUNT MATTERS **
| Pieces | Base Score |
| 1-5 | Low volume |
| 6-15 | Medium volume |
| 16-30 | Good volume |
| 30-50 | High volume |
| 50+ | Excellent - likely hidden gems |

** VARIETY = OPPORTUNITY **
Look for mix of:
- Brooches/pins
- Necklaces
- Bracelets
- Earrings (pairs)
- Rings
- Signed pieces visible
- Different eras/styles

** HIDDEN METAL POTENTIAL **
LOOK IN IMAGES FOR:
- Yellow metal that could be gold (clasps, chains, backs)
- White metal chains/components (could be sterling)
- Marks visible: 925, Sterling, 10K, 14K, 1/20, GF
- Patina/tarnish patterns suggesting real metal
- Weight indicators (heavy-looking pieces)

=== PRICING THRESHOLDS ===

** LOTS **
| Price | Piece Count | Decision |
| Under $20 | 10+ pieces | BUY if any potential |
| Under $30 | 20+ pieces | BUY if decent variety |
| Under $50 | 30+ pieces | BUY if designer or metal potential |
| Under $50 | 50+ pieces | Usually BUY (volume play) |
| $50-100 | Must have | Visible designer or confirmed value |
| Over $100 | Must have | Multiple designer pieces or gold/silver confirmed |

** INDIVIDUAL PIECES **
| Type | Max Buy |
| Tier 1 designer | Research market value |
| Tier 2 designer | $20-50 depending on piece |
| Tier 3 designer | $5-15 max |
| Unsigned vintage | $5-10 if exceptional |

=== CONFIDENCE SCORING ===
Start at 50%, adjust:

| Factor | Adjustment |
| Designer signature visible | +20% |
| Multiple designers in lot | +15% |
| High piece count (30+) | +15% |
| Yellow/white metal visible | +15% |
| Good variety of types | +10% |
| Vintage look (pre-1980) | +10% |
| Good photos showing marks | +10% |
| Poor photos/blurry | -15% |
| Modern looking | -20% |
| Damaged/broken pieces | -10% |
| Single earring present | -5% |

=== EV CALCULATION ===
EV = (Potential Upside × Confidence) - Price

Example lot:
- Price: $25
- 40 pieces visible, see "Trifari" on one brooch
- Some yellow metal chains, good variety
- Potential upside: $80-150 if Trifari + others
- Confidence: 70%
- EV = ($100 × 0.70) - $25 = $45 positive EV = BUY

=== REASONING FORMAT (REQUIRED) ===
"LOT: [piece count], [variety] | DESIGNERS: [any visible] | METALS: [potential gold/silver] | PRICE: $[X] for [Y] pieces = $[per piece] | EV: [upside] x [confidence] - [price] = [result] | DECISION: [BUY/PASS/RESEARCH] [why]"

=== JSON OUTPUT ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS"/"RESEARCH"
- listingtype: "Lot"/"Single"/"SmallLot"
- pieceCount: estimated number like "25" or "50+" or "1"
- designers: comma-separated list or "None visible" or "Unknown"
- bestDesigner: highest tier designer spotted or "None"
- metalPotential: "High"/"Medium"/"Low"/"None" (hidden gold/silver chance)
- variety: "Excellent"/"Good"/"Fair"/"Poor"
- pricePerPiece: price divided by piece count like "$0.50" or "$2.00"
- potentialValue: estimated upside like "$80-150" or "Unknown"
- confidence: "High"/"Medium"/"Low"
- EV: positive or negative expected value like "+$45" or "-$20"
- reasoning: MUST show LOT | DESIGNERS | METALS | PRICE | EV | DECISION

=== DECISION RULES ===
- BUY: Positive EV AND (designer visible OR high volume OR metal potential)
- RESEARCH: Borderline EV, needs more investigation
- PASS: Negative EV OR obvious junk OR overpriced

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
    elif category == "costume":
        return COSTUME_PROMPT
    else:
        return get_silver_prompt()  # Default


def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    title = data.get("Title", "").lower()
    reasons = []
    
    # Define keywords
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "karat"]
    silver_keywords = ["sterling", "925", ".925"]
    
    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    
    # ============================================================
    # PRIORITY 1: Sterling + Gold combo = ALWAYS SILVER
    # This overrides alias because the gold is just accent, not the main metal
    # ============================================================
    if silver_matches and gold_matches:
        reasons.append(f"Title has BOTH sterling ({silver_matches}) AND gold ({gold_matches}) - gold is accent only, treating as SILVER")
        return "silver", reasons
    
    # ============================================================
    # PRIORITY 2: Check Alias (user's search intent)
    # ============================================================
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
    elif "costume" in alias or "jewelry lot" in alias or "vintage lot" in alias:
        reasons.append(f"Alias contains costume keywords: {data.get('Alias', '')}")
        return "costume", reasons
    
    # ============================================================
    # PRIORITY 3: Fall back to title keywords
    # ============================================================
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "magic the gathering", "mtg booster", "sealed case", "tcg"]
    coral_keywords = ["coral", "mediterranean coral", "red coral", "angel skin", "salmon coral", "oxblood coral"]
    costume_keywords = ["costume jewelry", "vintage jewelry lot", "jewelry lot", "trifari", "coro", "eisenberg", "weiss", "miriam haskell", "rhinestone lot", "brooch lot"]
    
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    coral_matches = [kw for kw in coral_keywords if kw in title]
    costume_matches = [kw for kw in costume_keywords if kw in title]
    
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
    elif costume_matches:
        reasons.append(f"Title contains costume keywords: {costume_matches}")
        return "costume", reasons
    
    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons
