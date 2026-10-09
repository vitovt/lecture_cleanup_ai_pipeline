import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stt_api.cli import main


class CliValidationTests(unittest.TestCase):
    def test_speaker_count_requires_supported_diarization(self):
        for options in [
            ["--provider", "gemini", "--diarization", "provider", "--num-speakers", "2"],
            ["--provider", "elevenlabs", "--diarization", "off", "--num-speakers", "2"],
            ["--provider", "elevenlabs", "--diarization", "provider", "--num-speakers", "0"],
        ]:
            self.assertEqual(main(["validate", *options]), 2)

    def test_validate_requires_provider_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            self.assertEqual(main(["validate", "--language-code", "uk"]), 2)

    def test_option_conflict_is_reported_before_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--language-code", "uk",
                        "--custom-vocabulary", "Kubernetes",
                    ]
                ),
                2,
            )

    def test_valid_options_pass_with_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--language-code", "uk",
                        "--language-code", "de-DE",
                        "--timestamps", "off",
                        "--custom-vocabulary", "Sicherheitsgruppe",
                    ]
                ),
                0,
            )

    def test_output_basename_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "audio.wav"
            source.write_bytes(b"not-read-before-basename-validation")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}, clear=False):
                self.assertEqual(
                    main(
                        [
                            "transcribe",
                            "--input-file", str(source),
                            "--output-dir", directory,
                            "--output-basename", "../escape",
                            "--language-code", "uk",
                        ]
                    ),
                    2,
                )

    def test_elevenlabs_accepts_keyterms_with_timestamps_and_diarization(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-only"}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--provider", "elevenlabs",
                        "--language-code", "uk",
                        "--language-code", "de-DE",
                        "--custom-vocabulary", "Halbleiter",
                        "--timestamps", "on",
                        "--diarization", "provider",
                    ]
                ),
                0,
            )

    def test_elevenlabs_keyterm_validation_precedes_credentials(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--provider", "elevenlabs",
                        "--language-code", "uk",
                        "--custom-vocabulary", "invalid[keyterm]",
                    ]
                ),
                2,
            )

    def test_elevenlabs_requires_its_own_credentials(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--provider", "elevenlabs",
                        "--language-code", "uk",
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
