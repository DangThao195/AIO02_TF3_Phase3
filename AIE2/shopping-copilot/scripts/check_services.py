"""
scripts/check_services.py — Comprehensive check for all services and tools
"""
import sys, os, json, asyncio
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(override=True)

print("=" * 70)
print("CHECKING ALL BACKEND SERVICES & TOOLS CONNECTIVITY")
print("=" * 70)

# Print current config
import src.tools.service_config as sc
print(f"USE_TEST_SERVER : {sc.USE_TEST_SERVER}")
print(f"CATALOG_ADDR    : {sc.CATALOG_ADDR}")
print(f"CART_ADDR       : {sc.CART_ADDR}")
print(f"REVIEWS_ADDR    : {sc.REVIEWS_ADDR}")
print(f"RECO_ADDR       : {sc.RECO_ADDR}")
print(f"CURRENCY_ADDR   : {sc.CURRENCY_ADDR}")
print(f"SHIPPING_ADDR   : {sc.SHIPPING_ADDR}")
print(f"DB_HOST:PORT    : {os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}")

results = {}

# ── 1. Database Check ────────────────────────────────────────────────────────
print("\n[1/6] Testing PostgreSQL Database Connection...")
try:
    from src.tools.search_product.flow1.sql_executor import SQLQueryExecutor
    executor = SQLQueryExecutor()
    executor.ensure_initialized()
    rows = executor.execute("SELECT count(*) as cnt FROM catalog.products")
    cnt = rows[0]["cnt"] if rows else 0
    results["DB_SQL"] = f"OK — {cnt} products in DB"
    print(f"  ✅ DB SQL: SUCCESS ({cnt} products)")
except Exception as e:
    results["DB_SQL"] = f"FAIL — {e}"
    print(f"  ❌ DB SQL: FAILED ({e})")

# ── 2. Product Reviews gRPC Service Check ────────────────────────────────────
print("\n[2/6] Testing Product Reviews Service (REVIEWS_ADDR)...")
try:
    from src.tools.review_tool import get_product_reviews_tool
    rev_res = asyncio.run(get_product_reviews_tool.ainvoke({"product_id": "66VCHSJNUP"}))
    rev_data = json.loads(rev_res)
    st = rev_data.get("status")
    src = rev_data.get("source", "unknown")
    total_rev = rev_data.get("total_reviews", 0)
    results["REVIEWS_SERVICE"] = f"OK (status={st}, source={src}, total={total_rev})"
    print(f"  ✅ Reviews Service: SUCCESS (status={st}, source={src}, reviews={total_rev})")
except Exception as e:
    results["REVIEWS_SERVICE"] = f"FAIL — {e}"
    print(f"  ❌ Reviews Service: FAILED ({e})")

# ── 3. Cart gRPC Service Check ──────────────────────────────────────────────
print("\n[3/6] Testing Cart Service (CART_ADDR)...")
try:
    from src.tools.cart_tool import get_cart_tool
    cart_res = asyncio.run(get_cart_tool.ainvoke({"user_id": "test_user"}))
    cart_data = json.loads(cart_res)
    st = cart_data.get("status")
    results["CART_SERVICE"] = f"OK (status={st})"
    print(f"  ✅ Cart Service: SUCCESS (status={st})")
except Exception as e:
    results["CART_SERVICE"] = f"FAIL — {e}"
    print(f"  ❌ Cart Service: FAILED ({e})")

# ── 4. Currency gRPC Service Check ──────────────────────────────────────────
print("\n[4/6] Testing Currency Service (CURRENCY_ADDR)...")
try:
    from src.tools.currency_tool import convert_currency_tool
    cur_res = asyncio.run(convert_currency_tool.ainvoke({"from_currency": "USD", "to_currency": "VND", "amount_units": 100}))
    cur_data = json.loads(cur_res)
    st = cur_data.get("status")
    results["CURRENCY_SERVICE"] = f"OK (status={st}, result={cur_res[:100]})"
    print(f"  ✅ Currency Service: SUCCESS (status={st})")
except Exception as e:
    results["CURRENCY_SERVICE"] = f"FAIL — {e}"
    print(f"  ❌ Currency Service: FAILED ({e})")

# ── 5. Catalog Search Tool Check ─────────────────────────────────────────────
print("\n[5/6] Testing Catalog Search Tool (search_products_v2)...")
try:
    from src.tools import search_products_v2
    srch_res = asyncio.run(search_products_v2.ainvoke({"query": "telescope"}))
    srch_data = json.loads(srch_res)
    st = srch_data.get("status")
    total_prods = srch_data.get("total", 0)
    results["SEARCH_TOOL"] = f"OK (status={st}, total={total_prods})"
    print(f"  ✅ Search Tool: SUCCESS (status={st}, found {total_prods} products)")
except Exception as e:
    results["SEARCH_TOOL"] = f"FAIL — {e}"
    print(f"  ❌ Search Tool: FAILED ({e})")

# ── 6. Best Reviewed Products Tool Check ────────────────────────────────────
print("\n[6/6] Testing Best Reviewed Products Tool...")
try:
    from src.tools.review_tool import get_best_reviewed_products_tool
    best_res = asyncio.run(get_best_reviewed_products_tool.ainvoke({"limit": 5}))
    best_data = json.loads(best_res)
    st = best_data.get("status")
    total_best = best_data.get("total", 0)
    results["BEST_REVIEWED_TOOL"] = f"OK (status={st}, total={total_best})"
    print(f"  ✅ Best Reviewed Tool: SUCCESS (status={st}, total={total_best})")
except Exception as e:
    results["BEST_REVIEWED_TOOL"] = f"FAIL — {e}"
    print(f"  ❌ Best Reviewed Tool: FAILED ({e})")

print("\n" + "=" * 70)
print("FINAL SUMMARY REPORT")
print("=" * 70)
for k, v in results.items():
    icon = "✅" if "OK" in v else "❌"
    print(f"{icon} {k:25s}: {v}")
