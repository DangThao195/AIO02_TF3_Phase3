#!/usr/bin/env python
"""
scripts/compare_react_vs_graph.py — So sánh output ReAct vs LangGraph.

Dùng để validate graph migration không làm thay đổi chất lượng trả lời.

Usage:
    python scripts/compare_react_vs_graph.py
    python scripts/compare_react_vs_graph.py --queries tests/test_queries.json
    python scripts/compare_react_vs_graph.py --limit 5 --output compare_results.json
"""

import sys
import os
import json
import asyncio
import argparse
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────────────────────────
# Default test queries nếu không có file
# ──────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────
# Comparison logic
# ──────────────────────────────────────────────────────────────────

async def run_react(agent, session_id: str, user_id: str, message: str) -> dict:
    """Chạy ReAct agent path."""
    try:
        result = await agent.chat(
            session_id=session_id,
            user_id=user_id,
            user_message=message,
        )
        return {
            "status": result.get("status", "ok"),
            "reply": result.get("reply", ""),
            "error": None,
        }
    except Exception as e:
        return {"status": "error", "reply": "", "error": str(e)[:200]}


async def run_graph(graph, session_id: str, user_id: str, message: str) -> dict:
    """Chạy LangGraph path."""
    from langchain_core.messages import HumanMessage

    config = {"configurable": {"thread_id": session_id}}
    try:
        result = await graph.ainvoke(
            {
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
            },
            config=config,
        )
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


async def compare_single(agent, graph, query: str, idx: int) -> dict:
    """So sánh 1 query."""
    session_react = f"compare-react-{idx}"
    session_graph = f"compare-graph-{idx}"
    user = "compare-user"

    print(f"\n[{idx+1}] Query: {query[:60]}")

    react_result = await run_react(agent, session_react, user, query)
    graph_result = await run_graph(graph, session_graph, user, query)

    react_reply = react_result.get("reply", "")
    graph_reply = graph_result.get("reply", "")

    # So sánh độ tương đồng (đơn giản: có cùng key info không)
    is_same = react_reply.strip() == graph_reply.strip()

    # Đánh giá quality (length comparison)
    react_len = len(react_reply)
    graph_len = len(graph_reply)
    length_ratio = graph_len / max(react_len, 1)

    print(f"  ReAct ({react_len} chars): {react_reply[:100]!r}")
    print(f"  Graph ({graph_len} chars): {graph_reply[:100]!r}")
    print(f"  Intent: {graph_result.get('intent', '?')} (source: {graph_result.get('intent_source', '?')})")
    print(f"  Length ratio: {length_ratio:.2f} {'✅' if 0.5 <= length_ratio <= 2.0 else '⚠️'}")

    return {
        "query": query,
        "react": {
            "status": react_result.get("status"),
            "reply": react_reply,
            "error": react_result.get("error"),
        },
        "graph": {
            "status": graph_result.get("status"),
            "reply": graph_reply,
            "intent": graph_result.get("intent"),
            "intent_source": graph_result.get("intent_source"),
            "violations": graph_result.get("violations", []),
            "node_durations": graph_result.get("node_durations", {}),
            "error": graph_result.get("error"),
        },
        "is_identical": is_same,
        "length_ratio": round(length_ratio, 2),
        "quality_ok": 0.3 <= length_ratio <= 3.0,
    }


async def main():
    parser = argparse.ArgumentParser(description="Compare ReAct vs LangGraph outputs")
    parser.add_argument("--queries", default=None, help="Path to test_queries.json")
    parser.add_argument("--limit", type=int, default=None, help="Max queries to test")
    parser.add_argument("--output", default=None, help="Output JSON file")
    parser.add_argument("--graph-only", action="store_true", help="Chỉ chạy graph (không chạy ReAct)")
    args = parser.parse_args()

    # Load queries
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
    print(f"ReAct vs LangGraph Comparison — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Queries: {len(queries)}")
    print(f"{'='*60}")

    # Init agent
    from src.agent.copilot_agent import CopilotAgent
    agent = CopilotAgent()

    # Init graph
    # Enable all workflow flags cho comparison
    for flag in ["LANGGRAPH_ENABLED", "LANGGRAPH_SEARCH", "LANGGRAPH_REVIEW",
                 "LANGGRAPH_RECOMMEND", "LANGGRAPH_CART", "LANGGRAPH_SHIPPING"]:
        os.environ[flag] = "true"

    from src.graph.main_graph import build_graph
    graph = build_graph()

    # Run comparisons
    results = []
    for i, query in enumerate(queries):
        if args.graph_only:
            # Chỉ chạy graph
            graph_result = await run_graph(graph, f"graph-{i}", "test-user", query)
            print(f"\n[{i+1}] {query[:60]}")
            print(f"  Intent: {graph_result.get('intent')} | Reply: {graph_result.get('reply', '')[:100]!r}")
            results.append({"query": query, "graph": graph_result})
        else:
            result = await compare_single(agent, graph, query, i)
            results.append(result)

    # Summary
    if not args.graph_only:
        quality_ok = sum(1 for r in results if r.get("quality_ok", False))
        identical = sum(1 for r in results if r.get("is_identical", False))
        errors = sum(1 for r in results if r.get("graph", {}).get("error"))

        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"Total queries: {len(results)}")
        print(f"Quality OK (0.3x-3x length): {quality_ok}/{len(results)}")
        print(f"Identical output: {identical}/{len(results)}")
        print(f"Graph errors: {errors}/{len(results)}")
        print(f"{'='*60}")

    # Save output
    if args.output:
        output = {
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "results": results,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Results saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
