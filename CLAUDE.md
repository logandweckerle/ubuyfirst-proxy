# ClaudeProxyV3 - eBay Arbitrage System

## Quick Reference - CRITICAL RULES

**DO NOT:**
- Add price caps to gold/silver - melt value is the only limit
- Trust PASS rates as accuracy metrics - the AI misses BUYs, not the other way around
- Change MiniPC searches (they're separate from main PC)
- Return HTMLResponse without JSON fields - uBuyFirst needs BOTH

**ALWAYS:**
- Return JSONResponse with `html` field included for uBuyFirst
- Send Discord/TTS only for BUY (not RESEARCH)
- Let gold/silver calculate based on spot price × weight × purity

---

## Business Model

Logan buys underpriced items on eBay and resells for profit. Primary categories:

### Gold & Silver (PRIMARY - Most Profitable)
- **Strategy**: Buy jewelry priced below melt value
- **Edge**: Sellers don't know weight or spot prices
- **Best finds**: Estate sellers, thrift stores listing gold without weighing it
- **Gold calculation**: weight × (karat/24) × spot_price_per_gram × 0.95
- **Silver calculation**: weight × 0.925 × spot_price_per_gram × 0.82

### Watches (SECONDARY - Complex)
- **Strategy**: Buy premium brands for repair/parts, gold watches for melt
- **Edge**: People misprice vintage chronographs, especially triple vs double subdials
- **Profitable brands**: Omega, Rolex, Tudor, Heuer, Breitling
- **Avoid**: Fashion brands (Lacoste, Michael Kors, Fossil, etc.)

### Video Games/LEGO/TCG (TERTIARY)
- **Strategy**: Buy below 65-70% of PriceCharting market value
- **Edge**: Sellers don't check market prices
- **Requires**: PriceCharting database match for verification

---

## Owner's Proven Thresholds (From Actual Purchases)

### Omega Watches
| Model | BUY Threshold | Notes |
|-------|---------------|-------|
| Seamaster | Under $300 | Even for parts/not working |
| Seamaster (good condition) | Under $400 | Working, clean dial |
| Constellation | Under $500 | Any condition |
| Pie Pan dial | Under $600 | Premium Constellation dial |

### Chronographs
| Type | Value Range | Notes |
|------|-------------|-------|
| 2-subdial (no brand) | $100-300 | Basic chronograph |
| 2-subdial (designer) | $300-700 | Good dial/condition |
| 3-subdial (triple) | $800-3000+ | OFTEN MISPRICED as double |

### Gold Watch Weights (Real Data)
| Type | Expected Gold Weight |
|------|---------------------|
| Ladies small | 3-4 grams |
| Men's vintage 34-36mm | 7-10 grams |
| Bulova Accutron 14K | 16-18 grams |
| Ladies with gold band | 10-40 grams |
| Men's with gold band | 35-50 grams |

---

## Visual Weight Estimation (When No Weight Stated)

**BUY Trigger**: Under 80% of estimated melt value = instant BUY

### Weight Indicators by Item Type

**Chains:**
- Length + thickness + style
- Compare to sold listings of same length/thickness/style
- Heavier chains have stronger clasps

**Rings:**
- Men's vs women's (men's heavier)
- Vintage style = usually heavier
- Wedding bands = solid, predictable weight
- Ring size matters
- Build quality visible in photos

**Bracelets - Clasp Types Tell the Story:**
| Clasp Type | Weight Indicator |
|------------|------------------|
| Tongue-in-groove | HEAVY bracelet |
| Safety locks/chains | HEAVY - added for security |
| Spring ring | LIGHTER bracelet |
| Lobster claw | Medium weight |

**Earrings/Brooches:**
- Check BACK photos for construction
- Solid backs = more gold than hollow

### Quality Indicators (Markings)

| Marking | Meaning |
|---------|---------|
| Italy | Better quality (except Milor) |
| Milor | Often hollow/light - BE CAREFUL |
| Uno-A-Erre | Good quality, solid |
| 18K/18Kt | Higher purity = more value per gram |

### Green Flags (Seller Doesn't Know Value)
- "Solid 18Kt gold" but NO weight listed
- Estate/inherited keywords
- Low feedback casual seller
- Thrift store account

### Stone Deduction Rules
- Under 10g with 50%+ stones = PASS
- Over 15g with some stones = evaluate price vs stone estimate
- Large center stones with thin gold = mostly stone weight

---

## Code Architecture

### Pipeline Flow (WHY it's structured this way)

```
uBuyFirst POST → main.py → orchestrator.py → Response
                              ↓
                    1. pre_checks.py (spam, dedup, sold, cache)
                              ↓
                    2. instant_pass.py (plated, overpriced, no-value)
                              ↓
                    3. fast_pass.py (agent quick_pass, user prices)
                              ↓
                    4. AI Analysis (Tier 1 → Tier 2 if BUY)
                              ↓
                    5. response_builder.py (format JSON + HTML)
```

### Key Files and WHY They Exist

| File | Purpose | WHY |
|------|---------|-----|
| `pipeline/orchestrator.py` | Main analysis flow | Central coordinator - all logic flows through here |
| `pipeline/pre_checks.py` | Fast rejection | Save AI costs by rejecting spam/dupes BEFORE analysis |
| `pipeline/instant_pass.py` | Rule-based PASS | Plated items, fashion brands - no AI needed |
| `pipeline/fast_pass.py` | Rule-based BUY/RESEARCH | Known patterns that don't need AI (user prices, agent quick_pass) |
| `pipeline/response_builder.py` | Format output | uBuyFirst needs JSON fields + HTML display |
| `agents/gold.py` | Gold analysis | Melt value calculations, karat detection |
| `agents/silver.py` | Silver analysis | Sterling weight, weighted items (15% rule) |
| `agents/watch.py` | Watch analysis | Brand tiers, chronograph detection, gold content |
| `utils/extraction.py` | Weight/karat regex | Extract "14K 10 grams" from titles |
| `utils/spam_detection.py` | Seller blocking | 2+ listings in 30s = spam |
| `utils/rag_context.py` | RAG vector search | Find similar past purchases for weight estimation |
| `config/settings.py` | Environment config | API keys, webhook URLs |

### Response Format (CRITICAL)

uBuyFirst expects BOTH JSON fields AND HTML:
```python
# CORRECT - Always do this
result['html'] = render_result_html(result, category, title)
return JSONResponse(content=result)

# WRONG - Never return HTMLResponse alone
return HTMLResponse(content=html)  # Breaks uBuyFirst columns!
```

---

## Common Mistakes to Avoid

### 1. Adding Price Caps to Gold/Silver
**Wrong**: `if price > 500: return PASS`
**Why it's wrong**: A 50-gram 14K chain at $5000 could be $8000 melt value
**Correct**: Always calculate melt value, no arbitrary caps

### 2. Trusting PASS Rates
**Wrong**: "90% PASS rate means the system is working"
**Why it's wrong**: AI misses BUYs frequently; PASS doesn't mean it was correctly analyzed
**Correct**: Focus on BUY accuracy and profit per purchase

### 3. MiniPC vs Main PC Confusion
The Keywords CSV has searches for TWO different computers:
- **Main PC (Apple panels 1-4)**: Gold, silver, watches
- **MiniPC**: Separate searches, don't mix them

### 4. Shadowing Module Imports
**Wrong**: `import json` inside a function when `json` is used elsewhere
**Correct**: Use `import json as _json` or import at module level

### 5. Fashion Watch Chronographs
**Wrong**: Treating "Lacoste Chronograph" as valuable vintage chrono
**Why**: Fashion brands have no resale value regardless of complications
**Correct**: Filter fashion brands BEFORE chronograph value check

---

## Notifications

- **Discord + TTS**: Only for BUY recommendations
- **RESEARCH**: No notification (user reviews manually)
- **PASS**: No notification

---

## External Integrations

### uBuyFirst
- Sends listings via POST to `/match_mydata`
- Expects JSON response with these fields for columns:
  - `Recommendation`, `Profit`, `confidence`, `reasoning`
- Expects `html` field for display panel

### eBay Browse API
- Direct polling for gold/silver keywords
- Configured in `ebay_poller.py`
- Uses eBay App ID from `.env`

### Discord Webhook
- Configured in `.env` as `DISCORD_WEBHOOK_URL`
- Sends BUY alerts with item details, profit, image

---

## Session Log

### 2026-01-28
- Fixed JSON/HTML response issue - all paths now return JSONResponse with html field
- Added Discord/TTS for agent quick_pass BUY signals (was missing)
- Added fashion watch brands: Lacoste, Nautica, Tommy Hilfiger, Hugo Boss, Coach, etc.
- Updated Omega thresholds from owner data (Seamaster <$300, Constellation <$500)
- Added triple chronograph detection ($800+ floor vs $300 for double)
- Added gold watch weight estimates from owner's real purchases
- Added Leonidas to mid-tier watch brands
- Fixed `import json` shadowing bug in orchestrator.py
- Added pearl necklace instant pass (clasp only has 2-4g gold)
- **Fixed Discord notification timing** - now sends AFTER all validation (server score, high-value gold, etc.)
  - Previously: Discord sent before server score could force BUY→RESEARCH
  - Now: Discord only fires for items that remain BUY after ALL checks
- **Added RAG context system** - uses past purchase history for weight estimation
  - LanceDB vector store with 774 indexed purchases
  - sentence-transformers embeddings (all-MiniLM-L6-v2)
  - Finds similar past purchases and suggests weight ranges
  - Injects historical context into AI prompts for gold/silver

### 2026-01-07
- Implemented seller spam detection (auto-block after 2 listings in 30s)
- Imported 2,076 blocked sellers from uBuyFirst + manual list
- Added listing enhancements: freshness scoring, seller scoring, best offer flag
- Fixed datetime shadowing bug and video game validation bug
- Added item deduplication (10-min window prevents re-evaluation)

---

## Environment

- **Port**: 8000
- **Python**: 3.14
- **Key configs**: `.env` file in project root
- **Logs**: Console output, can redirect to file

## Starting the Server

```bash
cd C:\Users\Logan Weckerle\Documents\ClaudeProxy\ClaudeProxyV3
python main.py
```

Dashboard: http://localhost:8000
