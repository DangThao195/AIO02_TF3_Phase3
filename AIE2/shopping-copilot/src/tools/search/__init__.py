import json

from langchain_core.tools import tool

from src.tools.search.models import SearchToolResponse
from src.tools.search.orchestrator import SearchOrchestrator
from src.tools.search.tracer import SearchTracer


@tool
async def search_products_v2(query: str) -> str:
    """
    Tìm kiếm sản phẩm thông minh (tiếng Việt và tiếng Anh).
    Có thể tìm theo tên, danh mục, khoảng giá (VD: "dưới 50 đô", "từ 100-200 USD").
    Dùng SQL matching + RAG để có kết quả chính xác nhất.
    Trả về JSON: {"status","total","products":[{id,name,price,description,categories}]}
    """
    tracer = SearchTracer()
    orch = SearchOrchestrator()
    result = await orch.search(query, tracer=tracer)

    if result.categories:
        response = SearchToolResponse(
            status="category",
            total=len(result.categories),
            categories=list(result.categories),
        )
    elif not result.products:
        response = SearchToolResponse(
            status="success",
            total=0,
            products=[],
        )
    else:
        products_json = []
        for sp in result.products[:5]:
            p = sp.product
            units = getattr(p.price_usd, "units", 0)
            nanos = getattr(p.price_usd, "nanos", 0)
            products_json.append({
                "id": p.id,
                "name": p.name,
                "price": units + nanos / 1e9,
                "price_units": units,
                "price_nanos": nanos,
                "currency": "USD",
                "description": p.description,
                "categories": p.categories,
            })
        response = SearchToolResponse(
            status="success",
            total=len(products_json),
            products=products_json,
        )

    return response.to_json()


__all__ = ["search_products_v2"]
