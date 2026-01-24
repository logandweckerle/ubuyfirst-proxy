"""
Request parsing for the analysis pipeline.

Extracts and normalizes listing data from various request formats
(JSON body, URL-encoded body, query parameters).
"""

import json
import uuid
import logging
from datetime import datetime
from urllib.parse import parse_qs
from typing import Tuple

logger = logging.getLogger(__name__)


async def parse_analysis_request(request) -> dict:
    """
    Parse incoming request into normalized listing data dict.

    Handles JSON body, URL-encoded body, and query parameters.
    Returns dict with all extracted fields.
    """
    data = {}

    # Parse query params first
    query_data = dict(request.query_params)
    if query_data:
        data = query_data
        logger.info(f"[REQUEST] Query params count: {len(query_data)}")

    # Read body for POST requests
    body = b""
    if not data:
        try:
            body = await request.body()
            logger.info(f"[REQUEST] Body length: {len(body)} bytes")
            if len(body) < 500:
                logger.info(f"[REQUEST] Body content: {body[:500]}")
        except Exception as e:
            logger.warning(f"Failed to read body: {e}")

    # Parse JSON body
    if not data and body:
        try:
            json_data = json.loads(body)
            if isinstance(json_data, dict):
                data = json_data
                logger.info("[REQUEST] Parsed as JSON")
                logger.info(f"[REQUEST] response_type: {data.get('response_type', 'NOT SET')}")
                logger.info(f"[REQUEST] llm_provider: {data.get('llm_provider', 'NOT SET')}")
                logger.info(f"[REQUEST] llm_model: {data.get('llm_model', 'NOT SET')}")
                if 'system_prompt' in data:
                    logger.info(f"[REQUEST] system_prompt length: {len(str(data.get('system_prompt', '')))}")
                if 'display_template' in data:
                    logger.info(f"[REQUEST] display_template length: {len(str(data.get('display_template', '')))}")
        except Exception:
            pass

    # Parse URL-encoded body
    if not data and body:
        try:
            parsed = parse_qs(body.decode('utf-8', errors='ignore'))
            if parsed:
                data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
                logger.info("[REQUEST] Parsed as URL-encoded")
        except Exception:
            pass

    return data


def extract_listing_fields(data: dict) -> dict:
    """
    Extract and normalize standard listing fields from parsed data.

    Returns dict with: title, total_price, alias, response_type,
    listing_id, timestamp, item_id, ebay_url, checkout_url, view_url.
    """
    title = data.get('Title', 'No title')[:80]
    total_price = data.get('TotalPrice', data.get('ItemPrice', '0'))
    alias = data.get('Alias', '')
    response_type = data.get('response_type', 'html')
    listing_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().isoformat()

    checkout_url = data.get('CheckoutUrl', data.get('checkoutUrl', data.get('checkout_url', '')))
    item_id = data.get('ItemId', data.get('itemId', data.get('item_id', '')))
    view_url = data.get('ViewUrl', data.get('viewUrl', data.get('view_url', '')))
    ebay_url = checkout_url or view_url or ''

    logger.info(f"Title: {title[:50]}")
    logger.info(f"Price: ${total_price}")
    logger.info(f"[SAVED] response_type: {response_type}")
    logger.info(f"[DEBUG] CheckoutUrl: '{checkout_url}'")
    logger.info(f"[DEBUG] ItemId: '{item_id}'")
    logger.info(f"[DEBUG] ViewUrl: '{view_url}'")
    logger.info(f"[DEBUG] ALL KEYS: {list(data.keys())}")

    return {
        'title': title,
        'total_price': total_price,
        'alias': alias,
        'response_type': response_type,
        'listing_id': listing_id,
        'timestamp': timestamp,
        'item_id': item_id,
        'ebay_url': ebay_url,
        'checkout_url': checkout_url,
        'view_url': view_url,
    }


def log_request_fields(data: dict):
    """Log seller and listing fields for profiling/debugging."""
    seller_fields = {
        'SellerName': data.get('SellerName', ''),
        'SellerBusiness': data.get('SellerBusiness', ''),
        'SellerStore': data.get('SellerStore', ''),
        'SellerCountry': data.get('SellerCountry', ''),
        'SellerRegistration': data.get('SellerRegistration', ''),
        'StoreName': data.get('StoreName', ''),
        'FeedbackScore': data.get('FeedbackScore', ''),
        'FeedbackRating': data.get('FeedbackRating', ''),
        'EbayWebsite': data.get('EbayWebsite', ''),
    }
    logger.info(f"[SELLER DATA] {seller_fields}")

    listing_fields = {
        'PostedTime': data.get('PostedTime', ''),
        'ListingType': data.get('ListingType', ''),
        'BestOffer': data.get('BestOffer', ''),
        'Returns': data.get('Returns', ''),
        'Quantity': data.get('Quantity', ''),
        'FromCountry': data.get('FromCountry', ''),
        'Condition': data.get('Condition', ''),
        'ItemPrice': data.get('ItemPrice', ''),
        'SoldTime': data.get('SoldTime', ''),
        'Authenticity': data.get('Authenticity', ''),
        'TitleMatch': data.get('TitleMatch', ''),
        'Term': data.get('Term', ''),
    }
    logger.info(f"[LISTING DATA] {listing_fields}")

    skip_keys = {'system_prompt', 'display_template', 'llm_provider', 'llm_model', 'llm_api_key', 'response_type', 'description', 'images'}
    all_values = {k: str(v)[:100] for k, v in data.items() if k not in skip_keys}
    logger.info(f"[ALL VALUES] {all_values}")
