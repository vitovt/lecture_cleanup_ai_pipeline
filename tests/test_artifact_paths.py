from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import artifact_paths as paths
from scripts.run_pipeline import main
from tests.test_pipeline_summaries import PipelineAdapter

ROOT = paths.ROOT


class ArtifactPathsTests(unittest.TestCase):
    def test_destination_precedence_and_relative_bases(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            project, caller, home = (root / name for name in ('project', 'caller', 'home'))
            for path in (project, caller, home):
                path.mkdir()
            with patch.dict(os.environ, {'HOME': str(home)}), patch('pathlib.Path.cwd', return_value=caller):
                self.assertEqual(paths.destination('md', root=project), (project / 'output', False))
                (project / '.env').write_text('CLEANUP_MDOUTDIR="notes"\nTRANSCRIPT_OUTDIR="$HOME/transcripts"\n')
                self.assertEqual(paths.destination('md', root=project), (project / 'notes', True))
                self.assertEqual(paths.destination('transcript', root=project), (home / 'transcripts', True))
                self.assertEqual(paths.destination('md', 'notes', root=project), (caller / 'notes', True))
                self.assertEqual(paths.destination('md', '~/notes', root=project), (home / 'notes', True))

    def test_provider_config_cache_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'stt-api').mkdir()
            (root / 'stt-api/config.default.yaml').write_text('processing:\n  resume:\n    checkpoint_directory: null\n')
            (root / 'stt-api/config.yaml').write_text('processing:\n  resume:\n    checkpoint_directory: /custom/cache\n')
            with patch.object(paths, 'ROOT', root):
                self.assertEqual(paths.configured_cache('elevenlabs'), '/custom/cache')
                explicit = root / 'provider.yaml'
                explicit.write_text('processing:\n  resume:\n    checkpoint_directory: null\n')
                self.assertIsNone(paths.configured_cache('elevenlabs', str(explicit)))

    def test_custom_workdir_and_symlinks_are_not_cleanable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(paths, 'ROOT', root):
                work = root / 'input/_work/job'
                for custom in (False, True):
                    paths.write_record(work, inputs=['original.mkv'], outputs={}, custom_workdir=custom)
                    self.assertEqual(json.loads((work / 'run.json').read_text())['automatic_cleaning_allowed'], not custom)
                external = root / 'external'
                external.mkdir()
                link = root / 'input/_work/link'
                link.symlink_to(external, target_is_directory=True)
                paths.write_record(link, inputs=[], outputs={})
                self.assertFalse(json.loads((external / 'run.json').read_text())['automatic_cleaning_allowed'])

    def test_shell_jobs_share_final_names_but_keep_provider_artifacts_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            for filename in ('artifact_paths.py', 'artifact_paths.sh'):
                shutil.copy2(ROOT / 'scripts' / filename, root / 'scripts' / filename)
            (root / '.env').write_text('CLEANUP_MDOUTDIR="notes"\nTRANSCRIPT_OUTDIR="texts"\n')
            command = '''
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/artifact_paths.sh"
LECTURE_CLEANUP_FLAGS=()
workflow_path_defaults || exit $?
workflow_prepare_job "$SCRIPT_DIR/original.wav" lesson || exit $?
printf '%s\\n' "$WORKDIR" "$OUT_MD" "$TRANSCRIPT_DIR"
printf 'transcript\\n' > "$SRTOUTDIR/raw.txt"
workflow_publish_transcript "$SRTOUTDIR/raw.txt" lesson || exit $?
'''
            jobs = []
            for provider in ('one', 'two'):
                result = subprocess.run(['bash', '-c', command, provider, str(root)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                work, md, transcripts = result.stdout.splitlines()
                jobs.append(work)
                self.assertEqual(md, str(root / 'notes/lesson.md'))
                self.assertEqual(transcripts, str(root / 'texts'))
                self.assertEqual(list((root / 'texts').iterdir()), [root / 'texts/lesson.txt'])
                record = json.loads((Path(work) / 'run.json').read_text())
                self.assertTrue(record['outputs']['markdown']['overridden'])
            self.assertNotEqual(*jobs)
            (root / 'notes').mkdir()
            (root / 'notes/lesson.md').write_text('keep me')
            result = subprocess.run(['bash', '-c', command, 'three', str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Markdown already exists', result.stderr)
            self.assertEqual(len(list((root / 'input/_work').iterdir())), 2)


    def test_local_wrappers_publish_only_final_transcripts_and_guard_other_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('scripts', 'subtitle-utils', 'groq-api', 'stt-api', 'speechcoreai-api'):
                (root / name).mkdir()
            for helper in (ROOT / 'scripts').glob('*_shell_common.sh'):
                shutil.copy2(helper, root / 'scripts' / helper.name)
            for name in ('artifact_paths.py', 'artifact_paths.sh', 'config_loader.py'):
                shutil.copy2(ROOT / 'scripts' / name, root / 'scripts' / name)
            shutil.copy2(ROOT / 'config.default.yaml', root / 'config.default.yaml')
            shutil.copy2(ROOT / 'subtitle-utils/audio_streams.py', root / 'subtitle-utils/audio_streams.py')
            (root / 'subtitle-utils/sanitize_filename.sh').write_text('sanitize_filename() { printf "%s" "$1"; }\n')
            for package in ('stt-api', 'groq-api'):
                binary = root / package / '.venv/bin/python'
                binary.parent.mkdir(parents=True)
                binary.symlink_to(sys.executable)
            for provider in ('elevenlabs', 'gemini'):
                helper = root / 'scripts' / f'{provider}_shell_common.sh'
                with helper.open('a') as handle:
                    handle.write(f'\n{provider}_init() {{ :; }}\n')
            stub = r'''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
def option(name, default=None):
    return args[args.index(name)+1] if name in args else default
if 'validate' in args:
    print('VALID timestamps=on diarization=off')
    raise SystemExit()
with open(os.environ['PAID_CALLS'], 'a') as handle:
    handle.write('call\n')
output = Path(option('--output-dir'))
output.mkdir(parents=True, exist_ok=True)
name = option('--output-basename', Path(option('--input-file')).stem)
transcript = output / (name + '.txt')
transcript.write_text('[00:00:00,000] [speaker_0] A transcript.\n')
metadata = option('--metadata-output')
if metadata:
    Path(metadata).write_text(json.dumps({'transcript_file': str(transcript), 'model': 'fake', 'detected_language': 'uk'}))
'''
            for name in ('groq-api/groq_api.sh', 'stt-api/stt_api.sh', 'speechcoreai-api/speechcoreai_cli.py'):
                executable = root / name
                executable.write_text(f'#!{sys.executable}\n' + stub)
                executable.chmod(0o755)
            (root / 'groq-api/groq_cli.py').touch()
            cleanup = root / 'lecture_cleanup.sh'
            cleanup.write_text(f'#!{sys.executable}\n' + r'''import sys
from pathlib import Path
args = sys.argv[1:]
source = Path(args[args.index('--input')+1])
out = Path(args[args.index('--outdir')+1])
out.mkdir(parents=True, exist_ok=True)
(out/(source.stem+'.md')).write_text('Cleaned text')
''')
            cleanup.chmod(0o755)
            media = root / 'lesson.wav'
            with wave.open(str(media), 'wb') as audio:
                audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 800)
            env = {**os.environ, 'PAID_CALLS': str(root / 'calls')}
            for provider in ('groq', 'elevenlabs', 'gemini', 'speechcore'):
                script = root / f'process_localaudiovideo_via_{provider}.sh'
                shutil.copy2(ROOT / script.name, script)
                command = [str(script), '--lang', 'uk', '--outdir', str(root/'notes'), '--srtoutdir', str(root/'texts'), str(media)]
                result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([p.name for p in (root/'texts').iterdir()], ['lesson.txt'])
                self.assertTrue((root/'notes/lesson.md').is_file())
                count = (root/'calls').read_text()
                again = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(again.returncode, 2, again.stdout + again.stderr)
                self.assertEqual((root/'calls').read_text(), count)
                (root/'notes/lesson.md').unlink()
            self.assertEqual(len(list((root/'input/_work').glob('*/run.json'))), 4)

    def test_cleanup_refuses_existing_markdown_before_llm_and_overwrite_is_explicit(self):
        cfg = yaml.safe_load((ROOT / 'config.default.yaml').read_text())
        self.assertEqual(cfg['qc_report_mode'], 'off')
        cfg['logging']['level'] = 'quiet'
        cfg['summary']['short']['enabled'] = False
        cfg['summary']['long']['enabled'] = False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'lesson.txt'
            source.write_text('A sufficiently long lecture sentence for pipeline testing. ' * 8)
            target = root / 'lesson.md'
            target.write_text('original')
            argv = ['run_pipeline', '--input', str(source), '--lang', 'en', '--outdir', str(root)]
            adapter = PipelineAdapter()
            with patch('scripts.run_pipeline.load_effective_config', return_value=(cfg, True)), patch(
                'scripts.run_pipeline.create_llm_adapter', return_value=adapter
            ) as factory:
                with patch('sys.argv', argv):
                    self.assertEqual(main(), 2)
                factory.assert_not_called()
                self.assertEqual(target.read_text(), 'original')
                with patch('sys.argv', [*argv, '--overwrite']):
                    self.assertEqual(main(), 0)
                self.assertIn('Cleaned content', target.read_text())
                self.assertFalse(list(root.glob('*.csv')))


if __name__ == '__main__':
    unittest.main()
