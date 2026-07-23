import json
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Money:
    units: int = 0
    nanos: int = 0
    currency_code: str = "USD"


@dataclass
class Product:
    id: str
    name: str
    description: str
    categories: List[str]
    price_usd: Any = None


@dataclass
class SearchEntity:
    select_fields: List[str] = field(default_factory=lambda: ["*"])
    from_table: str = "products"
    where_conditions: dict = field(default_factory=dict)
    order_by: Optional[str] = None
    limit: int = 15


@dataclass
class ScoredProduct:
    product: Product
    score: float = 0.0
    source: str = ""
    strategy_name: str = ""


@dataclass
class SearchResult:
    products: List[ScoredProduct] = field(default_factory=list)
    query: str = ""
    flows_used: List[str] = field(default_factory=list)
    rerank_mode: str = "rule"
    error: Optional[str] = None
    categories: Optional[List[str]] = None

    @property
    def total(self) -> int:
        return len(self.products) if not self.categories else len(self.categories)


@dataclass
class SearchToolResponse:
    status: str  # "success" | "category" | "error"
    total: int = 0
    products: List[dict] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    message: str = ""
    confidence: float = 0.0

    def to_json(self) -> str:
        payload: dict = {"status": self.status, "total": self.total, "confidence": self.confidence}
        if self.products:
            payload["products"] = self.products
        if self.categories:
            payload["categories"] = self.categories
        if self.message:
            payload["message"] = self.message
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class SearchQuery:
    raw: str
    category: Optional[str] = None
    keywords_en: List[str] = field(default_factory=list)
    keywords_vn: List[str] = field(default_factory=list)
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    sort: str = "relevance"
    intent: str = "search"
    is_complex: bool = False
    sql: Optional[str] = None


class SearchStrategy:
    name: str = "base"

    def should_run(self, sq: SearchQuery) -> bool:
        raise NotImplementedError

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        raise NotImplementedError
