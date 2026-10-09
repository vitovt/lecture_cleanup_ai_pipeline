#!/usr/bin/env python3
"""Merge existing timestamped TXT sources without calling transcription or cleanup."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from multitrack.merging import merge_txt_files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', action='append', type=Path, required=True, help='Timestamped TXT; repeat per source')
    parser.add_argument('--offset-ms', action='append', type=float, help='Offset per file, in the same order; defaults to zero')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    offsets = args.offset_ms or [0] * len(args.file)
    if len(offsets) != len(args.file):
        parser.error('provide one --offset-ms per --file, or omit all offsets')
    try:
        import math
        if not all(math.isfinite(value) for value in offsets):
            raise ValueError('offsets must be finite')
        if args.output.resolve() in {path.resolve() for path in args.file}:
            raise ValueError('output must not replace a source TXT')
        merge_txt_files(list(zip(args.file, offsets)), args.output)
        return 0
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
