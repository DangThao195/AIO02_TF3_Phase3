"""
tools/search/__init__.py — Search tool exports + ToolRegistry registration for search tools
"""

from src.tools.registry import ToolRegistry, ToolSpec

# Import filter tools to trigger their ToolSpec registration
from src.tools.search.category_filter import category_filter  # noqa: F401
from src.tools.search.price_filter import price_filter  # noqa: F401
from src.tools.search.semantic_filter import semantic_filter  # noqa: F401
from src.tools.search.multi_filter import multi_filter  # noqa: F401

from src.tools.search.query_analyzer import QueryAnalyzerPipeline
from src.tools.search.synonym_cache import SynonymCache

__all__ = ["QueryAnalyzerPipeline", "SynonymCache"]
