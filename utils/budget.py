"""
OpenAI Budget Tracking Module

Tracks hourly spending on OpenAI API calls to prevent runaway costs.
Extracted from main.py for better organization.
"""

import logging
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

# Budget configuration
OPENAI_HOURLY_BUDGET = 10.0  # Max $10/hour spend on OpenAI

# Tracker state (module-level singleton)
_HOURLY_TRACKER: Dict = {
    "hour_start": datetime.now(),
    "hour_cost": 0.0,
    "calls_this_hour": 0,
    "budget_exceeded_count": 0,
}


def check_openai_budget(estimated_cost: float = 0.02) -> bool:
    """
    Check if we're within hourly OpenAI budget.
    Returns True if OK to proceed, False if budget exceeded.
    """
    now = datetime.now()
    hour_elapsed = (now - _HOURLY_TRACKER["hour_start"]).total_seconds() / 3600

    # Reset counter if new hour
    if hour_elapsed >= 1.0:
        logger.info(f"[BUDGET] Hour reset - spent ${_HOURLY_TRACKER['hour_cost']:.2f} in {_HOURLY_TRACKER['calls_this_hour']} calls")
        _HOURLY_TRACKER["hour_start"] = now
        _HOURLY_TRACKER["hour_cost"] = 0.0
        _HOURLY_TRACKER["calls_this_hour"] = 0

    # Check if adding this call would exceed budget
    if _HOURLY_TRACKER["hour_cost"] + estimated_cost > OPENAI_HOURLY_BUDGET:
        _HOURLY_TRACKER["budget_exceeded_count"] += 1
        remaining_mins = int((1.0 - hour_elapsed) * 60)
        logger.warning(f"[BUDGET] EXCEEDED: ${_HOURLY_TRACKER['hour_cost']:.2f}/${OPENAI_HOURLY_BUDGET:.2f} - skipping AI call ({remaining_mins}min until reset)")
        return False

    return True


def record_openai_cost(cost: float):
    """Record an OpenAI API call cost."""
    _HOURLY_TRACKER["hour_cost"] += cost
    _HOURLY_TRACKER["calls_this_hour"] += 1


def get_openai_budget_status() -> dict:
    """Get current budget status for dashboard."""
    now = datetime.now()
    hour_elapsed = (now - _HOURLY_TRACKER["hour_start"]).total_seconds() / 3600
    remaining_mins = max(0, int((1.0 - hour_elapsed) * 60))

    return {
        "hourly_budget": OPENAI_HOURLY_BUDGET,
        "hour_cost": _HOURLY_TRACKER["hour_cost"],
        "remaining": OPENAI_HOURLY_BUDGET - _HOURLY_TRACKER["hour_cost"],
        "calls_this_hour": _HOURLY_TRACKER["calls_this_hour"],
        "minutes_until_reset": remaining_mins,
        "budget_exceeded_count": _HOURLY_TRACKER["budget_exceeded_count"],
    }


def reset_budget_tracker():
    """Reset the budget tracker (for testing)."""
    _HOURLY_TRACKER["hour_start"] = datetime.now()
    _HOURLY_TRACKER["hour_cost"] = 0.0
    _HOURLY_TRACKER["calls_this_hour"] = 0
    _HOURLY_TRACKER["budget_exceeded_count"] = 0


def set_hourly_budget(budget: float):
    """Update the hourly budget limit."""
    global OPENAI_HOURLY_BUDGET
    OPENAI_HOURLY_BUDGET = budget
