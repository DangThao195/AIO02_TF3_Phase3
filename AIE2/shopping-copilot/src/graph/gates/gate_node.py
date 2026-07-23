"""
graph/gates/gate_node.py — Shared Gate Node Interface

Binary classification via Amazon Nova Lite.
Temperature=0.0, max_tokens=3 (YES/NO only).
Fallback to DEFAULT_DECISIONS on timeout/error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("graph.gates")

# ── Metrics counters ──
_gate_metrics: dict = {"calls": defaultdict(int), "decisions": defaultdict(int), "timeouts": defaultdict(int)}


DEFAULT_DECISIONS: dict[str, bool] = {
    "routing_gate": False,               # safe — go LLM path
    "plan_validity_gate": True,          # don't block unnecessarily
    "semantic_hallucination_gate": False, # lean toward fallback
    "confirm_parse_gate": True,          # UX: don't reject incorrectly
    "replan_gate": False,                # avoid infinite loops
}


@dataclass
class GateResult:
    decision: bool
    reason: Optional[str] = None
    latency_ms: float = 0.0
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0})


async def gate_node(
    question: str,
    context: str = "",
    gate_name: str = "routing_gate",
    want_reason: bool = False,
    timeout: float = 2.0,
) -> GateResult:
    """
    Call Nova Lite with binary classification prompt.
    Returns GateResult with decision=True (YES) or False (NO).
    Falls back to DEFAULT_DECISIONS on error.
    """
    t0 = time.time()
    default = DEFAULT_DECISIONS.get(gate_name, False)

    try:
        from src.llm.llm import get_llm_client
        from src.llm.prompt import GATE_SYSTEM_PROMPT

        llm = get_llm_client()
        max_tokens = 25 if want_reason else 3
        full_question = f"{question}\n\nContext: {context}" if context else question

        async def _call():
            # Run sync LLM in executor to support timeout
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: llm.invoke(
                    full_question,
                    system_prompt=GATE_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
            )

        resp = await asyncio.wait_for(_call(), timeout=timeout)
        text = resp.content if hasattr(resp, "content") else str(resp)
        text = text.strip()

        decision = text.upper().startswith("YES")
        reason = text if want_reason else None
        latency = (time.time() - t0) * 1000

        _gate_metrics["calls"][gate_name] += 1
        _gate_metrics["decisions"][f"{gate_name}:{decision}"] += 1
        logger.debug("[gate:%s] decision=%s latency=%.0fms", gate_name, decision, latency)
        return GateResult(decision=decision, reason=reason, latency_ms=latency)

    except asyncio.TimeoutError:
        _gate_metrics["timeouts"][gate_name] += 1
        logger.warning("[gate:%s] timeout after %.1fs — using default=%s", gate_name, timeout, default)
    except Exception as e:
        logger.warning("[gate:%s] error: %s — using default=%s", gate_name, e, default)

    return GateResult(
        decision=default,
        reason=f"fallback:{gate_name}",
        latency_ms=(time.time() - t0) * 1000,
    )
