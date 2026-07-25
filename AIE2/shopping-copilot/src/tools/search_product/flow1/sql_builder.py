from typing import Any, Dict, List


class SQLBuilder:
    """Xây dựng câu lệnh SQL từ entities đã trích xuất."""

    def __init__(self, field_rules: Dict[str, Dict[str, Any]] | None = None):
        self.base_table = "products"
        self.field_rules = field_rules or {
            "category": {"column": "categories", "op": "like"},
            "price_max": {"column": "price_units", "op": "<="},
            "price_min": {"column": "price_units", "op": ">="},
            "keywords": {"column": ["name", "description", "categories"], "op": "contains"},
        }

    def build(self, entities: Dict[str, Any]) -> str:
        if entities.get("intent") == "category_listing":
            return self.build_category_listing()

        select_columns = ["id", "name", "description", "categories", "price_units", "price_nanos"]
        where_clauses: List[str] = []

        for field_name, rule in self.field_rules.items():
            value = entities.get(field_name)
            if value in (None, ""):
                continue
            if not isinstance(value, (list, tuple, set)):
                value = [value]
            clause = self._build_clause(field_name, rule, value)
            if clause:
                where_clauses.append(clause)

        query = f"SELECT {', '.join(select_columns)} FROM {self.base_table}"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY price_units ASC LIMIT 15"
        return query

    def build_category_listing(self) -> str:
        return "SELECT DISTINCT categories FROM products WHERE categories IS NOT NULL AND categories != '' ORDER BY categories"

    def _build_clause(self, field_name: str, rule: Dict[str, Any], value: List[Any]) -> str | None:
        column = rule.get("column")
        op = rule.get("op")
        if op == "like":
            if isinstance(column, list):
                return None
            val = str(value[0]).lower().rstrip("s")
            return self._like_clause(column, val)
        if op == "<=":
            if isinstance(column, list):
                return None
            return f"{column} <= {int(value[0])}"
        if op == ">=":
            if isinstance(column, list):
                return None
            return f"{column} >= {int(value[0])}"
        if op == "contains":
            columns = column if isinstance(column, list) else [column]
            _VI_EN_MAP = {
                "kính thiên văn": "telescope",
                "kinh thien van": "telescope",
                "kính khúc xạ": "refractor telescope",
                "phụ kiện thiên văn": "astronomy accessory",
                "phụ kiện": "accessory",
                "đèn pin": "flashlight",
                "bộ vệ sinh": "cleaning kit",
                "sách": "book",
            }
            # Collect all individual word tokens from all keywords
            word_tokens = []
            for keyword in value:
                kw_str = str(keyword).lower()
                for vi_term, en_term in _VI_EN_MAP.items():
                    if vi_term in kw_str:
                        kw_str = kw_str.replace(vi_term, en_term)
                for word in kw_str.split():
                    w_clean = self._escape_value(word.strip())
                    if len(w_clean) > 2 and w_clean not in word_tokens:
                        word_tokens.append(w_clean)
            if not word_tokens:
                word_tokens = [self._escape_value(str(v).lower()) for v in value]

            # Require each word token to match in at least one column (AND logic across words)
            token_clauses = []
            for token in word_tokens:
                column_terms = [f"lower({col}) LIKE '%{token}%'" for col in columns]
                token_clauses.append(f"({' OR '.join(column_terms)})")
            return " AND ".join(token_clauses)
        return None

    def _like_clause(self, column: str, value: str) -> str:
        return f"lower({column}) LIKE '%{self._escape_value(value)}%'"

    def _escape_value(self, value: str) -> str:
        return str(value).replace("'", "''")
