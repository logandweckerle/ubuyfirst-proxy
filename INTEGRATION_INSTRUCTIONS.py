# PriceCharting Integration - Exact Code to Add to claude_proxy_server_v2.py
# ============================================================================

"""
SETUP STEPS:
1. Copy pricecharting_integration.py to same folder as claude_proxy_server_v2.py
2. Copy tcg_sealed_prices_v4.csv to same folder 
3. Add PRICECHARTING_API_KEY to your .env file (optional, for API fallback)
4. Add the code snippets below to claude_proxy_server_v2.py
5. Restart the proxy server
"""

# ============================================================================
# STEP 1: ADD IMPORT AT TOP OF FILE (after other imports, around line 35)
# ============================================================================

# Add this after: import uvicorn

# --- START COPY ---
# PriceCharting Integration
try:
    from pricecharting_integration import lookup_price, load_csv_prices, get_stats as pc_get_stats
    PRICECHARTING_AVAILABLE = True
    print("[PC] ✓ PriceCharting module loaded")
except ImportError as e:
    PRICECHARTING_AVAILABLE = False
    print(f"[PC] ✗ PriceCharting not available: {e}")
    print("[PC]   To enable: place pricecharting_integration.py in this folder")
# --- END COPY ---


# ============================================================================
# STEP 2: ADD PRICE LOOKUP FUNCTION (around line 1200, before match_mydata)
# ============================================================================

# Add this function before the @app.post("/match_mydata") decorator

# --- START COPY ---
def get_pricecharting_context(title: str, total_price: float, category: str) -> tuple:
    """
    Get PriceCharting data for TCG/LEGO listings
    Returns: (pc_result dict, context_string for prompt)
    """
    if not PRICECHARTING_AVAILABLE or category not in ["tcg", "lego"]:
        return None, ""
    
    try:
        pc_result = lookup_price(title, total_price)
        
        if pc_result.get('found'):
            context = f"""
=== PRICECHARTING DATA (USE THIS FOR PRICING) ===
Matched Product: {pc_result.get('product_name', 'Unknown')}
TCG: {pc_result.get('tcg', 'Unknown')}
Product Type: {pc_result.get('product_type', 'Unknown')}
Market Price: ${pc_result.get('market_price', 0):,.2f}
Buy Target (65%): ${pc_result.get('buy_target', 0):,.2f}
Listing Price: ${total_price:,.2f}
Margin: ${pc_result.get('margin', 0):,.2f}
Match Confidence: {pc_result.get('confidence', 0):.0%}
Source: {pc_result.get('source', 'unknown')}
=== END PRICECHARTING DATA ===

IMPORTANT: Use the market price above for calculations. Verify product match is correct.
If match confidence is low, be cautious about BUY recommendation.
"""
            print(f"[PC] Found: {pc_result.get('product_name')} @ ${pc_result.get('market_price'):,.0f}")
            return pc_result, context
        else:
            print(f"[PC] No match for: {title[:50]}...")
            return None, """
=== NO PRICECHARTING MATCH ===
Product not found in price database. Use your knowledge to estimate value.
For high-value items you're uncertain about, recommend RESEARCH.
=== END ===
"""
    except Exception as e:
        print(f"[PC] Lookup error: {e}")
        return None, ""


def validate_tcg_result(result: dict, pc_result: dict, total_price: float) -> dict:
    """
    Server-side validation for TCG results
    Override AI calculations with PriceCharting data
    """
    if not pc_result or not pc_result.get('found'):
        return result
    
    try:
        # Server is source of truth for prices
        server_market = pc_result.get('market_price', 0)
        server_buy_target = pc_result.get('buy_target', 0)
        server_margin = server_buy_target - total_price
        
        # Override AI values
        result['marketprice'] = str(int(server_market))
        result['maxBuy'] = str(int(server_buy_target))
        result['Margin'] = f"+{int(server_margin)}" if server_margin >= 0 else str(int(server_margin))
        
        # Add PriceCharting match info
        result['pcMatch'] = 'Yes'
        result['pcProduct'] = pc_result.get('product_name', '')
        result['pcConfidence'] = f"{pc_result.get('confidence', 0):.0%}"
        
        # Override recommendation if AI got it wrong
        ai_rec = result.get('Recommendation', 'RESEARCH')
        
        # PASS if negative margin
        if server_margin < 0 and ai_rec == 'BUY':
            result['Recommendation'] = 'PASS'
            result['reasoning'] = result.get('reasoning', '') + " | SERVER: Negative margin - overriding to PASS"
            print(f"[PC] Override: BUY→PASS (margin ${server_margin:.0f})")
        
        # BUY if good margin and high confidence
        elif server_margin >= 30 and pc_result.get('confidence', 0) >= 0.6 and ai_rec != 'BUY':
            # Only override if not already BUY and margin is substantial
            if server_margin >= 50:
                result['Recommendation'] = 'BUY'
                result['reasoning'] = result.get('reasoning', '') + " | SERVER: Strong margin - overriding to BUY"
                print(f"[PC] Override: {ai_rec}→BUY (margin ${server_margin:.0f})")
        
    except Exception as e:
        print(f"[PC] Validation error: {e}")
    
    return result
# --- END COPY ---


# ============================================================================
# STEP 3: MODIFY match_mydata ENDPOINT
# ============================================================================

# Find this line (around line 1427):
#     category, category_reasons = detect_category(data)
#
# ADD these lines right after it:

# --- START COPY ---
        # PriceCharting lookup for TCG
        pc_result = None
        pc_context = ""
        if category == "tcg":
            pc_result, pc_context = get_pricecharting_context(title, float(total_price), category)
# --- END COPY ---


# ============================================================================
# STEP 4: MODIFY THE PROMPT BUILDING
# ============================================================================

# Find where the user message is built for Claude (around line 1450):
#     user_message = f"{listing_text}"
# or:
#     user_message = f"Listing to analyze:\n\n{listing_text}"
#
# CHANGE IT TO:

# --- START COPY ---
        # Build user message with PriceCharting context
        if pc_context:
            user_message = f"{pc_context}\n\nListing to analyze:\n\n{listing_text}"
        else:
            user_message = f"Listing to analyze:\n\n{listing_text}"
# --- END COPY ---


# ============================================================================
# STEP 5: ADD SERVER VALIDATION AFTER AI RESPONSE
# ============================================================================

# Find where the AI response is parsed into result dict (around line 1485):
#     result = json.loads(response_text)
#
# ADD these lines right after it:

# --- START COPY ---
            # Server-side validation for TCG
            if category == "tcg" and pc_result:
                result = validate_tcg_result(result, pc_result, float(total_price))
# --- END COPY ---


# ============================================================================
# STEP 6: ADD PC STATS TO DASHBOARD (optional)
# ============================================================================

# In the dashboard HTML generation, you can add PriceCharting stats.
# Find the stats section and add:

# --- START COPY ---
# Get PriceCharting stats
pc_stats_html = ""
if PRICECHARTING_AVAILABLE:
    try:
        pcs = pc_get_stats()
        pc_stats_html = f"""
        <div style="background:#1a1a2e;padding:15px;border-radius:8px;margin-top:15px;">
            <h3 style="color:#4ade80;margin:0 0 10px 0;">📊 PriceCharting</h3>
            <div style="color:#888;">
                CSV Products: {pcs.get('csv_products', 0):,}<br>
                Searches: {pcs.get('total_searches', 0):,}<br>
                CSV Hits: {pcs.get('csv_hits', 0):,} ({pcs.get('csv_hit_rate', 'N/A')})<br>
                API Lookups: {pcs.get('api_lookups', 0):,}
            </div>
        </div>
        """
    except:
        pass
# --- END COPY ---

# Then include {pc_stats_html} in your dashboard HTML template


# ============================================================================
# STEP 7: UPDATE TCG AI COLUMNS IN UBUYFIRST
# ============================================================================

"""
In uBuyFirst SKU Manager, update the "Sealed TCG" columns profile to include:

Qualify
Recommendation
producttype
setname
tcgbrand
condition
language
marketprice
maxBuy
Margin
confidence
fakerisk
pcMatch
pcProduct
pcConfidence
reasoning

The new pcMatch, pcProduct, pcConfidence columns show PriceCharting match info.
"""


# ============================================================================
# TESTING
# ============================================================================

"""
After making these changes:

1. Start the proxy: python claude_proxy_server_v2.py

2. Look for these console messages:
   [PC] ✓ PriceCharting module loaded
   [PC] Loaded XXX products from CSV

3. Search for TCG items in uBuyFirst with "Sealed TCG" alias

4. Check console for:
   [PC] Found: Evolving Skies Booster Box @ $300
   or
   [PC] No match for: <title>

5. Verify the display shows:
   - Market price from PriceCharting
   - Correct margins
   - pcMatch: Yes/No column
"""


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

"""
Issue: "PriceCharting not available" message
Fix: Make sure pricecharting_integration.py is in same folder as proxy server

Issue: "CSV not found" message  
Fix: Copy tcg_sealed_prices_v4.csv to same folder as proxy server

Issue: No matches found
Fix: 
- Check CSV is loaded (look for "Loaded XXX products" message)
- Product type must match (Booster Box, ETB, etc.)
- Set name must be similar to CSV entries

Issue: API not working
Fix:
- Add PRICECHARTING_API_KEY=your_key to .env file
- Test: python pricecharting_integration.py search "evolving skies booster box"

Issue: Wrong prices
Fix:
- Update tcg_sealed_prices_v4.csv with current prices
- Download fresh CSV from PriceCharting subscription
"""
