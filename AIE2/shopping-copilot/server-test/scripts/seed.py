#!/usr/bin/env python3
import asyncio
import pathlib

import asyncpg

DB_DSN = "postgresql://otelu:otelp@localhost:5432/shopping"


async def main() -> None:
    sql_path = pathlib.Path(__file__).resolve().parent.parent / "database" / "init.sql"
    sql = sql_path.read_text(encoding="utf-8")

    conn = await asyncpg.connect(DB_DSN)
    try:
        await conn.execute(sql)
        print("init.sql executed successfully")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
