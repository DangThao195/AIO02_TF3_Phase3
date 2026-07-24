#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from src.tools.search.flow1.sql_executor import SQLQueryExecutor

e = SQLQueryExecutor()
e.ensure_initialized()

# Check tables
print("=== TABLES IN DATABASE ===")
rows = e.execute("""
SELECT table_schema, table_name 
FROM information_schema.tables 
WHERE table_type = 'BASE TABLE' 
AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name
""")

for r in rows:
    print(f"{r['table_schema']}.{r['table_name']}")

# Check reviews table columns
print("\n=== CHECKING REVIEWS TABLE ===")
try:
    rows = e.execute("SELECT * FROM reviews LIMIT 1")
    if rows:
        print("Columns:", list(rows[0].keys()))
except Exception as e:
    print(f"Error: {e}")
