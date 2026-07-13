# tools/search/orchestrator.py
"""
Search Orchestrator — điều phối toàn bộ multi-strategy search pipeline.

Flow:
1. Parse query (regex → LLM fallback)
2. Chạy strategies song parallel (timeout 3s mỗi strategy)
3. Merge + dedup + rule rank
4. LLM rerank (conditional: pool > 5 AND complex query)
5. Format kết quả trả về
"""

import asyncio
from typing import List, Optional
from tools.search.models import SearchQuery, ScoredProduct, SearchResult, Product
from tools.search.query_analyzer import QueryAnalyzerPipeline
from tools.search.strategies import (
    FullCatalogStrategy,
    DirectDBStrategy,
    SynonymExpansionStrategy,
)
from tools.search.ranker import ResultRanker
from tools.search.reranker import LLMReranker
from tools.search.cache import SearchCache


class SearchOrchestrator:
    """
    Điều phối toàn bộ quy trình search.
    """

    STRATEGY_TIMEOUT = 3.0  # seconds per strategy
    DEFAULT_TOP_K = 15      # Số lượng tối đa cho ranker phase
    RERANK_THRESHOLD = 5    # Chỉ rerank nếu pool > ngưỡng này

    def __init__(self):
        self.analyzer = QueryAnalyzerPipeline()
        self.strategies: List = [
            FullCatalogStrategy(),          # Always run
            DirectDBStrategy(),             # Always run
            SynonymExpansionStrategy(),     # Run khi có VN keywords
        ]
        self.ranker = ResultRanker()
        self.reranker = LLMReranker()
        self.cache = SearchCache()

    async def search(self, raw_query: str) -> SearchResult:
        """
        Entry point cho toàn bộ search pipeline.
        """
        # Step 1: Kiểm tra session cache cho empty result
        if self.cache.get_session_empty(raw_query):
            return SearchResult.empty(
                f"Query '{raw_query}' không có kết quả (từ session cache)"
            )

        # Step 2: Parse query
        sq = self.analyzer.parse(raw_query)

        # Step 3: Chạy strategies song parallel
        pools = await self._run_strategies_parallel(sq)

        # Step 4: Merge + dedup + rule rank
        merged = self.ranker.merge_and_rank(pools, sq)
        top_n = self.ranker.top_k(merged, self.DEFAULT_TOP_K)

        # Step 5: LLM rerank nếu cần
        if len(top_n) > self.RERANK_THRESHOLD and (sq.is_complex or sq.intent == "compare"):
            top_n = await self.reranker.rerank(top_n, sq)

        # Step 6: Format + return
        if not top_n:
            # Cache empty result ở session level
            self.cache.set_session_empty(raw_query)
            # Trả về empty + full catalog fallback
            return SearchResult.empty(
                "❌ Không tìm thấy sản phẩm phù hợp. "
                "Đây là toàn bộ mặt hàng đang bán."
            )

        return SearchResult(
            query=sq,
            products=top_n,
            total=len(top_n),
            strategies_used=list(set(p.strategy_name for p in top_n))
        )

    async def _run_strategies_parallel(self, sq: SearchQuery) -> List[List[ScoredProduct]]:
        """
        Chạy tất cả strategies song parallel với timeout.
        Trả về list của list (mỗi strategy trả về 1 list).
        """
        tasks = []
        for strategy in self.strategies:
            if strategy.should_run(sq):
                tasks.append(strategy.search(sq))

        if not tasks:
            return []

        try:
            # Gather với timeout
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.STRATEGY_TIMEOUT
            )
        except asyncio.TimeoutError:
            print(f"Strategy timeout after {self.STRATEGY_TIMEOUT}s")
            results = []

        # Lọc kết quả hợp lệ (list, không exception)
        pools = [r for r in results if isinstance(r, list)]
        return pools


# ============================================================================
# Wrapper LangChain Tool
# ============================================================================

from langchain_core.tools import tool


_orchestrator = SearchOrchestrator()


@tool
async def search_products_v2(query: str) -> str:
    """
    Tìm kiếm sản phẩm thông minh bằng tiếng Việt hoặc tiếng Anh.
    
    Ví dụ:
    - "kính thiên văn dưới 100 đô"
    - "telescope under 50 dollars"
    - "rẻ nhất"
    - "binoculars"
    
    Tool này tự động:
    - Phân tích query (giá, danh mục, intent)
    - Chạy 3 chiến lược tìm kiếm song song
    - Xếp hạng kết quả theo relevance
    - Gợi ý sản phẩm phù hợp nhất
    """
    result = await _orchestrator.search(query)
    
    # Format output cho LLM
    if result.error:
        return result.error
    
    if not result.products:
        return "❌ Không tìm thấy sản phẩm phù hợp với query này."
    
    # Format kết quả
    output_lines = [
        f"✅ Tìm thấy {len(result.products)} sản phẩm:\n"
    ]
    
    for i, sp in enumerate(result.products[:5], 1):  # Top 5 only
        p = sp.product
        output_lines.append(
            f"{i}. **{p.name}**\n"
            f"   - Giá: ${p.price_usd.units}\n"
            f"   - Danh mục: {', '.join(p.categories)}\n"
            f"   - Mô tả: {p.description[:100]}...\n"
        )
    
    if len(result.products) > 5:
        output_lines.append(f"\n... và {len(result.products) - 5} sản phẩm khác")
    
    return "\n".join(output_lines)
