import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_TEST_ROOT = ROOT / "server-test"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SERVER_TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_TEST_ROOT))

from src.tools.search.query_analyzer import QueryAnalyzerPipeline
from server.db import close_db, execute_search_sql, init_db


def test_sql_generation_and_execution():
    async def run_test():
        await init_db()
        try:
            analyzer = QueryAnalyzerPipeline()
            sq = analyzer.parse("tìm kính thiên văn dưới 100 đô")
            assert sq.sql is not None
            assert "SELECT" in sq.sql.upper()
            rows = await execute_search_sql(sq.sql, limit=5)
            assert rows
            assert any("telescopes" in (row["categories"] or "").lower() for row in rows)
        finally:
            await close_db()

    asyncio.run(run_test())
