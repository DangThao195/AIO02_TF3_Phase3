from typing import Any, Dict, List

from src.tools.search.flow1.entity_extractor import EntityExtractor
from src.tools.search.flow1.sql_builder import SQLBuilder
from src.tools.search.flow1.sql_executor import SQLFlowExecutor


class Flow1SQL:
    """Wrapper cho flow1 dùng LLM → SQL → database."""

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.sql_builder = SQLBuilder()
        self.executor = SQLFlowExecutor()

    async def run(self, query: str) -> Dict[str, Any]:
        entities = self.entity_extractor.extract(query)
        intent = entities.get("intent", "product_search")

        if intent == "category_listing":
            categories = self.entity_extractor.get_all_categories()
            return {
                "query": query,
                "entities": entities,
                "intent": "category_listing",
                "categories": categories,
                "sql": "SELECT DISTINCT categories FROM products ...",
                "results": [],
            }

        sql = self.sql_builder.build(entities)
        products = self.executor.execute(sql)
        return {
            "query": query,
            "entities": entities,
            "intent": intent,
            "sql": sql,
            "results": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "categories": p.categories,
                    "price_units": p.price_usd.units,
                    "price_nanos": p.price_usd.nanos,
                }
                for p in products
            ],
        }


# Backward-compatible aliases for existing imports.
class FullCatalogStrategy:
    def __init__(self):
        pass

    def should_run(self, sq):
        return True

    async def search(self, sq):
        return []


class DirectDBStrategy:
    def __init__(self):
        pass

    def should_run(self, sq):
        return True

    async def search(self, sq):
        return []


class SynonymExpansionStrategy:
    def __init__(self):
        pass

    def should_run(self, sq):
        return True

    async def search(self, sq):
        return []
