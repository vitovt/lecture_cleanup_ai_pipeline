from __future__ import annotations

from typing import Any, Dict, List, Optional
from decimal import Decimal
from urllib import request as urllib_request

from .base import Message, LLMConnectionError, LLMUnknownError
from .accounting import Balance, BalanceSnapshot, TokenUsage
from .openai_compatible_adapter import OpenAICompatibleChatAdapter


class DeepSeekAdapter(OpenAICompatibleChatAdapter):
    """DeepSeek adapter using its OpenAI-compatible chat completions endpoint."""

    supports_usage = True
    supports_balance = True

    def _record_response(self, response: Dict) -> None:
        self.last_usage = None
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return

        def count(key, source=usage):
            value = source.get(key)
            return value if type(value) is int and value >= 0 else None

        required = [count(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if any(value is None for value in required):
            return
        if required[2] != required[0] + required[1]:
            return
        details = usage.get("completion_tokens_details")
        reasoning = count("reasoning_tokens", details) if isinstance(details, dict) else None
        hit, miss = count("prompt_cache_hit_tokens"), count("prompt_cache_miss_tokens")
        if hit is not None and miss is not None and hit + miss != required[0]:
            hit = miss = None
        if reasoning is not None and reasoning > required[1]:
            reasoning = None
        self.last_usage = TokenUsage(*required, hit, miss, reasoning)

    def get_balance(self) -> BalanceSnapshot:
        request = urllib_request.Request(
            f"{self._api_base}/user/balance",
            headers={"Accept": "application/json", "Authorization": f"Bearer {self._api_key}",
                     "User-Agent": self._user_agent},
        )
        try:
            # Monitoring must not add a generation-length timeout to each run.
            with urllib_request.urlopen(request, timeout=min(self._timeout_seconds, 10.0)) as response:
                parsed = self._json_loads_bytes(response.read())
        except Exception as exc:
            # Do not expose response bodies, signed URLs or credentials in monitoring output.
            raise LLMConnectionError("Balance request failed") from exc
        try:
            if not isinstance(parsed, dict) or type(parsed.get("is_available")) is not bool:
                raise ValueError("Invalid availability")
            entries = parsed["balance_infos"]
            if not isinstance(entries, list) or not entries:
                raise ValueError("Missing balances")
            balances = []
            currencies = set()
            for entry in entries:
                currency = entry["currency"]
                if currency not in ("USD", "CNY") or currency in currencies:
                    raise ValueError("Invalid currency")
                currencies.add(currency)
                amounts = [Decimal(entry[key]) for key in
                           ("total_balance", "granted_balance", "topped_up_balance")]
                if any(not value.is_finite() for value in amounts):
                    raise ValueError("Invalid balance")
                balances.append(Balance(currency, *amounts))
            return BalanceSnapshot(parsed["is_available"], tuple(balances))
        except Exception as exc:
            raise LLMUnknownError("Invalid balance response") from exc

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
