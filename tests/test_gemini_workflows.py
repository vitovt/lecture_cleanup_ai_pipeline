from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "process_localaudiovideo_via_gemini.sh",
    "auto_process_youtube_via_gemini.sh",
    "process_localaudiovideo_via_gemini_list.sh",
    "auto_process_youtube_list_via_gemini.sh",
)


class GeminiWorkflowTests(unittest.TestCase):
    def test_common_builder_does_not_emit_empty_repeatable_arguments(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/gemini_shell_common.sh"
LANG=uk
ADDITIONAL_LANGS=()
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
STT_CONFIG= GEMINI_MODEL= GEMINI_MODE= GEMINI_TIMESTAMPS=
GEMINI_DIARIZATION= GEMINI_RESUME= GEMINI_CACHE_DIR= OVERWRITE=0
gemini_build_stt_flags
printf '<%s>\n' "${GEMINI_STT_FLAGS[@]}"
"""
        result = subprocess.run(
            ["bash", "-c", command, "bash", str(PROJECT)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["<--provider>", "<gemini>", "<--language-code>", "<uk>"],
        )

    def test_every_workflow_has_detailed_help(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = subprocess.run(
                    [str(PROJECT / script), "--help"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--additional-lang CODE", result.stdout)
                self.assertIn("--custom-vocabulary-file FILE", result.stdout)
                self.assertIn("uk-UA", result.stdout)
                self.assertIn("ru-RU", result.stdout)
                self.assertIn("Examples:", result.stdout)

    def test_unknown_options_fail_before_dependencies(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = subprocess.run(
                    [str(PROJECT / script), "--definitely-unknown"],
                    cwd=PROJECT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("unknown option", (result.stdout + result.stderr).lower())

    def test_low_level_validation_normalizes_languages(self):
        env = dict(os.environ, GEMINI_API_KEY="test-only")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--language-code", "uk",
                "--language-code", "de-DE",
                "--language-code", "ru-ru",
                "--timestamps", "off",
                "--custom-vocabulary", "Sicherheitsgruppe",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("languages=uk-UA,de-DE,ru-RU", result.stdout)

    def test_incompatible_options_fail_before_credentials(self):
        env = dict(os.environ, GEMINI_API_KEY="")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--language-code", "uk",
                "--custom-vocabulary", "Kubernetes",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be combined with word timestamps", result.stderr)
        self.assertNotIn("GEMINI_API_KEY is not set", result.stderr)

    def test_missing_credentials_fail_in_validate(self):
        env = dict(os.environ, GEMINI_API_KEY="")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--language-code", "uk",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("GEMINI_API_KEY is not set", result.stderr)


if __name__ == "__main__":
    unittest.main()
