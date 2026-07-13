"""
memory/cache.py - Backward compatibility module
Re-exports CacheStore from memory.store for cleaner imports
"""

from memory.store import CacheStore

__all__ = ["CacheStore"]
