\
import re
from typing import List, Dict, Tuple, Iterable

TIME_PATTERN = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
ARROW = "-->"

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

def add_timecodes_to_headings(markdown: str, chunk_start_seconds: float) -> str:
    """
    Append [HH:MM:SS] to the end of each top-level and second-level heading line in the given markdown.
    """
    if chunk_start_seconds is None:
        return markdown
    stamp = format_hms(chunk_start_seconds)
    out_lines = []
    for line in markdown.splitlines():
        if line.startswith("# " ) or line.startswith("## "):
            # avoid duplicate if already has [HH:MM:SS]
            if re.search(r"\[\d{2}:\d{2}:\d{2}\]\s*$", line):
                out_lines.append(line)
            else:
                out_lines.append(f"{line} — [{stamp}]")
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
