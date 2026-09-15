from __future__ import annotations

import unittest

from scripts.summary_references import (
    SummaryReferenceError,
    collect_source_blocks,
    render_long_summary_reference_display,
    validate_long_summary_references,
)
from scripts.summary_settings import LongSummaryReferenceDisplaySettings


SOURCE = (
    "### Timed — [00:01:00](#t=00:01:00) ^src-60\n"
    "Timed source text.\n"
    "#### Untimed ^txt-1\n"
    "Untimed source text.\n"
)


class SourceBlockTests(unittest.TestCase):
    def test_collects_timed_and_untimed_heading_ids(self) -> None:
        blocks = collect_source_blocks(SOURCE)

        self.assertEqual(blocks["src-60"].timestamp, "00:01:00")
        self.assertEqual(blocks["src-60"].title, "Timed")
        self.assertEqual(blocks["src-60"].markdown_heading, "### Timed")
        self.assertIsNone(blocks["txt-1"].timestamp)
        self.assertEqual(blocks["txt-1"].markdown_heading, "#### Untimed")

    def test_ignores_ids_in_code_and_generated_summary_blocks(self) -> None:
        source = (
            "```md\n### Code ^src-9\n```\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_START | AI NOTICE -->\n"
            "### Summary ^txt-8\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_END -->\n"
            "### Source ^txt-1\n"
        )

        self.assertEqual(set(collect_source_blocks(source)), {"txt-1"})


class LongSummaryReferenceTests(unittest.TestCase):
    def test_accepts_internal_references_for_appended_summary(self) -> None:
        summary = (
            "### 0️⃣ First\n"
            "↩ [[#^src-60|Source · 00:01:00]]\n\n"
            "#### 0️⃣.0️⃣ Detail\n"
            "↩ [[#^src-60|00:01:00]] · [[#^txt-1|Source]]\n"
        )

        validate_long_summary_references(summary, SOURCE, source_note="")

    SUMMARY = (
        "### 0️⃣ First\n"
        "↩ [[#^src-60|Source · 00:01:00]] · [[#^txt-1|Source]]\n"
    )

    def render(
        self,
        *,
        link_style: str = "wikilink",
        label: str = "🔗 Source",
        heading: str = "none",
        timestamp: bool = True,
        separator: str = " · ",
    ) -> str:
        return render_long_summary_reference_display(
            self.SUMMARY,
            SOURCE,
            LongSummaryReferenceDisplaySettings(
                label=label,
                heading=heading,
                timestamp=timestamp,
                separator=separator,
            ),
            link_style=link_style,
        )

    def test_default_display_adds_label_and_available_timestamp(self) -> None:
        rendered = self.render()

        self.assertIn("[[#^src-60|🔗 Source · 00:01:00]]", rendered)
        self.assertIn("[[#^txt-1|🔗 Source]]", rendered)

    def test_markdown_style_renders_internal_block_links(self) -> None:
        rendered = self.render(link_style="markdown")

        self.assertIn("[🔗 Source · 00:01:00](#^src-60)", rendered)
        self.assertIn("[🔗 Source](#^txt-1)", rendered)

    def test_title_display_uses_clean_source_heading(self) -> None:
        rendered = self.render(
            label="Source",
            heading="title",
            timestamp=False,
            separator=" / ",
        )

        self.assertIn("[[#^src-60|Source / Timed]]", rendered)
        self.assertIn("[[#^txt-1|Source / Untimed]]", rendered)

    def test_markdown_display_preserves_real_source_heading_level(self) -> None:
        rendered = self.render(
            label="",
            heading="markdown",
            timestamp=False,
        )

        self.assertIn("[[#^src-60|### Timed]]", rendered)
        self.assertIn("[[#^txt-1|#### Untimed]]", rendered)

    def test_display_rewrite_keeps_external_link_target(self) -> None:
        summary = "### 0️⃣ First\n↩ [[lecture#^txt-1|Source]]\n"

        rendered = render_long_summary_reference_display(
            summary,
            SOURCE,
            LongSummaryReferenceDisplaySettings(
                label="Origin",
                heading="none",
                timestamp=False,
                separator=" · ",
            ),
            link_style="wikilink",
        )

        self.assertIn("[[lecture#^txt-1|Origin]]", rendered)

    def test_markdown_style_renders_encoded_external_note_target(self) -> None:
        summary = "### 0️⃣ First\n↩ [[My lecture#^txt-1|Source]]\n"

        rendered = render_long_summary_reference_display(
            summary,
            SOURCE,
            LongSummaryReferenceDisplaySettings(
                label="Origin",
                heading="none",
                timestamp=False,
                separator=" · ",
            ),
            link_style="markdown",
        )

        self.assertIn("[Origin](My%20lecture.md#^txt-1)", rendered)

    def test_display_sanitizes_wikilink_delimiters_in_source_heading(self) -> None:
        source = "### Arrays [A] | Pipes ^txt-2\n"
        summary = "### 0️⃣ First\n↩ [[#^txt-2|Source]]\n"

        rendered = render_long_summary_reference_display(
            summary,
            source,
            LongSummaryReferenceDisplaySettings(
                label="",
                heading="title",
                timestamp=False,
                separator=" · ",
            ),
            link_style="wikilink",
        )

        self.assertIn("[[#^txt-2|Arrays (A) ¦ Pipes]]", rendered)

    def test_accepts_external_references_for_separate_summary(self) -> None:
        summary = (
            "### 0️⃣ First\n"
            "↩ [[lecture#^txt-1|Source]]\n"
        )

        validate_long_summary_references(summary, SOURCE, source_note="lecture")

    def test_rejects_heading_without_immediate_reference(self) -> None:
        summary = "### 0️⃣ First\n\n↩ [[#^txt-1|Source]]\n"

        with self.assertRaisesRegex(SummaryReferenceError, "no immediate"):
            validate_long_summary_references(summary, SOURCE, source_note="")

    def test_rejects_an_identifier_not_present_in_source(self) -> None:
        summary = "### 0️⃣ First\n↩ [[#^txt-99|Source]]\n"

        with self.assertRaisesRegex(SummaryReferenceError, "unknown source block"):
            validate_long_summary_references(summary, SOURCE, source_note="")

    def test_rejects_internal_link_for_separate_summary(self) -> None:
        summary = "### 0️⃣ First\n↩ [[#^txt-1|Source]]\n"

        with self.assertRaisesRegex(SummaryReferenceError, "wrong note"):
            validate_long_summary_references(
                summary,
                SOURCE,
                source_note="lecture",
            )

    def test_rejects_incorrect_timestamp_label(self) -> None:
        summary = "### 0️⃣ First\n↩ [[#^src-60|Source · 00:02:00]]\n"

        with self.assertRaisesRegex(SummaryReferenceError, "invalid label"):
            validate_long_summary_references(summary, SOURCE, source_note="")

    def test_ignores_markdown_headings_inside_code_fences(self) -> None:
        summary = (
            "### 0️⃣ First\n"
            "↩ [[#^txt-1|Source]]\n\n"
            "```md\n### Example without a reference\n```\n"
        )

        validate_long_summary_references(summary, SOURCE, source_note="")


if __name__ == "__main__":
    unittest.main()
