import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["SKIP_LLM_SQL_FLOW"] = "1"

from src.tools.search import search_products_v2
from src.tools.search.orchestrator import SearchOrchestrator
from src.tools.search.tracer import SearchTracer


async def test_telescope_under_100():
    orch = SearchOrchestrator()
    tracer = SearchTracer()
    result = await orch.search("telescope under 100", tracer=tracer)
    assert result.total > 0, "Should find telescope products under $100"
    assert "sql" in result.flows_used
    print(f"Found {result.total} products")
    for sp in result.products[:3]:
        p = sp.product
        print(f"  [{sp.score:.0f}] {p.name} - ${p.price_usd.units}")
    print("Steps:")
    for s in tracer.steps:
        print(f"  [{s['status']}] {s['action']} ({s['duration_ms']}ms) - {s['detail'][:80]}")
    print("OK: test_telescope_under_100")


async def test_full_text_search():
    orch = SearchOrchestrator()
    tracer = SearchTracer()
    result = await orch.search("flashlight", tracer=tracer)
    assert result.total > 0, "Should find flashlight products"
    print(f"Found {result.total} products")
    print("Steps:")
    for s in tracer.steps:
        print(f"  [{s['status']}] {s['action']} ({s['duration_ms']}ms) - {s['detail'][:80]}")
    print("OK: test_full_text_search")


async def test_empty_query():
    orch = SearchOrchestrator()
    tracer = SearchTracer()
    result = await orch.search("", tracer=tracer)
    assert result.total == 0
    assert result.error is not None
    print("Steps:")
    for s in tracer.steps:
        print(f"  [{s['status']}] {s['action']} ({s['duration_ms']}ms) - {s['detail'][:80]}")
    print("OK: test_empty_query")


async def test_tool_returns_trace():
    result = await search_products_v2.ainvoke({"query": "telescope"})
    parts = result.split("__SEARCH_TRACE__:")
    assert len(parts) == 2, "Should contain trace marker"
    trace = json.loads(parts[1])
    assert len(trace) > 0, "Should have trace steps"
    print(f"Tool returned {len(trace)} search trace steps")
    for s in trace:
        print(f"  [{s['status']}] {s['action']} ({s['duration_ms']}ms) - {s['detail'][:80]}")
    print("OK: test_tool_returns_trace")


async def main():
    await test_telescope_under_100()
    await test_full_text_search()
    await test_empty_query()
    await test_tool_returns_trace()
    print("\nAll smoke tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
