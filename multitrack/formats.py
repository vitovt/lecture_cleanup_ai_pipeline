from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


EVENT_SCHEMA = "lecture-cleanup/transcript-events"
EVENT_VERSION = 1


class EventFormatError(ValueError):
    """A transcript-event document is invalid."""


@dataclass(frozen=True)
class TranscriptEvent:
    start: float
    end: float
    text: str
    speaker: str | None = None
    track_index: int | None = None


@dataclass(frozen=True)
class EventDocument:
    source_file: str
    provider: str
    requested_language: str
    detected_language: str
    duration_seconds: float
    offset_ms: float
    track_index: int
    events: tuple[TranscriptEvent, ...]


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def append_suffix(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _event_from_dict(raw: Any, index: int) -> TranscriptEvent:
    if not isinstance(raw, dict):
        raise EventFormatError(f"events[{index}] must be an object")
    try:
        start = float(raw["start"])
        end = float(raw["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EventFormatError(f"events[{index}] has invalid timestamps") from exc
    text = str(raw.get("text") or "").strip()
    if start < 0 or end < start:
        raise EventFormatError(f"events[{index}] has an invalid time interval")
    if not text:
        raise EventFormatError(f"events[{index}].text cannot be empty")
    speaker = raw.get("speaker")
    return TranscriptEvent(
        start=start,
        end=end,
        text=text,
        speaker=str(speaker).strip() if speaker is not None else None,
        track_index=(
            int(raw["track_index"]) if raw.get("track_index") is not None else None
        ),
    )


def read_event_document(path: Path) -> EventDocument:
    source = path.expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EventFormatError(f"cannot read event document {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EventFormatError(f"event document {source} must be an object")
    if raw.get("schema") != EVENT_SCHEMA or raw.get("version") != EVENT_VERSION:
        raise EventFormatError(
            f"unsupported event schema in {source}; expected {EVENT_SCHEMA} v{EVENT_VERSION}"
        )
    events_raw = raw.get("events")
    if not isinstance(events_raw, list):
        raise EventFormatError(f"event document {source} has no events list")
    raw_track = raw.get("track")
    track: dict[str, Any] = raw_track if isinstance(raw_track, dict) else {}
    return EventDocument(
        source_file=str(raw.get("source_file") or ""),
        provider=str(raw.get("provider") or "unknown"),
        requested_language=str(raw.get("requested_language") or "auto"),
        detected_language=str(raw.get("detected_language") or ""),
        duration_seconds=float(raw.get("duration_seconds") or 0),
        offset_ms=float(track.get("offset_ms") or 0),
        track_index=int(track.get("index") or 0),
        events=tuple(
            _event_from_dict(event, index) for index, event in enumerate(events_raw)
        ),
    )


def event_to_dict(event: TranscriptEvent) -> dict[str, Any]:
    item: dict[str, Any] = {
        "start": round(event.start, 3),
        "end": round(event.end, 3),
        "text": event.text,
    }
    if event.speaker is not None:
        item["speaker"] = event.speaker
    if event.track_index is not None:
        item["track_index"] = event.track_index
    return item


def write_event_document(
    path: Path,
    document: EventDocument,
    *,
    speaker_map: dict[str, str] | None = None,
) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "version": EVENT_VERSION,
        "source_file": document.source_file,
        "provider": document.provider,
        "requested_language": document.requested_language,
        "detected_language": document.detected_language,
        "duration_seconds": round(document.duration_seconds, 3),
        "track": {
            "index": document.track_index,
            "offset_ms": document.offset_ms,
        },
        "events": [event_to_dict(event) for event in document.events],
    }
    if speaker_map:
        payload["speaker_map"] = speaker_map
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def merge_documents(documents: Iterable[EventDocument]) -> list[TranscriptEvent]:
    merged: list[TranscriptEvent] = []
    for document in documents:
        shift = document.offset_ms / 1000.0
        for event in document.events:
            shifted = replace(
                event,
                start=event.start + shift,
                end=event.end + shift,
                track_index=document.track_index,
            )
            if shifted.start < 0:
                raise EventFormatError(
                    f"track {document.track_index} offset moves an event before 00:00:00"
                )
            merged.append(shifted)
    return sorted(
        merged,
        key=lambda event: (
            event.start,
            event.end,
            event.track_index if event.track_index is not None else -1,
        ),
    )


def write_combined_events(
    path: Path, events: list[TranscriptEvent], source_files: list[str]
) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": EVENT_SCHEMA,
        "version": EVENT_VERSION,
        "kind": "combined",
        "source_files": source_files,
        "events": [event_to_dict(event) for event in events],
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def write_custom_txt(path: Path, events: Iterable[TranscriptEvent]) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for event in events:
        speaker = f" [{event.speaker}]" if event.speaker else ""
        lines.append(f"[{format_timestamp(event.start)}]{speaker} {event.text}")
    destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return destination


def write_srt(path: Path, events: Iterable[TranscriptEvent]) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, event in enumerate(events, 1):
        end = max(event.end, event.start + 0.001)
        label = f"{event.speaker}: " if event.speaker else ""
        blocks.append(
            f"{index}\n{format_timestamp(event.start)} --> {format_timestamp(end)}\n"
            f"{label}{event.text}"
        )
    destination.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
    return destination
