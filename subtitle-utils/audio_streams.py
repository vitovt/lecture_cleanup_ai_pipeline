#!/usr/bin/env python3
"""Shared, read-only audio-stream inspection for workflows and source planning."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def inspect_audio(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"media file not found: {path}")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_streams",
        "-show_format", "-of", "json", str(path),
    ], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"cannot inspect {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"no audio streams in {path}")
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"no valid duration in {path}")
    return {"file": str(path), "duration": duration, "streams": streams}


def require_single_audio(path: Path) -> dict:
    info = inspect_audio(path)
    count = len(info["streams"])
    if count != 1:
        raise ValueError(
            f"{path} contains {count} audio streams. Use StartMe.sh multitrack "
            "with --source ID --track N --name NAME to select each source; "
            "a separate --file source must contain exactly one audio stream."
        )
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", action="store_true", help="Require exactly one audio stream")
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        info = require_single_audio(args.file) if args.single else inspect_audio(args.file)
        if not args.single:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
