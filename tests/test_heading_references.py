from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from scripts.heading_references import (
    HeadingReferenceOptions,
    render_heading_references,
)
from scripts.utils import add_timecodes_to_headings, dedup_overlapping_boundary


PROJECT = Path(__file__).resolve().parents[1]


class HeadingReferenceTests(unittest.TestCase):
    def render(self, markdown: str, **kwargs: bool):
        return render_heading_references(
            markdown,
            HeadingReferenceOptions(**kwargs),
        )

    def test_default_inline_format_is_unchanged(self) -> None:
        source = "### Topic — [00:01:00](#t=00:01:00)\n\nBody.\n"

        result = self.render(source)

        self.assertEqual(result.markdown, source)
        self.assertEqual(result.timed_headings, 1)

    def test_tracked_defaults_preserve_inline_only_output(self) -> None:
        config = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )

        options = HeadingReferenceOptions(
            include_inline=config["include_timecodes_in_headings"],
            include_below=config["include_timecodes_below_headings"],
            include_src=config["include_src_block_ids"],
            include_txt_for_untimed=config["include_txt_block_ids_for_untimed"],
        )

        self.assertEqual(options, HeadingReferenceOptions())
        self.assertTrue(options.needs_timestamp_resolution())

    def test_inline_can_be_rendered_as_below_and_src(self) -> None:
        result = self.render(
            "### Topic — [01:29:40](#t=01:29:40)\n\nBody.\n",
            include_inline=False,
            include_below=True,
            include_src=True,
        )

        self.assertEqual(
            result.markdown,
            "### Topic ^src-5380\n[🎥 01:29:40](#)\n\nBody.\n",
        )

    def test_all_timed_formats_can_coexist(self) -> None:
        result = self.render(
            "### Topic — [00:01:00](https://youtu.be/abc?t=60s)\n",
            include_inline=True,
            include_below=True,
            include_src=True,
        )

        self.assertEqual(
            result.markdown,
            "### Topic — [00:01:00](https://youtu.be/abc?t=60s) ^src-60\n"
            "[🎥 00:01:00](https://youtu.be/abc?t=60s)\n",
        )

    def test_src_collisions_use_stable_suffixes(self) -> None:
        result = self.render(
            "### First [00:01:00]\n### Second [00:01:00]\n",
            include_src=True,
        )

        self.assertIn("^src-60\n", result.markdown)
        self.assertIn("^src-60-2\n", result.markdown)

    def test_txt_ids_are_added_only_to_untimed_headings(self) -> None:
        result = self.render(
            "# Timed [00:01:00]\n## Untimed\n### Also untimed\n",
            include_inline=False,
            include_src=True,
            include_txt_for_untimed=True,
        )

        self.assertEqual(
            result.markdown,
            "# Timed ^src-60\n## Untimed ^txt-1\n### Also untimed ^txt-2\n",
        )
        self.assertEqual(result.src_ids, 1)
        self.assertEqual(result.txt_ids, 2)

    def test_existing_output_is_idempotent(self) -> None:
        options = HeadingReferenceOptions(
            include_inline=False,
            include_below=True,
            include_src=True,
            include_txt_for_untimed=True,
        )
        source = (
            "### Timed [00:01:00]\n\n"
            "### Untimed\n"
        )

        first = render_heading_references(source, options).markdown
        second = render_heading_references(first, options).markdown

        self.assertEqual(second, first)

    def test_only_add_ids_reserves_existing_ids_and_keeps_formats(self) -> None:
        text = (
            "### New [00:01:00](#)\n"
            "### Existing [00:01:00](#) ^src-60\n"
            "### New untimed\n"
            "### Existing untimed ^txt-1\n"
        )
        options = HeadingReferenceOptions(
            include_src=True, include_txt_for_untimed=True, only_add_ids=True,
        )

        result = render_heading_references(text, options).markdown

        self.assertEqual(result, (
            "### New [00:01:00](#) ^src-60-2\n"
            "### Existing [00:01:00](#) ^src-60\n"
            "### New untimed ^txt-2\n"
            "### Existing untimed ^txt-1\n"
        ))
        self.assertEqual(render_heading_references(result, options).markdown, result)

    def test_only_add_ids_preserves_below_links_and_crlf(self) -> None:
        text = "### Timed\r\n[🎥 00:01:00](https://youtu.be/abc?t=60s)\r\nBody\r\n"

        result = self.render(text, include_src=True, only_add_ids=True)

        self.assertEqual(result.markdown, text.replace("### Timed\r\n", "### Timed ^src-60\r\n"))

    def test_code_fences_and_summary_blocks_are_ignored(self) -> None:
        source = (
            "```md\n### Example [00:01:00]\n```\n"
            "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_START | AI NOTICE -->\n"
            "### Summary heading [00:02:00]\n"
            "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_END -->\n"
            "### Source heading\n"
        )

        result = self.render(source, include_txt_for_untimed=True)

        self.assertIn("### Example [00:01:00]\n", result.markdown)
        self.assertIn("### Summary heading [00:02:00]\n", result.markdown)
        self.assertIn("### Source heading ^txt-1\n", result.markdown)


class CanonicalTimecodeTests(unittest.TestCase):
    def test_programmatic_fallback_marks_all_heading_levels(self) -> None:
        source = "# One\n### Three\n###### Six\n"

        result = add_timecodes_to_headings(source, 60, as_link=True)

        self.assertEqual(result.count("[00:01:00](#t=00:01:00)"), 3)
        self.assertTrue(result.endswith("\n"))

    def test_programmatic_fallback_is_idempotent_and_skips_fences(self) -> None:
        source = (
            "### Existing — [00:01:00](#t=00:01:00)\n"
            "```md\n### Example\n```\n"
        )

        first = add_timecodes_to_headings(source, 60, as_link=True)
        second = add_timecodes_to_headings(first, 60, as_link=True)

        self.assertEqual(second, first)
        self.assertIn("```md\n### Example\n```", first)

    def test_stitch_dedup_ignores_canonical_heading_timestamp(self) -> None:
        current, removed, mode = dedup_overlapping_boundary(
            "Body.\n### Repeated — [00:01:00](#t=00:01:00)",
            "### Repeated\n\nNext body.",
            500,
        )

        self.assertEqual(removed, 1)
        self.assertEqual(mode, "lines")
        self.assertEqual(current, "\nNext body.")


if __name__ == "__main__":
    unittest.main()
