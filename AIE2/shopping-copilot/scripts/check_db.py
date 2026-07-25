"""
scripts/check_db.py - Test kết nối DB và tìm kiếm kính thiên văn
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.database.connect import get_conn, execute_query

print("=== KIỂM TRA KẾT NỐI DB ===")
try:
    with get_conn() as conn:
        # 1. Kiểm tra bảng products
        rows = execute_query(conn, """
            SELECT id, name, 
                   price_units + price_nanos / 1e9 AS price
            FROM catalog.products
        """)
        print(f"[OK] DB OK. Tổng sản phẩm: {len(rows)}")
        for r in rows:
            print(f"  - {r['name']} ({r['id']}) -> ${r['price']:.2f}")

        # 2. Thử search 'telescope' giống tool search
        print("\n=== SEARCH TEST: 'kính thiên văn' (telescopes) ===")
        search_rows = execute_query(conn, """
            SELECT id, name, price_units + price_nanos / 1e9 AS price, categories
            FROM catalog.products
            WHERE categories LIKE '%telescopes%'
               OR name ILIKE '%telescope%'
               OR description ILIKE '%telescope%'
        """)
        print(f"Tìm được {len(search_rows)} sản phẩm liên quan đến telescope:")
        for r in search_rows:
            print(f"  - {r['name']} ({r['id']}) -> ${r['price']:.2f} | categories: {r['categories'][:60]}")

except Exception as e:
    print(f"[ERROR] {type(e).__name__}: {e}")
