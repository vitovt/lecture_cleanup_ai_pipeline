from __future__ import annotations

import os
from typing import List, Optional, Dict

from .base import (
    LLMAdapter,
    LLMError,
    LLMRateLimitError,
    LLMAuthError,
    LLMConnectionError,
    LLMUnknownError,
    Message,
)


class OpenAIAdapter(LLMAdapter):
    """OpenAI adapter wrapping the `openai` Python SDK (responses API).

    Expects OPENAI_API_KEY to be present in environment (or configured via the SDK).
    """

    def __init__(self, *, model: Optional[str] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> None:
        super().__init__(model=model, temperature=temperature, top_p=top_p)
        # Lazy import so that other providers can be used without installing openai
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover - import error path
            raise LLMUnknownError(f"OpenAI SDK import failed: {e}")
        # Initialize client (uses env var OPENAI_API_KEY)
        self._OpenAI = OpenAI
        self._client = OpenAI()

    def name(self) -> str:
        return "openai"

    def validate_environment(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            # Both .env and process env are supported by caller; we validate here.
            raise LLMAuthError("Missing OPENAI_API_KEY in environment (expected via .env or shell env)")

    def _build_params(self, messages: List[Message], model: Optional[str], temperature: Optional[float], top_p: Optional[float]) -> Dict:
        sys_msgs = [m for m in messages if (m.get("role") == "system")]
        user_msgs = [m for m in messages if (m.get("role") != "system")]
        # OpenAI responses API expects a list of role/content pairs in `input`
        input_msgs: List[Dict[str, str]] = []
        for m in sys_msgs + user_msgs:
            input_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        params: Dict = {
            "model": (model or self.model),
            "temperature": self.temperature if temperature is None else temperature,
            "input": input_msgs,
        }
        if (self.top_p if top_p is None else top_p) is not None:
            params["top_p"] = (self.top_p if top_p is None else top_p)
        return params

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
        params = self._build_params(messages, model, temperature, top_p)
        if debug:
            print("===== DEBUG: OpenAI request BEGIN" + (f" [{label}]" if label else "") + " =====")
            print(f"Model: {params.get('model')} | temperature: {params.get('temperature')} | top_p: {params.get('top_p', None)}")
            # Print only counts to avoid leaking full content by default
            print(f"Messages: {len(params.get('input', []))} (system={sum(1 for m in params.get('input', []) if m.get('role')=='system')})")
            print("===== DEBUG: OpenAI request END =====")
        try:
            resp = self._client.responses.create(**params)
            try:
                return getattr(resp, "output_text", "") or ""
            except Exception:
                # Attempt more defensive extraction
                return getattr(resp, "output", "") or ""
        except Exception as e:  # Map to generic errors
            err_str = str(e).lower()
            if any(k in err_str for k in ["rate limit", "quota", "429"]):
                raise LLMRateLimitError(str(e))
            if any(k in err_str for k in ["unauthorized", "invalid api key", "401", "permission"]):
                raise LLMAuthError(str(e))
            if any(k in err_str for k in ["timeout", "temporarily unavailable", "connection"]):
                raise LLMConnectionError(str(e))
            raise LLMUnknownError(str(e))


