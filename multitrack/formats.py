from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


class EventFormatError(ValueError):
    """Invalid timestamped transcript."""


@dataclass(frozen=True)
class TranscriptEvent:
    start: float
    text: str
    speaker: str | None = None
    source_index: int | None = None


@dataclass(frozen=True)
class TranscriptSource:
    offset_ms: float
    source_index: int
    events: tuple[TranscriptEvent, ...]


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def merge_documents(documents: Iterable[TranscriptSource]) -> list[TranscriptEvent]:
    merged: list[TranscriptEvent] = []
    for document in documents:
        shift = document.offset_ms / 1000.0
        for event in document.events:
            shifted = replace(
                event,
                start=event.start + shift,
                source_index=document.source_index,
            )
            if shifted.start < 0:
                raise EventFormatError(
                    f"source {document.source_index} offset moves an event before 00:00:00"
                )
            merged.append(shifted)
    return sorted(
        merged,
        key=lambda event: (
            event.start,
            event.source_index if event.source_index is not None else -1,
        ),
    )


def write_custom_txt(path: Path, events: Iterable[TranscriptEvent]) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for event in events:
        speaker = f" [{event.speaker}]" if event.speaker else ""
        lines.append(f"[{format_timestamp(event.start)}]{speaker} {event.text}")
    destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return destination
