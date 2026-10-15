"""Integration checks using tiny real FFmpeg files, without touching recordings."""

import hashlib
import importlib.util
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "subtitle-utils/glue_videos.py"
spec = importlib.util.spec_from_file_location("glue_videos", SCRIPT)
glue_videos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(glue_videos)


def packets(paths):
    """Ordered compressed-packet digests for each independent stream."""
    digests, counts = {}, {}
    for path in paths:
        command = ["ffprobe", "-v", "error", "-show_packets", "-show_data_hash", "sha256",
                   "-show_entries", "packet=stream_index,data_hash", "-of", "compact", str(path)]
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
            for line in process.stdout:
                fields = dict(part.split("=", 1) for part in line.strip().split("|") if "=" in part)
                if "data_hash" not in fields:
                    continue
                index = int(fields["stream_index"])
                digests.setdefault(index, hashlib.sha256()).update(fields["data_hash"].encode())
                counts[index] = counts.get(index, 0) + 1
            if process.wait():
                raise RuntimeError(f"Packet inspection failed: {path}")
    return {index: (counts[index], digest.hexdigest()) for index, digest in digests.items()}


class GlueCliTests(unittest.TestCase):
    def test_unreadable_input_uses_same_error_in_all_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'unreadable.mkv'
            source.write_bytes(b'video')
            output = str(Path(directory) / 'joined.mkv')
            for flags in ([], ['-o', output], ['-o', output, '--dry-run']):
                with self.subTest(flags=flags), \
                        patch.object(glue_videos.shutil, 'which', return_value='/fake/tool'), \
                        patch.object(Path, 'open', side_effect=PermissionError('input access denied')), \
                        patch.object(glue_videos, 'probe') as probe:
                    with self.assertRaisesRegex(PermissionError, 'input access denied'):
                        glue_videos.main([str(source), *flags])
                    probe.assert_not_called()
                    self.assertFalse(Path(output).exists())

    def test_help_and_empty_invocation_need_no_media_tools(self):
        for flags in ([], ["--help"], ["-h"]):
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, str(SCRIPT), *flags],
                                        env=dict(os.environ, PATH=""), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn("without re-encoding", result.stdout)
                self.assertIn("part1.mkv part2.mkv -o joined.mkv", result.stdout)
                self.assertIn("--help" if not flags else "--overwrite", result.stdout)

    def test_bad_options_fail_before_inspection(self):
        for option in ("--out", "--overw", "--unknown-option"):
            with self.subTest(option=option):
                result = subprocess.run([sys.executable, str(SCRIPT), "missing.mkv",
                                         "-o", "joined.mkv", option],
                                        env=dict(os.environ, PATH=""), capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("unrecognized arguments", result.stderr)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class GlueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="glue-tests-")
        cls.root = Path(cls.temp.name)
        cls.first = cls.make_video("first's recording.mkv", "red", 440)
        cls.second = cls.make_video("second\nrecording.mkv", "blue", 550)
        cls.one_audio = cls.make_video("one-audio.mkv", "red", 440, tracks=1)
        cls.large = cls.make_video("large.mkv", "red", 440, size="160x96")
        cls.rate = cls.make_video("rate.mkv", "red", 440, rate=44100)
        cls.mp4first = cls.make_video("first.mp4", "red", 440)
        cls.mp4second = cls.make_video("second.mp4", "blue", 550)
        cls.silentfirst = cls.make_video("silent1.mkv", "red", 440, tracks=0)
        cls.silentsecond = cls.make_video("silent2.mkv", "blue", 550, tracks=0)
        cls.original_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.root.iterdir()}

    @classmethod
    def make_video(cls, name, color, frequency, tracks=2, size="128x96", rate=48000):
        path = cls.root / name
        command = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color={color}:s={size}:r=25:d=0.4"]
        for index in range(tracks):
            command += ["-f", "lavfi", "-i", f"sine=frequency={frequency + index * 100}:sample_rate={rate}:duration=0.4"]
        command += ["-map", "0:v"]
        for index in range(tracks):
            command += ["-map", f"{index + 1}:a", f"-metadata:s:a:{index}", f"title=Track{index + 1}"]
        command += ["-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)]
        subprocess.run(command, check=True, capture_output=True)
        return path

    @classmethod
    def tearDownClass(cls):
        for path, expected in cls.original_hashes.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AssertionError(f"Source modified: {path}")
        cls.temp.cleanup()

    def invoke(self, *args, answer=None):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              input=answer, capture_output=True, text=True)

    def test_mkv_order_and_separate_tracks_without_reencoding(self):
        output = self.root / "joined.mkv"
        result = self.invoke(self.first, self.second, "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packets([self.first, self.second]), packets([output]))
        self.assertNotEqual(packets([self.second, self.first]), packets([output]))
        self.assertEqual(len(packets([output])), 3)

    def test_mp4_order_and_packets(self):
        output = self.root / "joined.mp4"
        result = self.invoke("--output", output, self.mp4first, self.mp4second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packets([self.mp4first, self.mp4second]), packets([output]))

    def test_options_between_inputs_and_dash_filename(self):
        output = self.root / "intermixed.mkv"
        result = self.invoke(self.first, "-o", output, self.second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packets([self.first, self.second]), packets([output]))
        dash_path = self.root / "-recording.mkv"
        dash_path.symlink_to(self.first)
        result = subprocess.run([sys.executable, str(SCRIPT), "-o", str(self.root / "dash.mkv"),
                                 "--", "-recording.mkv", str(self.second)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_videos_without_audio(self):
        output = self.root / "silent.mkv"
        result = self.invoke(self.silentfirst, self.silentsecond, "-o", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packets([self.silentfirst, self.silentsecond]), packets([output]))

    def test_compatibility_diagnostics_and_existing_output_protection(self):
        output = self.root / "protected.mkv"
        output.write_bytes(b"keep this")
        for incompatible, message in [(self.one_audio, "audio track count"),
                                      (self.large, "width"), (self.rate, "sample_rate"),
                                      (self.mp4first, "container")]:
            with self.subTest(message=message):
                result = self.invoke(self.first, incompatible, "-o", output, "--overwrite")
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertIn(str(incompatible), result.stderr)
                self.assertEqual(output.read_bytes(), b"keep this")

    def test_overwrite_no_yes_and_flag(self):
        output = self.root / "overwrite.mkv"
        output.write_bytes(b"original")
        args = (self.first, self.second, "-o", output)
        self.assertEqual(self.invoke(*args, answer="n\n").returncode, 1)
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(self.invoke(*args, answer="").returncode, 1)
        self.assertEqual(output.read_bytes(), b"original")
        result = self.invoke(*args, answer="maybe\ny\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke(*args, "--overwrite")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_input_cannot_be_output_even_with_overwrite(self):
        for output in (self.first, self.root / "input-hardlink.mkv", self.root / "input-symlink.mkv"):
            if output.name == "input-hardlink.mkv":
                output.hardlink_to(self.first)
            elif output.name == "input-symlink.mkv":
                output.symlink_to(self.first)
            result = self.invoke(self.first, self.second, "-o", output, "--overwrite")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Sources cannot be overwritten", result.stderr)

    def test_bad_arguments_and_files(self):
        empty = self.root / "empty.mkv"
        empty.touch()
        corrupt = self.root / "corrupt.mkv"
        corrupt.write_bytes(b"not a video")
        cases = [("-o", self.root / "none.mkv"),
                 (self.root / "missing.mkv", "-o", self.root / "bad.mkv"),
                 (empty, "-o", self.root / "bad.mkv"),
                 (corrupt, "-o", self.root / "bad.mkv"),
                 (self.root, "-o", self.root / "bad.mkv"),
                 (self.first, "-o", self.root / "wrong.mp4"),
                 (self.first, "-o", self.root / "missing-dir" / "out.mkv")]
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)

    def test_explicit_and_implicit_dry_run_report_without_writing(self):
        output = self.root / 'dry-run.mkv'
        before = sorted(p.name for p in self.root.iterdir())
        for flags in ([], ['--dry-run'], ['--dry-run', '-o', output]):
            with self.subTest(flags=flags):
                result = self.invoke(self.first, self.second, *flags, answer='')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Input 1:', result.stdout)
                self.assertIn('Input 2:', result.stdout)
                for field in ('Container:', 'Duration:', 'codec_name: "h264"', 'width:',
                              'height:', 'sample_rate:', 'channel_layout:', 'audio tracks: 2'):
                    self.assertIn(field, result.stdout)
                self.assertIn(str(output) if flags and '-o' in flags else 'Output: not specified', result.stdout)
                self.assertIn('Estimated output duration:', result.stdout)
                self.assertIn('Dry-run: no files were created or changed.', result.stdout)
                self.assertNotIn('Created:', result.stdout)
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        single = self.invoke(self.first)
        self.assertEqual(single.returncode, 0, single.stderr)
        self.assertIn('Output: not specified', single.stdout)

    def test_dry_run_existing_output_never_prompts_or_overwrites(self):
        output = self.root / 'dry-existing.mkv'
        output.write_bytes(b'original output')
        result = self.invoke(self.first, self.second, '-o', output, '--dry-run', answer='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), b'original output')
        self.assertNotIn('Overwrite?', result.stdout)
        self.assertIn('would require replacement', result.stdout)

    def test_dry_run_retains_input_and_output_validation(self):
        empty = self.root / 'dry-empty.mkv'
        empty.touch()
        for source in (self.root / 'missing.mkv', empty, self.root):
            for flags in ([], ['--dry-run'], ['-o', self.root / 'dry-invalid.mkv', '--dry-run']):
                result = self.invoke(source, *flags)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('Error:', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
        for flags in ([], ['--dry-run']):
            result = self.invoke(self.first, self.large, *flags)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Videos are incompatible', result.stderr)
        for output in (self.first, self.root / 'dry-invalid.mp4', self.root / 'missing' / 'dry.mkv'):
            result = self.invoke(self.first, '--dry-run', '-o', output)
            self.assertEqual(result.returncode, 1)

    def test_dry_run_duration_accounts_for_mp4_packet_timing(self):
        result = self.invoke(self.mp4first, self.mp4second)
        self.assertEqual(result.returncode, 0, result.stderr)
        match = re.search(r'Estimated output duration: ([\d.]+) seconds', result.stdout)
        self.assertIsNotNone(match)
        expected = sum(glue_videos.segment_durations(
            [self.mp4first, self.mp4second],
            [glue_videos.probe(p, shutil.which('ffprobe')) for p in (self.mp4first, self.mp4second)],
            shutil.which('ffprobe')))
        self.assertAlmostEqual(float(match[1]), expected, places=6)

    def test_container_extension_must_match_actual_format(self):
        for original, extension in ((self.first, ".mp4"), (self.mp4first, ".mov")):
            renamed = self.root / ("misnamed" + extension)
            shutil.copyfile(original, renamed)
            output = self.root / ("misnamed-out" + extension)
            result = self.invoke(renamed, "-o", output)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Correct the extension", result.stderr)
            self.assertFalse(output.exists())

    def test_argument_file_for_long_lists(self):
        output = self.root / "many.mkv"
        listing = self.root / "arguments.txt"
        # Paths with spaces/apostrophes remain one argument per line.
        listing.write_text("\n".join([str(self.first)] * 30 + ["-o", str(output)]) + "\n")
        result = self.invoke("@" + str(listing))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packets([self.first] * 30), packets([output]))

    def test_temporary_files_are_cleaned_up(self):
        self.assertEqual(list(self.root.glob(".glue-videos-*")), [])

    def test_failed_join_removes_partial_output_and_keeps_existing_file(self):
        failing_ffmpeg = self.root / "failing-ffmpeg"
        failing_ffmpeg.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[-1]).write_bytes(b'partial output')\n"
            "print('Simulated write failure', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        failing_ffmpeg.chmod(0o755)
        output = self.root / "failed.mkv"
        output.write_bytes(b"previous output")
        inputs = [self.first, self.second]
        infos = [glue_videos.probe(path, shutil.which("ffprobe")) for path in inputs]
        with self.assertRaisesRegex(glue_videos.GlueError, "Simulated write failure"):
            glue_videos.glue(inputs, output, infos, "matroska", str(failing_ffmpeg),
                             shutil.which("ffprobe"), glue_videos.output_state(output),
                             [glue_videos.fingerprint(path) for path in inputs])
        self.assertEqual(output.read_bytes(), b"previous output")
        self.assertEqual(list(self.root.glob(".glue-videos-*")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
