#!/usr/bin/env python3
"""Own one temporary usage journal across an entire StartMe workflow."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from accounting.usage import EVENT_FILE, UsageTotals, format_record


def run(mode, command):
    if os.environ.get(EVENT_FILE):
        return subprocess.call(command)
    try:
        descriptor, path = tempfile.mkstemp(prefix='lecture-usage-', suffix='.jsonl')
    except OSError:
        return subprocess.call(command)
    os.close(descriptor)
    try:
        try:
            code = subprocess.call(command, env={**os.environ, EVENT_FILE: path})
        except KeyboardInterrupt:
            code = 130
        finally:
            totals = UsageTotals()
            try:
                with open(path, encoding='utf-8') as events:
                    for line in events:
                        try:
                            totals.add(json.loads(line))
                        except (ValueError, TypeError):
                            continue
            except OSError:
                pass
            if any(event.get('visible') for event in totals.events):
                # Preserve standalone STT stdout JSON for shell consumers.
                stream = sys.stderr if mode == 'stt-api' else sys.stdout
                for fields in totals.records():
                    print('[INFO] ' + format_record('USAGE_TOTAL', **fields), file=stream)
        return 128 - code if code < 0 else code
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit('Internal usage: usage_runner.py MODE COMMAND [ARGUMENTS...]')
    raise SystemExit(run(sys.argv[1], sys.argv[2:]))
