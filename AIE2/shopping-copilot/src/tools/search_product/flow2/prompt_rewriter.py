class PromptRewriter:
    def rewrite(self, query: str) -> str:
        return (query or "").strip()
