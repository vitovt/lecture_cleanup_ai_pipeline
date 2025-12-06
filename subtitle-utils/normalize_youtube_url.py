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
from urllib.parse import parse_qs, urlparse


def _clean_video_id(value: str) -> str:
    """Remove trailing delimiters from a candidate video id."""
    value = value.split("?")[0]
    value = value.split("&")[0]
    value = value.split("#")[0]
    value = value.strip()
    return value


def extract_video_id(raw_url: str) -> str | None:
    """Pull the video id from many possible YouTube URL shapes."""
    raw_url = raw_url.strip()
    if not raw_url:
        return None

    # Allow passing a bare video id (no slashes, no scheme)
    if "://" not in raw_url and "/" not in raw_url:
        return _clean_video_id(raw_url)

    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query)
    parts = [p for p in path.split("/") if p]

    video_id = None

    if host.endswith("youtu.be"):
        if parts:
            video_id = parts[0]
    elif "youtube" in host:
        if "v" in query:
            video_id = query["v"][0]
        elif len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = parts[1]

    if not video_id:
        return None

    return _clean_video_id(video_id)


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
