"""
graph/nodes/task_graph_builder.py — Task Graph Builder Node (Planner)

Thuật toán:
1. Pure LLM: gọi LLM với PLANNER_PROMPT + tool schemas + user query
2. RepairLayer: fix tool names, depends_on
3. Validation: max 8 nodes, tool tồn tại
"""

from __future__ import annotations

import json
import re
import time
import logging
from typing import Any

logger = logging.getLogger("graph.task_graph_builder")


def _make_node(nid: str, tool: str, args: dict, depends_on: list, confidence: float = 0.95) -> dict:
    return {"id": nid, "tool": tool, "args": args, "depends_on": depends_on,
            "confidence": confidence, "description": f"Run {tool}"}


def _format_memory(memory: dict) -> str:
    if not memory:
        return "(không có dữ liệu phiên trước)"
    parts = []
    if memory.get("last_search"):
        parts.append(f"Lần trước bạn tìm: {memory['last_search']}")
    if memory.get("last_product_id"):
        name = memory.get("last_product_name", memory["last_product_id"])
        parts.append(f"Product ID vừa xem: {memory['last_product_id']} ({name})")
    if memory.get("current_cart_items", 0) > 0:
        parts.append(f"Giỏ hàng có {memory['current_cart_items']} món")
    if memory.get("last_goal"):
        parts.append(f"Mục tiêu lượt trước: {memory['last_goal']}")
    return "; ".join(parts) if parts else "(không có dữ liệu phiên trước)"


def _repair_plan(plan: dict) -> dict:
    """RepairLayer: fix common LLM output issues."""
    from difflib import get_close_matches
    from src.tools.registry import ToolRegistry

    nodes = plan.get("nodes", [])
    all_ids = {n.get("id") for n in nodes}
    repaired = []

    known_tools = set(ToolRegistry.get_all_specs().keys())

    for node in nodes:
        tool_name = node.get("tool", "")
        if tool_name not in known_tools:
            matches = get_close_matches(tool_name, known_tools, n=1, cutoff=0.7)
            if matches:
                node = dict(node)
                node["tool"] = matches[0]

        deps = node.get("depends_on", [])
        node_id = node.get("id", "")
        fixed_deps = [d for d in deps if d in all_ids and d != node_id]
        node = dict(node)
        node["depends_on"] = fixed_deps

        if "confidence" not in node:
            node["confidence"] = 0.8

        if not node.get("description"):
            spec = ToolRegistry.get_spec(node.get("tool", ""))
            node["description"] = spec.description[:60] if spec else node.get("tool", "")

        repaired.append(node)

    if len(repaired) > 8:
        repaired.sort(key=lambda n: n.get("confidence", 0), reverse=True)
        repaired = repaired[:8]

    plan = dict(plan)
    plan["nodes"] = repaired
    return plan


async def task_graph_builder_node(state: dict) -> dict:
    """
    Task Graph Builder Node — tạo DAG plan từ user query + tool schemas.
    Output: {plan, plan_step_index, current_goal, planner_reasoning, plan_confidence, node_durations}
    """
    t0 = time.time()

    messages = state.get("messages", [])
    query = ""
    if messages:
        last = messages[-1]
        query = last.content if hasattr(last, "content") else str(last)

    planner_memory = state.get("planner_memory") or {}

    # ── LLM path (pure LLM, no template matcher) ──
    plan = None
    from src.llm.llm import get_llm_client
    from src.llm.prompt import PLANNER_PROMPT
    from src.tools.registry import ToolRegistry

    llm = get_llm_client()
    prompt_text = ""
    try:
        prompt_text = PLANNER_PROMPT.format(
            tool_schemas_text=ToolRegistry.get_all_schemas_text(),
            user_query=query,
            planner_memory=_format_memory(planner_memory),
        )
    except Exception as e:
        logger.error("[task_graph_builder] Prompt format failed: %s", e)
        prompt_text = f"User query: {query}\nTools: {ToolRegistry.get_all_schemas_text()}\nCreate DAG plan JSON."

    try:
        resp = llm.invoke(prompt_text, temperature=0.2, max_tokens=800)
        text = resp.content if hasattr(resp, "content") else str(resp)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        try:
            plan = json.loads(text)
        except json.JSONDecodeError:
            parsed = llm.extract_json(resp)
            if parsed:
                plan = parsed
            else:
                raise
    except Exception as e:
        logger.warning("[task_graph_builder] LLM failed (attempt 1): %s", e)
        try:
            resp = llm.invoke(prompt_text, temperature=0.1, max_tokens=600)
            text = resp.content if hasattr(resp, "content") else str(resp)
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```\w*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            plan = json.loads(text)
        except Exception as e2:
            logger.error("[task_graph_builder] LLM failed (attempt 2): %s", e2)
            plan = {"nodes": [], "goal": query, "reasoning": "LLM parse failed"}

    # ── RepairLayer ──
    plan = _repair_plan(plan)

    # ── Validation: filter unknown tools ──
    from src.tools.registry import ToolRegistry
    known_tools = set(ToolRegistry.get_all_specs().keys())
    valid_nodes = [n for n in plan.get("nodes", []) if n.get("tool") in known_tools or not n.get("tool")]
    plan["nodes"] = valid_nodes

    # ── plan_confidence = average node confidence ──
    nodes = plan.get("nodes", [])
    if nodes:
        plan_confidence = sum(n.get("confidence", 0.8) for n in nodes) / len(nodes)
    else:
        plan_confidence = 1.0

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[task_graph_builder] nodes=%d confidence=%.2f goal=%.60s (%dms)",
                len(nodes), plan_confidence, plan.get("goal", ""), duration_ms)

    return {
        "plan": plan,
        "plan_step_index": 0,
        "current_goal": plan.get("goal", query),
        "planner_reasoning": plan.get("reasoning", ""),
        "plan_confidence": plan_confidence,
        "node_durations": {"task_graph_builder": duration_ms},
    }
