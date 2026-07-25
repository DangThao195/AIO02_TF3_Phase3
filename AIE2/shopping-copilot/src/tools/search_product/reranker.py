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

        # Priority sorting: if query is for telescopes, prioritize actual telescopes over accessories
        q_low = query.lower()
        is_accessory_query = any(kw in q_low for kw in ["accessory", "accessories", "phụ kiện", "phu kien"])

        if is_accessory_query:
            def _is_accessory(sp: ScoredProduct) -> bool:
                pname = sp.product.name.lower()
                cats = [c.lower() for c in sp.product.categories]
                return "accessories" in cats or "accessory" in pname or any(w in pname for w in ["filter", "kit", "imager", "assembly", "book"])

            combined.sort(key=lambda sp: 0 if _is_accessory(sp) else 1)
        elif "telescope" in q_low or "kính thiên văn" in q_low or "kinh thien van" in q_low:
            def _is_actual_telescope(sp: ScoredProduct) -> bool:
                pname = sp.product.name.lower()
                non_telescope_keywords = ["filter", "assembly", "imager", "kit", "book", "tube"]
                if any(w in pname for w in non_telescope_keywords):
                    return False
                return "telescope" in pname or "explorascope" in pname

            combined.sort(key=lambda sp: 0 if _is_actual_telescope(sp) else 1)

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
