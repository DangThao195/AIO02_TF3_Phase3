import asyncio
from typing import List, Optional

from src.tools.search_product.flow1 import Flow1SQL
from src.tools.search_product.flow2 import Flow2RAG
from src.tools.search_product.models import Money, Product, ScoredProduct, SearchQuery, SearchResult
from src.tools.search_product.reranker import Reranker
from src.tools.search_product.schema_loader import SchemaLoader
from src.tools.search_product.tracer import SearchTracer


class SearchOrchestrator:
    def __init__(self):
        self.schema_loader = SchemaLoader()
        self.flow1 = Flow1SQL()
        self.flow2 = Flow2RAG()
        self.reranker = Reranker()

    async def search(self, query: str, tracer: Optional[SearchTracer] = None) -> SearchResult:
        if tracer is None:
            tracer = SearchTracer()
        query = (query or "").strip()
        if not query:
            return SearchResult(query="", error="Query is empty")

        s_schema = tracer.time("SchemaLoader")
        schema_context = self.schema_loader.to_prompt_text()
        num_tables = schema_context.count("Table:")
        tracer.end(s_schema, "ok", f"Loaded {num_tables} tables from schema")

        sql_start = tracer.time("Flow1: SQL Matching")
        flow1_result = await self.flow1.run(query)
        intent = flow1_result.get("intent", "product_search")

        if intent == "category_listing":
            categories = flow1_result.get("categories", [])
            if categories:
                tracer.end(sql_start, "ok", f"Category listing: {len(categories)} categories")
            else:
                tracer.end(sql_start, "skip", "No categories found")
            return SearchResult(
                query=query,
                categories=categories,
                flows_used=["sql"],
            )

        sql_products = self._process_flow1_result(flow1_result, tracer)
        tracer.end(sql_start, "ok", f"Flow 1 completed: {len(sql_products)} products")

        rag_start = tracer.time("Flow2: Product RAG")
        rag_task = asyncio.create_task(self._run_flow2(query, tracer, rag_start))
        rag_results = await rag_task

        rag_products: List[ScoredProduct] = []
        if isinstance(rag_results, list):
            rag_products = rag_results

        s_r = tracer.time("Reranker")
        if not sql_products and not rag_products:
            tracer.end(s_r, "skip", "No results from either flow")
            return SearchResult(
                query=query,
                error="Không tìm thấy sản phẩm phù hợp.",
                flows_used=[],
            )

        result = self.reranker.rerank(sql_products, rag_products, query=query)
        tracer.end(s_r, "ok",
            f"Merged {len(sql_products)} SQL + {len(rag_products)} RAG = "
            f"{len(result.products)} after dedup, top={result.rerank_mode}"
        )

        result._tracer = tracer
        return result

    def _process_flow1_result(self, flow1_result: dict, tracer: SearchTracer) -> List[ScoredProduct]:
        products: List[ScoredProduct] = []
        for r in flow1_result.get("results", []):
            try:
                product = Product(
                    id=str(r.get("id", "")),
                    name=str(r.get("name", "")),
                    description=str(r.get("description", "")),
                    categories=list(r.get("categories", [])),
                    price_usd=Money(units=int(r.get("price_units", 0))),
                )
                products.append(ScoredProduct(product=product, score=0.0, source="sql", strategy_name="sql_matching"))
            except Exception:
                continue
        return products

    async def _run_flow2(self, query: str, tracer: SearchTracer, flow_start: tuple) -> List[ScoredProduct]:
        try:
            from src.tools.search_product.flow2.prompt_rewriter import PromptRewriter
            s_rw = tracer.time("PromptRewriter")
            rewriter = PromptRewriter()
            rewritten = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, rewriter.rewrite, query),
                timeout=3.0
            )
            if rewritten and rewritten != query:
                tracer.end(s_rw, "ok", f"Rewritten: {rewritten[:200]}")
            else:
                tracer.end(s_rw, "skip", "No rewrite needed")

            s_kb = tracer.time("KB Query (Product DS)")
            sq = SearchQuery(raw=query)
            results = await asyncio.wait_for(self.flow2.run(sq), timeout=5.0)
            if not results:
                tracer.end(s_kb, "skip", "No KB results (BEDROCK_KB_ID not set or empty)")
                tracer.end(flow_start, "skip", "Flow 2 skipped: no KB")
                return []
            for sp in results:
                sp.source = sp.source or "rag"
                if not sp.strategy_name:
                    sp.strategy_name = "bedrock_product_rag"
            tracer.end(s_kb, "ok", f"Found {len(results)} products from Product KB")
            tracer.end(flow_start, "ok", f"Flow 2 completed: {len(results)} products")
            return results
        except asyncio.TimeoutError:
            tracer.end(flow_start, "error", "Timed out after 5s")
            return []
        except Exception as e:
            tracer.end(flow_start, "error", str(e)[:150])
            return []
