import asyncio
import os
import re
import sqlite3
from pathlib import Path
import boto3
from typing import List, Optional

from src.database.connect import get_conn, init_pool
from src.tools.search.models import Money, Product, SearchQuery, ScoredProduct, SearchStrategy


class BedrockRAGStrategy(SearchStrategy):
    """
    Query AWS Bedrock Knowledge Base to perform semantic vector search on products.
    Requires BEDROCK_KB_ID to be set in environment variables.
    """

    _name = "bedrock_rag"

    def __init__(self):
        pass

    @property
    def kb_id(self) -> Optional[str]:
        return os.environ.get("BEDROCK_KB_ID")

    @property
    def region(self) -> str:
        return os.environ.get("BEDROCK_KB_REGION", "us-east-1")

    @property
    def name(self) -> str:
        return self._name

    def should_run(self, sq: SearchQuery) -> bool:
        """Only run if BEDROCK_KB_ID is configured in the environment."""
        return bool(self.kb_id)

    async def search(self, sq: SearchQuery) -> List[ScoredProduct]:
        kb_id = self.kb_id
        if not kb_id:
            return []

        print(f"\n[RAG] Kich hoat Bedrock RAG tim kiem ngu nghia cho: '{sq.raw}' (Region: {self.region}, KB_ID: {kb_id})")
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, self._query_kb, sq.raw)
            print(f"[RAG] Tim thay {len(results)} san pham phu hop tu Vector KB.")
            return results
        except Exception as e:
            print(f"[RAG] Loi BedrockRAGStrategy: {e}")
            return []

    def _query_kb(self, query_text: str) -> List[ScoredProduct]:
        kb_id = self.kb_id
        region = self.region

        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
        client = session.client("bedrock-agent-runtime", region_name=region)

        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={
                'text': query_text
            },
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': 5
                }
            }
        )

        scored_products = []
        retrieved_results = response.get("retrievalResults", [])

        id_pattern = re.compile(r"Product\s+ID:\s*([A-Z0-9]{10})", re.IGNORECASE)

        for res in retrieved_results:
            text = res.get("content", {}).get("text", "")
            score = res.get("score", 0.8)

            match = id_pattern.search(text)
            if match:
                product_id = match.group(1)
                product = self._resolve_product_details(product_id, text)
                scored_products.append(ScoredProduct(
                    product=product,
                    score=score * 100,
                    strategy_name=self.name
                ))

        return scored_products

    def _resolve_product_details(self, product_id: str, chunk_text: str) -> Product:
        try:
            init_pool()
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name, description, categories, price_units, price_nanos FROM products WHERE id = %s",
                    (product_id,)
                )
                row = cur.fetchone()
                if row:
                    cats = [c.strip() for c in row[2].split(",") if c.strip()] if row[2] else []
                    return Product(
                        id=product_id,
                        name=row[0],
                        description=row[1] or "",
                        categories=cats,
                        price_usd=Money(units=row[3] if row[3] is not None else 0,
                                        nanos=row[4] if row[4] is not None else 0)
                    )
        except Exception:
            pass

        try:
            candidates = []
            file_path = Path(__file__).resolve()
            for base in [file_path.parents[4], file_path.parents[3], file_path.parents[2], file_path.parents[1], Path.cwd()]:
                candidates.append(base / "server-test" / "shopping.db")
                candidates.append(base / "shopping.db")
            db_path = None
            for candidate in candidates:
                if candidate.exists():
                    db_path = candidate
                    break
            if db_path:
                conn = sqlite3.connect(str(db_path))
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT name, description, categories, price_units, price_nanos FROM products WHERE id = ?",
                        (product_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        cats = [c.strip() for c in row[2].split(",") if c.strip()] if row[2] else []
                        return Product(
                            id=product_id,
                            name=row[0],
                            description=row[1] or "",
                            categories=cats,
                            price_usd=Money(units=row[3] if row[3] is not None else 0,
                                            nanos=row[4] if row[4] is not None else 0)
                        )
                finally:
                    conn.close()
        except Exception:
            pass

        name_match = re.search(r"Product\s+Name:\s*(.*)", chunk_text, re.IGNORECASE)
        price_match = re.search(r"Price:\s*(\d+)", chunk_text, re.IGNORECASE)
        cat_match = re.search(r"Category:\s*(.*)", chunk_text, re.IGNORECASE)

        name = name_match.group(1).strip() if name_match else f"Product {product_id}"
        price = int(price_match.group(1).strip()) if price_match else 0
        categories = [c.strip() for c in cat_match.group(1).split(",") if c.strip()] if cat_match else []

        return Product(
            id=product_id,
            name=name,
            description=chunk_text[:200],
            categories=categories,
            price_usd=Money(units=price)
        )
