"""
graph/nodes/reference_resolver.py — Reference Resolver Node (§7.3-§7.7)

Phát hiện và resolve các tham chiếu như "nó", "cái đầu tiên", "cái cuối",
"quay lại", "sản phẩm đó" bằng deterministic priority chain trước khi
đưa query vào Planner (task_graph_builder).

Pipeline:
  User Input → Reference Resolver → Resolved Query → Agent (TGB)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger("graph.reference_resolver")

# ── Pattern sets ───────────────────────────────────────────────────

_DIRECT_REF = re.compile(
    r"\b(nó|cái này|cái đó|sản phẩm này|sản phẩm đó|của nó|"
    r"của chúng|sản phẩm kia)\b",
    re.I,
)

_POSITIONAL_VI = re.compile(
    r"\b(cái (đầu tiên|cuối cùng|thứ\s+\d+|thứ nhất|thứ hai|thứ ba|thứ tư|thứ năm))\b",
    re.I,
)

_POSITIONAL_EN = re.compile(
    r"\b(the (first|second|third|fourth|fifth|last|previous))\b",
    re.I,
)

_POSITIONAL_SHORT = re.compile(r"^(đầu tiên|cuối cùng|thứ hai|thứ ba)$", re.I)

_BACK_REF = re.compile(r"\b(quay lại|trở về|trước đó|quay về|trở lại|back)\b", re.I)

_ENTITY_REF = re.compile(
    r"\b(xem|cho tôi xem|show|mở|về|thông tin)\s+(.*)",
    re.I,
)

# Ánh xạ từ khóa vị trí → key trong reference_table
_POSITIONAL_MAP: dict[str, str] = {
    "đầu tiên": "first",
    "thứ nhất": "first",
    "first": "first",
    "thứ hai": "second",
    "second": "second",
    "thứ ba": "third",
    "third": "third",
    "thứ tư": "fourth",
    "fourth": "fourth",
    "thứ năm": "fifth",
    "fifth": "fifth",
    "cuối cùng": "last",
    "last": "last",
    "previous": "last",
    "trước": "last",
}

_SLIDING_WINDOW_SIZE = 5  # §9: giữ 5 assistant outputs gần nhất


def _detect_intent(query: str) -> str | None:
    """Detect reference type in query. Returns intent key or None."""
    q = query.lower().strip()

    if _BACK_REF.search(q):
        return "back"

    if _POSITIONAL_VI.search(q) or _POSITIONAL_EN.search(q) or _POSITIONAL_SHORT.match(q):
        return "positional"

    if _DIRECT_REF.search(q):
        return "direct_ref"

    if q.startswith("cái ") or q.startswith("chiếc ") or re.match(r"^(thằng|con|cái|chiếc)\s+", q):
        return "direct_ref"

    return None


def _resolve_positional(query: str, ref_table: dict) -> str | None:
    """Resolve 'cái đầu tiên', 'cái cuối', 'the second', etc."""
    q = query.lower()

    # Match "cái thứ X" or "the X"
    m = _POSITIONAL_VI.search(q) or _POSITIONAL_EN.search(q)
    if m:
        key = _POSITIONAL_MAP.get(m.group(2).lower() if m.lastindex and m.lastindex >= 2 else m.group(2))
        if key and key in ref_table:
            item = ref_table[key]
            return item.get("name") or item.get("id", "")
        return None

    # Match short form "đầu tiên", "cuối cùng"
    for phrase, key in sorted(_POSITIONAL_MAP.items(), key=lambda x: -len(x[0])):
        if phrase in q:
            if key in ref_table:
                item = ref_table[key]
                return item.get("name") or item.get("id", "")
            break

    return None


def _resolve_direct_ref(ref_stack: list, planner_memory: dict, entity_registry: dict) -> str | None:
    """§6 Reference Priority Chain."""
    # 1. Current result (top of stack)
    if ref_stack:
        items = ref_stack[-1].get("items", [])
        if items:
            first = items[0]
            return first.get("name") or first.get("id", "")

    # 2. Planner memory last product
    pid = planner_memory.get("last_product_id") or planner_memory.get("last_searched_product_id")
    if pid:
        pname = planner_memory.get("last_product_name") or planner_memory.get("last_searched_product_name")
        return pname or pid

    # 3. Entity registry — find most recent
    if entity_registry:
        # Lấy entity gần nhất (last inserted)
        for name, info in list(entity_registry.items())[-3:]:
            return info.get("id", name)

    return None


def _resolve_back(ref_stack: list) -> str | None:
    """Handle 'quay lại' — pop stack and return previous context."""
    if len(ref_stack) >= 2:
        ref_stack.pop()  # bỏ current
        prev = ref_stack[-1]
        items = prev.get("items", [])
        if items:
            return items[0].get("name") or items[0].get("id", "")
    elif ref_stack:
        # Chỉ có 1 item, quay lại item đó
        items = ref_stack[-1].get("items", [])
        if items:
            return items[0].get("name") or items[0].get("id", "")
    return None


def _resolve_entity(query: str, entity_registry: dict, ref_table: dict) -> str | None:
    """Try matching query substrings against entity_registry names."""
    q = query.lower().strip()
    # Remove common prefixes
    for prefix in ("cho tôi xem ", "xem ", "mở ", "show ", "về ", "thông tin "):
        if q.startswith(prefix):
            q = q[len(prefix):]
            break

    if not q or len(q) < 3:
        return None

    # Try exact entity name match (longest first)
    for name in sorted(entity_registry.keys(), key=len, reverse=True):
        if name in q:
            info = entity_registry[name]
            name_display = name.title() if name.islower() else name
            return info.get("id", name_display)

    # Try fuzzy: partial word match
    words = set(re.findall(r"[a-zA-ZÀ-ỹ0-9]{3,}", q))
    for name, info in entity_registry.items():
        name_words = set(re.findall(r"[a-zA-ZÀ-ỹ0-9]{3,}", name))
        if name_words and words & name_words:
            name_display = name.title() if name.islower() else name
            return info.get("id", name_display)

    return None


# ── Main node ───────────────────────────────────────────────────────

async def reference_resolver_node(state: dict) -> dict:
    """
    Reference Resolver Node — phát hiện & resolve tham chiếu trước khi vào Planner.

    Output: {resolved_query, resolved_entities, reference_stack (updated if back),
             node_durations}
    """
    t0 = time.time()

    messages = state.get("messages", [])
    query = messages[-1].content if messages and hasattr(messages[-1], "content") else ""

    ref_table = state.get("reference_table") or {}
    ref_stack = list(state.get("reference_stack") or [])
    entity_registry = state.get("entity_registry") or {}
    planner_memory = state.get("planner_memory") or {}

    resolved_query = query
    resolved_entities: dict = {}
    stack_popped = False

    # ── Detect intent ──
    intent = _detect_intent(query)

    if intent:
        logger.debug("[reference_resolver] intent=%s query=%.60s", intent, query)

        # ── Priority Chain (§6) ──

        # 1. "quay lại" — pop stack
        if intent == "back":
            prev_name = _resolve_back(ref_stack)
            if prev_name:
                resolved_query = f"Xem lại {prev_name}"
                resolved_entities["resolved_from"] = "reference_stack"
                resolved_entities["resolved_name"] = prev_name
                resolved_entities["reference_type"] = "back"
                stack_popped = True
                if len(ref_stack) >= 2 and state.get("reference_stack"):
                    pass

        # 2. Positional: "cái đầu tiên", "cái cuối", "thứ hai", "the last"
        if not resolved_entities:
            resolved = _resolve_positional(query, ref_table)
            if resolved:
                resolved_query = query
                resolved_entities["resolved_from"] = "reference_table"
                resolved_entities["resolved_name"] = resolved
                resolved_entities["reference_type"] = "positional"
                for key in ("first", "1", "last"):
                    item = ref_table.get(key, {})
                    if isinstance(item, dict) and item.get("name", "").lower() == resolved.lower():
                        pid = item.get("id", "")
                        if pid:
                            resolved_entities["product_id"] = pid
                        break

        # 3. Entity match: "xem iPhone 16"
        if not resolved_entities:
            resolved = _resolve_entity(query, entity_registry, ref_table)
            if resolved:
                resolved_query = query
                resolved_entities["resolved_from"] = "entity_registry"
                resolved_entities["resolved_name"] = resolved
                resolved_entities["reference_type"] = "entity"

        # 4. Direct reference: "nó", "cái đó", "sản phẩm này"
        if not resolved_entities:
            resolved = _resolve_direct_ref(ref_stack, planner_memory, entity_registry)
            if resolved:
                resolved_query = query
                resolved_entities["resolved_from"] = "direct_ref"
                resolved_entities["resolved_name"] = resolved
                resolved_entities["reference_type"] = "direct_ref"

        # 5. Planner memory fallback
        if not resolved_entities:
            last_pid = planner_memory.get("last_product_id") or planner_memory.get("last_searched_product_id")
            last_pname = (planner_memory.get("last_product_name") or
                          planner_memory.get("last_searched_product_name") or "")
            if last_pid:
                resolved_query = query
                resolved_entities["resolved_from"] = "planner_memory"
                resolved_entities["product_id"] = last_pid
                resolved_entities["resolved_name"] = last_pname or last_pid
                resolved_entities["reference_type"] = "planner_memory"

        # 6. LLM guess — only if everything above failed AND it's a clear ref
        if not resolved_entities:
            logger.info("[reference_resolver] all deterministic paths failed for ref query: %.60s", query)

    # ── Build output ──
    duration_ms = int((time.time() - t0) * 1000)

    output: dict = {
        "resolved_query": resolved_query,
        "resolved_entities": resolved_entities,
        "node_durations": {"reference_resolver": duration_ms},
    }

    # Trả về reference_stack đã pop nếu có "quay lại"
    if stack_popped:
        output["reference_stack"] = ref_stack

    return output
