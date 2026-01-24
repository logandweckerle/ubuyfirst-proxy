"""
Application State Management for ClaudeProxyV3

This module provides centralized state management, replacing global variables
with a proper dataclass that can be dependency-injected.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import asyncio
import threading
import time
import logging

logger = logging.getLogger(__name__)


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
    _in_flight_timestamps: Dict[str, float] = field(default_factory=dict, repr=False)
    _in_flight_lock: Optional[asyncio.Lock] = field(default=None, repr=False)
    _lock_creation_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # Cleanup configuration
    IN_FLIGHT_TTL: float = field(default=300.0, repr=False)  # 5 minutes TTL
    CLEANUP_INTERVAL: float = field(default=60.0, repr=False)  # Check every 60 seconds
    MAX_LISTINGS: int = field(default=100, repr=False)  # Max listings to keep in stats

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
        event = None
        async with self.in_flight_lock:
            if key in self.in_flight_results:
                return self.in_flight_results[key]
            if key in self.in_flight:
                # Store event reference inside lock to avoid race condition
                event = self.in_flight[key]

        # Check event reference (not dict) to avoid race with cleanup task
        if event is not None:
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
            self._in_flight_timestamps[key] = time.time()
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
            self._in_flight_timestamps.pop(key, None)

    # ============================================================
    # Automatic Memory Cleanup
    # ============================================================

    async def cleanup_expired_entries(self) -> int:
        """
        Remove in-flight entries older than IN_FLIGHT_TTL.
        Also cleans orphaned results without timestamps.
        Returns the number of entries cleaned up.
        """
        current_time = time.time()
        expired_keys = []
        orphaned_count = 0

        async with self.in_flight_lock:
            # Find expired entries
            for key, created_at in list(self._in_flight_timestamps.items()):
                if current_time - created_at > self.IN_FLIGHT_TTL:
                    expired_keys.append(key)

            # Remove expired entries
            for key in expired_keys:
                self.in_flight.pop(key, None)
                self.in_flight_results.pop(key, None)
                self._in_flight_timestamps.pop(key, None)

            # Clean orphaned results (results without timestamps)
            orphaned_keys = set(self.in_flight_results.keys()) - set(self._in_flight_timestamps.keys())
            for key in orphaned_keys:
                self.in_flight_results.pop(key, None)
                orphaned_count += 1

        if expired_keys or orphaned_count:
            logger.info(f"[CLEANUP] Removed {len(expired_keys)} expired, {orphaned_count} orphaned in-flight entries")

        return len(expired_keys) + orphaned_count

    def cleanup_old_listings(self) -> int:
        """
        Trim listings dict to MAX_LISTINGS most recent entries.
        Uses dict insertion order (Python 3.7+) - oldest entries are first.
        Returns the number of entries removed.
        """
        listings = self.stats.get("listings", {})
        if len(listings) <= self.MAX_LISTINGS:
            return 0

        # Use insertion order - oldest entries are at the start of the dict
        keys_to_remove = list(listings.keys())[:-self.MAX_LISTINGS]

        for key in keys_to_remove:
            listings.pop(key, None)

        if keys_to_remove:
            logger.debug(f"[CLEANUP] Trimmed {len(keys_to_remove)} old listings")

        return len(keys_to_remove)

    async def _cleanup_loop(self) -> None:
        """Background task that periodically cleans up expired entries."""
        logger.info(f"[CLEANUP] Background cleanup started (interval={self.CLEANUP_INTERVAL}s, TTL={self.IN_FLIGHT_TTL}s)")
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                expired_count = await self.cleanup_expired_entries()
                listings_count = self.cleanup_old_listings()

                if expired_count > 0 or listings_count > 0:
                    logger.debug(f"[CLEANUP] Cycle complete: {expired_count} in-flight, {listings_count} listings removed")

            except asyncio.CancelledError:
                logger.info("[CLEANUP] Background cleanup stopped")
                break
            except Exception as e:
                logger.error(f"[CLEANUP] Error in cleanup loop: {e}")

    def start_cleanup_task(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("[CLEANUP] Cleanup task started")

    def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("[CLEANUP] Cleanup task stopped")

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics for monitoring."""
        return {
            "in_flight_count": len(self.in_flight),
            "in_flight_results_count": len(self.in_flight_results),
            "listings_count": len(self.stats.get("listings", {})),
            "listing_queue_count": len(self.listing_queue),
            "session_duration_seconds": self.get_session_duration(),
            "cleanup_task_running": self._cleanup_task is not None and not self._cleanup_task.done(),
        }


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