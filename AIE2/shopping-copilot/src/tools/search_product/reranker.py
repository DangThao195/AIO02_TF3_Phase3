from typing import List
from src.tools.search_product.models import Product, ScoredProduct, SearchResult


class Reranker:
    def rerank(self, sql_products: List[ScoredProduct], rag_products: List[ScoredProduct], query: str = "") -> SearchResult:
        seen = set()
        combined: List[ScoredProduct] = []

        # RAG items get highest priority if available
        for p in rag_products:
            pid = p.product.id
            if pid not in seen:
                seen.add(pid)
                combined.append(p)

        for p in sql_products:
            pid = p.product.id
            if pid not in seen:
                seen.add(pid)
                combined.append(p)

        flows = []
        if sql_products:
            flows.append("sql")
        if rag_products:
            flows.append("rag")

        return SearchResult(
            query=query,
            products=combined,
            rerank_mode="combined",
            flows_used=flows,
        )
