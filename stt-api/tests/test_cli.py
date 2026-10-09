import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from stt_api.cli import main, _preflight, build_parser, transcribe
from stt_api.media import PreparedAudio, AudioPart
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO


class CliValidationTests(unittest.TestCase):
    def test_runtime_error_verbosity(self):
        for level in ['quiet', 'error', 'info', 'debug', 'trace']:
            error = StringIO()
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY': ''}), redirect_stderr(error):
                status = main(['validate', '--provider', 'elevenlabs', '--log-level', level])
            self.assertEqual(status, 2)
            self.assertEqual('ELEVENLABS_API_KEY' in error.getvalue(), level != 'quiet')
            self.assertEqual('Traceback' in error.getvalue(), level in {'debug', 'trace'})
        from stt_api.cli import configure_logging
        configure_logging('info')

    def test_progress_and_payload_log_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'audio.flac'
            audio.write_bytes(b'audio')
            args = build_parser().parse_args(['transcribe', '--input-file', str(audio), '--output-dir', directory,
                                               '--metadata-output', str(Path(directory) / 'metadata.json')])
            settings = dict(provider='elevenlabs', model='test', language_codes=['uk'],
                            provider_language_code='uk', vocabulary=[], mode='verbatim',
                            timestamps=True, diarization=False, max_seconds=100, overlap=0)
            provider = Mock()
            provider.transcribe.return_value = {'text': 'PRIVATE_TRANSCRIPT', 'words': []}
            for level in [20, 10, 5]:
                prepared = PreparedAudio([AudioPart(audio, 0, 1, 0, 1)], 1)
                stdout = StringIO()
                with patch('stt_api.cli._provider', return_value=provider), \
                     patch('stt_api.cli.prepare_audio', return_value=prepared), \
                     patch('stt_api.cli.CheckpointStore') as store, \
                     redirect_stdout(stdout), self.assertLogs('stt-api', level=level) as logs:
                    store.return_value.read.return_value = None
                    transcribe({}, args, settings)
                self.assertEqual(stdout.getvalue(), '')  # Bridge stdout stays protocol-only.
                self.assertTrue(Path(args.metadata_output).is_file())
                output = '\n'.join(logs.output)
                self.assertLess(output.index('Preparing provider audio'), output.index('Transcribing part'))
                self.assertIn('Audio ready', output)
                self.assertEqual('PRIVATE_TRANSCRIPT' in output, level == 5)
                self.assertEqual('Checkpoint miss in' in output, level <= 10)

    def test_excerpt_preflight_uses_planned_duration_without_reading_full_media(self):
        settings = {
            "max_seconds": 1500, "overlap": 5, "provider": "gemini", "model": "test",
            "language_codes": ["uk"], "provider_language_code": "uk", "timestamps": True,
            "diarization": True, "vocabulary": [],
        }
        with patch("stt_api.cli.probe_duration", return_value=4415) as probe:
            excerpt = _preflight(Path("recording.mkv"), settings, duration_seconds=60)
            self.assertEqual(excerpt["planned_chunks"], 1)
            self.assertEqual(excerpt["duration_seconds"], 60)
            probe.assert_not_called()
            self.assertEqual(_preflight(Path("recording.mkv"), settings)["planned_chunks"], 3)

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
