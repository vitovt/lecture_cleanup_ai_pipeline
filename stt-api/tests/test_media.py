import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from stt_api.media import prepare_audio


class ChunkBoundaryTests(unittest.TestCase):
    def test_final_chunk_does_not_create_extra_overlap_only_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            def ffmpeg(command, **kwargs):
                Path(command[-1]).touch()
                return SimpleNamespace(returncode=0)
            with patch('stt_api.media.probe_duration', return_value=2995), \
                 patch('stt_api.media.shutil.which', return_value='/usr/bin/ffmpeg'), \
                 patch('stt_api.media.subprocess.run', side_effect=ffmpeg):
                prepared = prepare_audio(Path(tmp)/'audio.flac', max_seconds=1500, overlap_seconds=5)
                try:
                    self.assertEqual(len(prepared.parts), 2)
                    self.assertEqual(prepared.parts[-1].offset + prepared.parts[-1].duration, 2995)
                finally:
                    prepared.cleanup()
