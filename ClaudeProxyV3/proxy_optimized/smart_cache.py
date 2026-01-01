"""
Smart Cache - Different TTLs based on recommendation type
BUY results cache shorter (might want to re-verify)
PASS results cache longer (won't change)
"""

import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict

from config import CACHE


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    result: Dict[str, Any]
    html: str
    timestamp: datetime
    recommendation: str
    category: str
    hits: int = 0
    
    def get_ttl(self) -> int:
        """Get TTL based on recommendation"""
        if self.recommendation == 'BUY':
            return CACHE.ttl_buy
        elif self.recommendation == 'PASS':
            return CACHE.ttl_pass
        elif self.recommendation == 'QUEUED':
            return CACHE.ttl_queued
        else:
            return CACHE.ttl_research
    
    def is_expired(self) -> bool:
        """Check if entry has expired"""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > self.get_ttl()
    
    def age_seconds(self) -> float:
        """Get age in seconds"""
        return (datetime.now() - self.timestamp).total_seconds()


class SmartCache:
    """
    Thread-safe LRU cache with smart TTL based on result type
    
    Features:
    - Different TTL for BUY vs PASS vs RESEARCH
    - LRU eviction when max size reached
    - Hit tracking for analytics
    - Thread-safe operations
    """
    
    def __init__(self, max_size: int = None):
        self.max_size = max_size or CACHE.max_size
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'expirations': 0
        }
    
    def _make_key(self, title: str, price: Any) -> str:
        """Create cache key from title and price"""
        # Normalize price to string
        price_str = str(price).replace('$', '').replace(',', '').strip()
        return f"{title[:100]}_{price_str}"
    
    def get(self, title: str, price: Any) -> Optional[Tuple[Dict[str, Any], str]]:
        """
        Get cached result if exists and not expired
        Returns (result, html) or None
        """
        key = self._make_key(title, price)
        
        with self._lock:
            if key not in self._cache:
                self._stats['misses'] += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                del self._cache[key]
                self._stats['expirations'] += 1
                self._stats['misses'] += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hits += 1
            self._stats['hits'] += 1
            
            return (entry.result, entry.html)
    
    def set(
        self,
        title: str,
        price: Any,
        result: Dict[str, Any],
        html: str,
        recommendation: str = 'RESEARCH',
        category: str = 'unknown'
    ) -> None:
        """Store result in cache"""
        key = self._make_key(title, price)
        
        with self._lock:
            # Evict oldest if at capacity
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
                self._stats['evictions'] += 1
            
            self._cache[key] = CacheEntry(
                result=result,
                html=html,
                timestamp=datetime.now(),
                recommendation=recommendation,
                category=category
            )
    
    def invalidate(self, title: str, price: Any) -> bool:
        """Remove specific entry from cache"""
        key = self._make_key(title, price)
        
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> int:
        """Clear all cache entries, return count cleared"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries, return count removed"""
        removed = 0
        
        with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
                removed += 1
            
            self._stats['expirations'] += removed
        
        return removed
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = (
                self._stats['hits'] / total_requests * 100
                if total_requests > 0 else 0
            )
            
            # Count by recommendation type
            by_rec = {'BUY': 0, 'PASS': 0, 'RESEARCH': 0, 'QUEUED': 0}
            for entry in self._cache.values():
                rec = entry.recommendation
                if rec in by_rec:
                    by_rec[rec] += 1
            
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.1f}%",
                'evictions': self._stats['evictions'],
                'expirations': self._stats['expirations'],
                'by_recommendation': by_rec
            }
    
    def get_entries(self, limit: int = 20) -> list:
        """Get recent cache entries for debugging"""
        with self._lock:
            entries = []
            for key, entry in list(self._cache.items())[-limit:]:
                entries.append({
                    'key': key[:50] + '...' if len(key) > 50 else key,
                    'recommendation': entry.recommendation,
                    'category': entry.category,
                    'age': f"{entry.age_seconds():.1f}s",
                    'ttl': entry.get_ttl(),
                    'expires_in': f"{max(0, entry.get_ttl() - entry.age_seconds()):.1f}s",
                    'hits': entry.hits
                })
            return entries


# Global cache instance
cache = SmartCache()


# Background cleanup task
def start_cache_cleanup(interval: int = 60):
    """Start background thread for periodic cache cleanup"""
    import time
    
    def cleanup_loop():
        while True:
            time.sleep(interval)
            removed = cache.cleanup_expired()
            if removed > 0:
                print(f"[CACHE] Cleaned up {removed} expired entries")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    print(f"[CACHE] Background cleanup started (every {interval}s)")
