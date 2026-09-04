from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from multitrack.formats import (
    EventDocument,
    EventFormatError,
    append_suffix,
    merge_documents,
    read_event_document,
    write_combined_events,
    write_custom_txt,
    write_srt,
)
from multitrack.manifest import ManifestError, SessionManifest


def documents_from_manifest(manifest: SessionManifest) -> list[EventDocument]:
    missing = [track.index for track in manifest.tracks if track.events_file is None]
    if missing:
        raise ManifestError(
            "resolved manifest is missing events_file for track(s): "
            + ", ".join(str(index) for index in missing)
        )
    documents = []
    for track in manifest.tracks:
        assert track.events_file is not None
        document = read_event_document(track.events_file)
        documents.append(
            replace(
                document,
                source_file=str(track.file),
                provider=track.provider,
                requested_language=track.language,
                offset_ms=track.offset_ms,
                track_index=track.index,
            )
        )
    return documents


def merge_to_outputs(
    documents: list[EventDocument],
    output_base: Path,
    formats: list[str],
) -> dict[str, Path]:
    events = merge_documents(documents)
    if not events:
        raise EventFormatError("the input event documents contain no transcript events")
    base = output_base.expanduser().resolve()
    outputs: dict[str, Path] = {}
    if "events" in formats:
        outputs["events"] = write_combined_events(
            append_suffix(base, ".events.json"),
            events,
            [document.source_file for document in documents],
        )
    if "txt" in formats:
        outputs["txt"] = write_custom_txt(append_suffix(base, ".txt"), events)
    if "srt" in formats:
        outputs["srt"] = write_srt(append_suffix(base, ".srt"), events)
    return outputs
