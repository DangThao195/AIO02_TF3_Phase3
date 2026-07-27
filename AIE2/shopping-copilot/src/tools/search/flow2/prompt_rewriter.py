from src.llm.llm import get_llm_client
from src.llm.prompt import REWRITE_SEARCH_QUERY_PROMPT


class PromptRewriter:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client or get_llm_client()

    def rewrite(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return ""

        prompt = REWRITE_SEARCH_QUERY_PROMPT.format(query=query)
        try:
            response = self.llm_client.invoke(prompt, temperature=0.3, max_tokens=256)
            rewritten = (response.content or "").strip()
            return rewritten if rewritten else query
        except Exception:
            return query
