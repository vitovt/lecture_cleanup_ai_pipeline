#!/usr/bin/env python3
"""Standalone source transcription and TXT merging; never invokes cleanup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_multitrack import main

if __name__ == '__main__':
    raise SystemExit(main(standalone=True))
