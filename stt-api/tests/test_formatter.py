import unittest

from stt_api.formatter import format_events, merge_plain_text, words_to_events


class FormatterTests(unittest.TestCase):
    def test_words_become_timestamped_events(self):
        events = words_to_events(
            [
                {"text": "Hello", "start": 1.0, "end": 1.2, "speaker": "spk_1"},
                {"text": "world.", "start": 1.3, "end": 6.2, "speaker": "spk_1"},
            ]
        )
        self.assertEqual(format_events(events), "[00:00:01,000] [spk_1] Hello world.\n")

    def test_plain_chunk_overlap_is_removed(self):
        self.assertEqual(
            merge_plain_text(["one two three four five", "two three four five six"]),
            "one two three four five six\n",
        )


if __name__ == "__main__":
    unittest.main()
