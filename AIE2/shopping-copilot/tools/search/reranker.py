# tools/search/reranker.py
"""
LLM-based reranking (optional, chỉ chạy khi cần).
Trigger: pool > 5 products AND query phức tạp (multi-intent).
"""

import json
from typing import List, Optional
from llm.llm import llm_model
from tools.search.models import SearchQuery, ScoredProduct


class LLMReranker:
    """Dùng LLM để rerank top products dựa trên query intent."""

    async def rerank(
        self,
        products: List[ScoredProduct],
        sq: SearchQuery
    ) -> List[ScoredProduct]:
        """
        Rerank top products. 
        Input: max 15 products. 
        Output: same list reordered theo LLM judgment.
        """
        if len(products) <= 1:
            return products

        # Format products cho LLM
        product_lines = [
            f"{i+1}. {p.product.name} — ${p.product.price_usd.units} — "
            f"Categories: {', '.join(p.product.categories)} — "
            f"Description: {p.product.description[:50]}..."
            for i, p in enumerate(products)
        ]

        # Build price range string
        price_range_str = "no filter"
        if sq.has_price_filter:
            if sq.price_min and sq.price_max:
                price_range_str = f"${sq.price_min} - ${sq.price_max}"
            elif sq.price_min:
                price_range_str = f">${sq.price_min}"
            elif sq.price_max:
                price_range_str = f"<${sq.price_max}"

        # Call LLM
        response = llm_model.invoke(f"""
You are a product ranking assistant for an astronomy equipment store.
Given a user's shopping query and a list of products, re-rank them by relevance.

Ranking rules:
- Consider: keyword match, price fit, category match, user intent
- Output ONLY a comma-separated list of product numbers (1-based) in new order
- If unclear, keep original order
- Example output: "3,1,2,5,4"

User query: "{sq.raw}"
Price range: {price_range_str}
Category: {sq.category or 'any'}
Intent: {sq.intent}

Products to rank:
{chr(10).join(product_lines)}

Reranked order (comma-separated numbers):
""")

        # Parse LLM output
        try:
            output = response.content if hasattr(response, 'content') else str(response)
            # Extract numbers
            indices = []
            for part in output.strip().split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1  # Convert to 0-based
                    if 0 <= idx < len(products):
                        indices.append(idx)

            # Build reranked list
            reranked = []
            seen = set()
            for idx in indices:
                if idx not in seen:
                    reranked.append(products[idx])
                    seen.add(idx)

            # Append any missing products (fallback)
            for i, p in enumerate(products):
                if i not in seen:
                    reranked.append(p)

            return reranked
        except (ValueError, AttributeError, IndexError) as e:
            print(f"LLMReranker parse error: {e}. Keeping original order.")
            # Fallback: return original order
            return products
