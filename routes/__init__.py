# Routes package for ClaudeProxyV3
from .analysis import router as analysis_router, configure_analysis
from .ebay import router as ebay_router, configure_ebay, log_race_item, API_ANALYSIS_ENABLED
from .pricecharting import router as pricecharting_router, configure_pricecharting
from .sellers import router as sellers_router, configure_sellers
from .dashboard import router as dashboard_router, configure_dashboard
from .keepa import router as keepa_router, configure_keepa
from .ebay_race import router as ebay_race_router, configure_ebay_race, UBUYFIRST_PRESETS

__all__ = [
    'analysis_router', 'configure_analysis',
    'ebay_router', 'configure_ebay', 'log_race_item', 'API_ANALYSIS_ENABLED',
    'pricecharting_router', 'configure_pricecharting',
    'sellers_router', 'configure_sellers',
    'dashboard_router', 'configure_dashboard',
    'keepa_router', 'configure_keepa',
    'ebay_race_router', 'configure_ebay_race', 'UBUYFIRST_PRESETS',
]
