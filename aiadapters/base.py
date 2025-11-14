from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class LLMError(Exception):
    """Base error for LLM providers."""


class LLMRateLimitError(LLMError):
    """Provider reported rate limiting or quota exhaustion."""


class LLMAuthError(LLMError):
    """Authentication or authorization failed (e.g., missing/invalid API key)."""


class LLMConnectionError(LLMError):
    """Transport-level errors (network, timeouts, transient failures)."""


class LLMUnknownError(LLMError):
    """Unexpected/unknown provider error."""


Message = Dict[str, str]


class LLMAdapter(ABC):
    """Unified interface for LLM providers.

    Adapters translate provider-agnostic inputs (a list of role/content messages)
    into provider-specific API calls and normalize the response into plain text.

    Implementors should:
    - Map message roles and content to the provider API.
    - Apply provider-specific parameters (model, temperature, top_p, etc.).
    - Catch provider SDK exceptions and re-raise as LLMError subclasses.
    - Avoid leaking provider SDK objects to callers.
    """

    def __init__(self, *, model: Optional[str] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> None:
        self._model = model
        self._temperature = temperature
        self._top_p = top_p

    @property
    def model(self) -> Optional[str]:
        return self._model

    @property
    def temperature(self) -> Optional[float]:
        return self._temperature

    @property
    def top_p(self) -> Optional[float]:
        return self._top_p

    @abstractmethod
    def name(self) -> str:
        """Human-friendly provider name (e.g., 'openai', 'gemini')."""

    @abstractmethod
    def generate(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        debug: bool = False,
        label: Optional[str] = None,
    ) -> str:
        """Generate text given a list of role/content messages.

        Parameters:
        - messages: [{'role': 'system'|'user'|'assistant', 'content': '...'}, ...]
        - model, temperature, top_p: Optional overrides for this call.
        - debug: When True, adapters may log basic request/response info (avoid sensitive content).
        - label: Optional label for logs (e.g., 'chunk 3/10').

        Returns plain text response.
        """

    # Optional: adapters can override to perform per-provider validation or setup.
    def validate_environment(self) -> None:
        """Validate required environment (e.g., API keys). Raise LLMAuthError when missing."""
        return None


