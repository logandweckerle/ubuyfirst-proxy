"""
HTML Templates and Renderers Package
"""

from .renderers import (
    render_disabled_html,
    render_queued_html,
    render_error_html,
    format_confidence,
    render_result_html,
)

from .pages import (
    render_purchases_page,
    render_training_dashboard,
    render_patterns_page,
    render_analytics_page,
)

__all__ = [
    'render_disabled_html',
    'render_queued_html',
    'render_error_html',
    'format_confidence',
    'render_result_html',
    'render_purchases_page',
    'render_training_dashboard',
    'render_patterns_page',
    'render_analytics_page',
]
