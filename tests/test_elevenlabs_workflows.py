from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "process_localaudiovideo_via_elevenlabs.sh",
    "auto_process_youtube_via_elevenlabs.sh",
    "process_localaudiovideo_via_elevenlabs_list.sh",
    "auto_process_youtube_list_via_elevenlabs.sh",
)


class ElevenLabsWorkflowTests(unittest.TestCase):
    def test_logging_helpers_and_validation_succeed_at_every_level(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
LANG=uk
ADDITIONAL_LANGS=()
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
STT_CONFIG= ELEVENLABS_MODEL= ELEVENLABS_MODE= ELEVENLABS_TIMESTAMPS=
ELEVENLABS_DIARIZATION= ELEVENLABS_RESUME= ELEVENLABS_CACHE_DIR= OVERWRITE=0
stt_runner() {
    printf '%s\n' 'VALID status=ok provider=elevenlabs model=test languages=uk-UA timestamps=off diarization=off vocabulary=0'
}
STT_RUNNER=stt_runner
for level in quiet error info debug trace; do
    LOG_LEVEL="$level"
    elevenlabs_info test >/dev/null 2>&1 || exit 10
    elevenlabs_debug test >/dev/null 2>&1 || exit 11
    elevenlabs_warn test >/dev/null 2>&1 || exit 12
    elevenlabs_validate_options >/dev/null 2>&1 || exit 13
    printf '%s=ok\n' "$level"
done
"""
        result = subprocess.run(
            ["bash", "-c", command, "bash", str(PROJECT)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["quiet=ok", "error=ok", "info=ok", "debug=ok", "trace=ok"],
        )

    def test_common_builder_does_not_emit_empty_repeatable_arguments(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
LANG=uk
ADDITIONAL_LANGS=()
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
STT_CONFIG= ELEVENLABS_MODEL= ELEVENLABS_MODE= ELEVENLABS_TIMESTAMPS=
ELEVENLABS_DIARIZATION= ELEVENLABS_RESUME= ELEVENLABS_CACHE_DIR= OVERWRITE=0
elevenlabs_build_stt_flags
printf '<%s>\n' "${ELEVENLABS_STT_FLAGS[@]}"
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
            ["<--provider>", "<elevenlabs>", "<--language-code>", "<uk>"],
        )

    def test_multilingual_builder_explicitly_selects_auto_detection(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
LANG=uk
ADDITIONAL_LANGS=()
ELEVENLABS_MULTILINGUAL=1
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
STT_CONFIG= ELEVENLABS_MODEL= ELEVENLABS_MODE= ELEVENLABS_TIMESTAMPS=
ELEVENLABS_DIARIZATION= ELEVENLABS_RESUME= ELEVENLABS_CACHE_DIR= OVERWRITE=0
elevenlabs_build_stt_flags
printf '<%s>\n' "${ELEVENLABS_STT_FLAGS[@]}"
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
            ["<--provider>", "<elevenlabs>", "<--language-code>", "<auto>"],
        )

    def test_multilingual_builder_validates_documented_additional_languages(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
LANG=uk
ADDITIONAL_LANGS=(de-DE)
ELEVENLABS_MULTILINGUAL=1
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
STT_CONFIG= ELEVENLABS_MODEL= ELEVENLABS_MODE= ELEVENLABS_TIMESTAMPS=
ELEVENLABS_DIARIZATION= ELEVENLABS_RESUME= ELEVENLABS_CACHE_DIR= OVERWRITE=0
elevenlabs_build_stt_flags
printf '<%s>\n' "${ELEVENLABS_STT_FLAGS[@]}"
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
            [
                "<--provider>",
                "<elevenlabs>",
                "<--language-code>",
                "<uk>",
                "<--language-code>",
                "<de-DE>",
            ],
        )

    def test_primary_workflow_language_must_have_two_letter_base(self):
        command = """
SCRIPT_DIR="$1"
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
elevenlabs_primary_label ceb
"""
        result = subprocess.run(
            ["bash", "-c", command, "bash", str(PROJECT)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

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
                self.assertIn("--multilingual", result.stdout)
                self.assertIn("--additional-lang CODE", result.stdout)
                self.assertIn("any number of languages", result.stdout)
                self.assertIn("--custom-vocabulary-file FILE", result.stdout)
                self.assertIn("keyterms array", result.stdout)
                self.assertIn("--diarization on", result.stdout)
                self.assertIn("speaker_0", result.stdout)
                self.assertIn("uk-UA", result.stdout)
                self.assertIn("ru-RU", result.stdout)
                self.assertIn("20%", result.stdout)
                self.assertIn("Examples:", result.stdout)
                self.assertIn("--lang uk --multilingual", result.stdout)

    def test_vocabulary_file_option_remains_accepted(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                content = (PROJECT / script).read_text(encoding="utf-8")
                self.assertIn("--custom-vocabulary-file)", content)

    def test_list_workflows_forward_multilingual_to_single_workflows(self):
        for script in (
            "process_localaudiovideo_via_elevenlabs_list.sh",
            "auto_process_youtube_list_via_elevenlabs.sh",
        ):
            with self.subTest(script=script):
                content = (PROJECT / script).read_text(encoding="utf-8")
                self.assertIn(
                    '[[ "$ELEVENLABS_MULTILINGUAL" -eq 1 ]] '
                    '&& CHILD_FLAGS+=(--multilingual)',
                    content,
                )

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
        env = dict(os.environ, ELEVENLABS_API_KEY="test-only")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--provider", "elevenlabs",
                "--language-code", "uk",
                "--language-code", "de-DE",
                "--language-code", "ru-ru",
                "--custom-vocabulary", "Sicherheitsgruppe",
                "--timestamps", "on",
                "--diarization", "on",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("languages=uk-UA,de-DE,ru-RU", result.stdout)
        self.assertIn("provider_language=auto", result.stdout)

    def test_invalid_keyterms_fail_before_credentials(self):
        env = dict(os.environ, ELEVENLABS_API_KEY="")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--provider", "elevenlabs",
                "--language-code", "uk",
                "--custom-vocabulary", "invalid[keyterm]",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported character", result.stderr)
        self.assertNotIn("ELEVENLABS_API_KEY is not set", result.stderr)

    def test_missing_credentials_fail_in_validate(self):
        env = dict(os.environ, ELEVENLABS_API_KEY="")
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT / "stt-api/stt_cli.py"),
                "validate",
                "--provider", "elevenlabs",
                "--language-code", "uk",
            ],
            cwd=PROJECT,
            env={**env, "PYTHONPATH": str(PROJECT / "stt-api")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ELEVENLABS_API_KEY is not set", result.stderr)


if __name__ == "__main__":
    unittest.main()
