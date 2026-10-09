import unittest
from multitrack.formats import TranscriptEvent, TranscriptSource, format_timestamp, merge_documents


class TimelineTests(unittest.TestCase):
    def test_equal_timestamps_keep_source_order_and_overlapping_speech(self):
        a = TranscriptSource(0, 0, (TranscriptEvent(1, 'A'),))
        b = TranscriptSource(0, 1, (TranscriptEvent(1, 'B'),))
        self.assertEqual([e.text for e in merge_documents([b, a])], ['A', 'B'])

    def test_millisecond_rounding_and_long_recordings(self):
        self.assertEqual(format_timestamp(360001.125), '100:00:01,125')
        self.assertEqual(format_timestamp(59.9996), '00:01:00,000')

    def test_negative_offsets_fail(self):
        with self.assertRaises(ValueError):
            merge_documents([TranscriptSource(-2000, 0, (TranscriptEvent(1, 'A'),))])
