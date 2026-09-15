from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


TIME_LABEL = r"\d{1,3}:\d{2}(?::\d{2})?"
HEADING_RE = re.compile(
    r"^(?P<prefix>[ \t]{0,3}#{1,6}[ \t]+)"
    r"(?P<body>[^\r\n]*)(?P<eol>\r\n|\n|\r)?$"
)
INLINE_RE = re.compile(
    rf"(?P<separator>[ \t]+(?:—[ \t]+)?)"
    rf"(?P<marker>\[(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?)[ \t]*$"
)
BELOW_RE = re.compile(
    rf"^[ \t]*\[🎥[ \t]+(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?[ \t]*(?P<eol>\r\n|\n|\r)?$"
)
TRAILING_ID_RE = re.compile(
    r"(?P<separator>[ \t]+)\^(?P<kind>src|txt)-"
    r"(?P<number>\d+)(?:-(?P<collision>[2-9]|[1-9]\d+))?[ \t]*$"
)
FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
SUMMARY_START_RE = re.compile(
    r"^[ \t]*<!--[ \t]+LECTURE_CLEANUP_(?:LONG|SHORT)_SUMMARY_START(?:[ \t|]|-->)"
)
SUMMARY_END_RE = re.compile(
    r"^[ \t]*<!--[ \t]+LECTURE_CLEANUP_(?:LONG|SHORT)_SUMMARY_END[ \t]*-->"
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


@dataclass(frozen=True)
class Marker:
    label: str
    seconds: int
    target: Optional[str]
    raw: str
    separator: str = " — "


def _split_eol(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1]
    return line, ""


def _document_newline(lines: list[str]) -> str:
    for line in lines:
        _, eol = _split_eol(line)
        if eol:
            return eol
    return "\n"


def _time_to_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = (int(part) for part in parts)
    else:
        hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError("invalid timestamp")
    return hours * 3600 + minutes * 60 + seconds


def _format_hms(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:02d}"


def _protected_line_mask(lines: list[str]) -> list[bool]:
    mask = [False] * len(lines)
    fence_char: Optional[str] = None
    fence_length = 0
    inside_summary = False

    for index, line in enumerate(lines):
        body, _ = _split_eol(line)
        if inside_summary:
            mask[index] = True
            if SUMMARY_END_RE.match(body):
                inside_summary = False
            continue
        if SUMMARY_START_RE.match(body):
            mask[index] = True
            inside_summary = True
            continue
        if fence_char is None:
            match = FENCE_OPEN_RE.match(body)
            if match:
                token = match.group("fence")
                fence_char = token[0]
                fence_length = len(token)
                mask[index] = True
            continue
        mask[index] = True
        if re.match(
            rf"^[ \t]{{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*$",
            body,
        ):
            fence_char = None
            fence_length = 0
    return mask


def _strip_trailing_ids(body: str) -> tuple[str, Optional[int]]:
    src_seconds: Optional[int] = None
    while True:
        match = TRAILING_ID_RE.search(body)
        if not match:
            return body.rstrip(), src_seconds
        if match.group("kind") == "src" and src_seconds is None:
            src_seconds = int(match.group("number"))
        body = body[:match.start()].rstrip()


def _inline_marker(body: str) -> tuple[str, Optional[Marker]]:
    match = INLINE_RE.search(body)
    if not match:
        return body.rstrip(), None
    try:
        seconds = _time_to_seconds(match.group("label"))
    except ValueError:
        return body.rstrip(), None
    return (
        body[:match.start()].rstrip(),
        Marker(
            label=match.group("label"),
            seconds=seconds,
            target=match.group("target"),
            raw=match.group("marker"),
            separator=match.group("separator"),
        ),
    )


def _below_marker(line: str) -> Optional[Marker]:
    match = BELOW_RE.match(line)
    if not match:
        return None
    try:
        seconds = _time_to_seconds(match.group("label"))
    except ValueError:
        return None
    body, _ = _split_eol(line)
    return Marker(
        label=match.group("label"),
        seconds=seconds,
        target=match.group("target"),
        raw=body.strip(),
    )


def _external_target(*markers: Optional[Marker]) -> Optional[str]:
    for marker in markers:
        if marker and marker.target and marker.target.startswith(("http://", "https://")):
            return marker.target
    return None


def render_heading_references(
    markdown: str,
    options: HeadingReferenceOptions,
) -> HeadingReferenceResult:
    """Render heading reference formats from one canonical timestamp marker."""
    lines = markdown.splitlines(keepends=True)
    if not lines and markdown:
        lines = [markdown]
    protected = _protected_line_mask(lines)
    newline = _document_newline(lines)
    output: list[str] = []
    src_occurrences: dict[int, int] = {}
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
        body, existing_src_seconds = _strip_trailing_ids(heading_match.group("body"))
        base_body, inline = _inline_marker(body)
        below: Optional[Marker] = None
        below_index = index + 1
        if below_index < len(lines) and not protected[below_index]:
            below = _below_marker(lines[below_index])

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
            label = _format_hms(seconds)
            if options.include_inline:
                if inline is not None:
                    rendered_body += inline.separator + inline.raw
                else:
                    inline_target = target or f"#t={label}"
                    rendered_body += f" — [{label}]({inline_target})"
            if options.include_src:
                occurrence = src_occurrences.get(seconds, 0) + 1
                src_occurrences[seconds] = occurrence
                suffix = "" if occurrence == 1 else f"-{occurrence}"
                rendered_body += f" ^src-{seconds}{suffix}"
                src_count += 1
        elif options.include_txt_for_untimed:
            txt_number += 1
            rendered_body += f" ^txt-{txt_number}"
            txt_count += 1

        heading_eol = heading_match.group("eol") or ""
        if options.include_below and seconds is not None and not heading_eol:
            heading_eol = newline
        output.append(heading_match.group("prefix") + rendered_body + heading_eol)

        if options.include_below and seconds is not None:
            label = _format_hms(seconds)
            below_target = target or "#"
            _, below_eol = (
                _split_eol(lines[below_index])
                if below is not None
                else ("", newline)
            )
            output.append(f"[🎥 {label}]({below_target}){below_eol or newline}")

        index += 2 if below is not None else 1

    return HeadingReferenceResult(
        markdown="".join(output),
        headings=heading_count,
        timed_headings=timed_count,
        src_ids=src_count,
        txt_ids=txt_count,
    )
