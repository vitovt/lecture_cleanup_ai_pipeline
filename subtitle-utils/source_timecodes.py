#!/usr/bin/env python3

"""Inspect and convert timestamp representations attached to Markdown headings."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LEGEND = "LEGEND I=inline B=below S=src"
EMPTY_FORMATS = "∅"
COMMANDS = {"doctor", "analyze", "transform"}
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

HEADING_RE = re.compile(
    r"^(?P<bom>\ufeff?)(?P<prefix>[ \t]{0,3}#{1,6}[ \t]+)"
    r"(?P<body>[^\r\n]*)(?P<eol>\r\n|\n|\r)?$"
)
TIME_LABEL = r"\d{1,3}:\d{2}(?::\d{2})?"
INLINE_RE = re.compile(
    rf"(?P<separator>[ \t]+(?:—[ \t]+)?)"
    rf"(?P<marker>\[(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?)[ \t]*$"
)
INLINE_ANY_RE = re.compile(rf"\[{TIME_LABEL}\](?:\([^)\r\n]*\))?")
BELOW_RE = re.compile(
    rf"^[ \t]*\[(?P<icon>🎥)[ \t]+(?P<label>{TIME_LABEL})\]"
    rf"(?:\((?P<target>[^)\r\n]+)\))?[ \t]*(?P<eol>\r\n|\n|\r)?$"
)
COLLISION_NUMBER = r"(?:[2-9]|[1-9]\d+)"
SRC_RE = re.compile(
    rf"(?<!\S)\^src-(?P<seconds>\d+)(?:-(?P<collision>{COLLISION_NUMBER}))?(?=\s|$)"
)
SRC_TRAILING_RE = re.compile(
    r"(?P<separator>[ \t]+)(?P<identifier>\^src-(?P<seconds>\d+)"
    rf"(?:-(?P<collision>{COLLISION_NUMBER}))?)[ \t]*$"
)
SRC_TOKEN_RE = re.compile(r"(?<!\S)(?P<identifier>\^src\S*)")
SRC_FULL_RE = re.compile(rf"^\^src-\d+(?:-{COLLISION_NUMBER})?$")
FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")


class ToolError(Exception):
    """A user-facing error with an intended process exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class Issue:
    code: str
    line: int
    message: str


@dataclass
class TargetInfo:
    raw: Optional[str]
    external: bool = False
    video_id: Optional[str] = None
    seconds: Optional[int] = None
    base_url: Optional[str] = None
    legacy_youtube_url: bool = False


@dataclass
class Marker:
    kind: str
    line_index: int
    line_number: int
    label: str
    seconds: Optional[int]
    raw: str
    target: TargetInfo
    separator: str = " "
    eol: str = ""


@dataclass
class Heading:
    line_index: int
    line_number: int
    prefix: str
    base_body: str
    eol: str
    original_line: str
    inline: Optional[Marker] = None
    below: Optional[Marker] = None
    src_id: Optional[str] = None
    src_seconds: Optional[int] = None
    timestamp_seconds: Optional[int] = None

    def representations(self) -> set[str]:
        result: set[str] = set()
        if self.inline:
            result.add("I")
        if self.below:
            result.add("B")
        if self.src_id:
            result.add("S")
        return result


@dataclass
class Document:
    path: Path
    text: str
    lines: list[str]
    headings: list[Heading]
    issues: list[Issue] = field(default_factory=list)
    url_state: str = "none"
    video_base_url: Optional[str] = None
    warnings: list[Issue] = field(default_factory=list)

    def formats(self) -> set[str]:
        result: set[str] = set()
        for heading in self.headings:
            result.update(heading.representations())
        return result


def json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def format_set(values: Iterable[str]) -> str:
    present = set(values)
    ordered = [name for name in ("I", "B", "S") if name in present]
    return "+".join(ordered) if ordered else EMPTY_FORMATS


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
    value = value.strip()
    numeric = re.fullmatch(r"(\d+)(?:s)?", value, flags=re.IGNORECASE)
    if numeric:
        return int(numeric.group(1))

    youtube_units = re.fullmatch(
        r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?",
        value,
        flags=re.IGNORECASE,
    )
    if youtube_units and any(group is not None for group in youtube_units.groups()):
        hours, minutes, seconds = (int(group or 0) for group in youtube_units.groups())
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


def format_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:02d}"


def parse_label(value: str, line_number: int, issues: list[Issue]) -> Optional[int]:
    try:
        return time_to_seconds(value)
    except ValueError as exc:
        issues.append(Issue("malformed_timestamp", line_number, str(exc)))
        return None


def parse_youtube_url(
    value: str,
) -> tuple[str, str, list[tuple[str, str]], bool]:
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
    legacy_youtube_url = False
    if host in ("youtu.be", "www.youtu.be"):
        path_parts = path.lstrip("/").split("/", 1)
        short_path = path_parts[0]
        if "&" in short_path:
            # Older pipeline output used youtu.be/ID&t=SECONDS.  Although the
            # timestamp is technically part of the URL path, treat the suffix
            # as a query string so existing documents remain valid input.
            video_id, legacy_query = short_path.split("&", 1)
            legacy_pairs = list(parse_qsl(legacy_query, keep_blank_values=True))
            query = legacy_pairs + query
            legacy_youtube_url = any(
                key.lower() in ("t", "start", "time_continue")
                for key, _ in legacy_pairs
            )
            path_suffix = f"/{path_parts[1]}" if len(path_parts) == 2 else ""
            base_path = f"/{video_id}{path_suffix}"
        else:
            video_id = short_path
    elif path == "/watch":
        query_map = dict(query)
        video_id = query_map.get("v", "")
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
        if key.lower() not in ("t", "start", "time_continue")
    ]
    base = urlunsplit(
        (parsed.scheme, parsed.netloc, base_path, urlencode(cleaned_query, doseq=True), "")
    )
    return video_id, base, query, legacy_youtube_url


def youtube_base_url(value: str) -> tuple[str, str]:
    video_id, base_url, _, _ = parse_youtube_url(value)
    return video_id, base_url


def timestamp_url(base_url: str, seconds: int) -> str:
    parsed = urlsplit(base_url)
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in ("t", "start", "time_continue")
    ]
    query.append(("t", f"{seconds}s"))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), "")
    )


def parse_target(raw: Optional[str], line_number: int, issues: list[Issue]) -> TargetInfo:
    if raw is None:
        return TargetInfo(raw=None)
    value = raw.strip()
    if value == "#":
        return TargetInfo(raw=value)
    if value.startswith("#t="):
        encoded = value[3:]
        try:
            seconds = time_to_seconds(encoded)
        except ValueError as exc:
            issues.append(Issue("malformed_local_target", line_number, str(exc)))
            return TargetInfo(raw=value)
        return TargetInfo(raw=value, seconds=seconds)

    try:
        video_id, base_url, query, legacy_youtube_url = parse_youtube_url(value)
    except ValueError as exc:
        issues.append(Issue("malformed_video_url", line_number, str(exc)))
        return TargetInfo(raw=value)

    timing_values = [
        val
        for key, val in query
        if key.lower() in ("t", "start", "time_continue")
    ]
    if not timing_values:
        issues.append(Issue("missing_url_timestamp", line_number, "video URL has no t/start parameter"))
        target_seconds = None
    else:
        try:
            target_seconds = time_to_seconds(timing_values[-1])
        except ValueError as exc:
            issues.append(Issue("malformed_url_timestamp", line_number, str(exc)))
            target_seconds = None
    return TargetInfo(
        raw=value,
        external=True,
        video_id=video_id,
        seconds=target_seconds,
        base_url=base_url,
        legacy_youtube_url=legacy_youtube_url,
    )


def code_fence_mask(lines: list[str]) -> list[bool]:
    mask = [False] * len(lines)
    fence_char: Optional[str] = None
    fence_length = 0
    for index, line in enumerate(lines):
        body, _ = split_eol(line)
        if fence_char is None:
            match = FENCE_OPEN_RE.match(body)
            if match:
                token = match.group("fence")
                fence_char = token[0]
                fence_length = len(token)
                mask[index] = True
            continue
        mask[index] = True
        if re.match(rf"^[ \t]{{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*$", body):
            fence_char = None
            fence_length = 0
    return mask


def parse_document(path: Path, text: str) -> Document:
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    issues: list[Issue] = []
    warnings: list[Issue] = []
    headings: list[Heading] = []
    fence_mask = code_fence_mask(lines)
    below_candidates: dict[int, Marker] = {}

    for index, line in enumerate(lines):
        if fence_mask[index]:
            continue
        below_match = BELOW_RE.match(line)
        if below_match:
            label = below_match.group("label")
            seconds = parse_label(label, index + 1, issues)
            target = parse_target(below_match.group("target"), index + 1, issues)
            below_candidates[index] = Marker(
                "B",
                index,
                index + 1,
                label,
                seconds,
                split_eol(line)[0].strip(),
                target,
                eol=below_match.group("eol") or "",
            )

        match = HEADING_RE.match(line)
        if not match:
            continue
        body = match.group("body")
        src_tokens = [match.group("identifier") for match in SRC_TOKEN_RE.finditer(body)]
        invalid_src = [token for token in src_tokens if not SRC_FULL_RE.fullmatch(token)]
        for token in invalid_src:
            issues.append(Issue("malformed_src", index + 1, f"invalid src identifier: {token}"))
        valid_src_tokens = [token for token in src_tokens if SRC_FULL_RE.fullmatch(token)]
        if len(src_tokens) > 1:
            issues.append(Issue("multiple_src", index + 1, "heading contains multiple src identifiers"))

        src_id: Optional[str] = None
        src_seconds: Optional[int] = None
        src_match = SRC_TRAILING_RE.search(body)
        if src_match:
            src_id = src_match.group("identifier")
            src_seconds = int(src_match.group("seconds"))
            body_without_src = body[: src_match.start()].rstrip()
        else:
            body_without_src = body
            if valid_src_tokens:
                issues.append(Issue("misplaced_src", index + 1, "src identifier must end the heading"))

        inline: Optional[Marker] = None
        inline_match = INLINE_RE.search(body_without_src)
        inline_tokens = list(INLINE_ANY_RE.finditer(body_without_src))
        if len(inline_tokens) > 1:
            issues.append(Issue("multiple_inline", index + 1, "heading contains multiple inline timestamps"))
        elif inline_tokens and not inline_match:
            issues.append(Issue("misplaced_inline", index + 1, "inline timestamp must end the heading or precede src"))
        if inline_match:
            label = inline_match.group("label")
            seconds = parse_label(label, index + 1, issues)
            target = parse_target(inline_match.group("target"), index + 1, issues)
            inline = Marker(
                "I",
                index,
                index + 1,
                label,
                seconds,
                inline_match.group("marker"),
                target,
                separator=inline_match.group("separator"),
                eol=match.group("eol") or "",
            )
            base_body = body_without_src[: inline_match.start()].rstrip()
        else:
            base_body = body_without_src.rstrip()

        headings.append(
            Heading(
                line_index=index,
                line_number=index + 1,
                prefix=(match.group("bom") or "") + match.group("prefix"),
                base_body=base_body,
                eol=match.group("eol") or "",
                original_line=line,
                inline=inline,
                src_id=src_id,
                src_seconds=src_seconds,
            )
        )

    consumed_below: set[int] = set()
    for heading in headings:
        index = heading.line_index + 1
        while index < len(lines) and not split_eol(lines[index])[0].strip():
            index += 1
        if index in below_candidates:
            heading.below = below_candidates[index]
            consumed_below.add(index)

    for index in sorted(set(below_candidates) - consumed_below):
        issues.append(Issue("orphan_below", index + 1, "below marker is not attached to a heading"))

    used_src: dict[str, int] = {}
    external_markers: list[tuple[Heading, Marker]] = []
    timestamped: list[Heading] = []
    for heading in headings:
        values: list[tuple[str, int, int]] = []
        for marker in (heading.inline, heading.below):
            if marker:
                if marker.seconds is not None:
                    values.append((marker.kind, marker.seconds, marker.line_number))
                if marker.target.seconds is not None:
                    values.append((f"{marker.kind}-target", marker.target.seconds, marker.line_number))
                if marker.target.external:
                    external_markers.append((heading, marker))
                if marker.target.legacy_youtube_url:
                    warnings.append(
                        Issue(
                            "legacy_youtube_url",
                            marker.line_number,
                            "youtu.be timestamp uses & instead of ?; "
                            "accepted for compatibility but should be fixed",
                        )
                    )
        if heading.src_seconds is not None:
            values.append(("S", heading.src_seconds, heading.line_number))
        unique_seconds = {value for _, value, _ in values}
        if len(unique_seconds) > 1:
            detail = ", ".join(f"{kind}={value}s@{line}" for kind, value, line in values)
            issues.append(Issue("timestamp_conflict", heading.line_number, detail))
        elif unique_seconds:
            heading.timestamp_seconds = next(iter(unique_seconds))
            timestamped.append(heading)

        if heading.src_id:
            if heading.src_id in used_src:
                issues.append(
                    Issue(
                        "duplicate_src",
                        heading.line_number,
                        f"{heading.src_id} also appears at line {used_src[heading.src_id]}",
                    )
                )
            else:
                used_src[heading.src_id] = heading.line_number

    video_ids = {marker.target.video_id for _, marker in external_markers if marker.target.video_id}
    if len(video_ids) > 1:
        issues.append(
            Issue(
                "conflicting_video_urls",
                external_markers[0][1].line_number,
                "multiple YouTube video IDs: " + ", ".join(sorted(video_ids)),
            )
        )

    if external_markers:
        for heading in timestamped:
            carriers = [marker for marker in (heading.inline, heading.below) if marker]
            if not carriers or any(not marker.target.external for marker in carriers):
                issues.append(
                    Issue(
                        "missing_video_url",
                        heading.line_number,
                        "timestamped heading does not have the video URL in every I/B representation",
                    )
                )
        url_state = "complete" if not any(issue.code in {"missing_video_url", "conflicting_video_urls"} for issue in issues) else "mixed"
        base_url = next(
            (marker.target.base_url for _, marker in external_markers if marker.target.base_url),
            None,
        )
    else:
        url_state = "none"
        base_url = None

    return Document(
        path,
        text,
        lines,
        headings,
        issues,
        url_state,
        base_url,
        warnings,
    )


def read_document(path: Path) -> Document:
    if path.suffix.lower() != ".md":
        raise ToolError(f"input file must have a .md extension: {path}", 2)
    if not path.exists():
        raise ToolError(f"input file does not exist: {path}", 2)
    if not path.is_file():
        raise ToolError(f"input path is not a regular file: {path}", 2)
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"input is not valid UTF-8 near byte {exc.start}") from exc
    except OSError as exc:
        raise ToolError(f"cannot read {path}: {exc}") from exc
    return parse_document(path, text)


def print_doctor_errors(document: Document) -> None:
    print(f"DOCTOR status=error errors={len(document.issues)}", file=sys.stderr)
    for issue in document.issues:
        print(
            f"ERROR code={issue.code} line={issue.line} message={json_value(issue.message)}",
            file=sys.stderr,
        )


def print_document_warnings(document: Document) -> None:
    by_code: dict[str, list[Issue]] = {}
    for warning in document.warnings:
        by_code.setdefault(warning.code, []).append(warning)
    for code, warnings in by_code.items():
        first = min(warning.line for warning in warnings)
        print(
            f"WARNING code={code} count={len(warnings)} first_line={first} "
            f"message={json_value(warnings[0].message)}",
            file=sys.stderr,
        )


def command_doctor(path: Path) -> int:
    document = read_document(path)
    print_document_warnings(document)
    if document.issues:
        print_doctor_errors(document)
        return 1
    print("DOCTOR status=ok errors=0")
    return 0


def command_analyze(path: Path) -> int:
    document = read_document(path)
    print_document_warnings(document)
    if document.issues:
        print_doctor_errors(document)
        return 1
    print(LEGEND)
    print(
        f"ANALYZE status=ok formats={format_set(document.formats())} "
        f"url={document.url_state}"
    )
    return 0


@dataclass
class FinalState:
    inline: bool
    below: bool
    src: bool
    src_id: Optional[str]


def canonical_inline(seconds: int, base_url: Optional[str]) -> str:
    label = format_hms(seconds)
    if base_url:
        return f"[{label}]({timestamp_url(base_url, seconds)})"
    return f"[{label}]"


def canonical_below(seconds: int, base_url: Optional[str]) -> str:
    label = format_hms(seconds)
    target = timestamp_url(base_url, seconds) if base_url else "#"
    return f"[🎥 {label}]({target})"


def allocate_src(seconds: int, used: set[str]) -> str:
    base = f"^src-{seconds}"
    if base not in used:
        used.add(base)
        return base
    collision = 2
    while f"{base}-{collision}" in used:
        collision += 1
    result = f"{base}-{collision}"
    used.add(result)
    return result


def warn_redundant(document: Document, args: argparse.Namespace) -> None:
    timestamped = [heading for heading in document.headings if heading.timestamp_seconds is not None]
    for code, add_name, remove_name in (
        ("I", "add_inline", "remove_inline"),
        ("B", "add_below", "remove_below"),
        ("S", "add_src", "remove_src"),
    ):
        present = sum(code in heading.representations() for heading in timestamped)
        if getattr(args, add_name) and present:
            print(
                f"WARNING code=already_present representation={code} count={present}",
                file=sys.stderr,
            )
        missing = len(timestamped) - present
        if getattr(args, remove_name) and missing:
            print(
                f"WARNING code=already_absent representation={code} count={missing}",
                file=sys.stderr,
            )


def final_states(document: Document, args: argparse.Namespace) -> dict[int, FinalState]:
    states: dict[int, FinalState] = {}
    used_src = {
        heading.src_id
        for heading in document.headings
        if heading.src_id and not args.remove_src
    }
    for heading in document.headings:
        reps = heading.representations()
        inline = "I" in reps
        below = "B" in reps
        src = "S" in reps
        if args.add_inline and heading.timestamp_seconds is not None:
            inline = True
        if args.remove_inline:
            inline = False
        if args.add_below and heading.timestamp_seconds is not None:
            below = True
        if args.remove_below:
            below = False
        if args.add_src and heading.timestamp_seconds is not None:
            src = True
        if args.remove_src:
            src = False

        src_id = heading.src_id if src else None
        if src and not src_id and heading.timestamp_seconds is not None:
            src_id = allocate_src(heading.timestamp_seconds, used_src)
        states[heading.line_index] = FinalState(inline, below, src, src_id)
    return states


def confirm_data_loss(document: Document, states: dict[int, FinalState], force: bool) -> None:
    losing = []
    for heading in document.headings:
        if heading.timestamp_seconds is None:
            continue
        state = states[heading.line_index]
        if not (state.inline or state.below or state.src):
            losing.append(heading)
    if not losing or force:
        return
    print(
        f"WARNING code=timestamp_data_loss headings={len(losing)} "
        "message=\"one or more headings will lose their last timestamp representation\"",
        file=sys.stderr,
    )
    if not sys.stdin.isatty():
        raise ToolError("timestamp removal requires --force in non-interactive mode", 3)
    print("Type DELETE TIMESTAMPS to continue: ", end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().rstrip("\r\n") != "DELETE TIMESTAMPS":
        raise ToolError("timestamp removal cancelled", 3)


def render_transform(
    document: Document,
    args: argparse.Namespace,
    states: dict[int, FinalState],
    base_url: Optional[str],
    rewrite_urls: bool,
) -> tuple[str, int]:
    lines = list(document.lines)
    insert_before: dict[int, list[str]] = {}
    changed_headings = 0
    newline = document_newline(lines)

    for heading in document.headings:
        state = states[heading.line_index]
        seconds = heading.timestamp_seconds
        original_reps = heading.representations()
        final_reps = {
            code
            for code, enabled in (("I", state.inline), ("B", state.below), ("S", state.src))
            if enabled
        }
        changed = original_reps != final_reps or rewrite_urls

        body = heading.base_body
        if state.inline and seconds is not None:
            if heading.inline and not rewrite_urls:
                marker_text = heading.inline.raw
                separator = heading.inline.separator
            else:
                marker_text = canonical_inline(seconds, base_url)
                separator = heading.inline.separator if heading.inline else " "
            body += separator + marker_text
        if state.src and state.src_id:
            body += " " + state.src_id
        rendered_heading = heading.prefix + body + heading.eol
        if rendered_heading != lines[heading.line_index]:
            lines[heading.line_index] = rendered_heading
            changed = True

        if state.below and seconds is not None:
            if heading.below:
                if rewrite_urls:
                    replacement = canonical_below(seconds, base_url) + (heading.below.eol or newline)
                    if replacement != lines[heading.below.line_index]:
                        lines[heading.below.line_index] = replacement
                        changed = True
            else:
                marker = canonical_below(seconds, base_url)
                index = heading.line_index + 1
                while index < len(lines) and not split_eol(lines[index])[0].strip():
                    index += 1
                prefix = "" if index > heading.line_index + 1 else newline
                insert_before.setdefault(index, []).append(prefix + marker + newline + newline)
                changed = True
        elif heading.below:
            lines[heading.below.line_index] = ""
            changed = True

        if changed:
            changed_headings += 1

    output: list[str] = []
    for index in range(len(lines) + 1):
        output.extend(insert_before.get(index, []))
        if index < len(lines):
            output.append(lines[index])
    return "".join(output), changed_headings


def check_output_path(path: Path) -> None:
    if path.suffix.lower() != ".md":
        raise ToolError(f"output file must have a .md extension: {path}", 2)
    if not path.parent.exists() or not path.parent.is_dir():
        raise ToolError(f"output directory does not exist: {path.parent}", 2)
    if path.exists() and not path.is_file():
        raise ToolError(f"output path is not a regular file: {path}", 2)


def atomic_write(path: Path, text: str, mode_source: Path) -> None:
    try:
        mode = stat.S_IMODE((path if path.exists() else mode_source).stat().st_mode)
    except OSError:
        mode = None
    fd: Optional[int] = None
    temp_name: Optional[str] = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = None
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_name, mode)
        os.replace(temp_name, path)
        temp_name = None
    except OSError as exc:
        raise ToolError(f"cannot write {path}: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def command_transform(args: argparse.Namespace) -> int:
    document = read_document(args.filename)
    if document.issues:
        print_document_warnings(document)
        print_doctor_errors(document)
        return 1
    timestamped = [heading for heading in document.headings if heading.timestamp_seconds is not None]
    if not timestamped and (args.add_inline or args.add_below or args.add_src):
        raise ToolError("no timestamp source found; representations cannot be added")

    warn_redundant(document, args)
    states = final_states(document, args)

    if args.set_url is not None:
        without_carrier = [
            heading
            for heading in timestamped
            if not (
                states[heading.line_index].inline
                or states[heading.line_index].below
            )
        ]
        if without_carrier:
            raise ToolError(
                f"--set-url needs I or B for every timestamped heading; "
                f"{len(without_carrier)} heading(s) have only S"
            )
        _, base_url = youtube_base_url(args.set_url)
        rewrite_urls = True
    elif args.remove_url:
        if document.url_state == "none":
            print("WARNING code=url_already_absent count=1", file=sys.stderr)
        base_url = None
        rewrite_urls = document.url_state != "none"
    else:
        base_url = document.video_base_url
        rewrite_urls = False

    confirm_data_loss(document, states, args.force)
    transformed, changed = render_transform(
        document,
        args,
        states,
        base_url,
        rewrite_urls,
    )
    final_document = parse_document(document.path, transformed)
    if final_document.issues:
        print_document_warnings(final_document)
        print_doctor_errors(final_document)
        return 1
    print_document_warnings(final_document)

    if args.overwrite:
        destination = document.path
    else:
        destination = args.output
    if destination:
        check_output_path(destination)
        atomic_write(destination, transformed, document.path)
        output_kind = "overwrite" if args.overwrite else "file"
    else:
        sys.stdout.write(transformed)
        output_kind = "stdout"

    print(LEGEND, file=sys.stderr)
    print(
        f"TRANSFORM status=ok before={format_set(document.formats())} "
        f"after={format_set(final_document.formats())} changed={changed} output={output_kind}",
        file=sys.stderr,
    )
    return 0


def add_transform_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("filename", type=Path, metavar="FILE.md")
    inline = parser.add_mutually_exclusive_group()
    inline.add_argument("--add-inline", action="store_true", help="add I to timestamped headings")
    inline.add_argument("--remove-inline", action="store_true", help="remove I")
    below = parser.add_mutually_exclusive_group()
    below.add_argument("--add-below", action="store_true", help="add B below timestamped headings")
    below.add_argument("--remove-below", action="store_true", help="remove B")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--add-src", action="store_true", help="add S, with collision-safe IDs")
    src.add_argument("--remove-src", action="store_true", help="remove S")
    url = parser.add_mutually_exclusive_group()
    url.add_argument("--set-url", metavar="YOUTUBE_URL", help="set one YouTube URL everywhere")
    url.add_argument("--remove-url", action="store_true", help="replace external URLs with no-URL forms")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--overwrite",
        action="store_true",
        help="atomically overwrite the original Markdown file",
    )
    destination.add_argument("-o", "--output", type=Path, metavar="FILE.md", help="write to another file")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow removal of the last timestamp representation",
    )


def detailed_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="source_timecodes.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Validate, analyze, and convert three timestamp representations:\n"
            "  I = inline timestamp in a heading\n"
            "  B = camera timestamp below a heading\n"
            "  S = ^src-SECONDS block identifier in a heading\n\n"
            "Passing only FILE.md is shorthand for: analyze FILE.md."
        ),
        epilog=(
            "Transform options:\n"
            "  --add-inline | --remove-inline    add or remove I\n"
            "  --add-below  | --remove-below     add or remove B\n"
            "  --add-src    | --remove-src       add or remove S\n"
            "  --set-url URL | --remove-url      set or remove the video URL\n"
            "  --overwrite                       atomically replace FILE.md\n"
            "  -o, --output FILE.md              write another file\n"
            "  --force                           allow irreversible timestamp removal\n\n"
            "Examples:\n"
            "  source_timecodes.py lecture.md\n"
            "  source_timecodes.py doctor lecture.md\n"
            "  source_timecodes.py transform lecture.md --add-src\n"
            "  source_timecodes.py transform lecture.md --remove-inline --add-below\n"
            "  source_timecodes.py transform lecture.md --add-below --set-url https://youtu.be/VIDEO_ID\n"
            "  source_timecodes.py transform lecture.md --add-src --overwrite\n\n"
            "Transform writes Markdown to stdout unless --overwrite or --output is used.\n"
            "Diagnostics use stable DOCTOR, ANALYZE, TRANSFORM, WARNING, and ERROR prefixes."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="validate consistency and URLs")
    doctor.add_argument("filename", type=Path, metavar="FILE.md")
    analyze = subparsers.add_parser("analyze", help="validate, then report I/B/S formats")
    analyze.add_argument("filename", type=Path, metavar="FILE.md")
    transform = subparsers.add_parser("transform", help="add or remove representations and URLs")
    add_transform_arguments(transform)
    return parser


def print_short_help() -> None:
    print(
        "Usage: source_timecodes.py FILE.md\n"
        "       source_timecodes.py doctor FILE.md\n"
        "       source_timecodes.py analyze FILE.md\n"
        "       source_timecodes.py transform FILE.md [OPTIONS]\n\n"
        "Commands: doctor, analyze, transform. FILE.md alone runs analyze.\n"
        "For more detailed options, run: source_timecodes.py --help"
    )


def has_transform_action(args: argparse.Namespace) -> bool:
    return any(
        (
            args.add_inline,
            args.remove_inline,
            args.add_below,
            args.remove_below,
            args.add_src,
            args.remove_src,
            args.set_url is not None,
            args.remove_url,
        )
    )


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print_short_help()
        return 0
    if argv[0] not in COMMANDS and argv[0] not in ("-h", "--help"):
        argv.insert(0, "analyze")

    parser = detailed_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return command_doctor(args.filename)
        if args.command == "analyze":
            return command_analyze(args.filename)
        if not has_transform_action(args):
            raise ToolError("transform requires at least one add/remove/URL option", 2)
        return command_transform(args)
    except ToolError as exc:
        print(f"ERROR code=operation_failed message={json_value(str(exc))}", file=sys.stderr)
        return exc.exit_code
    except ValueError as exc:
        print(f"ERROR code=invalid_value message={json_value(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
