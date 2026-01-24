"""
Response building for the analysis pipeline.

Assembles final result with enhancements, caches it,
and formats for the appropriate response type (JSON/HTML).
"""

import logging
from typing import Tuple

from fastapi.responses import JSONResponse, HTMLResponse

from services.deduplication import mark_as_evaluated

logger = logging.getLogger(__name__)


def finalize_result(result: dict, html: str, title: str, total_price: str,
                    listing_enhancements: dict, response_type: str,
                    timing: dict, start_time: float, cache) -> object:
    """
    Finalize analysis result: add enhancements, cache, mark evaluated, return response.

    This is the last step in the analysis pipeline, called after Tier 1/2 AI
    processing and validation are complete.
    """
    import time as _time

    # Log total timing breakdown
    _total_time = _time.time() - start_time
    timing['total'] = _total_time
    timing_summary = " | ".join([f"{k}:{v*1000:.0f}ms" for k, v in timing.items()])
    logger.info(f"[TIMING] TOTAL: {_total_time*1000:.0f}ms | {timing_summary}")

    # Add listing enhancements to result
    result['freshness_minutes'] = listing_enhancements.get('freshness_minutes')
    result['freshness_score'] = listing_enhancements.get('freshness_score')
    result['best_offer'] = listing_enhancements.get('best_offer')
    result['seller_score'] = listing_enhancements.get('seller_score')
    result['seller_type'] = listing_enhancements.get('seller_type')
    result['seller_recommendation'] = listing_enhancements.get('seller_recommendation')

    if listing_enhancements.get('seller_score', 0) >= 70:
        logger.info(f"[ENHANCEMENTS] HIGH-VALUE SELLER: score={listing_enhancements.get('seller_score')}, type={listing_enhancements.get('seller_type')}")

    # Mark as evaluated to prevent duplicate processing
    mark_as_evaluated(title, total_price, result)

    # ALWAYS include html in result for uBuyFirst display_template
    if 'html' not in result:
        result['html'] = html

    logger.info(f"[RESPONSE] FINAL Recommendation: {result.get('Recommendation')} (this should be post-Tier2)")

    if response_type == 'json':
        logger.info("[RESPONSE] Returning JSON (response_type=json) with html field for display")
        return JSONResponse(content=result)
    else:
        logger.info("[RESPONSE] Returning HTML (response_type=html)")
        return HTMLResponse(content=html)
