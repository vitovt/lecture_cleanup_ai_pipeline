"""LLM provider adapter package.

Exposes the base adapter types for external imports.
"""

from .base import (
    LLMAdapter,
    LLMError,
    LLMRateLimitError,
    LLMAuthError,
    LLMConnectionError,
    LLMUnknownError,
)

__all__ = [
    "LLMAdapter",
    "LLMError",
    "LLMRateLimitError",
    "LLMAuthError",
    "LLMConnectionError",
    "LLMUnknownError",
]

