from typing import Any, Dict, List

from src.tools.search.models import Product
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
        except Exception:
            pass
        self._initialized = True

    def execute(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        self._validate_query(query)
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(query)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description or []]
                results = [dict(zip(columns, row)) for row in rows[:limit]]
                return results
        except Exception as e:
            raise RuntimeError(
                f"Cannot execute SQL query — PostgreSQL EKS not reachable. "
                f"Please start port-forward (kubectl port-forward svc/postgresql 5433:5432 -n techx-tf3). "
                f"Original error: {e}"
            ) from e

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
