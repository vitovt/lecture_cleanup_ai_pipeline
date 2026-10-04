"""Shared Markdown timestamp, block-ID, and YouTube URL primitives.

This module deliberately contains no CLI or pipeline policy.  Callers decide
whether conflicting markers are errors, whether a representation is retained,
and where transformed content is written.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
TIMESTAMP_QUERY_KEYS = {"t", "start", "time_continue"}
TIME_LABEL = r"\d{1,3}:\d{2}(?::\d{2})?"
COLLISION_NUMBER = r"(?:[2-9]|[1-9]\d+)"

HEADING_RE = re.compile(
    r"^(?P<bom>\ufeff?)(?P<prefix>[ \t]{0,3}#{1,6}[ \t]+)"
    r"(?P<body>[^\r\n]*)(?P<eol>\r\n|\n|\r)?$"
)
INLINE_RE = re.compile(
    rf"(?P<separator>[ \t]+(?:—[ \t]+)?)"
    rf"(?P<marker>\[(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?)[ \t]*$"
)
INLINE_ANY_RE = re.compile(
    rf"(?P<marker>\[(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]*)\))?)"
)
BELOW_RE = re.compile(
    rf"^[ \t]*\[(?P<icon>🎥)[ \t]+(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?[ \t]*(?P<eol>\r\n|\n|\r)?$"
)
SRC_TRAILING_RE = re.compile(
    r"(?P<separator>[ \t]+)(?P<identifier>\^src-(?P<seconds>\d+)"
    rf"(?:-(?P<collision>{COLLISION_NUMBER}))?)[ \t]*$"
)
SRC_TOKEN_RE = re.compile(r"(?<!\S)(?P<identifier>\^src\S*)")
SRC_FULL_RE = re.compile(rf"^\^src-\d+(?:-{COLLISION_NUMBER})?$")
TRAILING_BLOCK_ID_RE = re.compile(
    r"(?P<separator>[ \t]+)\^(?P<kind>src|txt)-"
    rf"(?P<number>\d+)(?:-(?P<collision>{COLLISION_NUMBER}))?[ \t]*$"
)
FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
SUMMARY_START_RE = re.compile(
    r"^[ \t]*<!--[ \t]+LECTURE_CLEANUP_(?:LONG|SHORT)_SUMMARY_START"
    r"(?:[ \t|]|-->)"
)
SUMMARY_END_RE = re.compile(
    r"^[ \t]*<!--[ \t]+LECTURE_CLEANUP_(?:LONG|SHORT)_SUMMARY_END[ \t]*-->"
)


@dataclass(frozen=True)
class TimestampMarker:
    label: str
    seconds: Optional[int]
    target: Optional[str]
    raw: str
    start: int
    end: int
    separator: str = " "
    eol: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class BlockIdentifier:
    kind: str
    number: int
    collision: Optional[int]
    raw: str


@dataclass(frozen=True)
class YouTubeUrl:
    video_id: str
    base_url: str
    query: tuple[tuple[str, str], ...]
    legacy_timestamp_syntax: bool = False


def split_eol(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1]
    return line, ""


def document_newline(lines: list[str]) -> str:
    for line in lines:
        _, eol = split_eol(line)
        if eol:
            return eol
    return os.linesep


def time_to_seconds(value: str) -> int:
    """Parse seconds, YouTube time units, MM:SS, or HH:MM:SS."""
    value = value.strip()
    numeric = re.fullmatch(r"(\d+)(?:s)?", value, flags=re.IGNORECASE)
    if numeric:
        return int(numeric.group(1))

    youtube_units = re.fullmatch(
        r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?",
        value,
        flags=re.IGNORECASE,
    )
    if youtube_units and any(
        group is not None for group in youtube_units.groups()
    ):
        hours, minutes, seconds = (
            int(group or 0) for group in youtube_units.groups()
        )
        return hours * 3600 + minutes * 60 + seconds

    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        raise ValueError("expected seconds, MM:SS, or HH:MM:SS")
    values = [int(part) for part in parts]
    if len(values) == 2:
        minutes, seconds = values
        if seconds > 59:
            raise ValueError("seconds must be 00..59")
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    if minutes > 59 or seconds > 59:
        raise ValueError("minutes and seconds must be 00..59")
    return hours * 3600 + minutes * 60 + seconds


def format_hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:02d}"


def _parsed_seconds(label: str) -> tuple[Optional[int], Optional[str]]:
    try:
        return time_to_seconds(label), None
    except ValueError as exc:
        return None, str(exc)


def _marker_from_match(match: re.Match[str], *, trailing: bool) -> TimestampMarker:
    seconds, error = _parsed_seconds(match.group("label"))
    marker_start = match.start("marker")
    marker_end = match.end("marker")
    return TimestampMarker(
        label=match.group("label"),
        seconds=seconds,
        target=match.group("target"),
        raw=match.group("marker"),
        start=marker_start,
        end=marker_end,
        separator=match.group("separator") if trailing else " ",
        error=error,
    )


def find_inline_markers(body: str) -> list[TimestampMarker]:
    return [
        _marker_from_match(match, trailing=False)
        for match in INLINE_ANY_RE.finditer(body)
    ]


def parse_trailing_inline(body: str) -> Optional[TimestampMarker]:
    match = INLINE_RE.search(body)
    return _marker_from_match(match, trailing=True) if match else None


def split_trailing_inline(
    body: str,
) -> tuple[str, Optional[TimestampMarker]]:
    marker = parse_trailing_inline(body)
    if marker is None:
        return body.rstrip(), None
    attachment_start = marker.start - len(marker.separator)
    return body[:attachment_start].rstrip(), marker


def parse_below_marker(line: str) -> Optional[TimestampMarker]:
    match = BELOW_RE.match(line)
    if not match:
        return None
    seconds, error = _parsed_seconds(match.group("label"))
    body, eol = split_eol(line)
    return TimestampMarker(
        label=match.group("label"),
        seconds=seconds,
        target=match.group("target"),
        raw=body.strip(),
        start=0,
        end=len(body),
        eol=eol,
        error=error,
    )


def strip_trailing_block_ids(
    body: str,
) -> tuple[str, list[BlockIdentifier]]:
    identifiers: list[BlockIdentifier] = []
    while True:
        match = TRAILING_BLOCK_ID_RE.search(body)
        if not match:
            identifiers.reverse()
            return body.rstrip(), identifiers
        identifiers.append(
            BlockIdentifier(
                kind=match.group("kind"),
                number=int(match.group("number")),
                collision=(
                    int(match.group("collision"))
                    if match.group("collision")
                    else None
                ),
                raw=match.group(0).strip(),
            )
        )
        body = body[:match.start()].rstrip()


def fenced_block_ranges(lines):
    """Yield half-open ranges, keeping adjacent fenced blocks separate."""
    start = None
    token = None
    for index, line in enumerate(lines):
        body, _ = split_eol(line)
        if start is None:
            match = FENCE_OPEN_RE.match(body)
            if match:
                start, token = index, match.group("fence")
        elif re.fullmatch(rf"[ \t]{{0,3}}{re.escape(token[0])}{{{len(token)},}}[ \t]*", body):
            yield start, index + 1
            start, token = None, None
    if start is not None:
        yield start, len(lines)


def protected_line_mask(
    lines: list[str],
    *,
    protect_summaries: bool = True,
) -> list[bool]:
    """Mark fenced-code and, optionally, generated-summary lines as protected."""
    mask = [False] * len(lines)
    for start, end in fenced_block_ranges(lines):
        mask[start:end] = [True] * (end - start)
    inside_summary = False

    for index, line in enumerate(lines):
        body, _ = split_eol(line)
        if mask[index]:
            continue
        if protect_summaries and inside_summary:
            mask[index] = True
            if SUMMARY_END_RE.match(body):
                inside_summary = False
            continue
        if protect_summaries and SUMMARY_START_RE.match(body):
            mask[index] = True
            inside_summary = True
            continue
    return mask


def is_external_target(target: Optional[str]) -> bool:
    if target is None:
        return False
    return target.strip().lower().startswith(("http://", "https://"))


def is_local_target(target: Optional[str]) -> bool:
    if target is None:
        return True
    value = target.strip()
    return value == "#" or value.startswith("#t=")


def render_inline_marker(label: str, target: Optional[str] = None) -> str:
    marker = f"[{label}]"
    return f"{marker}({target})" if target is not None else marker


def render_below_marker(label: str, target: Optional[str] = "#") -> str:
    marker = f"[🎥 {label}]"
    return f"{marker}({target})" if target is not None else marker


def parse_youtube_url(value: str) -> YouTubeUrl:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid URL: {exc}") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("video URL must be an absolute HTTP(S) URL")
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise ValueError(f"unsupported video host: {host or '<empty>'}")

    path = parsed.path.rstrip("/")
    base_path = parsed.path
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    legacy_timestamp_syntax = False
    if host in ("youtu.be", "www.youtu.be"):
        path_parts = path.lstrip("/").split("/", 1)
        short_path = path_parts[0]
        if "&" in short_path:
            video_id, legacy_query = short_path.split("&", 1)
            legacy_pairs = list(parse_qsl(legacy_query, keep_blank_values=True))
            query = legacy_pairs + query
            legacy_timestamp_syntax = any(
                key.lower() in TIMESTAMP_QUERY_KEYS
                for key, _ in legacy_pairs
            )
            path_suffix = f"/{path_parts[1]}" if len(path_parts) == 2 else ""
            base_path = f"/{video_id}{path_suffix}"
        else:
            video_id = short_path
    elif path == "/watch":
        video_id = dict(query).get("v", "")
    elif path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
        parts = path.split("/", 2)
        video_id = parts[2] if len(parts) == 3 else ""
    else:
        video_id = ""
    if not video_id:
        raise ValueError("YouTube URL has no supported video ID")

    cleaned_query = [
        (key, val)
        for key, val in query
        if key.lower() not in TIMESTAMP_QUERY_KEYS
    ]
    base_url = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            base_path,
            urlencode(cleaned_query, doseq=True),
            "",
        )
    )
    return YouTubeUrl(
        video_id=video_id,
        base_url=base_url,
        query=tuple(query),
        legacy_timestamp_syntax=legacy_timestamp_syntax,
    )


def youtube_base_url(value: str) -> tuple[str, str]:
    parsed = parse_youtube_url(value)
    return parsed.video_id, parsed.base_url


def extract_youtube_video_id(
    value: str,
    *,
    allow_bare: bool = False,
    allow_missing_scheme: bool = False,
) -> Optional[str]:
    """Extract a video ID while optionally accepting CLI-friendly shorthand."""
    candidate = value.strip()
    if not candidate:
        return None
    if allow_bare and "://" not in candidate and "/" not in candidate:
        video_id = re.split(r"[?&#]", candidate, maxsplit=1)[0].strip()
        return video_id or None
    if allow_missing_scheme and not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate
    try:
        return parse_youtube_url(candidate).video_id
    except ValueError:
        return None


def timestamp_url(base_url: str, seconds: int) -> str:
    parsed = urlsplit(base_url)
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TIMESTAMP_QUERY_KEYS
    ]
    query.append(("t", f"{seconds}s"))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, doseq=True),
            "",
        )
    )


def canonical_inline(
    seconds: float,
    base_url: Optional[str] = None,
    *,
    local_link: bool = False,
) -> str:
    total_seconds = max(0, int(round(seconds)))
    label = format_hms(total_seconds)
    if base_url:
        target = timestamp_url(base_url, total_seconds)
    elif local_link:
        target = f"#t={label}"
    else:
        target = None
    return render_inline_marker(label, target)


def canonical_below(seconds: float, base_url: Optional[str] = None) -> str:
    total_seconds = max(0, int(round(seconds)))
    label = format_hms(total_seconds)
    target = timestamp_url(base_url, total_seconds) if base_url else "#"
    return render_below_marker(label, target)


def allocate_src(seconds: int, used: set[str]) -> str:
    base = f"^src-{seconds}"
    if base not in used:
        used.add(base)
        return base
    collision = 2
    while f"{base}-{collision}" in used:
        collision += 1
    identifier = f"{base}-{collision}"
    used.add(identifier)
    return identifier
