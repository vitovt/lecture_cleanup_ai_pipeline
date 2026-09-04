from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from multitrack.formats import (
    EventDocument,
    TranscriptEvent,
    read_event_document,
    write_event_document,
)
from multitrack.manifest import SessionManifest, TrackSpec, with_events_files
from multitrack.providers.base import TranscriptionProvider


ProviderFactory = Callable[[str], TranscriptionProvider]


def safe_stem(path: Path) -> str:
    value = re.sub(r"[^\w.()\[\] -]+", "-", path.stem, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value or "track"


class SpeakerAllocator:
    def __init__(self, reserved: set[str]) -> None:
        self.used = set(reserved)
        self.next_number = 0

    def allocate(self) -> str:
        while f"SPEAKER_{self.next_number:02d}" in self.used:
            self.next_number += 1
        label = f"SPEAKER_{self.next_number:02d}"
        self.used.add(label)
        self.next_number += 1
        return label


def _apply_speakers(
    document: EventDocument,
    track: TrackSpec,
    allocator: SpeakerAllocator,
) -> tuple[EventDocument, dict[str, str]]:
    speaker_map: dict[str, str] = {}
    events: list[TranscriptEvent] = []
    if not track.diarization:
        label = track.speaker or f"SPEAKER_{track.index:02d}"
        events = [replace(event, speaker=label) for event in document.events]
    else:
        for event in document.events:
            local = event.speaker or "SPEAKER_00"
            if local not in speaker_map:
                if track.speaker_prefix:
                    speaker_map[local] = (
                        f"{track.speaker_prefix}_{len(speaker_map):02d}"
                    )
                else:
                    speaker_map[local] = allocator.allocate()
            events.append(replace(event, speaker=speaker_map[local]))
    return (
        replace(
            document,
            source_file=str(track.file),
            provider=track.provider,
            requested_language=track.language,
            offset_ms=track.offset_ms,
            track_index=track.index,
            events=tuple(events),
        ),
        speaker_map,
    )


def transcribe_manifest(
    manifest: SessionManifest,
    output_dir: Path,
    provider_factory: ProviderFactory,
    *,
    overwrite: bool = False,
) -> SessionManifest:
    destination = output_dir.expanduser().resolve()
    tracks_dir = destination / "tracks"
    provider_dir = destination / "provider-artifacts"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    provider_dir.mkdir(parents=True, exist_ok=True)

    reserved = {
        track.speaker
        for track in manifest.tracks
        if not track.diarization and track.speaker is not None
    }
    allocator = SpeakerAllocator({label for label in reserved if label})
    events_files: list[Path] = []
    for track in manifest.tracks:
        if not track.file.is_file():
            raise FileNotFoundError(f"track audio file not found: {track.file}")
        events_path = (
            tracks_dir / f"{track.index:02d}-{safe_stem(track.file)}.events.json"
        )
        if events_path.is_file() and not overwrite:
            existing = read_event_document(events_path)
            allocator.used.update(
                event.speaker for event in existing.events if event.speaker
            )
            events_files.append(events_path)
            continue
        provider = provider_factory(track.provider)
        raw_document = provider.transcribe(track, provider_dir)
        document, speaker_map = _apply_speakers(raw_document, track, allocator)
        write_event_document(events_path, document, speaker_map=speaker_map)
        events_files.append(events_path)
    return with_events_files(manifest, events_files)
