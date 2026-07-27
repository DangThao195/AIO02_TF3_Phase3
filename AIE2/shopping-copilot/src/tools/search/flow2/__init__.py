from src.tools.search.flow2.kb_client import BedrockRAGStrategy

class Flow2RAG:
    """
    Wrapper của Flow 2 (RAG) để tuân thủ thiết kế search_design.md.
    """
    @staticmethod
    async def run(sq):
        strategy = BedrockRAGStrategy()
        if strategy.should_run(sq):
            return await strategy.search(sq)
        return []
