"""
LLM Client Module - AWS Bedrock-based LLM integration for shopping copilot
Migrated from Groq to Bedrock (Amazon Nova) to use TechX Corp infra.
"""

import os
import boto3
import json
from typing import Optional

class LLMClient:
    """LLM client wrapper using AWS Bedrock (Amazon Nova model)."""

    def __init__(self):
        """
        Initialize AWS Bedrock client.
        Reads credentials via AWS profile or environment variables.
        """
        self.model = os.getenv("BEDROCK_MODEL_ID", "apac.amazon.nova-lite-v1:0")
        self.region = os.getenv("BEDROCK_REGION", "ap-southeast-1")
        self.profile = os.getenv("AWS_PROFILE")

        # Initialize boto3 session
        if self.profile:
            session = boto3.Session(profile_name=self.profile)
        else:
            session = boto3.Session()
            
        self.client = session.client("bedrock-runtime", region_name=self.region)

    def invoke(self, prompt: str, temperature: float = 0.3, max_tokens: int = 500) -> "LLMResponse":
        """
        Call Bedrock Converse API with given prompt.
        
        Args:
            prompt: Input prompt
            temperature: Creativity level (0-1), lower = more deterministic
            max_tokens: Max response length
            
        Returns:
            LLMResponse object with .content attribute
        """
        try:
            response = self.client.converse(
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
            # Clean possible markdown wrap (```json ... ```)
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text.strip())
        except json.JSONDecodeError:
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


# Export singleton instance
try:
    llm_model = get_llm_client()
except Exception as exc:
    # Keep a placeholder that fails clearly for production-like usage.
    llm_model = None
    _llm_init_error = exc
