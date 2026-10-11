"""Validate downloaded SRT timing and optionally apply a user offset."""
import argparse
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

STAMP = r"\d{2,}:\d{2}:\d{2},\d{3}"
INTERVAL = re.compile(rf"^({STAMP}) --> ({STAMP})(.*)$", re.MULTILINE)


def seconds(value):
    hours, minutes, secs = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def offset_value(value):
    if not re.fullmatch(r"[+-]?\d+:\d{2}:\d{2}(?:\.\d{1,3})?", value):
        raise argparse.ArgumentTypeError("use signed HH:MM:SS, e.g. -00:15:33")
    unsigned = value.lstrip("+-")
    _, minutes, secs = unsigned.split(":")
    if int(minutes) >= 60 or float(secs) >= 60:
        raise argparse.ArgumentTypeError("minutes and seconds must be below 60")
    return (-1 if value.startswith("-") else 1) * seconds(unsigned)


def timestamp(value, milliseconds=False):
    ticks = max(0, round(value * 1000))
    hours, ticks = divmod(ticks, 3600000)
    minutes, ticks = divmod(ticks, 60000)
    secs, millis = divmod(ticks, 1000)
    result = f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{result},{millis:03}" if milliseconds else result


def process(path, duration, offset=None):
    text = path.read_text(encoding="utf-8-sig")
    intervals = list(INTERVAL.finditer(text))
    if not intervals:
        raise ValueError("downloaded subtitles contain no SRT timestamps")
    end = max(seconds(match[2]) for match in intervals)
    # Allow a final caption to linger briefly after the last video frame.
    if end > duration + 2:
        level = "ERROR" if offset is None else "WARNING"
        estimate = math.ceil(end - duration)
        print(f"{level}: Subtitle timing may not match video: captions end at "
              f"{timestamp(end)}; video ends at {timestamp(duration)}; "
              f"calculated offset is approximately -{timestamp(estimate)}.", file=sys.stderr)
        if offset is None:
            raise ValueError("Potential subtitle timing shift detected; further processing stopped "
                             "to prevent inaccuracies. Verify and retry with "
                             f"--time-offset -{timestamp(estimate)} (estimate only).")
    if offset is None:
        print(f"INFO: Subtitle timing bounds check passed: captions end at "
              f"{timestamp(end, True)}; video ends at {timestamp(duration, True)} "
              "(2s tolerance; audio synchronization not checked).")
        return
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    shifted = []
    for block in blocks:
        match = INTERVAL.search(block)
        if not match:
            raise ValueError("invalid SRT cue")
        start, stop = seconds(match[1]) + offset, seconds(match[2]) + offset
        if stop <= 0 or start >= duration:
            continue
        start, stop = max(0, start), min(duration, stop)
        if stop <= start:
            continue
        payload = block[match.end():].lstrip("\r\n")
        shifted.append(f"{len(shifted) + 1}\n{timestamp(start, True)} --> "
                       f"{timestamp(stop, True)}{match[3]}\n{payload}")
    if not shifted:
        raise ValueError("user time offset leaves no captions within the video")
    descriptor, name = tempfile.mkstemp(prefix=".subtitle-timing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("\n\n".join(shifted) + "\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(f"INFO: Applied user time offset: {offset:+.3f}s.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("srt", type=Path)
    parser.add_argument("url")
    parser.add_argument("--time-offset", type=offset_value)
    args = parser.parse_args()
    try:
        result = subprocess.run(["yt-dlp", "--quiet", "--no-warnings", "--skip-download",
                                 "--print", "%(duration)s", "--extractor-args",
                                 "youtube:player_client=default", args.url],
                                capture_output=True, text=True, timeout=120, check=True)
        duration = float(result.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("video duration is unavailable or invalid")
        process(args.srt, duration, args.time_offset)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: Subtitle timing check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
