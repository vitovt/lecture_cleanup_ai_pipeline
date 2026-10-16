"""Offline regression checks for the automatic subtitle workflow."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class YoutubeSubtitleTests(unittest.TestCase):
    def run_workflow(self, mode, language="en-US-orig", flags=(), standalone=False, config=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "auto_process_youtube.sh",
                "config.default.yaml",
                "scripts/config_loader.py",
                "subtitle-utils/download_youtube_subtitles.sh",
                "subtitle-utils/select_youtube_subtitles.py",
                "subtitle-utils/youtube_subtitle_selection.sh",
                "scripts/lecture_cleanup_shell_common.sh",
                "scripts/artifact_paths.sh",
                "scripts/artifact_paths.py",
                "subtitle-utils/normalize_youtube_url.py",
                "subtitle-utils/sanitize_filename.sh",
                "subtitle-utils/srt_to_custom.py",
                "subtitle-utils/subtitle_timing.py",
                "prompts/custom_context_general/youtube-url-timecodes.txt",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT / relative, target)
            (root / "bin").mkdir()
            downloader = root / "bin/yt-dlp"
            downloader.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ['TEST_MODE']
lang = os.environ['TEST_LANGUAGE']
if '--dump-single-json' in args:
    if mode == 'probe_failure': sys.exit(1)
    entries = [{'url': 'https://example.com/sub?lang='+lang.removesuffix('-orig')+'&kind=asr', 'ext': 'vtt', 'name': 'Original'}]
    info = {'upload_date': '20260921', 'automatic_captions': {lang: entries}, 'subtitles': {}}
    if mode == 'both':
        info['subtitles'][lang.removesuffix('-orig')] = [{'url': 'https://example.com/manual', 'ext': 'vtt', 'name': 'English'}]
    print(json.dumps(info))
elif '--get-filename' in args:
    print('Test video.mp4')
elif '--print' in args:
    print('10' if args[args.index('--print') + 1] == '%(duration)s' else 'Test video.mp4')
else:
    if mode == 'download_failure': sys.exit(1)
    if mode == 'missing': sys.exit(0)
    selected = args[args.index('--sub-lang') + 1]
    info = json.loads(Path(args[args.index('--load-info-json') + 1]).read_text())
    field = 'subtitles' if '--write-subs' in args else 'automatic_captions'
    assert selected in info[field]
    assert not info['automatic_captions' if field == 'subtitles' else 'subtitles']
    lang = selected
    output = args[args.index('-o') + 1].replace('%(ext)s', lang + '.srt')
    Path(output).write_text('invalid' if mode == 'invalid' else '1\\n00:00:00,000 --> 00:00:01,000\\nHello\\n')
''')
            downloader.chmod(0o755)
            cleanup = root / "lecture_cleanup.sh"
            cleanup.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > captured_args\n')
            cleanup.chmod(0o755)
            env = dict(os.environ, PATH=f"{root / 'bin'}:{os.environ['PATH']}",
                       TEST_MODE=mode, TEST_LANGUAGE=language)
            if config:
                (root / "config.yaml").write_text(config)
            command = ["bash", str(root / ("subtitle-utils/download_youtube_subtitles.sh" if standalone else "auto_process_youtube.sh"))]
            if not standalone:
                command += ["--log-level", "info", "--srtoutdir", str(root / "input"), "--outdir", str(root / "output")]
            command += list(flags) + ["https://youtu.be/gugUQtOQkQY"]
            result = subprocess.run(
                command,
                cwd=root, env=env, capture_output=True, text=True,
            )
            captured = root / "captured_args"
            args = captured.read_text() if captured.exists() else ""
            txts = list((root if standalone else root / "input").glob("*.txt"))
            return result, args, [p.read_text() for p in txts]

    def test_regional_and_plain_language_codes(self):
        for track, expected in (("en-US-orig", "en-US"), ("uk-orig", "uk")):
            with self.subTest(track=track):
                result, args, txts = self.run_workflow("success", track)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"--lang={expected}\n", args)
                self.assertEqual(txts, ["[00:00:00,000] Hello\n"])

    def test_failures_stop_before_ai_and_do_not_create_txt(self):
        for mode in ("probe_failure", "download_failure", "missing", "invalid"):
            with self.subTest(mode=mode):
                result, args, txts = self.run_workflow(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(args, "")
                self.assertEqual(txts, [])
                self.assertNotIn("[✓]", result.stdout)

    def test_source_policies_in_both_entrypoints(self):
        for standalone in (False, True):
            for flags, expected in (((), "auto"), (("--subtitle-source", "manual"), "manual"),
                                    (("--subtitle-source=prefer-manual",), "manual")):
                with self.subTest(standalone=standalone, flags=flags):
                    result, _, txts = self.run_workflow("both", flags=flags, standalone=standalone)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(f"Selected {expected} subtitles:", result.stdout + result.stderr)
                    self.assertEqual(len(txts), 1)
            result, _, txts = self.run_workflow("success", flags=("--subtitle-source", "manual"), standalone=standalone)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(txts, [])

    def test_config_and_cli_precedence(self):
        config = "autoyoutube:\n  subtitle_source: manual\n  lang: de\n"
        for standalone in (False, True):
            result, _, _ = self.run_workflow("both", config=config, standalone=standalone)
            self.assertNotEqual(result.returncode, 0)
            result, _, _ = self.run_workflow("both", config=config, standalone=standalone,
                                            flags=("--lang", "en-US", "--subtitle-source", "auto"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Selected auto subtitles:", result.stdout + result.stderr)

    def test_translation_is_forwarded_without_changing_subtitle_language(self):
        result, args, txts = self.run_workflow('success', 'fr-orig', flags=('--translate-to', 'uk'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--lang=fr\n', args)
        self.assertIn('--translate-to\nuk\n', args)
        self.assertIn('Selected auto subtitles: fr-orig', result.stdout)
        self.assertEqual(txts, ['[00:00:00,000] Hello\n'])
