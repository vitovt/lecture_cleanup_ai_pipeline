"""Offline regression checks for chunk boundaries and overlap requests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import run_pipeline as pipeline
from scripts.utils import (
    align_chunk_sentence_boundaries, chunk_text_line_preserving,
)
from tests.test_pipeline_summaries import PipelineAdapter

ROOT = Path(__file__).resolve().parents[1]


def new_units(chunks):
    return [[u for u in ch['_units'][ch['_overlap_units']:]] for ch in chunks]


class SentenceBoundaryTests(unittest.TestCase):
    def test_moves_unfinished_sentence_without_losing_source_indices(self):
        lines = ['[00:00:01] Модели недетерминированы и поэтому склонны совершать ошибки.',
                 '[00:00:02] По закону Мёрфи,',
                 '[00:00:03] всё пойдёт наперекосяк,',
                 '[00:00:04] особенно там, где цена ошибки велика.']
        limit = len('\n'.join(lines[:3]))
        original = chunk_text_line_preserving(lines, limit, 0)
        adjusted = align_chunk_sentence_boundaries(original, limit, 20)
        self.assertEqual(len(adjusted), 2)
        self.assertEqual(new_units(adjusted)[0][-1]['orig'], 0)
        self.assertEqual(new_units(adjusted)[1][0]['orig'], 1)
        self.assertEqual([u for group in new_units(original) for u in group],
                         [u for group in new_units(adjusted) for u in group])
        self.assertTrue(all(len(ch['text']) <= limit for ch in adjusted))

    def test_preserves_boundary_when_no_sentence_end_or_no_room(self):
        for lines in (['aaaaaa,', 'bbbbbb,', 'cccccc,', 'dddddd,'],
                      ['aaaaaa.', 'bbbbbb,', 'cccccc,', 'dddddd.']):
            with self.subTest(lines=lines):
                chunks = chunk_text_line_preserving(lines, 15, 0)
                self.assertEqual(new_units(align_chunk_sentence_boundaries(chunks, 15, 0)),
                                 new_units(chunks))


class OverlapRequestTests(unittest.TestCase):
    def test_cleaned_raw_and_skipped_predecessor_context(self):
        for mode, selection, expected in (
            ('cleaned', None, 'Cleaned content.'),
            ('raw', None, 'RAW SOURCE'),
            ('cleaned', '2', 'RAW SOURCE'),
        ):
            with self.subTest(mode=mode, selection=selection), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'lecture.txt'
                source.write_text(('RAW SOURCE with deliberately different wording.\n' * 12))
                cfg = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
                cfg['llm'].update(provider='dummy', request_delay_seconds=0)
                cfg.update(txt_chunk_chars=120, txt_overlap_chars=65,
                           use_context_overlap=mode, rebalance_small_tail_chunks=False,
                           qc_report_mode='off', include_timecodes_in_headings=False,
                           include_timecodes_below_headings=False, include_src_block_ids=False)
                cfg['summary']['short']['enabled'] = False
                cfg['summary']['long']['enabled'] = False
                cfg['logging']['level'] = 'quiet'
                adapter = PipelineAdapter()
                args = ['pipeline', '--input', str(source), '--outdir', str(root / 'out'), '--lang', 'en']
                if selection:
                    args.extend(['--chunks', selection])
                with patch.object(pipeline, 'load_effective_config', return_value=(cfg, True)), \
                     patch.object(pipeline, 'create_llm_adapter', return_value=adapter), \
                     patch('sys.argv', args):
                    self.assertEqual(pipeline.main(), 0)
                request = adapter.calls[0 if selection else 1][0][1]['content']
                context = request.split('Previous fragment context', 1)[1].split('<<<', 1)[1].split('>>>', 1)[0]
                self.assertIn(expected, context)
                if mode == 'cleaned' and not selection:
                    self.assertNotIn('RAW SOURCE', context)
