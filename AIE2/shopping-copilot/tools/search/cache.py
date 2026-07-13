# tools/search/cache.py
"""
Search-specific cache logic.
- Full catalog cache (5 phút)
- LLM parse cache (24h) — được handle ở query_analyzer.py
- Session-level empty result cache (30 phút)
"""

import hashlib
import time
from typing import Optional, Dict, Any
from memory.cache import CacheStore


class SearchCache:
    """Cache cho search operations."""

    def __init__(self):
        self.cache = CacheStore()
        self.session_empty: Dict[str, float] = {}  # query_hash → timestamp

    def get_session_empty(self, query: str) -> bool:
        """Kiểm tra query có bị cache empty trong session hiện tại không?"""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        cached_ts = self.session_empty.get(query_hash)
        
        if cached_ts is None:
            return False
        
        # Kiểm tra TTL 30 phút
        if time.time() - cached_ts > 1800:
            del self.session_empty[query_hash]
            return False
        
        return True

    def set_session_empty(self, query: str) -> None:
        """Đánh dấu query này không có kết quả trong session hiện tại."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        self.session_empty[query_hash] = time.time()

    def clear_session_empty(self) -> None:
        """Clear toàn bộ session empty cache (khi session kết thúc)."""
        self.session_empty.clear()

    def cleanup_expired(self) -> None:
        """Dọn sạch expired entries. Gọi định kỳ."""
        now = time.time()
        expired = [
            qh for qh, ts in self.session_empty.items()
            if now - ts > 1800
        ]
        for qh in expired:
            del self.session_empty[qh]
