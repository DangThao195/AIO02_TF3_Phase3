from src.tools.search_product.flow2.kb_client import BedrockRAGStrategy


class Flow2RAG:
    def __init__(self):
        self.rag = BedrockRAGStrategy()

    async def run(self, sq) -> list:
        if not self.rag.should_run(sq):
            return []
        return await self.rag.search(sq)
