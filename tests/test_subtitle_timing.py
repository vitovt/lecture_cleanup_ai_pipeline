"""Offline tests for subtitle bounds and explicit timestamp shifts."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("subtitle_timing", ROOT / "subtitle-utils/subtitle_timing.py")
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)


class SubtitleTimingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "captions.srt"

    def test_mismatch_stops_without_modifying_source(self):
        original = "1\n01:26:20,080 --> 01:26:23,080\nHello\n"
        self.path.write_text(original)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                ValueError, "--time-offset -00:14:55"):
            timing.process(self.path, 4288.684)
        self.assertEqual(self.path.read_text(), original)

    def test_two_second_tolerance(self):
        original = "1\n00:00:09,000 --> 00:00:12,000\nHello\n"
        self.path.write_text(original)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            timing.process(self.path, 10)
        self.assertIn("Subtitle timing bounds check passed", output.getvalue())
        self.assertIn("audio synchronization not checked", output.getvalue())
        self.assertEqual(self.path.read_text(), original)

    def test_user_shift_warns_clips_and_removes_outside_cues(self):
        self.path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMusic\n\n"
                             "2\n00:00:04,000 --> 00:00:07,000\nOpening\n\n"
                             "3\n00:00:13,000 --> 00:00:17,000\nClosing\n")
        errors, output = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(output):
            timing.process(self.path, 10, -5)
        self.assertIn("WARNING:", errors.getvalue())
        self.assertIn("Applied user time offset", output.getvalue())
        self.assertEqual(self.path.read_text(),
                         "1\n00:00:00,000 --> 00:00:02,000\nOpening\n\n"
                         "2\n00:00:08,000 --> 00:00:10,000\nClosing\n")

    def test_positive_shift_and_invalid_input(self):
        self.assertEqual(timing.offset_value("+00:00:02.500"), 2.5)
        self.assertEqual(timing.offset_value("-00:15:33"), -933)
        self.path.write_text("not subtitles")
        with self.assertRaisesRegex(ValueError, "no SRT timestamps"):
            timing.process(self.path, 10)

    def test_failed_shift_preserves_original(self):
        original = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        self.path.write_text(original)
        with self.assertRaisesRegex(ValueError, "no captions"):
            timing.process(self.path, 10, -20)
        self.assertEqual(self.path.read_text(), original)
