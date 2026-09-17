from __future__ import annotations

import re
from typing import Any


OFFSET_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)s$")


def offset_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = OFFSET_RE.fullmatch(str(value or "").strip())
    return float(match.group(1)) if match else 0.0


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def normalize_words(interaction: Any) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", None) != "word_info":
                    continue
                text = str(getattr(annotation, "text", "") or "").strip()
                if not text:
                    continue
                words.append(
                    {
                        "text": text,
                        "start": offset_seconds(getattr(annotation, "start_offset", "")),
                        "end": offset_seconds(getattr(annotation, "end_offset", "")),
                        "speaker": getattr(annotation, "speaker", None),
                    }
                )
    return words


def words_to_events(words: list[dict[str, Any]], max_seconds: float = 30.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if current:
            speaker_changed = word.get("speaker") != current[-1].get("speaker")
            duration = float(word["end"]) - float(current[0]["start"])
            gap = float(word["start"]) - float(current[-1]["end"])
            if speaker_changed or duration > max_seconds or gap > 2.0:
                events.append(_event(current))
                current = []
        current.append(word)
        if str(word["text"]).rstrip().endswith((".", "?", "!")) and (
            float(word["end"]) - float(current[0]["start"]) >= 5.0
        ):
            events.append(_event(current))
            current = []
    if current:
        events.append(_event(current))
    return events


def _event(words: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "speaker": words[0].get("speaker"),
        "text": " ".join(str(word["text"]) for word in words),
    }


def format_events(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        speaker = f" [{event['speaker']}]" if event.get("speaker") else ""
        lines.append(f"[{format_timestamp(float(event['start']))}]{speaker} {event['text']}")
    return "\n".join(lines) + ("\n" if lines else "")


def merge_plain_text(parts: list[str]) -> str:
    """Join untimed chunks and remove a small exact boundary overlap."""
    merged: list[str] = []
    for text in parts:
        incoming = text.strip().split()
        if not incoming:
            continue
        overlap = 0
        maximum = min(50, len(merged), len(incoming))
        for size in range(maximum, 3, -1):
            if [w.casefold() for w in merged[-size:]] == [w.casefold() for w in incoming[:size]]:
                overlap = size
                break
        merged.extend(incoming[overlap:])
    return " ".join(merged).strip() + ("\n" if merged else "")
