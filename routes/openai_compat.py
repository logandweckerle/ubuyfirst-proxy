"""
OpenAI-compatible API endpoints.

Provides /v1/models and /v1/chat/completions for LiteLLM/uBuyFirst
compatibility. Returns responses in OpenAI chat completion format.
"""

import json
import logging
import traceback

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai-compat"])

# Module state (set by configure_openai_compat)
_client = None
_model_fast = None
_enabled = None
_stats = None
_create_openai_response = None
_get_gold_prompt = None
_get_silver_prompt = None


def configure_openai_compat(client, model_fast, enabled_ref, stats,
                            create_openai_response_fn, get_gold_prompt_fn,
                            get_silver_prompt_fn):
    """Configure module dependencies."""
    global _client, _model_fast, _enabled, _stats
    global _create_openai_response, _get_gold_prompt, _get_silver_prompt
    _client = client
    _model_fast = model_fast
    _enabled = enabled_ref
    _stats = stats
    _create_openai_response = create_openai_response_fn
    _get_gold_prompt = get_gold_prompt_fn
    _get_silver_prompt = get_silver_prompt_fn
    logger.info("[OPENAI_COMPAT] Module configured")


@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": _model_fast, "object": "model", "owned_by": "anthropic"}]
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI-compatible endpoint for LiteLLM/uBuyFirst.
    Returns proper OpenAI JSON format for columns to populate.
    """
    logger.info("[/v1/chat/completions] Received request")

    try:
        body = await request.json()
        messages = body.get("messages", [])

        # Extract listing data from user message
        listing_data = {}
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    listing_data["raw_content"] = content
                elif isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            listing_data["raw_content"] = part.get("text", "")

        raw = listing_data.get("raw_content", "")

        # Get query params
        params = dict(request.query_params)
        title = params.get("Title", "Unknown")
        total_price = params.get("TotalPrice", "0")

        try:
            total_price = float(str(total_price).replace("$", "").replace(",", ""))
        except:
            total_price = 0

        # Detect category
        category = "unknown"
        raw_lower = raw.lower()
        if any(x in raw_lower for x in ["sterling", "925", "silver"]):
            category = "silver"
        elif any(x in raw_lower for x in ["10k", "14k", "18k", "22k", "24k", "karat", "gold"]):
            category = "gold"

        logger.info(f"[/v1/chat/completions] Category: {category}, Title: {title[:50]}")

        # Check if disabled
        if not _enabled[0]:
            result = {
                "Qualify": "No",
                "Recommendation": "DISABLED",
                "reasoning": "Proxy disabled - enable at localhost:8000"
            }
            return JSONResponse(content=_create_openai_response(result))

        # Run analysis
        _stats["api_calls"] += 1

        # Build prompt
        if category == "silver":
            system_prompt = _get_silver_prompt()
        elif category == "gold":
            system_prompt = _get_gold_prompt()
        else:
            system_prompt = "Analyze this listing and return JSON with Recommendation (BUY/PASS/RESEARCH), Qualify (Yes/No), and reasoning."

        # Call Claude
        try:
            response = await _client.messages.create(
                model=_model_fast,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": raw}]
            )

            raw_response = response.content[0].text
            logger.info(f"[/v1/chat/completions] Claude response: {raw_response[:200]}")

            # Parse response
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()

            result = json.loads(cleaned)

            if "Recommendation" not in result:
                result["Recommendation"] = "RESEARCH"
            if "Qualify" not in result:
                result["Qualify"] = "No"

            logger.info(f"[/v1/chat/completions] Result: {result.get('Recommendation')}")
            return JSONResponse(content=_create_openai_response(result))

        except json.JSONDecodeError as e:
            logger.error(f"[/v1/chat/completions] JSON parse error: {e}")
            result = {
                "Qualify": "No",
                "Recommendation": "RESEARCH",
                "reasoning": f"Parse error: {str(e)[:50]}"
            }
            return JSONResponse(content=_create_openai_response(result))

    except Exception as e:
        logger.error(f"[/v1/chat/completions] Error: {e}")
        traceback.print_exc()
        result = {
            "Qualify": "No",
            "Recommendation": "ERROR",
            "reasoning": f"Error: {str(e)[:50]}"
        }
        return JSONResponse(content=_create_openai_response(result))
