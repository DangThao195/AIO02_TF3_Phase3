import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency
    fuzz = None

from src.llm.llm import get_llm_client


class EntityExtractor:
    """Trích xuất thực thể từ câu hỏi bằng LLM hoặc heuristic fallback."""

    _STOP_WORDS = {
        "tìm", "tim", "của", "cua", "cho", "for", "the", "a", "an", "và", "va", "and", "or",
        "dưới", "duoi", "under", "từ", "tu", "from", "giữa", "giua", "between", "range",
        "sản", "san", "phẩm", "pham", "item", "items", "product", "products", "show", "look",
        "cheap", "affordable", "best", "good", "mới", "moi", "new"
    }

    def __init__(self, llm_client=None):
        self.llm_client = llm_client or get_llm_client()

    def extract(self, query: str) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"category": None, "price_max": None, "price_min": None, "keywords": []}

        entities = self._heuristic_extract(query)

        if os.getenv("SKIP_LLM_SQL_FLOW", "0") == "1":
            return entities

        try:
            response = self.llm_client.invoke(
                self._build_prompt(query),
                temperature=0.0,
                max_tokens=300,
            )
            if response and getattr(response, "content", ""):
                data = self._parse_response(response.content)
                if data:
                    return self._merge(entities, data)
        except Exception:
            pass

        return entities

    def _heuristic_extract(self, query: str) -> Dict[str, Any]:
        lowered = query.lower()
        entities: Dict[str, Any] = {
            "category": None,
            "price_max": None,
            "price_min": None,
            "keywords": [],
            "sort": "relevance",
        }

        entities["category"] = self._infer_category(query)

        price_matches = re.findall(r"(\d+)", query)
        if price_matches:
            if any(token in lowered for token in ["dưới", "duoi", "nhỏ hơn", "nho hon", "<", "under", "less than", "max", "below"]):
                entities["price_max"] = int(price_matches[0])
            elif any(token in lowered for token in ["từ", "tu", "between", "range", "giữa", "giua"]):
                if len(price_matches) >= 2:
                    entities["price_min"] = int(price_matches[0])
                    entities["price_max"] = int(price_matches[1])
                else:
                    entities["price_max"] = int(price_matches[0])
            else:
                entities["price_max"] = int(price_matches[0])

        catalog_hints = self._get_catalog_category_hints()
        tokens = re.findall(r"[a-zA-ZÀ-ỹ0-9]+", query.lower())
        keywords = []
        for token in tokens:
            normalized = re.sub(r"[^a-z0-9]+", "", token)
            if len(normalized) <= 2:
                continue
            if normalized in self._STOP_WORDS:
                continue
            if normalized in catalog_hints:
                continue
            keywords.append(normalized)
        entities["keywords"] = list(dict.fromkeys(keywords))
        return entities

    def _infer_category(self, query: str) -> str | None:
        normalized = re.sub(r"[^a-z0-9]+", "", query.lower())
        catalog_hints = self._get_catalog_category_hints()
        for normalized_hint, original_hint in catalog_hints.items():
            if normalized_hint in normalized:
                return original_hint
        for token in re.findall(r"[a-zA-ZÀ-ỹ0-9]+", query.lower()):
            cleaned = re.sub(r"[^a-z0-9]+", "", token)
            if cleaned in catalog_hints:
                return catalog_hints[cleaned]

        if not catalog_hints:
            return None

        query_tokens = [re.sub(r"[^a-z0-9]+", "", t.lower()) for t in re.findall(r"[a-zA-ZÀ-ỹ0-9]+", query.lower()) if re.sub(r"[^a-z0-9]+", "", t.lower())]
        if not query_tokens:
            return None

        best_match = None
        best_score = 0.0
        for normalized_hint, original_hint in catalog_hints.items():
            for token in query_tokens:
                if fuzz is not None:
                    score = fuzz.ratio(normalized_hint, token)
                else:
                    score = 0.0
                    if normalized_hint == token:
                        score = 100.0
                    elif normalized_hint.startswith(token) or token.startswith(normalized_hint):
                        score = 80.0
                if score > best_score:
                    best_score = score
                    best_match = original_hint
            if best_score >= 80.0:
                break
        if best_score >= 80.0:
            return best_match
        return None

    def _get_catalog_category_hints(self) -> Dict[str, str]:
        hints: Dict[str, str] = {}
        db_path = os.getenv("SHOPPING_DB_PATH")
        if not db_path:
            candidates = []
            base = Path(__file__).resolve()
            for parent in [base.parents[4], base.parents[3], base.parents[2], base.parents[1], Path.cwd()]:
                candidates.append(parent / "server-test" / "shopping.db")
                candidates.append(parent / "shopping.db")
            for candidate in candidates:
                if candidate.exists():
                    db_path = str(candidate)
                    break
        if not db_path:
            return hints

        try:
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.execute("SELECT DISTINCT categories FROM products")
                for (raw_categories,) in cur.fetchall():
                    if not raw_categories:
                        continue
                    for part in str(raw_categories).split(","):
                        cleaned = re.sub(r"[^a-z0-9]+", "", part.lower()).strip()
                        original = part.strip()
                        if cleaned and cleaned not in hints:
                            hints[cleaned] = original
            finally:
                conn.close()
        except Exception:
            return hints
        return hints

    def _build_prompt(self, query: str) -> str:
        return (
            "Bạn là trợ lý sinh SQL cho cửa hàng. Trả về JSON với các khóa: "
            "category, price_max, price_min, keywords, sort. "
            f"Câu hỏi: {query}. "
            "Nếu không rõ, dùng null hoặc []"
        )

    def _parse_response(self, content: str) -> Dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            parsed = json.loads(cleaned)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _merge(self, base: Dict[str, Any], llm_data: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key in ["category", "price_max", "price_min", "sort"]:
            if llm_data.get(key) not in (None, ""):
                merged[key] = llm_data[key]
        if llm_data.get("keywords"):
            merged["keywords"] = list(dict.fromkeys(base.get("keywords", []) + llm_data.get("keywords", [])))
        return merged
