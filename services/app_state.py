"""
Application State Management for ClaudeProxyV3

This module provides centralized state management, replacing global variables
with a proper dataclass that can be dependency-injected.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import threading


@dataclass
class AppState:
    """
    Centralized application state for ClaudeProxyV3.

    This replaces the global variables previously scattered throughout main.py,
    providing a clean, testable, and type-safe state container.
    """

    # Feature flags
    enabled: bool = True
    debug_mode: bool = False
    queue_mode: bool = False  # Queue mode OFF - auto-analyze immediately
    ebay_poller_enabled: bool = False  # Using race mode instead

    # Request tracking
    listing_queue: Dict[str, Dict] = field(default_factory=dict)
    in_flight: Dict[str, asyncio.Event] = field(default_factory=dict)
    in_flight_results: Dict[str, tuple] = field(default_factory=dict)
    _in_flight_lock: Optional[asyncio.Lock] = field(default=None, repr=False)
    _lock_creation_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # Session statistics
    stats: Dict[str, Any] = field(default_factory=lambda: {
        "total_requests": 0,
        "api_calls": 0,
        "skipped": 0,
        "buy_count": 0,
        "pass_count": 0,
        "research_count": 0,
        "cache_hits": 0,
        "session_cost": 0.0,
        "session_start": datetime.now().isoformat(),
        "listings": {}  # Recent listings for dashboard
    })

    @property
    def in_flight_lock(self) -> asyncio.Lock:
        """
        Thread-safe lazy initialization of asyncio lock.

        Uses double-checked locking pattern to prevent race conditions
        where multiple threads could create separate locks.
        """
        if self._in_flight_lock is None:
            with self._lock_creation_lock:
                # Double-check after acquiring the lock
                if self._in_flight_lock is None:
                    self._in_flight_lock = asyncio.Lock()
        return self._in_flight_lock

    def increment_stat(self, key: str, amount: int = 1) -> None:
        """Safely increment a statistics counter."""
        if key in self.stats:
            self.stats[key] += amount

    def record_recommendation(self, recommendation: str) -> None:
        """Record a recommendation result in stats."""
        self.stats["total_requests"] += 1
        rec_lower = recommendation.lower()
        if rec_lower == "buy":
            self.stats["buy_count"] += 1
        elif rec_lower == "pass":
            self.stats["pass_count"] += 1
        elif rec_lower == "research":
            self.stats["research_count"] += 1

    def add_cost(self, cost: float) -> None:
        """Add to the session cost tracker."""
        self.stats["session_cost"] += cost

    def get_session_duration(self) -> float:
        """Get session duration in seconds."""
        start = datetime.fromisoformat(self.stats["session_start"])
        return (datetime.now() - start).total_seconds()

    def reset_stats(self) -> None:
        """Reset session statistics."""
        self.stats = {
            "total_requests": 0,
            "api_calls": 0,
            "skipped": 0,
            "buy_count": 0,
            "pass_count": 0,
            "research_count": 0,
            "cache_hits": 0,
            "session_cost": 0.0,
            "session_start": datetime.now().isoformat(),
            "listings": {}
        }

    async def check_in_flight(self, key: str) -> Optional[tuple]:
        """
        Check if a request is already in flight.
        Returns cached result if available, None otherwise.
        """
        async with self.in_flight_lock:
            if key in self.in_flight_results:
                return self.in_flight_results[key]
            if key in self.in_flight:
                # Wait for existing request to complete
                event = self.in_flight[key]

        if key in self.in_flight:
            await event.wait()
            return self.in_flight_results.get(key)

        return None

    async def start_in_flight(self, key: str) -> bool:
        """
        Mark a request as in-flight.
        Returns True if this is a new request, False if already in flight.
        """
        async with self.in_flight_lock:
            if key in self.in_flight:
                return False
            self.in_flight[key] = asyncio.Event()
            return True

    async def complete_in_flight(self, key: str, result: tuple) -> None:
        """Mark an in-flight request as complete with its result."""
        async with self.in_flight_lock:
            self.in_flight_results[key] = result
            if key in self.in_flight:
                self.in_flight[key].set()

    async def cleanup_in_flight(self, key: str, delay: float = 5.0) -> None:
        """Clean up in-flight tracking after a delay."""
        await asyncio.sleep(delay)
        async with self.in_flight_lock:
            self.in_flight.pop(key, None)
            self.in_flight_results.pop(key, None)


# ============================================================
# FastAPI Dependency Injection Helpers
# ============================================================

def get_app_state_from_request(request) -> "AppState":
    """
    FastAPI dependency to get AppState from request.

    Usage in routes:
        from services.app_state import get_app_state_from_request

        @router.get("/endpoint")
        async def endpoint(request: Request):
            app_state = get_app_state_from_request(request)
            app_state.increment_stat("total_requests")
    """
    return request.app.state.app_state


def get_app_state_dependency():
    """
    FastAPI Depends() compatible dependency.

    Usage:
        from fastapi import Depends
        from services.app_state import get_app_state_dependency, AppState

        @router.get("/endpoint")
        async def endpoint(app_state: AppState = Depends(get_app_state_dependency())):
            app_state.increment_stat("total_requests")
    """
    from fastapi import Request

    async def _get_state(request: Request) -> AppState:
        return request.app.state.app_state

    return _get_state