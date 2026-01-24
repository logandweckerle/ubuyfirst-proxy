"""
Queue management endpoints.

Handles queued listing analysis:
- /analyze-queued: Analyze from queue, redirect to dashboard
- /analyze-now: Analyze and return HTML directly to panel
"""

import json
import logging
import traceback

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["queue"])

# Module state (set by configure_queue)
_client = None
_model_fast = None
_cost_per_call = None
_listing_queue = None
_queue_mode_ref = None
_stats = None
_cache = None
_process_image_list = None
_get_category_prompt = None
_get_agent_prompt = None
_format_listing_data = None
_sanitize_json_response = None
_validate_and_fix_margin = None
_get_agent = None
_render_result_html = None
_save_listing = None
_update_pattern_outcome = None


def configure_queue(client, model_fast, cost_per_call, listing_queue,
                    queue_mode_ref, stats, cache, process_image_list_fn,
                    get_category_prompt_fn, get_agent_prompt_fn,
                    format_listing_data_fn, sanitize_json_response_fn,
                    validate_and_fix_margin_fn, get_agent_fn,
                    render_result_html_fn, save_listing_fn,
                    update_pattern_outcome_fn):
    """Configure module dependencies."""
    global _client, _model_fast, _cost_per_call, _listing_queue
    global _queue_mode_ref, _stats, _cache, _process_image_list
    global _get_category_prompt, _get_agent_prompt, _format_listing_data
    global _sanitize_json_response, _validate_and_fix_margin, _get_agent
    global _render_result_html, _save_listing, _update_pattern_outcome

    _client = client
    _model_fast = model_fast
    _cost_per_call = cost_per_call
    _listing_queue = listing_queue
    _queue_mode_ref = queue_mode_ref
    _stats = stats
    _cache = cache
    _process_image_list = process_image_list_fn
    _get_category_prompt = get_category_prompt_fn
    _get_agent_prompt = get_agent_prompt_fn
    _format_listing_data = format_listing_data_fn
    _sanitize_json_response = sanitize_json_response_fn
    _validate_and_fix_margin = validate_and_fix_margin_fn
    _get_agent = get_agent_fn
    _render_result_html = render_result_html_fn
    _save_listing = save_listing_fn
    _update_pattern_outcome = update_pattern_outcome_fn
    logger.info("[QUEUE ROUTES] Module configured")


@router.post("/analyze-queued/{listing_id}")
async def analyze_queued(listing_id: str):
    """Analyze a specific queued listing."""
    if listing_id not in _listing_queue:
        return RedirectResponse(url="/", status_code=303)

    queued = _listing_queue[listing_id]

    # Temporarily disable queue mode
    original_queue_mode = _queue_mode_ref[0]
    _queue_mode_ref[0] = False

    try:
        data = queued["data"]
        raw_images = queued.get("raw_images", queued.get("images", []))
        category = queued["category"]
        title = queued["title"]
        total_price = queued["total_price"]

        _stats["api_calls"] += 1
        _stats["session_cost"] += _cost_per_call

        # Fetch images
        images = []
        if raw_images:
            images = await _process_image_list(raw_images)

        # Build prompt
        category_prompt = _get_category_prompt(category)
        listing_text = _format_listing_data(data)
        user_message = f"{category_prompt}\n\n{listing_text}"

        if images:
            message_content = [{"type": "text", "text": user_message}]
            message_content.extend(images[:5])
        else:
            message_content = user_message

        # Call Claude
        response = await _client.messages.create(
            model=_model_fast,
            max_tokens=500,
            system=_get_agent_prompt(category),
            messages=[{"role": "user", "content": message_content}]
        )

        raw_response = response.content[0].text.strip()
        response_text = _sanitize_json_response(raw_response)
        result = json.loads(response_text)

        # Agent validation
        agent_class = _get_agent(category)
        if agent_class:
            agent = agent_class()
            result = agent.validate_response(result)

        result['listingPrice'] = total_price
        result = _validate_and_fix_margin(result, total_price, category, title, data)

        recommendation = result.get('Recommendation', 'RESEARCH')

        # Update stats
        if recommendation == "BUY":
            _stats["buy_count"] += 1
        elif recommendation == "PASS":
            _stats["pass_count"] += 1
        else:
            _stats["research_count"] += 1

        # Save to database
        listing_record = {
            "id": listing_id,
            "timestamp": queued["timestamp"],
            "title": title,
            "total_price": total_price,
            "category": category,
            "recommendation": recommendation,
            "margin": result.get('Profit', result.get('Margin', 'NA')),
            "confidence": result.get('confidence', 'NA'),
            "reasoning": result.get('reasoning', ''),
            "raw_response": raw_response,
            "input_data": {k: v for k, v in data.items() if k != 'images'}
        }

        _stats["listings"][listing_id] = listing_record
        _save_listing(listing_record)

        margin_val = result.get('Profit', result.get('Margin', '0'))
        conf_val = result.get('confidence', '')
        _update_pattern_outcome(title, category, recommendation, margin_val, conf_val, '')

        # Cache the result
        result['listingPrice'] = total_price
        html = _render_result_html(result, category, title)
        _cache.set(title, total_price, result, html, recommendation, category)
        logger.info(f"Cached result for: {title[:40]}...")

        # Remove from queue
        del _listing_queue[listing_id]
        logger.info(f"Analyzed queued listing: {recommendation}")

    finally:
        _queue_mode_ref[0] = original_queue_mode

    return RedirectResponse(url="/", status_code=303)


@router.post("/analyze-now/{listing_id}")
async def analyze_now(listing_id: str):
    """Analyze a queued listing and return HTML directly to the panel."""
    if listing_id not in _listing_queue:
        return HTMLResponse(content='''
        <div style="color:#ef4444;padding:20px;text-align:center;">
        Listing not found in queue. Try clicking the listing again.
        </div>''')

    queued = _listing_queue[listing_id]

    try:
        data = queued["data"]
        raw_images = queued.get("raw_images", [])
        category = queued["category"]
        title = queued["title"]
        total_price = queued["total_price"]

        _stats["api_calls"] += 1
        _stats["session_cost"] += _cost_per_call

        # Fetch images
        images = []
        if raw_images:
            images = await _process_image_list(raw_images)
            logger.info(f"[analyze-now] Fetched {len(images)} images")

        # Build prompt
        category_prompt = _get_category_prompt(category)
        listing_text = _format_listing_data(data)
        user_message = f"{category_prompt}\n\n{listing_text}"

        if images:
            message_content = [{"type": "text", "text": user_message}]
            message_content.extend(images[:5])
        else:
            message_content = user_message

        # Call Claude
        response = await _client.messages.create(
            model=_model_fast,
            max_tokens=500,
            system=_get_agent_prompt(category),
            messages=[{"role": "user", "content": message_content}]
        )

        raw_response = response.content[0].text.strip()
        response_text = _sanitize_json_response(raw_response)
        result = json.loads(response_text)

        if 'reasoning' in result:
            result['reasoning'] = result['reasoning'].encode('ascii', 'ignore').decode('ascii')

        # Agent validation
        agent_class = _get_agent(category)
        if agent_class:
            agent = agent_class()
            result = agent.validate_response(result)

        result['listingPrice'] = total_price
        result = _validate_and_fix_margin(result, total_price, category, title, data)

        recommendation = result.get('Recommendation', 'RESEARCH')

        # Update stats
        if recommendation == "BUY":
            _stats["buy_count"] += 1
        elif recommendation == "PASS":
            _stats["pass_count"] += 1
        else:
            _stats["research_count"] += 1

        # Save to database
        listing_record = {
            "id": listing_id,
            "timestamp": queued["timestamp"],
            "title": title,
            "total_price": total_price,
            "category": category,
            "recommendation": recommendation,
            "margin": result.get('Profit', result.get('Margin', 'NA')),
            "confidence": result.get('confidence', 'NA'),
            "reasoning": result.get('reasoning', ''),
            "raw_response": raw_response,
            "input_data": {k: v for k, v in data.items() if k != 'images'}
        }

        _stats["listings"][listing_id] = listing_record
        _save_listing(listing_record)

        margin_val = result.get('Profit', result.get('Margin', '0'))
        conf_val = result.get('confidence', '')
        _update_pattern_outcome(title, category, recommendation, margin_val, conf_val, '')

        # Cache the result
        result['listingPrice'] = total_price
        result['category'] = category
        html = _render_result_html(result, category, title)
        result['html'] = html
        _cache.set(title, total_price, result, html, recommendation, category)

        # Remove from queue
        del _listing_queue[listing_id]
        logger.info(f"Analyze-now complete: {recommendation}")

        # Add hint to click again for columns
        columns_hint = '''<div style="text-align:center;margin-top:10px;padding:8px;background:#e0e7ff;border-radius:8px;font-size:11px;color:#4338ca;">
        Click listing again to update columns
        </div></div></body></html>'''
        html_with_hint = html.replace('</div></div></body></html>', columns_hint)

        return HTMLResponse(content=html_with_hint)

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return HTMLResponse(content=f'''
        <div style="background:#f8d7da;color:#721c24;padding:20px;border-radius:12px;text-align:center;">
        <div style="font-size:24px;font-weight:bold;">PARSE ERROR</div>
        <div style="margin-top:10px;">Could not parse AI response</div>
        </div>''')

    except Exception as e:
        logger.error(f"Analyze-now error: {e}")
        traceback.print_exc()
        return HTMLResponse(content=f'''
        <div style="background:#f8d7da;color:#721c24;padding:20px;border-radius:12px;text-align:center;">
        <div style="font-size:24px;font-weight:bold;">ERROR</div>
        <div style="margin-top:10px;">{str(e)[:100]}</div>
        </div>''')
