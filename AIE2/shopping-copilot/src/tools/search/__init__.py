"""
tools/search/__init__.py — search_products_v2 LangChain tool + ToolRegistry registration
"""

import json

from langchain_core.tools import tool

from src.tools.search.models import SearchToolResponse
from src.tools.search.query_analyzer import QueryAnalyzerPipeline
from src.tools.search.orchestrator import SearchOrchestrator
from src.tools.search.synonym_cache import SynonymCache
from src.tools.search.tracer import SearchTracer


@tool
async def search_products_v2(query: str) -> str:
    """
    Tìm kiếm sản phẩm thông minh (tiếng Việt và tiếng Anh).
    Có thể tìm theo tên, danh mục, khoảng giá (VD: "dưới 50 đô", "từ 100-200 USD").
    Dùng SQL matching + RAG để có kết quả chính xác nhất.
    Trả về JSON: {"status","total","confidence","products":[{id,name,price,description,image,categories}]}
    """
    tracer = SearchTracer()
    orch = SearchOrchestrator()
    result = await orch.search(query, tracer=tracer)

    if result.categories:
        response = SearchToolResponse(
            status="category",
            total=len(result.categories),
            categories=list(result.categories),
            confidence=0.9,
        )
    elif not result.products:
        response = SearchToolResponse(
            status="success",
            total=0,
            products=[],
            confidence=0.0,
        )
    else:
        products_json = []
        for sp in result.products[:5]:
            p = sp.product
            units = getattr(p.price_usd, "units", 0)
            nanos = getattr(p.price_usd, "nanos", 0)
            cents = nanos // 10_000_000
            cats = p.categories
            if isinstance(cats, str):
                cats = [c.strip() for c in cats.split(",") if c.strip()]
            products_json.append({
                "id": p.id,
                "name": p.name,
                "price": f"${units}.{cents:02d}" if (units or cents) else "$0.00",
                "description": p.description,
                "image": getattr(p, "picture", "") or "",
                "categories": cats,
            })
        response = SearchToolResponse(
            status="success",
            total=len(products_json),
            products=products_json,
            confidence=getattr(result, "confidence", 0.8),
        )

    return response.to_json()


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="search_products_v2",
    description=(
        "Tìm kiếm sản phẩm thông minh (tiếng Việt và tiếng Anh). "
        "Có thể tìm theo tên, danh mục, khoảng giá (VD: 'dưới 50 đô', 'từ 100-200 USD'). "
        "Dùng SQL matching + RAG semantic search."
    ),
    is_write=False,
    input_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "Câu tìm kiếm bằng tiếng Việt hoặc tiếng Anh"},
    }, "required": ["query"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string", "enum": ["success", "category", "error"]},
        "total": {"type": "integer"},
        "confidence": {"type": "number"},
        "products": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"},
            "price": {"type": "string"}, "description": {"type": "string"},
            "image": {"type": "string"}, "categories": {"type": "array"},
        }}},
        "categories": {"type": "array", "items": {"type": "string"}},
    }},
    examples=[
        {"input": {"query": "kính thiên văn dưới 100 đô"},
         "output": {"status": "success", "total": 2, "confidence": 0.9}},
    ],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=search_products_v2)


__all__ = ["search_products_v2", "QueryAnalyzerPipeline", "SynonymCache"]
