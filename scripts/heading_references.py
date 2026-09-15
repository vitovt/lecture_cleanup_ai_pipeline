from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from scripts.source_timecode_core import (
    HEADING_RE,
    TimestampMarker,
    allocate_src,
    canonical_below,
    canonical_inline,
    document_newline,
    format_hms,
    is_external_target,
    parse_below_marker,
    protected_line_mask,
    render_below_marker,
    render_inline_marker,
    split_trailing_inline,
    strip_trailing_block_ids,
)


@dataclass(frozen=True)
class HeadingReferenceOptions:
    include_inline: bool = True
    include_below: bool = False
    include_src: bool = False
    include_txt_for_untimed: bool = False

    def needs_timestamp_resolution(self) -> bool:
        return any(
            (
                self.include_inline,
                self.include_below,
                self.include_src,
                self.include_txt_for_untimed,
            )
        )


@dataclass(frozen=True)
class HeadingReferenceResult:
    markdown: str
    headings: int
    timed_headings: int
    src_ids: int
    txt_ids: int


def _external_target(*markers: Optional[TimestampMarker]) -> Optional[str]:
    for marker in markers:
        if marker and is_external_target(marker.target):
            return marker.target
    return None


def render_heading_references(
    markdown: str,
    options: HeadingReferenceOptions,
) -> HeadingReferenceResult:
    """Render requested heading formats from shared canonical markers."""
    lines = markdown.splitlines(keepends=True)
    if not lines and markdown:
        lines = [markdown]
    protected = protected_line_mask(lines)
    newline = document_newline(lines)
    output: list[str] = []
    used_src: set[str] = set()
    txt_number = 0
    heading_count = 0
    timed_count = 0
    src_count = 0
    txt_count = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if protected[index]:
            output.append(line)
            index += 1
            continue
        heading_match = HEADING_RE.match(line)
        if not heading_match:
            output.append(line)
            index += 1
            continue

        heading_count += 1
        body, identifiers = strip_trailing_block_ids(heading_match.group("body"))
        existing_src_seconds = next(
            (
                identifier.number
                for identifier in reversed(identifiers)
                if identifier.kind == "src"
            ),
            None,
        )
        base_body, inline = split_trailing_inline(body)
        if inline is not None and inline.seconds is None:
            base_body = body.rstrip()
            inline = None

        below: Optional[TimestampMarker] = None
        below_index = index + 1
        if below_index < len(lines) and not protected[below_index]:
            candidate = parse_below_marker(lines[below_index])
            if candidate is not None and candidate.seconds is not None:
                below = candidate

        if inline is not None:
            seconds = inline.seconds
        elif below is not None:
            seconds = below.seconds
        else:
            seconds = existing_src_seconds
        target = _external_target(inline, below)
        rendered_body = base_body

        if seconds is not None:
            timed_count += 1
            if options.include_inline:
                if inline is not None:
                    rendered_body += inline.separator + inline.raw
                else:
                    inline_text = (
                        render_inline_marker(format_hms(seconds), target)
                        if target
                        else canonical_inline(seconds, local_link=True)
                    )
                    rendered_body += " — " + inline_text
            if options.include_src:
                src_id = allocate_src(seconds, used_src)
                rendered_body += f" {src_id}"
                src_count += 1
        elif options.include_txt_for_untimed:
            txt_number += 1
            rendered_body += f" ^txt-{txt_number}"
            txt_count += 1

        heading_eol = heading_match.group("eol") or ""
        if options.include_below and seconds is not None and not heading_eol:
            heading_eol = newline
        output.append(
            (heading_match.group("bom") or "")
            + heading_match.group("prefix")
            + rendered_body
            + heading_eol
        )

        if options.include_below and seconds is not None:
            below_text = (
                render_below_marker(format_hms(seconds), target)
                if target
                else canonical_below(seconds)
            )
            below_eol = below.eol if below is not None else newline
            output.append(below_text + (below_eol or newline))

        index += 2 if below is not None else 1

    return HeadingReferenceResult(
        markdown="".join(output),
        headings=heading_count,
        timed_headings=timed_count,
        src_ids=src_count,
        txt_ids=txt_count,
    )
