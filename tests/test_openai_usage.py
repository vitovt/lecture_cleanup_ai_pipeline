"""Responses API usage reporting with a mocked SDK and no paid requests."""
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from aiadapters.base import LLMConnectionError
from aiadapters.openai_adapter import OpenAIAdapter
from scripts.llm_accounting import generate_with_usage
from scripts.run_pipeline import call_llm
from scripts.summary_generation import (
    generate_summaries, LONG_SUMMARY_START, LONG_SUMMARY_END,
    SHORT_SUMMARY_START, SHORT_SUMMARY_END,
)
from scripts.summary_settings import resolve_summary_settings


def usage(input_tokens=100, output_tokens=30, total_tokens=130, cached=40, reasoning=20):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           total_tokens=total_tokens,
                           input_tokens_details=SimpleNamespace(cached_tokens=cached),
                           output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))


class OpenAIUsageTests(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(responses=SimpleNamespace(create=Mock()))
        sdk = SimpleNamespace(OpenAI=Mock(return_value=self.client))
        with patch.dict(sys.modules, {'openai': sdk}), \
             patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}):
            self.adapter = OpenAIAdapter(model='test-model', temperature=1, top_p=1)

    def generate(self, tokens, text='Cleaned text'):
        self.client.responses.create.return_value = SimpleNamespace(usage=tokens, output_text=text)
        records = []
        with patch('scripts.llm_accounting.record', side_effect=lambda event, **fields: records.append(fields)):
            result = generate_with_usage(self.adapter, [{'role': 'user', 'content': 'Transcript'}],
                                         stage='cleanup', model='test-model')
        return result, records[0] if records else None

    def test_sdk_usage_reaches_per_request_records_without_changing_request(self):
        result, record = self.generate(usage())
        self.assertEqual(result, 'Cleaned text')
        self.assertEqual(record['provider'], 'openai')
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['input_tokens'], 100)
        self.assertEqual(record['output_tokens'], 30)
        self.assertEqual(record['total_tokens'], 130)
        self.assertEqual(record['cache_hit_tokens'], 40)
        self.assertEqual(record['cache_miss_tokens'], 60)
        self.assertEqual(record['reasoning_tokens'], 20)
        self.client.responses.create.assert_called_once_with(
            model='test-model', temperature=1, top_p=1,
            input=[{'role': 'user', 'content': 'Transcript'}])

    def test_zero_usage_is_valid_and_missing_breakdowns_are_omitted(self):
        _, record = self.generate(SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0))
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['total_tokens'], 0)
        self.assertNotIn('cache_hit_tokens', record)
        self.assertNotIn('cache_miss_tokens', record)
        self.assertNotIn('reasoning_tokens', record)

    def test_missing_or_invalid_usage_never_reuses_previous_counts(self):
        for tokens in (None, {}, usage(input_tokens=True), usage(input_tokens=-1),
                       usage(input_tokens='100'), usage(total_tokens=999)):
            with self.subTest(tokens=tokens):
                self.generate(usage())
                result, record = self.generate(tokens)
                self.assertEqual(result, 'Cleaned text')
                self.assertIsNone(record)
                self.assertIsNone(self.adapter.last_usage)

    def test_invalid_optional_counts_do_not_destroy_valid_core_counts(self):
        _, record = self.generate(usage(cached=101, reasoning=31))
        self.assertEqual(record['status'], 'ok')
        self.assertNotIn('cache_hit_tokens', record)
        self.assertNotIn('cache_miss_tokens', record)
        self.assertNotIn('reasoning_tokens', record)
        self.assertEqual(record['total_tokens'], 130)

    def test_error_resets_usage_even_for_direct_adapter_calls(self):
        self.generate(usage())
        self.client.responses.create.side_effect = RuntimeError('connection failed')
        with self.assertRaises(LLMConnectionError):
            self.adapter.generate([])
        self.assertIsNone(self.adapter.last_usage)

    def test_failed_request_omits_missing_counts(self):
        self.generate(usage())
        self.client.responses.create.side_effect = RuntimeError('connection failed')
        records = []
        with patch('scripts.llm_accounting.record', side_effect=lambda event, **fields: records.append(fields)):
            with self.assertRaises(LLMConnectionError):
                generate_with_usage(self.adapter, [], stage='summary', model='test-model')
        self.assertEqual(records, [])
        self.assertIsNone(self.adapter.last_usage)

    def test_cleanup_and_each_summary_retry_report_their_own_usage(self):
        good = f'{LONG_SUMMARY_START}\nLong\n{LONG_SUMMARY_END}\n{SHORT_SUMMARY_START}\nShort\n{SHORT_SUMMARY_END}'
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text=text, usage=usage()) for text in
            ('Cleaned lecture', 'Invalid summary markers', good)]
        settings = resolve_summary_settings({'summary': {'short': {'enabled': True},
                                                        'long': {'enabled': True}}}, 'en')
        records = []
        with patch('scripts.llm_accounting.record', side_effect=lambda event, **fields: records.append(fields)):
            self.assertEqual(call_llm(self.adapter, 'test-model', 'System', 'Text', 'en', [],
                                      'italic', [], '', usage_context={'part': 2, 'attempt': 1}),
                             'Cleaned lecture')
            self.assertEqual(generate_summaries(self.adapter, 'test-model', 'Cleaned lecture', settings,
                                               attempts=2, pause_seconds=0, request_delay=0),
                             {'long': 'Long', 'short': 'Short'})
        self.assertEqual([record['stage'] for record in records], ['cleanup', 'summary', 'summary'])
        self.assertEqual([record['attempt'] for record in records], [1, 1, 2])
        self.assertEqual(records[0]['part'], 2)
        self.assertEqual(sum(record['total_tokens'] for record in records), 390)
        self.assertEqual(self.client.responses.create.call_count, 3)
