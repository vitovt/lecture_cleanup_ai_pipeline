"""Generic provider selection and requests, with no network or credentials."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

from aiadapters.base import LLMAuthError, LLMUnknownError
from aiadapters.factory import create_llm_adapter
from scripts.summary_generation import generation_options

ROOT = Path(__file__).resolve().parents[1]


class ConfigurableProviderTests(unittest.TestCase):
    def config(self):
        cfg = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
        cfg['llm']['provider'] = 'openai_compatible'
        cfg['llm']['openai_compatible']['model'] = 'custom/model'
        return cfg

    def adapter(self, cfg, override=None):
        with tempfile.TemporaryDirectory() as tmp:
            return create_llm_adapter(cfg, provider_override=override, project_root=Path(tmp))

    def test_environment_url_credentials_and_custom_model_reach_request(self):
        cfg = self.config()
        with patch.dict(os.environ, {'OPENAI_COMPATIBLE_API_KEY': 'separate-key',
                                    'OPENAI_COMPATIBLE_API_BASE_URL': 'https://server.invalid/v1/'}, clear=True):
            adapter = self.adapter(cfg)
        self.assertEqual(adapter.name(), 'openai_compatible')
        self.assertEqual(generation_options(cfg)['model'], 'custom/model')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"Cleaned text"}}]}'
        with patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen', return_value=response) as send:
            self.assertEqual(adapter.generate([{'role': 'user', 'content': 'Transcript'}]), 'Cleaned text')
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://server.invalid/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer separate-key')
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'custom/model')
        self.assertFalse(payload['stream'])
        for field in ('temperature', 'top_p', 'thinking', 'reasoning_effort', 'reasoning_format'):
            self.assertNotIn(field, payload)

    def test_config_url_precedes_environment_and_cli_selects_provider(self):
        cfg = self.config()
        cfg['llm']['provider'] = 'dummy'
        cfg['llm']['openai_compatible'].update(api_base_url='http://localhost:8000/v1',
            temperature=0.3, reasoning_effort='high', reasoning_format='hidden', thinking='enabled')
        with patch.dict(os.environ, {'OPENAI_COMPATIBLE_API_KEY': 'local',
                                    'OPENAI_COMPATIBLE_API_BASE_URL': 'https://unused.invalid'}, clear=True):
            adapter = self.adapter(cfg, 'openai_compatible')
        self.assertEqual(adapter._endpoint(), 'http://localhost:8000/v1/chat/completions')
        payload = adapter._build_payload([], model=None, temperature=None, top_p=None)
        self.assertEqual(payload['temperature'], 0.3)
        self.assertEqual(payload['thinking'], {'type': 'enabled'})
        self.assertEqual(payload['reasoning_effort'], 'high')
        self.assertEqual(payload['reasoning_format'], 'hidden')

    def test_missing_settings_fail_without_using_openai_credentials(self):
        cfg = self.config()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unrelated-key'}, clear=True):
            with self.assertRaisesRegex(LLMUnknownError, 'API_BASE_URL'):
                self.adapter(cfg)
            cfg['llm']['openai_compatible']['api_base_url'] = 'https://server.invalid/v1'
            with self.assertRaisesRegex(LLMAuthError, 'OPENAI_COMPATIBLE_API_KEY'):
                self.adapter(cfg)
            cfg['llm']['openai_compatible']['model'] = ''
            with self.assertRaisesRegex(LLMUnknownError, 'model'):
                self.adapter(cfg)
