"""
graph/nodes/intent_classifier.py — IntentClassifier node.

Phân loại intent từ tin nhắn user:
1. Regex patterns trước (nhanh, deterministic)
2. LLM fallback nếu không khớp regex (chậm hơn nhưng linh hoạt)

Outputs: state["intent"], state["intent_source"]

Intent values:
  search    — tìm kiếm sản phẩm
  review    — xem đánh giá sản phẩm
  recommend — gợi ý sản phẩm
  cart      — thêm vào giỏ / xem giỏ hàng
  shipping  — vận chuyển / phí ship / quy đổi tiền tệ
  sequential — nhiều nghiệp vụ trong 1 câu
  agent     — fallback (không khớp hoặc câu mở)
"""

from __future__ import annotations

import re
import json
import time
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.state import ShoppingState

logger = logging.getLogger("graph.nodes.intent_classifier")


# ──────────────────────────────────────────────────────────────────
# Regex patterns (ưu tiên thứ tự)
# ──────────────────────────────────────────────────────────────────

# Mỗi intent có list of patterns, match bất kỳ → set intent
# Patterns cho câu hỏi tổng quan (không phải search cụ thể) — route về AgentWorkflow
# để LLM tự quyết định gọi get_categories / get_all_products
_AGENT_PATTERNS = [
    re.compile(r"\b(bạn có|có sản phẩm|bán những|có những)\b.*(gì|nào|không)\b", re.IGNORECASE),
    re.compile(r"\b(có sản phẩm|sản phẩm gì|những gì)\b", re.IGNORECASE),
    re.compile(r"\b(bán|sell|list).*(gì|nào|what)\b", re.IGNORECASE),
]

# Patterns cho multi-turn reference (cái thứ 2, sản phẩm đầu tiên, cái tiếp theo)
# Route về search để EntityExtractor resolve từ candidate_products
_REFERENCE_PATTERNS = [
    re.compile(r"\b(cái|sản phẩm|item|product)\s+(thứ|số|so|num|number)\s*(\d+|nhất|hai|ba|tư|năm)\b", re.IGNORECASE),
    re.compile(r"\b(cái|sản phẩm|item)\s+(đầu tiên|first|second|third|tiếp theo|cuối cùng|last|next)\b", re.IGNORECASE),
    re.compile(r"\b(thứ|số)\s*(\d+|nhất|hai|ba|tư|năm)\s*(cái|sản phẩm|item)\b", re.IGNORECASE),
]

_RANK_REFERENCE_PATTERNS = [
    re.compile(r"\b(cái nào|sản phẩm nào|item nào|product nào).*(rẻ nhất|cheapest|lowest price|đắt nhất|most expensive|highest price)\b", re.IGNORECASE),
    re.compile(r"\b(rẻ nhất|cheapest|lowest price|đắt nhất|most expensive|highest price)\b", re.IGNORECASE),
]

_INTENT_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("cart", [
        re.compile(r"\b(thêm|add|cho|bỏ|đặt|order|mua|mua ngay)\b.*(vào|into|to)?.*(giỏ|cart|basket|túi)", re.IGNORECASE),
        re.compile(r"\b(xem|kiểm tra|check).*(giỏ|cart)\b", re.IGNORECASE),
        re.compile(r"\bgiỏ hàng\b", re.IGNORECASE),
        re.compile(r"\badd to cart\b", re.IGNORECASE),
    ]),
    ("review", [
        re.compile(r"\b(review|đánh giá|nhận xét|feedback|rating|đánh giá|bình luận|danh gia)\b", re.IGNORECASE),
        re.compile(r"\b(khách hàng|người dùng).*(nghĩ|nói|đánh giá)\b", re.IGNORECASE),
        re.compile(r"\b(có tốt không|có đáng mua không|chất lượng thế nào)\b", re.IGNORECASE),
    ]),
    ("recommend", [
        re.compile(r"\b(gợi ý|recommend|đề xuất|suggest|tương tự|similar|like this|related)\b", re.IGNORECASE),
        re.compile(r"\b(sản phẩm nào|cái nào|loại nào).*(tốt|phù hợp|nên)\b", re.IGNORECASE),
        re.compile(r"\bnên mua (gì|cái gì|loại nào)\b", re.IGNORECASE),
    ]),
    ("shipping", [
        re.compile(r"\b(giao hàng|ship|vận chuyển|delivery|shipping|phí ship|phí giao)\b", re.IGNORECASE),
        re.compile(r"\b(quy đổi|convert|tiền tệ|currency|USD|VND|EUR|đô|đồng)\b", re.IGNORECASE),
        re.compile(r"\b(phí|fee|cost).*(ship|giao|delivery)\b", re.IGNORECASE),
    ]),
    ("search", [
        re.compile(r"\b(tìm|search|tìm kiếm|tra|lookup|find|show me|cho tôi xem)\b", re.IGNORECASE),
        re.compile(r"\b(có bán|có không|còn không|available|in stock)\b", re.IGNORECASE),
        re.compile(r"\b(giá|price|bao nhiêu|how much|cost)\b.*(của|của sản phẩm|product)?\b", re.IGNORECASE),
        re.compile(r"\b(danh mục|category|categories|loại sản phẩm)\b", re.IGNORECASE),
        re.compile(r"\b(sản phẩm nào|product).*(dưới|under|trên|above|từ|between)\b", re.IGNORECASE),
    ]),
]

# Pattern phát hiện "sequential" (nhiều intent trong 1 câu)
_SEQUENTIAL_PATTERNS = [
    re.compile(r"\b(và|and|rồi|then|sau đó|also|ngoài ra)\b", re.IGNORECASE),
    re.compile(r"\b(vừa|both|đồng thời)\b", re.IGNORECASE),
]

# Ngưỡng để gọi LLM fallback
_LLM_FALLBACK_MIN_LENGTH = 5  # Câu quá ngắn → agent


# ──────────────────────────────────────────────────────────────────
# LLM fallback prompt
# ──────────────────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """\
Phân loại ý định (intent) của câu hỏi mua sắm sau đây.
Chỉ trả về 1 trong các giá trị: search, review, recommend, cart, shipping, sequential, agent
Không giải thích, không thêm nội dung khác.

Định nghĩa:
- search: tìm kiếm, hỏi giá, xem danh mục
- review: xem đánh giá, nhận xét sản phẩm
- recommend: gợi ý sản phẩm tương tự
- cart: thêm/xem giỏ hàng
- shipping: hỏi phí giao hàng, quy đổi tiền tệ
- sequential: câu chứa nhiều ý định cùng lúc
- agent: câu chào hỏi, trò chuyện, không liên quan mua sắm

Câu hỏi: {message}
Intent:"""


# ──────────────────────────────────────────────────────────────────
# IntentClassifier node
# ──────────────────────────────────────────────────────────────────

class IntentClassifier:
    """
    Node phân loại intent.

    Thứ tự ưu tiên:
    1. Regex match → nhanh, không tốn token
    2. LLM fallback → khi regex không khớp và câu đủ dài
    3. Default "agent" → khi câu quá ngắn hoặc LLM lỗi
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        """Lazy init Bedrock LLM (không bind tools — chỉ classify)."""
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
                    max_tokens=16,
                )
            except Exception as e:
                logger.error("[INTENT_CLASSIFIER] Không thể init LLM: %s", e)
                self._llm = None
        return self._llm

    def _regex_classify(self, text: str) -> Optional[str]:
        """
        Thử khớp regex với tất cả patterns.
        Kiểm tra sequential trước nếu khớp nhiều intent.
        """
        # Kiểm tra agent patterns trước (câu hỏi tổng quan)
        is_agent_query = any(p.search(text) for p in _AGENT_PATTERNS)

        # Kiểm tra reference patterns (multi-turn: "cái thứ 2")
        is_reference = any(p.search(text) for p in _REFERENCE_PATTERNS)
        is_rank_reference = any(p.search(text) for p in _RANK_REFERENCE_PATTERNS)

        matched_intents = []
        for intent, patterns in _INTENT_PATTERNS:
            if any(p.search(text) for p in patterns):
                matched_intents.append(intent)

        if len(matched_intents) >= 2:
            if any(p.search(text) for p in _SEQUENTIAL_PATTERNS):
                return "sequential"
            return matched_intents[0]
        elif len(matched_intents) == 1:
            return matched_intents[0]

        # Multi-turn reference → search (EntityExtractor sẽ resolve từ candidate_products)
        if is_reference:
            return "search"

        # Rank reference ("cái nào rẻ nhất", "đắt nhất") → search để chọn từ candidate_products
        if is_rank_reference:
            return "search"

        # Không khớp intent cụ thể → agent nếu là câu hỏi tổng quan
        if is_agent_query:
            return "agent"

        return None  # Không khớp

    async def _llm_classify(self, text: str) -> str:
        """Gọi LLM để classify intent."""
        llm = self._get_llm()
        if llm is None:
            return "agent"

        from langchain_core.messages import HumanMessage
        prompt = _CLASSIFY_PROMPT.format(message=text)
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in raw
                )
            intent = raw.strip().lower().split()[0] if raw.strip() else "agent"
            valid = {"search", "review", "recommend", "cart", "shipping", "sequential", "agent"}
            return intent if intent in valid else "agent"
        except Exception as e:
            logger.error("[INTENT_CLASSIFIER] LLM classify error: %s", e)
            return "agent"

    async def __call__(self, state: "ShoppingState") -> dict:
        t0 = time.monotonic_ns()

        messages = state.get("messages", [])
        if not messages:
            return {
                "intent": "agent",
                "intent_source": "default",
                "node_durations": {"IntentClassifier": 0},
            }

        last_msg = messages[-1]
        text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        # 1. Regex
        intent = self._regex_classify(text)
        if intent:
            logger.info("[INTENT] Regex match | intent=%s | msg=%.80s", intent, text)
            return {
                "intent": intent,
                "intent_source": "regex",
                "node_durations": {"IntentClassifier": (time.monotonic_ns() - t0) // 1_000_000},
            }

        # 2. LLM fallback nếu câu đủ dài
        if len(text.strip()) >= _LLM_FALLBACK_MIN_LENGTH:
            intent = await self._llm_classify(text)
            logger.info("[INTENT] LLM fallback | intent=%s | msg=%.80s", intent, text)
            return {
                "intent": intent,
                "intent_source": "llm",
                "node_durations": {"IntentClassifier": (time.monotonic_ns() - t0) // 1_000_000},
            }

        # 3. Default
        logger.info("[INTENT] Default agent | msg=%.80s", text)
        return {
            "intent": "agent",
            "intent_source": "default",
            "node_durations": {"IntentClassifier": (time.monotonic_ns() - t0) // 1_000_000},
        }
