from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from multitrack.formats import (
    EVENT_SCHEMA,
    EVENT_VERSION,
    EventDocument,
    EventFormatError,
    TranscriptEvent,
    merge_documents,
    read_event_document,
    write_event_document,
    write_custom_txt,
    write_srt,
)
from multitrack.manifest import (
    ManifestError,
    load_manifest,
    manifest_from_files,
)
from multitrack.merging import documents_from_manifest
from multitrack.transcription import transcribe_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeProvider:
    def transcribe(self, track, work_dir):
        if track.diarization:
            events = (
                TranscriptEvent(0.0, 1.0, "Question", "SPEAKER_00"),
                TranscriptEvent(2.0, 3.0, "Answer", "SPEAKER_01"),
            )
        else:
            events = (TranscriptEvent(0.0, 1.0, "Hello"),)
        return EventDocument(
            source_file=str(track.file),
            provider="fake",
            requested_language=track.language,
            detected_language="uk",
            duration_seconds=3.0,
            offset_ms=0,
            track_index=track.index,
            events=events,
        )


class ManifestTests(unittest.TestCase):
    def _write_manifest(self, root: Path, data: dict) -> Path:
        path = root / "session.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def test_track_defaults_and_language_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = load_manifest(
                self._write_manifest(
                    root,
                    {
                        "language": "uk",
                        "tracks": [
                            {"file": "host.wav"},
                            {
                                "file": "guest.wav",
                                "language": "auto",
                                "speaker": "GUEST",
                                "offset_ms": 250,
                            },
                            {
                                "file": "audience.wav",
                                "diarization": True,
                                "speaker_prefix": "AUDIENCE",
                            },
                        ],
                    },
                )
            )

        self.assertEqual(manifest.tracks[0].speaker, "SPEAKER_00")
        self.assertFalse(manifest.tracks[0].diarization)
        self.assertEqual(manifest.tracks[0].offset_ms, 0)
        self.assertEqual(manifest.tracks[0].language, "uk")
        self.assertEqual(manifest.tracks[1].language, "auto")
        self.assertEqual(manifest.tracks[1].offset_ms, 250)
        self.assertEqual(manifest.tracks[2].speaker_prefix, "AUDIENCE")
        self.assertEqual(manifest.tracks[0].file, root / "host.wav")

    def test_manifestless_tracks_receive_defaults(self) -> None:
        manifest = manifest_from_files(
            [Path("host.wav"), Path("guest.wav")],
            "auto",
            "groq",
            Path("/tmp/session"),
        )

        self.assertEqual([track.language for track in manifest.tracks], ["auto", "auto"])
        self.assertEqual(
            [track.speaker for track in manifest.tracks],
            ["SPEAKER_00", "SPEAKER_01"],
        )

    def test_speaker_is_rejected_for_diarized_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_manifest(
                root,
                {
                    "language": "uk",
                    "tracks": [
                        {
                            "file": "audience.wav",
                            "diarization": True,
                            "speaker": "AUDIENCE",
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(ManifestError, "speaker_prefix"):
                load_manifest(path)


class TranscriptionTests(unittest.TestCase):
    def test_fixed_and_diarized_speakers_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("host.wav", "audience.wav"):
                (root / name).write_bytes(b"audio")
            manifest_path = root / "session.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "language": "uk",
                        "provider": "fake",
                        "tracks": [
                            {"file": "host.wav"},
                            {
                                "file": "audience.wav",
                                "diarization": True,
                                "speaker_prefix": "AUDIENCE",
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            resolved = transcribe_manifest(
                load_manifest(manifest_path),
                root / "work",
                lambda _name: FakeProvider(),
            )
            fixed = read_event_document(resolved.tracks[0].events_file)
            audience = read_event_document(resolved.tracks[1].events_file)

        self.assertEqual(fixed.events[0].speaker, "SPEAKER_00")
        self.assertEqual(
            [event.speaker for event in audience.events],
            ["AUDIENCE_00", "AUDIENCE_01"],
        )

    def test_unprefixed_diarized_speakers_avoid_fixed_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("host.wav", "audience.wav", "guest.wav"):
                (root / name).write_bytes(b"audio")
            manifest_path = root / "session.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "language": "uk",
                        "provider": "fake",
                        "tracks": [
                            {"file": "host.wav"},
                            {"file": "audience.wav", "diarization": True},
                            {"file": "guest.wav"},
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            resolved = transcribe_manifest(
                load_manifest(manifest_path),
                root / "work",
                lambda _name: FakeProvider(),
            )
            audience = read_event_document(resolved.tracks[1].events_file)

        self.assertEqual(
            [event.speaker for event in audience.events],
            ["SPEAKER_01", "SPEAKER_03"],
        )


class MergeTests(unittest.TestCase):
    def test_offsets_are_applied_and_txt_and_srt_are_rendered(self) -> None:
        first = EventDocument(
            "host.wav",
            "fake",
            "uk",
            "uk",
            5.0,
            0,
            0,
            (TranscriptEvent(1.0, 2.0, "Host line", "SPEAKER_00"),),
        )
        second = EventDocument(
            "guest.wav",
            "fake",
            "uk",
            "uk",
            5.0,
            250,
            1,
            (TranscriptEvent(0.8, 1.1, "Guest line", "SPEAKER_01"),),
        )
        events = merge_documents([first, second])
        self.assertEqual([event.text for event in events], ["Host line", "Guest line"])
        self.assertAlmostEqual(events[1].start, 1.05)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txt = write_custom_txt(root / "combined.txt", events)
            srt = write_srt(root / "combined.srt", events)
            txt_text = txt.read_text(encoding="utf-8")
            srt_text = srt.read_text(encoding="utf-8")

        self.assertIn("[00:00:01,000] [SPEAKER_00] Host line", txt_text)
        self.assertIn("[00:00:01,050] [SPEAKER_01] Guest line", txt_text)
        self.assertIn("SPEAKER_01: Guest line", srt_text)

    def test_negative_adjusted_timestamp_is_rejected(self) -> None:
        document = EventDocument(
            "track.wav",
            "fake",
            "uk",
            "uk",
            1.0,
            -500,
            0,
            (TranscriptEvent(0.1, 0.2, "Line", "SPEAKER_00"),),
        )
        with self.assertRaisesRegex(EventFormatError, "before 00:00:00"):
            merge_documents([document])

    def test_event_schema_constants_are_stable(self) -> None:
        self.assertEqual(EVENT_SCHEMA, "lecture-cleanup/transcript-events")
        self.assertEqual(EVENT_VERSION, 1)

    def test_resolved_manifest_offset_overrides_event_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "host.wav"
            audio.write_bytes(b"audio")
            events_path = write_event_document(
                root / "host.events.json",
                EventDocument(
                    str(audio),
                    "fake",
                    "uk",
                    "uk",
                    2.0,
                    0,
                    0,
                    (TranscriptEvent(0.5, 1.0, "Line", "SPEAKER_00"),),
                ),
            )
            manifest_path = root / "resolved.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "language": "uk",
                        "tracks": [
                            {
                                "file": str(audio),
                                "events_file": str(events_path),
                                "offset_ms": 750,
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            documents = documents_from_manifest(load_manifest(manifest_path))
            merged = merge_documents(documents)

        self.assertEqual(documents[0].offset_ms, 750)
        self.assertAlmostEqual(merged[0].start, 1.25)


class PipelineTests(unittest.TestCase):
    def test_high_level_pipeline_reuses_events_merges_and_cleans(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "run_multitrack_test", PROJECT_ROOT / "scripts/run_multitrack.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "host.wav"
            audio.write_bytes(b"audio")
            manifest_path = root / "session.yaml"
            manifest_path.write_text(
                yaml.safe_dump(
                    {"language": "uk", "tracks": [{"file": str(audio)}]},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            workdir = root / "work"
            write_event_document(
                workdir / "tracks/00-host.events.json",
                EventDocument(
                    str(audio),
                    "groq",
                    "uk",
                    "uk",
                    1.0,
                    0,
                    0,
                    (TranscriptEvent(0.0, 1.0, "Hello", "SPEAKER_00"),),
                ),
            )

            with patch.object(
                module.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as cleanup:
                result = module.main(
                    [
                        "--manifest",
                        str(manifest_path),
                        "--workdir",
                        str(workdir),
                        "--cleanup-outdir",
                        str(root / "clean"),
                        "--cleanup-args",
                        "--summary-mode",
                        "short",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue((workdir / "resolved-manifest.yaml").is_file())
            self.assertTrue((workdir / "combined/session.events.json").is_file())
            self.assertTrue((workdir / "combined/session.txt").is_file())
            self.assertTrue((workdir / "combined/session.srt").is_file())
            command = cleanup.call_args.args[0]
            self.assertEqual(command[0], str(PROJECT_ROOT / "lecture_cleanup.sh"))
            self.assertIn(str(workdir / "combined/session.txt"), command)
            self.assertEqual(command[-2:], ["--summary-mode", "short"])


if __name__ == "__main__":
    unittest.main()
