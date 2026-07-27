from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

PUBLIC_SHELL_SCRIPTS = (
    "auto_process_youtube.sh",
    "auto_process_youtube_list.sh",
    "auto_process_youtube_via_groq.sh",
    "auto_process_youtube_list_via_groq.sh",
    "auto_process_youtube_via_speechcore.sh",
    "auto_process_youtube_list_via_speechcore.sh",
    "manual_process_youtube.sh",
    "process_localaudiovideo_via_groq.sh",
    "process_localaudiovideo_via_groq_list.sh",
    "process_localaudiovideo_via_speechcore.sh",
    "process_localaudiovideo_via_speechcore_list.sh",
)


class ShellHelpTests(unittest.TestCase):
    def test_public_workflow_scripts_support_help(self) -> None:
        for relative_path in PUBLIC_SHELL_SCRIPTS:
            with self.subTest(script=relative_path):
                result = subprocess.run(
                    [str(PROJECT / relative_path), "--help"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Usage:", result.stdout)

    def test_unknown_long_options_are_rejected(self) -> None:
        for relative_path in PUBLIC_SHELL_SCRIPTS:
            with self.subTest(script=relative_path):
                result = subprocess.run(
                    [str(PROJECT / relative_path), "--definitely-unknown"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, 2, combined)
                self.assertIn("unknown option", combined.lower())

    def test_youtube_transcription_help_uses_lang_with_auto_default(self) -> None:
        scripts = (
            "auto_process_youtube_via_groq.sh",
            "auto_process_youtube_list_via_groq.sh",
            "auto_process_youtube_via_speechcore.sh",
            "auto_process_youtube_list_via_speechcore.sh",
        )
        for relative_path in scripts:
            with self.subTest(script=relative_path):
                result = subprocess.run(
                    [str(PROJECT / relative_path), "--help"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertIn("--lang CODE|auto", result.stdout)
                self.assertRegex(result.stdout, r"--lang CODE\|auto[^\n]*default: auto")
                self.assertNotIn("--language", result.stdout)


class YoutubeLanguageDefaultTests(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def test_single_video_passes_auto_without_subtitle_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "subtitle-utils").mkdir()
            (root / "groq-api").mkdir()
            (root / "bin").mkdir()

            for relative_path in (
                "auto_process_youtube_via_groq.sh",
                "scripts/groq_shell_common.sh",
                "subtitle-utils/normalize_youtube_url.py",
                "subtitle-utils/sanitize_filename.sh",
            ):
                destination = root / relative_path
                shutil.copy2(PROJECT / relative_path, destination)

            (root / "groq-api/groq_cli.py").write_text("", encoding="utf-8")
            captured_args = root / "groq-args.txt"
            yt_dlp_calls = root / "yt-dlp-calls.txt"
            self._write_executable(
                root / "groq-api/groq_api.sh",
                """#!/usr/bin/env bash
printf '%s\n' "$@" > "$CAPTURED_GROQ_ARGS"
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--preflight-output" ]]; then
        printf '{}\n' > "$2"
        exit 0
    fi
    shift
done
exit 0
""",
            )
            self._write_executable(
                root / "bin/yt-dlp",
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$YT_DLP_CALLS"
for arg in "$@"; do
    if [[ "$arg" == "--print" ]]; then
        printf '20260727\nTest video.mp4\n'
        exit 0
    fi
done
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then
        output="${2//%(ext)s/mp3}"
        mkdir -p "$(dirname "$output")"
        : > "$output"
        exit 0
    fi
    shift
done
exit 0
""",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{root / 'bin'}:{env['PATH']}",
                    "CAPTURED_GROQ_ARGS": str(captured_args),
                    "YT_DLP_CALLS": str(yt_dlp_calls),
                }
            )
            result = subprocess.run(
                [
                    str(root / "auto_process_youtube_via_groq.sh"),
                    "--info",
                    "--srtoutdir",
                    str(root / "transcripts"),
                    "--outdir",
                    str(root / "output"),
                    "--preflight",
                    "--preflight-output",
                    str(root / "preflight.json"),
                    "https://youtu.be/dQw4w9WgXcQ",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            groq_args = captured_args.read_text(encoding="utf-8").splitlines()
            language_index = groq_args.index("--language")
            self.assertEqual(groq_args[language_index + 1], "auto")
            self.assertNotIn(
                "--list-subs",
                yt_dlp_calls.read_text(encoding="utf-8"),
            )

    def test_playlist_forwards_explicit_auto_default(self) -> None:
        content = (PROJECT / "auto_process_youtube_list_via_groq.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('LANG="auto"', content)
        self.assertIn('CHILD_FLAGS+=(--lang "$LANG")', content)

    def test_speechcore_single_and_playlist_share_auto_default(self) -> None:
        single = (PROJECT / "auto_process_youtube_via_speechcore.sh").read_text(
            encoding="utf-8"
        )
        playlist = (
            PROJECT / "auto_process_youtube_list_via_speechcore.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('LANG_OVERRIDE="auto"', single)
        self.assertIn('if [[ "$LANG_OVERRIDE" != "auto" ]]', single)
        self.assertIn('LANG="auto"', playlist)
        self.assertIn('CHILD_FLAGS+=(--lang "$LANG")', playlist)


if __name__ == "__main__":
    unittest.main()
