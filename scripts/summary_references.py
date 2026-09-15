from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from scripts.source_timecode_core import (
    HEADING_RE,
    format_hms,
    parse_below_marker,
    protected_line_mask,
    split_trailing_inline,
    strip_trailing_block_ids,
)


BLOCK_ID_PATTERN = r"(?:src-\d+(?:-(?:[2-9]|[1-9]\d+))?|txt-\d+(?:-(?:[2-9]|[1-9]\d+))?)"
REFERENCE_LINK_RE = re.compile(
    rf"\[\[(?P<note>[^#|\]\r\n]*)#\^(?P<identifier>{BLOCK_ID_PATTERN})"
    r"\|(?P<label>[^\]\r\n]+)\]\]"
)


@dataclass(frozen=True)
class SourceBlock:
    identifier: str
    timestamp: Optional[str]


class SummaryReferenceError(RuntimeError):
    pass


def collect_source_blocks(markdown: str) -> dict[str, SourceBlock]:
    lines = markdown.splitlines(keepends=True)
    if not lines and markdown:
        lines = [markdown]
    protected = protected_line_mask(lines)
    blocks: dict[str, SourceBlock] = {}

    for index, line in enumerate(lines):
        if protected[index]:
            continue
        heading = HEADING_RE.match(line)
        if not heading:
            continue

        body, identifiers = strip_trailing_block_ids(heading.group("body"))
        _, inline = split_trailing_inline(body)
        below = None
        if index + 1 < len(lines) and not protected[index + 1]:
            below = parse_below_marker(lines[index + 1])
        visible_seconds = None
        if inline is not None and inline.seconds is not None:
            visible_seconds = inline.seconds
        elif below is not None and below.seconds is not None:
            visible_seconds = below.seconds

        for identifier in identifiers:
            identifier_text = identifier.raw.removeprefix("^")
            timestamp = None
            if identifier.kind == "src" and visible_seconds == identifier.number:
                timestamp = format_hms(identifier.number)
            blocks[identifier_text] = SourceBlock(identifier_text, timestamp)
    return blocks


def _parse_reference_line(line: str, line_number: int) -> list[tuple[str, str, str]]:
    stripped = line.rstrip("\r\n")
    if not stripped.startswith("↩ "):
        raise SummaryReferenceError(
            f"long-summary heading at line {line_number - 1} has no immediate "
            "source reference"
        )
    content = stripped[2:]
    matches = list(REFERENCE_LINK_RE.finditer(content))
    if not matches:
        raise SummaryReferenceError(
            f"invalid source reference at long-summary line {line_number}"
        )
    if content != " · ".join(match.group(0) for match in matches):
        raise SummaryReferenceError(
            f"invalid source reference syntax at long-summary line {line_number}"
        )
    return [
        (match.group("note"), match.group("identifier"), match.group("label"))
        for match in matches
    ]


def validate_long_summary_references(
    summary: str,
    source_markdown: str,
    *,
    source_note: str,
) -> None:
    source_blocks = collect_source_blocks(source_markdown)
    if not source_blocks:
        raise SummaryReferenceError(
            "long-summary references were requested, but the source has no "
            "^src-* or ^txt-* heading IDs"
        )

    lines = summary.splitlines(keepends=True)
    if not lines and summary:
        lines = [summary]
    protected = protected_line_mask(lines, protect_summaries=False)
    checked_headings = 0

    for index, line in enumerate(lines):
        if protected[index]:
            continue
        heading = HEADING_RE.match(line)
        if not heading:
            continue
        level = heading.group("prefix").count("#")
        if level not in (3, 4):
            continue
        checked_headings += 1
        if index + 1 >= len(lines) or protected[index + 1]:
            raise SummaryReferenceError(
                f"long-summary heading at line {index + 1} has no immediate "
                "source reference"
            )

        references = _parse_reference_line(lines[index + 1], index + 2)
        seen: set[str] = set()
        for note, identifier, label in references:
            if note != source_note:
                expected = "current document" if not source_note else source_note
                raise SummaryReferenceError(
                    f"source reference at long-summary line {index + 2} targets "
                    f"the wrong note; expected {expected!r}"
                )
            if identifier not in source_blocks:
                raise SummaryReferenceError(
                    f"unknown source block ^{identifier} at long-summary line "
                    f"{index + 2}"
                )
            if identifier in seen:
                raise SummaryReferenceError(
                    f"duplicate source block ^{identifier} at long-summary line "
                    f"{index + 2}"
                )
            seen.add(identifier)

            source_block = source_blocks[identifier]
            if source_block.timestamp is not None:
                allowed_labels = {
                    source_block.timestamp,
                    f"Source · {source_block.timestamp}",
                }
            else:
                allowed_labels = {"Source"}
            if label not in allowed_labels:
                raise SummaryReferenceError(
                    f"invalid label for ^{identifier} at long-summary line "
                    f"{index + 2}"
                )

    if checked_headings == 0:
        raise SummaryReferenceError(
            "long-summary references were requested, but the response has no "
            "### or #### headings"
        )
