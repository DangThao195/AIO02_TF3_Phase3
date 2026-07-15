import os
from pathlib import Path
import aiosqlite
from typing import List

from src.tools.search.models import Product


async def _candidate_db_paths() -> List[Path]:
    # Allow explicit override
    env = os.environ.get("SERVER_TEST_DB_PATH")
    if env:
        yield Path(env)

    # Common relative locations from this file: try a few upward hops
    p = Path(__file__).resolve()
    candidates = [
        p.parents[4] / "server-test" / "shopping.db",
        p.parents[3] / "server-test" / "shopping.db",
        Path.cwd() / "server-test" / "shopping.db",
    ]
    for c in candidates:
        yield c


async def _find_db() -> Path | None:
    async for candidate in _candidate_db_paths():
        if candidate and candidate.exists():
            return candidate
    # sync fallback: check non-async generator
    for candidate in [
        Path(os.environ.get("SERVER_TEST_DB_PATH", "")),
        Path.cwd() / "server-test" / "shopping.db",
    ]:
        if candidate and candidate.exists():
            return candidate
    return None


async def load_all_products() -> List[Product]:
    db_path = await _find_db()
    if not db_path:
        return []

    products: List[Product] = []
    try:
        async with aiosqlite.connect(str(db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT id, name, description, categories, price_units FROM products") as cur:
                rows = await cur.fetchall()
                for r in rows:
                    cats = []
                    if r[3]:
                        cats = [c.strip() for c in str(r[3]).split(",") if c.strip()]
                    products.append(Product(
                        id=str(r[0]),
                        name=str(r[1]),
                        description=str(r[2]) if r[2] else "",
                        categories=cats,
                        price_usd=type("M", (), {"units": int(r[4]) if r[4] is not None else 0})(),
                    ))
    except Exception:
        return []

    return products


async def search_local(query: str, limit: int = 20) -> List[Product]:
    db_path = await _find_db()
    if not db_path:
        return []

    qlike = f"%{query}%"
    products: List[Product] = []
    try:
        async with aiosqlite.connect(str(db_path)) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT id, name, description, categories, price_units FROM products WHERE name LIKE ? OR categories LIKE ? LIMIT ?",
                (qlike, qlike, limit),
            ) as cur:
                rows = await cur.fetchall()
                for r in rows:
                    cats = []
                    if r[3]:
                        cats = [c.strip() for c in str(r[3]).split(",") if c.strip()]
                    products.append(Product(
                        id=str(r[0]),
                        name=str(r[1]),
                        description=str(r[2]) if r[2] else "",
                        categories=cats,
                        price_usd=type("M", (), {"units": int(r[4]) if r[4] is not None else 0})(),
                    ))
    except Exception:
        return []

    return products
