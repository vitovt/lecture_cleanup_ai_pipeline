import base64
from contextlib import nullcontext, redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError

from stt_api import cli
from stt_api.checkpoints import fingerprint
from stt_api.config import read_yaml, resolve_profile
from stt_api.errors import InputError, ProviderError, ProviderRequestError, RetryExhaustedError
from stt_api.media import AudioPart, PreparedAudio
from stt_api.providers.openrouter import OpenRouterProvider

ROOT = Path(__file__).resolve().parents[1]


def response(value):
    return nullcontext(BytesIO(json.dumps(value).encode()))


class OpenRouterSttTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'config.default.yaml').write_bytes((ROOT / 'config.default.yaml').read_bytes())
        self.audio = self.root / 'lecture.flac'
        self.audio.write_bytes(b'fake-audio')
        self.output = {'text': 'Hello world', 'language': 'en',
            'words': [{'word': 'Hello', 'start': 0.0, 'end': 0.4, 'speaker': 'speaker_0'},
                      {'word': 'world', 'start': 0.5, 'end': 1.0, 'speaker_label': 'speaker_1'}],
            'usage': {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12, 'seconds': 1}}

    def provider(self, **options):
        values = dict(attempts=2, initial_delay=1, multiplier=2, max_delay=10,
                      jitter=0, request_timeout=90, sleeper=Mock())
        values.update(options)
        return OpenRouterProvider('private-test-key', **values)

    def transcribe(self, provider, **options):
        values = dict(model='openai/whisper-large-v3', language_codes=['en-US'],
                      vocabulary=[], mode='verbatim', timestamps=True, diarization=False)
        values.update(options)
        return provider.transcribe(self.audio, **values)

    def settings(self, config):
        args = cli.build_parser().parse_args(['transcribe', '--input-file', str(self.audio),
                                             '--output-dir', str(self.root / 'out')])
        return args, cli._effective_settings(config, args, self.root)

    def test_request_and_normalized_result_preserve_words_speakers_and_usage(self):
        provider = self.provider(provider_options={'data_collection': 'deny'})
        with patch('stt_api.providers.openrouter.request.urlopen', return_value=response(self.output)) as send:
            result = self.transcribe(provider, vocabulary=['OpenRouter'], diarization=True)
        req = send.call_args.args[0]
        self.assertEqual(req.full_url, 'https://openrouter.ai/api/v1/audio/transcriptions')
        self.assertEqual(req.get_header('Authorization'), 'Bearer private-test-key')
        self.assertEqual(send.call_args.kwargs['timeout'], 90)
        payload = json.loads(req.data)
        self.assertEqual(base64.b64decode(payload['input_audio']['data']), b'fake-audio')
        self.assertEqual(payload['input_audio']['format'], 'flac')
        self.assertEqual(payload['language'], 'en')
        self.assertEqual(payload['timestamp_granularities'], ['word'])
        self.assertEqual(payload['response_format'], 'verbose_json')
        self.assertTrue(payload['diarize'])
        self.assertEqual(payload['keyterms'], ['OpenRouter'])
        self.assertEqual(payload['provider'], {'data_collection': 'deny'})
        self.assertEqual(result['words'][0]['text'], 'Hello')
        self.assertEqual(result['words'][1]['speaker'], 'speaker_1')
        self.assertEqual(result['usage'], self.output['usage'])
        send.assert_called_once()

    def test_multilingual_plain_text_omits_single_language_and_timing_options(self):
        with patch('stt_api.providers.openrouter.request.urlopen', return_value=response({'text': 'Plain text'})) as send:
            result = self.transcribe(self.provider(), timestamps=False, language_codes=['uk-UA', 'de-DE'])
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload['response_format'], 'json')
        for field in ('language', 'diarize', 'timestamp_granularities', 'keyterms', 'provider'):
            self.assertNotIn(field, payload)
        self.assertEqual(result['words'], [])

    def test_retries_transport_and_transient_http_but_not_account_errors(self):
        for first in (URLError('sensitive text'), HTTPError('private', 429, 'secret', {}, BytesIO())):
            provider = self.provider()
            with patch('stt_api.providers.openrouter.request.urlopen', side_effect=[first, response(self.output)]) as send:
                self.assertEqual(self.transcribe(provider)['text'], 'Hello world')
            self.assertEqual(send.call_count, 2)
            provider.sleeper.assert_called_once_with(1)
        for code, exception in ((400, ProviderRequestError), (401, ProviderError), (402, ProviderError)):
            with patch('stt_api.providers.openrouter.request.urlopen', side_effect=HTTPError('private', code, 'secret', {}, BytesIO())) as send:
                with self.assertRaises(exception) as caught:
                    self.transcribe(self.provider())
            send.assert_called_once()
            self.assertNotIn('secret', str(caught.exception))
        with patch('stt_api.providers.openrouter.request.urlopen', side_effect=URLError('private')):
            with self.assertRaises(RetryExhaustedError):
                self.transcribe(self.provider())

    def test_error_inside_success_status_uses_retry_policy(self):
        with patch('stt_api.providers.openrouter.request.urlopen', side_effect=[
                response({'error': {'code': 503, 'message': 'private'}}), response(self.output)]) as send:
            self.assertEqual(self.transcribe(self.provider())['text'], 'Hello world')
        self.assertEqual(send.call_count, 2)

    def test_malformed_or_missing_timestamps_fail_instead_of_losing_parts(self):
        cases = ({'text': 'Missing words'}, {'text': 'Bad', 'words': [{'word': 'Bad', 'start': True, 'end': 1}]},
                 {'text': 'Bad', 'words': [{'word': 'Bad', 'start': 2, 'end': 1}]})
        for body in cases:
            with patch('stt_api.providers.openrouter.request.urlopen', return_value=response(body)), self.assertRaises(ProviderRequestError):
                self.transcribe(self.provider())
        with patch('stt_api.providers.openrouter.request.urlopen', return_value=response({'text': ''})):
            self.assertEqual(self.transcribe(self.provider())['words'], [])

    def test_size_and_mode_fail_before_network_and_trace_excludes_key_and_audio(self):
        with patch('stt_api.providers.openrouter.request.urlopen') as send:
            with self.assertRaises(InputError):
                self.transcribe(self.provider(max_audio_bytes=1))
            with self.assertRaises(InputError):
                self.transcribe(self.provider(), mode='smart')
            send.assert_not_called()
        with patch('stt_api.providers.openrouter.request.urlopen', return_value=response(self.output)), self.assertLogs('stt-api', level=5) as logs:
            self.transcribe(self.provider())
        output = '\n'.join(logs.output)
        self.assertNotIn('private-test-key', output)
        self.assertNotIn(base64.b64encode(b'fake-audio').decode(), output)

    def test_profile_cli_precedence_and_cache_reuse_then_routing_invalidation(self):
        config = read_yaml(ROOT / 'config.default.yaml')
        config.update(default_profile='router', profiles={'router': {'provider': 'openrouter',
            'model': 'openai/whisper-large-v3', 'provider_options': {'data_collection': 'deny'}}})
        config = resolve_profile(config)
        args, settings = self.settings(config)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test'}), \
             patch('stt_api.cli.prepare_audio', side_effect=lambda *a, **kw: PreparedAudio([AudioPart(self.audio, 0, 1, 0, 1)], 1)), \
             patch('stt_api.providers.openrouter.request.urlopen', side_effect=lambda *a, **kw: response(self.output)) as send, \
             redirect_stdout(StringIO()):
            self.assertEqual(cli.transcribe(config, args, settings), 0)
            self.assertEqual(cli.transcribe(config, args, settings), 0)
            self.assertEqual(send.call_count, 1)
            settings['provider_options'] = {'data_collection': 'allow'}
            self.assertEqual(cli.transcribe(config, args, settings), 0)
            self.assertEqual(send.call_count, 2)
        transcript = (self.root / 'out/lecture.txt').read_text()
        self.assertIn('Hello', transcript)
        self.assertIn('world', transcript)
        metadata = json.loads((self.root / 'out/lecture.metadata.json').read_text())
        self.assertEqual(metadata['profile'], 'router')
        raw = json.loads((self.root / 'out/lecture.raw.json').read_text())
        self.assertEqual(raw['parts'][0]['usage'], self.output['usage'])
        changed = dict(settings, model='different/model')
        self.assertNotEqual(fingerprint(self.audio, settings), fingerprint(self.audio, changed))

    def test_validate_provider_does_not_construct_client_or_make_requests(self):
        output = StringIO()
        with patch('stt_api.cli.PROJECT_DIR', self.root), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test'}), patch('stt_api.cli.OpenRouterProvider') as factory, \
             patch('stt_api.providers.openrouter.request.urlopen') as send, redirect_stdout(output):
            self.assertEqual(cli.main(['validate', '--provider', 'openrouter', '--language-code', 'uk']), 0)
        factory.assert_not_called()
        send.assert_not_called()
        self.assertIn('provider=openrouter', output.getvalue())
        error = StringIO()
        with patch('stt_api.cli.PROJECT_DIR', self.root), redirect_stderr(error):
            self.assertEqual(cli.main(['validate', '--provider', 'openrouter', '--mode', 'smart']), 2)
        self.assertIn('smart mode', error.getvalue())

    def test_preflight_does_not_require_a_key_or_send_audio(self):
        output = StringIO()
        with patch('stt_api.cli.PROJECT_DIR', self.root), patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}), \
             patch('stt_api.cli.probe_duration', return_value=2000), \
             patch('stt_api.providers.openrouter.request.urlopen') as send, redirect_stdout(output):
            status = cli.main(['transcribe', '--provider', 'openrouter', '--input-file', str(self.audio), '--preflight'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['planned_chunks'], 3)
        send.assert_not_called()

    def test_missing_requested_speakers_are_not_silently_accepted(self):
        body = dict(self.output, words=[{'word': 'Hello', 'start': 0, 'end': 1}])
        with patch('stt_api.providers.openrouter.request.urlopen', return_value=response(body)):
            with self.assertRaisesRegex(ProviderRequestError, 'speaker labels'):
                self.transcribe(self.provider(), diarization=True)
