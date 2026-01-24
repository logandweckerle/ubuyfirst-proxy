"""
Response formatting utilities for the proxy server.

Handles OpenAI-compatible response wrapping, JSON sanitization,
and listing data formatting for AI prompts.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from config import MODEL_FAST

logger = logging.getLogger(__name__)


def create_openai_response(result: dict, model: str = None) -> dict:
    """
    Wrap analysis result in OpenAI chat completion format.

    This format is required for uBuyFirst columns to populate.
    uBuyFirst parses the JSON from choices[0].message.content.
    """
    content_json = json.dumps(result)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": model or MODEL_FAST,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content_json
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }


def format_listing_data(data: dict) -> str:
    """Format listing data dict into readable string for AI prompts."""
    lines = ["LISTING DATA:"]
    for key, value in data.items():
        if value and key != 'images':
            display_value = str(value).replace('+', ' ') if isinstance(value, str) and '+' in value else value
            lines.append(f"- {key}: {display_value}")
    return "\n".join(lines)


def sanitize_json_response(text: str) -> str:
    """Clean up AI response text for JSON parsing."""
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    text = text.replace("```json", "").replace("```", "")

    replacements = {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u00d7 ": "-", "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Extract JSON object if there's extra text before/after
    if text and '{' in text:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start < end:
            text = text[start:end]

    # Try to parse - if it works, return as-is
    try:
        json.loads(text)
        return text.strip()
    except (json.JSONDecodeError, ValueError):
        # Only do aggressive ASCII cleanup if JSON parse fails
        text = text.encode('ascii', 'ignore').decode('ascii')
        text = " ".join(text.split())
        return text.strip()


def parse_reasoning(reasoning: str) -> dict:
    """Parse structured reasoning string into component parts."""
    parts = {"detection": "", "calc": "", "decision": "", "concerns": "", "profit": "", "raw": reasoning}

    if "|" in reasoning:
        sections = reasoning.split("|")
        for section in sections:
            section = section.strip()
            upper = section.upper()
            if upper.startswith("DETECTION:"):
                parts["detection"] = section[10:].strip()
            elif upper.startswith("CALC:"):
                parts["calc"] = section[5:].strip()
            elif upper.startswith("DECISION:"):
                parts["decision"] = section[9:].strip()
            elif upper.startswith("CONCERNS:"):
                parts["concerns"] = section[9:].strip()
            elif upper.startswith("PROFIT:"):
                parts["profit"] = section[7:].strip()

    return parts
