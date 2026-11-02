"""Shared metrics contracts, with no provider SDKs, keys or network requests."""
from decimal import Decimal
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from accounting.models import TokenUsage
from accounting.usage import (EVENT_FILE, metrics, normalize_usage,
    report_usage, request_with_usage, response_json, usage_context, usage_session)
from aiadapters.base import LLMAdapter
from scripts.llm_accounting import generate_with_usage


class SharedUsageTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_common_json_and_sdk_shapes_normalize_identically(self):
        values = [
            {'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130,
                       'prompt_tokens_details': {'cached_tokens': 40},
                       'completion_tokens_details': {'reasoning_tokens': 20}}},
            SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=30, total_tokens=130,
                input_tokens_details=SimpleNamespace(cached_tokens=40),
                output_tokens_details=SimpleNamespace(reasoning_tokens=20))),
            {'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 10,
                               'thoughtsTokenCount': 20, 'totalTokenCount': 130, 'cachedContentTokenCount': 40}},
            {'data': {'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130,
                'prompt_cache_hit_tokens': 40, 'prompt_cache_miss_tokens': 60,
                'completion_tokens_details': {'reasoning_tokens': 20}}}},
        ]
        for value in values:
            self.assertEqual(normalize_usage(value), TokenUsage(100, 30, 130, 40, 60, 20))

    def test_money_independent_of_tokens_and_requires_known_currency(self):
        raw = response_json('{"usage":{"cost":0.000000000000001234567890123456789}}')
        self.assertEqual(normalize_usage(raw, currency='USD').cost, Decimal('0.000000000000001234567890123456789'))
        self.assertIsNone(normalize_usage(raw))
        self.assertEqual(metrics(normalize_usage({'usage': {'cost': 0, 'currency': 'usd'}})),
                         {'cost': '0', 'currency': 'USD'})
        for value in (None, True, -1, 'NaN', float('inf'), 'bad'):
            self.assertIsNone(normalize_usage({'usage': {'cost': value}}, currency='USD'))
        partial = normalize_usage({'usage': {'prompt_tokens': True, 'cost': '0.001'}}, currency='USD')
        self.assertEqual(metrics(partial), {'cost': '0.001', 'currency': 'USD'})

    def test_partial_tokens_zero_and_absent_metrics_are_not_fabricated(self):
        self.assertEqual(metrics(normalize_usage({'usage': {'input_tokens': 0}})), {'input_tokens': 0})
        self.assertIsNone(normalize_usage({'usage': {}}))
        self.assertIsNone(normalize_usage({'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 99}}))
        lines = []
        report_usage(None, scope='cleanup', provider='unsupported', model='x', stage='cleanup', emit=lines.append)
        self.assertEqual(lines, [])

    def test_totals_keep_currencies_separate_and_mark_partial_coverage(self):
        lines = []
        with usage_session(emit=lines.append):
            for usage, scope, model in [(TokenUsage(10, 3, 13, cost=Decimal('0.1'), currency='USD'), 'cleanup', 'a'),
                                       (TokenUsage(10, 3, 13, cost=Decimal('0.2'), currency='USD'), 'cleanup', 'a'),
                                       (None, 'cleanup', 'a'),
                                       (TokenUsage(cost=Decimal('2'), currency='CNY'), 'stt', 'b')]:
                report_usage(usage, scope=scope, provider='example', model=model, stage='test', emit=lambda text: None)
        usd = next(line for line in lines if 'scope=cleanup' in line)
        self.assertIn('cost=0.3 currency=USD', usd)
        self.assertIn('requests=3', usd)
        self.assertIn('cost_requests=2', usd)
        self.assertIn('partial=true', usd)
        self.assertIn('total_tokens=26', usd)
        combined = [line for line in lines if 'scope=all' in line]
        self.assertTrue(any('cost=0.3 currency=USD' in line for line in combined))
        self.assertTrue(any('cost=2 currency=CNY' in line for line in combined))
        self.assertFalse(any('cost=2.3' in line for line in lines))

    def test_failed_attempt_still_finalizes_summary_without_stale_charge(self):
        lines = []
        with self.assertRaisesRegex(RuntimeError, 'original'), usage_session(emit=lines.append):
            request_with_usage(lambda: {'usage': {'cost': '0.25'}}, scope='stt', provider='test',
                               model='x', currency='USD', emit=lambda line: None)
            request_with_usage(lambda: (_ for _ in ()).throw(RuntimeError('original')),
                               scope='stt', provider='test', model='x', emit=lambda line: None)
        self.assertEqual(len(lines), 1)
        self.assertIn('cost=0.25', lines[0])
        self.assertIn('requests=2', lines[0])
        self.assertIn('cost_requests=1', lines[0])

    def test_nested_sessions_context_and_quiet_do_not_duplicate_totals(self):
        lines, outer, inner = [], [], []
        with usage_session(emit=outer.append), usage_context(part=1, parts=3):
            with usage_session(emit=inner.append):
                request_with_usage(lambda: {'usage': {'total_tokens': 7}}, scope='stt', provider='test', model='x', emit=lines.append, attempt=2, part=2)
        self.assertIn('part=2 parts=3 attempt=2', lines[0])
        self.assertEqual(len(outer), 1)
        self.assertEqual(inner, [])
        silent = []
        with usage_session(emit=silent.append):
            report_usage(TokenUsage(1, 1, 2), scope='stt', provider='x', model='y', stage='test', emit=lambda _: None, visible=False)
        self.assertEqual(silent, [])

    def test_any_llm_adapter_uses_the_same_reporting_and_multiple_responses(self):
        class Example(LLMAdapter):
            def name(self):
                return 'new-provider'
            def generate(self, messages, **kwargs):
                for value in ('0.1', '0.2'):
                    self._record_response({'usage': {'cost': value, 'currency': 'USD'}})
                return 'unchanged output'
        adapter = Example(model='model')
        records = []
        with patch('scripts.llm_accounting.record', side_effect=lambda event, **fields: records.append(fields)):
            self.assertEqual(generate_with_usage(adapter, [], stage='cleanup'), 'unchanged output')
        self.assertEqual([record['cost'] for record in records], ['0.1', '0.2'])
        self.assertFalse(any('input_tokens' in record for record in records))

    def test_journal_errors_cannot_fail_requests_or_expose_payloads(self):
        with patch.dict(os.environ, {EVENT_FILE: '/missing/usage.jsonl'}):
            self.assertEqual(request_with_usage(lambda: {'usage': {'total_tokens': 1}, 'text': 'PRIVATE'},
                scope='stt', provider='x', model='y', emit=lambda line: self.assertNotIn('PRIVATE', line))['text'], 'PRIVATE')
