"""
LLM Client Module - AWS Bedrock-based LLM integration for shopping copilot
Migrated from Groq to Bedrock (Amazon Nova) to use TechX Corp infra.
"""

import os
import re
import boto3
import json
from typing import Optional

_boto3_session = None
_bedrock_client = None


def _get_bedrock_client():
    global _boto3_session, _bedrock_client
    if _bedrock_client is not None:
        return _bedrock_client
    profile = os.getenv("AWS_PROFILE")
    if profile:
        _boto3_session = boto3.Session(profile_name=profile)
    else:
        _boto3_session = boto3.Session()
    region = os.getenv("BEDROCK_REGION", "ap-southeast-1")
    _bedrock_client = _boto3_session.client("bedrock-runtime", region_name=region)
    return _bedrock_client


class LLMClient:
    """LLM client wrapper using AWS Bedrock (Amazon Nova model)."""

    def __init__(self):
        """
        Initialize AWS Bedrock client.
        Reads credentials via AWS profile or environment variables.
        """
        self.model = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
        self.client = _get_bedrock_client()

    def invoke(self, prompt: str, temperature: float = 0.3, max_tokens: int = 500,
               system_prompt: str = "") -> "LLMResponse":
        """
        Call Bedrock Converse API with given prompt.
        
        Args:
            prompt: Input prompt
            temperature: Creativity level (0-1), lower = more deterministic
            max_tokens: Max response length
            system_prompt: Optional system prompt passed via Converse system parameter
            
        Returns:
            LLMResponse object with .content attribute
        """
        try:
            kwargs = dict(
                modelId=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ],
                inferenceConfig={
                    "temperature": temperature,
                    "maxTokens": max_tokens
                }
            )
            if system_prompt:
                kwargs["system"] = [{"text": system_prompt}]
            response = self.client.converse(**kwargs)
            
            content_blocks = response["output"]["message"]["content"]
            response_text = ""
            for block in content_blocks:
                if "text" in block:
                    response_text += block["text"]
                    
            return LLMResponse(content=response_text, raw=response)
        except Exception as e:
            return LLMResponse(content="", error=str(e))

    def extract_json(self, response: "LLMResponse") -> dict:
        """Extract JSON from LLM response safely."""
        if response.error:
            return {}
        try:
            text = response.content.strip()
            if not text:
                return {}
            # Strip markdown code fences and any surrounding whitespace
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?\s*```$", "", text)
            text = text.strip()
            # Also strip any leading/trailing non-JSON cruft
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end+1]
            # Remove BOM and zero-width chars
            text = text.replace("\ufeff", "").replace("\u200b", "")
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {}


class LLMResponse:
    """Wrapper for LLM response to provide consistent interface."""

    def __init__(self, content: str = "", raw=None, error: Optional[str] = None):
        self.content = content
        self.raw = raw
        self.error = error

    def __str__(self):
        return self.content

    def __bool__(self):
        """Response is truthy if it has content and no error."""
        return bool(self.content) and not self.error


# Singleton instance for use throughout the application
_llm_instance = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_instance
    if _llm_instance is None:
        try:
            _llm_instance = LLMClient()
        except Exception as e:
            # Fail closed in production-like paths instead of silently switching to mock.
            raise RuntimeError(f"Unable to initialize Bedrock LLM client: {e}") from e
    return _llm_instance


class MockLLMClient:
    """Mock LLM client for testing without AWS credentials."""

    def invoke(self, prompt: str, **kwargs) -> LLMResponse:
        """Return mock response with empty JSON for testing."""
        return LLMResponse(content="{}", error="Mock client - no API key")


# Lazy singleton access — only initializes on first use, not at import time
_llm_init_error = None


def __getattr__(name):
    if name == "llm_model":
        global _llm_init_error
        try:
            return get_llm_client()
        except Exception as exc:
            _llm_init_error = exc
            return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
