"""
Services Package

Business logic services extracted from main.py.
"""

from .ebay_lookup import (
    lookup_ebay_item,
    lookup_ebay_item_by_seller,
    get_ebay_search_url,
    configure_ebay_lookup,
)

from .app_state import AppState, get_app_state_from_request, get_app_state_dependency
from .error_handler import setup_error_handlers
from .exceptions import (
    ProxyException,
    AnalysisError,
    ExternalServiceError,
    ValidationError,
    SellerError,
    BlockedSellerError,
    RateLimitError,
)

__all__ = [
    # eBay lookup
    'lookup_ebay_item',
    'lookup_ebay_item_by_seller',
    'get_ebay_search_url',
    'configure_ebay_lookup',
    # App state
    'AppState',
    'get_app_state_from_request',
    'get_app_state_dependency',
    # Error handling
    'setup_error_handlers',
    'ProxyException',
    'AnalysisError',
    'ExternalServiceError',
    'ValidationError',
    'SellerError',
    'BlockedSellerError',
    'RateLimitError',
]
