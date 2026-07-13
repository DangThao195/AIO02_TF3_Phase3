"""
LLM Client Module - Groq-based LLM integration for shopping copilot
Uses groq Python client library for cost-efficient LLM calls
"""

import os
from typing import Optional
from dotenv import load_dotenv
import json

load_dotenv()

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False


class LLMClient:
    """LLM client wrapper using Groq API (cost-efficient 8b-instant model)."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize LLM client.
        
        Args:
            api_key: Groq API key. If None, reads from GROQ_API_KEY env var.
        """
        if not HAS_GROQ:
            raise ImportError("groq package not installed. Install with: pip install groq")
        
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.client = Groq(api_key=self.api_key)
        self.model = "mixtral-8b-32768"  # Free tier model (equivalent to 8b-instant)

    def invoke(self, prompt: str, temperature: float = 0.3, max_tokens: int = 500) -> "LLMResponse":
        """
        Call LLM with given prompt.
        
        Args:
            prompt: Input prompt
            temperature: Creativity level (0-1), lower = more deterministic
            max_tokens: Max response length
            
        Returns:
            LLMResponse object with .content attribute
        """
        try:
            message = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            response_text = message.choices[0].message.content
            return LLMResponse(content=response_text, raw=message)
        except Exception as e:
            # Return error response that can be handled gracefully
            return LLMResponse(content="", error=str(e))

    def extract_json(self, response: "LLMResponse") -> dict:
        """Extract JSON from LLM response safely."""
        if response.error:
            return {}
        try:
            return json.loads(response.content)
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
        except (ImportError, ValueError) as e:
            # For testing without Groq: return mock client
            print(f"Warning: Could not initialize Groq client: {e}")
            return MockLLMClient()
    return _llm_instance


class MockLLMClient:
    """Mock LLM client for testing without API key."""

    def invoke(self, prompt: str, **kwargs) -> LLMResponse:
        """Return mock response with empty content for testing."""
        return LLMResponse(content="{}", error="Mock client - no API key")


# Export singleton instance
try:
    llm_model = get_llm_client()
except Exception:
    # Fallback to mock for testing
    llm_model = MockLLMClient()
