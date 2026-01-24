"""
Analytics Routes - Pattern analytics and chart data endpoints
Extracted from main.py for modularity

This module contains:
- /api/analytics endpoint for raw analytics data
- /api/patterns endpoint for pattern analytics
- /api/analytics-data endpoint for formatted chart data
- /patterns page endpoint
- /analytics page endpoint
"""

import logging
from typing import Dict, Callable

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

# Create router for analytics endpoints
router = APIRouter(tags=["analytics"])

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_analytics)
# ============================================================

_config: Dict = {
    "get_analytics": None,
    "get_pattern_analytics": None,
    "render_patterns_page": None,
    "render_analytics_page": None,
}


def configure_analytics(
    get_analytics: Callable,
    get_pattern_analytics: Callable,
    render_patterns_page: Callable,
    render_analytics_page: Callable,
):
    """Configure the analytics module with all required dependencies."""
    global _config

    _config["get_analytics"] = get_analytics
    _config["get_pattern_analytics"] = get_pattern_analytics
    _config["render_patterns_page"] = render_patterns_page
    _config["render_analytics_page"] = render_analytics_page

    logger.info("[ANALYTICS ROUTES] Module configured")


# ============================================================
# API ENDPOINTS
# ============================================================

@router.get("/api/analytics")
async def api_analytics():
    """Get raw analytics data"""
    get_analytics = _config["get_analytics"]
    return get_analytics()


@router.get("/api/patterns")
async def api_patterns():
    """Get pattern analytics data"""
    get_pattern_analytics = _config["get_pattern_analytics"]
    return get_pattern_analytics()


@router.get("/api/analytics-data")
async def analytics_data():
    """JSON endpoint for chart data - formatted for Chart.js"""
    get_analytics = _config["get_analytics"]
    get_pattern_analytics = _config["get_pattern_analytics"]

    analytics = get_analytics()
    patterns = get_pattern_analytics()

    # Format daily trend for chart
    daily_labels = []
    daily_analyzed = []
    daily_buys = []
    daily_passes = []

    for day in reversed(analytics.get('daily_trend', [])):
        daily_labels.append(day.get('date', '')[-5:])  # MM-DD format
        daily_analyzed.append(day.get('total_analyzed', 0))
        daily_buys.append(day.get('buy_count', 0))
        daily_passes.append(day.get('pass_count', 0))

    # Format category data for donut chart
    cat_labels = []
    cat_values = []
    cat_colors = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

    for i, cat in enumerate(analytics.get('by_category', [])):
        cat_labels.append(cat.get('category', 'Unknown').upper())
        cat_values.append(cat.get('cnt', 0))

    # Format keyword data for bar chart
    kw_labels = []
    kw_pass_rates = []
    kw_counts = []

    for kw in patterns.get('high_pass_keywords', [])[:10]:
        kw_labels.append(kw.get('keyword', '')[:15])
        kw_pass_rates.append(round(kw.get('pass_rate', 0) * 100, 1))
        kw_counts.append(kw.get('times_analyzed', 0))

    return {
        "totals": {
            "analyzed": analytics.get('total_analyzed', 0),
            "buys": analytics.get('buy_count', 0),
            "passes": analytics.get('pass_count', 0),
            "purchases": analytics.get('actual_purchases', 0),
            "profit": analytics.get('total_profit', 0)
        },
        "daily": {
            "labels": daily_labels,
            "analyzed": daily_analyzed,
            "buys": daily_buys,
            "passes": daily_passes
        },
        "categories": {
            "labels": cat_labels,
            "values": cat_values,
            "colors": cat_colors[:len(cat_labels)]
        },
        "keywords": {
            "labels": kw_labels,
            "passRates": kw_pass_rates,
            "counts": kw_counts
        }
    }


# ============================================================
# PAGE ENDPOINTS
# ============================================================

@router.get("/patterns", response_class=HTMLResponse)
async def patterns_page():
    """Pattern analytics page with waste scoring"""
    get_pattern_analytics = _config["get_pattern_analytics"]
    render_patterns_page = _config["render_patterns_page"]

    patterns = get_pattern_analytics()
    return render_patterns_page(patterns)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page():
    """Visual analytics dashboard with charts"""
    get_analytics = _config["get_analytics"]
    get_pattern_analytics = _config["get_pattern_analytics"]
    render_analytics_page = _config["render_analytics_page"]

    analytics = get_analytics()
    patterns = get_pattern_analytics()
    return render_analytics_page(analytics, patterns)
