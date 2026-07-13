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
