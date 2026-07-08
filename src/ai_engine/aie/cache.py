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
            entry = self._store.get(self._key(product_id, version))
            hit = entry is not None and entry.expires_at > time.monotonic()
            if hit:
                self._hits += 1
            self._update_ratio_locked()
            return entry.value if hit else None

    def set(self, product_id: str, version: str, value: str) -> None:
        with self._lock:
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
