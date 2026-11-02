import json
from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from io import BytesIO

import yaml

from aiadapters.base import LLMAuthError, LLMConnectionError, LLMRateLimitError, LLMUnknownError
from aiadapters.factory import create_llm_adapter
from aiadapters.openrouter_adapter import OpenRouterAdapter
from scripts.config_loader import resolve_llm_profile
from scripts.llm_accounting import generate_with_usage
from scripts.summary_generation import generation_options

ROOT = Path(__file__).resolve().parents[1]


class OpenRouterTests(unittest.TestCase):
    def adapter(self, **kwargs):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'router-only'}, clear=True):
            return OpenRouterAdapter(model='vendor/model', **kwargs)

    def response(self, body):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(body).encode()
        return response

    def test_profile_routing_model_and_reasoning_reach_shared_transport(self):
        cfg = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
        cfg['llm']['profiles'] = {'chosen': {'provider': 'openrouter', 'model': 'vendor/special',
            'provider_routing': {'only': ['endpoint'], 'allow_fallbacks': False},
            'reasoning': {'effort': 'high', 'exclude': True}, 'max_tokens': 5000}}
        cfg = resolve_llm_profile(cfg, 'chosen')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {'OPENROUTER_API_KEY': 'router-only', 'OPENAI_API_KEY': 'unused'}, clear=True):
            adapter = create_llm_adapter(cfg, provider_override=None, project_root=Path(directory))
        self.assertEqual(generation_options(cfg)['model'], 'vendor/special')
        body = {'choices': [{'message': {'content': 'Cleaned lecture'}}], 'usage': {
            'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130, 'cost': 0.0042,
            'prompt_tokens_details': {'cached_tokens': 40},
            'completion_tokens_details': {'reasoning_tokens': 20}}}
        with patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen',
                   return_value=self.response(body)) as send:
            text = generate_with_usage(adapter, [{'role': 'user', 'content': 'Lecture'}],
                                       model=adapter.model, stage='cleanup')
        self.assertEqual(text, 'Cleaned lecture')
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer router-only')
        payload = json.loads(request.data)
        self.assertEqual(payload['provider'], {'only': ['endpoint'], 'allow_fallbacks': False})
        self.assertEqual(payload['reasoning'], {'effort': 'high', 'exclude': True})
        self.assertEqual(payload['model'], 'vendor/special')
        self.assertEqual(payload['max_tokens'], 5000)
        for key in ('temperature', 'top_p', 'reasoning_effort', 'thinking'):
            self.assertNotIn(key, payload)
        self.assertEqual(adapter.last_usage.cost, Decimal('0.0042'))
        self.assertEqual(adapter.last_usage.currency, 'USD')
        self.assertEqual(adapter.last_usage.total_tokens, 130)
        self.assertEqual(adapter.last_usage.cache_miss_tokens, 60)
        self.assertEqual(adapter.last_usage.reasoning_tokens, 20)
        send.assert_called_once()

    def test_environment_base_url_and_explicit_config_precedence(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test',
                                    'OPENROUTER_API_BASE_URL': 'https://env.invalid/v1'}, clear=True):
            self.assertEqual(OpenRouterAdapter(model='a/b')._endpoint(), 'https://env.invalid/v1/chat/completions')
            self.assertEqual(OpenRouterAdapter(model='a/b', api_base_url='https://cfg.invalid/v1/')._endpoint(),
                             'https://cfg.invalid/v1/chat/completions')

    def test_credentials_are_independent_of_openai_and_generic(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unrelated', 'OPENAI_COMPATIBLE_API_KEY': 'other'}, clear=True):
            with self.assertRaisesRegex(LLMAuthError, 'OPENROUTER_API_KEY'):
                OpenRouterAdapter(model='a/b')

    def test_invalid_configuration_fails_before_request(self):
        for params in ({'provider_routing': []}, {'reasoning': 'high'}, {'max_tokens': True},
                       {'max_tokens': 0}, {'reasoning': {'effort': float('nan')}}):
            with self.subTest(params=params), self.assertRaises(LLMUnknownError):
                self.adapter(**params)

    def test_missing_or_invalid_usage_cannot_reuse_previous_counts(self):
        adapter = self.adapter()
        for usage in (None, {}, {'prompt_tokens': True, 'completion_tokens': 0, 'total_tokens': 1},
                      {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 10}):
            adapter.last_usage = object()
            body = {'choices': [{'message': {'content': 'Text'}}], 'usage': usage}
            with patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen', return_value=self.response(body)):
                self.assertEqual(adapter.generate([]), 'Text')
            self.assertIsNone(adapter.last_usage)

    def test_success_status_error_body_uses_standard_retry_errors(self):
        adapter = self.adapter()
        for code, error in ((429, LLMRateLimitError), (402, LLMAuthError), (500, LLMConnectionError)):
            with patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen',
                       return_value=self.response({'error': {'code': code, 'message': 'Rejected'}})):
                with self.assertRaises(error):
                    adapter.generate([])
            self.assertIsNone(adapter.last_usage)

    def test_http_errors_keep_shared_mapping_and_clear_usage(self):
        adapter = self.adapter()
        adapter.last_usage = object()
        error = HTTPError('https://openrouter.invalid', 429, 'Rate limit', {}, BytesIO(b'{"error":{"message":"Rate limit"}}'))
        with patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen', side_effect=error):
            with self.assertRaises(LLMRateLimitError):
                adapter.generate([])
        self.assertIsNone(adapter.last_usage)


if __name__ == '__main__':
    unittest.main()
