# tools/search/strategies.py
"""
Search strategies chạy song song.
Strategy A: Full Catalog (in-memory)
Strategy B: Direct DB (gRPC)
Strategy C: Synonym Expansion (VN→EN translate)
"""

import asyncio
import re
from abc import ABC, abstractmethod
from typing import List, Optional
from rapidfuzz import fuzz
import grpc
import os

from tools.search.models import Product, SearchQuery, ScoredProduct
from tools.search.synonym_cache import SynonymCache
from memory.cache import CacheStore
import protos.demo_pb2 as demo_pb2
import protos.demo_pb2_grpc as demo_pb2_grpc


class SearchStrategy(ABC):
    """Interface cho search strategy."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tên strategy."""
        pass

    @abstractmethod
    def should_run(self, sq: SearchQuery) -> bool:
        """Có nên chạy với query này không?"""
        pass

    @abstractmethod
    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        """Thực thi search, trả về danh sách có score."""
        pass


class FullCatalogStrategy(SearchStrategy):
    """
    Load toàn bộ catalog vào cache (ListProducts).
    Filter + score in-memory.
    Luôn chạy — là baseline nhanh nhất.
    Cost: $0 (cache hit thường).
    """

    _name = "full_catalog"
    CACHE_TTL = 300  # 5 phút

    def __init__(self):
        self.cache = CacheStore()
        self.catalog_addr = os.getenv("CATALOG_ADDR", "product-catalog:3550")
        self._was_used = False

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, sq: SearchQuery) -> bool:
        """Luôn chạy."""
        return True

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        """Filter catalog in-memory, score theo rule-based."""
        self._was_used = True
        products = await self._get_all_products()
        scored = []

        for p in products:
            score = self._score_product(p, sq)
            if score > 0:  # Chỉ giữ sản phẩm có score > 0
                scored.append(ScoredProduct(
                    product=p,
                    score=score,
                    strategy_name=self.name
                ))

        # Sort giảm dần theo score
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _score_product(self, p: Product, sq: SearchQuery) -> float:
        """
        Rule-based scoring.
        
        Weights:
        - Exact name match:         100
        - Keyword in name:           50  (mỗi keyword)
        - Keyword in category:       30  (mỗi keyword)
        - Keyword in description:    20  (mỗi keyword)
        - Fuzzy name match >80%:     40
        - Category match:            60
        
        Penalty:
        - Price > max:               -1 (loại)
        - Price < min:               -1 (loại)
        """
        score = 0.0
        name_lower = p.name.lower()
        desc_lower = p.description.lower() if p.description else ""
        cats_lower = [c.lower() for c in p.categories]

        # Price penalty (loại bỏ nếu ngoài khoảng)
        if sq.has_price_filter:
            price = p.price_usd.units
            if sq.price_max is not None and price > sq.price_max:
                return -1
            if sq.price_min is not None and price < sq.price_min:
                return -1

        # Category match
        if sq.category:
            category_lower = sq.category.lower()
            for cat in cats_lower:
                if category_lower in cat or cat in category_lower:
                    score += 60
                    break

        # Name exact match
        if sq.raw.lower() == name_lower:
            score += 100
        elif sq.raw.lower() in name_lower:
            score += 80

        # Keyword matches
        for kw in sq.keywords_en:
            kw_lower = kw.lower()
            if kw_lower in name_lower:
                score += 50
            if kw_lower in desc_lower:
                score += 20
            for cat in cats_lower:
                if kw_lower in cat:
                    score += 30
                    break

        # Fuzzy match cho misspell
        for kw in sq.keywords_en:
            if len(kw) > 3:
                ratio = fuzz.partial_ratio(kw.lower(), name_lower)
                if ratio > 80:
                    score += 40
                    break

        return score

    async def _get_all_products(self) -> List[Product]:
        """Lấy từ cache hoặc gọi ListProducts gRPC."""
        cache_key = "full_catalog"
        cached = self.cache.get_raw(cache_key)
        if cached:
            return [Product.from_dict(d) for d in cached]

        # Gọi gRPC ListProducts
        try:
            # Chỉ dùng insecure channel (local dev/cluster service discovery)
            channel = grpc.aio.insecure_channel(self.catalog_addr)
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            response = await stub.ListProducts(demo_pb2.Empty())

            products = [Product(
                id=p.id,
                name=p.name,
                description=p.description or "",
                categories=list(p.categories) if hasattr(p, 'categories') else [],
                price_usd=p.price_usd or demo_pb2.Money()
            ) for p in response.products]

            await channel.close()

            # Cache
            self.cache.set_raw(
                cache_key,
                [p.to_dict() for p in products],
                ttl=self.CACHE_TTL
            )
            return products
        except Exception as e:
            print(f"Error fetching catalog: {e}")
            return []


class DirectDBStrategy(SearchStrategy):
    """
    Gọi SearchProducts gRPC với nhiều query variant.
    Dùng cho query tiếng Anh khớp trực tiếp tên sản phẩm.
    """

    _name = "direct_db"

    def __init__(self):
        self.catalog_addr = os.getenv("CATALOG_ADDR", "product-catalog:3550")
        self._was_used = False

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, sq: SearchQuery) -> bool:
        """Luôn chạy (fallback strategy)."""
        return True

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        """Gọi SearchProducts với variants, return scored list."""
        self._was_used = True
        pool = []

        # Build query variants
        variants = self._build_variants(sq)
        
        tasks = [self._search_variant(v, sq) for v in variants]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                pool.extend(result)

        return pool

    def _build_variants(self, sq: SearchQuery) -> List[str]:
        """Build nhiều query variant để tăng recall."""
        variants = [sq.raw]

        if sq.category:
            variants.append(sq.category)

        for kw in sq.keywords_en:
            if kw not in variants:
                variants.append(kw)

        return list(set(variants))

    async def _search_variant(self, query: str, sq: SearchQuery) -> List[ScoredProduct]:
        """Gọi gRPC SearchProducts với 1 query variant."""
        try:
            channel = grpc.aio.insecure_channel(self.catalog_addr)
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)

            request = demo_pb2.SearchProductsRequest(query=query)
            response = await stub.SearchProducts(request)

            scored = []
            for p in response.results:
                product = Product(
                    id=p.id,
                    name=p.name,
                    description=p.description or "",
                    categories=list(p.categories) if hasattr(p, 'categories') else [],
                    price_usd=p.price_usd or demo_pb2.Money()
                )
                base_score = self._base_score(product, sq, query)
                if base_score > 0:
                    scored.append(ScoredProduct(
                        product=product,
                        score=base_score,
                        strategy_name=self.name
                    ))

            await channel.close()
            return scored
        except Exception as e:
            print(f"DirectDBStrategy error for variant '{query}': {e}")
            return []

    def _base_score(self, p: Product, sq: SearchQuery, query_variant: str) -> float:
        """Base score từ direct DB match."""
        name_lower = p.name.lower()
        query_lower = query_variant.lower()

        if query_lower == name_lower:
            return 60
        elif query_lower in name_lower:
            return 50
        else:
            return 30  # Fallback score từ gRPC search


class SynonymExpansionStrategy(SearchStrategy):
    """
    Mở rộng query tiếng Việt sang tiếng Anh dùng synonym cache.
    Chỉ chạy khi query có từ khoá tiếng Việt.
    """

    _name = "synonym_expansion"

    def __init__(self):
        self.synonym_cache = SynonymCache()
        self.catalog_addr = os.getenv("CATALOG_ADDR", "product-catalog:3550")
        self._was_used = False

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, sq: SearchQuery) -> bool:
        """Chỉ chạy khi query có từ khoá tiếng Việt."""
        return len(sq.keywords_vn) > 0

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        """Expand VN keywords → EN, search từng EN keyword."""
        self._was_used = True
        en_keywords = self.synonym_cache.expand(sq.keywords_vn)

        if not en_keywords:
            return []

        pool = []
        tasks = [self._search_keyword(kw) for kw in en_keywords]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                pool.extend(result)

        return pool

    async def _search_keyword(self, keyword: str) -> List[ScoredProduct]:
        """Gọi gRPC với 1 EN keyword từ synonym expand."""
        try:
            channel = grpc.aio.insecure_channel(self.catalog_addr)
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)

            request = demo_pb2.SearchProductsRequest(query=keyword)
            response = await stub.SearchProducts(request)

            scored = []
            for p in response.results:
                product = Product(
                    id=p.id,
                    name=p.name,
                    description=p.description or "",
                    categories=list(p.categories) if hasattr(p, 'categories') else [],
                    price_usd=p.price_usd or demo_pb2.Money()
                )
                scored.append(ScoredProduct(
                    product=product,
                    score=35,  # Synonym match base score
                    strategy_name=self.name
                ))

            await channel.close()
            return scored
        except Exception as e:
            print(f"SynonymExpansionStrategy error for keyword '{keyword}': {e}")
            return []
