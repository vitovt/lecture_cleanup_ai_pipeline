from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import Message
from .openai_compatible_adapter import OpenAICompatibleChatAdapter


class DeepSeekAdapter(OpenAICompatibleChatAdapter):
    """DeepSeek adapter using its OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        thinking: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        api_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        thinking_mode = (thinking or "enabled").strip().lower() or "enabled"
        effective_temperature = None if thinking_mode == "enabled" else temperature
        effective_top_p = None if thinking_mode == "enabled" else top_p
        # DeepSeek documents reasoning_effort only for thinking mode. In non-thinking
        # mode we intentionally omit it, keeping temperature/top_p effective.
        effective_reasoning_effort = None if thinking_mode == "disabled" else reasoning_effort
        super().__init__(
            provider_name="deepseek",
            api_key_env_var="DEEPSEEK_API_KEY",
            api_base_url_env_var="DEEPSEEK_API_BASE_URL",
            default_api_base_url="https://api.deepseek.com",
            default_model="deepseek-v4-flash",
            model=model,
            temperature=effective_temperature,
            top_p=effective_top_p,
            thinking=thinking_mode,
            reasoning_effort=effective_reasoning_effort,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
            user_agent_suffix="DeepSeekAdapter",
        )

    def _build_payload(
        self,
        messages: List[Message],
        *,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
    ) -> Dict[str, Any]:
        if self._thinking == "enabled":
            temperature = None
            top_p = None
        return super()._build_payload(
            messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
        )
