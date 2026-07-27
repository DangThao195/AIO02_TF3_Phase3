"""
scripts/export_db_to_json.py - Export toàn bộ DB data (products + reviews) ra JSON
làm cơ sở evidence cho evaluation pipeline.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.database.connect import get_conn, execute_query

OUT_PATH = Path(__file__).resolve().parent.parent / "src" / "evaluation" / "reports" / "db_ground_truth.json"

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

print("=== EXPORT DB GROUND TRUTH ===")

result = {}

with get_conn() as conn:
    # 1. Products
    products = execute_query(conn, """
        SELECT
            id,
            name,
            description,
            picture,
            price_units,
            price_nanos,
            price_units + price_nanos / 1e9 AS price,
            categories
        FROM catalog.products
        ORDER BY name
    """)
    print(f"[+] Products: {len(products)} rows")
    for p in products:
        p['price'] = float(p['price'])
        p['price_units'] = int(p['price_units'])
        p['price_nanos'] = int(p['price_nanos'])
    result['products'] = products

    # 2. Reviews + avg score per product
    reviews_raw = execute_query(conn, """
        SELECT
            r.product_id,
            r.username AS reviewer_name,
            r.score,
            r.description AS review_text
        FROM reviews.productreviews r
        ORDER BY r.product_id, r.score DESC
    """)
    print(f"[+] Reviews: {len(reviews_raw)} rows")

    # Group by product_id
    from collections import defaultdict
    reviews_by_product = defaultdict(list)
    for rv in reviews_raw:
        reviews_by_product[rv['product_id']].append({
            'reviewer': rv['reviewer_name'],
            'score': float(rv['score']) if rv['score'] else None,
            'text': rv['review_text'],
        })
    result['reviews'] = dict(reviews_by_product)

    # 3. Avg scores per product
    avg_scores = execute_query(conn, """
        SELECT product_id, ROUND(AVG(score), 2) AS avg_score, COUNT(*) AS review_count
        FROM reviews.productreviews
        GROUP BY product_id
    """)
    avg_map = {r['product_id']: {'avg_score': float(r['avg_score']), 'review_count': int(r['review_count'])} for r in avg_scores}
    result['avg_scores'] = avg_map

    # 4. Categories
    cats = execute_query(conn, """
        SELECT DISTINCT categories FROM catalog.products ORDER BY categories
    """)
    result['all_categories_raw'] = [r['categories'] for r in cats]

    # 5. Enrich products with avg_score
    for p in products:
        pid = p['id']
        if pid in avg_map:
            p['avg_score'] = avg_map[pid]['avg_score']
            p['review_count'] = avg_map[pid]['review_count']
        else:
            p['avg_score'] = None
            p['review_count'] = 0

    print(f"\n=== SUMMARY ===")
    print(f"Products: {len(products)}")
    for p in sorted(products, key=lambda x: x['price']):
        print(f"  {p['name']:45s} ${p['price']:>8.2f}  ★{p.get('avg_score', 'N/A')} ({p.get('review_count', 0)} reviews)")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=decimal_default)

print(f"\n[OK] Saved -> {OUT_PATH}")
