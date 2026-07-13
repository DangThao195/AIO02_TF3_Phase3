# tools/search/models.py
"""
Cấu trúc dữ liệu trung tâm cho multi-strategy search.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional
import json


@dataclass
class Money:
    """Tiền tệ (mirror từ proto Money)."""
    units: int = 0
    nanos: int = 0
    currency_code: str = "USD"


@dataclass
class Product:
    """Sản phẩm trong catalog."""
    id: str
    name: str
    description: str = ""
    categories: list[str] = field(default_factory=list)
    price_usd: Money = field(default_factory=Money)

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        """Deserialize từ dict (khi load từ cache)."""
        price_data = data.get("price_usd", {})
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            categories=data.get("categories", []),
            price_usd=Money(
                units=price_data.get("units", 0),
                nanos=price_data.get("nanos", 0),
                currency_code=price_data.get("currency_code", "USD"),
            )
        )

    def to_dict(self) -> dict:
        """Serialize thành dict (khi lưu vào cache)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "categories": self.categories,
            "price_usd": {
                "units": self.price_usd.units,
                "nanos": self.price_usd.nanos,
                "currency_code": self.price_usd.currency_code,
            }
        }


@dataclass
class SearchQuery:
    """Cấu trúc query đã được parse, dùng cho mọi strategy."""
    raw: str                                    # Query gốc từ user
    keywords_en: list[str] = field(default_factory=list)  # Từ khoá tiếng Anh đã extract
    keywords_vn: list[str] = field(default_factory=list)  # Từ khoá tiếng Việt gốc
    price_min: Optional[int] = None             # Lọc giá tối thiểu (USD)
    price_max: Optional[int] = None             # Lọc giá tối đa (USD)
    category: Optional[str] = None              # Category slug (telescopes, ...)
    intent: Literal["search", "browse", "compare", "unknown"] = "search"
    sort: Literal["relevance", "price_asc", "price_desc"] = "relevance"
    is_complex: bool = False                    # Có multi-intent? → trigger LLM rerank

    @property
    def has_price_filter(self) -> bool:
        return self.price_min is not None or self.price_max is not None

    @property
    def has_category(self) -> bool:
        return self.category is not None


@dataclass
class ScoredProduct:
    """Sản phẩm kèm score từ strategy."""
    product: Product
    score: float
    strategy_name: str = ""

    def __lt__(self, other: "ScoredProduct") -> bool:
        """Dùng cho sort descending theo score."""
        return self.score > other.score


@dataclass
class SearchResult:
    """Kết quả trả về từ search orchestrator."""
    query: SearchQuery
    products: list[ScoredProduct] = field(default_factory=list)
    total: int = 0
    strategies_used: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def empty(cls, message: str) -> "SearchResult":
        """Tạo empty result khi không tìm được sản phẩm."""
        return cls(
            query=SearchQuery(raw=""),
            products=[],
            total=0,
            strategies_used=[],
            error=message
        )

    def to_dict(self) -> dict:
        """Serialize để lưu cache."""
        return {
            "query": {
                "raw": self.query.raw,
                "keywords_en": self.query.keywords_en,
                "keywords_vn": self.query.keywords_vn,
                "price_min": self.query.price_min,
                "price_max": self.query.price_max,
                "category": self.query.category,
                "intent": self.query.intent,
                "sort": self.query.sort,
                "is_complex": self.query.is_complex,
            },
            "products": [
                {
                    "product": p.product.to_dict(),
                    "score": p.score,
                    "strategy_name": p.strategy_name,
                }
                for p in self.products
            ],
            "total": self.total,
            "strategies_used": self.strategies_used,
            "error": self.error,
        }
