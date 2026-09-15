from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "subtitle-utils" / "add_video_url.py"
VIDEO_URL = "https://www.youtube.com/watch?v=A5qE7Eg7zPk"


class AddVideoUrlTests(unittest.TestCase):
    def run_tool(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *(str(arg) for arg in args)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_markdown(self, directory: str, content: str) -> Path:
        path = Path(directory) / "lecture.md"
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def test_adds_url_to_heading_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Heading [00:01:00](#t=60s)\n",
            )

            result = self.run_tool("-u", VIDEO_URL, path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "### Heading [00:01:00]"
            "(https://www.youtube.com/watch?v=A5qE7Eg7zPk&t=60s)\n",
        )

    def test_adds_url_to_below_timestamp_without_heading_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Heading\n[🎥 01:29:40](#)\n",
            )

            result = self.run_tool("-u", VIDEO_URL, path)

        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "[🎥 01:29:40]"
            "(https://www.youtube.com/watch?v=A5qE7Eg7zPk&t=5380s)",
            result.stdout,
        )

    def test_processes_mismatched_heading_and_below_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(
                directory,
                "### Heading [00:01:00](#t=999s)\n"
                "[🎥 00:02:00](#)\n",
            )

            result = self.run_tool("-u", VIDEO_URL, path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("watch?v=A5qE7Eg7zPk&t=60s", result.stdout)
        self.assertIn("watch?v=A5qE7Eg7zPk&t=120s", result.stdout)

    def test_repeated_run_is_idempotent(self) -> None:
        source = "### Heading [00:01:00](#t=60s)\n[🎥 00:01:00](#)\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, source)
            first = self.run_tool("-u", VIDEO_URL, path)
            converted = Path(directory) / "converted.md"
            converted.write_text(first.stdout, encoding="utf-8", newline="")

            second = self.run_tool("-u", VIDEO_URL, converted)

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout, first.stdout)
        self.assertIn("output is unchanged", second.stderr)

    def test_ignores_markers_in_code_and_generated_summaries(self) -> None:
        source = (
            "```md\n### Example [00:01:00](#)\n```\n"
            "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_START | AI NOTICE -->\n"
            "### Summary [00:02:00](#)\n"
            "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_END -->\n"
            "### Source [00:03:00](#)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, source)

            result = self.run_tool("-u", VIDEO_URL, path)

        self.assertEqual(result.returncode, 0)
        self.assertIn("### Example [00:01:00](#)", result.stdout)
        self.assertIn("### Summary [00:02:00](#)", result.stdout)
        self.assertIn(
            "### Source [00:03:00]"
            "(https://www.youtube.com/watch?v=A5qE7Eg7zPk&t=180s)",
            result.stdout,
        )

    def test_diff_prints_preview_and_does_not_modify_input(self) -> None:
        source = "### Heading [00:01:00](#t=60s)\n"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, source)

            result = self.run_tool("-u", VIDEO_URL, "--diff", path)
            after = path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(after, source)
        self.assertIn(f"--- {path}", result.stdout)
        self.assertIn(f"+++ {path.with_name('lecture.generated.md')}", result.stdout)
        self.assertIn("@@ -1 +1 @@", result.stdout)
        self.assertIn("-### Heading [00:01:00](#t=60s)", result.stdout)
        self.assertIn("+### Heading [00:01:00](https://", result.stdout)

    def test_diff_and_output_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_markdown(directory, "### Heading [00:01:00]\n")
            output = Path(directory) / "output.md"

            result = self.run_tool(
                "-u",
                VIDEO_URL,
                "--diff",
                "-o",
                output,
                path,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)


if __name__ == "__main__":
    unittest.main()
