#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from multitrack.sources import HELP, resolve
from scripts.config_loader import load_effective_config
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
    level = 'trace' if '--trace' in argv else 'debug' if '--debug' in argv else None
    if level is None and '--log-level' in argv:
        values = argv[argv.index('--log-level') + 1:]
        level = values[0] if values else 'info'
    try:
        if level is None:
            config, _ = load_effective_config(ROOT)
            level = config.get('logging', {}).get('level', 'info')
        plan = resolve(argv, standalone=standalone)
        level = plan['log_level']
        plan = preflight(plan)
        if plan['dry_run']:
            print('Resolved multitrack plan (read-only; no transcription):')
            print(yaml.dump(plan, Dumper=PlanDumper, allow_unicode=True, sort_keys=False))
            return 0
        run(plan)
        if plan["log_level"] not in {"quiet", "error"}:
            print(f'[INFO] Artifacts retained: {plan["workdir"]}')
        return 0
    except (OSError, ValueError, RuntimeError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        if level != 'quiet':
            print(f'[ERROR] {exc}', file=sys.stderr)
        if level in {'debug', 'trace'}:
            traceback.print_exc()
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
