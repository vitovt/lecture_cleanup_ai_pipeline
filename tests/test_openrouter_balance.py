"""OpenRouter account checks: isolated credential scopes and mocked GETs."""
import contextlib
from decimal import Decimal
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


def response(value):
    payload = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    return contextlib.nullcontext(io.BytesIO(payload))


class OpenRouterBalanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for scope, prefix in (('cleanup', '.'), ('stt', 'stt-api')):
            folder = self.root / prefix
            folder.mkdir(exist_ok=True)
            provider = {'api_key_env': 'GENERATION_KEY', 'api_base_url': None}
            config = ({'llm': {'provider': 'openrouter', 'openrouter': provider}}
                      if scope == 'cleanup' else {'provider': 'openrouter', 'providers': {'openrouter': provider}})
            (folder / 'config.default.yaml').write_text(yaml.safe_dump(config))
            (folder / '.env').write_text(f'OPENROUTER_MANAGEMENT_API_KEY={scope}-management\nGENERATION_KEY={scope}-ordinary\nOPENROUTER_API_KEY=unused\n')
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def cli(self, args):
        out = io.StringIO()
        with patch.object(balance, 'ROOT', self.root), contextlib.redirect_stdout(out):
            code = balance.main(args)
        return code, out.getvalue()

    def test_both_scopes_use_one_checker_and_their_own_management_key(self):
        self.assertEqual(REGISTRY['cleanup', 'openrouter'].checker, REGISTRY['stt', 'openrouter'].checker)
        original = dict(os.environ)
        for scope in ('cleanup', 'stt'):
            with patch('accounting.http.urllib_request.urlopen', return_value=response({'data': {
                    'total_credits': 100.5, 'total_usage': 25.75}})) as send:
                args = ['--provider', 'openrouter'] + (['--scope', 'stt'] if scope == 'stt' else [])
                code, output = self.cli(args)
            self.assertEqual(code, 0, output)
            self.assertIn('total=74.75', output)
            self.assertIn('currency=USD', output)
            self.assertIn('available=true', output)
            self.assertNotIn('granted=', output)
            self.assertNotIn('topped_up=', output)
            self.assertNotIn('management', output)
            request = send.call_args.args[0]
            self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/credits')
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Authorization'), f'Bearer {scope}-management')
            self.assertEqual(send.call_args.kwargs['timeout'], 10)
            send.assert_called_once()
        self.assertEqual(os.environ, original)

    def test_numeric_json_precision_zero_and_negative_balances(self):
        raw = '{"data":{"total_credits":100.50000000000000000123,"total_usage":25.75000000000000000012}}'
        with patch('accounting.http.urllib_request.urlopen', return_value=response(raw)):
            code, output = self.cli(['--provider', 'openrouter', '--format', 'json'])
        self.assertEqual(code, 0)
        row, = json.loads(output)
        self.assertEqual(row['balances'][0]['total'], '74.75000000000000000111')
        self.assertIsNone(row['balances'][0]['granted'])
        for credits, used, expected in ((0, 0, '0'), (1, 2, '-1')):
            with patch('accounting.http.urllib_request.urlopen', return_value=response({'data': {
                    'total_credits': credits, 'total_usage': used}})):
                snapshot = check_account(self.root, 'cleanup', 'openrouter')
            self.assertEqual(snapshot.status, 'ok')
            self.assertEqual(snapshot.balances[0].total, Decimal(expected))
            self.assertFalse(snapshot.available)

    def test_missing_management_key_never_falls_back_to_ordinary_or_other_scope(self):
        (self.root / 'stt-api/.env').write_text('GENERATION_KEY=ordinary\nOPENROUTER_API_KEY=ordinary\n')
        with patch('accounting.http.urllib_request.urlopen') as send:
            result = check_account(self.root, 'stt', 'openrouter')
        self.assertEqual(result.status, 'not_configured')
        self.assertEqual(result.reason, 'missing_credentials')
        send.assert_not_called()

    def test_management_override_exported_precedence_and_endpoint_configuration(self):
        local = {'llm': {'openrouter': {'management_api_key_env': 'CUSTOM_MANAGEMENT',
            'api_base_url': 'https://configured.invalid/api/v1/'}}}
        (self.root / 'config.yaml').write_text(yaml.safe_dump(local))
        with patch.dict(os.environ, {'CUSTOM_MANAGEMENT': 'exported-management',
                                    'OPENROUTER_API_BASE_URL': 'https://unused.invalid'}):
            settings = resolve_settings(self.root, REGISTRY['cleanup', 'openrouter'])
        self.assertEqual(settings.api_key, 'exported-management')
        self.assertEqual(settings.api_base_url, 'https://configured.invalid/api/v1')
        self.assertNotIn('exported-management', repr(settings))

    def test_invalid_amounts_and_shapes_are_rejected_without_fabricating_zero(self):
        bodies = [{}, {'data': None}, {'data': []}, {'data': {'total_credits': 1}},
                  *({'data': {'total_credits': value, 'total_usage': 0}}
                    for value in (True, None, -1, 'NaN', 'Infinity', {}, 'bad')),
                  {'data': {'total_credits': 1, 'total_usage': -1}}]
        for body in bodies:
            with self.subTest(body=body), patch('accounting.http.urllib_request.urlopen', return_value=response(body)):
                snapshot = check_account(self.root, 'cleanup', 'openrouter')
            self.assertEqual(snapshot.status, 'error')
            self.assertEqual(snapshot.reason, 'invalid_response')
            self.assertEqual(snapshot.balances, ())

    def test_http_and_network_errors_are_safe(self):
        for error, reason in ((HTTPError('private', 403, 'secret', {}, io.BytesIO(b'secret')), 'permission_denied'),
                              (HTTPError('private', 401, 'secret', {}, io.BytesIO()), 'authentication_failed'),
                              (URLError('secret'), 'connection_failed')):
            with patch('accounting.http.urllib_request.urlopen', side_effect=error):
                code, output = self.cli(['--provider', 'openrouter'])
            self.assertEqual(code, 1)
            self.assertIn(f'reason={reason}', output)
            self.assertNotIn('secret', output)
            self.assertNotIn('total=', output)

    def test_list_and_all_use_existing_entry_points(self):
        with patch('accounting.http.urllib_request.urlopen') as send:
            code, output = self.cli(['--list', '--format', 'json'])
        rows = [row for row in json.loads(output) if row['provider'] == 'openrouter']
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['money_balance'] and row['configuration'] == 'configured' for row in rows))
        send.assert_not_called()
        with patch('accounting.http.urllib_request.urlopen', side_effect=lambda *args, **kwargs: response({
                'data': {'total_credits': 5, 'total_usage': 1}})) as send:
            code, output = self.cli(['--all', '--format', 'json'])
        rows = [row for row in json.loads(output) if row['provider'] == 'openrouter']
        self.assertEqual(code, 0)
        self.assertEqual([row['status'] for row in rows], ['ok', 'ok'])
        self.assertEqual(send.call_count, 2)
