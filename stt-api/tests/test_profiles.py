import copy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from stt_api.cli import main
from stt_api.config import load_config, resolve_profile
from stt_api.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]


class SttProfileTests(unittest.TestCase):
    def config(self):
        config = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
        config.update(default_profile='lecture', profiles={
            'lecture': {'provider': 'elevenlabs', 'model': 'test-scribe',
                        'request': {'timeout_seconds': 123},
                        'transcription': {'diarization': {'enabled': True}}},
            'plain': {'provider': 'gemini', 'model': 'test-gemini',
                      'transcription': {'timestamps': {'enabled': False}}}})
        return config

    def test_profile_merges_provider_and_transcription_without_mutation(self):
        config = self.config()
        original = copy.deepcopy(config)
        selected = resolve_profile(config)
        self.assertEqual(config, original)
        self.assertEqual(selected['provider'], 'elevenlabs')
        self.assertEqual(selected['providers']['elevenlabs']['model'], 'test-scribe')
        self.assertEqual(selected['providers']['elevenlabs']['request']['timeout_seconds'], 123)
        self.assertTrue(selected['transcription']['diarization']['enabled'])
        self.assertTrue(selected['transcription']['timestamps']['enabled'])

    def test_explicit_provider_bypasses_default_and_conflicting_profile_fails(self):
        self.assertEqual(resolve_profile(self.config(), provider_override='gemini')['provider'], 'gemini')
        with self.assertRaisesRegex(ConfigError, 'conflicting'):
            resolve_profile(self.config(), 'lecture', 'gemini')
        self.assertEqual(resolve_profile(self.config(), 'plain', 'gemini')['active_profile'], 'plain')

    def test_unknown_or_malformed_profile_fails_with_clear_error(self):
        with self.assertRaisesRegex(ConfigError, 'available: lecture, plain'):
            resolve_profile(self.config(), 'missing')
        for preset in (None, {}, {'provider': 'missing'}, {'provider': 'gemini', 'transcription': False}):
            config = self.config()
            config['profiles']['lecture'] = preset
            with self.assertRaises(ConfigError):
                resolve_profile(config)

    def test_cli_selection_and_overrides_take_precedence_over_local_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.default.yaml').write_text(yaml.safe_dump(self.config()))
            (root / 'config.yaml').write_text(yaml.safe_dump({'profiles': {'plain': {'model': 'local-model'}}}))
            selected = load_config(root, profile='plain')
            self.assertEqual(selected['providers']['gemini']['model'], 'local-model')
            output = StringIO()
            with patch('stt_api.cli.PROJECT_DIR', root), patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), redirect_stdout(output):
                status = main(['validate', '--profile', 'plain', '--model', 'cli-model', '--language-code', 'uk'])
            self.assertEqual(status, 0)
            self.assertIn('provider=gemini model=cli-model', output.getvalue())
            self.assertIn('timestamps=off', output.getvalue())
            self.assertIn('local-model', (root / 'config.yaml').read_text())

    def test_default_profile_and_errors_are_resolved_before_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.default.yaml').write_text(yaml.safe_dump(self.config()))
            output, error = StringIO(), StringIO()
            with patch('stt_api.cli.PROJECT_DIR', root), patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'test'}), redirect_stdout(output):
                self.assertEqual(main(['validate']), 0)
            self.assertIn('provider=elevenlabs model=test-scribe', output.getvalue())
            with patch('stt_api.cli.PROJECT_DIR', root), redirect_stderr(error):
                self.assertEqual(main(['validate', '--profile', 'absent']), 2)
            self.assertIn('Unknown STT profile', error.getvalue())
