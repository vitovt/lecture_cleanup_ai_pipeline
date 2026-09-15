from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "subtitle-utils" / "source_timecodes.py"


class SourceTimecodesCliTests(unittest.TestCase):
    def run_tool(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *(str(arg) for arg in args)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_markdown(self, directory: str, content: str, name: str = "lecture.md") -> Path:
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def test_no_arguments_prints_short_help(self) -> None:
        result = self.run_tool()

        self.assertEqual(result.returncode, 0)
        self.assertIn("FILE.md alone runs analyze", result.stdout)
        self.assertIn("For more detailed options", result.stdout)
        self.assertNotIn("--remove-inline", result.stdout)

    def test_detailed_help_lists_transform_options(self) -> None:
        result = self.run_tool("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Transform options:", result.stdout)
        self.assertIn("--overwrite", result.stdout)
        self.assertIn("--add-src", result.stdout)

    def test_filename_alone_defaults_to_analyze(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### First [00:01:00] ^src-60\n\n"
                "### Second ^src-120\n\n"
                "[🎥 00:02:00](#)\n",
            )

            result = self.run_tool(path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "LEGEND I=inline B=below S=src\n"
            "ANALYZE status=ok formats=I+B+S url=none\n",
        )
        self.assertEqual(result.stderr, "")

    def test_analyze_runs_doctor_and_stops_on_timestamp_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Conflict [00:01:00] ^src-61\n",
            )

            result = self.run_tool("analyze", path)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("DOCTOR status=error", result.stderr)
        self.assertIn("code=timestamp_conflict", result.stderr)
        self.assertNotIn("ANALYZE", result.stderr)

    def test_doctor_rejects_partial_url_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Linked [00:01:00](https://youtu.be/abc?t=60s)\n\n"
                "### Placeholder [00:02:00]\n",
            )

            result = self.run_tool("doctor", path)

        self.assertEqual(result.returncode, 1)
        self.assertIn("code=missing_video_url", result.stderr)

    def test_add_src_warns_for_existing_and_adds_only_missing_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Existing [00:01:00] ^src-60\n\n"
                "### Missing [00:02:00]\n",
            )

            result = self.run_tool("transform", path, "--add-src")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("^src-60"), 1)
        self.assertEqual(result.stdout.count("^src-120"), 1)
        self.assertIn("WARNING code=already_present representation=S count=1", result.stderr)
        self.assertIn("TRANSFORM status=ok before=I+S after=I+S", result.stderr)

    def test_inline_can_be_replaced_by_below_and_src(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### CloudWatch [01:29:40](https://youtu.be/abc?t=5380s)\n\nBody.\n",
            )

            result = self.run_tool(
                "transform",
                path,
                "--remove-inline",
                "--add-below",
                "--add-src",
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("### CloudWatch ^src-5380", result.stdout)
        self.assertIn("[🎥 01:29:40](https://youtu.be/abc?t=5380s)", result.stdout)
        self.assertNotIn("CloudWatch [01:29:40]", result.stdout)
        self.assertIn("TRANSFORM status=ok before=I after=B+S", result.stderr)

    def test_add_src_allocates_collision_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### First [00:01:00]\n\n"
                "### Second [00:01:00]\n",
            )

            result = self.run_tool("transform", path, "--add-src")

        self.assertEqual(result.returncode, 0)
        self.assertIn("^src-60\n", result.stdout)
        self.assertIn("^src-60-2\n", result.stdout)

    def test_src_collision_suffix_can_reach_two_digits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "".join(f"### Heading {number} [00:01:00]\n" for number in range(10)),
            )

            transformed = self.run_tool("transform", path, "--add-src")
            converted = self.write_markdown(directory, transformed.stdout, "converted.md")
            analyzed = self.run_tool(converted)

        self.assertEqual(transformed.returncode, 0)
        self.assertIn("^src-60-10", transformed.stdout)
        self.assertEqual(analyzed.returncode, 0)
        self.assertIn("formats=I+S", analyzed.stdout)

    def test_doctor_reports_malformed_timestamp_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Invalid [00:99:00]\n")

            result = self.run_tool("doctor", path)

        self.assertEqual(result.returncode, 1)
        self.assertIn("code=malformed_timestamp", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_doctor_reports_malformed_src_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Invalid ^src=60\n")

            result = self.run_tool("doctor", path)

        self.assertEqual(result.returncode, 1)
        self.assertIn("code=malformed_src", result.stderr)

    def test_doctor_reports_multiple_inline_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Invalid [00:01:00] [00:02:00]\n",
            )

            result = self.run_tool("doctor", path)

        self.assertEqual(result.returncode, 1)
        self.assertIn("code=multiple_inline", result.stderr)

    def test_youtube_unit_timestamp_is_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Time [01:29:40](https://youtu.be/abc?t=1h29m40s)\n",
            )

            result = self.run_tool(path)

        self.assertEqual(result.returncode, 0)
        self.assertIn("formats=I url=complete", result.stdout)

    def test_legacy_short_youtube_timestamps_are_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### First [00:00:09](https://youtu.be/d3uPlWyiBNg&t=9s)\n\n"
                "### Second [00:17:38](https://youtu.be/d3uPlWyiBNg&t=1058s)\n",
            )

            result = self.run_tool(path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "LEGEND I=inline B=below S=src\n"
            "ANALYZE status=ok formats=I url=complete\n",
        )
        self.assertEqual(
            result.stderr,
            "WARNING code=legacy_youtube_url count=2 first_line=1 "
            'message="youtu.be timestamp uses & instead of ?; accepted for '
            'compatibility but should be fixed"\n',
        )

    def test_doctor_warns_but_succeeds_for_legacy_youtube_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### First [00:01:00](https://youtu.be/abc&t=60s)\n",
            )

            result = self.run_tool("doctor", path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "DOCTOR status=ok errors=0\n")
        self.assertIn("WARNING code=legacy_youtube_url count=1", result.stderr)

    def test_added_marker_canonicalizes_legacy_short_youtube_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### First [00:01:00](https://youtu.be/abc&t=60s)\n",
            )

            transformed = self.run_tool("transform", path, "--add-below")
            converted = self.write_markdown(directory, transformed.stdout, "converted.md")
            analyzed = self.run_tool(converted)

        self.assertEqual(transformed.returncode, 0)
        self.assertIn("[00:01:00](https://youtu.be/abc&t=60s)", transformed.stdout)
        self.assertIn("[🎥 00:01:00](https://youtu.be/abc?t=60s)", transformed.stdout)
        self.assertEqual(analyzed.returncode, 0)
        self.assertIn("formats=I+B url=complete", analyzed.stdout)

    def test_set_url_requires_inline_or_below_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Only source ID ^src-60\n")

            result = self.run_tool(
                "transform",
                path,
                "--set-url",
                "https://youtu.be/abc",
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("needs I or B", result.stderr)

    def test_remove_url_warns_and_is_noop_when_url_is_already_absent(self) -> None:
        source = "### Local — [00:01:00](#t=00:01:00) ^src-60\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, source)

            result = self.run_tool("transform", path, "--remove-url")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, source)
        self.assertIn("WARNING code=url_already_absent", result.stderr)
        self.assertIn("changed=0", result.stderr)

    def test_last_representation_removal_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Only ^src-60\n")

            refused = self.run_tool("transform", path, "--remove-src")
            forced = self.run_tool("transform", path, "--remove-src", "--force")

        self.assertEqual(refused.returncode, 3)
        self.assertEqual(refused.stdout, "")
        self.assertIn("code=timestamp_data_loss", refused.stderr)
        self.assertIn("requires --force", refused.stderr)
        self.assertEqual(forced.returncode, 0)
        self.assertEqual(forced.stdout, "### Only\n")

    def test_overwrite_atomically_replaces_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Time [00:01:00]\n")

            result = self.run_tool("transform", path, "--add-src", "--overwrite")
            updated = path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(updated, "### Time [00:01:00] ^src-60\n")
        self.assertIn("output=overwrite", result.stderr)

    def test_diff_prints_preview_and_does_not_modify_input(self) -> None:
        source = "### Time [00:01:00]\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, source)

            result = self.run_tool("transform", path, "--add-src", "--diff")
            after = path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(after, source)
        self.assertIn(f"--- {path}", result.stdout)
        self.assertIn(f"+++ {path.with_name('lecture.generated.md')}", result.stdout)
        self.assertIn("@@ -1 +1 @@", result.stdout)
        self.assertIn("-### Time [00:01:00]", result.stdout)
        self.assertIn("+### Time [00:01:00] ^src-60", result.stdout)
        self.assertIn("output=diff", result.stderr)

    def test_diff_and_output_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Time [00:01:00]\n")
            output = Path(directory) / "output.md"

            result = self.run_tool(
                "transform",
                path,
                "--add-src",
                "--diff",
                "-o",
                output,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)

    def test_markers_in_fenced_code_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "```md\n### Example [00:01:00] ^src-61\n```\n\n"
                "### Real [00:02:00]\n",
            )

            result = self.run_tool(path)

        self.assertEqual(result.returncode, 0)
        self.assertIn("formats=I", result.stdout)


if __name__ == "__main__":
    unittest.main()
