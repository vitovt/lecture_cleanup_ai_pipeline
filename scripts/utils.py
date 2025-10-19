\
import re, sys
from typing import List, Dict, Tuple, Iterable, Optional

TIME_PATTERN = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
ARROW = "-->"
TIMESTAMPED_TXT_LINE = re.compile(
    r"^\s*\[(\d{2}):(\d{2}):(\d{2})(?:[\.,](\d{3}))?\]\s*(.*)$",
    re.UNICODE,
)

def parse_srt_time(s: str) -> float:
    """
    'HH:MM:SS,mmm' -> seconds (float)
    """
    m = TIME_PATTERN.fullmatch(s.strip())
    if not m:
        raise ValueError(f"Bad SRT time: {s!r}")
    hh, mm, ss, ms = map(int, m.groups())
    return hh*3600 + mm*60 + ss + ms/1000.0

def format_hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hh = seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"

def parse_srt(path: str) -> List[Dict]:
    """
    Parse simple SRT into a list of segments:
    [{"start": float, "end": float, "text": "..."}, ...]
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    segments = []
    for block in blocks:
        lines = [ln.strip("\ufeff") for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # Some SRTs start with an index line; tolerate both.
        if ARROW in lines[0]:
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) > 1 and ARROW in lines[1]:
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            # Skip malformed
            continue
        try:
            start_str, end_str = [s.strip() for s in time_line.split(ARROW)]
            start = parse_srt_time(start_str)
            end = parse_srt_time(end_str)
        except Exception:
            continue
        text = " ".join(text_lines).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments

def chunk_segments_by_time(segments: List[Dict], chunk_seconds=240, overlap_seconds=8) -> List[Dict]:
    """
    Group SRT segments into time-based chunks with overlap.
    Return: [{"start": s, "end": e, "text": "..."}]
    """
    if not segments:
        return []
    chunks = []
    current_start = segments[0]["start"]
    current_end = current_start + chunk_seconds

    i = 0
    n = len(segments)
    while i < n:
        block_segs = []
        block_start = None
        block_end = None
        # gather segs within [current_start, current_end]
        while i < n and segments[i]["start"] < current_end:
            seg = segments[i]
            block_segs.append(seg)
            block_start = seg["start"] if block_start is None else min(block_start, seg["start"])
            block_end = seg["end"] if block_end is None else max(block_end, seg["end"])
            i += 1
        if block_segs:
            text = " ".join(s["text"] for s in block_segs)
            chunks.append({"start": block_start, "end": block_end, "text": text})
        # move window forward with overlap
        current_start = current_end - overlap_seconds
        current_end = current_start + chunk_seconds
        # advance i to first seg starting after new start
        while i > 0 and segments[i-1]["start"] >= current_start:
            i -= 1
    return chunks

def chunk_text(txt: str, chunk_chars=6500, overlap_chars=500) -> List[Dict]:
    """
    Chunk plain text by characters with overlap; we approximate timing as None.
    """
    txt = txt.strip()
    if not txt:
        return []
    chunks = []
    start = 0
    n = len(txt)
    while start < n:
        end = min(n, start + chunk_chars)
        piece = txt[start:end]
        chunks.append({"start": None, "end": None, "text": piece})
        if end >= n:
            break
        start = max(0, end - overlap_chars)
    return chunks

def chunk_text_with_offsets(txt: str, chunk_chars=6500, overlap_chars=500) -> List[Dict]:
    """
    Chunk plain text by characters with overlap and include start/end offsets.
    Returns: [{"text": piece, "start_offset": start, "end_offset": end}]
    """
    if not txt:
        return []
    chunks: List[Dict] = []
    start = 0
    n = len(txt)
    while start < n:
        end = min(n, start + chunk_chars)
        piece = txt[start:end]
        chunks.append({"text": piece, "start_offset": start, "end_offset": end})
        if end >= n:
            break
        start = max(0, end - overlap_chars)
    return chunks

def parse_timestamped_txt_lines(txt: str) -> List[Dict]:
    """
    Parse TXT lines that may start with a timestamp like [HH:MM:SS,mmm].
    Returns a list of {"time": Optional[float], "text": str} per input line.
    """
    out: List[Dict] = []
    for raw in txt.splitlines():
        m = TIMESTAMPED_TXT_LINE.match(raw)
        if m:
            hh, mm, ss, ms, rest = m.groups()
            hh = int(hh); mm = int(mm); ss = int(ss); ms = int(ms or 0)
            t = hh*3600 + mm*60 + ss + ms/1000.0
            out.append({"time": t, "text": rest})
        else:
            out.append({"time": None, "text": raw})
    return out

def add_timecodes_to_headings(markdown: str, chunk_start_seconds: float, as_link: bool = False) -> str:
    """
    Append [HH:MM:SS] to the end of each top-level and second-level heading line in the given markdown.
    """
    if chunk_start_seconds is None:
        return markdown
    stamp = format_hms(chunk_start_seconds)
    link_text = f"[{stamp}]" if not as_link else f"[{stamp}](#t={stamp})"
    out_lines = []
    for line in markdown.splitlines():
        if line.startswith("# " ) or line.startswith("## "):
            # avoid duplicate if already has [HH:MM:SS]
            if re.search(r"\[\d{2}:\d{2}:\d{2}\]\s*$", line):
                out_lines.append(line)
            else:
                out_lines.append(f"{line} — {link_text}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)

def similarity_ratio(a: str, b: str) -> float:
    """
    Rough similarity (0..1). We use a whitespace-token based Jaccard-like metric for speed.
    """
    ta = set(a.split())
    tb = set(b.split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union

# -----------------------
# Line-preserving chunking
# -----------------------

SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!?…])\s+")

def _warn(msg: str) -> None:
    try:
        print(msg, file=sys.stderr)
    except Exception:
        pass

def split_line_for_limit(line: str, limit: int) -> Tuple[List[str], List[str]]:
    """
    Split a single line into quasi-lines each <= limit.
    Strategy: sentences -> words -> characters.
    Returns (pieces, notes) where notes are warning strings to log.
    """
    notes: List[str] = []
    if len(line) <= limit:
        return [line], notes

    notes.append(f"Long line split: original length {len(line)} > txt_chunk_chars {limit}")

    # 1) Sentence-based packing
    sentences = SENTENCE_SPLIT_RE.split(line)
    # If no split occurred, fallback to word-split
    if len(sentences) > 1:
        pieces: List[str] = []
        buf = ""
        for s in sentences:
            if not s:
                continue
            add_len = len(s) if not buf else (1 + len(s))  # assuming a space when gluing sentences
            if (len(buf) + add_len) <= limit:
                buf = (s if not buf else (buf + " " + s))
            else:
                if buf:
                    pieces.append(buf)
                # If a single sentence longer than limit: fallback to word split for this sentence
                if len(s) > limit:
                    ws_pieces, ws_notes = _split_by_words_with_char_fallback(s, limit)
                    notes.extend(ws_notes)
                    pieces.extend(ws_pieces)
                    buf = ""
                else:
                    buf = s
        if buf:
            pieces.append(buf)
        return pieces, notes

    # 2) Word-based packing with char fallback for ultra-long tokens
    pieces, ws_notes = _split_by_words_with_char_fallback(line, limit)
    notes.extend(ws_notes)
    return pieces, notes

def _split_by_words_with_char_fallback(text: str, limit: int) -> Tuple[List[str], List[str]]:
    notes: List[str] = []
    tokens = re.findall(r"\S+|\s+", text)
    pieces: List[str] = []
    buf = ""
    for tok in tokens:
        # measure length if we append token
        add_len = len(tok)
        if len(buf) + add_len <= limit:
            buf += tok
            continue
        # flush current buffer
        if buf:
            pieces.append(buf)
            buf = ""
        # token itself longer than limit -> char-split
        if len(tok) > limit:
            notes.append("Unusual: very long token without spaces; hard-splitting by characters to respect limit")
            start = 0
            n = len(tok)
            while start < n:
                end = min(n, start + limit)
                pieces.append(tok[start:end])
                start = end
        else:
            buf = tok
    if buf:
        pieces.append(buf)
    return pieces, notes

def _joined_len(lines: List[str]) -> int:
    if not lines:
        return 0
    return sum(len(s) for s in lines) + (len(lines) - 1)

def chunk_text_line_preserving(lines: List[str], chunk_chars: int = 6500, overlap_chars: int = 500) -> List[Dict]:
    """
    Build chunks preserving whole lines. Never split inside a line unless the line
    alone exceeds chunk_chars. Enforce strict size limits and correct
    continuation across chunks.

    Returns: list of dicts with keys:
      {"start": None, "end": None, "text": "...", "_units": [{"text": str, "orig": int, "split": bool}], "_overlap_units": int}
    Only 'text' is intended for downstream consumption; meta keys are internal.
    """
    # Normalize None
    lines = list(lines or [])
    # Early exit
    if not any(ln.strip() for ln in lines):
        return []

    chunks: List[Dict] = []
    i = 0  # index over original lines
    pending: Optional[Dict] = None  # {"pieces": [...], "cursor": int, "orig": int}
    prev_units: Optional[List[Dict]] = None

    # Bound overlap by chunk size - 1 to leave room for progress; will fall back if needed
    hard_overlap_limit = max(0, min(overlap_chars, max(0, chunk_chars - 1)))

    while True:
        # termination: no more new content AND no pending continuation
        if i >= len(lines) and (not pending):
            break

        # 1) Determine overlap from previous chunk
        def compute_overlap(units: Optional[List[Dict]], limit: int) -> List[Dict]:
            if not units or limit <= 0:
                return []
            # If the last unit is a split piece, prefer taking a tail of it that fits the limit
            last = units[-1]
            if last.get("split"):
                # Split last unit text into sub-pieces and take from the end
                sub_pieces, sub_notes = split_line_for_limit(last["text"], limit)
                # choose minimal number from end that fit
                out: List[str] = []
                total = 0
                for s in reversed(sub_pieces):
                    add = len(s) if total == 0 else (1 + len(s))
                    if total + add <= limit:
                        out.append(s)
                        total += add
                    else:
                        break
                out.reverse()
                return [{"text": t, "orig": last["orig"], "split": True} for t in out]
            # Else, add whole lines from the end backwards
            out_rev: List[Dict] = []
            total = 0
            for u in reversed(units):
                # only take whole original lines for overlap
                if u.get("split"):
                    # stop at first split piece encountered from the end
                    break
                add = len(u["text"]) if total == 0 else (1 + len(u["text"]))
                if total + add <= limit:
                    out_rev.append(u)
                    total += add
                else:
                    # If even the very last whole line doesn't fit, split it
                    if not out_rev:  # no line has fit yet
                        sub_pieces, sub_notes = split_line_for_limit(u["text"], limit)
                        # take from the end minimal pieces that fit
                        out: List[str] = []
                        sub_total = 0
                        for s in reversed(sub_pieces):
                            add2 = len(s) if sub_total == 0 else (1 + len(s))
                            if sub_total + add2 <= limit:
                                out.append(s)
                                sub_total += add2
                            else:
                                break
                        out.reverse()
                        return [{"text": t, "orig": u["orig"], "split": True} for t in out]
                    break
            out_rev.reverse()
            return out_rev

        attempt = 0
        while True:
            overlap_limit = hard_overlap_limit if attempt == 0 else 0
            overlap_units = compute_overlap(prev_units, overlap_limit)
            units: List[Dict] = list(overlap_units)
            curr_len = _joined_len([u["text"] for u in units])
            added_new = 0

            # 2) Fill with new content
            if pending:
                piece = pending["pieces"][pending["cursor"]]
                # ensure it fits; if not (overlap too big), we'll retry with no overlap
                add_len = len(piece) if curr_len == 0 else (1 + len(piece))
                if curr_len + add_len <= chunk_chars:
                    units.append({"text": piece, "orig": pending["orig"], "split": True})
                    added_new += 1
                    curr_len += add_len
                    pending["cursor"] += 1
                    if pending["cursor"] >= len(pending["pieces"]):
                        pending = None
                        i += 1  # move past the original long line
                # Regardless, only one split piece per chunk
            else:
                # add whole lines until next would overflow
                while i < len(lines):
                    line = lines[i]
                    next_len = len(line) if curr_len == 0 else (1 + len(line))
                    if curr_len + next_len <= chunk_chars:
                        units.append({"text": line, "orig": i, "split": False})
                        added_new += 1
                        curr_len += next_len
                        i += 1
                    else:
                        # current chunk already has some content -> finalize
                        if added_new > 0:
                            break
                        # The single line doesn't fit an empty chunk -> split
                        pieces, notes = split_line_for_limit(line, chunk_chars)
                        for n in notes:
                            _warn(n)
                        pending = {"pieces": pieces, "cursor": 0, "orig": i}
                        # place ONLY first piece into this chunk
                        piece0 = pieces[pending["cursor"]]
                        add_len0 = len(piece0) if curr_len == 0 else (1 + len(piece0))
                        if curr_len + add_len0 <= chunk_chars:
                            units.append({"text": piece0, "orig": i, "split": True})
                            added_new += 1
                            curr_len += add_len0
                            pending["cursor"] += 1
                            if pending["cursor"] >= len(pending["pieces"]):
                                pending = None
                                i += 1
                        # finalize regardless
                        break

            # If this attempt added no new content (overlap consumed all room), retry without overlap once
            if added_new == 0 and overlap_limit > 0:
                attempt += 1
                if attempt <= 1:
                    continue
            # finalize this chunk if it has any content at all (including overlap-only shouldn't happen after retry)
            if added_new == 0:
                # No progress and no overlap -> we're stuck; break to avoid infinite loop
                break

            chunk_text = "\n".join(u["text"] for u in units)
            chunks.append({
                "start": None,
                "end": None,
                "text": chunk_text,
                "_units": units,
                "_overlap_units": len(overlap_units),
            })
            prev_units = units
            break

    return chunks

# -----------------------
# Stitching deduplication helpers
# -----------------------

_TRAILING_TIMECODE_RE = re.compile(
    r"\s+—\s+\[(\d{2}:\d{2}:\d{2})\](?:\(#t=\1\))?\s*$"
)

def _normalize_for_match(s: str) -> str:
    """Normalize a line for boundary matching.
    - trim
    - collapse spaces
    - normalize quotes/dashes
    - strip trailing timecode markers like:  — [HH:MM:SS] or  — [HH:MM:SS](#t=HH:MM:SS)
    """
    if not s:
        return ""
    # unify unicode quotes and dashes
    s2 = s.replace("“", '"').replace("”", '"').replace("„", '"').replace("«", '"').replace("»", '"')
    s2 = s2.replace("–", "-").replace("—", "-").replace("−", "-")
    s2 = _TRAILING_TIMECODE_RE.sub("", s2)
    # collapse whitespace
    s2 = re.sub(r"\s+", " ", s2.strip())
    return s2

def _window_lines_from_end(text: str, max_chars: int) -> List[str]:
    lines = text.splitlines()
    out: List[str] = []
    total = 0
    for ln in reversed(lines):
        add = len(ln) + (1 if total > 0 else 0)
        if total + add > max_chars and out:
            break
        out.append(ln)
        total += add
        if total >= max_chars:
            break
    return list(reversed(out))

def _window_lines_from_start(text: str, max_chars: int) -> List[str]:
    lines = text.splitlines()
    out: List[str] = []
    total = 0
    for ln in lines:
        add = len(ln) + (1 if total > 0 else 0)
        if total + add > max_chars and out:
            break
        out.append(ln)
        total += add
        if total >= max_chars:
            break
    return out

def _longest_common_prefix_len(a: List[str], b: List[str]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n

def _dedup_try_lines(prev_text: str, cur_text: str, window_chars: int) -> Tuple[int, str]:
    """Return (matched_count, mode) using line-based comparison.
    mode is 'lines' when used.
    """
    prev_win = _window_lines_from_end(prev_text, window_chars)
    cur_win = _window_lines_from_start(cur_text, window_chars)
    # normalize for comparison
    prev_norm = [_normalize_for_match(s) for s in prev_win]
    cur_norm = [_normalize_for_match(s) for s in cur_win]
    # find the longest k where last k of prev == first k of cur
    max_k = min(len(prev_norm), len(cur_norm))
    best = 0
    for k in range(max_k, 0, -1):
        if prev_norm[-k:] == cur_norm[:k]:
            best = k
            break
    return best, 'lines'

SENTENCE_RE = re.compile(r"(?<=[\.!?…])\s+")

def _dedup_try_sentences(prev_text: str, cur_text: str, window_chars: int) -> Tuple[int, str]:
    prev = "\n".join(_window_lines_from_end(prev_text, window_chars))
    cur = "\n".join(_window_lines_from_start(cur_text, window_chars))
    prev_sent = [s for s in SENTENCE_RE.split(prev) if s]
    cur_sent = [s for s in SENTENCE_RE.split(cur) if s]
    prev_norm = [_normalize_for_match(s) for s in prev_sent]
    cur_norm = [_normalize_for_match(s) for s in cur_sent]
    max_k = min(len(prev_norm), len(cur_norm))
    best = 0
    for k in range(max_k, 0, -1):
        if prev_norm[-k:] == cur_norm[:k]:
            best = k
            break
    return best, 'sentences'

def dedup_overlapping_boundary(prev_text: str, cur_text: str, window_chars: int) -> Tuple[str, int, str]:
    """
    Compute and remove duplicated prefix in cur_text that overlaps with suffix in prev_text within a window.
    Comparison is by lines first, then by sentences if line matching yields 0.
    Returns: (new_cur_text, removed_count, mode)
    - removed_count is the number of matched lines (or sentences) removed from the start of cur_text.
    """
    if not prev_text or not cur_text or window_chars <= 0:
        return cur_text, 0, 'none'
    # Try line-based first
    match_count, mode = _dedup_try_lines(prev_text, cur_text, window_chars)
    if match_count > 0:
        lines = cur_text.splitlines()
        new_text = "\n".join(lines[match_count:])
        return new_text, match_count, mode
    # Optional sentence-based fallback is disabled to avoid damaging Markdown structure.
    # If needed in the future, implement a structure-preserving removal.
    return cur_text, 0, 'none'

# -----------------------
# Edit comment stripping
# -----------------------

_EDIT_COMMENT_TAGS = (
    "fixed",
    "filler_removed",
    "merged_terms",
    "rephrased",
    "unsure",
    "generalized",
    "generalised",
    "genearalised",
    "structure_changed",
    "typos_fixed",
)

_EDIT_COMMENT_RE = re.compile(
    r"<!--\s*(?:" + "|".join(_EDIT_COMMENT_TAGS) + r")\s*:\s*(?:.|\n)*?-->", re.IGNORECASE
)

def strip_edit_comments(markdown: str) -> str:
    """Remove known end-of-block HTML edit comments like <!-- fixed: ... --> from Markdown.
    Conservative: removes only recognized tags to avoid deleting other HTML comments.
    """
    if not markdown:
        return markdown
    out = _EDIT_COMMENT_RE.sub("", markdown)
    # collapse multiple consecutive blank lines created by removals
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out
