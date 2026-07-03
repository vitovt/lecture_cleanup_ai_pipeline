from __future__ import annotations

from typing import Optional

from .openai_compatible_adapter import OpenAICompatibleChatAdapter


class GroqAdapter(OpenAICompatibleChatAdapter):
    """Groq adapter using its OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        reasoning_format: Optional[str] = None,
        api_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(
            provider_name="groq",
            api_key_env_var="GROQ_API_KEY",
            api_base_url_env_var="GROQ_API_BASE_URL",
            default_api_base_url="https://api.groq.com/openai/v1",
            default_model="openai/gpt-oss-120b",
            model=model,
            temperature=temperature,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            reasoning_format=reasoning_format,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
            user_agent_suffix="GroqAdapter",
        )
