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
- PEARLS = $0 (deduct their weight! 8mm pearl = 1.7g, 10mm = 3g)
- CAMEOS = $0 (deduct their weight! Small cameo = 2-3g, Large cameo = 4-6g)
- DESIGNER NAMES = $0 (Tiffany, Cartier = same as generic, we're melting it)
- SINGLE EARRINGS = PASS (no resale market)

PEARL WARNING: Pearls are HEAVY! A pearl strand "40g 14K" = 36g pearls + 4g gold!
If you see "pearl" in title, deduct ALL pearl weight before calculating gold value!

CAMEO WARNING: Cameos are carved shell/coral/stone - NOT metal!
Typical cameo brooch: 1" cameo = 2-3g, 1.5" cameo = 4-5g, 2" cameo = 6-8g
A "6.7g 10K cameo brooch" = 4-5g cameo + 1.7-2.7g gold frame!

If the listing price only makes sense because of stones/designer/collectible value,
and the METAL ALONE doesn't justify the price = PASS

## GOLD BUYING RULES (Scrap Only)
- Target: 90% of melt value (hard ceiling)
- Quick filter: Auto-PASS anything over $100/gram of gold
- Current spot: ~${gold_oz:,.0f}/oz
- Diamonds/gemstones = $0 added value (just deduct weight)

### Karat Rates (at ${gold_oz:,.0f}/oz)
- 24K: ${gold_oz/31.1035:.2f}/g, max buy ${gold_oz/31.1035*0.90:.2f}
- 18K: ${gold_oz/31.1035*0.70:.2f}/g, max buy ${gold_oz/31.1035*0.70*0.90:.2f}
- 14K: ${gold_oz/31.1035*0.583:.2f}/g, max buy ${gold_oz/31.1035*0.583*0.90:.2f}
- 10K: ${gold_oz/31.1035*0.417:.2f}/g, max buy ${gold_oz/31.1035*0.417*0.90:.2f}

### Gold INSTANT PASS
- Single earring (worthless)
- Diamond-focused jewelry (value in stones, not gold)
- "Gold Filled", "GF", "Gold Plated", "GP", "HGE", "RGP", "Vermeil", "Gold Tone"
- GOLD FILLED BRANDS: "Champion Dueber", "Dueber", "Wadsworth", "Keystone", "Star Watch Case"
- Price > $100/gram of actual gold weight
- WATCHES: Most vintage watch cases are gold FILLED, not solid! Research required.

## SILVER BUYING RULES
- Target: 75% of melt value or under (MAX ceiling)
- Sweet spot: 50-60% of melt = excellent deal
- Current spot: ~${silver_oz:.0f}/oz = ${silver_oz/31.1035:.2f}/gram pure, ${silver_oz/31.1035*0.925:.2f}/gram sterling

### Silver Item Types
- Flatware (spoons, forks): 100% solid silver weight
- Hollowware (bowls, trays): 100% solid
- Weighted (candlesticks): ONLY 15% is actual silver!
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

=== ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â CRITICAL: READ THE SCALE PHOTO FIRST ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ===
BEFORE DOING ANYTHING ELSE, look for a scale photo in the images!

If you see a digital scale displaying a number:
1. READ THE EXACT NUMBER on the scale display (e.g., "120.5", "45.8", "312")
2. USE THAT EXACT NUMBER as the weight - DO NOT ESTIMATE!
3. The scale reading is the MOST ACCURATE weight source

IF SCALE SHOWS 120g ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ weight = 120g (NOT an estimate!)
IF NO SCALE PHOTO ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ then estimate based on item type

=== CRITICAL RULE: SCRAP VALUE ONLY ===
GEMSTONES = $0 VALUE (turquoise, coral, onyx, etc. - deduct weight, add no value)
DECORATIVE STONES = $0 VALUE (just reduces silver weight)
DESIGNER NAMES = $0 PREMIUM (we're melting it)

If the listing price only makes sense because of stones/design/collectible value,
and the SILVER ALONE doesn't justify the price = INSTANT PASS

=== CHECK IMAGES ===
- SCALE showing weight -> USE THAT EXACT WEIGHT (set weightSource="scale")
- Hallmarks (Sterling, 925) -> Verify authenticity
- Large stones visible -> DEDUCT STONE WEIGHT
- "Weighted" or "Reinforced" -> Apply 15% silver rule
- Plated indicators (EPNS, Rogers, Silverplate) -> INSTANT PASS

=== CURRENT PRICING ({source}) ===
- Silver spot: ${silver_oz:.2f}/oz (updated: {last_updated})
- Sterling melt rate: ${sterling_rate:.2f}/gram

=== PRICING MODEL ===
DEFINITIONS:
- meltValue = silverWeight ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${sterling_rate:.2f} (the theoretical 100% value)
- maxBuy = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.70 (our ceiling - NEVER pay more than this)
- sellPrice = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.82 (what refiner actually pays us)
- Profit = maxBuy - listingPrice (positive = can buy, negative = PASS)

CALCULATION STEPS:
1. silverWeight = totalWeight - stoneWeight (DEDUCT ALL STONES)
2. meltValue = silverWeight ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${sterling_rate:.2f}
3. maxBuy = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.70
4. sellPrice = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.82
5. Profit = maxBuy - listingPrice
6. If Profit < 0 = PASS (no exceptions!)

=== STONE DEDUCTIONS ===
Stones add ZERO value - only deduct their weight!

| Stone Type | Deduct |
| Small accent stone (<5mm) | 0.5-1g |
| Medium cabochon (5-10mm) | 1-3g |
| Large cabochon (10-20mm) | 3-6g |
| Very large stone (20mm+) | 6-10g+ |
| Turquoise cluster | 5-15g depending on size |
| Coral/amber beads | Estimate by size |
| CAMEO - Small (1") | 2-3g |
| CAMEO - Medium (1.5") | 4-5g |
| CAMEO - Large (2"+) | 6-8g |

** CHUNKY CABOCHON EARRINGS - STONES DOMINATE THE WEIGHT! **
Dense stones: Tiger's Eye, Turquoise, Amber, Malachite, Lapis, Onyx, Jade
- Clip-back/chunky earrings with these = 50-80% STONE WEIGHT
- Per earring with large cabochon: 2-3g stone, only 0.5-1.5g silver
- EXAMPLE: "10g Turquoise Sterling earrings" = ~6-7g stones, only 3-4g silver
- Melt: 3.5g silver = ~$3.50, NOT $10!

=== CRITICAL: BEADED JEWELRY ===
BEADED bracelets/necklaces are MOSTLY BEADS, not silver!
If you see strung beads (turquoise, coral, glass, gemstone), the silver is just:
- Clasp: 1-3g
- Wire/findings: 1-2g
- Spacer beads (if silver): 2-5g

BEADED ITEM RULE: Only 10-30% of total weight is silver!

| Beaded Item Type | Silver % of Total Weight |
| Heavy bead necklace/bracelet | 10-15% |
| Mixed bead with silver spacers | 20-30% |
| Charm bracelet with some beads | 50-70% |
| Solid chain with bead pendant | 70-80% |

EXAMPLE - Lot of 13 beaded bracelets, 300g total:
- Photos show turquoise, coral, glass beads strung on wire
- These are BEADED items = only ~20% silver
- Silver weight: 300g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.20 = 60g (NOT 280g!)
- Melt: 60g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${sterling_rate:.2f} = ${60 * sterling_rate:.2f}
- Max buy: ${60 * sterling_rate * 0.70:.2f}

LOOK AT THE PHOTOS! If beads are the main component, use the percentage rule.

=== CRITICAL: BAKELITE/LUCITE/PLASTIC JEWELRY (INSTANT PASS!) ===
BAKELITE, LUCITE, ACRYLIC, and RESIN jewelry has almost NO SILVER!
These are PLASTIC materials - the "sterling silver" is just the clasp/findings!

BAKELITE JEWELRY RULE: INSTANT PASS unless dirt cheap!
- Bakelite necklaces: 1-5g silver (clasp only), rest is plastic
- Lucite bracelets: 0-3g silver (findings), rest is plastic
- "Cherry Red Bakelite" = PLASTIC, not gemstone!
- "260g bakelite necklace with sterling" = 5g silver, 255g plastic

KEYWORDS TO WATCH: bakelite, lucite, acrylic, celluloid, plastic, resin (as main material)
These items are valued as VINTAGE COSTUME JEWELRY, not silver scrap!

| Bakelite/Lucite Item | Actual Silver Content |
| Necklace with clasp | 2-5g (clasp only) |
| Bracelet with findings | 1-3g (findings only) |
| Brooch with pin back | 1-2g (pin mechanism) |
| Earrings | 0.5-1g each (posts/clips) |

EXAMPLE - Bakelite Necklace:
- Listing: "Vintage Cherry Red Bakelite Necklace Sterling Silver 260g"
- WRONG: 260g sterling = huge value!
- RIGHT: Clasp only = 3-5g silver = ~$5 melt value
- These sell for $20-100+ as vintage costume, NOT as silver scrap!
- INSTANT PASS for silver arbitrage

EXAMPLE - Stone Ring:
- Listing: "Sterling 925 turquoise ring, 12g total"
- Stone deduction: Large turquoise ~4g
- Silver weight: 12g - 4g = 8g
- Melt: 8g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${sterling_rate:.2f} = ${8 * sterling_rate:.2f}
- Max buy: ${8 * sterling_rate * 0.70:.2f}
- The turquoise adds $0 to our calculation!

=== ITEM TYPE RULES ===
SOLID STERLING (100% of weight is silver):
- Flatware (forks, spoons)
- Bowls, trays, plates (non-weighted)
- Simple jewelry (no stones)

WEIGHTED ITEMS (cement/resin filled - use FIXED silver amounts below):
- Candlesticks, salt/pepper shakers, compotes, cream/sugar sets
- Items marked "Weighted", "Reinforced", "Loaded"
- Umbrella handles (weighted!)

FLATWARE KNIVES: Deduct 85g per knife (stainless blade)

=== WEIGHTED STERLING REFERENCE (CRITICAL - USE THESE FIXED VALUES!) ===
DO NOT calculate percentage of total weight! Use these FIXED silver amounts:

| Weighted Item Type | ACTUAL SILVER (not total weight!) |
| Small candlestick (each) | 25g silver |
| Medium candlestick (each) | 35-45g silver |
| Large candlestick (each) | 50-75g silver |
| Small compote | 50g silver |
| Cream pitcher (weighted) | 45g silver |
| Sugar bowl (weighted) | 45g silver |
| Cream/sugar SET | 90g silver total |
| Salt/pepper shaker (each) | 15-25g silver |
| Weighted bowl 8-10" | 150-200g silver |
| Weighted bowl 10-12"+ | 200-250g silver |
| Umbrella handle | 30-50g silver |

EXAMPLE - Weighted Candlestick Pair:
- Listing says "Weighted Sterling Candlesticks 450g pair"
- WRONG: 450g Ã— 20% = 90g silver
- RIGHT: Use reference = 25g Ã— 2 = 50g silver (small) or 70g (medium)
- The 450g is mostly cement/filler!

=== HOLLOWWARE WEIGHT REFERENCE (SOLID BOWLS, DISHES, TRAYS) ===
These are for SOLID (non-weighted) sterling hollowware.
Sterling hollowware is LIGHTER than it looks! Use these realistic ranges:

| Item Type | Size | Typical Weight |
| Small nut/candy dish | 3-4" | 30-50g |
| Medium bowl | 5-6" | 60-100g |
| Large bowl | 7-8" | 120-200g |
| Very large bowl | 9-10" | 200-350g |
| Bread tray | 10-12" | 150-250g |
| Serving tray | 12-14" | 250-400g |
| Large platter | 14-16"+ | 400-600g |
| Compote/pedestal | 6-8" | 150-250g |
| Cream/sugar set | pair | 100-180g total |

CRITICAL: Without a scale photo, use the LOWER end of the range!
- 6" bowl with no scale = estimate 70-80g, NOT 150g
- When in doubt, estimate CONSERVATIVE (low)

=== QUANTITY LISTING DETECTION (CRITICAL!) ===
CHECK FOR MULTIPLE QUANTITY LISTINGS!

Some sellers list items with Qty > 1, meaning:
- Price shown is PER ITEM
- But you get MULTIPLE items for that price
- This makes the deal much better!

LOOK FOR IN DATA:
- "Quantity" or "Qty" field > 1
- Title says "1 of 6 available" or "6 qty"
- Description mentions multiple available

IF QUANTITY > 1:
- The value calculation applies to EACH item
- Profit = (maxBuy Ã— quantity) - (listingPrice Ã— quantity)
- A $20 spoon with Qty 6 = $120 total value for $120 total cost
- BUT if seller ships all 6 for one price, it's 6Ã— the deal!

EXAMPLE - Silver Spoon Qty 6:
- Listing: "$25 per spoon, Qty: 6 available"
- Each spoon: 45g sterling = $80 melt, $60 maxBuy
- If buying all 6: 270g total = $480 melt, $360 maxBuy
- Total cost: $150 (if $25 Ã— 6)
- Profit: $360 - $150 = $210!
- NOTE: Verify if price is per item or for all!

=== FLATWARE WEIGHT ESTIMATION (CRITICAL!) ===
When estimating flatware weight, use CONSERVATIVE per-piece averages:

ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚Â KNIVES HAVE HOLLOW HANDLES - They weigh much less than forks/spoons!

| Piece Type | Weight |
| Dinner fork | 45g |
| Salad fork | 35g |
| Dinner spoon/Tablespoon | 45g |
| Soup spoon | 35g |
| Teaspoon | 20g |
| Iced tea spoon | 18g |
| Flat butter knife | 20g |
| Dinner knife (filled handle) | 15-20g SILVER ONLY |
| Serving fork/spoon | 50-60g |
| Small pickle fork | 10g |

FLATWARE SET AVERAGE: ~30-35g per piece (knives and teaspoons drag it down!)
- 36 pieces ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 38g = ~1368g realistic
- 48 pieces ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 38g = ~1824g realistic
- 72 pieces ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 38g = ~2736g realistic

NEVER estimate flatware at >40g/piece average!

=== INSTANT PASS CONDITIONS ===
- Negative margin (no exceptions!)
- Plated: Rogers, 1847 Rogers, Community, EPNS, Silverplate
- Stone jewelry priced for the stone, not the silver
- Price > $3/gram of actual silver weight (overpriced)

=== CRITICAL: ESTIMATED WEIGHT RULE ===
*** If weightSource = "estimate", Recommendation CANNOT be "BUY"! ***
- Estimated weight means guessing - guessing wrong loses money
- RESEARCH or PASS only for estimated weights
- BUY requires scale photo or seller-stated weight

When weight is ESTIMATED:
1. PASS if price is too high for any reasonable weight
2. RESEARCH if could be profitable at higher weight estimate (DEFAULT)
3. BUY only with VERIFIED weight (scale or stated)

=== CONFIDENCE SCORING (0-100) ===
Start at 60, then adjust:

INCREASES:
| Factor | Add |
| Weight shown on scale photo | +25 |
| Sterling/925 mark clearly visible | +10 |
| Known maker (Gorham, Towle, etc.) | +10 |
| Hallmarks visible in photos | +5 |

DECREASES:
| Factor | Subtract |
| No weight stated | -15 |
| Weight must be estimated | -10 |
| Stone size uncertain | -10 |
| Mixed lot, pieces unclear | -15 |
| Poor/blurry photos | -10 |

IMPORTANT: If weightSource = "estimate", confidence MAXIMUM is 50!

Final score: 0-100 (output as integer)

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [what you found] | STONES: [deduction or None] | CALC: [silver wt]g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â $[rate] = $[melt], sell 82% = $[sell], list $[price] | PROFIT: $[sell - price] | DECISION: [BUY/PASS] [why]"

=== JSON KEYS (ALL REQUIRED) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (PASS if listingPrice > maxBuy)
- verified: "Yes"/"No"/"Unknown"
- itemtype: "Flatware"/"Hollowware"/"Weighted"/"Jewelry"/"Plated"/"NotSilver"/"Beaded"
- weightSource: "scale" (if read from scale photo) or "estimate" (if guessed)
- weight: total weight like "120" (number from scale) or "45" (estimate)
- stoneDeduction: "4g turquoise" or "0" or "NA"
- silverweight: weight after deduction
- pricepergram: listing price / silverweight
- meltvalue: silverweight ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${sterling_rate:.2f}
- maxBuy: meltvalue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.70 (our ceiling - don't pay more than this)
- sellPrice: meltvalue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.82 (what refiner pays us)
- Profit: sellPrice - listingPrice (actual money in our pocket)
- confidence: MUST BE INTEGER 0-100 - if weightSource="scale" start at 85, if "estimate" start at 45
- confidenceBreakdown: "Base 60 + scale 25 + 925 visible 10 - stone 10 = 85" OR "Base 60 - no scale 15 = 45"
- reasoning: MUST show DETECTION | STONES | CALC | PROFIT | DECISION

CRITICAL: 
- meltvalue, maxBuy, sellPrice, Profit MUST be actual numbers!
- confidence MUST be a number like 75, NOT a word like "High"!
- Profit = sellPrice (82% of melt) - listingPrice
- If you read weight from a SCALE PHOTO, weightSource = "scale" (higher confidence)
- If you ESTIMATED weight, weightSource = "estimate" (lower confidence)

=== FINAL RULES ===
1. If listingPrice > maxBuy = ALWAYS PASS (price exceeds our ceiling)
2. Stones = $0 value, just deduct weight
3. We pay for SILVER WEIGHT ONLY
4. When in doubt, estimate LOW on silver weight, HIGH on stone weight
5. READ THE SCALE NUMBER CAREFULLY - don't estimate if scale is visible!

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# COIN SCRAP PROMPT (Junk Silver / Constitutional Silver)
# ============================================================

def get_coin_prompt() -> str:
    """Get coin/junk silver analysis prompt with current spot prices"""
    silver_oz = SPOT_PRICES.get("silver_oz", 30)
    source = SPOT_PRICES.get("source", "default")
    last_updated = SPOT_PRICES.get("last_updated", "unknown")

    # 90% silver coin melt values (silver content per coin)
    # Dime: 0.07234 oz, Quarter: 0.18084 oz, Half: 0.36169 oz, Dollar: 0.77344 oz
    dime_90 = silver_oz * 0.07234
    quarter_90 = silver_oz * 0.18084
    half_90 = silver_oz * 0.36169
    dollar_90 = silver_oz * 0.77344  # Morgan/Peace

    # 40% silver (1965-1970 halves, silver Ikes)
    half_40 = silver_oz * 0.1479
    ike_40 = silver_oz * 0.3161

    # Silver Eagle (1 oz .999)
    eagle = silver_oz * 1.0

    # Per $1 face value for 90% silver
    face_value_90 = silver_oz * 0.7234

    return f"""
=== JUNK SILVER / CONSTITUTIONAL SILVER CALCULATOR ===

You are calculating MELT value of US silver coins. We buy coins for SILVER CONTENT only.
No numismatic/collector premiums - just metal value.

=== CURRENT SILVER SPOT ({source}) ===
Silver: ${silver_oz:.2f}/oz (updated: {last_updated})

=== 90% SILVER COINS (Pre-1965) - MELT VALUES ===
| Coin Type | Face Value | Silver (oz) | Melt Value |
|-----------|------------|-------------|------------|
| Barber/Mercury/Roosevelt Dime | $0.10 | 0.0723 oz | ${dime_90:.2f} |
| Barber/Standing Liberty/Washington Quarter | $0.25 | 0.1808 oz | ${quarter_90:.2f} |
| Barber/Walking Liberty/Franklin/1964 Kennedy Half | $0.50 | 0.3617 oz | ${half_90:.2f} |
| Morgan Dollar (1878-1921) | $1.00 | 0.7734 oz | ${dollar_90:.2f} |
| Peace Dollar (1921-1935) | $1.00 | 0.7734 oz | ${dollar_90:.2f} |

=== 40% SILVER COINS ===
| Coin Type | Face Value | Silver (oz) | Melt Value |
|-----------|------------|-------------|------------|
| Kennedy Half (1965-1970) | $0.50 | 0.1479 oz | ${half_40:.2f} |
| Eisenhower Dollar (1971-1976 Silver) | $1.00 | 0.3161 oz | ${ike_40:.2f} |

=== SILVER BULLION ===
| Coin Type | Silver (oz) | Melt Value |
|-----------|-------------|------------|
| American Silver Eagle (1986-present) | 1.000 oz | ${eagle:.2f} |
| Canadian Maple Leaf | 1.000 oz | ${eagle:.2f} |
| Generic 1 oz Round | 1.000 oz | ${eagle:.2f} |

=== QUICK CALCULATION: 90% SILVER BY FACE VALUE ===
$1.00 face value of 90% silver = 0.7234 oz = ${face_value_90:.2f} melt
- $10 face = ${face_value_90 * 10:.2f}
- $100 face = ${face_value_90 * 100:.2f}

=== BUYING RULES ===
- MAX BUY: 90% of melt value (our ceiling)
- SWEET SPOT: 80-85% of melt = good deal
- EXAMPLE: $10 face 90% silver, melt ${face_value_90 * 10:.2f}, max buy ${face_value_90 * 10 * 0.90:.2f}

=== INSTANT PASS ===
- Slabbed/graded coins (collector premium, not scrap)
- Key dates (1916-D dime, 1893-S Morgan, etc.)
- Proof sets (collector value)
- "Cleaned", "polished" rare coins
- Any price significantly above melt (>95%)

=== WATCH FOR ===
- "Cull" or "junk" = good, means no collector value
- "Lot" or "roll" = calculate total face value
- Mixed lots: count each denomination separately
- 40% vs 90% - HUGE difference! 1965-1970 halves are only 40%

=== CALCULATION STEPS ===
1. Identify coin type and count
2. Calculate total face value by denomination
3. Look up melt value per coin from table above
4. Total melt = sum of all coins
5. Max buy = total melt × 0.90
6. If listing price > max buy = PASS

=== OUTPUT FORMAT ===
Return JSON with:
- Recommendation: BUY/RESEARCH/PASS
- Qualify: Yes/Maybe/No
- reasoning: Coin type | Count | Face value | Melt calculation | Profit
- coinType: "90% junk silver" / "40% silver" / "silver eagle" / "mixed"
- faceValue: total face value (e.g., "$5.00")
- silverOz: total silver ounces
- meltvalue: total melt value
- maxBuy: melt × 0.90
- Profit: maxBuy - listingPrice

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
    k18 = gold_gram * 0.70
    k22 = gold_gram * 0.917
    k24 = gold_gram
    
    return f"""
=== GOLD CALCULATOR - SCRAP VALUE ONLY ===

You are calculating SCRAP/MELT value of gold items. This is NOT a jewelry appraisal.
We buy gold to MELT IT, not to resell as jewelry.

=== ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â CRITICAL: READ THE SCALE PHOTO FIRST ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ===
BEFORE DOING ANYTHING ELSE, look for a scale photo in the images!

=== SCALE UNIT DETECTION (CHECK THIS FIRST!) ===
Scales display different units - LOOK AT THE UNIT ON THE DISPLAY:
- "g" = grams ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ USE THIS for gold weight
- "dwt" = pennyweight ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ multiply by 1.555 for grams
- "ct" or "CT" = CARATS = GEMSTONE WEIGHT, NOT GOLD!
- "oz" = ounces ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ multiply by 31.1 for grams
- "PCS" = piece count mode ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ NOT A WEIGHT!

ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â CRITICAL WARNING: If scale shows "ct" mode:
- "ct" measures GEMSTONES in carats, NOT gold in grams!
- 109.0 ct = 109 carats of GEMSTONES, NOT 109 grams of gold!
- When scale shows "ct", the actual GOLD is just the clasp/findings (3-8g)

If you see a digital scale displaying a number AND it shows "g" mode:
1. READ THE EXACT NUMBER on the scale display (e.g., "2.16", "4.84", "8.2")
2. USE THAT EXACT NUMBER as the weight - DO NOT ESTIMATE!
3. The scale reading is the MOST ACCURATE weight source

Common scale display formats:
- "2.16" = 2.16 grams (if showing "g" mode)
- "4.8" or "4.84" = 4.8 or 4.84 grams (if showing "g" mode)
- Numbers may be small/blurry - zoom in mentally and read carefully

=== SCALE READING ERRORS TO AVOID ===
DECIMAL POINT DETECTION IS CRITICAL!
- "1.5" vs "15" = 10x difference! Look for the decimal point carefully.
- "19.1" vs "1.91" = 10x difference! 
- Small jewelry scales usually show 0.00 to 99.99 grams
- If reading seems too high for the item type, CHECK THE DECIMAL!

SANITY CHECK YOUR SCALE READING:
- Thin chain showing 19g? Probably 1.9g - recheck decimal!
- Small pendant showing 15g? Probably 1.5g - recheck decimal!
- Single earring showing 12g? Probably 1.2g - recheck decimal!

When uncertain about decimal placement:
1. Consider what weight is REALISTIC for the item
2. Thin chains are usually 1-5g, not 10-50g
3. Small pendants are usually 1-4g, not 10-40g
4. If unsure, recommend RESEARCH

IF SCALE SHOWS 2.16g ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ weight = 2.16g (NOT an estimate!)
IF SCALE SHOWS "ct" MODE ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ This is gemstone weight, not gold! See stone-heavy section.
IF NO SCALE PHOTO ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ then estimate based on item type

=== ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â STONE-HEAVY PIECES (MINIMAL GOLD - USUALLY PASS) ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ===
Some jewelry is 80-95% gemstones with very little gold!

GEMSTONE BEAD NECKLACES (peridot, amethyst, garnet, citrine, pearl, coral strands):
- These are BEADED jewelry where gems are strung on wire
- Gold content: ONLY clasp + small spacer beads = 3-8g total
- Do NOT use total weight for gold calculation!

RED FLAGS - STONE-HEAVY PIECE:
- Description says "XX cttw" or "total carat weight gemstone"
- Scale photo shows "ct" mode (carat mode, not grams)
- Photos show beaded/strung gemstone construction
- Title mentions specific gemstone carat weight

IF STONE-HEAVY DETECTED:
1. Estimate gold parts ONLY: clasp ~3-5g, spacer beads ~1-2g
2. IGNORE the gemstone weight entirely
3. If gold weight is unclear ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ PASS (don't guess on stones)
4. Better to miss a deal than lose money

EXAMPLE - PERIDOT NECKLACE (WHAT WENT WRONG):
Listing: "14K Peridot Briolette Necklace Michael Anthony 109 cttw"
Scale shows: 109.0 ct (carat mode for gemstones)
Description: "109 cttw gemstone"
ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚ÂÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ WRONG: Treating as 10.98g gold ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ $890 melt ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ BUY +$605
ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ RIGHT: Gold is clasp only ~4g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â $50 = $200 melt ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ list $250 = MARGINAL/PASS

When you see "cttw" in description or "ct" on scale = STONE-HEAVY PIECE!

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
- RESIN CORE / HOLLOW CORE: Gold over plastic = almost no gold! INSTANT PASS
- PEARL STRAND/NECKLACE: Gold is ONLY the clasp (2-4g max) - if price > $200, instant PASS
- PEARL BRACELET: Gold is 5-10% of total weight - if price > $300, instant PASS
- MIXED METAL (Silver + Gold): Items with BOTH sterling/silver AND gold are PRIMARILY SILVER!

=== HOLLOW GOLD DETECTION (CRITICAL!) ===
Look for these keywords in title/description:
- "hollow" / "hollow construction" / "hollow form"
- "lightweight" / "light weight" / "surprisingly light"
- "dimensional" / "puffed" / "tube construction"

RED FLAG: Sellers mentioning "hollow" often DON'T provide weight on purpose!
This is intentional to make buyers overestimate gold value. Be very suspicious.

HOLLOW vs SOLID vs SEMI-HOLLOW:
| Type | Weight vs Solid | Notes |
| SOLID | 100% | Look for "solid gold" - CONFIDENCE BOOST |
| SEMI-HOLLOW | 50-60% of solid | Still valuable, moderate discount |
| HOLLOW | ~20% of solid | Major discount, often a PASS |

WEIGHT MULTIPLIERS:
- "SOLID" mentioned = Use normal weight estimate (confidence +10)
- "SEMI-HOLLOW" mentioned = Multiply estimate by 0.55
- "HOLLOW" mentioned = Multiply estimate by 0.20 (often a PASS!)

| Item Type | Solid Weight | Semi-Hollow | Hollow |
| Small pendant/charm | 2-4g | 1-2g | 0.4-0.8g |
| Medium pendant | 4-8g | 2-4g | 0.8-1.6g |
| Large pendant/cross | 8-15g | 4-8g | 1.6-3g |
| Hoop earrings (pair) | 3-6g | 1.5-3g | 0.6-1.2g |
| Bangle bracelet | 15-30g | 8-16g | 3-6g |
| Rope chain per inch | 1-2g | 0.5-1g | 0.2-0.4g |

EXAMPLE - Hollow Cross Pendant:
- Description: "hollow construction", NO WEIGHT PROVIDED (red flag!)
- Seller hiding weight = assume worst case
- Looks like 8-10g cross but actual weight = 1.6-2g (hollow = 20%)
- At 14K: 2g x $82 = $164 melt, max buy $148
- If listing > $100, probably a PASS

IF "HOLLOW" DETECTED AND NO SCALE:
1. Use 20% of solid weight estimate
2. Set confidence to LOW (35-45)
3. Add to reasoning: "HOLLOW detected, no weight provided - RED FLAG"
4. Likely PASS unless price is very low

IF "SOLID" DETECTED:
1. Use normal weight estimates
2. Confidence +10 (seller being transparent)
3. Still verify with scale photo if available

IF "SEMI-HOLLOW" DETECTED:
1. Use 55% of solid weight estimate
2. Set confidence to MEDIUM (50-60)
3. Can still be profitable - calculate carefully

ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â RESIN CORE WARNING ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â
"Resin core", "resin filled", "hollow core" = thin gold shell over plastic!
- Milor Italy bangles are notorious for this
- Looks like 12-15g bracelet but actual gold is 2-4g MAX
- CANNOT be refined - resin is worthless
- INSTANT PASS on any "resin" or "hollow core" items

ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â MIXED METAL WARNING ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â
Brands like John Hardy, David Yurman, Lagos, Konstantino are SILVER with gold accents!
- "925 Silver and 18K Gold 78g" = 70-75g silver, 3-8g gold
- NEVER calculate the total weight as gold weight!
- If you see "Silver & Gold" or "925/18K" = treat as SILVER item, PASS for gold value

PEARL STRAND EXAMPLE:
- "14K Pearl Strand 24 inches" at $225
- This is 90%+ pearls by weight, clasp is 2-3g gold max
- Clasp gold value: 2.5g ÃƒÆ’Ã¢â‚¬â€ $81 = $202 melt, sell 96% = $194
- Price $225 > sell $194 = INSTANT PASS

ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â JADE/STONE BEAD NECKLACE WARNING ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â
Stone bead necklaces have gold ONLY in spacers + clasp, NOT distributed through beads!

WRONG CALCULATION:
- "14K Jade Bead Necklace 85g total"
- WRONG: 85g - 70g jade = 15g gold ÃƒÂ¢Ã‚ÂÃ…â€™
- This assumes gold is mixed with stones - IT'S NOT!

CORRECT UNDERSTANDING:
- Gold is ONLY in: clasp (2-3g) + spacer beads between stones
- Each tiny gold spacer bead = 0.3-0.5g
- A 34" necklace might have 15-20 spacers = 6-10g
- MAXIMUM gold in any bead necklace = 12-15g (generous estimate)

JADE BEAD NECKLACE EXAMPLE:
- "14K Jade 7mm Bead Necklace 34 inches" at $785
- Look at photo: jade beads with small gold spacers
- Gold content: clasp 2g + 15 spacers ÃƒÆ’Ã¢â‚¬â€ 0.5g = 9.5g gold
- Melt: 9.5g ÃƒÆ’Ã¢â‚¬â€ $81 = $769, sell $738
- $785 > sell $738 = PASS (actually a loss!)

If you see "jade/coral/turquoise bead necklace" + "mm" + no scale:
1. Estimate gold at MAX 12-15g (spacers + clasp only)
2. Do NOT calculate "total - stones = gold"
3. Confidence = LOW
4. If price > $500 = RESEARCH (needs weight verification)

=== CURRENT GOLD PRICING ({source} - {last_updated}) ===
Gold spot: ${gold_oz:,.2f}/oz = ${gold_gram:.2f}/gram pure

SCRAP RATES (what refiners pay) - USE THESE EXACT VALUES:
- 10K (41.7%): ${k10:.2f}/gram
- 14K (58.3%): ${k14:.2f}/gram  
- 18K (75.0%): ${k18:.2f}/gram
- 22K (91.7%): ${k22:.2f}/gram
- 24K (99.9%): ${k24:.2f}/gram

=== PRICING MODEL (SHOW YOUR WORK) ===
DEFINITIONS:
- meltValue = goldWeight ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â karatRate (the theoretical 100% value)
- maxBuy = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.90 (our ceiling - NEVER pay more than this)
- sellPrice = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.96 (what refiner actually pays us)
- Profit = maxBuy - listingPrice (positive = can buy, negative = PASS)

CALCULATION STEPS:
1. goldWeight = totalWeight - stoneWeight (deduct ALL stones/pearls/diamonds)
2. meltValue = goldWeight ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â karatRate
3. maxBuy = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.90
4. sellPrice = meltValue ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.96
5. Profit = maxBuy - listingPrice
6. If Profit < 0 = PASS (no exceptions!)

EXAMPLE - 18K pendant, 8.2g on scale, listed at $700:
- Gold weight: 8.2g (no stones)
- Melt: 8.2g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${k18:.2f} = ${8.2 * k18:.0f}
- maxBuy: ${8.2 * k18:.0f} ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.90 = ${8.2 * k18 * 0.90:.0f} (our ceiling)
- sellPrice: ${8.2 * k18:.0f} ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 0.96 = ${8.2 * k18 * 0.96:.0f} (what we get)
- Profit: ${8.2 * k18 * 0.96:.0f} - $700 = ${8.2 * k18 * 0.96 - 700:.0f}
- $700 < maxBuy ${8.2 * k18 * 0.90:.0f} = BUY with ${8.2 * k18 * 0.96 - 700:.0f} profit

=== WEIGHT ESTIMATION ===

=== CHAIN WEIGHT REFERENCE (CRITICAL FOR THIN CHAINS!) ===
Thin chains are VERY hard to estimate - 1g vs 2g = $82+ difference at 14K!
When estimating chain weight, be CONSERVATIVE (estimate LOW).

| Chain Type | Per Inch Weight | 18" Chain | 24" Chain |
| Very thin/delicate | 0.03-0.05g | 0.5-1g | 0.7-1.2g |
| Thin (box, snake) | 0.05-0.10g | 1-2g | 1.3-2.4g |
| Light (rope, singapore) | 0.10-0.15g | 2-3g | 2.4-3.6g |
| Medium (figaro, curb) | 0.15-0.25g | 3-5g | 3.6-6g |
| Heavy (miami cuban) | 0.3-0.5g+ | 5-9g+ | 7-12g+ |

THIN CHAIN RULE:
- If chain looks delicate/thin in photos = estimate 1-2g for typical length
- NEVER estimate thin chain over 3g without scale confirmation
- When in doubt on thin chains = RESEARCH (not BUY)

EXAMPLE - Thin 14K Box Chain, no scale:
- Looks like 18-20" thin chain
- Conservative estimate: 1.5g
- Melt: 1.5g x $82 = $123
- Max buy: $111
- If listing is $75, profit is only ~$36
- But if chain is actually 1g, profit is only $0!
- RESEARCH recommended for thin chains without scale

** SINGLE STUD EARRING **
PASS IMMEDIATELY - Single earrings have NO resale value
(If you must estimate: 0.3-0.8g gold, but PASS anyway)

** PAIR OF STUD EARRINGS **
| Type | Gold Weight |
| Small studs | 0.5-1g total |
| Medium studs | 1-2g total |
| Large studs | 2-4g total |

** DROP/DANGLE EARRINGS WITH STONES **
ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â CRITICAL: The STONE is most of the weight, NOT the gold!

DROP EARRING COMPONENTS:
- French hook/leverback: 0.3-0.5g each = 0.6-1g pair
- Setting/cap for stone: 0.2-0.5g each = 0.4-1g pair
- TOTAL GOLD: Usually 1-2g for the PAIR

STONE WEIGHT DOMINATES:
| Stone Size | Stone Weight (EACH) |
| Small drop (8mm) | 1-2g |
| Medium drop (10mm) | 2-4g |
| Large drop (12mm+) | 4-6g |
| Jade/Onyx/Opal teardrops | 3-5g each typically |

EXAMPLE - "14K Jade Drop Earrings":
- Photos show: Medium jade teardrops (~10mm each) on French hooks
- WRONG: "6g gold weight" (this would be total including jade!)
- RIGHT: Jade stones ~3g each = 6g stones, French hooks + caps = 1.5g gold
- If no scale, gold estimate: 1-2g MAX for drop earrings with visible stones
- Melt 1.5g ÃƒÆ’Ã¢â‚¬â€ $82 = $123, sell $118
- If listing > $120 on stone earrings without scale = PASS or RESEARCH

IF YOU SEE PROMINENT STONES ON EARRINGS + NO SCALE:
1. Estimate gold at 1-2g MAX (just the hooks/findings)
2. Set confidence to LOW
3. Recommend RESEARCH unless obviously profitable at 1-2g gold
4. DO NOT estimate 4-6g gold for small earrings with visible stones!

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

ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚Â WATCH SCALE PHOTOS - READ THE NUMBER! ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚ÂÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚Â
STOP! If there's a scale photo with a watch:
1. READ THE EXACT NUMBER on the scale (e.g., "4.56" means 4.56 grams!)
2. Ask yourself: Is the movement removed? (look for empty case vs visible dial/hands)
3. If movement is OUT and scale shows 4.56g ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ Gold weight = 4.56g - 0.4g glass = ~4.1g
4. Do NOT estimate "8g" when scale clearly shows "4.56g"!

LADIES WATCH GOLD WEIGHTS (realistic ranges):
- Small/petite case: 3-5g gold
- Medium case: 5-8g gold
- Large case: 8-12g gold

MEN'S WATCH GOLD WEIGHTS:
- Standard case: 8-15g gold
- Large/heavy case: 15-25g gold

If scale photo shows:
- Empty case (no hands/dial visible) = Scale weight IS the gold weight (minus ~0.4g glass)
- Complete watch (hands/dial visible) = Scale weight INCLUDES movement - deduct 3g

IF MOVEMENT/CRYSTAL STILL INSIDE (visible in photos):

MEN'S WATCH DEDUCTIONS (larger movements):
| Component | Deduct |
| Quartz movement | 3-4g |
| Mechanical movement | 5-8g |
| Crystal (glass face) | 1-2g |
| TOTAL quartz + crystal | 5-6g |
| TOTAL mechanical + crystal | 7-10g |

LADIES WATCH DEDUCTIONS (smaller movements):
| Component | Deduct |
| Movement (any type) | 2-3g |
| Crystal | 0.3-0.5g |
| TOTAL movement + crystal | 2.5-3.5g |

MEN'S WATCH EXAMPLE (Concord, Movado, dress watch):
- Seller states: "16g total with movement"
- This is a men's quartz watch
- Deduct: 5g (quartz 3.5g + crystal 1.5g)
- goldweight: "11" (NOT 13!)

EMPTY CASE (movement removed): Only deduct glass (~1g mens, ~0.5g ladies)

| Watch Type | Case Only Weight |
| Ladies small case | 2-4g |
| Ladies medium case | 4-6g |
| Mens small/thin case | 5-8g |
| Mens standard case | 8-12g |
| Mens heavy case | 12-18g |

EXAMPLE 1 - Watch with movement (complete):
- Scale shows 9g total, hands/dial visible = movement inside
- Deduct movement + crystal: 9g - 3g = 6g gold
- goldweight: "6"

EXAMPLE 2 - Watch case only (movement removed):
- Scale shows 4.56g, NO hands/dial = empty case
- Only deduct glass: 4.56g - 0.4g = 4.1g gold
- goldweight: "4.1"

LOOK FOR: If watch face is intact and you can see hands/dial, the movement is inside!

=== PEARL-HEAVY JEWELRY - CRITICAL WEIGHT DEDUCTIONS ===

PEARLS ARE HEAVY! A single large pearl can weigh MORE than all the gold in a piece!
If you see "pearl" in title or photos, STOP and carefully calculate pearl weight first!

** PEARL WEIGHT BY SIZE (memorize this!) **
| Pearl Diameter | Weight Each |
| 4mm | 0.3g |
| 5mm | 0.5g |
| 6mm | 0.8g |
| 7mm | 1.1g |
| 8mm | 1.7g |
| 9mm | 2.3g |
| 10mm | 3.0g |
| 11mm | 4.0g |
| 12mm+ | 5.0g+ |

** PEARL STRAND/NECKLACE = MOSTLY PEARLS, ALMOST NO GOLD! **
Pearl necklaces are 90-95% PEARL weight - gold is just the clasp!

- 16" choker with 7mm pearls: ~50 pearls x 1.1g = 55g PEARLS, gold clasp = 2g
- 18" strand with 8mm pearls: ~55 pearls x 1.7g = 94g PEARLS, gold clasp = 2-3g
- Total weight 40g pearl necklace? Gold is probably only 2-4g!

PEARL STRAND RULE: Gold = total weight x 0.05 to 0.10 (5-10% is gold)

ÃƒÆ’Ã‚Â¢Ãƒâ€¦Ã‚Â¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¯Ãƒâ€šÃ‚Â¸Ãƒâ€šÃ‚Â FOR PEARL STRANDS IN JSON OUTPUT:
- itemtype: "PearlNecklace"
- weight: total weight shown (e.g., "40")
- goldweight: CLASP ONLY = "2" to "3" (NOT the total weight!)
- stoneDeduction: total pearl weight (e.g., "37g pearls")
- Recommendation: Almost always PASS unless clasp gold value exceeds price

** PEARL EARRINGS - PEARLS DOMINATE THE WEIGHT! **
| Pearl Size (pair) | Total Weight | Pearl Weight | GOLD Weight |
| 6mm studs | 2.5g | 1.6g | 0.9g |
| 7mm studs | 3.5g | 2.2g | 1.3g |

=== CORD NECKLACES - ALMOST NO GOLD! ===

ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚ÂÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚ÂÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â CRITICAL: CORD ÃƒÂ¢Ã¢â‚¬Â°Ã‚Â  CHAIN! ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚ÂÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚ÂÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â

If title contains "cord", "leather", "silk", "rubber", "fabric", "string":
- The CORD is NOT gold! It's fabric/leather/rubber!
- Gold is ONLY in: clasp (1-2g) + bail (0.5g) + end caps (0.5g)
- Total gold: 2-4g MAXIMUM regardless of stated weight!

CORD NECKLACE EXAMPLE:
- Title: "14k Gold Murano Glass Fish Pendant Cord Necklace 12.7g"
- WRONG: 12.7g gold = $1,034 melt ÃƒÂ¢Ã‚ÂÃ…â€™
- CORRECT: 12.7g TOTAL, gold only in clasp/bail = 2-3g = $160-240 melt ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“

CORD NECKLACE RULE:
- Gold weight = 2-4g MAX (clasp + bail + caps)
- confidence = LOW
- If price > $200, usually PASS

=== GLASS/STONE PENDANTS - PENDANT IS NOT GOLD! ===

ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â MURANO, MILLEFIORI, GLASS, CRYSTAL PENDANTS ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â

If title mentions: "Murano", "Millefiori", "glass", "crystal pendant", "stone pendant":
- The PENDANT is glass/stone, NOT gold!
- Gold is only the BAIL (connector piece) = 0.5-2g
- Stated weight is TOTAL including heavy glass pendant!

GLASS PENDANT WEIGHTS:
| Size | Glass Weight | Gold Bail |
| 15mm | 3-5g | 0.5g |
| 25mm | 8-12g | 1g |
| 34mm | 15-25g | 1-2g |
| 50mm+ | 30g+ | 1-2g |

GLASS PENDANT EXAMPLE:
- Title: "14k Gold 34mm Murano Glass Fish Pendant 12.7g"
- Glass fish (34mm): ~10-12g
- Gold bail only: ~1-2g
- Total 12.7g checks out (glass + bail + cord)
- ACTUAL GOLD: 2-3g = ~$160-240 melt, NOT $1,034!

GLASS/STONE PENDANT RULE:
- Gold weight = bail only = 1-2g
- confidence = LOW
- Recommendation = PASS unless price < $100
| 8mm studs | 4.5g | 3.4g | 1.1g |
| 10mm studs | 7.0g | 6.0g | 1.0g |

WARNING: 8mm pearl studs at 5g = only ~1g of gold!

** PEARL PENDANT/DROP **
- 8mm pearl pendant, 4g total: pearl 1.7g, gold 2.3g
- 10mm pearl pendant, 5g total: pearl 3.0g, gold 2.0g
- 12mm pearl pendant, 7g total: pearl 5.0g, gold 2.0g

** PEARL BRACELET = TRAP! **
Multi-pearl bracelets have 20-30 pearls = almost all pearl weight!
- 7.5" bracelet with 7mm pearls: ~28 pearls x 1.1g = 31g PEARLS
- Gold links/clasp: 3-5g
- If total weight is 35g, gold is only ~4g!

** PEARL DETECTION - CHECK BEFORE ANY CALCULATION **
1. Does title say "pearl"? 
2. Do photos show round white/cream/pink spheres?
3. Is this a strand, necklace, or bracelet with pearls?
4. Count the pearls if possible, estimate size

IF PEARLS PRESENT: Deduct ALL pearl weight before calculating gold value!

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

** CRITICAL: CHUNKY CABOCHON EARRINGS - STONES DOMINATE THE WEIGHT! **
Dense stones like Tiger's Eye, Turquoise, Amber, Malachite, Lapis, Onyx, Jade:
- These stones are HEAVY (specific gravity 2.5-3.0)
- Clip-back/chunky earrings with these stones = 50-80% STONE WEIGHT
- Per earring with large cabochon: 2-3g stone, only 0.5-1.5g gold
- EXAMPLE: "8.5g Tiger's Eye 9K earrings" = ~5-6g stones, only 2.5-3.5g gold
- At 9K (37.5%): 3g gold = 1.1g pure = ~$95 melt, NOT $300+!

RULE: If earrings have chunky/large cabochon stones, deduct 50-70% of total weight for stones!

** CRITICAL: BROOCHES WITH LARGE STONES - STONE IS MOST OF THE WEIGHT! **
Agate, Carnelian, Jasper, Onyx, Chalcedony, Malachite - all dense stones (~2.6 g/cm³)
- Brooch frame is THIN METAL wrapped around the stone!
- A 1.5" brooch with large stone: Frame is typically only 2-4g gold
- EXAMPLE: "8.87g Edwardian 9K agate brooch" = ~5-6g agate + 2-3g gold frame
- At 9K (37.5%): 2.5g gold = 0.94g pure = ~$140 melt, NOT $350+!

RULE: If brooch features a large cabochon/agate stone, deduct 50-70% for stone weight!

EXAMPLE - 14K chain with pearl pendant (like in photos):
- Scale shows 4.84g total WITH the pearl
- Pearl visible ~10mm = deduct 2g
- Gold weight: 4.84 - 2 = 2.84g
- Melt: 2.84g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${k14:.2f} = ${2.84 * k14:.0f}
- maxBuy: ${2.84 * k14 * 0.90:.0f}
- At $300 list: Margin = ${2.84 * k14 * 0.90:.0f} - $300 = -${300 - 2.84 * k14 * 0.90:.0f} = PASS

=== ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â MIXED KARAT LOTS - CALCULATE EACH ITEM SEPARATELY ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¯ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ===

When a listing has MULTIPLE items with DIFFERENT KARATS and STATED WEIGHTS:
**DO NOT average the karats!** Calculate each piece separately and ADD them up.

EXAMPLE - Mixed lot with stated weights:
Listing says: "1.2g 18K earrings, 3.9g 10K charm, 1.5g 14K charms"

WRONG: Total 6.6g at "average 14K" = WRONG!

RIGHT: Calculate EACH item:
- 1.2g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${k18:.2f} (18K) = ${1.2 * k18:.0f}
- 3.9g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${k10:.2f} (10K) = ${3.9 * k10:.0f}
- 1.5g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ${k14:.2f} (14K) = ${1.5 * k14:.0f}
- TOTAL MELT = ${1.2 * k18 + 3.9 * k10 + 1.5 * k14:.0f}
- maxBuy (90%) = ${(1.2 * k18 + 3.9 * k10 + 1.5 * k14) * 0.90:.0f}
- sellPrice (96%) = ${(1.2 * k18 + 3.9 * k10 + 1.5 * k14) * 0.96:.0f}

WHEN TO CALCULATE SEPARATELY:
- Description lists SPECIFIC weights for EACH karat (like above)
- Multiple items with different karats visible in photos

WHEN TO USE 14K AVERAGE:
- "Mixed lot mostly 14K" with NO individual weights
- Bulk scrap where karats can't be identified per piece

For the karat field in JSON, use: "10K/14K/18K" (slash-separated list)

=== CONFIDENCE SCORING (0-100) - MUST BE A NUMBER! ===
Start at 60, then adjust:

WEIGHT SOURCE IS CRITICAL:
- Scale photo = weightSource "scale" -> START at 75
- Seller stated weight = weightSource "stated" -> START at 70
- You estimated weight = weightSource "estimate" -> START at 45 (LOW!)

=== CRITICAL: DECISION LOGIC FOR ESTIMATED WEIGHT ===
When weight is ESTIMATED (not from scale or seller stated):

*** ABSOLUTE RULE: ESTIMATED WEIGHT = CANNOT BE BUY ***
If weightSource = "estimate", your Recommendation CANNOT be "BUY"!
- ESTIMATED weight means we're GUESSING - guessing wrong loses money
- Only RESEARCH or PASS are valid for estimated weights
- BUY requires VERIFIED weight (scale photo or seller stated weight)

1. PASS if price is clearly too high:
   - Calculate the MAXIMUM possible melt value (generous weight estimate)
   - If listing price > maximum possible melt value = PASS (not RESEARCH!)
   - Example: Ring could be 5-15g max. At 15g 14K = $1200 melt. Price $1800 = PASS
   - Example: Pearl necklace has maybe 3-5g gold clasp. Price $500 = PASS

2. RESEARCH if profit is uncertain (DEFAULT for estimated weight):
   - Price is in the "maybe profitable" range depending on actual weight
   - Could be a deal OR a loss - need to verify weight first
   - Example: Ring could be 8-15g. At 10g = loss, at 15g = profit. RESEARCH.
   - THIS IS THE CORRECT RESPONSE WHEN WEIGHT IS ESTIMATED!

3. BUY ONLY with verified weight:
   - Scale photo shows exact weight (weightSource = "scale")
   - Seller states weight in title/description (weightSource = "stated")
   - Math clearly shows profit with verified numbers
   - NEVER BUY with weightSource = "estimate"!

ENFORCEMENT:
- If you set weightSource = "estimate" AND Recommendation = "BUY" = YOU ARE WRONG!
- Server will override BUY to RESEARCH when weight is estimated
- Train yourself: estimated weight = RESEARCH at best, never BUY

SIMPLE RULE: 
- Price way too high for ANY reasonable weight = PASS
- Price might work if weight is on high end = RESEARCH  
- Price works with VERIFIED weight = BUY

DO NOT use RESEARCH as a "safe default" - if the price is obviously too high, say PASS!


INCREASES:
| Factor | Add |
| Weight shown on scale photo | +15 |
| Clear karat stamp visible | +10 |
| Vintage/antique piece | +5 |
| Known maker visible | +5 |
| Multiple items in scrap lot | +5 |

DECREASES:
| Factor | Subtract |
| ESTIMATED weight (no scale/stated) | -20 |
| High-risk chain style (Cuban, Rope) | -15 |
| New seller (<50 feedback) | -10 |
| Stock photos only | -10 |
| Stone visible but size uncertain | -10 |
| Single item, no scale | -10 |

Final score: 0-100 (output as INTEGER like 45 or 75, NOT "High"!)

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
Single karat: "DETECTION: [karat], [item type], [SCALE: X.XXg] or [EST: Xg] | STONES: [deduction or None] | CALC: [gold wt]g ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â $[rate] = $[melt], sell 96% = $[sell], list $[price] | PROFIT: $[sell - price] | DECISION: [BUY/PASS] [why]"

MIXED LOT: "DETECTION: Mixed lot [karats] with STATED weights | CALC: 1.2gÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â18K=$77 + 3.9gÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â10K=$139 + 1.5gÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â14K=$75 = $291 melt, sell 96% = $279, list $450 | PROFIT: $279-$450 = -$171 | DECISION: PASS price exceeds melt"

=== JSON OUTPUT (ALL REQUIRED - MUST HAVE ACTUAL VALUES) ===
- Qualify: "Yes"/"No"
- Recommendation: "BUY"/"PASS" (PASS if listingPrice > maxBuy, or instant pass condition)
- verified: "Yes"/"No"/"Unknown"
- karat: "10K"/"14K"/"18K"/"22K"/"24K" or "10K/14K/18K" for mixed lots (slash-separated)
- itemtype: "Ring"/"Chain"/"Bracelet"/"Earrings"/"Pendant"/"Watch"/"Scrap"/"Plated"/"MixedLot"/"BeadNecklace"/"PearlNecklace"/"PearlEarrings" (Pearl items = heavy deduction needed!)
- weightSource: "scale" (if read from scale photo) or "stated" (if seller specified) or "estimate"
- weight: total weight like "6.6" for mixed lots, or individual weight for single items
- mixedCalc: FOR MIXED LOTS ONLY - show breakdown like "1.2gÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â18K=$77 + 3.9gÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â10K=$139 + 1.5gÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â14K=$75 = $291" or "NA"
- stoneDeduction: "2.5g pearl" or "0.5g diamond" or "3g pearls (2x8mm)" or "0" or "NA" - INCLUDE PEARL DEDUCTIONS HERE!
- watchDeduction: "3g movement+crystal" or "0" or "NA"
- goldweight: weight after ALL deductions including pearls (MUST BE A NUMBER like "6.6")
- meltvalue: calculated melt (FOR MIXED LOTS: sum of individual calculations)
- maxBuy: meltvalue ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 0.90 (MUST BE A NUMBER - this is our ceiling)
- sellPrice: meltvalue ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 0.96 (MUST BE A NUMBER - what refiner pays us)
- Profit: sellPrice - listingPrice (MUST BE A NUMBER like "-172" or "+50")
- confidence: INTEGER 0-100 (NOT "High"!) - if weightSource="estimate" MAXIMUM is 50, if "scale" start at 75
- confidenceBreakdown: "Base 60 + scale 15 + karat visible 10 = 85" OR "Base 40 (estimated weight cap) - no karat 10 = 30"
- fakerisk: "High"/"Medium"/"Low"
- reasoning: MUST show DETECTION | CALC (with breakdown for mixed!) | PROFIT | DECISION

CRITICAL: 
- meltvalue, maxBuy, sellPrice, Profit MUST be actual numbers, NOT "$--" or "NA"!
- confidence MUST be a number like 75, NOT a word like "High"!
- Profit = sellPrice (96% of melt) - listingPrice
- FOR MIXED KARAT LOTS: Calculate EACH piece at its karat rate, then SUM totals!
- DO NOT average karats when individual weights are stated!
- PEARL ITEMS: Always deduct pearl weight! 8mm pearl = 1.7g, 10mm = 3g!

=== FINAL RULES ===
1. If listingPrice > maxBuy = ALWAYS PASS (price exceeds our ceiling)
2. Single earring = ALWAYS PASS
3. Diamond jewelry where gold alone doesn't justify price = PASS
4. We pay for GOLD WEIGHT ONLY, never for stones or designer names
5. When in doubt, estimate LOW on gold weight
6. Watches with movement/crystal inside = DEDUCT 3g
7. READ THE SCALE NUMBER AND UNIT CAREFULLY - check for "g" vs "ct" vs "dwt"!
8. MIXED LOTS: Calculate each karat separately, then add totals!
9. STONE-HEAVY PIECES (bead necklaces): Gold is only clasp (3-5g), not total weight!
10. If scale shows "ct" mode or description says "cttw" = STONE-HEAVY, gold is minimal!
11. PEARL ITEMS: Deduct pearl weight FIRST! Pearl strand = gold is only 2-4g clasp!
12. PEARL EARRINGS/PENDANTS: Pearl weight dominates! 8mm pearl studs 5g total = only 1g gold!

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# LEGO PROMPT
# ============================================================

LEGO_PROMPT = """
Analyze this LEGO listing and return JSON.

=== BUYING RULES ===
- Target: 65% of market price or under
- SEALED/NEW sets ONLY (factory sealed box required!)
- Focus on retired sets (higher value)
- Walmart and eBay are our sales channels

=== INSTANT PASS - NO EXCEPTIONS ===
CONDITION ISSUES (we only buy SEALED):
- "open box", "opened", "box opened"
- "no box", "missing box", "without box", "box only"
- "no instructions", "missing instructions"
- "incomplete", "partial", "missing pieces", "missing parts"
- "used", "played with", "pre-owned", "previously owned"
- "built", "assembled", "complete build", "displayed"
- "bulk", "loose", "bricks only", "parts only"
- "damaged box", "box damage", "crushed", "dented", "torn"
- "minifigures only", "minifig lot", "figures only"

KNOCKOFFS (not real LEGO):
- Mega Bloks, Lepin, Cobi, King, SY, Decool, Bela, Kazi
- "compatible with LEGO", "fits LEGO", "not LEGO", "like LEGO"
- "building blocks" (generic term = usually knockoff)
- "MOC", "custom", "modified"

If ANY of these terms appear in title/description = INSTANT PASS, Qualify = "No"

=== HIGH VALUE THEMES ===
- Star Wars (especially UCS sets)
- Harry Potter
- Marvel/DC Super Heroes
- Creator Expert/Icons
- Technic (large sets)
- Ideas/Cuusoo
- Modular Buildings

=== PRICING GUIDANCE ===
If PriceCharting data is provided above, USE THOSE PRICES.
Otherwise estimate based on:
- Retail price ÃƒÆ’Ã¢â‚¬â€ 0.8-1.5 depending on retirement status
- Retired sets typically 1.5-3ÃƒÆ’Ã¢â‚¬â€ retail
- UCS/large sets hold value best

=== FAKE/KNOCKOFF WARNING SIGNS ===
- Price too good to be true (50%+ below market)
- Stock photos only
- Seller in China with very low prices
- Missing LEGO logo in photos
- Poor print quality on box

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [set info, theme, condition] | CONCERNS: [red flags or none] | CALC: Market ~$[X], 65% = $[Y], list $[Z] = [margin] | DECISION: [BUY/PASS/RESEARCH] [rationale]"

=== JSON KEYS (EXACT - case sensitive) ===
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- SetNumber: LEGO set number like "75192" or "Unknown"
- SetName: Name of the set like "Millennium Falcon" or "Unknown"
- Theme: "Star Wars"/"Harry Potter"/"Marvel"/"Technic"/"Creator"/"City"/"Other"
- Retired: "Yes" or "No" or "Unknown"
- SetCount: Number of sets as string like "1" or "3"
- marketprice: Estimated market value as number string like "849" or "Unknown"
- maxBuy: 65% of market price as number string like "552" or "NA"
- Margin: maxBuy minus listing price like "+150" or "-50" or "NA"
- confidence: "High" or "Medium" or "Low"
- fakerisk: "High" or "Medium" or "Low"
- reasoning: MUST include DETECTION | CONCERNS | CALC | DECISION sections

=== OUTPUT RULES ===
Return ONLY a single line JSON object.
No markdown. No code blocks. No explanation before or after.
If Margin is NEGATIVE, Recommendation MUST be "PASS".
If item is OPENED/USED/INCOMPLETE = PASS and Qualify = "No"

=== EXAMPLE OUTPUT ===
{"Qualify":"Yes","Recommendation":"BUY","SetNumber":"75192","SetName":"Millennium Falcon","Theme":"Star Wars","Retired":"Yes","SetCount":"1","marketprice":"849","maxBuy":"552","Margin":"+152","confidence":"High","fakerisk":"Low","reasoning":"DETECTION: UCS Millennium Falcon 75192, sealed, Star Wars theme | CONCERNS: None, authentic LEGO packaging visible | CALC: Market ~$849, 65% = $552, list $400 = +$152 | DECISION: BUY strong margin on desirable retired set"}

OUTPUT ONLY THE JSON. NOTHING ELSE.
"""


# ============================================================
# TCG PROMPT
# ============================================================

TCG_PROMPT = """
Analyze this TCG (Trading Card Game) sealed product listing and return JSON.

=== CRITICAL: QUANTITY DETECTION ===
DEFAULT TO 1 ITEM unless the title EXPLICITLY states multiple items.

ONLY count as multiple if title contains:
- "x2", "x3", "2x", "3x" 
- "lot of 2", "bundle of 2", "set of 2"
- "2 boxes", "3 ETBs", "two booster boxes"
- EXPLICIT quantity words

DO NOT assume multiple items from:
- Pack counts (36 packs = 1 booster box, NOT 36 items)
- Card counts (9 packs in ETB = 1 ETB, NOT 9 items)
- Vague wording

When in doubt, ItemCount = "1"

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
- "Mystery" or "repack" products

=== HIGH VALUE SETS (Pokemon) ===
Vintage WOTC (1999-2003): Base Set, Jungle, Fossil, Team Rocket, Neo series
Modern Hits: Evolving Skies, Hidden Fates, Champion's Path, Celebrations, 151

=== FAKE/REPACK WARNING SIGNS ===
- Price too good to be true (50%+ below market)
- Stock photos only
- New seller, no history
- "Mystery" or "repack" in title
- Shrink wrap looks wrong

=== REASONING FORMAT (REQUIRED) ===
"DETECTION: [product type], [set name], [condition], [language] | CONCERNS: [red flags or none] | CALC: Market ~$[X], 65% = $[Y], list $[Z] = [margin] | DECISION: [BUY/PASS/RESEARCH] [rationale]"

=== JSON KEYS (EXACT - case sensitive) ===
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- TCG: "Pokemon" or "YuGiOh" or "MTG" or "OnePiece" or "Lorcana" or "Other"
- ProductType: "BoosterBox" or "ETB" or "Bundle" or "CollectionBox" or "Pack" or "Case" or "Other"
- SetName: Name of the set like "Evolving Skies" or "Unknown"
- ItemCount: Number of items as string like "1" or "6" (for cases)
- marketprice: Estimated market value as number string like "285" or "Unknown"
- maxBuy: 65% of market price as number string like "185" or "NA"
- Margin: maxBuy minus listing price like "+50" or "-20" or "NA"
- confidence: "High" or "Medium" or "Low"
- fakerisk: "High" or "Medium" or "Low"
- reasoning: MUST include DETECTION | CONCERNS | CALC | DECISION sections

=== OUTPUT RULES ===
Return ONLY a single line JSON object.
No markdown. No code blocks. No explanation before or after.
If Margin is NEGATIVE, Recommendation MUST be "PASS".
If PriceCharting data is provided above, USE THOSE PRICES for calculations.

=== EXAMPLE OUTPUT ===
{"Qualify":"Yes","Recommendation":"BUY","TCG":"Pokemon","ProductType":"BoosterBox","SetName":"Evolving Skies","ItemCount":"1","marketprice":"285","maxBuy":"185","Margin":"+35","confidence":"High","fakerisk":"Low","reasoning":"DETECTION: Pokemon Evolving Skies Booster Box, sealed, English | CONCERNS: None, factory sealed visible | CALC: Market ~$285, 65% = $185, list $150 = +$35 | DECISION: BUY good margin on popular set"}

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

=== CORE STRATEGY ===
DEFAULT: RESEARCH - Costume jewelry requires careful visual analysis
Only auto-BUY on strong positive signals. When in doubt, RESEARCH.

We buy THREE types:
1. TRIFARI - Premium vintage costume brand (our specialty)
2. QUALITY LOTS - High piece count with visible quality indicators  
3. SPECIAL ITEMS - Bakelite, quality cameos, rare designers

=== TRIFARI IDENTIFIER DATABASE ===

** TRIFARI MARKS (HOW TO DATE) **
| Mark | Era | Value Tier |
| Crown over T | 1940s-1960s | PREMIUM ($40-300+) |
| Crown Trifari ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© | 1950s-1968 | HIGH ($35-200) |
| Trifari ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© | 1960s-1970s | MEDIUM ($20-80) |
| Trifari TM | Post-1975 | STANDARD ($15-40) |
| Trifari (script) | 1930s-1940s | VERY HIGH ($50-400) |

** VALUABLE TRIFARI COLLECTIONS **
| Collection | Years | Value | Identifiers |
| Jelly Belly | 1940s-50s | $100-500+ | Lucite bellies on animals/insects |
| Fruit Salad | 1940s | $80-300+ | Colored carved glass "fruit" stones |
| Alfred Philippe | 1930s-50s | $80-400+ | Patent numbers, signed pieces |
| Ming | 1960s | $60-150 | Asian-inspired, jade-like stones |
| Cavalcade | 1950s | $50-120 | Modernist, abstract designs |
| Moonstone/Lucite | 1950s-60s | $40-100 | Glowing moonstone cabochons |
| Invisibly Set | 1950s | $60-200 | No visible prongs on stones |
| Pet Series | 1960s | $35-80 | Animals without jelly bellies |
| Florentine | 1960s-70s | $25-60 | Textured gold-tone finish |
| L'Orient | 1968 | $50-150 | Eastern inspired, colorful |

** STERLING TRIFARI (1940s) - PREMIUM **
During WWII, Trifari used sterling silver instead of base metal.
- Marked "STERLING" with Trifari mark
- Value: $50-200+ (silver content + collectibility)
- Look for: Retro designs, large rhinestones, heavy weight

** JELLY BELLY GUIDE (Most Valuable) **
| Animal | Typical Value | Notes |
| Rooster | $200-400 | Most common, still valuable |
| Fish | $150-350 | Various designs |
| Duck | $150-300 | |
| Bird on Branch | $150-350 | |
| Elephant | $200-400 | Less common |
| Turtle | $250-500 | Rare |
| Frog | $300-500+ | Rare |
| Spider | $400-600+ | Very rare |
| Fly | $300-500+ | Rare |

** TRIFARI RED FLAGS **
- "Trifari style" or "like Trifari" = NOT AUTHENTIC
- "Unsigned but Trifari" = SKIP (probably not)
- Missing clasp/broken = deduct 50% value
- Heavy tarnish = deduct 20-30%
- Missing stones = PASS unless priced accordingly
- Chinese reproductions (modern jelly bellies flooding market)

=== DESIGNER TIER SYSTEM ===

** TIER 1 - ALWAYS CONSIDER (Premium Vintage) **
- Trifari (especially Crown mark)
- Eisenberg Original (not Ice)
- Miriam Haskell
- Schreiner
- Hobe
Value: $40-500+ per piece

** TIER 2 - GOOD VALUE (Mid-Tier Vintage) **
- Weiss
- Juliana/DeLizza & Elster
- Coro (especially Duette)
- Eisenberg Ice
- Kramer
- Lisner
- Vendome
- Sherman (Canadian, rhinestones)
Value: $20-100 per piece

** TIER 3 - VOLUME ONLY (Lower Value) **
- Monet
- Napier
- Sarah Coventry
- Avon
- Emmons
- Coventry
Value: $5-25 per piece (buy in lots only)

** TIER 4 - GENERALLY PASS **
- Fashion brands (Forever 21, H&M, Claire's, Icing)
- Unbranded modern
- "Boutique" jewelry
- Etsy-style handmade
Value: $1-5 (not worth handling)

=== LOT QUALITY SCORING (VISUAL ANALYSIS) ===

Look at photos and score the lot:

** POSITIVE INDICATORS (+points) **
| Factor | Points | What to Look For |
| Signed pieces visible | +15 | See maker marks in photos |
| Vintage construction | +10 | Prong settings, quality clasps |
| Rhinestones intact/sparkly | +10 | No missing stones, good clarity |
| Brooches present | +10 | Higher value than necklaces |
| Aurora borealis stones | +5 | Iridescent/rainbow rhinestones |
| Enamel work | +5 | Colorful, detailed enamelwork |
| Heavy/substantial pieces | +5 | Quality feel, not flimsy |
| Gold-tone (not silver) | +5 | More desirable era usually |
| Bakelite pieces visible | +15 | Test with photos if possible |

** NEGATIVE INDICATORS (-points) **
| Factor | Points | What to Look For |
| Tarnish/green patina | -10 | Green corrosion, dark oxidation |
| Missing stones visible | -15 | Empty prong settings |
| Broken pieces | -10 | Damaged, incomplete items |
| Cheap chain necklaces | -10 | Low-value filler items |
| Plastic beads dominant | -10 | Modern, low quality |
| Sarah Cov/Avon dominant | -5 | Lower tier designers |
| Modern look | -15 | Contemporary mass-produced |
| Poor photos (can't assess) | -10 | Risk factor |
| "Mystery" or grab bag | -20 | Never buy blind |

** LOT DECISION MATRIX **
| Quality Score | Price/Piece | Recommendation |
| 30+ points | Under $2.00 | BUY |
| 30+ points | $2-3.00 | RESEARCH |
| 20-29 points | Under $1.50 | BUY |
| 20-29 points | $1.50-2.50 | RESEARCH |
| 10-19 points | Under $1.00 | BUY |
| 10-19 points | $1-2.00 | RESEARCH |
| Under 10 | Any price | PASS |

=== BAKELITE IDENTIFICATION ===
Genuine vintage Bakelite is valuable ($25-150+ per piece)

** BAKELITE COLORS (most to least valuable) **
1. Red/Cherry - $40-150+
2. Apple Juice (transparent yellow) - $30-100+
3. Butterscotch - $25-80
4. Green (dark, marbled) - $30-100
5. Black - $20-50
6. Cream/Ivory - $15-40

** BAKELITE RED FLAGS **
- "Bakelite style" = NOT BAKELITE
- Perfect condition modern pieces = likely Fakelite
- Bright unnatural colors = probably plastic
- Very lightweight = not Bakelite

=== CAMEO BUYING ===
| Type | Value | Notes |
| Shell cameo, Victorian | $50-200+ | Look for quality carving |
| Shell cameo, vintage | $25-75 | Common but sellable |
| Hardstone cameo | $100-500+ | Agate, onyx, etc. |
| Glass/plastic cameo | $5-20 | Pass unless bulk |
| Wedgwood jasperware | $40-150 | Blue & white ceramic |

=== INSTANT PASS CONDITIONS ===
- Single unsigned pieces (no designer ID)
- Price over $60 without premium indicators
- Modern fashion brands (Tier 4)
- Broken beyond reasonable repair
- "Mystery" lots with no photos
- Lots dominated by chain necklaces
- Quality score under 10 points

=== INSTANT BUY CONDITIONS ===
- Crown Trifari at under $40 (in good condition)
- Jelly Belly pieces under $100
- Sterling Trifari under $60
- Confirmed Bakelite under $30
- Quality lot (30+ score) under $1.50/piece

=== DEFAULT BEHAVIOR ===
When uncertain: RESEARCH
This category requires human review for edge cases.
Only output BUY for clear wins, PASS for clear losses.

=== JSON KEYS ===
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- itemtype: "Trifari" or "Lot" or "Cameo" or "Bakelite" or "Designer" or "Other"
- pieceCount: Number of pieces as string
- pricePerPiece: Calculated price per piece
- designer: Specific designer if identified, or "Various" or "None"
- designerTier: "1" or "2" or "3" or "4" or "Unknown"
- hasTrifari: "Yes" or "No" or "Maybe"
- trifariCollection: If Trifari, which collection? (e.g., "Jelly Belly", "Crown", "Standard")
- qualityScore: Lot quality score (sum of +/- indicators)
- positiveIndicators: What good things you see
- negativeIndicators: What concerns you see
- estimatedvalue: Your estimate of resale value
- EV: Expected profit like "+25" or "-10"
- confidence: "High" or "Medium" or "Low"
- reasoning: DETECTION: [what] | QUALITY: [score breakdown] | DECISION: [rationale]

=== EXAMPLE OUTPUTS ===

Crown Trifari jelly belly at $85:
{"Qualify":"Yes","Recommendation":"BUY","itemtype":"Trifari","pieceCount":"1","pricePerPiece":"85","designer":"Crown Trifari","designerTier":"1","hasTrifari":"Yes","trifariCollection":"Jelly Belly","qualityScore":"40","positiveIndicators":"Crown mark visible, lucite belly intact, vintage patina","negativeIndicators":"None","estimatedvalue":"180","EV":"+95","confidence":"High","reasoning":"DETECTION: Crown Trifari jelly belly rooster | QUALITY: Premium collectible | DECISION: BUY clear value"}

Mixed lot 40 pieces at $45:
{"Qualify":"Yes","Recommendation":"RESEARCH","itemtype":"Lot","pieceCount":"40","pricePerPiece":"1.13","designer":"Various","designerTier":"Mixed","hasTrifari":"Maybe","trifariCollection":"NA","qualityScore":"22","positiveIndicators":"Several signed pieces visible, brooches present, vintage look","negativeIndicators":"Some tarnish, few chain necklaces","estimatedvalue":"70","EV":"+25","confidence":"Medium","reasoning":"DETECTION: Mixed vintage lot | QUALITY: Score 22 (signed +15, brooches +10, tarnish -10, chains -5) | DECISION: RESEARCH - decent lot but verify signed pieces"}

Modern fashion lot at $30:
{"Qualify":"No","Recommendation":"PASS","itemtype":"Lot","pieceCount":"25","pricePerPiece":"1.20","designer":"None","designerTier":"4","hasTrifari":"No","trifariCollection":"NA","qualityScore":"-5","positiveIndicators":"None","negativeIndicators":"Modern look, plastic beads, cheap construction","estimatedvalue":"15","EV":"-15","confidence":"High","reasoning":"DETECTION: Modern fashion jewelry | QUALITY: Score -5 (modern -15, plastic -10) | DECISION: PASS no vintage value"}

OUTPUT ONLY VALID JSON. NO OTHER TEXT.
"""


# ============================================================
# VIDEO GAMES PROMPT
# ============================================================

VIDEO_GAMES_PROMPT = """
Analyze this video game listing and return JSON.

=== BUYING RULES ===
- Target: 65% of market price or under
- Focus on: CIB (Complete In Box), Sealed/New games
- Loose games need higher margin (harder to sell)

=== CONDITION TIERS (Critical for pricing!) ===
- Loose: Cart/disc only, no box or manual (lowest value)
- CIB: Complete In Box - game, box, manual all present (2-3x loose price)
- New/Sealed: Factory sealed, never opened (5-10x loose price for valuable games)

=== CONSOLE DETECTION ===
Identify the console from title:
- Nintendo: NES, SNES, N64, GameCube, Wii, Wii U, Switch, Game Boy, GBA, DS, 3DS
- Sega: Genesis/Mega Drive, Saturn, Dreamcast, Game Gear, Master System
- Sony: PS1/PSX, PS2, PS3, PS4, PS5, PSP, Vita
- Microsoft: Xbox, Xbox 360, Xbox One, Xbox Series X/S
- Other: Atari, TurboGrafx-16, Neo Geo, 3DO

=== FAKE/REPRODUCTION WARNING ===
HIGH RISK consoles (reproductions very common):
- SNES, GBA, DS, Game Boy (especially Pokemon games!)
- NES (popular titles)

Warning signs:
- "Reproduction", "Repro", "Custom", "Homebrew"
- Ships from China/Hong Kong
- Price too good to be true on valuable games
- New/perfect condition on 20+ year old games

=== LOT DETECTION ===
If listing contains multiple games:
- Extract game count if possible
- Calculate per-game average
- Large lots (10+) need RESEARCH for individual game values

=== REASONING FORMAT ===
"DETECTION: [console], [game title], [condition] | CONCERNS: [fakes/condition issues or none] | CALC: Market ~$[X], 65% = $[Y], list $[Z] = [margin] | DECISION: [BUY/PASS/RESEARCH] [rationale]"

=== JSON KEYS ===
- Qualify: "Yes" or "No"
- Recommendation: "BUY" or "PASS" or "RESEARCH"
- console: "NES", "SNES", "N64", "Genesis", "PS1", "PS2", etc.
- gameTitle: Name of the game
- condition: "Loose", "CIB", "New", "Unknown"
- isLot: "Yes" or "No"
- lotCount: Number of games if lot, "1" otherwise
- marketprice: Estimated market value for this condition
- maxBuy: 65% of market as string
- Margin: maxBuy minus listing price like "+50" or "-20"
- confidence: "High", "Medium", or "Low"
- fakerisk: "High", "Medium", or "Low"
- reasoning: MUST include DETECTION | CONCERNS | CALC | DECISION

=== PRICING GUIDANCE ===
Without PriceCharting data, estimate conservatively:
- Common games (sports, movie tie-ins): $5-15 CIB
- Popular titles (Mario, Zelda, Pokemon): $30-100+ CIB depending on specific game
- Rare/valuable: $100+ (research required)

If unsure of value, recommend RESEARCH.

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
    elif category == "coin_scrap":
        return get_coin_prompt()
    elif category == "lego":
        return LEGO_PROMPT
    elif category == "tcg":
        return TCG_PROMPT
    elif category == "coral":
        return CORAL_AMBER_PROMPT
    elif category == "costume":
        return COSTUME_PROMPT
    elif category == "videogames":
        return VIDEO_GAMES_PROMPT
    else:
        return get_silver_prompt()  # Default


def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    # Normalize title: replace URL encoding (+, %20) with spaces
    title = data.get("Title", "").lower().replace('+', ' ').replace('%20', ' ')
    reasons = []

    # Define keywords
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "karat", "gold nugget", "placer gold",
                     "raw gold", "dental gold", "dental scrap", "8k", "9k", "750 gold", "585 gold",
                     "417 gold", "375 gold", "solid gold", "scrap gold", "gold grams"]
    silver_keywords = ["sterling", "925", ".925"]
    platinum_keywords = ["platinum", "pt950", "pt900", "pt850", "950 plat", "900 plat", "iridium plat"]
    palladium_keywords = ["palladium", "pd950", "pd500", "950 palladium"]
    coin_scrap_keywords = ["junk silver", "90% silver", "constitutional silver", "pre-1965 silver",
                           "silver coin lot", "morgan lot", "peace dollar lot", "walking liberty lot",
                           "mercury dime lot", "silver quarter lot", "silver half lot"]

    # NON-PRECIOUS METAL items that might appear in gold/silver searches
    # These should NEVER be routed to gold/silver agents
    knife_keywords = ["pocket knife", "folding knife", "case xx", "buck knife", "kershaw", "benchmade",
                      "spyderco", "knife lot", "hunting knife", "switchblade", "bowie knife", "swiss army"]
    book_keywords = ["book", "linen book", "picture book", "first edition", "hardcover", "paperback",
                     "magazine", "comic", "novel", "encyclopedia", "dictionary"]
    figurine_keywords = ["figurine", "porcelain", "ceramic", "statue", "sculpture", "hummel", "lladro",
                         "precious moments", "department 56", "lenox"]
    collectible_keywords = ["peanut butter jar", "cookie jar", "mason jar", "ball jar", "canning jar",
                            "daguerreotype", "tintype", "photograph", "photo lot", "postcard",
                            "disney", "mickey mouse", "pluto", "floaty pen", "souvenir", "memorabilia",
                            "vintage toy", "tin toy", "cast iron", "advertising sign", "neon sign"]
    watch_keywords = ["watch", "wristwatch", "pocket watch", "chronograph", "automatic watch", "seiko",
                      "omega", "rolex", "timex", "bulova", "hamilton", "citizen"]

    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    platinum_matches = [kw for kw in platinum_keywords if kw in title]
    palladium_matches = [kw for kw in palladium_keywords if kw in title]
    coin_scrap_matches = [kw for kw in coin_scrap_keywords if kw in title]
    knife_matches = [kw for kw in knife_keywords if kw in title]
    book_matches = [kw for kw in book_keywords if kw in title]
    figurine_matches = [kw for kw in figurine_keywords if kw in title]
    collectible_matches = [kw for kw in collectible_keywords if kw in title]
    watch_matches = [kw for kw in watch_keywords if kw in title]

    # ============================================================
    # PRIORITY -1: EARLY EXCLUSIONS - Non-precious items in gold/silver searches
    # These should NEVER go to gold/silver agents even if alias says "Gold"
    # ============================================================

    # If item has NO gold/silver keywords but HAS non-precious keywords, route elsewhere
    has_precious_metal = bool(gold_matches or silver_matches or platinum_matches or palladium_matches)

    if not has_precious_metal:
        # Knives - route to knives category
        if knife_matches:
            reasons.append(f"EXCLUSION: Knife detected ({knife_matches}) with NO precious metal keywords - routing to knives")
            return "knives", reasons

        # Watches - route to watch category
        if watch_matches:
            reasons.append(f"EXCLUSION: Watch detected ({watch_matches}) with NO precious metal keywords - routing to watch")
            return "watch", reasons

        # Books, figurines, collectibles - these aren't arbitrage categories, PASS them
        if book_matches:
            reasons.append(f"EXCLUSION: Book detected ({book_matches}) - not an arbitrage category, routing to collectibles")
            return "collectibles", reasons
        if figurine_matches:
            reasons.append(f"EXCLUSION: Figurine detected ({figurine_matches}) - not an arbitrage category, routing to collectibles")
            return "collectibles", reasons
        if collectible_matches:
            reasons.append(f"EXCLUSION: Collectible detected ({collectible_matches}) - not an arbitrage category, routing to collectibles")
            return "collectibles", reasons

    # ============================================================
    # PRIORITY 0: Known mixed-metal brands = ALWAYS SILVER
    # These brands are primarily sterling silver with gold accents
    # ============================================================
    mixed_metal_brands = ['john hardy', 'david yurman', 'lagos', 'konstantino', 'andrea candela']
    for brand in mixed_metal_brands:
        if brand in title:
            reasons.append(f"Known mixed-metal brand '{brand}' detected - these are primarily SILVER with gold accents")
            return "silver", reasons
    
    # ============================================================
    # PRIORITY 1: Sterling/Silver + Gold combo = ALWAYS SILVER
    # This overrides alias because the gold is just accent, not the main metal
    # Mixed metal pieces (John Hardy, David Yurman, etc.) are primarily silver
    # ============================================================
    
    # Check for "silver" as a standalone word (not just sterling/925)
    has_silver_word = ' silver ' in f' {title} ' or title.startswith('silver ') or title.endswith(' silver')
    has_silver_word = has_silver_word or 'silver &' in title or '& silver' in title or 'silver and' in title or 'and silver' in title
    
    if (silver_matches or has_silver_word) and gold_matches:
        reasons.append(f"Title has BOTH silver AND gold ({gold_matches}) - mixed metal = treating as SILVER (gold is accent only)")
        return "silver", reasons
    
    # ============================================================
    # PRIORITY 2: Check Alias (user's search intent)
    # BUT validate that precious metal keywords are actually in the title
    # ============================================================
    if "platinum" in alias:
        if platinum_matches or "plat" in title:
            reasons.append(f"Alias contains 'platinum' AND title has platinum: {data.get('Alias', '')}")
            return "platinum", reasons
        # Alias says platinum but title doesn't - fall through to title-based detection
        reasons.append(f"Alias says platinum but title has no platinum keywords - will check title")
    elif "palladium" in alias:
        if palladium_matches or "pallad" in title:
            reasons.append(f"Alias contains 'palladium' AND title has palladium: {data.get('Alias', '')}")
            return "palladium", reasons
        reasons.append(f"Alias says palladium but title has no palladium keywords - will check title")
    elif "gold" in alias or "nugget" in alias or "dental" in alias:
        # IMPORTANT: Only route to gold if title actually has gold indicators
        # This prevents knives, books, figurines etc from gold searches being misrouted
        if gold_matches or "gold" in title or "kt " in title or "karat" in title:
            reasons.append(f"Alias contains gold keywords AND title has gold indicators: {data.get('Alias', '')}")
            return "gold", reasons
        # Alias says gold but no gold in title - DON'T route to gold agent
        reasons.append(f"Alias says gold but title has NO gold keywords ({title[:60]}...) - will check title for actual category")
    elif "junk silver" in alias or "coin scrap" in alias or "90%" in alias:
        reasons.append(f"Alias contains coin scrap keywords: {data.get('Alias', '')}")
        return "coin_scrap", reasons
    elif "silver" in alias or "sterling" in alias:
        if silver_matches or "silver" in title:
            reasons.append(f"Alias contains silver/sterling AND title has silver: {data.get('Alias', '')}")
            return "silver", reasons
        reasons.append(f"Alias says silver but title has no silver keywords - will check title")
    elif "knife" in alias or "knives" in alias:
        reasons.append(f"Alias contains knife keywords: {data.get('Alias', '')}")
        return "knives", reasons
    elif "watch" in alias:
        reasons.append(f"Alias contains watch keywords: {data.get('Alias', '')}")
        return "watch", reasons
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
    elif "videogame" in alias or "video game" in alias or "game" in alias:
        reasons.append(f"Alias contains video game keywords: {data.get('Alias', '')}")
        return "videogames", reasons
    
    # ============================================================
    # PRIORITY 3: Fall back to title keywords
    # Order matters! Check specific categories before generic gold/silver
    # ============================================================
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "magic the gathering", "mtg booster", "sealed case", "tcg"]
    coral_keywords = ["coral", "mediterranean coral", "red coral", "angel skin", "salmon coral", "oxblood coral"]
    costume_keywords = ["costume jewelry", "vintage jewelry lot", "jewelry lot", "trifari", "coro", "eisenberg", "weiss", "miriam haskell", "rhinestone lot", "brooch lot"]
    videogame_keywords = ["sega", "genesis", "nintendo", "nes", "snes", "n64", "gamecube", "wii", "switch", 
                         "playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "psp", "vita",
                         "xbox", "dreamcast", "saturn", "game boy", "gameboy", "gba", "ds", "3ds",
                         "atari", "turbografx", "neo geo", "cib", "complete in box",
                         "video game", "videogame", "resident evil", "final fantasy", "zelda", "mario",
                         "sonic", "mega man", "metroid", "castlevania", "silent hill", "metal gear"]
    
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    coral_matches = [kw for kw in coral_keywords if kw in title]
    costume_matches = [kw for kw in costume_keywords if kw in title]
    videogame_matches = [kw for kw in videogame_keywords if kw in title]
    
    # CHECK VIDEO GAMES FIRST - they may have gold/silver in title (e.g., "Gold Edition")
    # but are NOT precious metals
    if videogame_matches:
        reasons.append(f"Title contains video game keywords: {videogame_matches}")
        return "videogames", reasons
    elif lego_matches:
        reasons.append(f"Title contains LEGO keywords: {lego_matches}")
        return "lego", reasons
    elif tcg_matches:
        reasons.append(f"Title contains TCG keywords: {tcg_matches}")
        return "tcg", reasons
    elif gold_matches:
        reasons.append(f"Title contains gold keywords: {gold_matches}")
        return "gold", reasons
    elif silver_matches:
        reasons.append(f"Title contains silver keywords: {silver_matches}")
        return "silver", reasons
    elif coral_matches:
        reasons.append(f"Title contains coral keywords: {coral_matches}")
        return "coral", reasons
    elif costume_matches:
        reasons.append(f"Title contains costume keywords: {costume_matches}")
        return "costume", reasons
    
    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons


# ============================================================
# SYSTEM CONTEXT GENERATOR
# ============================================================

def get_system_context(category: str) -> str:
    """
    Get the full system context for a category.
    Combines business context with category-specific prompt.
    """
    business = get_business_context()
    category_prompt = get_category_prompt(category)
    return f"{business}\n\n{category_prompt}"
