#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from multitrack.sources import HELP, resolve
from multitrack.workflow import preflight, run

class PlanDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def main(argv: list[str] | None = None, *, standalone: bool = False) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if '--help' in argv or '-h' in argv:
        print(HELP)
        subprocess.run(['bash', '-c', 'source "$1"; lecture_cleanup_print_forwarded_help',
                        'cleanup-help', str(ROOT / 'scripts/lecture_cleanup_shell_common.sh')], check=True)
        return 0
    try:
        plan = preflight(resolve(argv, standalone=standalone))
        if plan['dry_run']:
            print('Resolved multitrack plan (read-only; no transcription):')
            print(yaml.dump(plan, Dumper=PlanDumper, allow_unicode=True, sort_keys=False))
            return 0
        output = run(plan)
        if plan["log_level"] not in {"quiet", "error"}:
            print(f'Merged TXT: {output}')
            print(f'Artifacts retained: {plan["workdir"]}')
        return 0
    except (OSError, ValueError, RuntimeError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
