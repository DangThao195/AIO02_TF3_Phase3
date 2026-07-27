import re
import json
import logging
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger("guardrails.tool_validator")

# Regex for valid product_id: alphanumeric, hyphen, underscore
PRODUCT_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]+$")

# Common malicious pattern keywords
MALICIOUS_PATTERNS = (
    "<script",
    "javascript:",
    "../",
    "..\\",
    "select ",
    "drop ",
    "insert ",
    "delete ",
    "union ",
    "' or '1'='1",
    '" or "1"="1',
)


def validate_product_id_argument(product_id: Any) -> Tuple[bool, Optional[str]]:
    """
    Validates product_id parameter:
    - Must be string
    - Non-empty
    - Length between 1 and 64
    - Alphanumeric with hyphens/underscores only
    - No injection keywords
    """
    if not isinstance(product_id, str):
        return False, f"product_id must be str, got {type(product_id).__name__}"

    stripped = product_id.strip()
    if not stripped:
        return False, "product_id cannot be empty"

    if len(stripped) > 64:
        return False, f"product_id length ({len(stripped)}) exceeds max limit 64"

    if not PRODUCT_ID_REGEX.match(stripped):
        return False, "product_id contains invalid characters (alphanumeric, -, _ allowed)"

    lower_val = stripped.lower()
    for pattern in MALICIOUS_PATTERNS:
        if pattern in lower_val:
            return False, f"product_id contains suspicious/malicious pattern: {pattern.strip()}"

    return True, None


def validate_tool_arguments(raw_arguments: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Parses and validates LLM tool call arguments JSON at the boundary.
    Returns (is_valid, parsed_dict, error_reason).
    """
    if not isinstance(raw_arguments, str):
        logger.warning("[TOOL_VALIDATOR] raw_arguments is not a string")
        return False, None, "invalid_arguments_type"

    try:
        parsed_args = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError, ValueError) as decode_err:
        logger.warning("[TOOL_VALIDATOR] Failed to decode JSON arguments: %s", decode_err)
        return False, None, "json_decode_error"

    if not isinstance(parsed_args, dict):
        logger.warning("[TOOL_VALIDATOR] Parsed arguments is not a JSON object/dict")
        return False, None, "non_dict_arguments"

    if "product_id" in parsed_args:
        valid_pid, pid_err = validate_product_id_argument(parsed_args["product_id"])
        if not valid_pid:
            logger.warning("[TOOL_VALIDATOR] Product ID argument schema check failed: %s", pid_err)
            return False, parsed_args, f"invalid_schema:{pid_err}"

    return True, parsed_args, None
