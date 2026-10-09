from __future__ import annotations

import subprocess
from contextlib import redirect_stderr
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multitrack.excerpts import parse_time, source_window
from multitrack.sources import resolve
from multitrack.workflow import preflight, run
from multitrack.merging import read_timestamped_txt


class ExcerptTests(unittest.TestCase):
    def test_time_formats_and_invalid_ranges(self):
        self.assertEqual(parse_time('00:01:10.125'), 70.125)
        self.assertEqual(parse_time('70.125'), 70.125)
        self.assertEqual(parse_time('100:00:00'), 360000)
        for value in ['-1', 'nan', 'inf', '00:60:00', '01:01', '1.1234', '1e3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value)
        for options in [['--start', '10', '--end', '10'], ['--start', '10', '--end', '9']]:
            with self.assertRaisesRegex(ValueError, 'greater'):
                resolve([*options, '--source', 'a', '--file', 'a.wav'])
        with self.assertRaisesRegex(ValueError, 'global-only'):
            resolve(['--source', 'a', '--file', 'a.wav', '--start', '10'])

    def test_window_offsets_and_partial_overlap(self):
        window = source_window(20, 5000, 10, 15)
        self.assertEqual(window, {'extract_start': 5, 'duration': 5, 'merge_offset_ms': 10000})
        self.assertEqual(source_window(20, -5000, 10, 15)['extract_start'], 15)
        self.assertEqual(source_window(20, 12000, 10, 15)['duration'], 3)
        self.assertEqual(source_window(20, 12000, 10, 15)['merge_offset_ms'], 12000)
        with self.assertRaisesRegex(ValueError, 'does not overlap'):
            source_window(20, 20000, 10, 15)

    def test_excerpt_output_names_are_distinct(self):
        full = resolve(['--source','a','--file','a.wav'])
        first = resolve(['--start','10','--end','70','--source','a','--file','a.wav'])
        second = resolve(['--start','70','--source','a','--file','a.wav'])
        self.assertEqual(len({p['workdir'] for p in [full,first,second]}), 3)
        self.assertEqual(len({p['output_name'] for p in [full,first,second]}), 3)

    def test_extraction_timing_reuse_and_changed_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root/'audio.wav'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                            'sine=frequency=440:duration=2','-c:a','pcm_s16le',str(media)],check=True)
            base = ['--dry-run','--workdir',str(root/'work'),'--provider','elevenlabs','--lang','uk']
            sources = ['--source','fixed','--file',str(media),'--name','Teacher',
                       '--source','detected','--file',str(media),'--name','Student',
                       '--offset-ms','250','--diarization','provider','--num-speakers','1']
            calls=[]
            def provider(source, action, **kwargs):
                if action == 'plan':
                    self.assertAlmostEqual(source['duration'], .75)
                    return {'planned_chunks':1, 'model':'fake'}
                calls.append(source['id'])
                duration = float(subprocess.check_output(['ffprobe','-v','error',
                    '-show_entries','format=duration','-of','default=nw=1:nk=1',source['input']],text=True))
                self.assertAlmostEqual(duration,.75,places=3)
                txt=kwargs['output']/'transcript.txt'
                txt.write_text('[00:00:00,010] [speaker_0] Hello\n')
                return {'transcript_file':str(txt)}
            with patch('multitrack.workflow.provider_call',side_effect=provider):
                plan = preflight(resolve([*base,'--start','0.5','--end','1.25',*sources]))
                self.assertFalse((root/'work').exists())
                self.assertEqual([s['extract_start'] for s in plan['sources']],[.5,.25])
                logs = StringIO()
                with redirect_stderr(logs):
                    events=read_timestamped_txt(run(plan))
                for message in ['hashing input', 'extracting 0.750s', 'provider preparation',
                                'Merging 2 source', 'multitrack.stop_after_merge=true']:
                    self.assertIn(message, logs.getvalue())
                self.assertNotIn('[DEBUG]', logs.getvalue())
                self.assertEqual([e.start for e in events],[.51,.51])
                self.assertEqual([e.speaker for e in events],['Teacher','Student'])
                run(plan)
                self.assertEqual(calls,['fixed','detected'])
                changed = preflight(resolve([*base,'--start','0.75','--end','1.5',*sources]))
                self.assertEqual(read_timestamped_txt(run(changed))[0].start,.76)
                self.assertEqual(calls,['fixed','detected','fixed','detected'])
            with patch('multitrack.workflow.provider_call',return_value={'planned_chunks':1}):
                with self.assertRaisesRegex(ValueError,'exceeds'):
                    preflight(resolve([*base,'--end','10',*sources]))
                with self.assertRaisesRegex(ValueError,'does not overlap'):
                    preflight(resolve([*base,'--start','10',*sources]))


if __name__ == '__main__':
    unittest.main()
