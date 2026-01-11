"""
Seller Routes - Seller profiling and blocked seller management endpoints
Extracted from main.py for modularity

This module contains:
- /api/sellers/* endpoints for seller profile management
- /api/blocked-sellers/* endpoints for spam seller management
"""

import asyncio
import concurrent.futures
import logging
from datetime import datetime
from typing import Callable, Optional, Set

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Create router for seller endpoints
router = APIRouter(tags=["sellers"])

# ============================================================
# MODULE-LEVEL DEPENDENCIES (Set via configure_sellers)
# ============================================================

_get_all_seller_profiles = None
_get_seller_profile_stats = None
_get_high_value_sellers = None
_calculate_seller_score = None
_analyze_new_seller = None
_populate_seller_profiles_from_purchases = None
_get_seller_profile = None
_BLOCKED_SELLERS: Set[str] = None
_save_blocked_sellers = None
_SELLER_SPAM_WINDOW = None
_SELLER_SPAM_THRESHOLD = None


def configure_sellers(
    get_all_seller_profiles: Callable,
    get_seller_profile_stats: Callable,
    get_high_value_sellers: Callable,
    calculate_seller_score: Callable,
    analyze_new_seller: Callable,
    populate_seller_profiles_from_purchases: Callable,
    get_seller_profile: Callable,
    BLOCKED_SELLERS: Set[str],
    save_blocked_sellers: Callable,
    SELLER_SPAM_WINDOW: int,
    SELLER_SPAM_THRESHOLD: int,
):
    """Configure the sellers module with required dependencies."""
    global _get_all_seller_profiles, _get_seller_profile_stats, _get_high_value_sellers
    global _calculate_seller_score, _analyze_new_seller, _populate_seller_profiles_from_purchases
    global _get_seller_profile, _BLOCKED_SELLERS, _save_blocked_sellers
    global _SELLER_SPAM_WINDOW, _SELLER_SPAM_THRESHOLD

    _get_all_seller_profiles = get_all_seller_profiles
    _get_seller_profile_stats = get_seller_profile_stats
    _get_high_value_sellers = get_high_value_sellers
    _calculate_seller_score = calculate_seller_score
    _analyze_new_seller = analyze_new_seller
    _populate_seller_profiles_from_purchases = populate_seller_profiles_from_purchases
    _get_seller_profile = get_seller_profile
    _BLOCKED_SELLERS = BLOCKED_SELLERS
    _save_blocked_sellers = save_blocked_sellers
    _SELLER_SPAM_WINDOW = SELLER_SPAM_WINDOW
    _SELLER_SPAM_THRESHOLD = SELLER_SPAM_THRESHOLD

    logger.info("[SELLERS ROUTES] Module configured")


# ============================================================
# SELLER PROFILE ENDPOINTS
# ============================================================

@router.get("/api/sellers")
async def api_sellers_list(min_score: int = 0, limit: int = 100):
    """
    Get all seller profiles, optionally filtered by minimum score.
    Usage: /api/sellers?min_score=60&limit=50
    """
    try:
        profiles = _get_all_seller_profiles(min_score=min_score, limit=limit)
        return {
            "count": len(profiles),
            "min_score_filter": min_score,
            "profiles": profiles
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/sellers/stats")
async def api_sellers_stats():
    """Get aggregate statistics about seller profiles."""
    try:
        return _get_seller_profile_stats()
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/sellers/high-value")
async def api_sellers_high_value(min_score: int = 70, limit: int = 50):
    """
    Get high-value sellers (likely to misprice).
    Usage: /api/sellers/high-value?min_score=65&limit=25
    """
    try:
        profiles = _get_high_value_sellers(min_score=min_score, limit=limit)
        return {
            "count": len(profiles),
            "min_score": min_score,
            "sellers": profiles
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/sellers/score")
async def api_seller_score(seller_id: str, title: str = "", category: str = ""):
    """
    Quick score lookup for a seller.
    Usage: /api/sellers/score?seller_id=someuser123&category=gold
    """
    try:
        # Calculate score with full analysis
        analysis = _calculate_seller_score(
            seller=seller_id,
            titles=[title] if title else None,
            category=category
        )
        return {
            "seller_id": seller_id,
            "score": analysis['final_score'],
            "avatar": analysis.get('avatar', 'UNKNOWN'),
            "avatar_color": analysis.get('avatar_color', ''),
            "avatar_description": analysis.get('avatar_description', ''),
            "all_avatars": analysis.get('all_avatars', []),
            "type": analysis['estimated_type'],
            "patterns": analysis['username_analysis']['pattern_names'],
            "breakdown": analysis['score_breakdown'],
            "recommendation": "HIGH_PRIORITY" if analysis['final_score'] >= 70 else
                             "MEDIUM_PRIORITY" if analysis['final_score'] >= 55 else "NORMAL"
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/sellers/analyze")
async def api_seller_analyze(seller_id: str, title: str = "", category: str = ""):
    """
    Analyze a seller and get their profile score.
    Usage: POST /api/sellers/analyze?seller_id=someuser123&title=14k+gold+ring&category=gold
    """
    try:
        analysis = _analyze_new_seller(seller=seller_id, title=title, category=category)
        return analysis
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/sellers/populate")
async def api_sellers_populate():
    """
    Populate seller profiles from purchase history database.
    This will analyze all sellers you've bought from and score them.
    """
    try:
        logger.info("[SELLERS] Populating profiles from purchase history...")

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        result = await loop.run_in_executor(executor, _populate_seller_profiles_from_purchases)

        return result
    except Exception as e:
        logger.error(f"[SELLERS] Populate error: {e}")
        return {"error": str(e)}


@router.get("/api/sellers/{seller_id}")
async def api_seller_profile(seller_id: str):
    """Get a specific seller's profile."""
    try:
        profile = _get_seller_profile(seller_id)
        if profile:
            return profile
        return {"error": f"Seller '{seller_id}' not found", "seller_id": seller_id}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# BLOCKED SELLERS API
# ============================================================

@router.get("/api/blocked-sellers")
async def api_blocked_sellers():
    """Get list of blocked (spam) sellers."""
    return {
        "count": len(_BLOCKED_SELLERS),
        "sellers": sorted(list(_BLOCKED_SELLERS)),
        "spam_window_seconds": _SELLER_SPAM_WINDOW,
        "spam_threshold": _SELLER_SPAM_THRESHOLD
    }


@router.post("/api/blocked-sellers/add")
async def api_add_blocked_seller(seller: str):
    """Manually add a seller to the block list."""
    seller_key = seller.lower().strip()
    if seller_key in _BLOCKED_SELLERS:
        return {"status": "already_blocked", "seller": seller}

    _BLOCKED_SELLERS.add(seller_key)
    _save_blocked_sellers(_BLOCKED_SELLERS)
    logger.info(f"[BLOCKED] Manually added seller: {seller}")
    return {
        "status": "blocked",
        "seller": seller,
        "total_blocked": len(_BLOCKED_SELLERS)
    }


@router.post("/api/blocked-sellers/remove")
async def api_remove_blocked_seller(seller: str):
    """Remove a seller from the block list."""
    seller_key = seller.lower().strip()
    if seller_key not in _BLOCKED_SELLERS:
        return {"status": "not_found", "seller": seller}

    _BLOCKED_SELLERS.discard(seller_key)
    _save_blocked_sellers(_BLOCKED_SELLERS)
    logger.info(f"[BLOCKED] Removed seller from block list: {seller}")
    return {
        "status": "unblocked",
        "seller": seller,
        "total_blocked": len(_BLOCKED_SELLERS)
    }


@router.post("/api/blocked-sellers/clear")
async def api_clear_blocked_sellers():
    """Clear all blocked sellers (use with caution)."""
    count = len(_BLOCKED_SELLERS)
    _BLOCKED_SELLERS.clear()
    _save_blocked_sellers(_BLOCKED_SELLERS)
    logger.warning(f"[BLOCKED] Cleared all {count} blocked sellers")
    return {
        "status": "cleared",
        "removed_count": count
    }


@router.post("/api/blocked-sellers/import")
async def api_import_blocked_sellers(request: Request):
    """
    Import blocked sellers from JSON body.
    Accepts: {"sellers": ["seller1", "seller2", ...]}
    Or just a list: ["seller1", "seller2", ...]
    """
    try:
        body = await request.json()

        # Handle both formats
        if isinstance(body, list):
            sellers = body
        elif isinstance(body, dict):
            sellers = body.get('sellers', [])
        else:
            return {"error": "Invalid format. Send {sellers: [...]} or [...]"}

        added = 0
        skipped = 0
        for seller in sellers:
            seller_key = str(seller).lower().strip()
            if seller_key and seller_key not in _BLOCKED_SELLERS:
                _BLOCKED_SELLERS.add(seller_key)
                added += 1
            else:
                skipped += 1

        _save_blocked_sellers(_BLOCKED_SELLERS)
        logger.info(f"[BLOCKED] Imported {added} sellers ({skipped} already blocked)")

        return {
            "status": "imported",
            "added": added,
            "skipped": skipped,
            "total_blocked": len(_BLOCKED_SELLERS)
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/blocked-sellers/export")
async def api_export_blocked_sellers():
    """Export blocked sellers as a simple list (for backup/import elsewhere)."""
    return {
        "sellers": sorted(list(_BLOCKED_SELLERS)),
        "count": len(_BLOCKED_SELLERS),
        "exported_at": datetime.now().isoformat()
    }
