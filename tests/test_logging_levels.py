from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import logging
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from multitrack.sources import resolve
from scripts.run_multitrack import main
from scripts.logging_helper import set_log_level, _LOGGER
from aiadapters.openai_compatible_adapter import OpenAICompatibleChatAdapter
from aiadapters.base import LLMUnknownError

ROOT = Path(__file__).resolve().parents[1]


class LoggingLevelsTests(unittest.TestCase):
    def tearDown(self):
        set_log_level('info')

    def test_workflow_quiet_and_error_cover_validation(self):
        for script in ['auto_process_youtube.sh', 'process_localaudiovideo_via_speechcore.sh',
                       'process_localaudiovideo_via_gemini.sh', 'process_localaudiovideo_via_elevenlabs.sh',
                       'process_localaudiovideo_via_groq.sh']:
            for level in ['quiet', 'error']:
                with self.subTest(script=script, level=level):
                    result = subprocess.run(['bash', str(ROOT / script), '--log-level', level],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(bool(result.stderr), level == 'error')

    def test_stt_wrappers_preserve_trace(self):
        for provider in ['gemini', 'elevenlabs']:
            result = subprocess.run(['bash', '-c',
                'SCRIPT_DIR="$1"; source "$1/scripts/$2_shell_common.sh"; '
                'LOG_LEVEL=trace; STT_RUNNER=show_args; show_args() { printf "%s\\n" "$@"; }; '
                '"${2}_transcribe" audio out metadata base',
                'test', str(ROOT), provider], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--log-level\ntrace\n', result.stdout)

    def test_multitrack_inherits_config_and_cli_overrides(self):
        with patch('multitrack.sources.load_effective_config', return_value=({'logging': {'level': 'error'}}, True)):
            args = ['--source', 'a', '--file', 'a.wav']
            self.assertEqual(resolve(args)['log_level'], 'error')
            self.assertEqual(resolve(['--trace', *args])['log_level'], 'trace')

    def test_multitrack_quiet_failure_and_debug_traceback(self):
        for level in ['quiet', 'error', 'debug', 'trace']:
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err), \
                 patch('scripts.run_multitrack.preflight', side_effect=ValueError('bad media')):
                self.assertEqual(main(['--log-level', level, '--source', 'a', '--file', 'a.wav']), 2)
            self.assertEqual(out.getvalue(), '')
            self.assertEqual('bad media' in err.getvalue(), level != 'quiet')
            self.assertEqual('Traceback' in err.getvalue(), level in {'debug', 'trace'})

    def test_llm_response_body_is_trace_only(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'PRIVATE_RESPONSE'
        with patch.dict(os.environ, {'TEST_API_KEY': 'SECRET_KEY'}):
            adapter = OpenAICompatibleChatAdapter(provider_name='test', api_key_env_var='TEST_API_KEY',
                        default_api_base_url='https://example.invalid/v1', default_model='test')
        for level in ['info', 'debug', 'trace']:
            set_log_level(level)
            output = StringIO()
            handler = logging.StreamHandler(output)
            with patch.object(_LOGGER, 'handlers', [handler]), redirect_stdout(output), \
                 patch('aiadapters.openai_compatible_adapter.urllib_request.urlopen', return_value=Response()):
                with self.assertRaises(LLMUnknownError):
                    adapter.generate([{'role': 'user', 'content': 'PRIVATE_PROMPT'}], debug=level != 'info')
            self.assertEqual('PRIVATE_RESPONSE' in output.getvalue(), level == 'trace')
            self.assertEqual('PRIVATE_PROMPT' in output.getvalue(), level == 'trace')
            self.assertNotIn('SECRET_KEY', output.getvalue())
