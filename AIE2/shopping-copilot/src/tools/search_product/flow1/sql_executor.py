from typing import Any, Dict, List

from src.tools.search_product.models import Product
from src.database.connect import get_conn, init_pool


class SQLQueryExecutor:
    """Thực thi SQL query trên database của thư mục src/database."""

    def __init__(self):
        self._initialized = False

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            init_pool()
            self._initialized = True
        except Exception as e:
            self._initialized = False
            raise e

    _PG_UNREACHABLE = False

    def execute(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        self._validate_query(query)

        # If running in mock mode or PostgreSQL previously failed, skip PostgreSQL and query SQLite directly.
        import os
        if os.getenv("MOCK_EKS") == "true" or SQLQueryExecutor._PG_UNREACHABLE:
            return self._execute_sqlite(query, limit)

        try:
            self.ensure_initialized()
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(query)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description or []]
                return [dict(zip(columns, row)) for row in rows[:limit]]
        except Exception as e:
            SQLQueryExecutor._PG_UNREACHABLE = True
            import logging
            logging.getLogger(__name__).warning(f"PostgreSQL connection failed ({e}). Falling back to SQLite...")
            return self._execute_sqlite(query, limit)

    def _execute_sqlite(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        import sqlite3
        import os
        from pathlib import Path

        db_path = os.getenv("SHOPPING_DB_PATH")
        if not db_path:
            base = Path(__file__).resolve()
            for parent in [base.parents[4], base.parents[3], base.parents[2], base.parents[1], Path.cwd()]:
                cand1 = parent / "server-test" / "shopping.db"
                cand2 = parent / "shopping.db"
                if cand1.exists():
                    db_path = str(cand1)
                    break
                if cand2.exists():
                    db_path = str(cand2)
                    break

        if not db_path or not os.path.exists(db_path):
            raise RuntimeError(f"Cannot execute SQL — PostgreSQL failed and SQLite DB not found at {db_path}")

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description or []]
            return [dict(zip(columns, row)) for row in rows[:limit]]
        finally:
            conn.close()

    def _validate_query(self, query: str) -> None:
        normalized = (query or "").strip()
        if not normalized:
            raise ValueError("SQL query is empty")
        if not normalized.upper().startswith("SELECT"):
            raise ValueError("Only SELECT statements are allowed")
        blocked_tokens = [";", "--", "/*", "*/", "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
        upper_query = normalized.upper()
        if any(token in upper_query for token in blocked_tokens):
            raise ValueError("Unsupported SQL statement")


class SQLFlowExecutor:
    """Wrapper dùng cho Flow 1, mapping kết quả SQL sang định dạng sản phẩm."""

    def __init__(self):
        self.executor = SQLQueryExecutor()

    def execute(self, query: str, limit: int = 15) -> List[Product]:
        rows = self.executor.execute(query, limit=limit)
        products: List[Product] = []
        for row in rows:
            categories = []
            if row.get("categories"):
                categories = [c.strip() for c in str(row.get("categories")).split(",") if c.strip()]
            products.append(
                Product(
                    id=str(row.get("id", "")),
                    name=str(row.get("name", "")),
                    description=str(row.get("description", "")),
                    categories=categories,
                    price_usd=type("Money", (), {"units": int(row.get("price_units") or 0), "nanos": int(row.get("price_nanos") or 0), "currency_code": "USD"})(),
                )
            )
        return products
