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
import re
from typing import List, Optional

import grpc

import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc

from src.tools.search.models import SearchQuery, ScoredProduct, SearchResult, Product
from src.tools.search.query_analyzer import QueryAnalyzerPipeline
from src.tools.search.strategies import (
    FullCatalogStrategy,
    DirectDBStrategy,
    SynonymExpansionStrategy,
)
from src.tools.search.ranker import ResultRanker
from src.tools.search.reranker import LLMReranker
from src.tools.search.cache import SearchCache
from src.tools.service_config import CATALOG_ADDR

_CATEGORY_LIST_PATTERNS: list[re.Pattern] = [
    re.compile(r"danh.?mục", re.IGNORECASE),
    re.compile(r"các.?loại", re.IGNORECASE),
    re.compile(r"thể.?loại", re.IGNORECASE),
    re.compile(r"có.*(những|gì)", re.IGNORECASE),
    re.compile(r"category", re.IGNORECASE),
]

_CATEGORY_LABELS: dict[str, str] = {
    "telescopes": "Kính thiên văn (Telescopes)",
    "binoculars": "Ống nhòm (Binoculars)",
    "flashlights": "Đèn pin (Flashlights)",
    "accessories": "Phụ kiện (Accessories)",
    "books": "Sách (Books)",
    "travel": "Du lịch (Travel)",
    "assembly": "Ống kính / Linh kiện (Assembly)",
}


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

        # Step 2.5: Category list query
        if self._is_category_list(sq):
            return await self._list_categories(sq)

        # Step 3: Chạy strategies song parallel
        pools = await self._run_strategies_parallel(sq)

        # Step 4: Merge + dedup + rule rank
        merged = self.ranker.merge_and_rank(pools, sq)
        # If user specified structured attributes (e.g., color), filter merged results
        if sq.attributes.get("color"):
            color = sq.attributes.get("color").lower()
            filtered = []
            for sp in merged:
                name = (sp.product.name or "").lower()
                desc = (sp.product.description or "").lower()
                cats = " ".join(sp.product.categories).lower() if sp.product.categories else ""
                if color in name or color in desc or color in cats:
                    filtered.append(sp)
            if filtered:
                merged = filtered
            # If no product matched color, keep merged (avoid surprising empty result)

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

    @staticmethod
    def _is_category_list(sq: SearchQuery) -> bool:
        raw = sq.raw.strip().lower()
        return any(p.search(raw) for p in _CATEGORY_LIST_PATTERNS)

    async def _list_categories(self, sq: SearchQuery) -> SearchResult:
        channel = grpc.aio.insecure_channel(CATALOG_ADDR)
        stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
        try:
            response = await stub.ListProducts(demo_pb2.Empty())
            cat_map: dict[str, int] = {}
            for p in response.products:
                for c in p.categories:
                    cat_map[c] = cat_map.get(c, 0) + 1

            lines = ["Danh mục sản phẩm hiện có:\n"]
            for c in sorted(cat_map):
                label = _CATEGORY_LABELS.get(c, c)
                count = cat_map[c]
                lines.append(f"  - {label}: {count} sản phẩm")
            lines.append("\nGợi ý: Hãy nói 'tìm [danh mục]' để xem sản phẩm trong danh mục đó!")
            return SearchResult(
                query=sq, products=[], total=0,
                strategies_used=["category_list"],
                error="\n".join(lines),
            )
        except Exception as e:
            return SearchResult.empty(f"Lỗi khi lấy danh mục: {e}")
        finally:
            await channel.close()


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
    # Quick guard: if query appears unrelated to shopping, return clear customer-facing message
    SHOPPING_KEYWORDS = (
        "mua", "mua hàng", "giá", "đơn", "sản phẩm", "tìm", "tìm kiếm",
        "kính", "telescope", "kính thiên văn", "ống nhòm", "binocular",
        "sách", "book", "đèn pin", "headphone", "tai nghe", "headphones",
    )
    low = query.lower()
    if not any(k in low for k in SHOPPING_KEYWORDS):
        return (
            "Xin lỗi — yêu cầu của bạn không phải là truy vấn tìm sản phẩm. "
            "Nếu bạn cần hỗ trợ khác, vui lòng liên hệ bộ phận chăm sóc khách hàng."
        )

    try:
        result = await _orchestrator.search(query)
    except Exception as e:
        msg = str(e)
        # Map common LLM / AWS Bedrock validation error to friendly message
        if "ValidationException" in msg or "Converse" in msg or "conversation" in msg:
            return (
                "Lỗi kết nối đến dịch vụ LLM: cuộc hội thoại hiện tại không hợp lệ. "
                "Vui lòng thử lại sau 1 vài phút hoặc liên hệ hỗ trợ kỹ thuật nếu vẫn gặp lỗi."
            )
        # Generic fallback
        return (
            "Đã xảy ra lỗi khi xử lý truy vấn. Vui lòng thử lại sau hoặc liên hệ bộ phận hỗ trợ."
        )
    
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
            f"   - ID: {p.id}\n"
            f"   - Giá: ${p.price_usd.units}\n"
            f"   - Danh mục: {', '.join(p.categories)}\n"
            f"   - Mô tả: {p.description[:100]}...\n"
        )
    
    if len(result.products) > 5:
        output_lines.append(f"\n... và {len(result.products) - 5} sản phẩm khác")
    
    return "\n".join(output_lines)
