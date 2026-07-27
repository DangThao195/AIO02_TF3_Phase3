"""
tools/product_tool.py — get_product_details_tool

Backend: ProductCatalogService gRPC (demo.proto)
"""

import json
import logging
from functools import wraps

import grpc
from langchain_core.tools import tool

from src.protos import demo_pb2, demo_pb2_grpc
from src.tools.service_config import CATALOG_ADDR

logger = logging.getLogger("tools.product")


def _grpc_retry(max_retries=3, backoff=1.5):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except grpc.RpcError as e:
                    last_err = e
                    if e.code() == grpc.StatusCode.UNAVAILABLE:
                        import time as _time
                        _time.sleep(backoff * (attempt + 1))
                    else:
                        break
            return {"_grpc_error": True, "_error_detail": str(last_err)}
        return wrapper
    return decorator


def _normalize_price(units: int, nanos: int) -> str:
    cents = nanos // 10_000_000
    return f"${units}.{cents:02d}"


def _get_product_via_db(product_id: str) -> dict | None:
    """Query local SQLite database for product details as fallback."""
    import sqlite3 as _sqlite3
    from pathlib import Path as _Path

    try:
        candidates = []
        fp = _Path(__file__).resolve()
        for base in [fp.parents[4], fp.parents[3], fp.parents[2], fp.parents[1], _Path.cwd()]:
            candidates.append(base / "server-test" / "shopping.db")
            candidates.append(base / "shopping.db")
        db_path = None
        for c in candidates:
            if c.exists():
                db_path = c
                break
        if not db_path:
            return None
        conn = _sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name, description, picture, price_units, price_nanos, categories FROM products WHERE id = ?",
                (product_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            cats = [c.strip() for c in row[5].split(",") if c.strip()] if row[5] else []
            return {
                "status": "success",
                "product": {
                    "id": product_id,
                    "name": row[0],
                    "price": _normalize_price(row[3] or 0, row[4] or 0),
                    "description": row[1] or "",
                    "image": row[2] or "",
                    "categories": cats,
                    "rating": 0,
                    "review_count": 0,
                },
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("DB product fallback failed: %s", e)
        return None


@tool
def get_product_details_tool(product_id: str) -> str:
    """
    Lấy chi tiết đầy đủ của một sản phẩm theo product_id (tên, giá, mô tả, hình ảnh, danh mục).
    Trả về JSON: {status, product{id,name,price,description,image,categories,rating,review_count}}
    """
    @_grpc_retry(max_retries=3, backoff=1.5)
    def _do_get_product(pid: str):
        with grpc.insecure_channel(CATALOG_ADDR) as ch:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(ch)
            return stub.GetProduct(demo_pb2.GetProductRequest(id=pid))

    try:
        p = _do_get_product(product_id)
        if p is None or (isinstance(p, dict) and p.get("_grpc_error")):
            db_result = _get_product_via_db(product_id)
            if db_result:
                return json.dumps(db_result, ensure_ascii=False)
            return json.dumps({
                "status": "error",
                "message": "Dịch vụ sản phẩm tạm thời không khả dụng. Vui lòng thử lại sau.",
            })

        cats = p.categories
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(",") if c.strip()]
        elif not isinstance(cats, list):
            cats = list(cats)

        rating = 0
        review_count = 0
        try:
            from src.tools.review_tool import get_product_reviews_tool
            raw = get_product_reviews_tool(product_id)
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict) and data.get("status") == "success":
                rating = data.get("average_score", 0)
                review_count = data.get("total_reviews", 0)
        except Exception:
            pass

        return json.dumps({
            "status": "success",
            "product": {
                "id": p.id,
                "name": p.name,
                "price": _normalize_price(p.price_usd.units, p.price_usd.nanos),
                "description": p.description,
                "image": getattr(p, "picture", "") or "",
                "categories": cats,
                "rating": rating,
                "review_count": review_count,
            },
        }, ensure_ascii=False)

    except grpc.RpcError as e:
        code = e.code().name if hasattr(e, "code") else "UNKNOWN"
        if code == "NOT_FOUND":
            return json.dumps({"status": "error", "message": f"Không tìm thấy sản phẩm '{product_id}'."})
        logger.error("[get_product_details_tool] gRPC %s | product=%s | %s", code, product_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": "Dịch vụ không khả dụng, vui lòng thử lại sau."})
    except Exception as e:
        logger.error("[get_product_details_tool] error | product=%s | %s", product_id, e, exc_info=True)
        return json.dumps({"status": "error", "message": str(e)})


# ── ToolSpec registration ─────────────────────────────────────────

from src.tools.registry import ToolRegistry, ToolSpec

ToolRegistry.register(ToolSpec(
    name="get_product_details_tool",
    description="Lấy chi tiết đầy đủ của một sản phẩm theo product_id (tên, giá, mô tả, hình ảnh, danh mục, đánh giá).",
    is_write=False,
    input_schema={"type": "object", "properties": {
        "product_id": {"type": "string", "description": "ID sản phẩm"}
    }, "required": ["product_id"]},
    output_schema={"type": "object", "properties": {
        "status": {"type": "string"},
        "product": {"type": "object", "properties": {
            "id": {"type": "string"}, "name": {"type": "string"},
            "price": {"type": "string"}, "description": {"type": "string"},
            "image": {"type": "string"}, "categories": {"type": "array"},
            "rating": {"type": "number"}, "review_count": {"type": "integer"},
        }},
        "message": {"type": "string"},
    }},
    examples=[{"input": {"product_id": "OLJCESPC7Z"},
               "output": {"status": "success", "product": {"name": "Vintage Typewriter", "price": "$65.50"}}}],
    retry_config={"max_retries": 2, "backoff": [0.5, 1.0]},
), fn=get_product_details_tool)
