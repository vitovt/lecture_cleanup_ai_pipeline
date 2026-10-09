"""Shared output destinations and ownership records for generated artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH_VARIABLES = {'CLEANUP_MDOUTDIR', 'TRANSCRIPT_OUTDIR'}


def path_settings(root: Path = ROOT) -> dict[str, str]:
    values = {}
    env_file = root / '.env'
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.removeprefix('export ').partition('=')
            if sep and key.strip() in PATH_VARIABLES:
                parts = shlex.split(value, comments=True)
                values[key.strip()] = parts[0] if parts else ''
    # Match the workflows' existing .env precedence over exported defaults.
    return {key: values.get(key, os.environ.get(key, '')) for key in PATH_VARIABLES}


def absolute(value: str | Path, base: Path) -> Path:
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def destination(kind: str, cli: str | None = None, *, root: Path = ROOT) -> tuple[Path, bool]:
    """Return absolute path and whether the caller owns it (excluded from cleaning)."""
    if cli:
        return absolute(cli, Path.cwd()), True
    variable, default = {'md': ('CLEANUP_MDOUTDIR', 'output'),
                         'transcript': ('TRANSCRIPT_OUTDIR', 'input/transcripts')}[kind]
    setting = path_settings(root).get(variable)
    return absolute(setting or default, root), bool(setting)


def configured_cache(provider: str, config: str | None = None) -> str | None:
    """Honor provider cache overrides before choosing a job-local default."""
    import yaml
    directory = ROOT / ('groq-api' if provider == 'groq' else 'stt-api')
    value = None
    for path in (directory / 'config.default.yaml', Path(config).expanduser() if config else directory / 'config.yaml'):
        if path.is_file():
            data = yaml.safe_load(path.read_text()) or {}
            resume = data.get('resume', {}) if provider == 'groq' else data.get('processing', {}).get('resume', {})
            key = 'cache_dir' if provider == 'groq' else 'checkpoint_directory'
            if key in resume:
                value = resume[key]
    return str(absolute(value, Path.cwd())) if value else None


def job_directory(name: str, identity: str, *, root: Path = ROOT) -> Path:
    safe = re.sub(r'[/\\\x00-\x1f]', '_', name).strip('. ')[:90] or 'session'
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return root / 'input/_work' / f'{safe}-{digest}'


def require_available(path: Path, overwrite: bool = False) -> None:
    if (path.exists() or path.is_symlink()) and not overwrite:
        raise ValueError(f'Markdown already exists: {path}. Use --overwrite to replace it.')


def write_record(workdir: Path, *, inputs: list[str], outputs: dict, custom_workdir: bool = False) -> None:
    managed = ROOT / 'input/_work'
    cleanable = not custom_workdir and managed.resolve() == managed and workdir.resolve().is_relative_to(managed)
    workdir.mkdir(parents=True, exist_ok=True)
    record = {'schema': 'lecture-artifacts-v1', 'inputs': inputs, 'workdir': str(workdir),
              'automatic_cleaning_allowed': cleanable,
              'categories': {name: str(workdir / name) for name in ('media', 'transcripts', 'provider', 'cache')},
              'outputs': outputs}
    target = workdir / 'run.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    defaults = commands.add_parser('defaults')
    defaults.add_argument('--kind', choices=['md', 'transcript'])
    job = commands.add_parser('job')
    job.add_argument('--name', required=True)
    job.add_argument('--input', required=True)
    job.add_argument('--workflow', required=True)
    job.add_argument('--outdir')
    job.add_argument('--transcript-dir')
    job.add_argument('--provider')
    job.add_argument('--provider-config')
    job.add_argument('--cache-dir')
    job.add_argument('--overwrite', action='store_true')
    job.add_argument('--managed-md', action='store_true')
    job.add_argument('--managed-transcript', action='store_true')
    args = parser.parse_args()
    if args.command == 'defaults':
        if args.kind:
            print(destination(args.kind)[0])
        else:
            for var, kind in [('OUTDIR', 'md'), ('SRTOUTDIR', 'transcript')]:
                path, custom = destination(kind)
                print(f'{var}={shlex.quote(str(path))}')
                print(f'{var}_CUSTOM={int(custom)}')
        return
    md, md_custom = destination('md', args.outdir)
    transcript, transcript_custom = destination('transcript', args.transcript_dir)
    require_available(md / (args.name + '.md'), args.overwrite)
    work = job_directory(args.name, args.workflow + '\n' + args.input)
    custom_cache = args.cache_dir or (configured_cache(args.provider, args.provider_config) if args.provider else None)
    cache = absolute(custom_cache, Path.cwd()) if custom_cache else work / 'cache'
    write_record(work, inputs=[args.input], outputs={
        'cache': {'path': str(cache), 'protected': bool(custom_cache), 'overridden': bool(custom_cache)},
        'markdown': {'path': str(md / (args.name + '.md')), 'protected': True, 'overridden': md_custom and not args.managed_md},
        'transcript': {'path': str(transcript / (args.name + '.txt')), 'protected': True, 'overridden': transcript_custom and not args.managed_transcript}})
    for name in ('media', 'transcripts', 'provider', 'cache'):
        (work / name).mkdir(exist_ok=True)
    for name, value in [('WORKDIR', work), ('WORKFLOW_CACHE_DIR', cache), ('TRANSCRIPT_DIR', transcript), ('OUTDIR', md),
                        ('OUT_MD', md / (args.name + '.md')), ('SRTOUTDIR', work / 'provider')]:
        print(f'{name}={shlex.quote(str(value))}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        raise SystemExit(2)
