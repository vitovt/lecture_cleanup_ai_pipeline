"""Inventory and extract source from Markdown without rewriting its contents."""

from __future__ import annotations

import json
import re
import bisect
from dataclasses import dataclass, field
from pathlib import Path

from scripts.source_timecode_core import HEADING_RE, fenced_block_ranges, protected_line_mask
from scripts.utils import _EDIT_COMMENT_TAGS


MARKER_RE = re.compile(r"^[ \t]*<!--\s+LECTURE_CLEANUP_(LONG|SHORT)_SUMMARY_(START|END)(?:\s*\|.*)?\s*-->[ \t]*$")
META_RE = re.compile(r"^[ \t]*<!--\s+LECTURE_CLEANUP_SUMMARY_META\s+(.*?)\s*-->[ \t]*$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SERVICE_RE = re.compile(
    r"<!--\s*(?:" + "|".join((*_EDIT_COMMENT_TAGS, "unsures", "llm_provider", "model", "content_mode", "txt_overlap_chars", "processsing_time", "processing_time")) + r")\s*:",
    re.IGNORECASE,
)


class SummaryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class SummaryBlock:
    path: Path
    kind: str
    start: int
    end: int
    metadata: dict = field(default_factory=dict)

    @property
    def identifier(self):
        return self.metadata.get("id") or f"{self.path.name}:{self.kind}@{self.start + 1}"

    @property
    def language(self):
        return self.metadata.get("lang")


@dataclass
class SourceDocument:
    path: Path
    original: str
    blocks: list[SummaryBlock]
    source: str
    line_map: list[int]
    omitted: list[tuple[int, int, str]]
    legacy_start: int | None
    comments_removed: int


def read_markdown(path: Path) -> str:
    if path.suffix.lower() != ".md" or not path.is_file():
        raise SummaryError("invalid_input", f"Expected an existing Markdown file: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def inventory(path: Path, text: str) -> list[SummaryBlock]:
    lines = text.splitlines(keepends=True)
    fenced = protected_line_mask(lines, protect_summaries=False)
    blocks = []
    current = None
    identifiers = set()
    for index, line in enumerate(lines):
        if fenced[index]:
            continue
        body = line.rstrip("\r\n").lstrip("\ufeff")
        marker = MARKER_RE.fullmatch(body)
        if marker:
            kind, boundary = marker.groups()
            kind = kind.lower()
            if boundary == "START":
                if current is not None:
                    raise SummaryError("invalid_summary_markers", f"Nested summary at {path}:{index + 1}")
                current = SummaryBlock(path, kind, index, -1)
            else:
                if current is None or current.kind != kind:
                    raise SummaryError("invalid_summary_markers", f"Unmatched summary END at {path}:{index + 1}")
                current.end = index + 1
                blocks.append(current)
                current = None
            continue
        meta = META_RE.fullmatch(body)
        if meta:
            if current is None or current.metadata:
                raise SummaryError("invalid_summary_metadata", f"Unexpected metadata at {path}:{index + 1}")
            try:
                data = json.loads(meta.group(1))
            except ValueError as exc:
                raise SummaryError("invalid_summary_metadata", f"Invalid metadata at {path}:{index + 1}: {exc}") from exc
            if not isinstance(data, dict):
                raise SummaryError("invalid_summary_metadata", "Summary metadata must be a JSON object")
            identifier = data.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in identifiers:
                raise SummaryError("invalid_summary_metadata", f"Missing or duplicate summary ID at {path}:{index + 1}")
            if data.get("lang") is not None and (not isinstance(data["lang"], str) or not re.fullmatch(r"[a-z]{2}", data["lang"])):
                raise SummaryError("invalid_summary_metadata", f"Invalid summary language at {path}:{index + 1}")
            identifiers.add(identifier)
            current.metadata = data
        elif "<!-- LECTURE_CLEANUP_" in body and "SUMMARY_" in body:
            raise SummaryError("invalid_summary_markers", f"Malformed summary marker at {path}:{index + 1}")
    if current is not None:
        raise SummaryError("invalid_summary_markers", f"Unclosed summary at {path}:{current.start + 1}")
    return blocks


def heading_text(lines, index):
    match = HEADING_RE.match(lines[index])
    if match:
        return match.group("body")
    if index + 1 < len(lines) and lines[index].strip() and re.fullmatch(r"[ \t]{0,3}(?:=+|-+)[ \t]*\r?\n?", lines[index + 1]):
        return lines[index].strip()
    return None


def prepare_source(path: Path, text: str, policy) -> SourceDocument:
    blocks = inventory(path, text)
    lines = text.splitlines(keepends=True)
    omitted = [(block.start, block.end, f"{block.kind} summary") for block in blocks]
    excluded = {index for start, end, _ in omitted for index in range(start, end)}
    fenced = protected_line_mask(lines, protect_summaries=False)
    frontmatter_end = 0
    if lines and lines[0].lstrip("\ufeff").strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() in ("---", "..."):
                frontmatter_end = index + 1
                omitted.append((0, frontmatter_end, "frontmatter (not used for language)"))
                excluded.update(range(frontmatter_end))
                break
        else:
            raise SummaryError("invalid_frontmatter", "Unclosed frontmatter")
    legacy_start = None
    # Remove comment text for heading detection, keeping line positions intact.
    # A real heading with an inline comment still counts as a legacy heading.
    detection_lines = COMMENT_RE.sub(
        lambda match: "".join(re.findall(r"\r\n|\n|\r", match.group())), text,
    ).splitlines(keepends=True)
    patterns = [re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", 0 if policy.legacy_case_sensitive else re.IGNORECASE) for word in policy.legacy_words]
    if policy.legacy_enabled:
        for index in range(frontmatter_end, len(lines)):
            if index in excluded or fenced[index] or index >= len(detection_lines):
                continue
            title = heading_text(detection_lines, index)
            if title and any(pattern.search(title) for pattern in patterns):
                legacy_start = index
                omitted.append((index, len(lines), "legacy summary tail"))
                excluded.update(range(index, len(lines)))
                break
    selected = [index for index in range(len(lines)) if index not in excluded]
    source = "".join(lines[index] for index in selected)
    source_lines = source.splitlines(keepends=True)
    # Only diagnostic-only fences are removed. Meaningful code remains source.
    diagnostic_comments = 0
    for start, index in fenced_block_ranges(source_lines):
        fence_body = "".join(source_lines[start + 1:max(start + 1, index - 1)])
        comments = list(COMMENT_RE.finditer(fence_body))
        if policy.comments != "keep" and comments and not COMMENT_RE.sub("", fence_body).strip() and all(policy.comments == "all" or SERVICE_RE.match(match.group()) for match in comments):
            diagnostic_comments += len(comments)
            omitted.append((selected[start], selected[index - 1] + 1, "diagnostic-only code block"))
            for line_index in range(start, index):
                source_lines[line_index] = "".join(re.findall(r"\r\n|\n|\r", source_lines[line_index]))
    source = "".join(source_lines)
    code_mask = protected_line_mask(source.splitlines(keepends=True), protect_summaries=False)
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    removed = diagnostic_comments
    def remove(match):
        nonlocal removed
        # Keep comment literals in code; remove actual service comments only.
        line_index = bisect.bisect_right(offsets, match.start()) - 1
        if policy.comments == "keep" or (line_index < len(code_mask) and code_mask[line_index]):
            return match.group()
        if policy.comments == "service" and not SERVICE_RE.match(match.group()):
            return match.group()
        removed += 1
        end_index = bisect.bisect_right(offsets, match.end() - 1) - 1
        omitted.append((selected[line_index], selected[end_index] + 1, "service comment" if policy.comments == "service" else "HTML comment"))
        return "".join(re.findall(r"\r\n|\n|\r", match.group()))
    source = COMMENT_RE.sub(remove, source)
    if len(source.splitlines(keepends=True)) != len(selected):
        # A removed comment on a final unterminated line still needs its map.
        while len(selected) > len(source.splitlines(keepends=True)):
            selected.pop()
    return SourceDocument(path, text, blocks, source, selected, omitted, legacy_start, removed)
