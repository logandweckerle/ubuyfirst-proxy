"""
Ollama Local LLM Integration for Fast Extraction

Uses local Ollama instance for quick weight/karat extraction before
expensive API calls. Runs in ~200-400ms on RTX 2070.

Usage:
    from ollama_extract import extract_gold_silver_info, is_available

    if is_available():
        result = await extract_gold_silver_info(title, description)
        # result = {"karat": 14, "weight_grams": 7.4} or None on failure
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Ollama API settings
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_TIMEOUT = 10.0  # seconds

# Track availability
_ollama_available = None


async def check_ollama_available() -> bool:
    """Check if Ollama is running and model is loaded."""
    global _ollama_available

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get('name', '') for m in data.get('models', [])]
                if OLLAMA_MODEL in models or any(OLLAMA_MODEL.split(':')[0] in m for m in models):
                    _ollama_available = True
                    logger.info(f"[OLLAMA] Available with model {OLLAMA_MODEL}")
                    return True
        _ollama_available = False
        return False
    except Exception as e:
        logger.debug(f"[OLLAMA] Not available: {e}")
        _ollama_available = False
        return False


def is_available() -> bool:
    """Check if Ollama was detected as available."""
    return _ollama_available is True


async def extract_gold_silver_info(title: str, description: str = "") -> Optional[Dict[str, Any]]:
    """
    Use Ollama to extract karat and weight from listing.

    Returns dict with keys:
        - karat: int or None (e.g., 10, 14, 18, 24)
        - weight_grams: float or None
        - has_stones: bool (detected diamonds, gems, etc.)
        - category_hint: str or None ('gold', 'silver', 'watch', 'other')

    Returns None on error/timeout.
    """
    if not _ollama_available:
        return None

    prompt = f"""You are a JSON extractor for eBay precious metals listings. Extract information from this listing.

TITLE: {title}
DESCRIPTION: {description}

Extract:
1. Gold karat (10, 14, 18, 22, 24) or null if not gold
2. Weight in grams if stated, or null if not found
3. Whether it contains stones/gems (true/false)
4. Category: "gold", "silver", "watch", or "other"

Respond with ONLY valid JSON in this exact format:
{{"karat": 14, "weight_grams": 5.2, "has_stones": false, "category_hint": "gold"}}"""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )

            if resp.status_code != 200:
                logger.warning(f"[OLLAMA] API error: {resp.status_code}")
                return None

            data = resp.json()
            response_text = data.get("response", "").strip()

            # Parse JSON from response
            try:
                # Handle potential markdown code blocks
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]

                result = json.loads(response_text)

                # Validate and normalize
                normalized = {
                    "karat": None,
                    "weight_grams": None,
                    "has_stones": False,
                    "category_hint": None,
                }

                # Karat
                if result.get("karat"):
                    try:
                        k = int(result["karat"])
                        if k in [8, 9, 10, 12, 14, 15, 18, 20, 21, 22, 24]:
                            normalized["karat"] = k
                    except (ValueError, TypeError):
                        pass

                # Weight
                if result.get("weight_grams"):
                    try:
                        w = float(result["weight_grams"])
                        if 0.1 <= w <= 10000:  # Sanity check
                            normalized["weight_grams"] = w
                    except (ValueError, TypeError):
                        pass

                # Stones
                normalized["has_stones"] = bool(result.get("has_stones"))

                # Category
                cat = str(result.get("category_hint", "")).lower()
                if cat in ["gold", "silver", "watch", "other"]:
                    normalized["category_hint"] = cat

                # Log timing
                duration_ms = data.get("total_duration", 0) / 1_000_000
                logger.info(f"[OLLAMA] Extracted in {duration_ms:.0f}ms: karat={normalized['karat']}, weight={normalized['weight_grams']}g")

                return normalized

            except json.JSONDecodeError as e:
                logger.warning(f"[OLLAMA] JSON parse error: {e}, response: {response_text[:100]}")
                return None

    except asyncio.TimeoutError:
        logger.warning("[OLLAMA] Request timeout")
        return None
    except Exception as e:
        logger.warning(f"[OLLAMA] Error: {e}")
        return None


async def quick_category_check(title: str) -> Optional[str]:
    """
    Quick category detection using Ollama.
    Returns: 'gold', 'silver', 'watch', 'skip', or None on error.

    'skip' means the item is clearly not precious metals (e.g., clothing, electronics).
    """
    if not _ollama_available:
        return None

    prompt = f"""Categorize this eBay listing. Reply with ONLY one word.

TITLE: {title}

Categories:
- gold (gold jewelry, gold coins, gold bars)
- silver (sterling silver, silver coins, silverware)
- watch (watches, timepieces)
- skip (not precious metals - clothing, electronics, toys, etc.)

Reply with ONLY the category word, nothing else."""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                response_text = data.get("response", "").strip().lower()

                # Extract just the category word
                for cat in ["gold", "silver", "watch", "skip"]:
                    if cat in response_text:
                        return cat

    except Exception as e:
        logger.debug(f"[OLLAMA] Category check error: {e}")

    return None


# Initialize on module load
async def _init():
    await check_ollama_available()

# Try to initialize (will be called again from main if needed)
try:
    import asyncio
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.create_task(_init())
    else:
        loop.run_until_complete(_init())
except Exception:
    pass
