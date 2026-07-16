#!/usr/bin/env python
"""
scripts/test_langgraph.py — Chạy test queries qua LangGraph.

Dùng để validate graph hoạt động đúng với mock EKS.

Usage:
    python scripts/test_langgraph.py
    python scripts/test_langgraph.py --queries tests/test_queries.json
    python scripts/test_langgraph.py --limit 5 --output results.json
"""

import sys, os, json, asyncio, argparse, uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_QUERIES = [
    "tìm kính thiên văn dưới 500 đô",
    "thêm iPhone 15 vào giỏ hàng",
    "review Macbook Pro",
    "gợi ý sản phẩm tương tự kính thiên văn",
    "phí giao hàng là bao nhiêu",
    "xem giỏ hàng của tôi",
    "quy đổi 100 USD sang VND",
    "sản phẩm từ 200 đến 1000 đô",
]


async def run_graph(graph, session_id: str, user_id: str, message: str) -> dict:
    """Chạy LangGraph."""
    from langchain_core.messages import HumanMessage

    config = {"configurable": {"thread_id": session_id}}
    try:
        result = await graph.ainvoke({
            "messages": [HumanMessage(content=message)],
            "session_id": session_id,
            "user_id": user_id,
            "trace_id": str(uuid.uuid4()),
            "intent": "agent",
            "intent_source": "default",
            "entities": {},
            "candidate_products": [],
            "tool_results": {},
            "final_answer": "",
            "pending_workflows": [],
            "current_workflow_index": 0,
            "workflow_results": [],
            "pending_action": None,
            "confirmed": False,
            "errors": [],
            "retry_count": 0,
            "node_retry_counts": {},
            "guardrail_violations": [],
            "node_durations": {},
            "current_product_id": None,
        }, config=config)
        return {
            "status": "ok",
            "reply": result.get("final_answer", ""),
            "intent": result.get("intent", "unknown"),
            "intent_source": result.get("intent_source", ""),
            "violations": result.get("guardrail_violations", []),
            "node_durations": result.get("node_durations", {}),
            "error": None,
        }
    except Exception as e:
        return {"status": "error", "reply": "", "intent": "error", "error": str(e)[:200]}


async def main():
    parser = argparse.ArgumentParser(description="Test LangGraph với mock EKS")
    parser.add_argument("--queries", default=None, help="Path to test_queries.json")
    parser.add_argument("--limit", type=int, default=None, help="Max queries")
    parser.add_argument("--output", default=None, help="Output JSON file")
    args = parser.parse_args()

    queries = DEFAULT_QUERIES
    if args.queries:
        with open(args.queries) as f:
            data = json.load(f)
            if isinstance(data, list):
                queries = [q if isinstance(q, str) else q.get("query", str(q)) for q in data]
            elif isinstance(data, dict):
                queries = [q.get("query", "") for q in data.get("queries", [])]

    if args.limit:
        queries = queries[:args.limit]

    print(f"\n{'='*60}")
    print(f"🧪 LangGraph Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Queries: {len(queries)}")
    print(f"{'='*60}")

    from tests.test_interactive import _setup_grpc_mocks
    _setup_grpc_mocks()

    from src.graph.main_graph import build_graph
    graph = build_graph()

    results = []
    for i, query in enumerate(queries):
        result = await run_graph(graph, f"test-{i}", "test-user", query)
        status_icon = "✅" if result.get("status") == "ok" else "❌"
        print(f"\n[{i+1}] {status_icon} {query[:60]}")
        print(f"    Intent: {result.get('intent', '?')} | Source: {result.get('intent_source', '?')}")
        reply = result.get("reply", "")
        if reply:
            print(f"    Reply: {reply[:120]}…" if len(reply) > 120 else f"    Reply: {reply}")
        if result.get("violations"):
            print(f"    ⚠️  Violations: {json.dumps(result['violations'], ensure_ascii=False)}")
        if result.get("error"):
            print(f"    ❌ Error: {result['error']}")
        results.append({"query": query, **result})

    errors = sum(1 for r in results if r.get("error"))
    print(f"\n{'='*60}")
    print(f"📊 Kết quả: {len(results) - errors}/{len(results)} passed")
    if errors:
        print(f"❌ Errors: {errors}")
    print(f"{'='*60}\n")

    if args.output:
        output = {"timestamp": datetime.now().isoformat(), "total": len(results), "results": results}
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
