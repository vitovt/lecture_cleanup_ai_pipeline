\
import re, sys, json
from typing import List, Dict, Tuple, Optional, Set

TIMESTAMPED_TXT_LINE = re.compile(
    r"^\s*\[(\d{2}):(\d{2}):(\d{2})(?:[\.,](\d{3}))?\]\s*(.*)$",
    re.UNICODE,
)

def format_hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hh = seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def parse_timestamped_txt_lines(txt: str, keep_raw: bool = False) -> List[Dict]:
    """
    Parse TXT lines that may start with a timestamp like [HH:MM:SS,mmm].
    Returns a list of {"time": Optional[float], "text": str, "raw": Optional[str]} per input line.
    When keep_raw=True, the original line (without trailing newline) is returned in "raw".
    """
    out: List[Dict] = []
    for raw in txt.splitlines():
        m = TIMESTAMPED_TXT_LINE.match(raw)
        if m:
            hh, mm, ss, ms, rest = m.groups()
            hh = int(hh); mm = int(mm); ss = int(ss); ms = int(ms or 0)
            t = hh*3600 + mm*60 + ss + ms/1000.0
            item = {"time": t, "text": rest}
        else:
            item = {"time": None, "text": raw}
        if keep_raw:
            item["raw"] = raw
        out.append(item)
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

def dedup_overlapping_boundary(prev_text: str, cur_text: str, window_chars: int) -> Tuple[str, int, str]:
    """
    Compute and remove duplicated prefix in cur_text that overlaps with suffix in prev_text within a window.
    Comparison uses line-based matching within a window.
    Returns: (new_cur_text, removed_count, mode)
    - removed_count is the number of matched lines removed from the start of cur_text.
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

# -----------------------
# Merged-terms memory utils
# -----------------------

_MERGED_TERMS_COMMENT_RE = re.compile(r"<!--\s*merged_terms\s*:\s*(.*?)-->", re.IGNORECASE | re.DOTALL)

def _normalize_text_token(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip('"\'')

def _parse_json_mterm_payload(payload: str) -> Dict[str, Set[str]]:
    """Attempt to parse payload as JSON in multiple shapes.
    Supported shapes:
      - [{"canonical": "Term", "variants": ["v1","v2"], ...}, ...]
      - {"Term": ["v1","v2"], "evidence": [...], "confidence": "high"}
    Returns mapping canonical -> set(variants).
    """
    out: Dict[str, Set[str]] = {}
    try:
        data = json.loads(payload)
    except Exception:
        return out
    # Array of objects
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            # common fields
            canon = item.get("canonical") or item.get("term") or None
            variants = item.get("variants") or []
            if isinstance(canon, str) and isinstance(variants, list):
                c = _normalize_text_token(canon)
                vs = {_normalize_text_token(v) for v in variants if isinstance(v, str) and _normalize_text_token(v)}
                if c and vs:
                    out.setdefault(c, set()).update(vs)
    # Dict mapping
    elif isinstance(data, dict):
        for k, v in data.items():
            if k in ("evidence", "confidence"):
                continue
            if not isinstance(k, str) or not isinstance(v, list):
                continue
            c = _normalize_text_token(k)
            vs = {_normalize_text_token(x) for x in v if isinstance(x, str) and _normalize_text_token(x)}
            if c and vs:
                out.setdefault(c, set()).update(vs)
    return out

def _parse_pairs_mterm_payload(payload: str) -> Dict[str, Set[str]]:
    """Parse semi-structured pairs: "v1, v2" -> "Canonical"; ...
    Returns mapping canonical -> set(variants).
    """
    out: Dict[str, Set[str]] = {}
    # split by semicolons or newlines
    parts = [p for p in re.split(r"[;\n]", payload) if p.strip()]
    for p in parts:
        if "->" not in p:
            continue
        lhs, rhs = p.split("->", 1)
        canon = _normalize_text_token(rhs)
        lhs = lhs.strip()
        # extract within quotes if present, else split by comma
        m = re.findall(r"\"([^\"]+)\"|'([^']+)'", lhs)
        variants: List[str] = []
        if m:
            # m is list of tuples; take whichever group matched
            for a, b in m:
                s = (a or b)
                # a single quoted group may contain comma-separated variants
                for part in s.split(','):
                    part = part.strip()
                    if part:
                        variants.append(part)
        else:
            variants = [t.strip() for t in lhs.split(',') if t.strip()]
        vs = {_normalize_text_token(v) for v in variants if _normalize_text_token(v)}
        if canon and vs:
            out.setdefault(canon, set()).update(vs)
    return out

def extract_merged_terms_map(markdown: str) -> Dict[str, Set[str]]:
    """Extract mapping of canonical term -> set(variants) from all merged_terms comments.
    Attempts JSON first, then pair-format parsing.
    """
    if not markdown:
        return {}
    out: Dict[str, Set[str]] = {}
    for m in _MERGED_TERMS_COMMENT_RE.finditer(markdown):
        payload = (m.group(1) or "").strip()
        # try JSON
        jmap = _parse_json_mterm_payload(payload)
        if jmap:
            for k, vs in jmap.items():
                out.setdefault(k, set()).update(vs)
            continue
        # try pairs
        pmap = _parse_pairs_mterm_payload(payload)
        for k, vs in pmap.items():
            out.setdefault(k, set()).update(vs)
    return out

def merge_term_maps(into: Dict[str, Set[str]], inc: Dict[str, Set[str]]) -> None:
    for k, vs in (inc or {}).items():
        into.setdefault(k, set()).update(vs)

def diff_term_maps(cur: Dict[str, Set[str]], prev: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    """Return only the variants that are new compared to prev.
    Output values are sorted lists for stable display.
    """
    diff: Dict[str, List[str]] = {}
    for k, vs in (cur or {}).items():
        old = prev.get(k, set()) if prev else set()
        new = sorted([v for v in vs if v not in old])
        if new:
            diff[k] = new
    return diff

def serialize_term_hints_json(known: Dict[str, Set[str]]) -> str:
    """Build a compact JSON string for TERM_HINTS block: {"Canonical": ["v1","v2"], ...}.
    Returns empty string if no known terms.
    """
    if not known:
        return ""
    payload = {k: sorted(list(vs)) for k, vs in sorted(known.items(), key=lambda kv: kv[0].lower()) if vs}
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        # extremely unlikely; fallback to a naive text form
        lines = []
        for k, vs in payload.items():
            lines.append(f"{k}: {', '.join(vs)}")
        return "\n".join(lines)

def _format_pairs_comment(payload_map: Dict[str, List[str]]) -> str:
    parts = []
    for canon, vs in sorted(payload_map.items(), key=lambda kv: kv[0].lower()):
        if not vs:
            continue
        lhs = ", ".join(vs)
        parts.append(f'"{lhs}" -> "{canon}"')
    return "; ".join(parts)

def _format_json_comment(payload_map: Dict[str, List[str]]) -> str:
    arr = []
    for canon, vs in sorted(payload_map.items(), key=lambda kv: kv[0].lower()):
        if not vs:
            continue
        arr.append({"canonical": canon, "variants": vs})
    try:
        return json.dumps(arr, ensure_ascii=False)
    except Exception:
        # unlikely; fallback to pairs
        return _format_pairs_comment(payload_map)

def rewrite_merged_terms_comments(markdown: str, keep_map: Dict[str, List[str]], prefer_style: str = "auto") -> str:
    """Rewrite all <!-- merged_terms: ... --> comments to only contain items in keep_map.
    If keep_map is empty, remove the comments entirely.
    prefer_style: 'json' | 'pairs' | 'auto'
    """
    if not markdown:
        return markdown
    def repl(m: re.Match) -> str:
        if not keep_map:
            return ""  # remove comment
        # choose style
        payload = (m.group(1) or "").strip()
        style = prefer_style
        if style == "auto":
            style = "json" if (payload.startswith("[") or payload.startswith("{")) else "pairs"
        if style == "json":
            inner = _format_json_comment(keep_map)
        else:
            inner = _format_pairs_comment(keep_map)
        return f"<!-- merged_terms: {inner} -->"
    return _MERGED_TERMS_COMMENT_RE.sub(repl, markdown)

# -----------------------
# Coalescing and aliasing of term maps
# -----------------------

def coalesce_term_map(term_map: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """Collapse a mapping where canonicals may also appear as variants of other canonicals.
    Mutates a shallow copy of input and returns it.
    """
    if not term_map:
        return {}
    m: Dict[str, Set[str]] = {k: set(vs) for k, vs in term_map.items()}
    changed = True
    # Iteratively merge clusters where a canonical appears in another's variants or vice versa
    while changed:
        changed = False
        keys = list(m.keys())
        for k in keys:
            if k not in m:
                continue
            vs = m[k]
            # Case A: k is variant of j
            for j in list(m.keys()):
                if j == k or j not in m:
                    continue
                if k in m[j]:
                    # merge k into j
                    m[j].update(vs)
                    m[j].add(k)
                    del m[k]
                    changed = True
                    break
            if changed:
                break
            # Case B: some variant v is a canonical key
            for v in list(vs):
                if v in m and v != k:
                    # merge v into k
                    m[k].update(m[v])
                    m[k].add(v)
                    del m[v]
                    changed = True
                    break
            if changed:
                break
    return m

def build_alias_index(term_map: Dict[str, Set[str]]) -> Dict[str, str]:
    """Return alias->canonical map for quick lookup (includes canonical names themselves)."""
    alias: Dict[str, str] = {}
    for c, vs in term_map.items():
        alias.setdefault(c, c)
        for v in vs:
            alias[v] = c
    return alias

def remap_keys_to_canonical(only_new: Dict[str, List[str]], alias_index: Dict[str, str]) -> Dict[str, List[str]]:
    """Re-key a per-chunk map to canonical keys using alias_index.
    Keeps list values as-is.
    """
    out: Dict[str, List[str]] = {}
    for k, vs in (only_new or {}).items():
        root = alias_index.get(k, k)
        out.setdefault(root, [])
        out[root].extend(vs)
    # deduplicate and sort
    for k in list(out.keys()):
        uniq = sorted(set(out[k]))
        out[k] = uniq
    return out

# -----------------------
# Overlap building (tail selection)
# -----------------------

_HTML_COMMENT_RE = re.compile(r"<!--(?:.|\n)*?-->")

def strip_all_html_comments(s: str) -> str:
    if not s:
        return s
    return _HTML_COMMENT_RE.sub("", s)

def _tail_fit_by_sentences(line: str, limit: int, sentence_delimiters: str) -> str:
    if limit <= 0 or not line:
        return ""
    # Split into sentences using delimiter chars; keep simple heuristic
    # We split on whitespace after a delimiter char
    delims = re.escape(sentence_delimiters or ".!?…")
    parts = re.split(rf"(?<=[{delims}])\s+", line)
    if len(parts) <= 1:
        return ""  # no clear sentence boundary
    out: List[str] = []
    total = 0
    for s in reversed(parts):
        if not s:
            continue
        add = len(s) if total == 0 else (1 + len(s))
        if total + add <= limit:
            out.append(s)
            total += add
        else:
            break
    out.reverse()
    return " ".join(out)

def _tail_fit_by_words(text: str, limit: int) -> str:
    if limit <= 0 or not text:
        return ""
    tokens = re.findall(r"\S+|\s+", text)
    out: List[str] = []
    total = 0
    for tok in reversed(tokens):
        if not tok:
            continue
        add = len(tok)
        if total + add <= limit:
            out.append(tok)
            total += add
        else:
            if not out and add > limit:
                # take suffix of a too-long token to fit the budget
                out.append(tok[-limit:])
                total = limit
            break
    out.reverse()
    return "".join(out).strip()

def build_context_overlap(prev_raw_text: str,
                          prev_cleaned_text: Optional[str],
                          source: str,
                          max_chars: int,
                          sentence_delimiters: str = ".!?…") -> str:
    """
    Select a tail overlap (<= max_chars) from previous fragment.
    - source: 'raw' | 'cleaned' | 'none'
    - prev_cleaned_text: if None/empty and source='cleaned', caller should fallback to raw.
    - Algorithm: lines -> sentences -> words (from end), keeping natural order.
    """
    if max_chars is None or max_chars <= 0 or source == "none":
        return ""
    src_text = (prev_raw_text or "")
    if source == "cleaned" and (prev_cleaned_text or "").strip():
        # remove any HTML comments (including edit comments)
        src_text = strip_all_html_comments(prev_cleaned_text or "")
    elif source == "cleaned":
        # cleaned missing -> caller should have warned and fallen back; still be safe
        src_text = prev_raw_text or ""
    # Work with the tail
    if not src_text:
        return ""
    # Step 1: whole lines from the end
    lines = src_text.splitlines()
    acc_lines_rev: List[str] = []
    total = 0
    for ln in reversed(lines):
        add = len(ln) if total == 0 else (1 + len(ln))  # account for newline when joining
        if total + add <= max_chars:
            acc_lines_rev.append(ln)
            total += add
        else:
            # Need a partial of this last line via sentences, then words
            remain = max_chars - total
            # Tail sentences
            part = _tail_fit_by_sentences(ln, remain, sentence_delimiters)
            if not part:
                # fallback to words
                part = _tail_fit_by_words(ln, remain)
            if part:
                acc_lines_rev.append(part)
            break
    acc_lines = list(reversed(acc_lines_rev))
    out = "\n".join(acc_lines).strip()
    # Ensure not exceeding max_chars; trim hard if extreme edge-case
    if len(out) > max_chars:
        out = out[-max_chars:]
    return out
