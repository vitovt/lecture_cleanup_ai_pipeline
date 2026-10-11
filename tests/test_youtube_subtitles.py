"""Offline regression checks for the automatic subtitle workflow."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class YoutubeSubtitleTests(unittest.TestCase):
    def run_workflow(self, mode, language="en-US-orig"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "auto_process_youtube.sh",
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
import os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ['TEST_MODE']
lang = os.environ['TEST_LANGUAGE']
if '--list-subs' in args:
    if mode == 'probe_failure': sys.exit(1)
    print(lang + ' English (Original) vtt, srt')
    print('20260921')
elif '--print' in args:
    print('10' if args[args.index('--print') + 1] == '%(duration)s' else 'Test video.mp4')
else:
    if mode == 'download_failure': sys.exit(1)
    if mode == 'missing': sys.exit(0)
    assert args[args.index('--sub-lang') + 1] == lang
    output = args[args.index('-o') + 1].replace('%(ext)s', lang + '.srt')
    Path(output).write_text('invalid' if mode == 'invalid' else '1\\n00:00:00,000 --> 00:00:01,000\\nHello\\n')
''')
            downloader.chmod(0o755)
            cleanup = root / "lecture_cleanup.sh"
            cleanup.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > captured_args\n')
            cleanup.chmod(0o755)
            env = dict(os.environ, PATH=f"{root / 'bin'}:{os.environ['PATH']}",
                       TEST_MODE=mode, TEST_LANGUAGE=language)
            result = subprocess.run(
                ["bash", str(root / "auto_process_youtube.sh"),
                 "--log-level", "info",
                 "--srtoutdir", str(root / "input"),
                 "--outdir", str(root / "output"), "https://youtu.be/gugUQtOQkQY"],
                cwd=root, env=env, capture_output=True, text=True,
            )
            captured = root / "captured_args"
            args = captured.read_text() if captured.exists() else ""
            txts = list((root / "input").glob("*.txt"))
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
