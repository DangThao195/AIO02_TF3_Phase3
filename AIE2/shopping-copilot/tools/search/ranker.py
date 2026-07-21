# tools/search/ranker.py
"""
Merge kết quả từ nhiều strategy, dedup, rescore, rank.
"""

from typing import List, Tuple, Optional
from tools.search.models import Product, SearchQuery, ScoredProduct


class ResultRanker:
    """Merge nhiều pool results, dedup theo product_id, rescore, rank."""

    def merge_and_rank(
        self,
        pools: List[List[ScoredProduct]],
        sq: SearchQuery
    ) -> List[ScoredProduct]:
        """
        Merge nhiều pool, dedup theo product_id, rescore, sort.
        
        Dedup strategy: giữ entry có score cao nhất từ bất kỳ strategy nào.
        """
        merged: dict[str, ScoredProduct] = {}

        # Gộp tất cả pool, dedup theo product_id
        for pool in pools:
            for sp in pool:
                pid = sp.product.id
                # Dedup: giữ entry có score cao nhất
                if pid not in merged or sp.score > merged[pid].score:
                    merged[pid] = sp

        scored = list(merged.values())

        # Rescore với price/sort adjustment
        for sp in scored:
            sp.score = self._adjust_score(sp, sq)

        # Sort theo sort order
        self._sort_results(scored, sq)

        return scored

    def _adjust_score(self, sp: ScoredProduct, sq: SearchQuery) -> float:
        """
        Điều chỉnh score dựa trên price proximity và sort preference.
        """
        score = sp.score

        # Price proximity bonus (nếu có price filter)
        if sq.has_price_filter and sq.price_max:
            price = sp.product.price_usd.units
            # Bonus cho sản phẩm gần target price nhất
            proximity = 1.0 - (sq.price_max - min(price, sq.price_max)) / max(sq.price_max, 1)
            score += proximity * 10

        # Category match bonus
        if sq.category:
            cat_lower = sq.category.lower()
            for cat in sp.product.categories:
                if cat_lower in cat.lower():
                    score += 5  # Nhẹ bonus
                    break

        return score

    def _sort_results(self, products: List[ScoredProduct], sq: SearchQuery) -> None:
        """Sort products theo sort order. Mutate in-place."""
        if sq.sort == "price_asc":
            # Thấp nhất trước
            products.sort(key=lambda x: x.product.price_usd.units)
        elif sq.sort == "price_desc":
            # Cao nhất trước
            products.sort(key=lambda x: x.product.price_usd.units, reverse=True)
        else:
            # "relevance" (default) — sort theo score descending
            products.sort(key=lambda x: x.score, reverse=True)

    def top_k(self, products: List[ScoredProduct], k: int = 15) -> List[ScoredProduct]:
        """Lấy top K kết quả."""
        return products[:k]
