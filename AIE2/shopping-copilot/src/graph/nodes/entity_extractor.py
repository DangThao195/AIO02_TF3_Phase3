"""
graph/nodes/entity_extractor.py — EntityExtractor node.

Extract các entity nghiệp vụ từ tin nhắn user:
  product_name: str    — tên sản phẩm ("iPhone 15", "kính thiên văn")
  quantity: int        — số lượng (mặc định 1)
  category: str        — danh mục ("điện thoại", "telescope")
  price_min: float     — giá từ
  price_max: float     — giá đến
  currency: str        — đơn vị tiền ("USD", "VND")
  destination: str     — địa chỉ giao hàng

Dùng LLM để extract, với cache để tránh gọi lại cho cùng input.
"""

from __future__ import annotations

import re
import json
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.entity_extractor")


# ──────────────────────────────────────────────────────────────────
# Regex pre-extraction (nhanh, trước LLM)
# ──────────────────────────────────────────────────────────────────

# Multi-turn positional reference patterns (khớp với IntentClassifier)
_REFERENCE_PATTERNS = [
    re.compile(r"\b(cái|sản phẩm|item|product)\s+(thứ|số|so|num|number)\s*(\d+|nhất|hai|ba|tư|năm)\b", re.IGNORECASE),
    re.compile(r"\b(cái|sản phẩm|item)\s+(đầu tiên|first|second|third|tiếp theo|cuối cùng|last|next)\b", re.IGNORECASE),
    re.compile(r"\b(thứ|số)\s*(\d+|nhất|hai|ba|tư|năm)\s*(cái|sản phẩm|item)\b", re.IGNORECASE),
]
_ORDINAL_MAP = {
    "nhất": 1, "first": 1, "đầu tiên": 1,
    "hai": 2, "second": 2,
    "ba": 3, "third": 3,
    "tư": 4, "fourth": 4,
    "năm": 5, "fifth": 5,
}

_QTY_PATTERN = re.compile(
    r"\b(\d+)\s*(cái|chiếc|sản phẩm|items?|units?|pcs?|cai|chiec)\b", re.IGNORECASE
)
_PRICE_RANGE_PATTERN = re.compile(
    r"\b(từ|from|tu)?\s*\$?(\d+(?:[.,]\d+)?)\s*(?:đến|to|-|den)\s*\$?(\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
_PRICE_UNDER_PATTERN = re.compile(
    r"\b(?:dưới|under|below|<|duoi)\s*\$?(\d+(?:[.,]\d+)?)\b", re.IGNORECASE
)
_PRICE_ABOVE_PATTERN = re.compile(
    r"\b(?:trên|above|over|>|tren)\s*\$?(\d+(?:[.,]\d+)?)\b", re.IGNORECASE
)
_CURRENCY_PATTERN = re.compile(
    r"\b(USD|VND|EUR|GBP|JPY|SGD|đô|đồng|do|dong)\b", re.IGNORECASE
)


def _regex_preextract(text: str) -> dict:
    """Extract các entity đơn giản bằng regex trước LLM."""
    entities: dict = {}

    # Số lượng
    qty_match = _QTY_PATTERN.search(text)
    if qty_match:
        entities["quantity"] = int(qty_match.group(1))

    # Khoảng giá
    range_match = _PRICE_RANGE_PATTERN.search(text)
    if range_match:
        entities["price_min"] = float(range_match.group(2).replace(",", "."))
        entities["price_max"] = float(range_match.group(3).replace(",", "."))
    else:
        under_match = _PRICE_UNDER_PATTERN.search(text)
        if under_match:
            entities["price_max"] = float(under_match.group(1).replace(",", "."))
        above_match = _PRICE_ABOVE_PATTERN.search(text)
        if above_match:
            entities["price_min"] = float(above_match.group(1).replace(",", "."))

    # Tiền tệ
    currency_match = _CURRENCY_PATTERN.search(text)
    if currency_match:
        raw_currency = currency_match.group(1).upper()
        # Normalize
        if raw_currency in ("ĐÔ",):
            raw_currency = "USD"
        elif raw_currency in ("ĐỒNG",):
            raw_currency = "VND"
        entities["currency"] = raw_currency

    return entities


# ──────────────────────────────────────────────────────────────────
# LLM extraction prompt
# ──────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
Extract các entity sau từ câu hỏi mua sắm.
Trả về JSON thuần, KHÔNG có markdown, KHÔNG có giải thích.

Fields cần extract (bỏ qua nếu không có):
- product_name: string — tên sản phẩm cụ thể
- quantity: integer — số lượng (mặc định 1 nếu mua hàng)
- category: string — danh mục sản phẩm
- destination: string — địa chỉ giao hàng

Ví dụ output: {{"product_name": "iPhone 15 Pro", "quantity": 2, "category": "điện thoại"}}
Nếu không có entity nào: {{}}

Câu hỏi: {message}
JSON:"""


# ──────────────────────────────────────────────────────────────────
# EntityExtractor node
# ──────────────────────────────────────────────────────────────────

class EntityExtractor:
    """
    Node extract entity từ tin nhắn user.

    Chiến lược:
    1. Regex extract quantity, price range, currency (không tốn token)
    2. LLM extract product_name, category, destination
    3. Merge kết quả (regex thắng nếu conflict)

    Cache theo (intent, text) để tránh gọi LLM lại cho cùng input.
    """

    def __init__(self):
        self._llm = None
        self._cache: dict[str, dict] = {}

    def _get_llm(self):
        if self._llm is None:
            import os
            from langchain_aws import ChatBedrockConverse
            model = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
            region = os.getenv("BEDROCK_REGION", "ap-southeast-1")
            try:
                self._llm = ChatBedrockConverse(
                    model=model,
                    region_name=region,
                    temperature=0.0,
                    max_tokens=200,
                )
            except Exception as e:
                logger.error("[ENTITY_EXTRACTOR] Không thể init LLM: %s", e)
        return self._llm

    async def _llm_extract(self, text: str) -> dict:
        """Dùng LLM để extract product_name, category, destination."""
        # Cache check
        cache_key = f"entity:{hash(text)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        llm = self._get_llm()
        if llm is None:
            return {}

        from langchain_core.messages import HumanMessage
        prompt = _EXTRACT_PROMPT.format(message=text)
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in raw
                )

            # Parse JSON
            raw = raw.strip()
            # Strip markdown code block nếu LLM trả về
            if raw.startswith("```"):
                raw = re.sub(r"```(?:json)?", "", raw).strip("`").strip()

            result = json.loads(raw) if raw and raw != "{}" else {}
            self._cache[cache_key] = result
            return result

        except Exception as e:
            logger.warning("[ENTITY_EXTRACTOR] LLM extract error: %s", e)
            return {}

    def _resolve_positional_reference(self, text: str, state: "ShoppingState") -> dict | None:
        """
        Kiểm tra text có phải positional reference (cái thứ 2) không.
        Nếu có, resolve từ candidate_products trong state.
        """
        for pattern in _REFERENCE_PATTERNS:
            m = pattern.search(text)
            if m:
                candidates = state.get("candidate_products", [])
                if not candidates:
                    logger.info("[ENTITY] Positional reference but no candidate_products in state")
                    return None

                # Xác định index
                raw = m.group(3) if m.lastindex >= 3 else m.group(2)
                idx = _ORDINAL_MAP.get(raw.lower())
                if idx is None:
                    try:
                        idx = int(raw)
                    except ValueError:
                        return None

                if idx < 1 or idx > len(candidates):
                    logger.info("[ENTITY] Positional index %d out of range (1-%d)", idx, len(candidates))
                    return None

                product = candidates[idx - 1]
                name = product.get("name") or product.get("product_name", "")
                if name:
                    logger.info("[ENTITY] Resolved positional ref #%d → '%s'", idx, name)
                    return {"product_name": name}
        return None

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        messages = state.get("messages", [])
        intent = state.get("intent", "agent")

        if not messages:
            return {
                "entities": {},
                "node_durations": {"EntityExtractor": 0},
            }

        last_msg = messages[-1]
        text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        entities: dict = {}

        # 0. Multi-turn positional reference (trước regex để ưu tiên)
        ref_result = self._resolve_positional_reference(text, state)
        if ref_result:
            entities.update(ref_result)

        # 1. Regex pre-extract (nhanh)
        entities.update(_regex_preextract(text))

        # 2. LLM extract product_name, category, destination
        # Chỉ gọi LLM nếu intent cần product_name và chưa có từ positional reference
        needs_product = intent in ("search", "review", "recommend", "cart", "shipping")
        if needs_product and "product_name" not in entities:
            llm_entities = await self._llm_extract(text)
            for k, v in llm_entities.items():
                if k not in entities:
                    entities[k] = v

        # Đảm bảo quantity mặc định = 1 nếu intent là cart
        if intent == "cart" and "quantity" not in entities:
            entities["quantity"] = 1

        ms = (time.monotonic_ns() - t0) // 1_000_000
        logger.info(
            "[ENTITY_EXTRACTOR] intent=%s | entities=%s | %dms",
            intent, list(entities.keys()), ms
        )

        return {
            "entities": entities,
            "node_durations": {"EntityExtractor": ms},
        }
