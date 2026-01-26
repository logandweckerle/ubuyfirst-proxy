"""
Debug and utility endpoints.

Handles development/debugging operations:
- /reload: Hot reload prompts and agents
- /api/debug-prompts: View current prompt values
- /api/debug-db: Database debug info
- /test-tts: Text-to-speech test page
- /architecture: System architecture dashboard
- /detail/{listing_id}: Detailed listing view
"""

import importlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debug"])

# Module state (set by configure_debug)
_reload_history = []
_get_spot_prices = None
_get_db_debug_info = None
_stats = None
_db_fetchone = None
_format_confidence = None


def configure_debug(get_spot_prices_fn, get_db_debug_info_fn, stats,
                    db_fetchone_fn, format_confidence_fn):
    """Configure module dependencies."""
    global _get_spot_prices, _get_db_debug_info, _stats
    global _db_fetchone, _format_confidence

    _get_spot_prices = get_spot_prices_fn
    _get_db_debug_info = get_db_debug_info_fn
    _stats = stats
    _db_fetchone = db_fetchone_fn
    _format_confidence = format_confidence_fn
    logger.info("[DEBUG ROUTES] Module configured")


# ============================================================
# CONFIDENCE BREAKDOWN BUILDER
# ============================================================

def build_confidence_breakdown(category: str, parsed_response: dict, listing: dict) -> str:
    """Build HTML showing confidence score breakdown"""
    if not parsed_response:
        return '<div style="color:#666;padding:10px;">No parsed response available for breakdown</div>'

    confidence = parsed_response.get('confidence', listing.get('confidence', '--'))
    ai_breakdown = parsed_response.get('confidenceBreakdown', '')

    try:
        conf_value = int(confidence) if str(confidence).isdigit() else confidence
        conf_color = "#22c55e" if isinstance(conf_value, int) and conf_value >= 70 else "#f59e0b" if isinstance(conf_value, int) and conf_value >= 50 else "#ef4444"
    except:
        conf_value = confidence
        conf_color = "#888"

    ai_breakdown_html = ""
    if ai_breakdown:
        ai_breakdown_html = f'''
        <div style="background:#1a3a1a;border:1px solid #22c55e;border-radius:8px;padding:15px;margin-bottom:15px;">
            <div style="color:#22c55e;font-weight:bold;margin-bottom:8px;">AI's Confidence Calculation</div>
            <div style="font-family:monospace;color:#fff;">{ai_breakdown}</div>
        </div>'''

    factors = []
    reasoning = str(parsed_response.get('reasoning', listing.get('reasoning', ''))).lower()
    weight_source = parsed_response.get('weightSource', '').lower()

    if weight_source == 'scale':
        weight_was_from_scale = True
    elif weight_source == 'estimate':
        weight_was_from_scale = False
    else:
        weight_was_from_scale = 'scale' in reasoning and 'est' not in reasoning

    if category == "gold":
        weight = str(parsed_response.get('weight', listing.get('weight', '')))
        karat = parsed_response.get('karat', '')
        fakerisk = parsed_response.get('fakerisk', '')
        stoneDeduction = parsed_response.get('stoneDeduction', '')

        factors.append(("Base Score", "60", "Starting point for gold"))

        weight_has_value = weight and weight not in ['NA', '--', 'Unknown', '', '0']
        if weight_has_value and weight_was_from_scale:
            factors.append(("Weight from Scale", "+25", f"Scale: {weight}g"))
        elif weight_has_value and weight_source == 'stated':
            factors.append(("Weight Stated", "+15", f"Stated: {weight}g"))
        elif weight_has_value and not weight_was_from_scale:
            factors.append(("Weight Estimated", "-30", f"Est: {weight}g (UNVERIFIED - BUY blocked)"))
        else:
            factors.append(("No Weight", "-40", "Weight unknown (BUY blocked)"))

        if karat and karat not in ['NA', '--', 'Unknown', '']:
            factors.append(("Karat Visible", "+10", f"Karat: {karat}"))

        if fakerisk == "High":
            factors.append(("High Fake Risk", "-15", "Cuban/Rope chain or suspicious"))
        elif fakerisk == "Low":
            factors.append(("Low Fake Risk", "+5", "Vintage/signed/low risk item"))

        if stoneDeduction and stoneDeduction not in ['0', 'NA', '--', '']:
            factors.append(("Stone Deduction", "-10", f"Stone estimate: {stoneDeduction}"))

    elif category == "silver":
        weight = str(parsed_response.get('weight', listing.get('weight', '')))
        verified = parsed_response.get('verified', '')
        itemtype = parsed_response.get('itemtype', '')
        stoneDeduction = parsed_response.get('stoneDeduction', '')

        factors.append(("Base Score", "60", "Starting point for silver"))

        weight_has_value = weight and weight not in ['NA', '--', 'Unknown', '', '0']
        if weight_has_value and weight_was_from_scale:
            factors.append(("Weight from Scale", "+25", f"Scale: {weight}g"))
        elif weight_has_value and weight_source == 'stated':
            factors.append(("Weight Stated", "+15", f"Stated: {weight}g"))
        elif weight_has_value and not weight_was_from_scale:
            factors.append(("Weight Estimated", "-30", f"Est: {weight}g (UNVERIFIED - BUY blocked)"))
        else:
            factors.append(("No Weight", "-40", "Weight unknown (BUY blocked)"))

        if verified == "Yes":
            factors.append(("925 Mark Visible", "+10", "Sterling verified"))

        if stoneDeduction and stoneDeduction not in ['0', 'NA', '--', '']:
            factors.append(("Stone Deduction", "-10", f"Stone estimate: {stoneDeduction}"))

        if itemtype == "Weighted":
            factors.append(("Weighted Item", "-10", "Only 15% is silver"))

    elif category == "costume":
        pieceCount = parsed_response.get('pieceCount', '')
        bestDesigner = parsed_response.get('bestDesigner', '')
        metalPotential = parsed_response.get('metalPotential', '')
        variety = parsed_response.get('variety', '')
        silverEstimate = parsed_response.get('silverEstimate', '')

        factors.append(("Base Score", "50", "Starting point for costume"))

        if bestDesigner and bestDesigner not in ['None', 'Unknown', '--', '']:
            factors.append(("Designer Visible", "+20", f"Designer: {bestDesigner}"))

        try:
            count = int(str(pieceCount).replace('+', ''))
            if count >= 30:
                factors.append(("High Piece Count", "+10", f"Count: {pieceCount}"))
        except:
            pass

        if metalPotential == "High":
            factors.append(("Metal Potential", "+15", "Gold/silver likely"))
        elif metalPotential in ("Low", "None"):
            factors.append(("No Metal", "-10", "No precious metal visible"))

        if silverEstimate and silverEstimate not in ['NA', '--', '']:
            factors.append(("Sterling Visible", "+15", f"Estimate: {silverEstimate}"))

        if variety in ("Excellent", "Good"):
            factors.append(("Good Variety", "+10", f"Variety: {variety}"))
        elif variety == "Poor":
            factors.append(("Poor Variety", "-10", "Limited variety"))

    else:
        factors.append(("Category", "--", f"No breakdown for {category}"))

    rows_html = ""
    for factor, adjustment, note in factors:
        if adjustment.startswith('+'):
            color = "#22c55e"
        elif adjustment.startswith('-'):
            color = "#ef4444"
        else:
            color = "#888"

        rows_html += f'''
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;">{factor}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{color};font-weight:bold;text-align:center;">{adjustment}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#888;font-size:12px;">{note}</td>
        </tr>'''

    return f'''
    <div style="background:#252540;border-radius:8px;padding:15px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">
            <span style="color:#888;">Final Confidence Score</span>
            <span style="font-size:24px;font-weight:bold;color:{conf_color};">{conf_value}</span>
        </div>

        {ai_breakdown_html}

        <div style="color:#888;font-size:12px;margin-bottom:10px;">Reference Scoring Factors:</div>
        <table style="width:100%;border-collapse:collapse;">
            <tr style="color:#888;font-size:12px;text-transform:uppercase;">
                <th style="text-align:left;padding:8px;border-bottom:2px solid #444;">Factor</th>
                <th style="text-align:center;padding:8px;border-bottom:2px solid #444;">Adjust</th>
                <th style="text-align:left;padding:8px;border-bottom:2px solid #444;">Note</th>
            </tr>
            {rows_html}
        </table>
    </div>'''


# ============================================================
# HOT RELOAD
# ============================================================

@router.post("/reload")
async def hot_reload():
    """Hot reload prompts.py and agents without restarting the server"""
    global _reload_history

    try:
        import prompts
        importlib.reload(prompts)

        import agents
        import agents.base, agents.gold, agents.silver, agents.costume
        import agents.videogames, agents.lego, agents.tcg, agents.coral_amber
        importlib.reload(agents.base)
        importlib.reload(agents.gold)
        importlib.reload(agents.silver)
        importlib.reload(agents.costume)
        importlib.reload(agents.videogames)
        importlib.reload(agents.lego)
        importlib.reload(agents.tcg)
        importlib.reload(agents.coral_amber)
        importlib.reload(agents)

        reload_time = datetime.now().isoformat()
        _reload_history.append({"time": reload_time, "status": "success", "file": "prompts.py"})

        if len(_reload_history) > 10:
            _reload_history = _reload_history[-10:]

        logger.info(f"[RELOAD] prompts.py reloaded successfully at {reload_time}")
        return RedirectResponse(url="/?reload=success", status_code=303)

    except Exception as e:
        error_msg = str(e)
        _reload_history.append({"time": datetime.now().isoformat(), "status": "error", "error": error_msg})
        logger.error(f"[RELOAD] Failed to reload prompts.py: {error_msg}")
        return RedirectResponse(url=f"/?reload=error&msg={error_msg[:50]}", status_code=303)


@router.get("/reload")
async def reload_page():
    """Page to trigger and view reload status"""
    history_html = ""
    for entry in reversed(_reload_history[-10:]):
        status_color = "#22c55e" if entry.get("status") == "success" else "#ef4444"
        history_html += f'<div style="padding:5px;border-bottom:1px solid #333;"><span style="color:{status_color}">{entry.get("time", "?")} - {entry.get("status", "?")} {entry.get("error", "")}</span></div>'

    if not history_html:
        history_html = '<div style="color:#888;padding:10px;">No reloads yet</div>'

    return HTMLResponse(content=f'''
    <!DOCTYPE html>
    <html>
    <head><title>Hot Reload</title></head>
    <body style="background:#1a1a1a;color:#fff;font-family:monospace;padding:20px;">
        <h1>Hot Reload</h1>
        <p>Reload prompts.py without restarting the server.</p>

        <form method="POST" action="/reload">
            <button type="submit" style="background:#3b82f6;color:white;border:none;padding:15px 30px;font-size:16px;cursor:pointer;border-radius:5px;">
                Reload prompts.py
            </button>
        </form>

        <h2 style="margin-top:30px;">Recent Reloads</h2>
        <div style="background:#222;border-radius:5px;max-width:600px;">
            {history_html}
        </div>

        <p style="margin-top:20px;"><a href="/" style="color:#3b82f6;">Back to Dashboard</a></p>
    </body>
    </html>
    ''')


# ============================================================
# DEBUG ENDPOINTS
# ============================================================

@router.get("/api/debug-prompts")
async def debug_prompts():
    """Show current prompt values for debugging"""
    from prompts import get_gold_prompt, get_silver_prompt

    gold_prompt = get_gold_prompt()
    silver_prompt = get_silver_prompt()

    gold_pricing_start = gold_prompt.find("=== CURRENT GOLD PRICING")
    gold_pricing_end = gold_prompt.find("=== PRICING MODEL")
    gold_pricing = gold_prompt[gold_pricing_start:gold_pricing_end] if gold_pricing_start > 0 else "Not found"

    silver_pricing_start = silver_prompt.find("=== CURRENT PRICING")
    silver_pricing_end = silver_prompt.find("=== ITEM TYPE")
    silver_pricing = silver_prompt[silver_pricing_start:silver_pricing_end] if silver_pricing_start > 0 else "Not found"

    return {
        "spot_prices": _get_spot_prices(),
        "gold_prompt_pricing": gold_pricing.strip(),
        "silver_prompt_pricing": silver_pricing.strip(),
    }


@router.get("/api/debug-db")
async def debug_database():
    """Debug endpoint to check database contents"""
    return _get_db_debug_info()


# ============================================================
# ADAPTIVE LEARNING
# ============================================================

@router.get("/api/adaptive-stats")
async def adaptive_stats():
    """Get adaptive learning statistics"""
    try:
        from utils.adaptive_rules import get_adaptive_stats, get_learned_rules
        return {
            "status": "ok",
            "stats": get_adaptive_stats(),
            "top_rules": get_learned_rules(),
        }
    except Exception as e:
        logger.error(f"[ADAPTIVE] Error getting stats: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/adaptive-reload")
async def adaptive_reload():
    """Force reload adaptive learning patterns"""
    try:
        from utils.adaptive_rules import reload_patterns
        count = reload_patterns(force=True)
        return {"status": "ok", "patterns_loaded": count}
    except Exception as e:
        logger.error(f"[ADAPTIVE] Error reloading: {e}")
        return {"status": "error", "message": str(e)}


# ============================================================
# TTS TEST
# ============================================================

@router.get("/test-tts", response_class=HTMLResponse)
async def test_tts():
    """Test Text-to-Speech functionality"""
    return HTMLResponse(content='''<!DOCTYPE html>
<html><head><title>TTS Test</title>
<style>
body { font-family: Arial, sans-serif; padding: 40px; background: #1a1a2e; color: #fff; }
.btn { padding: 20px 40px; font-size: 24px; cursor: pointer; margin: 10px; border-radius: 10px; }
.buy { background: #28a745; color: white; border: none; }
.test { background: #007bff; color: white; border: none; }
h1 { color: #00ff88; }
#status { margin-top: 20px; padding: 20px; background: #2d2d44; border-radius: 10px; }
</style>
</head><body>
<h1>TTS Test Page</h1>
<p>Click a button to test Text-to-Speech:</p>

<button class="btn buy" onclick="speak('Buy alert! 14k Gold Chain 15 grams solid gold')">
    Test BUY Alert
</button>

<button class="btn test" onclick="speak('Testing text to speech. If you can hear this, it works!')">
    Test Generic Speech
</button>

<button class="btn" style="background:#dc3545;color:white;border:none;" onclick="testVoices()">
    List Available Voices
</button>

<div id="status">Status: Ready</div>

<script>
function speak(text) {
    var status = document.getElementById('status');

    if (!('speechSynthesis' in window)) {
        status.innerHTML = 'Speech Synthesis NOT supported in this browser!';
        return;
    }

    status.innerHTML = 'Speaking: "' + text + '"';

    window.speechSynthesis.cancel();

    var msg = new SpeechSynthesisUtterance();
    msg.text = text;
    msg.rate = 1.1;
    msg.pitch = 1.0;
    msg.volume = 1.0;

    msg.onend = function() {
        status.innerHTML = 'Speech completed!';
    };

    msg.onerror = function(e) {
        status.innerHTML = 'Speech error: ' + e.error;
    };

    var voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
        var englishVoice = voices.find(v => v.lang.startsWith('en'));
        if (englishVoice) {
            msg.voice = englishVoice;
            status.innerHTML += '<br>Using voice: ' + englishVoice.name;
        }
    }

    setTimeout(function() {
        window.speechSynthesis.speak(msg);
    }, 100);
}

function testVoices() {
    var status = document.getElementById('status');
    var voices = window.speechSynthesis.getVoices();

    if (voices.length === 0) {
        status.innerHTML = 'No voices loaded yet. Click again in a second.';
        window.speechSynthesis.getVoices();
        return;
    }

    var html = '<strong>Available Voices (' + voices.length + '):</strong><br>';
    voices.forEach(function(v, i) {
        html += (i+1) + '. ' + v.name + ' (' + v.lang + ')' + (v.default ? ' [DEFAULT]' : '') + '<br>';
    });
    status.innerHTML = html;
}

window.speechSynthesis.getVoices();
</script>
</body></html>''')


# ============================================================
# ARCHITECTURE PAGE
# ============================================================

@router.get("/architecture", response_class=HTMLResponse)
async def architecture_page():
    """System architecture and understanding dashboard"""
    from templates.pages import render_system_architecture
    from agents import AGENTS
    from config.settings import CATEGORY_THRESHOLDS

    system_data = {}

    agents_info = {}
    agent_descriptions = {
        'gold': 'Precious metal scrap - analyzes gold jewelry by weight/karat for melt value',
        'silver': 'Sterling silver analysis - 925/800 purity, flatware, scrap lots',
        'platinum': 'Platinum jewelry - 950/900 purity melt value calculations',
        'palladium': 'Palladium items - rare precious metal analysis',
        'tcg': 'Trading cards - Pokemon, MTG sealed products and graded cards',
        'lego': 'LEGO sets - sealed/retired sets with PriceCharting lookup',
        'videogames': 'Video games - retro/collectible games with market pricing',
        'watch': 'Watches - luxury/vintage watches, NOT gold scrap',
        'knives': 'Collectible knives - Chris Reeve, Strider, Benchmade, vintage',
        'pens': 'Fountain pens - Montblanc, Pelikan, vintage collectibles',
        'costume': 'Costume jewelry - Trifari, Eisenberg, vintage signed pieces',
        'coral': 'Coral & Amber - antique/vintage natural materials',
        'textbook': 'College textbooks - ISBN lookup for buyback value',
        'industrial': 'Industrial equipment - PLCs, automation gear',
    }
    for name, agent_class in AGENTS.items():
        threshold = CATEGORY_THRESHOLDS.get(name, CATEGORY_THRESHOLDS.get('default', 0.65))
        agents_info[name.title()] = {
            'active': True,
            'description': agent_descriptions.get(name, f'{name} category analysis'),
            'threshold': f'{threshold:.0%}' if isinstance(threshold, float) else str(threshold),
        }
    system_data['agents'] = agents_info

    dbs = []
    db_files = [
        ('arbitrage_data.db', 'Historical listings, seller patterns, dedup cache'),
        ('pricecharting_prices.db', '117K+ video game/collectible market prices'),
        ('purchase_history.db', 'Logged purchases for learning/tracking'),
        ('price_data.db', 'Cached price lookups'),
    ]
    for db_name, purpose in db_files:
        db_path = Path(db_name)
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            dbs.append({'name': db_name, 'purpose': purpose, 'size_mb': size_mb, 'records': '--'})
    system_data['databases'] = dbs

    from utils import BLOCKED_SELLERS
    system_data['stats'] = {
        'Listings Analyzed': _stats.get('total_count', 0),
        'BUY Signals': _stats.get('buy_count', 0),
        'PASS': _stats.get('pass_count', 0),
        'RESEARCH': _stats.get('research_count', 0),
        'Blocked Sellers': len(BLOCKED_SELLERS),
        'Cache Hits': _stats.get('cache_hits', 0),
    }

    from config import SPOT_PRICES
    system_data['config'] = {
        'Gold Spot': f"${SPOT_PRICES.get('gold_oz', 0):,.2f}/oz",
        'Silver Spot': f"${SPOT_PRICES.get('silver_oz', 0):,.2f}/oz",
        'Tier 1 Model': 'GPT-4o-mini',
        'Tier 2 Model': 'GPT-4o',
        'Discord Alerts': 'Enabled' if os.getenv('DISCORD_WEBHOOK_URL') else 'Disabled',
        'eBay Polling': 'Available',
    }

    system_data['routes'] = [
        {'method': 'POST', 'path': '/match_mydata', 'description': 'Main analysis endpoint (uBuyFirst webhook)'},
        {'method': 'GET', 'path': '/dashboard', 'description': 'Main monitoring dashboard'},
        {'method': 'GET', 'path': '/live', 'description': 'Real-time WebSocket feed'},
        {'method': 'POST', 'path': '/ebay/poll/start', 'description': 'Start direct eBay polling'},
        {'method': 'GET', 'path': '/ebay/stats', 'description': 'eBay API usage statistics'},
        {'method': 'GET', 'path': '/api/blocked-sellers', 'description': 'List blocked sellers'},
        {'method': 'GET', 'path': '/purchases', 'description': 'Purchase history dashboard'},
        {'method': 'GET', 'path': '/training', 'description': 'Training data dashboard'},
        {'method': 'GET', 'path': '/health', 'description': 'Health check endpoint'},
    ]

    html = render_system_architecture(system_data)
    return HTMLResponse(content=html)


# ============================================================
# DETAIL VIEW
# ============================================================

@router.get("/detail/{listing_id}", response_class=HTMLResponse)
async def detail_view(listing_id: str):
    """Detailed view of a single listing analysis"""

    listing = _stats["listings"].get(listing_id)

    if not listing:
        row = _db_fetchone(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        )
        if row:
            listing = dict(row)

    if not listing:
        return HTMLResponse(content=f"""
        <html><body style="font-family:system-ui;background:#0f0f1a;color:#fff;padding:40px;">
        <h1>Listing not found</h1>
        <p>ID: {listing_id}</p>
        <a href="/" style="color:#6366f1;">Back to Dashboard</a>
        </body></html>
        """)

    title = listing.get('title', 'Unknown')
    category = listing.get('category', 'unknown')
    recommendation = listing.get('recommendation', 'UNKNOWN')
    total_price = listing.get('total_price', '--')
    margin = listing.get('margin', '--')
    confidence = _format_confidence(listing.get('confidence', '--'))
    reasoning = listing.get('reasoning', 'No reasoning available')
    timestamp = listing.get('timestamp', '--')
    raw_response = listing.get('raw_response', 'Not available')

    parsed_response = {}
    if raw_response and raw_response != 'Not available':
        try:
            parsed_response = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
        except:
            pass

    confidence_breakdown_html = build_confidence_breakdown(category, parsed_response, listing)

    input_data = listing.get('input_data', {})
    if isinstance(input_data, str):
        try:
            input_data = eval(input_data)
        except:
            input_data = {}

    input_html = ""
    for key, value in input_data.items():
        if value and key != 'images':
            input_html += f'<tr><td style="color:#888;padding:8px;border-bottom:1px solid #333;">{key}</td><td style="padding:8px;border-bottom:1px solid #333;">{str(value)[:100]}</td></tr>'

    if recommendation == 'BUY':
        rec_color = '#22c55e'
        rec_bg = 'rgba(34,197,94,0.1)'
    elif recommendation == 'PASS':
        rec_color = '#ef4444'
        rec_bg = 'rgba(239,68,68,0.1)'
    else:
        rec_color = '#f59e0b'
        rec_bg = 'rgba(245,158,11,0.1)'

    return f"""<!DOCTYPE html>
<html><head>
<title>Detail - {title[:30]}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}
.container {{ max-width: 900px; margin: 0 auto; }}
.back {{ color: #6366f1; text-decoration: none; display: inline-block; margin-bottom: 20px; }}
.back:hover {{ text-decoration: underline; }}
.header {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.title {{ font-size: 18px; font-weight: 600; margin-bottom: 10px; word-break: break-word; }}
.meta {{ display: flex; gap: 20px; flex-wrap: wrap; color: #888; font-size: 14px; }}
.recommendation {{ display: inline-block; padding: 8px 20px; border-radius: 8px; font-size: 24px; font-weight: 700; background: {rec_bg}; color: {rec_color}; margin-bottom: 15px; }}
.section {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.section-title {{ font-size: 14px; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 15px; border-bottom: 1px solid #333; padding-bottom: 10px; }}
.reasoning {{ background: #252540; border-radius: 8px; padding: 15px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; }}
.stat-box {{ background: #252540; border-radius: 8px; padding: 15px; text-align: center; }}
.stat-value {{ font-size: 20px; font-weight: 700; color: #fff; }}
.stat-label {{ font-size: 11px; color: #888; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; }}
.raw {{ background: #0a0a15; border-radius: 8px; padding: 15px; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; }}
</style>
</head><body>
<div class="container">
<a href="/" class="back">Back to Dashboard</a>

<div class="header">
    <div class="recommendation">{recommendation}</div>
    <div class="title">{title}</div>
    <div class="meta">
        <span>Category: <strong>{category.upper()}</strong></span>
        <span>Price: <strong>${total_price}</strong></span>
        <span>Time: {timestamp[:19] if timestamp else '--'}</span>
    </div>
</div>

<div class="section">
    <div class="section-title">Analysis Results</div>
    <div class="stats-grid">
        <div class="stat-box">
            <div class="stat-value" style="color:{rec_color}">{margin}</div>
            <div class="stat-label">Profit</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{confidence}</div>
            <div class="stat-label">Confidence</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{category.upper()}</div>
            <div class="stat-label">Category</div>
        </div>
    </div>
</div>

<div class="section">
    <div class="section-title">AI Reasoning</div>
    <div class="reasoning">{reasoning}</div>
</div>

<div class="section">
    <div class="section-title">Confidence Breakdown</div>
    {confidence_breakdown_html}
</div>

<div class="section">
    <div class="section-title">Input Data</div>
    <table>{input_html if input_html else '<tr><td style="color:#666;">No input data available</td></tr>'}</table>
</div>

<div class="section">
    <div class="section-title">Raw AI Response (Debug)</div>
    <div class="raw">{raw_response}</div>
</div>

</div>
</body></html>"""
