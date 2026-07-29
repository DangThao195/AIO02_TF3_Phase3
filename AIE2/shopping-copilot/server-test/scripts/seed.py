#!/usr/bin/env python3
import asyncio
import pathlib

import aiosqlite


async def main() -> None:
    sql_path = pathlib.Path(__file__).resolve().parent.parent / "database" / "init.sql"
    sql = sql_path.read_text(encoding="utf-8")

    db_path = sql_path.parent.parent / "shopping.db"
    conn = await aiosqlite.connect(str(db_path))
    try:
        await conn.executescript(sql)
        print(f"init.sql executed successfully → {db_path}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
