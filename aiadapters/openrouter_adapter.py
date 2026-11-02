"""OpenRouter text generation using the shared Chat Completions transport."""
from copy import deepcopy
import json

from .accounting import TokenUsage
from .base import LLMUnknownError
from .openai_compatible_adapter import OpenAICompatibleChatAdapter


class OpenRouterAdapter(OpenAICompatibleChatAdapter):
    supports_usage = True

    def __init__(self, *, model=None, temperature=None, top_p=None,
                 api_base_url=None, timeout_seconds=None, provider_routing=None,
                 reasoning=None, max_tokens=None):
        if not isinstance(model, str) or not model.strip():
            raise LLMUnknownError('Set llm.openrouter.model to an OpenRouter model ID')
        for name, value in (('provider_routing', provider_routing), ('reasoning', reasoning)):
            if value is not None and not isinstance(value, dict):
                raise LLMUnknownError(f'llm.openrouter.{name} must be a mapping or null')
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise LLMUnknownError(f'llm.openrouter.{name} must contain JSON values') from exc
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
            raise LLMUnknownError('llm.openrouter.max_tokens must be a positive integer or null')
        self._routing = deepcopy(provider_routing)
        self._reasoning = deepcopy(reasoning)
        self._max_tokens = max_tokens
        super().__init__(provider_name='openrouter', api_key_env_var='OPENROUTER_API_KEY',
            api_base_url_env_var='OPENROUTER_API_BASE_URL',
            default_api_base_url='https://openrouter.ai/api/v1', default_model=model,
            model=model, temperature=temperature, top_p=top_p,
            api_base_url=api_base_url, timeout_seconds=timeout_seconds)

    def _build_payload(self, messages, *, model, temperature, top_p):
        payload = super()._build_payload(messages, model=model, temperature=temperature, top_p=top_p)
        if self._routing is not None:
            payload['provider'] = deepcopy(self._routing)
        if self._reasoning is not None:
            payload['reasoning'] = deepcopy(self._reasoning)
        if self._max_tokens is not None:
            payload['max_tokens'] = self._max_tokens
        return payload

    def _record_response(self, response):
        self.last_usage = None
        error = response.get('error')
        if isinstance(error, dict):
            code = error.get('code')
            self._raise_mapped_error(self._extract_error_message(response) or 'OpenRouter request failed',
                                     status=code if type(code) is int else None, debug=False)
        usage = response.get('usage')
        if not isinstance(usage, dict):
            return

        def count(source, key):
            value = source.get(key) if isinstance(source, dict) else None
            return value if type(value) is int and value >= 0 else None

        counts = [count(usage, key) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        if any(value is None for value in counts) or counts[2] != counts[0] + counts[1]:
            return
        cached = count(usage.get('prompt_tokens_details'), 'cached_tokens')
        reasoning = count(usage.get('completion_tokens_details'), 'reasoning_tokens')
        if cached is not None and cached > counts[0]:
            cached = None
        if reasoning is not None and reasoning > counts[1]:
            reasoning = None
        self.last_usage = TokenUsage(*counts, cached,
            counts[0] - cached if cached is not None else None, reasoning)
