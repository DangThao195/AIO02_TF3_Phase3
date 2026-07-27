"""
graph/nodes/task_graph_builder.py — Task Graph Builder Node (Planner)

Thuật toán:
1. LLM path: gọi LLM với PLANNER_PROMPT + tool schemas + user query
2. RepairLayer: fix tool names
3. Validation: max 8 nodes, tool tồn tại
4. Output flat list — không DAG, không depends_on, không args
"""

from __future__ import annotations

import json
import re
import time
import logging
from typing import Any

logger = logging.getLogger("graph.task_graph_builder")


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
    """RepairLayer: fix tool names via fuzzy matching, cap at 8 nodes."""
    from difflib import get_close_matches
    from src.tools.registry import ToolRegistry

    nodes = plan.get("nodes", [])
    repaired = []
    known_tools = set(ToolRegistry.get_all_specs().keys())

    for node in nodes:
        tool_name = node.get("tool", "")
        if tool_name not in known_tools:
            matches = get_close_matches(tool_name, known_tools, n=1, cutoff=0.7)
            if matches:
                node = dict(node)
                node["tool"] = matches[0]

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
    Task Graph Builder Node — tạo flat list plan từ user query + tool schemas.
    Output: {plan, plan_step_index, current_goal, planner_reasoning, plan_confidence, node_durations}
    """
    t0 = time.time()

    try:
        from src.tools.registry import ToolRegistry
        messages = state.get("messages", [])
        query = ""
        if messages:
            last = messages[-1]
            query = last.content if hasattr(last, "content") else str(last)

        translated_query = state.get("translated_query") or ""
        if translated_query and translated_query != query:
            logger.info("[task_graph_builder] using translated_query: %.80s → %.80s", query, translated_query)
            query = translated_query

        resolved_entities = state.get("resolved_entities") or {}
        planner_memory = state.get("planner_memory") or {}

        if resolved_entities.get("product_id") and not planner_memory.get("last_product_id"):
            planner_memory = dict(planner_memory)
            planner_memory["last_product_id"] = resolved_entities["product_id"]
        if resolved_entities.get("resolved_name") and not planner_memory.get("last_product_name"):
            planner_memory = dict(planner_memory)
            planner_memory["last_product_name"] = resolved_entities["resolved_name"]

        reference_context = ""
        ref_name = resolved_entities.get("resolved_name") or ""
        ref_id = resolved_entities.get("product_id") or ""
        ref_type = resolved_entities.get("reference_type") or ""
        if ref_name or ref_id:
            reference_context = f"\nReference context: user is referring to '{ref_name}' (product_id={ref_id}, type={ref_type})"

        # ── LLM path ──
        plan = None
        from src.llm.llm import get_llm_client
        from src.llm.prompt import PLANNER_PROMPT

        llm = get_llm_client()
        prompt_text = ""
        try:
            from src.tools.language_detector import detect_language
            user_lang = state.get("user_original_lang") or detect_language(query)
            lang_instruction = {
                "vi": "Trả về JSON danh sách tool — không kèm giải thích.",
                "en": "Return JSON tool list only — no explanation.",
            }.get(user_lang, "Respond in the same language as the user's input.")
            prompt_text = PLANNER_PROMPT.format(
                tool_schemas_text=ToolRegistry.get_all_schemas_text(),
                user_query=query,
                planner_memory=_format_memory(planner_memory),
                language_instruction=lang_instruction,
            ) + reference_context
        except Exception as e:
            logger.error("[task_graph_builder] Prompt format failed: %s", e)
            prompt_text = f"User query: {query}\nTools: {ToolRegistry.get_all_schemas_text()}\nCreate flat list plan JSON.{reference_context}"

        try:
            resp = llm.invoke(prompt_text, temperature=0.2, max_tokens=800)
            text = resp.content if hasattr(resp, "content") else str(resp)
            text = text.strip()
            m = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
            if m:
                text = m.group(1).strip()
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
                m = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
                if m:
                    text = m.group(1).strip()
                plan = json.loads(text)
            except Exception as e2:
                logger.error("[task_graph_builder] LLM failed (attempt 2): %s", e2)
                plan = {"nodes": [], "goal": query, "reasoning": "LLM parse failed"}

        # ── Normalize: list → dict ──
        if isinstance(plan, list):
            plan = {"nodes": plan, "goal": query, "reasoning": "LLM returned array"}

        # ── RepairLayer ──
        if plan:
            plan = _repair_plan(plan)
        else:
            plan = {"nodes": [], "goal": query, "reasoning": "Empty plan from LLM"}

        # ── Validation: filter unknown tools ──
        known_tools = set(ToolRegistry.get_all_specs().keys())
        valid_nodes = [n for n in plan.get("nodes", []) if n.get("tool") in known_tools or not n.get("tool")]
        plan["nodes"] = valid_nodes

        # ── plan_confidence ──
        nodes = plan.get("nodes", [])
        plan_confidence = sum(n.get("confidence", 0.8) for n in nodes) / len(nodes) if nodes else 1.0

    except Exception as e:
        logger.error("[task_graph_builder] UNHANDLED ERROR in node: %s", e, exc_info=True)
        query = "unknown"
        plan = {"nodes": [], "goal": "fallback", "reasoning": f"Node error: {str(e)[:200]}"}
        plan_confidence = 1.0
        nodes = []

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
