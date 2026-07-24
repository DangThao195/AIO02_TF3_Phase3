#!/usr/bin/env python3
"""
test_db_direct.py — Direct database test for review ranking queries
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.tools.search_product.flow1.sql_executor import SQLQueryExecutor

print("="*80)
print("DIRECT DATABASE QUERY TEST")
print("="*80)

executor = SQLQueryExecutor()
executor.ensure_initialized()

# Test 1: Simple query
print("\n[Test 1] Count products...")
try:
    rows = executor.execute("SELECT COUNT(*) as cnt FROM products")
    print(f"✓ Total products: {rows[0]['cnt']}")
except Exception as e:
    print(f"✗ FAIL: {e}")

# Test 2: Count reviews
print("\n[Test 2] Count reviews...")
try:
    rows = executor.execute("SELECT COUNT(*) as cnt FROM reviews.productreviews")
    print(f"✓ Total reviews: {rows[0]['cnt']}")
except Exception as e:
    print(f"✗ FAIL: {e}")

# Test 3: Best reviewed products query (with timeout)
print("\n[Test 3] Get best reviewed products...")
try:
    import time
    start = time.time()
    
    query = """
        SELECT p.id, p.name, p.categories, p.price_units, p.price_nanos,
               ROUND(AVG(r.score), 2) AS avg_score,
               COUNT(r.id) AS review_count
        FROM catalog.products p
        JOIN reviews.productreviews r ON r.product_id = p.id
        GROUP BY p.id, p.name, p.categories, p.price_units, p.price_nanos
        HAVING COUNT(r.id) > 0
        ORDER BY avg_score DESC, review_count DESC
    """
    
    rows = executor.execute(query, limit=5)
    elapsed = time.time() - start
    
    print(f"✓ Query completed in {elapsed:.2f}s")
    print(f"✓ Found {len(rows)} products")
    for i, r in enumerate(rows[:3]):
        print(f"  {i+1}. {r['name']} - {r['avg_score']} stars ({r['review_count']} reviews)")
        
except Exception as e:
    print(f"✗ FAIL: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("TEST COMPLETE")
print("="*80)
