from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multitrack.sources import resolve
from multitrack.workflow import preflight, run
from multitrack.merging import read_timestamped_txt, name_source_events, merge_txt_files


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        config = patch("multitrack.sources.load_effective_config", return_value=({"multitrack": {"stop_after_merge": True}}, False))
        config.start()
        self.addCleanup(config.stop)

    def test_stop_reason_follows_effective_cleanup_policy(self):
        source = ['--source', 'a', '--file', 'a.wav']
        self.assertIn('multitrack.stop_after_merge=true', resolve(source)['stop_reason'])
        self.assertIn('--stop-after-merge', resolve(['--stop-after-merge', *source])['stop_reason'])
        self.assertIn('standalone', resolve(['--cleanup', *source], standalone=True)['stop_reason'])
        self.assertIsNone(resolve(['--cleanup', *source])['stop_reason'])

    def test_scope_and_conditional_recording(self):
        p = resolve(['--lang','uk','--source','a','--track','2','--name','Alice','movie.mkv'])
        self.assertEqual(p['sources'][0]['name'], 'Alice')
        self.assertFalse(p['cleanup'])
        self.assertEqual(resolve(['--source','x','--file','x.wav'])['sources'][0]['name'], 'Source_x')
        for args in [
            ['--source','a','--track','2'],
            ['--source','a','--file','x.wav','movie.mkv'],
            ['--source','a','--track','2','--file','x.wav','movie.mkv'],
            ['--source','a','--track','2','--llm-provider','gemini','movie.mkv'],
            ['--source','a','--track','2','--dry-run','movie.mkv'],
            ['--source','a','--track','0','movie.mkv'],
            ['--source','a','--track','2','movie.mkv','--lang','uk'],
            ['--source','a','--file','x','--source','a','--file','y'],
            ['--source','a','--file','x','--diarization','on'],
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                resolve(args)

    def test_misspelled_option_without_dashes_names_token_and_suggests_option(self):
        args = ['--no-long-summary', '--no-short-summary', '--provider', 'elevenlabs',
                '--lang', 'uk', '--additional-lang', 'de', 'dirization', 'off',
                '--source', 'Nazar', '--track', '2', '--source', 'Vitalii', '--track', '5',
                'recording.mkv']
        with self.assertRaisesRegex(ValueError, "unexpected positional argument 'dirization'.*Did you mean --diarization"):
            resolve(args)
        corrected = [*args[:8], '--diarization', *args[9:]]
        plan = resolve(corrected)
        self.assertEqual([s['diarization'] for s in plan['sources']], ['off', 'off'])

    def test_nonfinal_recording_error_names_path_without_spelling_guess(self):
        with self.assertRaises(ValueError) as raised:
            resolve(['--source', 'a', '--track', '2', 'recording with spaces.mkv', '--lang', 'uk'])
        self.assertIn("unexpected positional argument 'recording with spaces.mkv'", str(raised.exception))
        self.assertIn('recording must be the single final positional argument', str(raised.exception))
        self.assertNotIn('Did you mean', str(raised.exception))

    def test_preset_cli_precedence_and_source_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'preset.yaml'
            path.write_text('''defaults:
  provider: elevenlabs
  lang: uk
  additional_lang: [de]
  diarization: off
sources:
  - id: a
    track: 2
    lang: en
  - id: b
    file: original.wav
''')
            p = resolve(['--preset',str(path),'--lang','de','--source','a','--file','new.wav',
                         '--additional-lang','fr','--source','b','--track','5',
                         '--source','c','--file','third.wav','movie.mkv'])
            a,b,c = p['sources']
            self.assertNotIn('track', a)
            self.assertNotIn('file', b)
            self.assertEqual(a['lang'],'en')
            self.assertEqual(b['lang'],'de')
            self.assertEqual(a['additional_lang'],['fr'])
            self.assertEqual(c['additional_lang'],['de'])
            self.assertEqual(a['diarization'],'off')
            original = resolve(['--preset',str(path),'movie.mkv'])
            self.assertEqual(original['sources'][1]['file'], str(Path(tmp)/'original.wav'))

    def test_clear_languages_and_standalone_cleanup(self):
        p=resolve(['--cleanup','--additional-lang','de','--source','a','--file','a.wav','--no-additional-langs'],standalone=True)
        self.assertFalse(p['cleanup'])
        self.assertEqual(p['sources'][0]['additional_lang'],[])

    def test_cleanup_shared_options(self):
        p=resolve(['--llm-provider','dummy','--short-summary','--short-summary-lang','en',
                   '--long-summary','--long-summary-lang','de',
                   '--source','a','--file','a.wav'])
        self.assertEqual(p['cleanup_args'], [
            '--llm-provider','dummy','--short-summary','--short-summary-lang','en',
            '--long-summary','--long-summary-lang','de',
        ])


class TxtTests(unittest.TestCase):
    def test_names_and_merge_offsets_preserve_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b,out=(Path(tmp)/n for n in ['a.txt','b.txt','out.txt'])
            a.write_text('[00:00:01,000] [s0] Hello\n[00:00:03,000] [s1] Bye\n')
            b.write_text('[00:00:01,000] [Teacher] Reply\n')
            events=read_timestamped_txt(a)
            self.assertEqual([e.speaker for e in name_source_events(events,'Students','provider')],['Students_01','Students_02'])
            self.assertEqual(name_source_events(events[:1],'Student','provider')[0].speaker,'Student')
            self.assertEqual([e.speaker for e in name_source_events(events,'Student','off')],['Student','Student'])
            merge_txt_files([(a,0),(b,500)],out)
            self.assertEqual([e.start for e in read_timestamped_txt(out)],[1,1.5,3])
            with self.assertRaises(ValueError):
                merge_txt_files([(a,-2000)],out)
            a.write_text('untimed text\n')
            with self.assertRaises(ValueError):
                read_timestamped_txt(a)


class MediaIntegrationTests(unittest.TestCase):
    def test_real_extraction_fake_asr_cache_and_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            media=root/'two.mkv'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2',
                            '-f','lavfi','-i','sine=frequency=880:duration=0.2','-map','0:a','-map','1:a',
                            '-c:a','flac',str(media)],check=True)
            args=['--stop-after-merge','--dry-run','--workdir',str(root/'work'),'--outdir',str(root/'output'),'--srtoutdir',str(root/'transcripts'),'--provider','elevenlabs','--lang','uk',
                  '--source','a','--track','1','--source','b','--track','2',str(media)]
            calls=[]
            def provider(source,action,**kwargs):
                if action=='plan':return {'planned_chunks':1,'model':'fake'}
                calls.append(source['id'])
                path=kwargs['output']/'raw.txt'
                path.write_text('[00:00:00,010] [speaker0] Hello\n')
                return {'transcript_file':str(path)}
            with patch('multitrack.workflow.provider_call',side_effect=provider):
                plan=preflight(resolve(args))
                self.assertFalse((root/'work').exists())
                output=run(plan)
                self.assertEqual([e.speaker for e in read_timestamped_txt(output)],['Source_a','Source_b'])
                # Cleaning extracted media must not discard completed source reuse.
                for source in plan['sources']:
                    Path(source['audio_output']).unlink()
                run(plan)
                self.assertEqual(calls,['a','b'])
                plan['sources'][0]['name']='Renamed'
                run(plan)
                self.assertEqual(calls,['a','b','a'])
                plan['cleanup'] = True
                plan['cleanup_lang'] = 'uk'
                with patch('multitrack.workflow.subprocess.run') as cleanup:
                    run(plan)
                    command = cleanup.call_args.args[0]
                    self.assertTrue(command[0].endswith('lecture_cleanup.sh'))
                    self.assertIn(str(output), command)
                plan['cleanup'] = False
                for provider_name in ['groq', 'gemini', 'elevenlabs', 'speechcore']:
                    script = Path(__file__).resolve().parents[1] / f'process_localaudiovideo_via_{provider_name}.sh'
                    result = subprocess.run([str(script), '--lang', 'uk', str(media)], capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('2 audio streams', result.stdout + result.stderr)

                with self.assertRaisesRegex(ValueError,'2 audio streams'):
                    preflight(resolve(['--dry-run','--source','x','--file',str(media)]))
                with self.assertRaisesRegex(ValueError,'contains 2'):
                    preflight(resolve(['--dry-run','--source','x','--track','3',str(media)]))
                with patch('multitrack.workflow.provider_call',return_value={'planned_chunks':2}):
                    with self.assertRaisesRegex(ValueError,'stable speaker'):
                        preflight(resolve(['--dry-run','--provider','gemini','--diarization','provider',
                                           '--source','x','--track','1',str(media)]))


if __name__=='__main__':unittest.main()
