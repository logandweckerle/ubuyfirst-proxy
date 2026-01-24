"""
HTML Renderers for ClaudeProxy

Extracted from main.py for better organization.
Contains all HTML rendering functions for the proxy UI.
"""


def render_disabled_html() -> str:
    """Render HTML for disabled proxy state"""
    return '''<!DOCTYPE html>
<html><head><style>
body { font-family: system-ui; background: #f5f5f5; padding: 20px; }
.card { background: #fff3cd; border: 3px solid #ffc107; border-radius: 12px; padding: 20px; text-align: center; max-width: 400px; margin: auto; }
.status { font-size: 28px; font-weight: bold; color: #856404; }
</style></head><body>
<div class="card"><div class="status">PROXY DISABLED</div>
<p>Enable at <a href="http://localhost:8000">localhost:8000</a></p></div>
</body></html>'''


def render_queued_html(category: str, listing_id: str, title: str, price: str) -> str:
    """Render HTML for queued listing with analyze button"""
    return f'''<!DOCTYPE html>
<html><head><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; padding: 15px; min-height: 100%; }}
.container {{ text-align: center; }}
.title {{ font-size: 13px; color: #888; margin-bottom: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.category {{ display: inline-block; background: #252540; color: #6366f1; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-bottom: 15px; }}
.analyze-btn {{
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white;
    border: none;
    padding: 15px 40px;
    font-size: 18px;
    font-weight: 700;
    border-radius: 12px;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
}}
.analyze-btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5); }}
.analyze-btn:active {{ transform: translateY(0); }}
.loading {{ display: none; color: #888; font-size: 14px; }}
.result {{ display: none; }}
</style></head><body>
<div class="container">
<div class="category">{category.upper()}</div>
<div class="title">{title[:60]}</div>
<button class="analyze-btn" onclick="runAnalysis()">ANALYZE</button>
<div class="loading" id="loading">Analyzing...</div>
<div class="result" id="result"></div>
</div>
<script>
function runAnalysis() {{
    document.querySelector('.analyze-btn').style.display = 'none';
    document.getElementById('loading').style.display = 'block';

    fetch('/analyze-now/{listing_id}', {{ method: 'POST' }})
        .then(response => response.text())
        .then(html => {{
            document.body.innerHTML = html;
        }})
        .catch(err => {{
            document.getElementById('loading').textContent = 'Error: ' + err;
        }});
}}
</script>
</body></html>'''


def render_error_html(error: str) -> str:
    """Render HTML for error state"""
    return f'''<!DOCTYPE html>
<html><head><style>
body {{ font-family: system-ui; background: #f5f5f5; padding: 20px; }}
.card {{ background: #f8d7da; border: 3px solid #dc3545; border-radius: 12px; padding: 20px; text-align: center; max-width: 400px; margin: auto; }}
.status {{ font-size: 28px; font-weight: bold; color: #721c24; }}
</style></head><body>
<div class="card"><div class="status">ERROR</div>
<p>{error[:100]}</p></div>
</body></html>'''


def format_confidence(confidence) -> str:
    """Format confidence as 'Number (Label)' e.g. '85 (High)'"""
    try:
        # Try to get numeric value
        if isinstance(confidence, str):
            conf_lower = confidence.lower().strip()
            # Convert word to number
            if conf_lower in ['high', 'h']:
                conf_num = 80
            elif conf_lower in ['medium', 'med', 'm']:
                conf_num = 60
            elif conf_lower in ['low', 'l']:
                conf_num = 40
            else:
                conf_num = int(confidence.replace('%', '').strip())
        else:
            conf_num = int(confidence) if confidence else 50

        # Determine label
        if conf_num >= 70:
            label = "High"
        elif conf_num >= 50:
            label = "Med"
        else:
            label = "Low"

        return f"{conf_num} ({label})"
    except (ValueError, TypeError):
        # Last resort - return what we got
        return str(confidence) if confidence else "50 (Med)"


def render_result_html(result: dict, category: str, title: str = "") -> str:
    """Render analysis result as HTML based on category"""
    recommendation = result.get('Recommendation', 'RESEARCH')
    reasoning = result.get('reasoning', 'No reasoning provided')
    # Use Profit (actual money made) not Margin (room under ceiling)
    profit = result.get('Profit', result.get('Margin', result.get('margin', '--')))
    confidence = format_confidence(result.get('confidence', '--'))

    # Determine card styling
    if recommendation == 'BUY':
        bg = 'linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%)'
        border = '#28a745'
        text_color = '#155724'
    elif recommendation == 'PASS':
        bg = 'linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%)'
        border = '#dc3545'
        text_color = '#721c24'
    elif recommendation in ('CLICK AGAIN', 'QUEUED', 'DISABLED'):
        bg = 'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)'
        border = '#6366f1'
        text_color = '#3730a3'
    else:
        bg = 'linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%)'
        border = '#ffc107'
        text_color = '#856404'

    # Build info grid based on category
    info_items = []

    if category == 'gold':
        listing_price = result.get('listingPrice', '--')
        # Prefer goldweight (after deductions) over total weight
        gold_weight = result.get('goldweight', result.get('weight', '--'))
        # Show deduction info if present
        stone_deduction = result.get('stoneDeduction', '')
        weight_display = f"{gold_weight}"
        if stone_deduction and stone_deduction not in ['0', 'NA', '', 'None']:
            weight_display = f"{gold_weight} (net)"
        info_items = [
            ('Karat', result.get('karat', '--')),
            ('Gold Wt', weight_display),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Sell (96%)', f"${result.get('sellPrice', '--')}"),
            ('Listing', f"${listing_price}"),
            ('Confidence', confidence),
        ]
    elif category == 'silver':
        listing_price = result.get('listingPrice', '--')
        info_items = [
            ('Type', result.get('itemtype', '--')),
            ('Weight', result.get('weight', result.get('silverweight', '--'))),
            ('Melt', f"${result.get('meltvalue', '--')}"),
            ('Sell (82%)', f"${result.get('sellPrice', '--')}"),
            ('Listing', f"${listing_price}"),
            ('Confidence', confidence),
        ]
    elif category == 'costume':
        # Get quality score and format it
        quality_score = result.get('qualityScore', '--')
        designer_tier = result.get('designerTier', '--')
        tier_label = f"Tier {designer_tier}" if designer_tier not in ['--', 'Unknown', 'Mixed'] else designer_tier

        info_items = [
            ('Type', result.get('itemtype', '--')),
            ('Pieces', result.get('pieceCount', '--')),
            ('$/Piece', f"${result.get('pricePerPiece', '--')}"),
            ('Designer', result.get('designer', '--')[:15]),  # Truncate long names
            ('Quality', quality_score),
            ('Tier', tier_label),
        ]
    elif category == 'tcg':
        info_items = [
            ('TCG', result.get('TCG', '--')),
            ('Type', result.get('ProductType', '--')),
            ('Set', result.get('SetName', '--')),
            ('Market', f"${result.get('marketprice', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Risk', result.get('fakerisk', '--')),
        ]
    elif category == 'lego':
        info_items = [
            ('Set#', result.get('SetNumber', '--')),
            ('Set', result.get('SetName', '--')),
            ('Theme', result.get('Theme', '--')),
            ('Market', f"${result.get('marketprice', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Retired', result.get('Retired', '--')),
        ]
    elif category == 'coral':
        info_items = [
            ('Material', result.get('material', '--')),
            ('Age', result.get('age', '--')),
            ('Color', result.get('color', '--')),
            ('Type', result.get('itemtype', '--')),
            ('Value', f"${result.get('estimatedvalue', '--')}"),
            ('Risk', result.get('fakerisk', '--')),
        ]
    elif category == 'videogames':
        info_items = [
            ('Game', result.get('pcProduct', result.get('product_name', '--'))[:30]),
            ('Console', result.get('console_name', result.get('detected_console', '--'))),
            ('Condition', result.get('condition', result.get('detected_condition', '--'))),
            ('Market', f"${result.get('marketprice', '--')}"),
            ('Max Buy', f"${result.get('maxBuy', '--')}"),
            ('Confidence', confidence),
        ]
    else:
        info_items = [
            ('Type', result.get('itemtype', '--')),
            ('Confidence', confidence),
        ]

    info_html = ""
    for label, value in info_items:
        info_html += f'''<div class="info-box">
<div class="info-label">{label}</div>
<div class="info-value">{value}</div>
</div>'''

    # Text-to-Speech script for BUY alerts
    # Clean the title for speech (remove special chars)
    clean_title = title.replace('"', '').replace("'", "").replace('&', 'and')[:100] if title else ""

    tts_script = ""
    if recommendation == 'BUY' and clean_title:
        tts_script = f'''
<script>
(function() {{
    if ('speechSynthesis' in window) {{
        // Cancel any ongoing speech
        window.speechSynthesis.cancel();

        // Create utterance
        var msg = new SpeechSynthesisUtterance();
        msg.text = "Buy alert! {clean_title}";
        msg.rate = 1.1;  // Slightly faster
        msg.pitch = 1.0;
        msg.volume = 1.0;

        // Try to use a good voice
        var voices = window.speechSynthesis.getVoices();
        if (voices.length > 0) {{
            // Prefer English voices
            var englishVoice = voices.find(v => v.lang.startsWith('en'));
            if (englishVoice) msg.voice = englishVoice;
        }}

        // Speak after a tiny delay (helps with voice loading)
        setTimeout(function() {{
            window.speechSynthesis.speak(msg);
        }}, 100);
    }}
}})();
</script>'''

    return f'''<!DOCTYPE html>
<html><head><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 10px; }}
.container {{ max-width: 500px; margin: 0 auto; }}
.result-card {{ border-radius: 12px; padding: 20px; text-align: center; background: {bg}; border: 3px solid {border}; }}
.status {{ font-size: 36px; font-weight: bold; color: {text_color}; margin-bottom: 5px; }}
.profit {{ font-size: 24px; font-weight: bold; color: {text_color}; margin-bottom: 10px; }}
.reason {{ background: rgba(255,255,255,0.7); border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 13px; line-height: 1.4; color: #333; text-align: left; }}
.info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 15px; }}
.info-box {{ background: #fff; border-radius: 8px; padding: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.info-label {{ font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.info-value {{ font-size: 14px; font-weight: bold; color: #333; }}
</style></head><body>
<div class="container">
<div class="result-card">
<div class="status">{recommendation}</div>
<div class="profit">{profit}</div>
<div class="reason">{reasoning}</div>
<div class="info-grid">{info_html}</div>
</div></div>
{tts_script}
</body></html>'''


# Backwards compatibility aliases (with underscore prefix)
_render_disabled_html = render_disabled_html
_render_queued_html = render_queued_html
_render_error_html = render_error_html
