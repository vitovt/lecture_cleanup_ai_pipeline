from __future__ import annotations

import unittest

from scripts.summary_references import (
    SummaryReferenceError,
    collect_source_blocks,
    validate_long_summary_references,
)


SOURCE = (
    "### Timed — [00:01:00](#t=00:01:00) ^src-60\n"
    "Timed source text.\n"
    "### Untimed ^txt-1\n"
    "Untimed source text.\n"
)


class SourceBlockTests(unittest.TestCase):
    def test_collects_timed_and_untimed_heading_ids(self) -> None:
        blocks = collect_source_blocks(SOURCE)

        self.assertEqual(blocks["src-60"].timestamp, "00:01:00")
        self.assertIsNone(blocks["txt-1"].timestamp)

    def test_ignores_ids_in_code_and_generated_summary_blocks(self) -> None:
        source = (
            "```md\n### Code ^src-9\n```\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_START | AI NOTICE -->\n"
            "### Summary ^txt-8\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_END -->\n"
            "### Source ^txt-1\n"
        )

        self.assertEqual(set(collect_source_blocks(source)), {"txt-1"})


class LongSummaryReferenceValidationTests(unittest.TestCase):
    def test_accepts_internal_references_for_appended_summary(self) -> None:
        summary = (
            "### 0️⃣ First\n"
            "↩ [[#^src-60|Source · 00:01:00]]\n\n"
            "#### 0️⃣.0️⃣ Detail\n"
            "↩ [[#^src-60|00:01:00]] · [[#^txt-1|Source]]\n"
        )

        validate_long_summary_references(summary, SOURCE, source_note="")

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
