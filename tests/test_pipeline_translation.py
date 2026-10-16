"""Offline translation controls and unchanged legacy cleanup requests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import run_pipeline as pipeline
from tests.test_pipeline_summaries import PipelineAdapter, RecordingAdapter

ROOT = Path(__file__).resolve().parents[1]


class TranslationPromptTests(unittest.TestCase):
    def request(self, translate_to=None):
        adapter = RecordingAdapter('Result')
        system = 'Keep the original language unless the author clearly switches languages.'
        response = pipeline.call_llm(adapter, 'model', system,
            '[00:00:01,000] Bonjour le monde.', 'fr', ['euh'], 'italic', ['FFmpeg'],
            'Keep timestamps unchanged.', translate_to=translate_to)
        self.assertEqual(response, 'Result')
        return adapter.calls[0][0], system

    def test_without_translation_requests_are_byte_for_byte_unchanged(self):
        messages, system = self.request()
        expected = (ROOT / 'tests/fixtures/cleanup_user_prompt_without_translation.md').read_text()
        self.assertEqual(messages, [{'role': 'system', 'content': system},
                                    {'role': 'user', 'content': expected}])

    def test_translation_keeps_source_language_and_overrides_output_language(self):
        messages, system = self.request('uk')
        self.assertTrue(messages[0]['content'].startswith(system + '\n\nException:'))
        self.assertIn('ISO-639-1 code uk', messages[0]['content'])
        self.assertIn('overrides instructions to preserve', messages[0]['content'])
        user = messages[1]['content']
        self.assertIn('Language of this fragment: fr\nAfter cleanup, translate', user)
        self.assertIn('ISO-639-1 code uk', user)
        self.assertIn('Filler words for this language (remove only if safe): [euh]', user)
        self.assertIn('timestamps, links, block IDs', user)
        self.assertIn('[00:00:01,000] Bonjour le monde.', user)

    def test_translation_language_is_optional_normalized_and_validated(self):
        parser = pipeline.build_parser()
        args = ['--input', 'lecture.txt', '--lang', 'fr']
        self.assertIsNone(parser.parse_args(args).translate_to)
        self.assertEqual(parser.parse_args(args + ['--translate-to', 'UK']).translate_to, 'uk')
        for value in ('', 'auto', 'default', 'uk-UA', 'Ukrainian', '--lang'):
            with self.subTest(value=value), patch('sys.stderr'):
                with self.assertRaises(SystemExit) as error:
                    parser.parse_args(args + ['--translate-to', value])
                self.assertEqual(error.exception.code, 2)


class TranslationPipelineTests(unittest.TestCase):
    def run_pipeline(self, flags=(), short_lang='default', long_lang='default'):
        config = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
        config['llm'].update(provider='dummy', dummy={'model': 'test-model'}, request_delay_seconds=0)
        config['retry']['attempts'] = 1
        config['logging']['level'] = 'quiet'
        config['qc_report_mode'] = 'off'
        config['summary']['short'].update(enabled=True, lang=short_lang)
        config['summary']['long'].update(enabled=True, lang=long_lang)
        config['txt_chunk_chars'] = 120
        config['txt_overlap_chars'] = 0
        config['rebalance_small_tail_chunks'] = False
        adapter = PipelineAdapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'lecture.txt'
            source.write_text('Bonjour. Ceci est une phrase suffisamment longue pour ce test.\n' * 12)
            args = ['run_pipeline.py', '--input', str(source), '--outdir', str(root / 'out'),
                    '--lang', 'fr', *flags]
            with patch.object(pipeline, 'load_effective_config', return_value=(config, True)), \
                    patch.object(pipeline, 'create_llm_adapter', return_value=adapter), \
                    patch('sys.argv', args):
                self.assertEqual(pipeline.main(), 0)
            self.assertTrue((root / 'out/lecture.md').is_file())
        return adapter.calls, config

    def test_all_chunks_receive_translation_but_summary_requests_do_not(self):
        calls, config = self.run_pipeline(['--translate-to', 'uk'])
        chunks = [c for c in calls if c[1].get('label', '').startswith('chunk')]
        self.assertGreater(len(chunks), 1)
        original_system = (ROOT / 'prompts' / f"system_{config['content_mode']}.md").read_text()
        for messages, _ in chunks:
            self.assertTrue(messages[0]['content'].startswith(original_system + '\n\nException:'))
            self.assertIn('ISO-639-1 code uk', messages[0]['content'])
            self.assertIn('Language of this fragment: fr\nAfter cleanup, translate', messages[1]['content'])
        summary_system = calls[-1][0][0]['content']
        self.assertIn('code `uk`', summary_system)
        self.assertNotIn('Exception: after cleanup', summary_system)

    def test_explicit_summary_languages_override_translation_fallback(self):
        for flags, short, long in ((['--translate-to', 'uk'], 'de', 'en'),
                                  (['--translate-to', 'uk', '--short-summary-lang', 'de',
                                    '--long-summary-lang', 'en'], 'default', 'default')):
            with self.subTest(flags=flags):
                calls, _ = self.run_pipeline(flags, short, long)
                long_system, short_system = calls[-1][0][0]['content'].split('[SHORT SUMMARY SYSTEM INSTRUCTIONS]')
                self.assertIn('code `en`', long_system)
                self.assertIn('`de`', short_system)

    def test_without_translation_system_prompts_and_summary_language_are_unchanged(self):
        calls, config = self.run_pipeline()
        system = (ROOT / 'prompts' / f"system_{config['content_mode']}.md").read_text()
        for messages, kwargs in calls[:-1]:
            self.assertEqual(messages[0]['content'], system)
            self.assertIn('Language of this fragment: fr\nFiller words', messages[1]['content'])
            self.assertNotIn('After cleanup, translate', messages[1]['content'])
        self.assertIn('code `fr`', calls[-1][0][0]['content'])
