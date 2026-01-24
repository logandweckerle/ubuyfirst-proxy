"""
PriceCharting Routes - Video game/TCG/LEGO price lookup endpoints
Extracted from main.py for modularity

This module contains:
- /pc/* endpoints for PriceCharting database operations
- /api/pricecharting endpoint for stats
"""

import asyncio
import csv
import logging
import concurrent.futures
from io import StringIO
from typing import Callable, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Create router for PriceCharting endpoints
router = APIRouter(tags=["pricecharting"])

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_pricecharting)
# ============================================================

_pc_lookup = None
_pc_get_stats = None
_pc_refresh = None
_PRICECHARTING_AVAILABLE = False


def configure_pricecharting(
    pc_lookup: Callable,
    pc_get_stats: Callable,
    pc_refresh: Callable,
    PRICECHARTING_AVAILABLE: bool,
):
    """Configure the PriceCharting module with required dependencies."""
    global _pc_lookup, _pc_get_stats, _pc_refresh, _PRICECHARTING_AVAILABLE

    _pc_lookup = pc_lookup
    _pc_get_stats = pc_get_stats
    _pc_refresh = pc_refresh
    _PRICECHARTING_AVAILABLE = PRICECHARTING_AVAILABLE

    logger.info("[PC ROUTES] Module configured")


# ============================================================
# PRICECHARTING ENDPOINTS
# ============================================================

@router.get("/api/pricecharting")
async def api_pricecharting_stats():
    """Get PriceCharting database statistics"""
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}
    return _pc_get_stats()


@router.get("/pc/refresh")
async def pc_refresh_endpoint(force: bool = False):
    """Manually trigger PriceCharting database refresh (runs in background)"""
    if not _PRICECHARTING_AVAILABLE:
        return JSONResponse(
            content={"error": "PriceCharting module not available"},
            status_code=500
        )

    logger.info("[PC] Manual refresh triggered (background)...")

    # Run in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Fire and forget - don't wait for result
    loop.run_in_executor(executor, lambda: _pc_refresh(force=force))

    return {"status": "refresh_started", "message": "Database refresh started in background"}


@router.get("/pc/lookup")
async def pc_lookup_endpoint(q: str, category: str = None, price: float = 100):
    """
    Test PriceCharting lookup

    Usage: /pc/lookup?q=Pokemon+Evolving+Skies+Booster+Box&price=200
    """
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    result = _pc_lookup(q, category=category, listing_price=price)
    return result


@router.get("/pc/rebuild-fts")
async def pc_rebuild_fts():
    """Rebuild the FTS5 search index"""
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    try:
        from pricecharting_db import rebuild_fts_index
        result = rebuild_fts_index()
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/pc/debug")
async def pc_debug_search(q: str, category: str = None):
    """
    Debug PriceCharting search

    Usage: /pc/debug?q=LEGO+Star+Wars+75192&category=lego
    """
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    try:
        from pricecharting_db import debug_search
        result = debug_search(q, category)
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/pc/test-download")
async def pc_test_download(console: str = "lego-star-wars"):
    """
    Test downloading a specific category CSV

    Usage: /pc/test-download?console=lego-star-wars
    """
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    try:
        from pricecharting_db import download_csv
        csv_content = download_csv(console)

        if not csv_content:
            return {"error": f"Failed to download {console}"}

        # Parse first few rows to show what we got
        lines = csv_content.split('\n')[:10]

        # Parse headers
        reader = csv.DictReader(StringIO(csv_content))
        headers = reader.fieldnames

        # Get first 5 products
        products = []
        for i, row in enumerate(reader):
            if i >= 5:
                break
            products.append({
                'product_name': row.get('product-name', ''),
                'console_name': row.get('console-name', ''),
                'new_price': row.get('new-price', 0),
            })

        return {
            "console_requested": console,
            "headers": headers,
            "sample_products": products,
            "total_lines": len(csv_content.split('\n'))
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/pc/api-lookup")
async def pc_api_lookup(q: str, price: float = 100, category: str = None):
    """
    Test real-time API lookup (for LEGO sets and TCG)

    Usage: /pc/api-lookup?q=LEGO+Star+Wars+75192&price=500&category=lego
           /pc/api-lookup?q=Pokemon+Evolving+Skies+Booster+Box&price=200&category=pokemon
    """
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    try:
        from pricecharting_db import api_lookup_product
        result = api_lookup_product(q, price, category)
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/pc/upc-lookup")
async def pc_upc_lookup(upc: str, price: float = 100):
    """
    Test direct UPC lookup (most accurate method)

    Usage: /pc/upc-lookup?upc=820650853302&price=100
    """
    if not _PRICECHARTING_AVAILABLE:
        return {"error": "PriceCharting module not available"}

    try:
        from pricecharting_db import api_lookup_by_upc
        result = api_lookup_by_upc(upc, price)
        return result
    except Exception as e:
        return {"error": str(e)}
