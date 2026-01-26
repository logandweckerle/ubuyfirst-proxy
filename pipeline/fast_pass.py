"""
Fast-pass checks for the analysis pipeline.

Rule-based checks that can return results without AI calls:
- User price database match
- PriceCharting quick pass (clearly overpriced)
- Agent quick pass (plated/filled keywords)
- Gold price-per-gram quick pass
- Fast extraction instant pass (verified weight, clearly overpriced)
- Lazy image skip (verified weight, price 30%+ over max buy)
"""

import re
import logging
from typing import Optional, Tuple, Any

from fastapi.responses import JSONResponse, HTMLResponse

logger = logging.getLogger(__name__)


def check_user_price_db(title: str, total_price: str, category: str,
                        listing_enhancements: dict, lookup_user_price_fn,
                        render_result_html_fn, cache) -> Optional[Tuple[dict, str]]:
    """
    Check user price database for known item values.

    Returns (result, response_type_hint) if matched, None to continue.
    The caller handles response formatting.
    """
    user_price_match = lookup_user_price_fn(title)
    if not user_price_match:
        return None

    matched_name, price_data = user_price_match
    user_market_value = price_data['market_value']
    user_max_buy = price_data['max_buy']

    try:
        listing_price = float(str(total_price).replace('$', '').replace(',', ''))
    except:
        listing_price = 0

    if listing_price <= 0:
        return None

    profit = user_market_value - listing_price
    roi = (profit / listing_price) * 100 if listing_price > 0 else 0

    if listing_price <= user_max_buy:
        logger.info(f"[USER-PRICE] MATCH: {matched_name} -> Market ${user_market_value}, Max Buy ${user_max_buy}")
        logger.info(f"[USER-PRICE] BUY! Price ${listing_price} <= Max ${user_max_buy} (Profit ${profit:.2f}, ROI {roi:.0f}%)")
        result = {
            "Recommendation": "BUY",
            "Qualify": "Yes",
            "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, listing ${listing_price} = ${profit:.2f} profit ({roi:.0f}% ROI)",
            "confidence": 95,
            "marketprice": f"${user_market_value:.2f}",
            "Profit": f"+${profit:.2f}",
            "ROI": f"{roi:.0f}%",
            "userPriceMatch": True,
            "matchedItem": matched_name,
            "maxBuy": f"${user_max_buy:.2f}",
            "category": category,
            **listing_enhancements
        }
    elif listing_price <= user_market_value * 0.85:
        logger.info(f"[USER-PRICE] RESEARCH: Price ${listing_price} > Max ${user_max_buy} but < 85% market")
        result = {
            "Recommendation": "RESEARCH",
            "Qualify": "Maybe",
            "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, but price ${listing_price} > max buy ${user_max_buy}. Still {roi:.0f}% ROI if accurate.",
            "confidence": 75,
            "marketprice": f"${user_market_value:.2f}",
            "Profit": f"+${profit:.2f}",
            "ROI": f"{roi:.0f}%",
            "userPriceMatch": True,
            "matchedItem": matched_name,
            "maxBuy": f"${user_max_buy:.2f}",
            "category": category,
            **listing_enhancements
        }
    else:
        logger.info(f"[USER-PRICE] PASS: Price ${listing_price} too high (market ${user_market_value})")
        result = {
            "Recommendation": "PASS",
            "Qualify": "No",
            "reasoning": f"USER PRICE MATCH: {matched_name}. Market ${user_market_value}, max buy ${user_max_buy}, but listing ${listing_price} is too high.",
            "confidence": 90,
            "marketprice": f"${user_market_value:.2f}",
            "Profit": f"-${listing_price - user_max_buy:.2f}",
            "userPriceMatch": True,
            "matchedItem": matched_name,
            "maxBuy": f"${user_max_buy:.2f}",
            "category": category,
            **listing_enhancements
        }

    html = render_result_html_fn(result, category, title)
    cache.set(title, total_price, result, html)
    return result, html


def check_pc_quick_pass(pc_result: dict, category: str, title: str,
                        total_price: str, price_float: float,
                        render_result_html_fn, cache, stats: dict,
                        response_type: str) -> Optional[object]:
    """
    Quick PASS if PriceCharting shows clearly negative margin (< -$15).

    Returns Response if quick-passed, None to continue.
    """
    if not pc_result or not pc_result.get('found'):
        return None
    if pc_result.get('margin') is None:
        return None

    pc_margin = pc_result.get('margin', 0)
    pc_product = pc_result.get('product_name', 'Unknown')

    if pc_margin >= -15:
        return None

    logger.info(f"[QUICK PASS] {category.upper()}: {pc_product} margin ${pc_margin:.0f} - skipping images")

    quick_result = {
        'Qualify': 'No',
        'Recommendation': 'PASS',
        'reasoning': f"PriceCharting: {pc_product} @ ${pc_result.get('market_price', 0):.0f} market, max buy ${pc_result.get('buy_target', 0):.0f}, listing ${price_float:.0f} = ${pc_margin:.0f} margin (auto-PASS)",
        'marketprice': str(int(pc_result.get('market_price', 0))),
        'maxBuy': str(int(pc_result.get('buy_target', 0))),
        'Margin': str(int(pc_margin)),
        'Profit': str(int(pc_margin)),
        'confidence': 'High',
        'fakerisk': 'Low',
        'pcMatch': 'Yes',
        'pcProduct': pc_product[:50],
    }

    if category == 'lego':
        quick_result.update({
            'SetNumber': pc_result.get('product_id', 'Unknown'),
            'SetName': pc_product,
            'Theme': 'Unknown',
            'Retired': 'Unknown',
        })
    elif category == 'tcg':
        quick_result.update({
            'TCG': 'Pokemon',
            'ProductType': 'Unknown',
            'SetName': pc_result.get('console_name', 'Unknown'),
        })

    html = render_result_html_fn(quick_result, category, title)
    quick_result['html'] = html
    cache.set(title, total_price, quick_result, html)

    stats["pass_count"] += 1
    logger.info(f"[QUICK PASS] Saved 30+ seconds by skipping images!")

    if response_type == 'json':
        return JSONResponse(content=quick_result)
    return HTMLResponse(content=html)


def check_agent_quick_pass(category: str, data: dict, total_price: str,
                           title: str, get_agent_fn,
                           render_result_html_fn, cache, stats: dict,
                           response_type: str) -> Optional[object]:
    """
    Agent-based quick pass for category-specific keyword checks.

    Returns Response if quick-passed, None to continue.
    """
    try:
        agent_class = get_agent_fn(category)
        if not agent_class:
            return None

        agent = agent_class()
        price_float = float(str(total_price).replace('$', '').replace(',', ''))
        reason, decision = agent.quick_pass(data, price_float)

        if decision != "PASS":
            return None

        logger.info(f"[AGENT QUICK PASS] {category}: {reason}")
        quick_result = {
            'Qualify': 'No',
            'Recommendation': 'PASS',
            'reasoning': reason,
            'confidence': 95,
            'itemtype': 'Unknown',
        }
        html = render_result_html_fn(quick_result, category, title)
        quick_result['html'] = html
        cache.set(title, total_price, quick_result, html)
        stats["pass_count"] += 1

        if response_type == 'json':
            return JSONResponse(content=quick_result)
        return HTMLResponse(content=html)

    except Exception as e:
        logger.error(f"[AGENT QUICK PASS] Error: {e}")
        return None


async def check_textbook(category: str, data: dict, total_price: str, title: str,
                         get_agent_fn, render_result_html_fn, cache, stats: dict,
                         response_type: str) -> Optional[object]:
    """
    Handle textbook category with Keepa lookup instead of AI.

    Returns Response if handled, None to continue.
    """
    if category != "textbook":
        return None

    try:
        logger.info(f"[TEXTBOOK] Processing: {title[:60]}...")
        agent_class = get_agent_fn(category)
        if not agent_class:
            return None

        agent = agent_class()
        price_float = float(str(total_price).replace('$', '').replace(',', ''))
        textbook_result = await agent.analyze_textbook(data, price_float)
        logger.info(f"[TEXTBOOK] Result: {textbook_result.get('Recommendation', 'UNKNOWN')} - {textbook_result.get('reasoning', '')[:80]}")

        html = render_result_html_fn(textbook_result, category, title)
        textbook_result['html'] = html
        cache.set(title, total_price, textbook_result, html)

        if textbook_result.get('Recommendation') == 'BUY':
            stats["buy_count"] += 1
        else:
            stats["pass_count"] += 1

        if response_type == 'json':
            return JSONResponse(content=textbook_result)
        return HTMLResponse(content=html)

    except Exception as e:
        logger.error(f"[TEXTBOOK] Error: {e}")
        return None


def check_gold_price_per_gram(category: str, title: str, total_price: str,
                              render_result_html_fn, cache, stats: dict,
                              response_type: str) -> Optional[object]:
    """
    Price/gram ceiling check - DISABLED.

    Gold prices have risen significantly, so this ceiling is no longer valid.
    Let AI make decisions based on current spot prices.

    Returns None to continue to AI analysis.
    """
    # Ceiling removed - gold prices have risen significantly
    return None

    # Legacy code below - kept for reference but never executed
    if category != "gold":
        return None

    try:
        price_float = float(str(total_price).replace('$', '').replace(',', ''))

        weight_match = re.search(r'(\d+\.?\d*)\s*(?:g(?:ram)?s?|dwt)\b', title.lower())
        if not weight_match:
            return None

        title_weight = float(weight_match.group(1))
        if 'dwt' in title.lower():
            title_weight = title_weight * 1.555

        if title_weight <= 0:
            return None

        price_per_gram = price_float / title_weight
        if price_per_gram <= 100:
            return None

        logger.info(f"[QUICK PASS] Gold: ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram > $100 - skipping images")

        quick_result = {
            'Qualify': 'No',
            'Recommendation': 'PASS',
            'reasoning': f"Price ${price_float:.0f} / {title_weight}g = ${price_per_gram:.0f}/gram exceeds $100/gram ceiling (auto-PASS)",
            'karat': 'Unknown',
            'weight': f"{title_weight}g",
            'goldweight': f"{title_weight}",
            'meltvalue': 'NA',
            'maxBuy': 'NA',
            'sellPrice': 'NA',
            'Profit': 'NA',
            'Margin': 'NA',
            'confidence': 60,
            'fakerisk': 'Low',
            'itemtype': 'Unknown',
            'pricePerGram': f"${price_per_gram:.0f}",
        }

        html = render_result_html_fn(quick_result, category, title)
        quick_result['html'] = html
        cache.set(title, total_price, quick_result, html)

        stats["pass_count"] += 1
        logger.info(f"[QUICK PASS] Saved time by skipping images!")

        if response_type == 'json':
            return JSONResponse(content=quick_result)
        return HTMLResponse(content=html)

    except Exception as e:
        logger.debug(f"[QUICK PASS] Gold check error: {e}")
        return None


def check_fast_extract_pass(fast_result: Any, category: str, data: dict,
                            total_price: str, title: str,
                            render_result_html_fn, cache, stats: dict,
                            response_type: str) -> Optional[object]:
    """
    Instant PASS from fast extraction if clearly overpriced or plated.

    Handles best-offer near-miss exceptions.
    Returns Response if instant-passed, None to continue.
    """
    if fast_result is None or not fast_result.instant_pass:
        return None

    price_float = float(str(total_price).replace('$', '').replace(',', ''))
    accepts_offers = str(data.get('BestOffer', data.get('bestoffer', ''))).lower() in ['true', 'yes', '1']

    # Check if this is a near-miss that could work with best offer
    skip_instant_pass = False
    if accepts_offers and fast_result.max_buy and not fast_result.is_plated:
        gap_percent = ((price_float - fast_result.max_buy) / price_float) * 100 if price_float > 0 else 100
        native_keywords = ['navajo', 'native american', 'zuni', 'hopi', 'squash blossom',
                          'southwestern', 'turquoise', 'concho', 'old pawn']
        is_native = any(kw in title.lower() for kw in native_keywords)
        max_gap = 20 if is_native else 10

        if gap_percent <= max_gap:
            skip_instant_pass = True
            logger.info(f"[FAST] Skipping instant PASS - best offer available, gap only {gap_percent:.1f}%")

    if skip_instant_pass:
        return None

    logger.info(f"[FAST] INSTANT PASS: {fast_result.pass_reason}")

    quick_result = {
        'Qualify': 'No',
        'Recommendation': 'PASS',
        'reasoning': f"[FAST EXTRACT] {fast_result.pass_reason}",
        'karat': str(fast_result.karat) + 'K' if fast_result.karat else 'Unknown',
        'weight': f"{fast_result.weight_grams}g" if fast_result.weight_grams else 'Unknown',
        'weightSource': fast_result.weight_source,
        'goldweight': str(fast_result.weight_grams) if fast_result.weight_grams else 'Unknown',
        'meltvalue': str(int(fast_result.melt_value)) if fast_result.melt_value else 'NA',
        'maxBuy': str(int(fast_result.max_buy)) if fast_result.max_buy else 'NA',
        'confidence': fast_result.confidence,
        'itemtype': 'Plated' if fast_result.is_plated else 'Unknown',
    }

    html = render_result_html_fn(quick_result, category, title)
    quick_result['html'] = html
    cache.set(title, total_price, quick_result, html, "PASS")

    stats["pass_count"] += 1
    logger.info(f"[FAST] Saved ALL AI time with instant PASS!")

    if response_type == 'json':
        return JSONResponse(content=quick_result)
    return HTMLResponse(content=html)


def check_lazy_image_skip(fast_result: Any, category: str, price_float: float,
                          title: str, total_price: str, start_time: float,
                          render_result_html_fn, cache, stats: dict,
                          timing: dict, response_type: str) -> Optional[object]:
    """
    Skip AI entirely if we have verified weight and price is 30%+ over max buy.

    Returns Response if skipped, None to continue.
    """
    import time as _time

    if category not in ['gold', 'silver']:
        return None
    if fast_result is None:
        return None
    if not fast_result.max_buy:
        return None
    if price_float <= fast_result.max_buy * 1.3:
        return None

    # All checks passed: verified weight, price clearly too high
    logger.info(f"[LAZY] SKIP AI: verified weight {fast_result.weight_grams}g, price ${price_float:.0f} > maxBuy ${fast_result.max_buy:.0f} x 1.3")

    quick_result = {
        'Qualify': 'No',
        'Recommendation': 'PASS',
        'reasoning': f"[FAST] Verified {fast_result.weight_grams}g {fast_result.karat}K = ${fast_result.melt_value:.0f} melt, maxBuy ${fast_result.max_buy:.0f} < price ${price_float:.0f}",
        'karat': f"{fast_result.karat}K" if fast_result.karat else 'Unknown',
        'weight': f"{fast_result.weight_grams}g",
        'weightSource': fast_result.weight_source,
        'goldweight': str(fast_result.weight_grams),
        'meltvalue': str(int(fast_result.melt_value)) if fast_result.melt_value else 'NA',
        'maxBuy': str(int(fast_result.max_buy)) if fast_result.max_buy else 'NA',
        'Profit': str(int(fast_result.max_buy - price_float)) if fast_result.max_buy else 'NA',
        'confidence': fast_result.confidence,
        'category': category,
    }

    html = render_result_html_fn(quick_result, category, title)
    quick_result['html'] = html
    cache.set(title, total_price, quick_result, html, "PASS")
    stats["pass_count"] += 1

    timing['total'] = _time.time() - start_time
    logger.info(f"[LAZY] Saved 6+ seconds (no images, no AI) - PASS in {timing['total']*1000:.0f}ms")

    if response_type == 'json':
        return JSONResponse(content=quick_result)
    return HTMLResponse(content=html)


def determine_image_needs(fast_result: Any, category: str, price_float: float) -> bool:
    """
    Determine if Tier 1 AI needs images for gold/silver.

    Returns True if images should be fetched, False otherwise.
    """
    if category not in ['gold', 'silver']:
        return False

    if fast_result is None:
        logger.info(f"[LAZY] Need images: no fast_result")
        return True
    elif getattr(fast_result, 'has_non_metal', False):
        logger.info(f"[LAZY] Need images: has non-metal ({fast_result.non_metal_type})")
        return True
    elif fast_result.weight_grams is None:
        logger.info(f"[LAZY] Need images: no weight in title")
        return True
    elif fast_result.weight_source == 'estimate':
        logger.info(f"[LAZY] Need images: weight is estimated")
        return True
    elif fast_result.max_buy and price_float <= fast_result.max_buy * 1.3:
        logger.info(f"[LAZY] Need images: price ${price_float:.0f} near maxBuy ${fast_result.max_buy:.0f}, need AI verification")
        return True

    return False
