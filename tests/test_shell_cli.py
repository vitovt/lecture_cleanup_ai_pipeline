from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]

PUBLIC_SHELL_SCRIPTS = (
    "bulk_cleanup.sh",
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
    "process_multitrack.sh",
)

FORWARDED_CLEANUP_OPTIONS = {
    "--qc-report",
    "--glossary",
    "--txt-chunk-chars",
    "--txt-overlap-chars",
    "--llm-provider",
    "--request-delay",
    "--retry-attempts",
    "--summary-mode",
    "--summary-output",
    "--long-summary-lang",
    "--chunks",
    "--use-context-overlap",
    "--include-timecodes",
    "--no-include-timecodes",
    "--include-timecodes-below-headings",
    "--no-include-timecodes-below-headings",
    "--include-src-block-ids",
    "--no-include-src-block-ids",
    "--include-txt-block-ids-for-untimed",
    "--no-include-txt-block-ids-for-untimed",
    "--process-timecodes-by-ai",
    "--no-process-timecodes-by-ai",
    "--log-level",
    "--trace",
}

EXAMPLE_SCRIPT_MODES = {
    "bulk_cleanup.sh": "cleanup-list",
    "auto_process_youtube.sh": "youtube-subtitles",
    "auto_process_youtube_via_groq.sh": "youtube-groq",
    "auto_process_youtube_list_via_groq.sh": "youtube-groq-list",
    "auto_process_youtube_via_speechcore.sh": "youtube-speechcore",
    "auto_process_youtube_list_via_speechcore.sh": "youtube-speechcore-list",
    "manual_process_youtube.sh": "youtube-manual",
    "process_localaudiovideo_via_groq.sh": "local-groq",
    "process_localaudiovideo_via_groq_list.sh": "local-groq-list",
    "process_localaudiovideo_via_speechcore.sh": "local-speechcore",
    "process_localaudiovideo_via_speechcore_list.sh": "local-speechcore-list",
    "process_multitrack.sh": "multitrack",
}

YOUTUBE_CONTEXT_SCRIPTS = (
    "auto_process_youtube.sh",
    "auto_process_youtube_via_groq.sh",
    "auto_process_youtube_via_speechcore.sh",
    "manual_process_youtube.sh",
)
YOUTUBE_CONTEXT_PLACEHOLDER = "https://youtu.be/dQw4w9WgXcQ"


class ShellHelpTests(unittest.TestCase):
    def _help_options(self, relative_path: str) -> set[str]:
        result = subprocess.run(
            [str(PROJECT / relative_path), "--help"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=True,
        )
        return set(re.findall(r"--[a-z][a-z0-9-]*", result.stdout))

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

    def test_workflow_help_lists_cleanup_options(self) -> None:
        for relative_path in PUBLIC_SHELL_SCRIPTS:
            with self.subTest(script=relative_path):
                self.assertTrue(
                    FORWARDED_CLEANUP_OPTIONS.issubset(
                        self._help_options(relative_path)
                    )
                )

    def test_recent_summary_options_pass_initial_validation(self) -> None:
        for relative_path in PUBLIC_SHELL_SCRIPTS:
            with self.subTest(script=relative_path):
                result = subprocess.run(
                    [
                        str(PROJECT / relative_path),
                        "--summary-mode",
                        "both",
                        "--summary-output",
                        "separate",
                        "--long-summary-lang",
                        "de",
                    ],
                    cwd=PROJECT,
                    text=True,
                    input="n\n",
                    capture_output=True,
                    check=False,
                )
                combined = result.stdout + result.stderr
                self.assertNotIn("unknown option", combined.lower())

    def test_workflows_forward_collected_cleanup_options(self) -> None:
        for relative_path in PUBLIC_SHELL_SCRIPTS:
            with self.subTest(script=relative_path):
                content = (PROJECT / relative_path).read_text(encoding="utf-8")
                self.assertIn('"${LECTURE_CLEANUP_FLAGS[@]}"', content)

    def test_groq_wrappers_request_final_language_suffixed_artifacts(self) -> None:
        content = (PROJECT / "scripts/groq_shell_common.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--language-suffix", content)

    def test_examples_use_script_basename_from_any_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for relative_path, mode in EXAMPLE_SCRIPT_MODES.items():
                expected_command = f"./{relative_path}"
                commands = (
                    [str(PROJECT / relative_path), "--help"],
                    [
                        str(PROJECT / "StartMe.sh"),
                        "--no-color",
                        "help",
                        mode,
                    ],
                )
                for command in commands:
                    with self.subTest(script=relative_path, command=command):
                        result = subprocess.run(
                            command,
                            cwd=directory,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            result.returncode,
                            0,
                            result.stdout + result.stderr,
                        )
                        match = re.search(
                            r"(?m)^Examples:\n((?:[ \t]+.*\n)+)",
                            result.stdout,
                        )
                        if match:
                            example_lines = match.group(1).splitlines()
                        else:
                            example_lines = [
                                line
                                for line in result.stdout.splitlines()
                                if line.strip().startswith(f"{expected_command} ")
                            ]
                        self.assertTrue(example_lines, result.stdout)
                        for line in example_lines:
                            self.assertEqual(
                                line.strip().split(maxsplit=1)[0],
                                expected_command,
                            )

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

    def test_single_and_list_wrappers_keep_shared_option_names(self) -> None:
        pairs = (
            (
                "auto_process_youtube_via_groq.sh",
                "auto_process_youtube_list_via_groq.sh",
                {"--preflight", "--preflight-output"},
                {"--videos", "--max-batch-cost-usd"},
            ),
            (
                "process_localaudiovideo_via_groq.sh",
                "process_localaudiovideo_via_groq_list.sh",
                {"--preflight", "--preflight-output"},
                {"--all", "--max-batch-cost-usd"},
            ),
            (
                "auto_process_youtube_via_speechcore.sh",
                "auto_process_youtube_list_via_speechcore.sh",
                set(),
                {"--videos"},
            ),
            (
                "process_localaudiovideo_via_speechcore.sh",
                "process_localaudiovideo_via_speechcore_list.sh",
                set(),
                {"--all"},
            ),
        )

        for single, batch, single_only, batch_only in pairs:
            with self.subTest(single=single, batch=batch):
                single_options = self._help_options(single)
                batch_options = self._help_options(batch)
                self.assertEqual(single_options - batch_options, single_only)
                self.assertEqual(batch_options - single_options, batch_only)

    def test_groq_workflows_expose_resume_controls(self) -> None:
        scripts = (
            "auto_process_youtube_via_groq.sh",
            "auto_process_youtube_list_via_groq.sh",
            "process_localaudiovideo_via_groq.sh",
            "process_localaudiovideo_via_groq_list.sh",
        )
        for relative_path in scripts:
            with self.subTest(script=relative_path):
                options = self._help_options(relative_path)
                self.assertIn("--resume", options)
                self.assertIn("--cache-dir", options)

                result = subprocess.run(
                    [str(PROJECT / relative_path), "--resume", "invalid"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("Invalid --resume value", result.stderr)


class YoutubeTimecodeContextTests(unittest.TestCase):
    def test_short_url_context_uses_query_separator_for_timestamp(self) -> None:
        template = (
            PROJECT / "prompts/custom_context_general/youtube-url-timecodes.txt"
        ).read_text(encoding="utf-8")
        normalized = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "subtitle-utils/normalize_youtube_url.py"),
                "https://www.youtube.com/watch?v=6gL8fDG9Zo4",
            ],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        rendered = template.replace(YOUTUBE_CONTEXT_PLACEHOLDER, normalized)

        self.assertEqual(normalized, "https://youtu.be/6gL8fDG9Zo4")
        self.assertIn("https://youtu.be/6gL8fDG9Zo4?t=SECONDS", rendered)
        self.assertNotIn("https://youtu.be/6gL8fDG9Zo4&t=SECONDS", rendered)

    def test_all_youtube_workflows_replace_the_short_url_placeholder(self) -> None:
        for relative_path in YOUTUBE_CONTEXT_SCRIPTS:
            with self.subTest(script=relative_path):
                content = (PROJECT / relative_path).read_text(encoding="utf-8")
                self.assertIn(
                    f'sed "s|{YOUTUBE_CONTEXT_PLACEHOLDER}|$ESCAPED_URL|g"',
                    content,
                )

    def test_startme_youtube_groq_delegates_to_checked_workflow(self) -> None:
        content = (PROJECT / "StartMe.sh").read_text(encoding="utf-8")

        self.assertIn(
            'youtube-groq) TARGET="$SCRIPT_DIR/auto_process_youtube_via_groq.sh"',
            content,
        )


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
                "scripts/source_timecode_core.py",
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
