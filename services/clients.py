"""
API client initialization for AI services.

Creates and configures Anthropic (Claude) and OpenAI client instances.
"""

import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


def create_anthropic_client(api_key: str) -> Any:
    """Create an async Anthropic client for Claude API calls."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    logger.info("[CLIENTS] Anthropic client initialized")
    return client


def create_openai_client(api_key: Optional[str], tier2_model: str = "gpt-4o") -> Optional[Any]:
    """
    Create an async OpenAI client for GPT API calls.

    Returns None if api_key is not provided or openai package is not installed.
    """
    if not api_key:
        logger.warning("[CLIENTS] No OpenAI API key provided")
        return None

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        logger.info(f"[CLIENTS] OpenAI client initialized (GPT-4o-mini for Tier 1, {tier2_model} for Tier 2)")
        return client
    except ImportError:
        logger.warning("[CLIENTS] openai package not installed. Run: pip install openai")
        logger.warning("[CLIENTS] All categories will fall back to Haiku")
        return None
