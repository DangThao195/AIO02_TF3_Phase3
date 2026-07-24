import asyncio
import os
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.search_product.flow1 import Flow1SQL


def test_flow1_generates_sql_and_returns_results():
    flow = Flow1SQL()
    result = asyncio.run(flow.run("tìm kính thiên văn dưới 100 đô"))

    assert result["sql"].upper().startswith("SELECT")
    assert result["entities"]["category"] in {"telescopes", None}
    assert isinstance(result["results"], list)


def test_entity_extractor_uses_catalog_values_from_db(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE products (id INTEGER, categories TEXT)")
    conn.execute("INSERT INTO products (id, categories) VALUES (1, 'camping gear')")
    conn.commit()
    conn.close()

    old_env = os.environ.get("SHOPPING_DB_PATH")
    os.environ["SHOPPING_DB_PATH"] = str(db_path)
    try:
        from src.tools.search_product.flow1.entity_extractor import EntityExtractor

        extractor = EntityExtractor()
        entities = extractor.extract("find camping gear under 100")
    finally:
        if old_env is None:
            os.environ.pop("SHOPPING_DB_PATH", None)
        else:
            os.environ["SHOPPING_DB_PATH"] = old_env

    assert entities["category"] in {"camping gear", "camping"}


def test_entity_extractor_uses_fuzzy_matching_for_catalog_variants(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE products (id INTEGER, categories TEXT)")
    conn.execute("INSERT INTO products (id, categories) VALUES (1, 'camping gear')")
    conn.commit()
    conn.close()

    old_env = os.environ.get("SHOPPING_DB_PATH")
    os.environ["SHOPPING_DB_PATH"] = str(db_path)
    try:
        from src.tools.search_product.flow1.entity_extractor import EntityExtractor

        extractor = EntityExtractor()
        entities = extractor.extract("find camping gears under 100")
    finally:
        if old_env is None:
            os.environ.pop("SHOPPING_DB_PATH", None)
        else:
            os.environ["SHOPPING_DB_PATH"] = old_env

    assert entities["category"] == "camping gear"


def test_sql_builder_uses_schema_driven_rules():
    from src.tools.search_product.flow1.sql_builder import SQLBuilder

    builder = SQLBuilder(
        field_rules={
            "custom_category": {"column": "category_name", "op": "like"},
            "price_max": {"column": "price_units", "op": "<="},
        }
    )
    sql = builder.build({"custom_category": "hiking", "price_max": 50})

    assert "category_name" in sql
    assert "price_units" in sql
    assert "hiking" in sql


def test_sql_builder_handles_multiple_clauses_and_ranges():
    from src.tools.search_product.flow1.sql_builder import SQLBuilder

    builder = SQLBuilder(
        field_rules={
            "category": {"column": "categories", "op": "like"},
            "price_min": {"column": "price_units", "op": ">="},
            "price_max": {"column": "price_units", "op": "<="},
            "keywords": {"column": ["name", "description"], "op": "contains"},
        }
    )
    sql = builder.build(
        {
            "category": "hiking",
            "price_min": 20,
            "price_max": 100,
            "keywords": ["waterproof", "lightweight"],
        }
    )

    assert "WHERE" in sql
    assert "categories" in sql
    assert "price_units >= 20" in sql
    assert "price_units <= 100" in sql
    assert "waterproof" in sql
    assert "lightweight" in sql


def test_sql_builder_ignores_empty_values_and_preserves_ordering():
    from src.tools.search_product.flow1.sql_builder import SQLBuilder

    builder = SQLBuilder(
        field_rules={
            "category": {"column": "categories", "op": "like"},
            "price_max": {"column": "price_units", "op": "<="},
        }
    )
    sql = builder.build({"category": "", "price_max": 75, "keywords": []})

    assert "WHERE" in sql
    assert "price_units <= 75" in sql
    assert "ORDER BY price_units ASC" in sql
    assert "LIMIT 15" in sql


def test_entity_extractor_handles_mixed_language_and_long_keywords(tmp_path):
    db_path = tmp_path / "flow1-test.db"

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE products (id INTEGER, categories TEXT)")
    conn.execute("INSERT INTO products (id, categories) VALUES (1, 'outdoor camping')")
    conn.commit()
    conn.close()

    old_env = os.environ.get("SHOPPING_DB_PATH")
    os.environ["SHOPPING_DB_PATH"] = str(db_path)
    try:
        from src.tools.search_product.flow1.entity_extractor import EntityExtractor

        extractor = EntityExtractor()
        entities = extractor.extract("tìm sản phẩm cắm trại ngoài trời dưới 200")
    finally:
        if old_env is None:
            os.environ.pop("SHOPPING_DB_PATH", None)
        else:
            os.environ["SHOPPING_DB_PATH"] = old_env

    assert entities["price_max"] == 200
    assert entities["keywords"]
