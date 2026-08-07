#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from typing import List, Tuple


TIMESTAMP = r'(?:\d+:)?\d{2}:\d{2}\.\d{3}'
TIME_RE = re.compile(
    rf'^\s*(?P<start>{TIMESTAMP})\s*-->\s*(?P<end>{TIMESTAMP})(?:[ \t]+.*)?$'
)


def normalize(text: str) -> str:
    """Collapse whitespace and trim the text."""
    return re.sub(r'\s+', ' ', text).strip()


def normalize_timestamp(timestamp: str) -> str:
    """Convert a WebVTT timestamp to the timestamp format used in the output."""
    parts = timestamp.split(':')
    if len(parts) == 2:
        hours = '00'
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts

    return f"{int(hours):02d}:{minutes}:{seconds.replace('.', ',')}"


def longest_overlap(previous: str, current: str) -> int:
    """Return length of the longest suffix of previous that is a prefix of current."""
    max_len = min(len(previous), len(current))
    for length in range(max_len, 0, -1):
        if previous.endswith(current[:length]):
            return length
    return 0


def parse_entries(path: Path) -> List[Tuple[str, str]]:
    content = path.read_text(encoding='utf-8-sig', errors='ignore')
    blocks = re.split(r'(?:\r?\n)[ \t]*(?:\r?\n)+', content)
    entries: List[Tuple[str, str]] = []

    for block in blocks:
        lines = block.splitlines()
        first_line = lines[0].strip() if lines else ''
        if (
            first_line == 'WEBVTT'
            or first_line.startswith('WEBVTT ')
            or first_line == 'NOTE'
            or first_line.startswith('NOTE ')
            or first_line in {'STYLE', 'REGION'}
        ):
            continue

        timing_index = None
        match = None

        for index, line in enumerate(lines):
            match = TIME_RE.match(line)
            if match:
                timing_index = index
                break

        if match is None or timing_index is None:
            continue

        start = normalize_timestamp(match.group('start'))
        text = normalize(' '.join(lines[timing_index + 1:]))
        entries.append((start, text))

    return entries


def dedupe_entries(entries: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    prev_text = ''

    for start, text in entries:
        if not text:
            continue

        if not prev_text:
            cleaned = text
        else:
            if text == prev_text:
                prev_text = text
                continue

            if text.startswith(prev_text):
                cleaned = text[len(prev_text):].lstrip()
                if not cleaned:
                    prev_text = text
                    continue
            elif prev_text.startswith(text):
                prev_text = text
                continue
            else:
                overlap = longest_overlap(prev_text, text)
                cleaned = text[overlap:].lstrip() if overlap else text
                if not cleaned:
                    prev_text = text
                    continue

        result.append((start, cleaned))
        prev_text = text

    return result


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python vtt_to_custom.py path/to/file.vtt", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    entries = parse_entries(path)
    cleaned = dedupe_entries(entries)

    for start, text in cleaned:
        if text:
            print(f"[{start}] {text}")


if __name__ == "__main__":
    main()
