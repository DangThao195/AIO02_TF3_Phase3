"""
memory/cache.py - Backward compatibility module
Re-exports CacheStore from src.memory.store for cleaner imports
"""

from src.memory.store import CacheStore

__all__ = ["CacheStore"]
