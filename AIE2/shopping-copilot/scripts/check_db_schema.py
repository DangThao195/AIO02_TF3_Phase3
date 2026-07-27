import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from src.database.connect import get_conn, execute_query

with get_conn() as conn:
    schemas = execute_query(conn, "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name")
    print('Schemas:', [s['schema_name'] for s in schemas])

    tables = execute_query(conn, """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
        ORDER BY 1,2
    """)
    print('Tables:')
    for t in tables:
        name = t['table_name']
        sc = t['table_schema']
        print(f"  {sc}.{name}")
