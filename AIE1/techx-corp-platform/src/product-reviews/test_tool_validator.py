import pytest
from guardrails.tool_validator import (
    validate_tool_arguments,
    validate_product_id_argument,
)


def test_validate_product_id_valid():
    ok, err = validate_product_id_argument("PROD123_ABC-45")
    assert ok is True
    assert err is None


def test_validate_product_id_invalid_type():
    ok, err = validate_product_id_argument(12345)
    assert ok is False
    assert "must be str" in err


def test_validate_product_id_empty():
    ok, err = validate_product_id_argument("   ")
    assert ok is False
    assert "cannot be empty" in err


def test_validate_product_id_too_long():
    ok, err = validate_product_id_argument("A" * 65)
    assert ok is False
    assert "exceeds max limit 64" in err


def test_validate_product_id_special_chars():
    ok, err = validate_product_id_argument("PROD-123; DROP TABLE reviews;")
    assert ok is False
    assert "invalid characters" in err or "suspicious" in err


def test_validate_product_id_injection_patterns():
    ok, err = validate_product_id_argument("PROD-123<script>alert(1)</script>")
    assert ok is False
    assert "invalid characters" in err or "suspicious" in err


def test_validate_tool_arguments_valid_json():
    raw = '{"product_id": "L9ECAV7KIM", "limit": 10}'
    ok, args, err = validate_tool_arguments(raw)
    assert ok is True
    assert args == {"product_id": "L9ECAV7KIM", "limit": 10}
    assert err is None


def test_validate_tool_arguments_malformed_json():
    raw = '{"product_id": "L9ECAV7KIM", unquoted_key}'
    ok, args, err = validate_tool_arguments(raw)
    assert ok is False
    assert args is None
    assert err == "json_decode_error"


def test_validate_tool_arguments_non_dict_json():
    raw = '["item1", "item2"]'
    ok, args, err = validate_tool_arguments(raw)
    assert ok is False
    assert args is None
    assert err == "non_dict_arguments"


def test_validate_tool_arguments_invalid_product_id():
    raw = '{"product_id": "../etc/passwd"}'
    ok, args, err = validate_tool_arguments(raw)
    assert ok is False
    assert args == {"product_id": "../etc/passwd"}
    assert "invalid_schema" in err
