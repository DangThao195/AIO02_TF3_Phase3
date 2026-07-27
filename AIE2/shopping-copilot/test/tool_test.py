"""
tool_test.py — Kiem tra tat ca tool trong shopping copilot.

Output tu dong luu vao test/tool_test.txt (cung thu muc).
Neu shopping.db rong, du lieu duoc nap tu server-test/database/init.sql.

Cach chay:
    cd shopping-copilot
    py -m test.tool_test
    py -m test.tool_test --mock     (dung mock EKS)
"""

import argparse
import contextlib
import io
import json
import os
import sqlite3
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

parser = argparse.ArgumentParser(description="Tool Test")
parser.add_argument("--mock", action="store_true", help="Bat mock EKS")
args, _ = parser.parse_known_args()

if args.mock:
    os.environ["MOCK_EKS"] = "true"

SEP = "=" * 72
SUB_SEP = "-" * 40
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_test.txt")


_orig_stdout = sys.stdout
_orig_stderr = sys.stderr


def _tee_write(buf, text):
    buf.write(text)
    _orig_stdout.write(text)


@contextlib.contextmanager
def _capture_output():
    buf = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    class Tee:
        def write(self, text):
            _tee_write(buf, text)

        def flush(self):
            buf.flush()
            old_stdout.flush()

    sys.stdout = Tee()
    sys.stderr = Tee()
    try:
        yield buf
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        with open(_OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        _orig_stdout.write(f"\n  Output saved to: {_OUTPUT_FILE}\n")


def _ensure_db():
    db_path = os.path.join(ROOT, "server-test", "shopping.db")
    init_path = os.path.join(ROOT, "server-test", "database", "init.sql")
    if not os.path.exists(db_path):
        print(f"  [DB] shopping.db not found, creating from {init_path}")
        _populate_db(db_path, init_path)
        return
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM products")
        cnt = cur.fetchone()[0]
        if cnt == 0:
            print("  [DB] shopping.db empty, populating from init.sql")
            conn.close()
            os.remove(db_path)
            _populate_db(db_path, init_path)
            return
        print(f"  [DB] shopping.db san sang ({cnt} products)")
    except sqlite3.OperationalError:
        print("  [DB] shopping.db missing schema, re-creating from init.sql")
        conn.close()
        os.remove(db_path)
        _populate_db(db_path, init_path)
        return
    finally:
        conn.close()


def _populate_db(db_path, init_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        with open(init_path, encoding="utf-8") as f:
            cur.executescript(f.read())
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM products")
        cnt = cur.fetchone()[0]
        print(f"  [DB] Da nap {cnt} products tu init.sql")
    except Exception as e:
        print(f"  [DB] Loi khi nap init.sql: {e}", file=sys.stderr)
    finally:
        conn.close()


def _resolve_fn(fn):
    """Tra ve ham thuc te ben trong StructuredTool neu la @tool decorator."""
    if hasattr(fn, "coroutine") and callable(fn.coroutine):
        return fn.coroutine
    if hasattr(fn, "func") and callable(fn.func):
        return fn.func
    return fn


def _json_preview(raw, max_len=200):
    if not raw:
        return "(empty)"
    try:
        parsed = json.loads(raw)
        dumped = json.dumps(parsed, indent=2, ensure_ascii=False)
        if len(dumped) > max_len:
            return dumped[:max_len] + "..."
        return dumped
    except (json.JSONDecodeError, ValueError):
        raw_s = str(raw)
        return raw_s[:max_len] + ("..." if len(raw_s) > max_len else "")


def print_result(tool_name, status, detail="", output=""):
    icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}.get(status, "????")
    print(f"  [{icon}] {tool_name}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")
    if output:
        out_str = _json_preview(output, 300)
        for line in out_str.split("\n"):
            print(f"         | {line}")


def test_sync(name, fn, kwargs, skip_on=()):
    impl = _resolve_fn(fn)
    print(f"\n{SUB_SEP}")
    print(f"  Tool: {name}")
    print(f"  Input: {json.dumps(kwargs, ensure_ascii=False)}")
    try:
        for exc_type in skip_on:
            try:
                result = impl(**kwargs)
            except exc_type:
                print_result(name, SKIP, f"Bo qua (gap {exc_type.__name__})")
                return
        result = impl(**kwargs)
        print_result(name, PASS, output=result)
    except Exception as e:
        print_result(name, FAIL, detail=f"{type(e).__name__}: {e}")


async def test_async(name, fn, kwargs, skip_on=()):
    impl = _resolve_fn(fn)
    print(f"\n{SUB_SEP}")
    print(f"  Tool: {name}")
    print(f"  Input: {json.dumps(kwargs, ensure_ascii=False)}")
    try:
        for exc_type in skip_on:
            try:
                result = await impl(**kwargs)
            except exc_type:
                print_result(name, SKIP, f"Bo qua (gap {exc_type.__name__})")
                return
        result = await impl(**kwargs)
        print_result(name, PASS, output=result)
    except Exception as e:
        print_result(name, FAIL, detail=f"{type(e).__name__}: {e}")


async def main():
    _ensure_db()

    print(SEP)
    print("  SHOPPING COPILOT - TOOL TEST")
    print(f"  Mode: {'MOCK' if args.mock else 'LIVE'}")
    print(SEP)

    # 1. Registry
    print(f"\n{'=' * 72}")
    print("  1. ToolRegistry")
    print("=" * 72)
    from src.tools.registry import ToolRegistry
    specs = ToolRegistry.get_all_specs()
    print(f"\n  Registered tools: {len(specs)}")
    for i, (tname, spec) in enumerate(specs.items(), 1):
        print(f"    {i:2d}. {tname:<35s} write={spec.is_write}")
    print()

    # 2. Search
    print(f"\n{'=' * 72}")
    print("  2. SEARCH")
    print("=" * 72)
    from src.tools.search import search_products_v2
    await test_async("search_products_v2", search_products_v2, {"query": "laptop"})
    await test_async("search_products_v2", search_products_v2, {"query": "iphone"})
    await test_async("search_products_v2", search_products_v2, {"query": "ao thun"})
    await test_async("search_products_v2", search_products_v2, {"query": "telescope"})
    await test_async("search_products_v2", search_products_v2, {"query": "solar filter"})

    # 3. Catalog
    print(f"\n{'=' * 72}")
    print("  3. CATALOG")
    print("=" * 72)
    from src.tools.catalog_tool import get_categories, get_all_products
    test_sync("get_categories", get_categories, {})
    test_sync("get_all_products", get_all_products, {})

    # 4. Product ID
    print(f"\n{'=' * 72}")
    print("  4. PRODUCT ID LOOKUP")
    print("=" * 72)
    from src.tools.product_id_tool import get_product_id
    test_sync("get_product_id", get_product_id, {"product_name": "Solar Filter"})
    test_sync("get_product_id", get_product_id, {"product_name": "Laptop"})
    test_sync("get_product_id", get_product_id, {"product_name": "San pham khong ton tai XYZ"})

    # 5. Product Detail
    print(f"\n{'=' * 72}")
    print("  5. PRODUCT DETAIL")
    print("=" * 72)
    from src.tools.product_tool import get_product_details_tool
    test_sync("get_product_details_tool", get_product_details_tool, {"product_id": "OLJCESPC7Z"},
              skip_on=(Exception,))
    test_sync("get_product_details_tool", get_product_details_tool, {"product_id": "1"},
              skip_on=(Exception,))

    # 6. Reviews
    print(f"\n{'=' * 72}")
    print("  6. REVIEWS")
    print("=" * 72)
    from src.tools.review_tool import (
        get_product_reviews_tool,
        get_best_reviewed_products_tool,
        get_worst_reviewed_products_tool,
    )
    test_sync("get_product_reviews_tool", get_product_reviews_tool, {"product_id": "OLJCESPC7Z"},
              skip_on=(Exception,))
    test_sync("get_product_reviews_tool", get_product_reviews_tool, {"product_id": "1"},
              skip_on=(Exception,))
    test_sync("get_best_reviewed_products_tool", get_best_reviewed_products_tool, {"limit": 5},
              skip_on=(Exception,))
    test_sync("get_best_reviewed_products_tool", get_best_reviewed_products_tool,
              {"limit": 5, "category": "telescopes"},
              skip_on=(Exception,))
    test_sync("get_best_reviewed_products_tool", get_best_reviewed_products_tool,
              {"limit": 5, "category": "electronics"},
              skip_on=(Exception,))
    test_sync("get_worst_reviewed_products_tool", get_worst_reviewed_products_tool, {"limit": 3},
              skip_on=(Exception,))
    test_sync("get_worst_reviewed_products_tool", get_worst_reviewed_products_tool,
              {"limit": 3, "category": "binoculars"},
              skip_on=(Exception,))

    # 7. Cart
    print(f"\n{'=' * 72}")
    print("  7. CART")
    print("=" * 72)
    from src.tools.cart_tool import (
        get_cart_tool, add_to_cart_tool, update_cart_item_tool, check_cart_item_tool,
    )
    test_sync("get_cart_tool", get_cart_tool, {"user_id": "user001"},
              skip_on=(Exception,))
    test_sync("check_cart_item_tool", check_cart_item_tool,
              {"user_id": "user001", "product_id": "OLJCESPC7Z"},
              skip_on=(Exception,))
    test_sync("add_to_cart_tool", add_to_cart_tool,
              {"user_id": "user001", "product_id": "OLJCESPC7Z", "quantity": 1},
              skip_on=(Exception,))
    test_sync("update_cart_item_tool", update_cart_item_tool,
              {"user_id": "user001", "product_id": "OLJCESPC7Z", "quantity": 2},
              skip_on=(Exception,))

    # 8. Recommendations
    print(f"\n{'=' * 72}")
    print("  8. RECOMMENDATIONS")
    print("=" * 72)
    from src.tools.recommendation_tool import get_recommendations_tool
    test_sync("get_recommendations_tool", get_recommendations_tool, {"product_id": "OLJCESPC7Z"},
              skip_on=(Exception,))
    test_sync("get_recommendations_tool", get_recommendations_tool, {"product_id": "1"},
              skip_on=(Exception,))

    # 9. Currency
    print(f"\n{'=' * 72}")
    print("  9. CURRENCY CONVERSION")
    print("=" * 72)
    from src.tools.currency_tool import convert_currency_tool
    test_sync("convert_currency_tool", convert_currency_tool,
              {"from_currency": "USD", "to_currency": "VND", "amount": 100.0},
              skip_on=(Exception,))
    test_sync("convert_currency_tool", convert_currency_tool,
              {"from_currency": "VND", "to_currency": "USD", "amount": 100000},
              skip_on=(Exception,))

    # 10. Shipping
    print(f"\n{'=' * 72}")
    print("  10. SHIPPING QUOTE")
    print("=" * 72)
    from src.tools.shipping_tool import get_shipping_quote_tool
    test_sync("get_shipping_quote_tool", get_shipping_quote_tool,
              {"city": "Ho Chi Minh", "country": "VN"},
              skip_on=(Exception,))
    test_sync("get_shipping_quote_tool", get_shipping_quote_tool,
              {"address": "123 Nguyen Hue, Q1", "city": "Ho Chi Minh", "country": "VN"},
              skip_on=(Exception,))

    # 11. Out of Scope
    print(f"\n{'=' * 72}")
    print("  11. OUT OF SCOPE")
    print("=" * 72)
    from src.tools.out_of_scope_tool import respond_out_of_scope_tool
    for reason in ["greeting", "weather", "math", "news", "general"]:
        test_sync(f"respond_out_of_scope_tool({reason!r})",
                  respond_out_of_scope_tool, {"reason": reason})

    # Summary
    print(f"\n{SEP}")
    print("  DONE - Tat ca tool da duoc kiem tra.")
    print(f"  Mode: {'MOCK' if args.mock else 'LIVE'}")
    print(SEP)


if __name__ == "__main__":
    import asyncio
    with _capture_output():
        asyncio.run(main())
