import asyncio
import os
import re
import boto3
from typing import List, Optional

from src.tools.search.models import Product, SearchQuery, ScoredProduct, SearchStrategy
import src.protos.demo_pb2 as demo_pb2


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

        print(f"\n[RAG] 🔍 Kích hoạt Bedrock RAG tìm kiếm ngữ nghĩa cho: '{sq.raw}' (Region: {self.region}, KB_ID: {kb_id})")
        try:
            # Run blocking boto3 client calls in asyncio executor to prevent event loop blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, self._query_kb, sq.raw)
            print(f"[RAG] ✅ Tìm thấy {len(results)} sản phẩm phù hợp từ Vector KB.")
            return results
        except Exception as e:
            print(f"❌ [RAG] Lỗi BedrockRAGStrategy: {e}")
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
            score = res.get("score", 0.8) # default score
            
            match = id_pattern.search(text)
            if match:
                product_id = match.group(1)
                
                # Fetch actual live details from SQLite db if available to ensure 100% accuracy
                product = self._resolve_product_details(product_id, text)
                scored_products.append(ScoredProduct(
                    product=product,
                    score=score * 100,  # Scale score to 0-100
                    strategy_name=self.name
                ))
                
        return scored_products

    def _resolve_product_details(self, product_id: str, chunk_text: str) -> Product:
        # Default fallback parsing the chunk text
        name_match = re.search(r"Product\s+Name:\s*(.*)", chunk_text, re.IGNORECASE)
        price_match = re.search(r"Price:\s*(\d+)", chunk_text, re.IGNORECASE)
        cat_match = re.search(r"Category:\s*(.*)", chunk_text, re.IGNORECASE)
        
        name = name_match.group(1).strip() if name_match else f"Product {product_id}"
        price = int(price_match.group(1).strip()) if price_match else 0
        categories = [c.strip() for c in cat_match.group(1).split(",") if c.strip()] if cat_match else []
        
        db_path = os.path.join("server-test", "shopping.db")
        if os.path.exists(db_path):
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name, description, categories, price_units FROM products WHERE id = ?", (product_id,))
                row = cursor.fetchone()
                if row:
                    cats = [c.strip() for c in row[2].split(",") if c.strip()] if row[2] else []
                    return Product(
                        id=product_id,
                        name=row[0],
                        description=row[1] or "",
                        categories=cats,
                        price_usd=demo_pb2.Money(units=row[3] if row[3] is not None else 0)
                    )
            except Exception:
                pass
            finally:
                conn.close()
                
        return Product(
            id=product_id,
            name=name,
            description=chunk_text[:200],
            categories=categories,
            price_usd=demo_pb2.Money(units=price)
        )
