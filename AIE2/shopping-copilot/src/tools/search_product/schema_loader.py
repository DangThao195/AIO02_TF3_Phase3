import json
import os


class SchemaLoader:
    def __init__(self):
        self.schema_path = os.path.join(os.path.dirname(__file__), "schema.json")

    def load(self) -> dict:
        if os.path.exists(self.schema_path):
            with open(self.schema_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"tables": []}

    def to_prompt_text(self) -> str:
        schema = self.load()
        lines = []
        for t in schema.get("tables", []):
            cols = ", ".join(t.get("columns", []))
            lines.append(f"Table: {t.get('name')} ({cols})")
        return "\n".join(lines)
