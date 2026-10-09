"""Time parsing and source-local extraction on the shared session timeline."""
from __future__ import annotations

import math
import re


def parse_time(value: str) -> float:
    """Accept nonnegative seconds or HH:MM:SS[.mmm], without rounding the window."""
    if re.fullmatch(r'\d+(?:\.\d{1,3})?', value):
        seconds = float(value)
    else:
        match = re.fullmatch(r'(\d+):([0-5]\d):([0-5]\d(?:\.\d{1,3})?)', value)
        if not match:
            raise ValueError('time must be nonnegative seconds or HH:MM:SS[.mmm]')
        seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
    if not math.isfinite(seconds):
        raise ValueError('time must be finite')
    return seconds


def source_window(duration: float, offset_ms: float, start: float, end: float | None) -> dict:
    """Intersect a session window with this source; retain the absolute merge origin."""
    offset = offset_ms / 1000
    local_start = max(0.0, start - offset)
    local_end = min(duration, end - offset) if end is not None else duration
    if local_end <= local_start:
        raise ValueError('source does not overlap the requested interval; omit it or change the interval/offset')
    return {
        'extract_start': local_start,
        'duration': local_end - local_start,
        'merge_offset_ms': (local_start + offset) * 1000,
    }
