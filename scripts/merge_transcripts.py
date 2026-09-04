#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multitrack.formats import (  # noqa: E402
    EventFormatError,
    read_event_document,
)
from multitrack.manifest import ManifestError, load_manifest  # noqa: E402
from multitrack.merging import documents_from_manifest, merge_to_outputs  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge provider-neutral track event files on one session timeline."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--manifest",
        type=Path,
        help="Resolved manifest containing tracks[].events_file.",
    )
    source.add_argument(
        "--file",
        type=Path,
        action="append",
        help="Event JSON file; repeat for each track.",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        required=True,
        help="Output path without .events.json, .txt, or .srt suffix.",
    )
    parser.add_argument(
        "--format",
        action="append",
        choices=("events", "txt", "srt"),
        dest="formats",
        help="Output format; repeat as needed (default: txt).",
    )
    return parser


def merge_from_files(event_files: list[Path], output_base: Path, formats: list[str]):
    documents = [read_event_document(path) for path in event_files]
    return merge_to_outputs(documents, output_base, formats)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.manifest:
            manifest = load_manifest(args.manifest)
            documents = documents_from_manifest(manifest)
        else:
            documents = [read_event_document(path) for path in args.file or []]
        outputs = merge_to_outputs(
            documents,
            args.output_base,
            args.formats or ["txt"],
        )
    except (EventFormatError, ManifestError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for output in outputs.values():
        print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
