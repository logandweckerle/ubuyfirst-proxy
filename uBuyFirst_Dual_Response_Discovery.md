# uBuyFirst Dual Response System - Discovery Documentation

## Date: December 31, 2024

## Executive Summary

After extensive debugging, we discovered that uBuyFirst's External Endpoint mode makes **TWO separate HTTP requests** to the same endpoint - one for display (HTML) and one for column data (JSON). The key differentiator is the `response_type` parameter sent in the request body.

---

## The Problem

We could get EITHER:
- **Display working** (styled BUY/PASS cards) when returning HTML
- **Columns working** (AI columns populated) when returning JSON

But NEVER both simultaneously. Every attempt to combine them failed.

## The Discovery

### uBuyFirst's Dual-Request Architecture

When you click a listing in External Endpoint mode, uBuyFirst makes **TWO requests**:

1. **First Request**: `response_type: html` → Expects HTML for the display panel
2. **Second Request**: `response_type: json` → Expects JSON for column population

Both requests go to the same endpoint URL (`/match_mydata`) but with different `response_type` values in the JSON body.

### Request Body Structure

uBuyFirst sends a rich JSON body containing:

```json
{
  "response_type": "json",           // or "html"
  "llm_provider": "openai",
  "llm_model": "gpt-4o",
  "llm_api_key": "...",
  "system_prompt": "...",            // 368 chars in our case
  "display_template": "...",         // 1733 chars in our case
  "images": [...],
  "Title": "...",
  "Alias": "...",
  "TotalPrice": "...",
  "description": "...",
  // ... other listing fields
}
```

### The Solution

The proxy must check `response_type` and return the appropriate format:

```python
response_type = data.get('response_type', 'html')

if response_type == 'json':
    return JSONResponse(content=result)  # For columns
else:
    return HTMLResponse(content=html)    # For display
```

---

## Technical Implementation

### Key Code Sections

#### 1. Save response_type Early
```python
title = data.get('Title', 'No title')[:80]
total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))
response_type = data.get('response_type', 'html')  # Save early!
```

#### 2. Cache Must Respect response_type
```python
cached = cache.get(title, total_price)
if cached:
    result, html = cached
    if response_type == 'json':
        return JSONResponse(content=result)
    else:
        return HTMLResponse(content=html)
```

#### 3. Fresh Analysis Response
```python
if response_type == 'json':
    return JSONResponse(content=result)
else:
    return HTMLResponse(content=html)
```

### JSON Response Format (for columns)

The JSON must include these keys for column population:
```json
{
  "Qualify": "Yes",
  "Recommendation": "BUY",
  "verified": "Yes",
  "itemtype": "Flatware",
  "weight": "100g",
  "meltvalue": "211.00",
  "maxBuy": "158.25",
  "Margin": "+50.00",
  "pricepergram": "2.11",
  "confidence": "High",
  "reasoning": "Sterling flatware, stated weight...",
  "listingPrice": "108.25",
  "category": "silver"
}
```

### HTML Response Format (for display)

Standard HTML with styling. The proxy's `render_result_html()` function generates the styled BUY/PASS/RESEARCH cards.

---

## What We Learned About uBuyFirst Modes

### Three SKU Manager Modes

1. **Local Machine**: Runs Python scripts locally
2. **External Endpoint**: Sends requests to a URL (what we use)
3. **AI**: Uses LiteLLM with OpenAI API format

### External Endpoint Mode Behavior

- Ignores the Display Template field in uBuyFirst UI (proxy controls display)
- Makes dual requests (html + json)
- Populates columns from JSON response
- Shows HTML response in panel

### AI Mode Behavior

- Uses OPENAI_API_BASE environment variable for routing
- Expects OpenAI chat completion format
- Uses Display Template from uBuyFirst UI
- Requires Prompt field to be filled

### Key Finding: External Endpoint is Self-Contained

When using External Endpoint mode:
- The proxy handles EVERYTHING
- uBuyFirst's Prompt and Display Template fields are sent TO the proxy but aren't used by uBuyFirst itself
- The proxy can use or ignore these as needed

---

## Configuration Requirements

### .env File
```
# NOT needed for External Endpoint mode
# OPENAI_API_BASE=http://localhost:8000/v1

# Only needed if using AI mode
```

### uBuyFirst Settings

1. **SKU Manager Type**: External Endpoint
2. **Endpoint URL**: `http://localhost:8000/match_mydata?Title={Title}&TotalPrice={TotalPrice}&...`
3. **Send description and pictures**: ✅ Checked
4. **Select fields to send**: Check relevant fields

### Filter Settings

1. **Filter Action**: Apply AI Prompt (or appropriate action)
2. **All 4 dropdowns filled**:
   - Prompt profile
   - Display Template profile  
   - **Columns profile** ← Most commonly missed!
   - Fields to Send profile

### AI Columns Configuration

Each column name on a **separate line**:
```
Qualify
Recommendation
verified
itemtype
weight
meltvalue
maxBuy
Margin
pricepergram
confidence
reasoning
```

Column names must match JSON keys **exactly** (case-sensitive).

---

## Debugging Checklist

### If Display Works But Columns Empty
- Check if proxy returns JSON for `response_type: json`
- Verify column names match JSON keys exactly
- Ensure Columns profile is selected in filter

### If Columns Work But Display Empty/Wrong
- Check if proxy returns HTML for `response_type: html`
- Verify HTML is valid and styled
- Check for JavaScript errors in HTML

### If Nothing Works
- Check proxy console for requests
- Verify endpoint URL is correct
- Ensure "Send description and pictures" is checked
- Restart both proxy and uBuyFirst

### Useful Logging
```python
logger.info(f"[SAVED] response_type: {response_type}")
logger.info(f"[RESPONSE] Returning JSON (response_type=json)")
logger.info(f"[RESPONSE] Returning HTML (response_type=html)")
```

---

## Cache Considerations

The smart cache stores BOTH result (dict) and HTML:
```python
cache.set(title, total_price, result, html, recommendation, category)
```

Cache retrieval must check response_type:
```python
result, html = cached
if response_type == 'json':
    return JSONResponse(content=result)
else:
    return HTMLResponse(content=html)
```

This ensures cached items serve both request types correctly.

---

## Performance Notes

- uBuyFirst makes 2 requests per listing click
- First request (html) is typically faster (cache hit after first analysis)
- Second request (json) triggers full analysis if not cached
- Images are fetched once and cached
- Claude API called once per unique listing

---

## Failed Approaches (For Reference)

### What Didn't Work

1. **Returning JSON with embedded HTML field** - uBuyFirst showed raw JSON
2. **HTML with embedded JSON script tags** - Columns didn't populate
3. **OpenAI format wrapper from External Endpoint** - Not recognized
4. **Template-based rendering with Jinja2** - External Endpoint ignores templates
5. **Single response trying to serve both** - Can't be both HTML and JSON

### Why They Failed

External Endpoint mode expects:
- Pure HTML for display requests
- Pure JSON for column requests
- Two separate responses, not a hybrid

---

## Summary

The breakthrough was discovering the `response_type` parameter. uBuyFirst's architecture:

```
Click Listing
    │
    ├──► Request 1: response_type=html ──► Proxy returns HTML ──► Display Panel
    │
    └──► Request 2: response_type=json ──► Proxy returns JSON ──► AI Columns
```

By respecting this parameter and returning the appropriate format for each request, both display AND columns work simultaneously.

---

## Files Modified

- `main.py` - Added response_type detection and dual-format responses
- `prompts.py` - No changes needed (works as-is)

## Version

Claude Proxy v3 - Dual Response Support
