from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json


@dataclass
class Money:
    units: int = 0
    nanos: int = 0

    def to_float(self) -> float:
        return self.units + self.nanos / 1e9


@dataclass
class Product:
    id: str
    name: str
    description: str = ""
    categories: List[str] = field(default_factory=list)
    price_usd: Money = field(default_factory=Money)


@dataclass
class ScoredProduct:
    product: Product
    score: float = 0.0
    source: str = "sql"
    strategy_name: str = ""


@dataclass
class SearchQuery:
    raw: str
    rewritten: Optional[str] = None
    extracted_entities: Dict = field(default_factory=dict)
    generated_sql: Optional[str] = None
    sql_params: List = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    products: List[ScoredProduct] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    rerank_mode: str = "combined"
    flows_used: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "rerank_mode": self.rerank_mode,
            "flows_used": self.flows_used,
            "categories": self.categories,
            "products": [
                {
                    "id": p.product.id,
                    "name": p.product.name,
                    "price_usd": p.product.price_usd.to_float(),
                    "score": p.score,
                    "source": p.source,
                    "strategy": p.strategy_name,
                }
                for p in self.products
            ],
            "error": self.error,
        }


@dataclass
class SearchToolResponse:
    status: str
    total: int
    products: List[dict] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        d = {"status": self.status, "total": self.total}
        if self.categories:
            d["categories"] = self.categories
        else:
            d["products"] = self.products
        return json.dumps(d, ensure_ascii=False)


class SearchStrategy:
    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        raise NotImplementedError
