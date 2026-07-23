"""
graph/nodes/reflection.py — Reflection Node

Kiểm tra chất lượng tool results và quyết định có replan không.
4 trigger checks tuần tự, first match wins.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("graph.reflection")


async def reflection_node(state: dict) -> dict:
    """
    Reflection Node — quyết định pass hoặc replan.
    Output: {reflection_result, replan_count, reflection_issues, node_durations}
    """
    t0 = time.time()

    # ── Skip conditions ──
    if state.get("guardrail_violations"):
        return _pass(t0, ["guardrail_violation — skip"])
    if state.get("pending_action"):
        return _pass(t0, ["pending_action — skip"])

    errors = state.get("errors") or []
    if isinstance(errors, (str, int, float)):
        errors = []

    tool_results = state.get("tool_results") or {}
    plan_confidence = state.get("plan_confidence", 1.0)
    replan_count = state.get("replan_count", 0)
    semantic_fail = state.get("semantic_hallucination_detected", False)
    issues: list[str] = []

    # ── Check errors FIRST (before tool_results) ──
    if len(errors) >= 1:
        error_strs = [e.get("error", str(e)) if isinstance(e, dict) else str(e) for e in errors]
        transient_keywords = ["UNAVAILABLE", "Connection refused", "gRPC", "connection", "timeout"]
        all_transient = all(
            any(kw.lower() in es.lower() for kw in transient_keywords)
            for es in error_strs
        )
        if all_transient:
            logger.info("[reflection] all errors transient — skipping replan")
        else:
            issues.append(f"tool_errors: {len(errors)} errors")

    # ── 4 trigger checks (sequential, first match) ──

    # 1. Zero result
    if not issues:
        for tool_name, result in tool_results.items():
            r = result if isinstance(result, dict) else {}
            if isinstance(result, str):
                try:
                    r = json.loads(result)
                except Exception:
                    pass
            if r.get("total") == 0 or r.get("status") == "empty":
                issues.append(f"zero_result: {tool_name} returned 0 results")
                break

    # 3. Low confidence
    if not issues and plan_confidence < 0.5:
        issues.append(f"low_confidence: plan_confidence={plan_confidence:.2f}")

    # 4. Semantic gate fail
    if not issues and semantic_fail:
        issues.append("semantic_gate_fail: hallucination detected")

    # ── Decision ──
    if replan_count >= 2:
        # Force pass — giới hạn replan loops (max 1 per spec)
        reflection_result = "pass"
    elif issues:
        reflection_result = "replan"
        replan_count += 1
    else:
        reflection_result = "pass"

    duration_ms = int((time.time() - t0) * 1000)
    logger.info("[reflection] result=%s issues=%s replan_count=%d (%dms)",
                reflection_result, issues, replan_count, duration_ms)

    return {
        "reflection_result": reflection_result,
        "replan_count": replan_count,
        "reflection_issues": issues,
        "node_durations": {"reflection": duration_ms},
    }


def _pass(t0: float, issues: list) -> dict:
    return {
        "reflection_result": "pass",
        "replan_count": 0,
        "reflection_issues": issues,
        "node_durations": {"reflection": int((time.time() - t0) * 1000)},
    }
