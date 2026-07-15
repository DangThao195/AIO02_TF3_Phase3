"""Summary cache (C4). Each cache hit = one LLM call NOT paid for (cost) and <50ms (latency).

Keyed by product_id + review-set version so a new review invalidates the stale summary.
In-memory TTL map here as the reference/local implementation; production swaps the backend
for shared valkey (decision recorded in ADR, per C4 §cache backend) without changing callers.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..common.metrics import CACHE_HIT_RATIO


def review_version(reviews: list) -> str:
    """Cheap version tag: count + hash of ids/scores. Changes when reviews change."""
    return f"{len(reviews)}:{hash(tuple(str(r) for r in reviews)) & 0xFFFFFFFF:x}"


@dataclass
class _Entry:
    value: str
    expires_at: float


class SummaryCache:
    """Thread-safe: product-reviews serves gRPC on a ThreadPoolExecutor(max_workers=10), so
    get/set and the hit counters are touched concurrently. A lock keeps the dict + counters
    consistent (bug #6 fix). Contention is negligible — operations are O(1) dict ops."""

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry] = {}
        self._hits = 0
        self._lookups = 0
        self._lock = threading.Lock()

    def _key(self, product_id: str, version: str) -> str:
        return f"{product_id}|{version}"

    def get(self, product_id: str, version: str) -> str | None:
        with self._lock:
            self._lookups += 1
            key = self._key(product_id, version)
            entry = self._store.get(key)
            if entry is None:
                self._update_ratio_locked()
                return None
            
            if entry.expires_at > time.monotonic():
                self._hits += 1
                self._update_ratio_locked()
                return entry.value
            
            # Expired -> Evict to prevent memory leak
            self._store.pop(key, None)
            self._update_ratio_locked()
            return None

    def set(self, product_id: str, version: str, value: str) -> None:
        with self._lock:
            # Cleanup expired entries if cache grows large
            if len(self._store) >= 1000:
                now = time.monotonic()
                expired_keys = [k for k, e in self._store.items() if e.expires_at <= now]
                for k in expired_keys:
                    self._store.pop(k, None)
            
            # Evict oldest if still full (FIFO eviction)
            if len(self._store) >= 1000:
                first_key = next(iter(self._store))
                self._store.pop(first_key, None)

            self._store[self._key(product_id, version)] = _Entry(
                value=value, expires_at=time.monotonic() + self._ttl
            )

    def flush(self) -> None:
        """cache-flush action (C6)."""
        with self._lock:
            self._store.clear()

    def _update_ratio_locked(self) -> None:
        if self._lookups:
            CACHE_HIT_RATIO.set(self._hits / self._lookups)
