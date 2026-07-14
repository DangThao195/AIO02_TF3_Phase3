# tools/search/strategies.py
"""
Search strategies chạy song song.
Strategy A: Full Catalog (in-memory)
Strategy B: Direct DB (gRPC)
Strategy C: Synonym Expansion (VN→EN translate)
"""

import asyncio
import os
import re
from abc import ABC, abstractmethod
from typing import List, Optional
import boto3
from rapidfuzz import fuzz
import grpc

from src.tools.search.models import Product, SearchQuery, ScoredProduct
from src.tools.search.synonym_cache import SynonymCache
from src.tools.service_config import CATALOG_ADDR
from src.memory.cache import CacheStore
import src.protos.demo_pb2 as demo_pb2
import src.protos.demo_pb2_grpc as demo_pb2_grpc


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
            channel = grpc.aio.insecure_channel(CATALOG_ADDR)
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
        """Gọi gRPC SearchProducts với 1 query variant.

        Nếu gRPC không khả dụng (ví dụ đang chạy server-test local), thử gọi trực tiếp
        vào module `server.db` (nếu import được) để tận dụng các hàm db_* mới.
        """
        # First attempt: try gRPC
        try:
            channel = grpc.aio.insecure_channel(CATALOG_ADDR)
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
        except Exception:
            # gRPC failed — try local DB functions if available (server-test)
            try:
                import server.db as local_db  # type: ignore

                rows = await local_db.db_execute_text_search(query, limit=50)
                scored = []
                for r in rows:
                    product = Product(
                        id=r["id"],
                        name=r["name"],
                        description=r["description"] or "",
                        categories=(r["categories"].split(",") if r["categories"] else []),
                        price_usd=demo_pb2.Money(units=r["price_units"] if r["price_units"] is not None else 0)
                    )
                    base_score = self._base_score(product, sq, query)
                    if base_score > 0:
                        scored.append(ScoredProduct(product=product, score=base_score, strategy_name=self.name))
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
            channel = grpc.aio.insecure_channel(CATALOG_ADDR)
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


class BedrockRAGStrategy(SearchStrategy):
    """
    Query AWS Bedrock Knowledge Base to perform semantic vector search on products.
    Requires BEDROCK_KB_ID to be set in environment variables.
    """

    _name = "bedrock_rag"

    def __init__(self):
        pass

    @property
    def kb_id(self) -> Optional[str]:
        return os.environ.get("BEDROCK_KB_ID")

    @property
    def region(self) -> str:
        return os.environ.get("BEDROCK_KB_REGION", "us-east-1")

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, sq: SearchQuery) -> bool:
        """Only run if BEDROCK_KB_ID is configured in the environment."""
        return bool(self.kb_id)

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        kb_id = self.kb_id
        if not kb_id:
            return []

        print(f"\n[RAG] 🔍 Kích hoạt Bedrock RAG tìm kiếm ngữ nghĩa cho: '{sq.raw}' (Region: {self.region}, KB_ID: {kb_id})")
        try:
            # Run blocking boto3 client calls in asyncio executor to prevent event loop blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, self._query_kb, sq.raw)
            print(f"[RAG] ✅ Tìm thấy {len(results)} sản phẩm phù hợp từ Vector KB.")
            return results
        except Exception as e:
            print(f"❌ [RAG] Lỗi BedrockRAGStrategy: {e}")
            return []

    def _query_kb(self, query_text: str) -> List[ScoredProduct]:
        kb_id = self.kb_id
        region = self.region
        
        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
        client = session.client("bedrock-agent-runtime", region_name=region)
        
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={
                'text': query_text
            },
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': 5
                }
            }
        )
        
        scored_products = []
        retrieved_results = response.get("retrievalResults", [])
        
        id_pattern = re.compile(r"Product\s+ID:\s*([A-Z0-9]{10})", re.IGNORECASE)
        
        for res in retrieved_results:
            text = res.get("content", {}).get("text", "")
            score = res.get("score", 0.8) # default score
            
            match = id_pattern.search(text)
            if match:
                product_id = match.group(1)
                
                # Fetch actual live details from SQLite db if available to ensure 100% accuracy
                product = self._resolve_product_details(product_id, text)
                scored_products.append(ScoredProduct(
                    product=product,
                    score=score * 100,  # Scale score to 0-100
                    strategy_name=self.name
                ))
                
        return scored_products

    def _resolve_product_details(self, product_id: str, chunk_text: str) -> Product:
        # Default fallback parsing the chunk text
        name_match = re.search(r"Product\s+Name:\s*(.*)", chunk_text, re.IGNORECASE)
        price_match = re.search(r"Price:\s*(\d+)", chunk_text, re.IGNORECASE)
        cat_match = re.search(r"Category:\s*(.*)", chunk_text, re.IGNORECASE)
        
        name = name_match.group(1).strip() if name_match else f"Product {product_id}"
        price = int(price_match.group(1).strip()) if price_match else 0
        categories = [c.strip() for c in cat_match.group(1).split(",") if c.strip()] if cat_match else []
        
        db_path = os.path.join("server-test", "shopping.db")
        if os.path.exists(db_path):
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name, description, categories, price_units FROM products WHERE id = ?", (product_id,))
                row = cursor.fetchone()
                if row:
                    cats = [c.strip() for c in row[2].split(",") if c.strip()] if row[2] else []
                    return Product(
                        id=product_id,
                        name=row[0],
                        description=row[1] or "",
                        categories=cats,
                        price_usd=demo_pb2.Money(units=row[3] if row[3] is not None else 0)
                    )
            except Exception:
                pass
            finally:
                conn.close()
                
        return Product(
            id=product_id,
            name=name,
            description=chunk_text[:200],
            categories=categories,
            price_usd=demo_pb2.Money(units=price)
        )
