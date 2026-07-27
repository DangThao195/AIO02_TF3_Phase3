import json
from pathlib import Path
from typing import Dict, List, Optional


class SchemaLoader:
    def __init__(self, schema_path: Optional[str] = None):
        if schema_path is None:
            schema_path = str(Path(__file__).parent / "schema.json")
        self.schema_path = schema_path
        self._schema: Optional[dict] = None

    def load(self) -> dict:
        if self._schema is not None:
            return self._schema
        with open(self.schema_path, encoding="utf-8") as f:
            self._schema = json.load(f)
        return self._schema

    def to_prompt_text(self) -> str:
        schema = self.load()
        lines: List[str] = []
        for table in schema.get("tables", []):
            lines.append(f"Table: {table['name']}")
            if table.get("description"):
                lines.append(f"  Description: {table['description']}")
            for col in table.get("columns", []):
                col_type = col.get("type", "")
                col_desc = col.get("description", "")
                example = col.get("example")
                line = f"  - {col['name']} ({col_type}): {col_desc}"
                if example is not None:
                    line += f" (VD: {example})"
                if col.get("primary_key"):
                    line += " [PRIMARY KEY]"
                if col.get("foreign_key"):
                    line += f" [FK → {col['foreign_key']}]"
                lines.append(line)
            cat_vals = table.get("category_values")
            if cat_vals:
                lines.append(f"  Category values: {', '.join(cat_vals)}")
            lines.append("")
        return "\n".join(lines)

    def get_column_names(self, table_name: str) -> List[str]:
        schema = self.load()
        for table in schema.get("tables", []):
            if table["name"] == table_name:
                return [col["name"] for col in table.get("columns", [])]
        return []
