from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from multitrack.formats import TranscriptSource, merge_documents, write_custom_txt

def read_timestamped_txt(path: Path) -> list:
    """Read the existing cleanup interchange format; never guess missing times."""
    import re
    from multitrack.formats import TranscriptEvent
    pattern = re.compile(r'^\[(\d+):([0-5]\d):([0-5]\d)[,.](\d{3})\]\s*(?:\[([^\]\r\n]+)\]\s*)?(.*)$')
    events = []
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        match = pattern.fullmatch(line.strip())
        if not match or not match[6].strip():
            raise ValueError(f'{path}:{number}: expected [HH:MM:SS,mmm] [speaker] text')
        hours, minutes, seconds, millis = map(int, match.group(1, 2, 3, 4))
        start = hours * 3600 + minutes * 60 + seconds + millis / 1000
        events.append(TranscriptEvent(start, match[6].strip(), match[5]))
    return events


def name_source_events(events: list, name: str, diarization: str, expected: str = 'auto') -> list:
    import sys
    if diarization == 'off':
        return [replace(event, speaker=name) for event in events]
    if any(not event.speaker for event in events):
        raise ValueError(f'{name}: requested diarization returned speech without speaker labels')
    labels = list(dict.fromkeys(event.speaker for event in events))
    if expected != 'auto' and len(labels) != int(expected):
        print(f'WARNING: {name}: expected {expected} speakers, detected {len(labels)}', file=sys.stderr)
    mapping = {label: name if len(labels) == 1 else f'{name}_{i+1:02d}' for i,label in enumerate(labels)}
    return [replace(event, speaker=mapping[event.speaker]) for event in events]


def merge_txt_files(sources: list[tuple[Path, float]], output: Path) -> Path:
    documents = [TranscriptSource(offset, index,
                               tuple(read_timestamped_txt(path)))
                 for index, (path, offset) in enumerate(sources)]
    events = merge_documents(documents)
    if not events:
        raise ValueError('sources contain no timed speech')
    return write_custom_txt(output, events)
