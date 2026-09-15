#!/usr/bin/env python3
"""
Normalize YouTube URLs to a clean canonical form.

Accepts any common YouTube URL (watch, shorts, embed, live, youtu.be) or a raw
video id and returns either the short youtu.be link, long watch link, or just
the id. Extra parameters (list/t/si/feature/etc.) are dropped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.source_timecode_core import extract_youtube_video_id


def extract_video_id(raw_url: str) -> str | None:
    """Pull the video id from many possible YouTube URL shapes."""
    return extract_youtube_video_id(
        raw_url,
        allow_bare=True,
        allow_missing_scheme=True,
    )


def normalize_youtube_url(raw_url: str, output_format: str = "short") -> str | None:
    """Return a normalized YouTube URL or id based on the desired format."""
    video_id = extract_video_id(raw_url)
    if not video_id:
        return None

    if output_format == "id":
        return video_id
    if output_format == "long":
        return f"https://www.youtube.com/watch?v={video_id}"
    return f"https://youtu.be/{video_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a YouTube URL.")
    parser.add_argument(
        "url",
        help="YouTube URL or raw video id",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="output_format",
        choices=["short", "long", "id"],
        default="short",
        help="Output format: short=youtu.be (default), long=watch link, id=raw id",
    )
    args = parser.parse_args()

    normalized = normalize_youtube_url(args.url, output_format=args.output_format)
    if not normalized:
        return 1

    print(normalized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
