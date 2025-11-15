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


class GeminiAdapter(LLMAdapter):
    """Google Gemini adapter using the `google-generativeai` SDK.

    Expects GOOGLE_API_KEY in the environment. Maps provider-agnostic messages
    to a best-effort prompt. For richer chat history handling, consider
    extending this adapter to use `start_chat` with structured history.
    """

    def __init__(self, *, model: Optional[str] = None, temperature: Optional[float] = None, top_p: Optional[float] = None) -> None:
        super().__init__(model=model, temperature=temperature, top_p=top_p)
        try:
            import google.generativeai as genai  # type: ignore
        except Exception as e:  # pragma: no cover
            raise LLMUnknownError(f"Gemini SDK import failed: {e}")
        self._genai = genai
        # Configure with env key
        if not os.environ.get("GOOGLE_API_KEY"):
            raise LLMAuthError("Missing GOOGLE_API_KEY in environment (expected via .env or shell env)")
        self._genai.configure(api_key=os.environ["GOOGLE_API_KEY"])  # type: ignore

    def name(self) -> str:
        return "gemini"

    def validate_environment(self) -> None:
        if not os.environ.get("GOOGLE_API_KEY"):
            raise LLMAuthError("Missing GOOGLE_API_KEY in environment (expected via .env or shell env)")

    def _split_messages(self, messages: List[Message]) -> Dict[str, str]:
        sys_texts = []
        conv_texts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                if content:
                    sys_texts.append(content)
            else:
                if content:
                    conv_texts.append(f"{role.upper()}: {content}")
        return {
            "system_instruction": "\n\n".join(sys_texts).strip(),
            "conversation": "\n\n".join(conv_texts).strip(),
        }

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
        from typing import Any
        split = self._split_messages(messages)
        system_instruction = split["system_instruction"] or None
        prompt = split["conversation"] or ""
        model_name = model or self.model or "gemini-1.5-pro"
        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        elif self.temperature is not None:
            generation_config["temperature"] = self.temperature
        if top_p is not None:
            generation_config["top_p"] = top_p
        elif self.top_p is not None:
            generation_config["top_p"] = self.top_p

        try:
            # Construct model with optional system instruction
            if system_instruction:
                model_obj = self._genai.GenerativeModel(model_name, system_instruction=system_instruction)
            else:
                model_obj = self._genai.GenerativeModel(model_name)

            if debug:
                print("===== DEBUG: Gemini request BEGIN" + (f" [{label}]" if label else "") + " =====")
                print(f"Model: {model_name} | temperature: {generation_config.get('temperature')} | top_p: {generation_config.get('top_p')}")
                print(f"Prompt chars: {len(prompt)} | system: {bool(system_instruction)}")
                print("===== DEBUG: Gemini request END =====")

            resp = model_obj.generate_content(
                prompt,
                generation_config=generation_config or None,
            )
            # google-generativeai returns .text for aggregated text
            return getattr(resp, "text", "") or ""
        except Exception as e:
            err = str(e).lower()
            # Retriable: clear rate-limit signals (checked first)
            rate_keys = ["rate limit", "429", "resourceexhausted", "too many requests", "retry in", "retry_delay"]
            for k in rate_keys:
                if k in err:
                    if debug:
                        print(f"[DEBUG] {self.name()} matched '{k}' -> LLMRateLimitError")
                    raise LLMRateLimitError(str(e))
            # Retriable: transient/connection
            conn_keys = ["deadline exceeded", "timeout", "temporarily unavailable", "connection", "unavailable", "dns"]
            for k in conn_keys:
                if k in err:
                    if debug:
                        print(f"[DEBUG] {self.name()} matched '{k}' -> LLMConnectionError")
                    raise LLMConnectionError(str(e))
            # Non-retriable: authentication/billing/subscription issues
            auth_keys = [
                "unauthenticated", "invalid api key", "401", "permission", "api key not valid", "forbidden",
                "billing", "payment", "insufficient funds", "subscription",
            ]
            for k in auth_keys:
                if k in err:
                    if debug:
                        print(f"[DEBUG] {self.name()} matched '{k}' -> LLMAuthError")
                    raise LLMAuthError(str(e))
            # Unknown -> non-retriable by default
            if debug:
                print(f"[DEBUG] {self.name()} did not match known errors -> LLMUnknownError")
            raise LLMUnknownError(str(e))
