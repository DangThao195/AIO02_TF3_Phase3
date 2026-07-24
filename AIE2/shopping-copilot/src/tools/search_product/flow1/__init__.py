from src.tools.search_product.flow1.entity_extractor import EntityExtractor
from src.tools.search_product.flow1.sql_builder import SQLBuilder
from src.tools.search_product.flow1.sql_executor import SQLFlowExecutor


class Flow1SQL:
    def __init__(self):
        self.extractor = EntityExtractor()
        self.builder = SQLBuilder()
        self.executor = SQLFlowExecutor()

    async def run(self, query: str) -> dict:
        try:
            entities = self.extractor.extract(query)
            intent = entities.get("intent", "product_search")
            if intent == "category_listing":
                categories = self.extractor.get_all_categories()
                return {"intent": "category_listing", "categories": categories, "results": []}

            sql = self.builder.build(entities)
            rows = self.executor.executor.execute(sql)
            return {"intent": "product_search", "entities": entities, "sql": sql, "results": rows}
        except Exception as e:
            return {"intent": "product_search", "error": str(e), "results": []}
