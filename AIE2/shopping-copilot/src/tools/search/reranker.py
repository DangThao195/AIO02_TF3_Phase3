import re
from typing import Dict, List

from src.tools.search.models import Product, ScoredProduct, SearchResult
from src.llm.llm import get_llm_client


class Reranker:
    MODE = "llm"

    @classmethod
    def set_mode(cls, mode: str):
        cls.MODE = mode

    def rerank(
        self,
        sql_results: List[ScoredProduct],
        rag_results: List[ScoredProduct],
        query: str = "",
    ) -> SearchResult:
        merged = self._merge(sql_results, rag_results)
        if not merged:
            return SearchResult(query=query, flows_used=[], rerank_mode=self.MODE)

        flows_used = []
        if sql_results:
            flows_used.append("sql")
        if rag_results:
            flows_used.append("rag")

        if self.MODE == "llm":
            ranked = self._rerank_llm(merged, query)
        else:
            ranked = self._rerank_rule(merged, query)

        return SearchResult(
            products=ranked[:15],
            query=query,
            flows_used=flows_used,
            rerank_mode=self.MODE,
        )

    def _merge(
        self,
        sql_results: List[ScoredProduct],
        rag_results: List[ScoredProduct],
    ) -> List[ScoredProduct]:
        seen: Dict[str, ScoredProduct] = {}
        for sp in sql_results:
            pid = sp.product.id
            if pid not in seen:
                seen[pid] = sp
        for sp in rag_results:
            pid = sp.product.id
            if pid not in seen:
                seen[pid] = sp
        return list(seen.values())

    def _rerank_rule(
        self,
        products: List[ScoredProduct],
        query: str,
    ) -> List[ScoredProduct]:
        query_tokens = set(
            re.sub(r"[^a-z0-9]+", " ", query.lower()).split()
        )
        for sp in products:
            score = 0.0
            if sp.source == "sql":
                score += 30.0
            elif sp.source == "rag":
                score += 20.0
            score += sp.score
            p = sp.product
            name_lower = p.name.lower()
            for token in query_tokens:
                if len(token) <= 2:
                    continue
                if token == name_lower or name_lower.startswith(token) or name_lower.endswith(token):
                    score += 50.0
                elif token in name_lower:
                    score += 30.0
            for cat in p.categories:
                for token in query_tokens:
                    if len(token) <= 2:
                        continue
                    if token in cat.lower():
                        score += 60.0
                        break
            desc_text = " ".join([p.name.lower(), p.description.lower(), " ".join(p.categories)])
            kw_matches = sum(1 for t in query_tokens if len(t) > 2 and t in desc_text)
            score += min(kw_matches * 10.0, 50.0)
            sp.score = score
        products.sort(key=lambda x: x.score, reverse=True)
        return products

    def _rerank_llm(
        self,
        products: List[ScoredProduct],
        query: str,
    ) -> List[ScoredProduct]:
        try:
            lines = []
            for i, sp in enumerate(products, 1):
                p = sp.product
                lines.append(f"{i}. {p.name} - ${getattr(p.price_usd, 'units', 0)} - Cat: {', '.join(p.categories)}")
            product_text = "\n".join(lines)
            prompt = (
                f"Bạn là chuyên gia xếp hạng sản phẩm. "
                f"Với câu hỏi '{query}', hãy sắp xếp lại danh sách sản phẩm dưới đây "
                f"theo thứ tự phù hợp nhất (phù hợp nhất lên đầu). "
                f"Chỉ trả về số thứ tự mới, cách nhau bằng dấu phẩy, "
                f"VD: 3,1,4,2,5\n\n{product_text}"
            )
            llm = get_llm_client()
            response = llm.invoke(prompt, temperature=0.3, max_tokens=256)
            indices = [int(x.strip()) for x in response.content.split(",") if x.strip().isdigit()]
            reordered = []
            for idx in indices:
                if 1 <= idx <= len(products):
                    reordered.append(products[idx - 1])
            remaining = [p for p in products if p not in reordered]
            return reordered + remaining
        except Exception:
            return self._rerank_rule(products, query)
