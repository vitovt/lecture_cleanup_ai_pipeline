from __future__ import annotations

import unittest

from scripts.source_timecode_core import (
    allocate_src,
    extract_youtube_video_id,
    fenced_block_ranges,
    find_inline_markers,
    parse_below_marker,
    parse_youtube_url,
    protected_line_mask,
    split_trailing_inline,
    strip_trailing_block_ids,
    timestamp_url,
)


class SourceTimecodeCoreTests(unittest.TestCase):
    def test_inline_and_below_use_the_same_timestamp_parser(self) -> None:
        base, inline = split_trailing_inline(
            "Topic [01:29:40](https://youtu.be/abc?t=5380s)"
        )
        below = parse_below_marker("[🎥 01:29:40](#)\n")

        self.assertEqual(base, "Topic")
        self.assertIsNotNone(inline)
        self.assertIsNotNone(below)
        self.assertEqual(inline.seconds, 5380)
        self.assertEqual(below.seconds, inline.seconds)
        self.assertEqual(len(find_inline_markers(inline.raw)), 1)

    def test_src_and_txt_ids_share_trailing_identifier_parser(self) -> None:
        base, identifiers = strip_trailing_block_ids(
            "Topic ^src-60-2 ^txt-4"
        )

        self.assertEqual(base, "Topic")
        self.assertEqual(
            [(item.kind, item.number, item.collision) for item in identifiers],
            [("src", 60, 2), ("txt", 4, None)],
        )

    def test_protection_covers_fences_and_generated_summaries(self) -> None:
        lines = (
            "```md\n### Example [00:01:00]\n```\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_START | AI NOTICE -->\n"
            "### Summary [00:02:00]\n"
            "<!-- LECTURE_CLEANUP_LONG_SUMMARY_END -->\n"
            "### Source [00:03:00]\n"
        ).splitlines(keepends=True)

        mask = protected_line_mask(lines)

        self.assertEqual(mask, [True, True, True, True, True, True, False])

    def test_legacy_url_is_parsed_and_rewritten_canonically(self) -> None:
        parsed = parse_youtube_url("https://youtu.be/abc&t=60s")

        self.assertEqual(parsed.video_id, "abc")
        self.assertEqual(parsed.base_url, "https://youtu.be/abc")
        self.assertTrue(parsed.legacy_timestamp_syntax)
        self.assertEqual(
            timestamp_url(parsed.base_url, 120),
            "https://youtu.be/abc?t=120s",
        )

    def test_summary_marker_example_does_not_protect_later_source(self) -> None:
        lines = (
            "```md\n<!-- LECTURE_CLEANUP_SHORT_SUMMARY_START -->\n```\n"
            "### Real source [00:01:00]\n"
        ).splitlines(keepends=True)

        self.assertEqual(protected_line_mask(lines), [True, True, True, False])

    def test_fence_ranges_keep_adjacent_and_unclosed_blocks_separate(self) -> None:
        lines = "```md\nfirst\n```\n~~~\nsecond\n~~~\n````\nthird\n".splitlines(keepends=True)

        self.assertEqual(list(fenced_block_ranges(lines)), [(0, 3), (3, 6), (6, 8)])

    def test_normalizer_shorthand_uses_shared_video_id_parser(self) -> None:
        cases = {
            "abc&t=60s": "abc",
            "youtu.be/short-id?t=10s": "short-id",
            "youtube.com/watch?v=watch-id&t=10s": "watch-id",
            "https://youtube.com/shorts/shorts-id": "shorts-id",
        }

        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    extract_youtube_video_id(
                        value,
                        allow_bare=True,
                        allow_missing_scheme=True,
                    ),
                    expected,
                )

    def test_src_allocator_uses_one_collision_algorithm(self) -> None:
        used = {"^src-60", "^src-60-2"}

        self.assertEqual(allocate_src(60, used), "^src-60-3")


if __name__ == "__main__":
    unittest.main()
