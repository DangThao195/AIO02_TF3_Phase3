"""
scripts/check_services_fast.py — Fast connectivity check with explicit socket timeouts
"""
import sys, os, json, socket, asyncio
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(override=True)

import src.tools.service_config as sc

def check_tcp_port(host_port_str: str) -> bool:
    try:
        # Clean http:// if present
        cleaned = host_port_str.replace("http://", "").replace("https://", "")
        host, port = cleaned.split(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        res = s.connect_ex((host, int(port)))
        s.close()
        return res == 0
    except Exception:
        return False

print("=" * 70)
print("FAST SERVICE DIAGNOSTIC CHECK (WITH TIMEOUTS)")
print("=" * 70)

services = {
    "DB_SQL": (os.getenv("DB_HOST", "localhost"), int(os.getenv("DB_PORT", "5432"))),
    "CATALOG": sc.CATALOG_ADDR,
    "CART": sc.CART_ADDR,
    "REVIEWS": sc.REVIEWS_ADDR,
    "RECOMMENDATION": sc.RECO_ADDR,
    "CURRENCY": sc.CURRENCY_ADDR,
    "SHIPPING": sc.SHIPPING_ADDR,
}

for name, addr in services.items():
    if isinstance(addr, tuple):
        addr_str = f"{addr[0]}:{addr[1]}"
    else:
        addr_str = addr
    
    is_open = check_tcp_port(addr_str)
    icon = "✅" if is_open else "❌"
    status = "OPEN / CONNECTED" if is_open else "CLOSED / UNREACHABLE"
    print(f"{icon} {name:20s} ({addr_str:25s}): {status}")

print("\n" + "=" * 70)

# Test DB Query directly if port is open
db_addr = f"{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}"
if check_tcp_port(db_addr):
    print("\n▸ Testing DB query execution...")
    try:
        from src.tools.search_product.flow1.sql_executor import SQLQueryExecutor
        e = SQLQueryExecutor()
        e.ensure_initialized()
        rows = e.execute("SELECT count(*) as total FROM catalog.products")
        print(f"  ✅ DB Query SUCCESS! Products in catalog: {rows[0]['total']}")
    except Exception as ex:
        print(f"  ❌ DB Query FAILED: {ex}")

# Test Reviews Tool if 9090 is open
reviews_addr = sc.REVIEWS_ADDR
if check_tcp_port(reviews_addr):
    print("\n▸ Testing Product Reviews gRPC call...")
    try:
        from src.tools.review_tool import get_product_reviews_tool
        res = asyncio.run(get_product_reviews_tool.ainvoke({"product_id": "66VCHSJNUP"}))
        print(f"  ✅ Reviews Tool SUCCESS: {res[:150]}")
    except Exception as ex:
        print(f"  ❌ Reviews Tool FAILED: {ex}")
