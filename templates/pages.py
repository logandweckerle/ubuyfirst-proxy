"""
Page Rendering Templates

HTML page rendering functions extracted from main.py.
Each function takes data and returns an HTML string.
"""

from typing import List, Dict, Any


def render_purchases_page(purchases: List[Dict], total_spent: float, total_projected_profit: float) -> str:
    """Render the purchase history dashboard page"""

    # Build table rows
    rows = ""
    for p in purchases[:100]:
        listing = p.get("listing", {})
        analysis = p.get("analysis", {})
        timestamp = p.get("timestamp", "")[:19].replace("T", " ")
        title = listing.get("title", "")[:50]
        price = listing.get("price", "--")
        category = listing.get("category", "--")
        profit = analysis.get("profit", "--")
        confidence = analysis.get("confidence", "--")
        weight = analysis.get("weight", "--")

        profit_color = "#22c55e" if str(profit).startswith("+") or (isinstance(profit, (int, float)) and profit > 0) else "#ef4444"

        rows += f'''
        <tr>
            <td style="color:#888;font-size:12px">{timestamp}</td>
            <td>{title}</td>
            <td>${price}</td>
            <td>{category}</td>
            <td style="color:{profit_color};font-weight:600">${profit}</td>
            <td>{confidence}</td>
            <td>{weight}</td>
        </tr>'''

    return f'''<!DOCTYPE html>
<html><head>
<title>Purchase History</title>
<style>
body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}
.container {{ max-width: 1400px; margin: 0 auto; }}
h1 {{ color: #fff; margin-bottom: 20px; }}
.stats {{ display: flex; gap: 20px; margin-bottom: 30px; }}
.stat-card {{ background: #1a1a2e; padding: 20px; border-radius: 12px; text-align: center; min-width: 150px; }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #22c55e; }}
.stat-label {{ color: #888; font-size: 14px; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; }}
th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #333; }}
th {{ background: #252540; color: #888; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
td {{ font-size: 13px; }}
a {{ color: #6366f1; text-decoration: none; }}
.back-link {{ margin-bottom: 20px; display: inline-block; }}
</style>
</head><body>
<div class="container">
<a href="/" class="back-link">&larr; Back to Dashboard</a>
<h1>Purchase History</h1>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{len(purchases)}</div>
        <div class="stat-label">Total Purchases</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">${total_spent:,.0f}</div>
        <div class="stat-label">Total Spent</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" style="color:#22c55e">${total_projected_profit:,.0f}</div>
        <div class="stat-label">Projected Profit</div>
    </div>
</div>

<table>
<thead>
<tr><th>Time</th><th>Title</th><th>Price</th><th>Category</th><th>Est Profit</th><th>Confidence</th><th>Weight</th></tr>
</thead>
<tbody>
{rows if rows else '<tr><td colspan="7" style="text-align:center;color:#888;padding:40px;">No purchases logged yet. Click "I Bought This" on listings to track your purchases.</td></tr>'}
</tbody>
</table>

<p style="margin-top:20px;color:#888;font-size:12px;">
Export: <a href="/api/purchases?limit=1000">JSON</a>
</p>
</div>
</body></html>'''


def render_training_dashboard(overrides: List[Dict], by_type: Dict[str, int], by_category: Dict[str, int]) -> str:
    """Render the training data dashboard page"""

    # Build table rows
    rows = ""
    for o in reversed(overrides[-50:]):  # Most recent 50
        ts = o.get('timestamp', '')[:19]
        title = o.get('input', {}).get('title', 'N/A')[:50]
        price = o.get('input', {}).get('price', 0)
        cat = o.get('input', {}).get('category', 'N/A')
        t1_rec = o.get('tier1_output', {}).get('recommendation', '?')
        t2_rec = o.get('tier2_output', {}).get('recommendation', '?')
        t1_profit = o.get('tier1_output', {}).get('profit', 'N/A')
        t2_profit = o.get('tier2_output', {}).get('profit', 'N/A')
        t2_reason = o.get('tier2_output', {}).get('tier2_reason', '')[:100]

        color = '#ef4444' if t1_rec == 'BUY' and t2_rec == 'PASS' else '#f59e0b'

        rows += f'''
        <tr style="border-bottom: 1px solid #333;">
            <td style="padding: 8px; color: #888;">{ts}</td>
            <td style="padding: 8px;">{title}</td>
            <td style="padding: 8px;">${price:.2f}</td>
            <td style="padding: 8px;">{cat}</td>
            <td style="padding: 8px; color: #22c55e;">{t1_rec}</td>
            <td style="padding: 8px;">{t1_profit}</td>
            <td style="padding: 8px; color: {color};">{t2_rec}</td>
            <td style="padding: 8px;">{t2_profit}</td>
            <td style="padding: 8px; color: #888; font-size: 11px;">{t2_reason}</td>
        </tr>
        '''

    # Build summary cards
    type_cards = ""
    for otype, count in sorted(by_type.items(), key=lambda x: -x[1]):
        color = '#ef4444' if 'PASS' in otype else '#f59e0b'
        type_cards += f'<div style="background: #1a1a2e; padding: 10px 15px; border-radius: 8px; margin: 5px;"><span style="color: {color}; font-weight: bold;">{otype}</span>: {count}</div>'

    cat_cards = ""
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        cat_cards += f'<div style="background: #1a1a2e; padding: 10px 15px; border-radius: 8px; margin: 5px;">{cat}: {count}</div>'

    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Training Data - Override Analysis</title>
        <style>
            body {{ background: #0f0f1a; color: #e0e0e0; font-family: system-ui; padding: 20px; }}
            h1 {{ color: #6366f1; }}
            h2 {{ color: #a5b4fc; margin-top: 30px; }}
            table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 8px; }}
            th {{ background: #252540; padding: 12px; text-align: left; }}
            .summary {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }}
            .export-btn {{ background: #6366f1; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <h1>Training Data - Tier Override Analysis</h1>
        <p>Captures cases where Tier 2 (Sonnet) corrected Tier 1 (Tier1) mistakes. Use this to improve prompts and identify patterns.</p>

        <h2>Override Types</h2>
        <div class="summary">{type_cards}</div>

        <h2>By Category</h2>
        <div class="summary">{cat_cards}</div>

        <h2>Recent Overrides ({len(overrides)} total)</h2>
        <button class="export-btn" onclick="window.location='/api/training-data?limit=1000'">Export JSON</button>

        <table style="margin-top: 20px;">
            <tr>
                <th>Time</th>
                <th>Title</th>
                <th>Price</th>
                <th>Category</th>
                <th>Tier1</th>
                <th>T1 Profit</th>
                <th>Tier2</th>
                <th>T2 Profit</th>
                <th>Reason</th>
            </tr>
            {rows if rows else '<tr><td colspan="9" style="padding: 20px; text-align: center; color: #888;">No overrides logged yet. They will appear here when Tier 2 corrects Tier 1 recommendations.</td></tr>'}
        </table>

        <h2 style="margin-top: 40px;">Using This Data</h2>
        <ul>
            <li><strong>BUY_TO_PASS</strong> = Tier1 said BUY but Sonnet found it was actually a bad deal (most critical errors)</li>
            <li><strong>BUY_TO_RESEARCH</strong> = Tier1 was too confident, Sonnet wants more verification</li>
            <li><strong>RESEARCH_TO_PASS</strong> = Tier1 was uncertain but Sonnet confirmed it's not worth it</li>
        </ul>
        <p>Look for patterns in the reasoning - common words/phrases that correlate with errors can be added to prompts or sanity checks.</p>
    </body>
    </html>
    '''


def render_patterns_page(patterns: Dict[str, Any]) -> str:
    """Render the patterns analytics page"""

    # Worst keywords (high waste score)
    worst_html = ""
    for kw in patterns.get('worst_keywords', [])[:20]:
        avg_margin = kw.get('avg_margin', 0) or 0
        avg_conf = kw.get('avg_confidence', 0) or 0
        waste = kw.get('waste_score', 0) or 0
        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"
        conf_color = "#ef4444" if avg_conf < 50 else "#f59e0b" if avg_conf < 70 else "#22c55e"
        worst_html += f'''
        <tr>
            <td><strong>{kw.get('keyword', '')}</strong></td>
            <td>{kw.get('category', '')}</td>
            <td>{kw.get('times_analyzed', 0)}</td>
            <td style="color:#ef4444">{kw.get('pass_rate', 0):.0%}</td>
            <td style="color:{margin_color}">${avg_margin:.0f}</td>
            <td style="color:{conf_color}">{avg_conf:.0f}</td>
            <td style="color:#ef4444;font-weight:bold">{waste:.2f}</td>
        </tr>'''

    # Bad keywords
    bad_html = ""
    for kw in patterns.get('bad_keywords', [])[:20]:
        avg_margin = kw.get('avg_margin', 0) or 0
        avg_conf = kw.get('avg_confidence', 0) or 0
        waste = kw.get('waste_score', 0) or 0
        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"
        bad_html += f'''
        <tr>
            <td>{kw.get('keyword', '')}</td>
            <td>{kw.get('category', '')}</td>
            <td>{kw.get('times_analyzed', 0)}</td>
            <td style="color:#f59e0b">{kw.get('pass_rate', 0):.0%}</td>
            <td style="color:{margin_color}">${avg_margin:.0f}</td>
            <td>{avg_conf:.0f}</td>
            <td style="color:#f59e0b">{waste:.2f}</td>
        </tr>'''

    # All high-pass keywords table
    all_html = ""
    for kw in patterns.get('high_pass_keywords', [])[:50]:
        avg_margin = kw.get('avg_margin', 0) or 0
        avg_conf = kw.get('avg_confidence', 0) or 0
        pass_rate = kw.get('pass_rate', 0) or 0
        margin_color = "#ef4444" if avg_margin < 0 else "#22c55e"
        pass_color = "#ef4444" if pass_rate > 0.8 else "#f59e0b" if pass_rate > 0.5 else "#888"
        all_html += f'''
        <tr>
            <td>{kw.get('keyword', '')}</td>
            <td>{kw.get('category', '')}</td>
            <td>{kw.get('times_seen', 0)}</td>
            <td>{kw.get('times_analyzed', 0)}</td>
            <td style="color:{pass_color}">{pass_rate:.0%}</td>
            <td style="color:{margin_color}">${avg_margin:.0f}</td>
            <td>{avg_conf:.0f}</td>
        </tr>'''

    return f"""<!DOCTYPE html>
<html><head>
<title>Pattern Analytics - Keyword Waste Scoring</title>
<style>
body {{ font-family: system-ui; background: #0f0f1a; color: #e0e0e0; padding: 20px; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ color: #fff; margin-bottom: 10px; }}
h2 {{ color: #fff; margin: 30px 0 15px 0; font-size: 18px; }}
.subtitle {{ color: #888; margin-bottom: 20px; font-size: 14px; }}
table {{ width: 100%; border-collapse: collapse; background: #1a1a2e; border-radius: 12px; overflow: hidden; margin-bottom: 30px; }}
th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #333; }}
th {{ background: #252540; color: #888; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
td {{ font-size: 13px; }}
a {{ color: #6366f1; text-decoration: none; }}
.section {{ background: #1a1a2e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
.worst {{ border-left: 4px solid #ef4444; }}
.bad {{ border-left: 4px solid #f59e0b; }}
.legend {{ display: flex; gap: 20px; margin-bottom: 20px; font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; gap: 5px; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.formula {{ background: #252540; padding: 15px; border-radius: 8px; margin: 15px 0; font-family: monospace; font-size: 12px; }}
</style>
</head><body>
<div class="container">
<a href="/">&larr; Back to Dashboard</a>
<h1>Keyword Waste Scoring</h1>
<p class="subtitle">Identifies the least profitable keywords to add as negative filters</p>

<div class="formula">
<strong>Waste Score Formula:</strong><br>
waste_score = (pass_rate x 0.5) + (negative_margin_penalty x 0.3) + (low_confidence_penalty x 0.2) x volume_weight<br>
<span style="color:#888;">Higher score = worse keyword. Score &gt; 0.4 = definitely add to negative filter</span>
</div>

<div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#ef4444;"></div> Worst (score &gt; 0.4)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f59e0b;"></div> Bad (score 0.2-0.4)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#22c55e;"></div> Profitable margin</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ef4444;"></div> Negative margin</div>
</div>

<div class="section worst">
<h2>WORST Keywords (Add to Negative Filters!)</h2>
<p style="color:#888;font-size:12px;margin-bottom:15px;">High pass rate + negative margins + low confidence = waste of time</p>
<table>
<thead><tr><th>Keyword</th><th>Category</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th><th>Waste Score</th></tr></thead>
<tbody>{worst_html if worst_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No worst keywords yet (need more data)</td></tr>'}</tbody>
</table>
</div>

<div class="section bad">
<h2>Bad Keywords (Consider Filtering)</h2>
<p style="color:#888;font-size:12px;margin-bottom:15px;">Moderately wasteful - review before filtering</p>
<table>
<thead><tr><th>Keyword</th><th>Category</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th><th>Waste Score</th></tr></thead>
<tbody>{bad_html if bad_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No bad keywords yet</td></tr>'}</tbody>
</table>
</div>

<h2>All High-Pass Keywords</h2>
<table>
<thead><tr><th>Keyword</th><th>Category</th><th>Seen</th><th>Analyzed</th><th>Pass Rate</th><th>Avg Margin</th><th>Avg Conf</th></tr></thead>
<tbody>{all_html if all_html else '<tr><td colspan="7" style="color:#888;text-align:center;">No pattern data yet</td></tr>'}</tbody>
</table>

</div>
</body></html>"""


def render_analytics_page(analytics: Dict[str, Any], patterns: Dict[str, Any]) -> str:
    """Render the analytics dashboard page with charts"""

    # Build recent listings table
    recent_html = ""
    for listing in analytics.get('recent', [])[:10]:
        rec = listing.get('recommendation', 'UNKNOWN')
        rec_color = '#22c55e' if rec == 'BUY' else '#ef4444' if rec == 'PASS' else '#f59e0b'
        margin = listing.get('margin', '--')
        recent_html += f'''
        <tr>
            <td><a href="/detail/{listing.get('id', '')}" style="color:#6366f1">{listing.get('title', '')[:40]}...</a></td>
            <td>{listing.get('category', '').upper()}</td>
            <td style="color:{rec_color};font-weight:600">{rec}</td>
            <td>{margin}</td>
        </tr>'''

    # Build high-pass keywords table
    keywords_html = ""
    for kw in patterns.get('high_pass_keywords', [])[:8]:
        pass_rate = kw.get('pass_rate', 0) * 100
        keywords_html += f'''
        <tr>
            <td style="font-weight:500">{kw.get('keyword', '')}</td>
            <td>{kw.get('times_analyzed', 0)}</td>
            <td style="color:#ef4444;font-weight:600">{pass_rate:.0f}%</td>
        </tr>'''

    # Calculate buy rate
    total = analytics.get('total_analyzed', 0)
    buys = analytics.get('buy_count', 0)
    buy_rate = (buys / total * 100) if total > 0 else 0

    return f"""<!DOCTYPE html>
<html><head>
<title>Analytics Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }}
.header {{ background: #1a1a2e; padding: 20px 30px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; }}
.logo {{ font-size: 20px; font-weight: 700; color: #fff; }}
.logo span {{ color: #6366f1; }}
.nav {{ display: flex; gap: 15px; }}
.nav a {{ color: #888; text-decoration: none; padding: 8px 16px; border-radius: 6px; transition: all 0.2s; }}
.nav a:hover, .nav a.active {{ color: #fff; background: rgba(99,102,241,0.2); }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 25px; }}
.page-title {{ font-size: 28px; font-weight: 700; margin-bottom: 25px; color: #fff; }}

/* Stats Cards */
.stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 20px; margin-bottom: 30px; }}
.stat-card {{ background: linear-gradient(135deg, #1a1a2e 0%, #252540 100%); border-radius: 16px; padding: 25px; position: relative; overflow: hidden; }}
.stat-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: linear-gradient(90deg, #6366f1, #8b5cf6); }}
.stat-card.green::before {{ background: linear-gradient(90deg, #22c55e, #16a34a); }}
.stat-card.red::before {{ background: linear-gradient(90deg, #ef4444, #dc2626); }}
.stat-card.yellow::before {{ background: linear-gradient(90deg, #f59e0b, #d97706); }}
.stat-value {{ font-size: 36px; font-weight: 800; color: #fff; margin-bottom: 5px; }}
.stat-label {{ font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
.stat-sub {{ font-size: 12px; color: #666; margin-top: 8px; }}

/* Charts */
.charts-row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 30px; }}
.chart-card {{ background: #1a1a2e; border-radius: 16px; padding: 25px; }}
.chart-title {{ font-size: 16px; font-weight: 600; margin-bottom: 20px; color: #fff; display: flex; align-items: center; gap: 10px; }}
.chart-title::before {{ content: ''; width: 4px; height: 20px; background: #6366f1; border-radius: 2px; }}
.chart-container {{ position: relative; height: 280px; }}

/* Tables */
.tables-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.table-card {{ background: #1a1a2e; border-radius: 16px; overflow: hidden; }}
.table-header {{ padding: 20px 25px; border-bottom: 1px solid #333; font-weight: 600; color: #fff; display: flex; align-items: center; gap: 10px; }}
.table-header::before {{ content: ''; width: 4px; height: 20px; background: #6366f1; border-radius: 2px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 14px 20px; text-align: left; border-bottom: 1px solid #252540; }}
th {{ background: #252540; color: #888; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ font-size: 14px; }}
tr:hover {{ background: rgba(99,102,241,0.05); }}

/* Responsive */
@media (max-width: 1200px) {{
    .stats-grid {{ grid-template-columns: repeat(3, 1fr); }}
    .charts-row, .tables-row {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 768px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head><body>
<div class="header">
    <div class="logo">Claude <span>Proxy v3</span></div>
    <div class="nav">
        <a href="/">Dashboard</a>
        <a href="/patterns">Patterns</a>
        <a href="/analytics" class="active">Analytics</a>
    </div>
</div>

<div class="container">
    <h1 class="page-title">Analytics Dashboard</h1>

    <!-- Stats Cards -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{analytics.get('total_analyzed', 0):,}</div>
            <div class="stat-label">Total Analyzed</div>
            <div class="stat-sub">All time listings</div>
        </div>
        <div class="stat-card green">
            <div class="stat-value" style="color:#22c55e">{analytics.get('buy_count', 0):,}</div>
            <div class="stat-label">BUY Signals</div>
            <div class="stat-sub">{buy_rate:.1f}% of analyzed</div>
        </div>
        <div class="stat-card red">
            <div class="stat-value" style="color:#ef4444">{analytics.get('pass_count', 0):,}</div>
            <div class="stat-label">PASS Signals</div>
            <div class="stat-sub">Filtered out</div>
        </div>
        <div class="stat-card yellow">
            <div class="stat-value" style="color:#f59e0b">{analytics.get('actual_purchases', 0)}</div>
            <div class="stat-label">Purchases Made</div>
            <div class="stat-sub">Following BUY signals</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${analytics.get('total_profit', 0):,.0f}</div>
            <div class="stat-label">Total Profit</div>
            <div class="stat-sub">Tracked outcomes</div>
        </div>
    </div>

    <!-- Charts Row -->
    <div class="charts-row">
        <div class="chart-card">
            <div class="chart-title">Daily Activity (Last 7 Days)</div>
            <div class="chart-container">
                <canvas id="dailyChart"></canvas>
            </div>
        </div>
        <div class="chart-card">
            <div class="chart-title">By Category</div>
            <div class="chart-container">
                <canvas id="categoryChart"></canvas>
            </div>
        </div>
    </div>

    <!-- Keywords Chart -->
    <div class="chart-card" style="margin-bottom:30px;">
        <div class="chart-title">Top PASS Keywords (Negative Filter Candidates)</div>
        <div class="chart-container" style="height:220px;">
            <canvas id="keywordsChart"></canvas>
        </div>
    </div>

    <!-- Tables Row -->
    <div class="tables-row">
        <div class="table-card">
            <div class="table-header">Recent Listings</div>
            <table>
                <thead><tr><th>Title</th><th>Category</th><th>Result</th><th>Margin</th></tr></thead>
                <tbody>{recent_html if recent_html else '<tr><td colspan="4" style="text-align:center;color:#666;">No listings yet</td></tr>'}</tbody>
            </table>
        </div>
        <div class="table-card">
            <div class="table-header">High-Pass Keywords</div>
            <table>
                <thead><tr><th>Keyword</th><th>Analyzed</th><th>Pass Rate</th></tr></thead>
                <tbody>{keywords_html if keywords_html else '<tr><td colspan="3" style="text-align:center;color:#666;">Need more data</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</div>

<script>
// Fetch data and render charts
fetch('/api/analytics-data')
    .then(res => res.json())
    .then(data => {{
        // Daily Activity Line Chart
        new Chart(document.getElementById('dailyChart'), {{
            type: 'line',
            data: {{
                labels: data.daily.labels,
                datasets: [
                    {{
                        label: 'Analyzed',
                        data: data.daily.analyzed,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99,102,241,0.1)',
                        fill: true,
                        tension: 0.4
                    }},
                    {{
                        label: 'BUY',
                        data: data.daily.buys,
                        borderColor: '#22c55e',
                        backgroundColor: 'transparent',
                        tension: 0.4
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ labels: {{ color: '#888' }} }} }},
                scales: {{
                    x: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    y: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }}
                }}
            }}
        }});

        // Category Pie Chart
        new Chart(document.getElementById('categoryChart'), {{
            type: 'doughnut',
            data: {{
                labels: data.categories.labels,
                datasets: [{{
                    data: data.categories.values,
                    backgroundColor: ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'right', labels: {{ color: '#888' }} }} }}
            }}
        }});

        // Keywords Bar Chart
        new Chart(document.getElementById('keywordsChart'), {{
            type: 'bar',
            data: {{
                labels: data.keywords.labels,
                datasets: [{{
                    label: 'Pass Rate %',
                    data: data.keywords.values,
                    backgroundColor: '#ef4444'
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#888' }}, max: 100 }},
                    y: {{ grid: {{ display: false }}, ticks: {{ color: '#888' }} }}
                }}
            }}
        }});
    }});
</script>
</body></html>"""


def render_system_architecture(system_data: Dict[str, Any]) -> str:
    """Render the system architecture and understanding page"""

    # Extract data
    agents = system_data.get('agents', {})
    routes = system_data.get('routes', [])
    databases = system_data.get('databases', [])
    config = system_data.get('config', {})
    stats = system_data.get('stats', {})
    thresholds = system_data.get('thresholds', {})

    # Build agents grid
    agents_html = ""
    for name, info in agents.items():
        status_color = "#22c55e" if info.get('active') else "#888"
        agents_html += f'''
        <div class="component-card">
            <div class="component-icon">🤖</div>
            <div class="component-name">{name}</div>
            <div class="component-desc">{info.get('description', '')}</div>
            <div class="component-meta">
                <span style="color:{status_color}">● {'Active' if info.get('active') else 'Inactive'}</span>
                <span>Threshold: {info.get('threshold', 'N/A')}</span>
            </div>
        </div>'''

    # Build routes list
    routes_html = ""
    for route in routes:
        method_color = "#22c55e" if route.get('method') == 'GET' else "#f59e0b"
        routes_html += f'''
        <tr>
            <td><span class="method-badge" style="background:{method_color}">{route.get('method', 'GET')}</span></td>
            <td><code>{route.get('path', '')}</code></td>
            <td>{route.get('description', '')}</td>
        </tr>'''

    # Build databases list
    dbs_html = ""
    for db in databases:
        size_mb = db.get('size_mb', 0)
        size_color = "#f59e0b" if size_mb > 1000 else "#22c55e"
        dbs_html += f'''
        <tr>
            <td><strong>{db.get('name', '')}</strong></td>
            <td>{db.get('purpose', '')}</td>
            <td style="color:{size_color}">{size_mb:.1f} MB</td>
            <td>{db.get('records', 'N/A')}</td>
        </tr>'''

    # Build config display
    config_html = ""
    for key, value in config.items():
        config_html += f'''
        <tr>
            <td><code>{key}</code></td>
            <td>{value}</td>
        </tr>'''

    # Build stats display
    stats_html = ""
    for key, value in stats.items():
        stats_html += f'''
        <div class="stat-item">
            <div class="stat-value">{value}</div>
            <div class="stat-label">{key}</div>
        </div>'''

    return f'''<!DOCTYPE html>
<html><head>
<title>System Architecture - ClaudeProxyV3</title>
<style>
* {{ box-sizing: border-box; }}
body {{
    font-family: system-ui, -apple-system, sans-serif;
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
    color: #e0e0e0;
    padding: 20px;
    margin: 0;
    min-height: 100vh;
}}
.container {{ max-width: 1600px; margin: 0 auto; }}
h1 {{
    color: #fff;
    margin-bottom: 10px;
    font-size: 28px;
    display: flex;
    align-items: center;
    gap: 12px;
}}
.subtitle {{ color: #888; margin-bottom: 30px; font-size: 14px; }}
.back-link {{
    color: #6366f1;
    text-decoration: none;
    margin-bottom: 20px;
    display: inline-block;
    font-size: 14px;
}}
.back-link:hover {{ text-decoration: underline; }}

/* Section styling */
.section {{
    background: rgba(26, 26, 46, 0.8);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    border: 1px solid rgba(99, 102, 241, 0.1);
}}
.section-title {{
    color: #fff;
    font-size: 18px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 10px;
}}
.section-title span {{ font-size: 24px; }}

/* Stats grid */
.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
}}
.stat-item {{
    background: rgba(37, 37, 64, 0.8);
    padding: 20px;
    border-radius: 12px;
    text-align: center;
}}
.stat-value {{
    font-size: 28px;
    font-weight: bold;
    color: #6366f1;
}}
.stat-label {{
    color: #888;
    font-size: 12px;
    margin-top: 5px;
    text-transform: uppercase;
}}

/* Component cards */
.components-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
}}
.component-card {{
    background: rgba(37, 37, 64, 0.8);
    padding: 20px;
    border-radius: 12px;
    border: 1px solid rgba(99, 102, 241, 0.1);
    transition: transform 0.2s, border-color 0.2s;
}}
.component-card:hover {{
    transform: translateY(-2px);
    border-color: rgba(99, 102, 241, 0.3);
}}
.component-icon {{ font-size: 32px; margin-bottom: 12px; }}
.component-name {{
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 8px;
}}
.component-desc {{
    color: #888;
    font-size: 13px;
    line-height: 1.5;
    margin-bottom: 12px;
}}
.component-meta {{
    display: flex;
    gap: 16px;
    font-size: 12px;
    color: #888;
}}

/* Tables */
table {{
    width: 100%;
    border-collapse: collapse;
}}
th, td {{
    padding: 12px 16px;
    text-align: left;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}}
th {{
    color: #888;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    background: rgba(37, 37, 64, 0.5);
}}
td {{ font-size: 13px; }}
code {{
    background: rgba(99, 102, 241, 0.1);
    padding: 2px 8px;
    border-radius: 4px;
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 12px;
}}

/* Method badges */
.method-badge {{
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    color: #000;
}}

/* Architecture diagram */
.arch-diagram {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 40px 20px;
    background: rgba(37, 37, 64, 0.5);
    border-radius: 12px;
    margin-bottom: 20px;
    overflow-x: auto;
}}
.arch-node {{
    text-align: center;
    padding: 20px;
    min-width: 120px;
}}
.arch-node-icon {{ font-size: 40px; margin-bottom: 10px; }}
.arch-node-label {{ font-size: 12px; color: #888; }}
.arch-node-value {{ font-size: 14px; color: #fff; font-weight: 600; }}
.arch-arrow {{
    color: #6366f1;
    font-size: 24px;
    opacity: 0.6;
}}

/* File tree */
.file-tree {{
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 13px;
    line-height: 1.8;
    color: #888;
}}
.file-tree .folder {{ color: #f59e0b; }}
.file-tree .file {{ color: #6366f1; }}
.file-tree .desc {{ color: #555; font-style: italic; }}
</style>
</head>
<body>
<div class="container">
    <a href="/" class="back-link">← Back to Dashboard</a>
    <h1>🧠 System Architecture</h1>
    <p class="subtitle">ClaudeProxyV3 - eBay Arbitrage Intelligence System</p>

    <!-- Live Stats -->
    <div class="section">
        <div class="section-title"><span>📊</span> Live System Stats</div>
        <div class="stats-grid">
            {stats_html if stats_html else '<div class="stat-item"><div class="stat-value">--</div><div class="stat-label">No stats</div></div>'}
        </div>
    </div>

    <!-- Data Flow Diagram -->
    <div class="section">
        <div class="section-title"><span>🔄</span> Data Flow</div>
        <div class="arch-diagram">
            <div class="arch-node">
                <div class="arch-node-icon">📡</div>
                <div class="arch-node-value">uBuyFirst</div>
                <div class="arch-node-label">Webhook Alerts</div>
            </div>
            <div class="arch-arrow">→</div>
            <div class="arch-node">
                <div class="arch-node-icon">🔍</div>
                <div class="arch-node-value">Category Detection</div>
                <div class="arch-node-label">Route to Agent</div>
            </div>
            <div class="arch-arrow">→</div>
            <div class="arch-node">
                <div class="arch-node-icon">🤖</div>
                <div class="arch-node-value">AI Analysis</div>
                <div class="arch-node-label">GPT-4o / Tier 1+2</div>
            </div>
            <div class="arch-arrow">→</div>
            <div class="arch-node">
                <div class="arch-node-icon">✅</div>
                <div class="arch-node-value">Validation</div>
                <div class="arch-node-label">Server-side Checks</div>
            </div>
            <div class="arch-arrow">→</div>
            <div class="arch-node">
                <div class="arch-node-icon">🔔</div>
                <div class="arch-node-value">Discord Alert</div>
                <div class="arch-node-label">BUY/RESEARCH/PASS</div>
            </div>
        </div>
    </div>

    <!-- Category Agents -->
    <div class="section">
        <div class="section-title"><span>🤖</span> Category Agents</div>
        <div class="components-grid">
            {agents_html if agents_html else '<div class="component-card"><div class="component-desc">No agents loaded</div></div>'}
        </div>
    </div>

    <!-- Databases -->
    <div class="section">
        <div class="section-title"><span>🗄️</span> Databases</div>
        <table>
            <thead><tr><th>Database</th><th>Purpose</th><th>Size</th><th>Records</th></tr></thead>
            <tbody>
                {dbs_html if dbs_html else '<tr><td colspan="4" style="text-align:center;color:#888">No database info</td></tr>'}
            </tbody>
        </table>
    </div>

    <!-- Project Structure -->
    <div class="section">
        <div class="section-title"><span>📁</span> Project Structure</div>
        <div class="file-tree">
<span class="folder">ClaudeProxyV3/</span>
├── <span class="file">main.py</span> <span class="desc"># Core server, 8000+ lines, FastAPI app</span>
├── <span class="file">database.py</span> <span class="desc"># Seller profiling, pattern storage</span>
├── <span class="file">pricecharting_db.py</span> <span class="desc"># 117K product prices, graded card lookup</span>
├── <span class="file">prompts.py</span> <span class="desc"># AI prompts for each category</span>
├── <span class="file">ebay_poller.py</span> <span class="desc"># Direct eBay API polling</span>
├── <span class="folder">agents/</span> <span class="desc"># Category-specific analysis agents</span>
│   ├── <span class="file">gold.py, silver.py, platinum.py</span> <span class="desc"># Precious metals</span>
│   ├── <span class="file">tcg.py, lego.py, videogames.py</span> <span class="desc"># Collectibles</span>
│   ├── <span class="file">watch.py, knives.py, pens.py</span> <span class="desc"># Specialty items</span>
│   └── <span class="file">base.py</span> <span class="desc"># Abstract base class</span>
├── <span class="folder">routes/</span> <span class="desc"># API endpoint handlers</span>
│   ├── <span class="file">analysis.py</span> <span class="desc"># Main /match_mydata endpoint</span>
│   ├── <span class="file">ebay.py</span> <span class="desc"># eBay API routes</span>
│   └── <span class="file">websocket.py</span> <span class="desc"># Live dashboard WebSocket</span>
├── <span class="folder">utils/</span> <span class="desc"># Utility modules</span>
│   ├── <span class="file">discord.py</span> <span class="desc"># Discord webhook + TTS</span>
│   ├── <span class="file">extraction.py</span> <span class="desc"># Weight/karat extraction</span>
│   └── <span class="file">spam_detection.py</span> <span class="desc"># Seller spam blocking</span>
├── <span class="folder">templates/</span> <span class="desc"># HTML page renderers</span>
├── <span class="folder">config/</span> <span class="desc"># Settings and thresholds</span>
└── <span class="folder">pipeline/</span> <span class="desc"># Analysis pipeline components</span>
        </div>
    </div>

    <!-- Configuration -->
    <div class="section">
        <div class="section-title"><span>⚙️</span> Current Configuration</div>
        <table>
            <thead><tr><th>Setting</th><th>Value</th></tr></thead>
            <tbody>
                {config_html if config_html else '<tr><td colspan="2" style="text-align:center;color:#888">No config info</td></tr>'}
            </tbody>
        </table>
    </div>

    <!-- API Routes -->
    <div class="section">
        <div class="section-title"><span>🛣️</span> Key API Routes</div>
        <table>
            <thead><tr><th>Method</th><th>Endpoint</th><th>Description</th></tr></thead>
            <tbody>
                {routes_html if routes_html else '<tr><td colspan="3" style="text-align:center;color:#888">No routes info</td></tr>'}
            </tbody>
        </table>
    </div>
</div>

<script>
// Auto-refresh stats every 30 seconds
setTimeout(() => location.reload(), 30000);
</script>
</body></html>'''
