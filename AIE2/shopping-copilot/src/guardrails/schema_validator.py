"""
Output Schema Validator for LLM Model Responses

Validates LLM output against expected JSON schemas BEFORE using the response.
Prevents crashes and garbage argument execution by catching malformed/invalid outputs.

Ref: MANDATE #25 requirement #5 (output validation at boundary; no crash on garbage)
"""

import json
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("guardrails.schema_validator")


@dataclass
class ValidationResult:
    is_valid: bool
    error: Optional[str] = None
    data: Optional[Any] = None


def validate_intent_parser_output(raw_text: str) -> ValidationResult:
    """
    Validate LLM intent parser output.
    
    Expected format: JSON with keys like task_type, target_entity, product_query, etc.
    
    Args:
        raw_text: LLM response text (may contain markdown code blocks)
    
    Returns:
        ValidationResult with parsed JSON or error
    """
    try:
        # Extract JSON from markdown code blocks if present
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        parsed = json.loads(text)
        
        # Validate required fields
        required_fields = ["task_type", "target_entity"]
        missing = [f for f in required_fields if f not in parsed]
        if missing:
            return ValidationResult(
                is_valid=False,
                error=f"Missing required fields in intent: {missing}"
            )
        
        # Validate task_type values
        valid_task_types = {
            "search", "list_products", "list_categories", "lookup", "rank",
            "compare", "add_to_cart", "view_cart", "unsupported_cart_action",
            "get_reviews", "get_recommendations", "convert_currency",
            "get_shipping", "greeting", "clarify", "unknown"
        }
        if parsed.get("task_type") not in valid_task_types:
            return ValidationResult(
                is_valid=False,
                error=f"Invalid task_type: {parsed.get('task_type')}. "
                      f"Must be one of {valid_task_types}"
            )
        
        # Validate target_entity values
        valid_entities = {
            "product", "category", "cart", "review", "recommendation",
            "currency", "shipping", ""
        }
        if parsed.get("target_entity") not in valid_entities:
            return ValidationResult(
                is_valid=False,
                error=f"Invalid target_entity: {parsed.get('target_entity')}. "
                      f"Must be one of {valid_entities}"
            )
        
        return ValidationResult(is_valid=True, data=parsed)
        
    except json.JSONDecodeError as e:
        return ValidationResult(
            is_valid=False,
            error=f"Failed to parse JSON: {str(e)}"
        )
    except Exception as e:
        return ValidationResult(
            is_valid=False,
            error=f"Unexpected error in intent validation: {str(e)}"
        )


def validate_planner_output(raw_text: str) -> ValidationResult:
    """
    Validate LLM planner output.
    
    Expected format: JSON array of tool calls like:
    [
      {"name": "tool_name", "args": {"param": "value"}},
      ...
    ]
    
    Args:
        raw_text: LLM response text
    
    Returns:
        ValidationResult with parsed plan or error
    """
    try:
        # Extract JSON from markdown code blocks
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        parsed = json.loads(text)
        
        # Must be a list
        if not isinstance(parsed, list):
            return ValidationResult(
                is_valid=False,
                error=f"Plan must be a JSON array, got {type(parsed).__name__}"
            )
        
        # Validate each tool call
        for i, tool_call in enumerate(parsed):
            if not isinstance(tool_call, dict):
                return ValidationResult(
                    is_valid=False,
                    error=f"Tool call {i} must be a dict, got {type(tool_call).__name__}"
                )
            
            if "name" not in tool_call or not isinstance(tool_call.get("name"), str):
                return ValidationResult(
                    is_valid=False,
                    error=f"Tool call {i} missing or invalid 'name' field"
                )
            
            if "args" not in tool_call or not isinstance(tool_call.get("args"), dict):
                return ValidationResult(
                    is_valid=False,
                    error=f"Tool call {i} missing or invalid 'args' dict"
                )
        
        return ValidationResult(is_valid=True, data=parsed)
        
    except json.JSONDecodeError as e:
        return ValidationResult(
            is_valid=False,
            error=f"Failed to parse JSON in plan: {str(e)}"
        )
    except Exception as e:
        return ValidationResult(
            is_valid=False,
            error=f"Unexpected error in plan validation: {str(e)}"
        )


def validate_synthesis_output(raw_text: str) -> ValidationResult:
    """
    Validate LLM synthesis output (response to user).
    
    For synthesis, we do light validation:
    - Must be non-empty string
    - Must not contain unresolved template placeholders like [INSERT_NAME]
    
    Args:
        raw_text: LLM response text
    
    Returns:
        ValidationResult
    """
    try:
        if not isinstance(raw_text, str) or len(raw_text.strip()) == 0:
            return ValidationResult(
                is_valid=False,
                error="Synthesis output must be non-empty string"
            )
        
        # Check for unresolved placeholders (template leak)
        placeholder_patterns = [
            "[INSERT_", "[TÊN_", "[GIÁ_", "[TỔNG_", "[LIST_", "[LINK_"
        ]
        for pattern in placeholder_patterns:
            if pattern in raw_text:
                return ValidationResult(
                    is_valid=False,
                    error=f"Synthesis contains unresolved template placeholder: {pattern}..."
                )
        
        return ValidationResult(is_valid=True, data=raw_text)
        
    except Exception as e:
        return ValidationResult(
            is_valid=False,
            error=f"Unexpected error in synthesis validation: {str(e)}"
        )


def repair_intent_fallback(raw_text: str) -> Dict[str, Any]:
    """
    Attempt to repair/parse partial/malformed intent from LLM.
    
    If validation fails completely, return safe default intent.
    """
    try:
        result = validate_intent_parser_output(raw_text)
        if result.is_valid:
            return result.data
    except:
        pass
    
    # Fallback: detect keywords and construct minimal valid intent
    logger.warning(f"[SCHEMA_VALIDATOR] Could not parse intent, using keyword fallback")
    text_lower = raw_text.lower()
    
    if "cart" in text_lower or "giỏ hàng" in text_lower:
        return {
            "task_type": "view_cart",
            "target_entity": "cart",
            "product_query": ""
        }
    elif "review" in text_lower or "đánh giá" in text_lower:
        return {
            "task_type": "get_reviews",
            "target_entity": "review",
            "product_query": ""
        }
    elif "category" in text_lower or "danh mục" in text_lower:
        return {
            "task_type": "list_categories",
            "target_entity": "category",
            "product_query": ""
        }
    else:
        # Most general fallback
        return {
            "task_type": "search",
            "target_entity": "product",
            "product_query": raw_text[:100]  # Use raw text as query
        }


def repair_plan_fallback() -> list:
    """
    Return empty plan (no tools) as fallback.
    Empty plan triggers abstain response.
    """
    logger.warning(f"[SCHEMA_VALIDATOR] Could not parse plan, returning empty plan (abstain)")
    return []
