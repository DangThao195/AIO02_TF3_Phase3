import aiosqlite

from server.config import DB_PATH

_conn: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def get_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("db not initialised — call init_db() first")
    return _conn


async def fetch(query: str, *args) -> list:
    async with get_conn().execute(query, args) as cursor:
        return await cursor.fetchall()


async def fetchrow(query: str, *args):
    async with get_conn().execute(query, args) as cursor:
        return await cursor.fetchone()


async def execute(query: str, *args) -> None:
    await get_conn().execute(query, args)
    await get_conn().commit()


async def execute_many(query: str, args: list[tuple]) -> None:
    await get_conn().executemany(query, args)
    await get_conn().commit()


async def db_query_variants(query_variants: list, filters: dict | None = None, limit: int = 50) -> list:
    """Run a list of parameterized text variants and return deduplicated product rows.

    Each variant is treated as a LIKE pattern search against `name` and `description`.
    Returns a list of sqlite3.Row objects.
    """
    seen = set()
    out = []
    filters = filters or {}
    for v in query_variants:
        pattern = f"%{v}%"
        rows = await fetch(
            """SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories
               FROM products
               WHERE name LIKE ? OR description LIKE ?
               LIMIT ?""",
            pattern, pattern, limit,
        )
        for r in rows:
            pid = r["id"]
            if pid in seen:
                continue
            seen.add(pid)
            out.append(r)
    return out


async def db_query_conditions(conditioned_query: dict, limit: int = 50) -> tuple[list, int]:
    """Run a conditioned query built from structured filters.

    conditioned_query example: {"price_min": 10, "price_max": 100, "category": "books", "keywords": ["telescope"]}
    Returns (rows, total_estimate)
    """
    clauses = []
    params: list = []

    if not conditioned_query:
        conditioned_query = {}

    if "price_min" in conditioned_query:
        clauses.append("price_units >= ?")
        params.append(int(conditioned_query["price_min"]))
    if "price_max" in conditioned_query:
        clauses.append("price_units <= ?")
        params.append(int(conditioned_query["price_max"]))
    if "category" in conditioned_query and conditioned_query["category"]:
        clauses.append("categories LIKE ?")
        params.append(f"%{conditioned_query['category']}%")
    if "keywords" in conditioned_query and conditioned_query["keywords"]:
        kw_clauses = []
        for kw in conditioned_query["keywords"]:
            kw_clauses.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        if kw_clauses:
            clauses.append("(" + " OR ".join(kw_clauses) + ")")

    where = " AND ".join(clauses) if clauses else "1=1"

    query = f"SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories FROM products WHERE {where} LIMIT ?"
    params.append(limit)
    rows = await fetch(query, *params)

    # Try to estimate total by counting if DB small; otherwise return -1
    try:
        count_query = f"SELECT COUNT(1) as cnt FROM products WHERE {where}"
        count_row = await fetchrow(count_query, *params[:-1])
        total = int(count_row["cnt"]) if count_row is not None else -1
    except Exception:
        total = -1

    return rows, total


async def db_execute_text_search(text_query: str, limit: int = 50) -> list:
    """Full-text-like search using LIKE on name and description.

    In production this should use FTS / dedicated search index. This implementation
    is intentionally simple for server-test environment.
    """
    pattern = f"%{text_query}%"
    rows = await fetch(
        """SELECT id, name, description, picture, price_currency_code, price_units, price_nanos, categories
           FROM products
           WHERE name LIKE ? OR description LIKE ?
           ORDER BY name
           LIMIT ?""",
        pattern, pattern, limit,
    )
    return rows


async def get_category(category_hint: str) -> list:
    """Return category suggestions (simple substring match over categories column)."""
    pattern = f"%{category_hint}%"
    rows = await fetch(
        "SELECT DISTINCT categories FROM products WHERE categories LIKE ? LIMIT 20",
        pattern,
    )
    cats = set()
    for r in rows:
        raw = r["categories"] or ""
        for part in raw.split(","):
            p = part.strip()
            if category_hint.lower() in p.lower():
                cats.add(p)
    return list(cats)


async def get_full_product_name(product_id_or_partial: str) -> str | None:
    """Return exact product name for id or the best match for a partial name."""
    # Try id lookup first
    row = await fetchrow(
        "SELECT name FROM products WHERE id = ?",
        product_id_or_partial,
    )
    if row:
        return row["name"]

    # Fallback to name LIKE
    row = await fetchrow(
        "SELECT name FROM products WHERE name LIKE ? LIMIT 1",
        f"%{product_id_or_partial}%",
    )
    if row:
        return row["name"]
    return None
