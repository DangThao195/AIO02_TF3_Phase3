import json
import logging
import unicodedata

from langchain_core.tools import tool

from src.tools.search_product.models import SearchToolResponse
from src.tools.search_product.orchestrator import SearchOrchestrator
from src.tools.search_product.tracer import SearchTracer

logger = logging.getLogger(__name__)

# Vietnamese → English phrase map for search query normalization.
# Applied BEFORE sending query to SearchOrchestrator to avoid Unicode
# tokenization issues (diacritic stripping in entity_extractor).
_VI_EN_SEARCH_MAP = [
    ("kính thiên văn", "telescope"),
    ("kinh thien van", "telescope"),
    ("kính viễn vọng", "telescope"),
    ("ống nhòm", "binoculars"),
    ("ong nhom", "binoculars"),
    ("kính khúc xạ", "refractor telescope"),
    ("kính phản xạ", "reflector telescope"),
    ("đèn pin", "flashlight"),
    ("den pin", "flashlight"),
    ("bộ vệ sinh", "cleaning kit"),
    ("bo ve sinh", "cleaning kit"),
    ("phụ kiện thiên văn", "astronomy accessory"),
    ("phu kien thien van", "astronomy accessory"),
    ("phụ kiện", "accessory"),
    ("phu kien", "accessory"),
    ("sách", "book"),
    ("sach", "book"),
]


def _translate_vi_query(query: str) -> str:
    """Normalize and translate Vietnamese search phrases to English.
    Uses NFC normalization to handle both composed (NFC) and decomposed (NFD)
    Unicode representations that may differ between LLM output and source literals.
    """
    q = unicodedata.normalize("NFC", query or "")
    for vi_phrase, en_phrase in _VI_EN_SEARCH_MAP:
        vi_norm = unicodedata.normalize("NFC", vi_phrase)
        if vi_norm in q:
            q = q.replace(vi_norm, en_phrase)
    return q


@tool
async def search_products_v2(query: str) -> str:
    """
    Tìm kiếm sản phẩm thông minh (tiếng Việt và tiếng Anh).
    Có thể tìm theo tên, danh mục, khoảng giá (VD: "dưới 50 đô", "từ 100-200 USD").
    Dùng SQL matching + Product RAG (truy vấn riêng Product Datasource) để có kết quả chính xác nhất.
    Trả về JSON: {"status","total","products":[{id,name,price,description,categories}]}
    """
    # Translate Vietnamese phrases to English before search to ensure
    # SQL LIKE clauses match the English-language product catalog.
    translated = _translate_vi_query(query)
    if translated != query:
        logger.info(f"[SEARCH_V2] VI→EN: '{query}' -> '{translated}'")
        query = translated

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


__all__ = ["search_products_v2", "SearchOrchestrator", "SearchTracer"]
