#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from typing import List, Tuple

TIME_RE = re.compile(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})')


def normalize(text: str) -> str:
    """Collapse whitespace and trim the text."""
    return re.sub(r'\s+', ' ', text).strip()


def longest_overlap(previous: str, current: str) -> int:
    """Return length of the longest suffix of previous that is a prefix of current."""
    max_len = min(len(previous), len(current))
    for length in range(max_len, 0, -1):
        if previous.endswith(current[:length]):
            return length
    return 0


def parse_entries(path: Path) -> List[Tuple[str, str]]:
    content = path.read_text(encoding='utf-8', errors='ignore')
    lines = content.splitlines()
    entries: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\n')
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        match = TIME_RE.search(line)
        text_lines = []

        if match:
            start = match.group(1)
            trailing = line[match.end():].strip()
            if trailing:
                text_lines.append(trailing)
            i += 1
        elif stripped.isdigit() and i + 1 < len(lines):
            match = TIME_RE.search(lines[i + 1])
            if match:
                start = match.group(1)
                trailing = lines[i + 1][match.end():].strip()
                if trailing:
                    text_lines.append(trailing)
                i += 2
            else:
                i += 1
                continue
        else:
            i += 1
            continue

        while i < len(lines):
            nxt = lines[i]
            stripped_nxt = nxt.strip()

            if not stripped_nxt:
                # Allow stray blank lines inside a caption block; stop only if the
                # next meaningful line starts a new block.
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines):
                    i = j
                    break
                upcoming = lines[j].strip()
                if TIME_RE.search(lines[j]) or upcoming.isdigit():
                    i = j
                    break
                i = j
                continue

            if TIME_RE.search(nxt) and not stripped_nxt.isdigit():
                break
            text_lines.append(stripped_nxt)
            i += 1

        entry_text = normalize(' '.join(text_lines))
        entries.append((start, entry_text))

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
        print("Usage: python srt_to_custom.py path/to/file.srt", file=sys.stderr)
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
