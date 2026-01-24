"""
Listing enrichment for the analysis pipeline.

Calculates freshness score, seller profile score, and logs race comparison data.
These enhancements are added to every analysis result.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def calculate_freshness(data: dict) -> tuple:
    """
    Calculate listing freshness from PostedTime.

    Returns (freshness_minutes, freshness_score).
    """
    freshness_minutes = None
    freshness_score = 50  # Default

    posted_time_str = data.get('PostedTime', '').replace('+', ' ')
    if posted_time_str:
        try:
            from datetime import datetime as dt_parse
            posted_time = dt_parse.strptime(posted_time_str.strip(), '%m/%d/%Y %I:%M:%S %p')
            freshness_minutes = (dt_parse.now() - posted_time).total_seconds() / 60

            if freshness_minutes < 2:
                freshness_score = 100
            elif freshness_minutes < 5:
                freshness_score = 90
            elif freshness_minutes < 15:
                freshness_score = 75
            elif freshness_minutes < 30:
                freshness_score = 60
            elif freshness_minutes < 60:
                freshness_score = 40
            else:
                freshness_score = 20

            logger.info(f"[FRESHNESS] Posted {freshness_minutes:.1f} min ago, score: {freshness_score}")
        except Exception as e:
            logger.debug(f"[FRESHNESS] Could not parse PostedTime: {e}")

    return freshness_minutes, freshness_score


def calculate_seller_score(data: dict, analyze_new_seller_fn) -> dict:
    """
    Calculate seller profile score using eBay data fields.

    Returns dict with: seller_name, seller_score, seller_type, seller_recommendation.
    """
    seller_name = data.get('SellerName', '')
    seller_score = 50
    seller_type = 'unknown'
    seller_recommendation = 'NORMAL'

    if seller_name:
        try:
            ebay_seller_data = {
                'SellerBusiness': data.get('SellerBusiness', ''),
                'SellerStore': data.get('SellerStore', ''),
                'StoreName': data.get('StoreName', ''),
                'FeedbackScore': data.get('FeedbackScore', ''),
                'FeedbackRating': data.get('FeedbackRating', ''),
                'SellerRegistration': data.get('SellerRegistration', ''),
            }
            seller_analysis = analyze_new_seller_fn(
                seller=seller_name,
                title=data.get('Title', '')[:80],
                category='',
                ebay_data=ebay_seller_data
            )
            seller_score = seller_analysis.get('score', 50)
            seller_type = seller_analysis.get('type', 'unknown')
            seller_recommendation = seller_analysis.get('recommendation', 'NORMAL')

            if seller_score >= 70:
                logger.info(f"[SELLER] HIGH VALUE: {seller_name} (score:{seller_score}, type:{seller_type})")
            elif seller_score <= 35:
                logger.info(f"[SELLER] LOW VALUE (dealer): {seller_name} (score:{seller_score})")
        except Exception as e:
            logger.debug(f"[SELLER] Could not analyze seller: {e}")

    return {
        'seller_name': seller_name,
        'seller_score': seller_score,
        'seller_type': seller_type,
        'seller_recommendation': seller_recommendation,
    }


def build_enhancements(data: dict, analyze_new_seller_fn) -> dict:
    """
    Build complete listing enhancements dict.

    Combines freshness, best offer flag, and seller scoring.
    """
    freshness_minutes, freshness_score = calculate_freshness(data)

    best_offer = str(data.get('BestOffer', '')).lower() == 'true'
    if best_offer:
        logger.info(f"[BEST OFFER] Seller accepts offers - negotiation possible")

    seller_info = calculate_seller_score(data, analyze_new_seller_fn)

    return {
        'freshness_minutes': freshness_minutes,
        'freshness_score': freshness_score,
        'best_offer': best_offer,
        **seller_info,
    }


def log_race_item(data: dict, title: str, total_price: str, item_id: str,
                  freshness_minutes: Optional[float], seller_name: str,
                  log_race_item_fn, log_listing_received_fn, race_log_ubf_item_fn):
    """
    Log item for race comparison between sources (uBuyFirst vs eBay poller).
    """
    try:
        price_float = float(str(total_price).replace('$', '').replace(',', ''))
        race_item_id = item_id if item_id else f"ubf_{hash(title + str(price_float)) % 10000000:07d}"

        log_race_item_fn(
            item_id=race_item_id,
            source="ubuyfirst",
            title=title,
            price=price_float,
            category=data.get('CategoryName', 'Unknown'),
        )
        logger.info(f"[RACE] Logged item {race_item_id} from uBuyFirst: {title[:40]}")

        log_listing_received_fn(
            item_id=race_item_id,
            source="ubf",
            posted_time=data.get('PostedTime', ''),
            title=title,
            price=price_float,
            category=data.get('CategoryName', 'Unknown'),
        )

        latency_ms = int(freshness_minutes * 60 * 1000) if freshness_minutes else 999999
        race_log_ubf_item_fn(race_item_id, title, price_float, seller_name, latency_ms)

    except Exception as e:
        logger.warning(f"[RACE] Failed to log item: {e}")
