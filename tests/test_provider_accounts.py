"""Read-only account checks using isolated configs and mocked HTTP responses."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import yaml

from accounting.credentials import resolve_settings
from accounting.registry import REGISTRY
from accounting.service import check_account
from scripts import balance


ELEVEN = dict(character_count=1200, character_limit=10000, tier='starter',
              status='active', next_character_count_reset_unix=1738356858)
DEEPSEEK = dict(is_available=True, balance_infos=[dict(currency='USD',
                total_balance='1.000000001', granted_balance='0', topped_up_balance='1.000000001')])


def response(value):
    return contextlib.nullcontext(io.BytesIO(json.dumps(value).encode()))


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory, cfg, env in (
            ('.', {'llm': {'provider': 'deepseek', 'deepseek': {}}},
             'DEEPSEEK_API_KEY=root-secret\nGROQ_API_KEY=root-groq\nELEVENLABS_API_KEY=wrong-root-key\n'),
            ('stt-api', {'provider': 'elevenlabs', 'providers': {
                'elevenlabs': {'api_key_env': 'CUSTOM_ELEVEN_KEY'}, 'gemini': {}}},
             'CUSTOM_ELEVEN_KEY=stt-secret\n'),
            ('groq-api', {'api': {'api_key_env': 'CUSTOM_GROQ_KEY'}},
             'CUSTOM_GROQ_KEY=stt-groq\n'),
        ):
            dest = self.root / directory
            dest.mkdir(exist_ok=True)
            (dest / 'config.default.yaml').write_text(yaml.safe_dump(cfg))
            (dest / '.env').write_text(env)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def cli(self, args):
        with patch.object(balance, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()) as out:
            code = balance.main(args)
        return code, out.getvalue()

    def test_elevenlabs_default_scope_uses_stt_config_and_custom_key(self):
        before = dict(os.environ)
        with patch('accounting.http.urllib_request.urlopen', return_value=response(ELEVEN)) as call:
            code, output = self.cli(['--scope', 'stt', '--format', 'json'])
        self.assertEqual(code, 0)
        result, = json.loads(output)
        self.assertEqual(result['provider'], 'elevenlabs')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['reason'], 'monetary_balance_unavailable')
        self.assertEqual(result['balances'], [])
        self.assertIsNone(result['available'])
        quota, = result['quotas']
        self.assertEqual(quota['remaining'], 8800)
        self.assertEqual(quota['unit'], 'characters')
        self.assertEqual(quota['resets_at'], '2025-01-31T20:54:18+00:00')
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.elevenlabs.io/v1/user/subscription')
        self.assertEqual(request.get_header('Xi-api-key'), 'stt-secret')
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(call.call_args.kwargs['timeout'], 10)
        self.assertEqual(dict(os.environ), before)
        self.assertNotIn('secret', output)

    def test_deepseek_legacy_records_and_json_precision(self):
        for args in ([], ['--provider', 'deepseek', '--format', 'json']):
            with self.subTest(args=args), patch('accounting.http.urllib_request.urlopen',
                                               return_value=response(DEEPSEEK)):
                code, output = self.cli(args)
            self.assertEqual(code, 0)
            if args:
                self.assertEqual(json.loads(output)[0]['balances'][0]['total'], '1.000000001')
            else:
                self.assertTrue(output.startswith('LLM_BALANCE '))
                self.assertIn('total=1.000000001', output)
                self.assertIn('available=true', output)

    def test_elevenlabs_overage_zero_and_unknown_reset_are_not_cash(self):
        for used, limit in ((12000, 10000), (0, 0)):
            with self.subTest(used=used), patch('accounting.http.urllib_request.urlopen',
                return_value=response(dict(character_count=used, character_limit=limit))):
                result = check_account(self.root, 'stt', 'elevenlabs')
            self.assertEqual(result.quotas[0].remaining, 0)
            self.assertEqual(result.quotas[0].overage, max(0, used - limit))
            self.assertIsNone(result.quotas[0].resets_at)
            self.assertEqual(result.balances, ())

    def test_bad_subscription_data_is_never_zero_balance(self):
        values = [{}, [], {**ELEVEN, 'character_count': '12'},
                  {**ELEVEN, 'character_count': True}, {**ELEVEN, 'character_limit': -1},
                  {**ELEVEN, 'next_character_count_reset_unix': True},
                  {**ELEVEN, 'next_character_count_reset_unix': 10**30}]
        for value in values:
            with self.subTest(value=value), patch('accounting.http.urllib_request.urlopen', return_value=response(value)):
                result = check_account(self.root, 'stt', 'elevenlabs')
            self.assertEqual(result.status, 'error')
            self.assertEqual(result.reason, 'invalid_response')
            self.assertEqual(result.quotas, ())
            self.assertEqual(result.balances, ())

    def test_errors_are_safe_and_distinguishable(self):
        errors = [(HTTPError('https://secret', 401, 'stt-secret', {}, None), 'authentication_failed'),
                  (HTTPError('https://secret', 403, 'stt-secret', {}, None), 'permission_denied'),
                  (HTTPError('https://secret', 429, 'stt-secret', {}, None), 'rate_limited'),
                  (HTTPError('https://secret', 500, 'stt-secret', {}, None), 'http_error'),
                  (URLError('stt-secret'), 'connection_failed')]
        for error, reason in errors:
            with self.subTest(reason=reason), patch('accounting.http.urllib_request.urlopen', side_effect=error):
                code, output = self.cli(['--scope', 'stt', '--provider', 'elevenlabs'])
            self.assertEqual(code, 1)
            self.assertIn(f'reason={reason}', output)
            self.assertNotIn('secret', output)
            self.assertNotIn('total=', output)

    def test_root_key_cannot_fill_missing_stt_credentials(self):
        (self.root / 'stt-api/.env').write_text('')
        with patch('accounting.http.urllib_request.urlopen') as request:
            result = check_account(self.root, 'stt', 'elevenlabs')
        request.assert_not_called()
        self.assertEqual(result.status, 'not_configured')
        self.assertEqual(result.reason, 'missing_credentials')

    def test_exported_env_precedence_endpoint_override_and_timeout(self):
        (self.root / 'stt-api/config.yaml').write_text(yaml.safe_dump({
            'accounting': {'timeout_seconds': 7}, 'providers': {'elevenlabs': {
                'api_base_url': 'https://custom.invalid/'}}}))
        with patch.dict(os.environ, {'CUSTOM_ELEVEN_KEY': 'exported-key'}), \
             patch('accounting.http.urllib_request.urlopen', return_value=response(ELEVEN)) as call:
            result = check_account(self.root, 'stt', 'elevenlabs')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(call.call_args.args[0].get_header('Xi-api-key'), 'exported-key')
        self.assertEqual(call.call_args.args[0].full_url, 'https://custom.invalid/v1/user/subscription')
        self.assertEqual(call.call_args.kwargs['timeout'], 7)

    def test_groq_scopes_resolve_separately_without_account_probe(self):
        cleanup = resolve_settings(self.root, REGISTRY['cleanup', 'groq'])
        stt = resolve_settings(self.root, REGISTRY['stt', 'groq'])
        self.assertEqual(cleanup.api_key, 'root-groq')
        self.assertEqual(stt.api_key, 'stt-groq')
        self.assertNotIn('stt-groq', repr(stt))
        with patch('accounting.http.urllib_request.urlopen') as request:
            self.assertEqual(check_account(self.root, 'cleanup', 'groq').status, 'unsupported')
            self.assertEqual(check_account(self.root, 'stt', 'groq').status, 'unsupported')
        request.assert_not_called()

    def test_list_never_queries_accounts_or_imports_stt_sdks(self):
        with patch('accounting.http.urllib_request.urlopen') as request:
            code, output = self.cli(['--list', '--format', 'json'])
        request.assert_not_called()
        self.assertEqual(code, 0)
        entries = {(r['scope'], r['provider']): r for r in json.loads(output)}
        self.assertTrue(entries['cleanup', 'deepseek']['money_balance'])
        self.assertTrue(entries['stt', 'elevenlabs']['subscription_quota'])
        self.assertEqual(entries['stt', 'groq']['configuration'], 'configured')
        self.assertFalse(entries['stt', 'groq']['money_balance'])
        self.assertNotIn('secret', output)

    def test_all_continues_after_error_and_filters_scope(self):
        def send(request, **kwargs):
            if request.full_url.endswith('/user/balance'):
                raise URLError('root-secret')
            return response(ELEVEN)
        with patch('accounting.http.urllib_request.urlopen', side_effect=send):
            code, output = self.cli(['--all', '--format', 'json'])
        self.assertEqual(code, 1)
        results = {(r['scope'], r['provider']): r for r in json.loads(output)}
        self.assertEqual(results['cleanup', 'deepseek']['status'], 'error')
        self.assertEqual(results['stt', 'elevenlabs']['status'], 'partial')
        self.assertEqual(results['stt', 'gemini']['status'], 'not_configured')
        with patch('accounting.http.urllib_request.urlopen', return_value=response(ELEVEN)) as request:
            code, output = self.cli(['--scope', 'stt', '--all', '--format', 'json'])
        self.assertEqual(code, 0)
        self.assertTrue(all(r['scope'] == 'stt' for r in json.loads(output)))
        self.assertEqual(request.call_count, 1)

    def test_uninstalled_optional_component_is_unconfigured(self):
        (self.root / 'groq-api/config.default.yaml').unlink()
        with patch('accounting.http.urllib_request.urlopen', return_value=response(ELEVEN)):
            code, output = self.cli(['--scope', 'stt', '--all', '--format', 'json'])
        self.assertEqual(code, 0)
        groq = next(item for item in json.loads(output) if item['provider'] == 'groq')
        self.assertEqual(groq['status'], 'not_configured')
        self.assertEqual(groq['reason'], 'component_not_installed')

    def test_strict_cli_rejects_invalid_combinations(self):
        for args in (['--scope', 'cleanup', '--provider', 'elevenlabs'],
                     ['--scope', 'stt', '--provider', 'deepseek'],
                     ['--provider', 'groq', '--all'], ['--all', '--list'],
                     ['--provid', 'deepseek']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.cli(args)
                self.assertEqual(error.exception.code, 2)

    def test_invalid_config_or_timeout_never_makes_request(self):
        for value in (0, -1, 61, True, float('nan'), 'bad'):
            (self.root / 'stt-api/config.yaml').write_text(yaml.safe_dump({'accounting': {'timeout_seconds': value}}))
            with self.subTest(value=value), patch('accounting.http.urllib_request.urlopen') as request:
                result = check_account(self.root, 'stt', 'elevenlabs')
            request.assert_not_called()
            self.assertEqual(result.reason, 'invalid_configuration')
        (self.root / 'stt-api/config.yaml').write_text('providers: null\n')
        result = check_account(self.root, 'stt', 'elevenlabs')
        self.assertEqual(result.status, 'error')
        self.assertEqual(result.reason, 'invalid_configuration')
