"""Resolve scoped CLI/YAML sources without performing media or provider work."""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import yaml

from scripts.config_loader import load_effective_config
from multitrack.excerpts import parse_time

ROOT = Path(__file__).resolve().parents[1]


class PresetLoader(yaml.SafeLoader):
    # YAML 1.2-style booleans: unquoted off/on are mode strings, not bools.
    yaml_implicit_resolvers = {
        key: [(tag, pattern) for tag, pattern in rules if tag != 'tag:yaml.org,2002:bool']
        for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


PresetLoader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'), list('tTfF'))

SHARED = {
    'provider': 'groq', 'lang': 'auto', 'additional_lang': [],
    'diarization': 'off', 'num_speakers': 'auto', 'model': None,
    'provider_config': None, 'custom_vocabulary': [], 'custom_vocabulary_file': [],
    'multilingual': False, 'mode': 'verbatim', 'timestamps': 'on',
    'resume': 'on', 'cache_dir': None, 'prompt': None, 'temperature': None,
    'oversize_policy': [], 'max_file_cost_usd': None,
}
SOURCE_ONLY = {'track', 'file', 'name', 'offset_ms'}
LISTS = {'additional_lang', 'custom_vocabulary', 'custom_vocabulary_file', 'oversize_policy'}
PATHS = {'file', 'provider_config', 'cache_dir'}
GLOBALS = {'preset', 'workdir', 'outdir', 'output_name', 'cleanup_lang', 'log_level', 'start', 'end'}
FLAGS = {'dry_run', 'overwrite', 'cleanup', 'stop_after_merge', 'debug', 'trace'}

HELP = '''Usage: ./StartMe.sh multitrack [GLOBAL OPTIONS] --source ID [SOURCE OPTIONS] ... [RECORDING]
       ./process_multitrack.sh [same options]
       python3 scripts/transcribe_tracks.py [same options; never runs cleanup]

Options before the first --source are shared defaults or global workflow options.
Each --source ID starts a source context. Global-only options are forbidden there.
RECORDING must be last and is required only if a resolved source uses --track.

Global workflow options:
  --preset FILE             YAML defaults/sources; CLI overrides by source ID
  --workdir DIR             Artifacts (default: multitrack-work/<recording or session>)
  --outdir DIR              Cleanup Markdown (default: output/multitrack)
  --output-name NAME        Merged TXT basename (default: recording stem or session)
  --start TIME              Session start: seconds or HH:MM:SS[.mmm] (default 0)
  --end TIME                Session end, exclusive (default end of sources)
                            Global only; merged TXT keeps original timestamps
  --dry-run                 Read-only preflight; show all effective defaults/settings
  --overwrite               Reprocess sources instead of reusing verified results
  --cleanup                 Run cleanup after merge
  --stop-after-merge        Stop at TXT (initial configuration default)
  --cleanup-lang CODE      Required for cleanup when sources use different languages/auto
  --log-level LEVEL         quiet|error|info|debug|trace
  --debug / --trace         Diagnostic logging
  Cleanup flags from lecture_cleanup.sh are global, including --llm-provider,
  --context-file, --short-summary, --long-summary, --include-timecodes, etc.

Source selection (only inside a source context):
  --source ID              Unique stable identifier (letters/digits/_/-/.)
  --track N                One-based audio stream in RECORDING; exclusive with --file
  --file FILE              Separate file with exactly one audio stream
  --name NAME              Recommended speaker label; default Source_<ID>
  --offset-ms NUMBER       Manual timeline adjustment (default 0)

Shared defaults / source overrides:
  --provider NAME          groq|gemini|elevenlabs (default groq)
  --lang CODE              Primary language or auto (default auto)
  --additional-lang CODE   Repeatable; replaces inherited list on first occurrence
  --no-additional-langs    Clear inherited additional languages
  --multilingual / --no-multilingual   Native automatic multilingual recognition
  --diarization MODE       off|pyannote|provider; no automatic fallback
  --num-speakers N|auto    Expected count; requires a supporting diarization engine
  --model NAME             Transcription model (cleanup uses --llm-provider)
  --provider-config FILE   Provider YAML override
  --custom-vocabulary TERM / --custom-vocabulary-file FILE   Repeatable
  --mode verbatim|smart    Provider mode; only timed modes can be merged
  --timestamps on          Timed output is mandatory
  --resume on|off          Provider checkpoints
  --cache-dir DIR          Provider checkpoint directory
  --prompt TEXT / --temperature N / --oversize-policy POLICY (repeatable)
  --max-file-cost-usd N    Groq-specific options; incompatible providers reject them

Examples (descriptive --name values are recommended):
  ./StartMe.sh multitrack --provider elevenlabs --lang uk --additional-lang de \\
    --source student --track 2 --name Student_Nazar \\
    --source teacher --track 5 --name Teacher_Vitalii recording.mkv
  ./StartMe.sh multitrack --provider groq --lang uk \\
    --source host --file host.wav --name Vitalii \\
    --source audience --file audience.wav --name Students --diarization pyannote --num-speakers 3
  ./StartMe.sh multitrack --preset webinar.yaml --start 00:00:10 --end 00:01:10 --dry-run recording.mkv
  ./StartMe.sh multitrack --preset webinar.yaml --lang de \\
    --source teacher --file better.wav --name Teacher_Vitalii \\
    --source translator --file translator.wav --name Interpreter recording.mkv

CLI globals override YAML defaults; source settings override shared defaults.
Existing IDs update; new IDs append. A CLI file replaces an inherited track and
vice versa. YAML paths resolve relative to the preset, CLI paths to the cwd.
Provider diarization requiring multiple requests is rejected. Sources and provider
artifacts are retained. See Docs/MULTITRACK_DESIGN.md and Docs/PIPELINE_Multitrack.md.
'''


def _paths(values: dict, base: Path) -> dict:
    values = dict(values)
    for key in PATHS:
        if values.get(key) is not None:
            path = Path(str(values[key])).expanduser()
            values[key] = str((base / path).resolve())
    if 'custom_vocabulary_file' in values:
        values['custom_vocabulary_file'] = [str((base / Path(str(p)).expanduser()).resolve())
                                             for p in values['custom_vocabulary_file']]
    return values


def _validate_keys(values: dict, allowed: set, label: str) -> None:
    if not isinstance(values, dict):
        raise ValueError(f'{label} must be a mapping')
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f'{label}: unknown options: {sorted(unknown)}')
    for key in LISTS & values.keys():
        if not isinstance(values[key], list):
            raise ValueError(f'{label}.{key} must be a list')
    if 'track' in values and 'file' in values:
        raise ValueError(f'{label}: track and file are mutually exclusive')


def _cleanup_option(option: str, value: str) -> int:
    # Reuse the shell workflow allowlist, rather than maintaining a second list.
    result = subprocess.run(['bash', '-c',
        'source "$1"; lecture_cleanup_parse_option "$2" "$3" || exit $?; printf "%s" "$LECTURE_CLEANUP_OPTION_SHIFT"',
        'cleanup-options', str(ROOT / 'scripts/lecture_cleanup_shell_common.sh'), option, value],
        capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'unknown option: {option}')
    return int(result.stdout)


def resolve(argv: list[str], *, standalone: bool = False) -> dict:
    config, _ = load_effective_config(ROOT)
    configured = config.get('multitrack', {})
    shared, cli_sources, workflow, cleanup = {}, {}, {}, []
    current = None
    recording = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if not token.startswith('--'):
            if i != len(argv) - 1 or recording is not None:
                raise ValueError('recording must be the single final positional argument')
            recording = str(Path(token).expanduser().resolve())
            break
        key = token[2:].replace('-', '_')
        if key == 'source':
            if i + 1 >= len(argv) or argv[i+1].startswith('--'):
                raise ValueError('--source requires an ID')
            ident = argv[i+1]
            if not re.fullmatch(r'[\w.-]+', ident) or ident in {'.', '..'}:
                raise ValueError('source ID must contain only letters, digits, _, -, or .')
            if ident in cli_sources:
                raise ValueError(f'duplicate CLI source ID: {ident}')
            current = cli_sources.setdefault(ident, {})
            i += 2
            continue
        if key in GLOBALS | FLAGS or key not in set(SHARED) | SOURCE_ONLY | {'no_additional_langs', 'no_multilingual'}:
            if current is not None:
                raise ValueError(f'{token} is global-only or unknown; place global options before --source')
            if key in FLAGS:
                workflow[key] = True
                i += 1
                continue
            if key in GLOBALS:
                if i+1 >= len(argv) or argv[i+1].startswith('--'):
                    raise ValueError(f'{token} requires a value')
                workflow[key] = argv[i+1]
                i += 2
                continue
            if key == 'context_file':
                shift = 2
            else:
                shift = _cleanup_option(token, argv[i+1] if i+1 < len(argv) else '')
            if shift == 2 and (i+1 >= len(argv) or argv[i+1].startswith('--')):
                raise ValueError(f'{token} requires a value')
            cleanup.extend(argv[i:i+shift])
            i += shift
            continue
        if key in SOURCE_ONLY and current is None:
            raise ValueError(f'{token} requires a preceding --source ID')
        target = shared if current is None else current
        if key in {'multilingual', 'no_multilingual', 'no_additional_langs'}:
            target['additional_lang' if key == 'no_additional_langs' else 'multilingual'] = [] if key == 'no_additional_langs' else key == 'multilingual'
            i += 1
            continue
        if i+1 >= len(argv) or argv[i+1].startswith('--'):
            raise ValueError(f'{token} requires a value')
        value = argv[i+1]
        if key in LISTS:
            target.setdefault(key, []).append(value)
        else:
            if key in target:
                raise ValueError(f'duplicate option in one context: {token}')
            target[key] = value
        i += 2
    preset = {}
    base = Path.cwd()
    if workflow.get('preset'):
        path = Path(workflow['preset']).expanduser().resolve()
        preset = yaml.load(path.read_text(), Loader=PresetLoader) or {}
        base = path.parent
    _validate_keys(preset, {'defaults', 'sources'}, 'preset')
    defaults = preset.get('defaults', {})
    _validate_keys(defaults, set(SHARED), 'defaults')
    effective_defaults = {**SHARED, **_paths(defaults, base), **_paths(shared, Path.cwd())}
    raw_sources = preset.get('sources', [])
    if not isinstance(raw_sources, list):
        raise ValueError('sources must be a list')
    sources = {}
    origins = {}
    for raw in raw_sources:
        _validate_keys(raw, set(SHARED) | SOURCE_ONLY | {'id'}, 'source')
        ident = str(raw.get('id', ''))
        if not re.fullmatch(r'[\w.-]+', ident) or ident in {'.', '..'} or ident in sources:
            raise ValueError(f'invalid or duplicate preset source ID: {ident!r}')
        sources[ident] = _paths({k:v for k,v in raw.items() if k != 'id'}, base)
        origins[ident] = {k:'preset source' for k in sources[ident]}
    for ident, raw in cli_sources.items():
        _validate_keys(raw, set(SHARED) | SOURCE_ONLY, f'source {ident}')
        old = sources.setdefault(ident, {})
        if 'file' in raw:
            old.pop('track', None)
        if 'track' in raw:
            old.pop('file', None)
        old.update(_paths(raw, Path.cwd()))
        origins.setdefault(ident, {}).update({k:'CLI source' for k in raw})
    resolved = []
    for ident, raw in sources.items():
        if ('track' in raw) == ('file' in raw):
            raise ValueError(f'source {ident} requires exactly one of track or file')
        item = {**effective_defaults, 'offset_ms': 0, **raw, 'id': ident}
        item.setdefault('name', f'Source_{ident}')
        if not isinstance(item['name'], str) or not item['name'].strip() or re.search(r'[\[\]\r\n]', item['name']):
            raise ValueError(f'invalid speaker name for {ident}')
        if 'track' in item:
            if isinstance(item['track'], bool) or not str(item['track']).isdigit() or int(item['track']) < 1:
                raise ValueError(f'source {ident}: track must be a positive integer')
            item['track'] = int(item['track'])
        if 'file' in item and (not isinstance(item['file'], str) or not item['file']):
            raise ValueError(f'source {ident}: file must be a nonempty path')
        try:
            item['offset_ms'] = float(item['offset_ms'])
        except (TypeError, ValueError) as exc:
            raise ValueError(f'source {ident}: offset must be numeric') from exc
        if not math.isfinite(item['offset_ms']):
            raise ValueError(f'source {ident}: offset must be finite')
        if not isinstance(item['diarization'], str) or item['diarization'] not in {'off', 'pyannote', 'provider'}:
            raise ValueError(f'source {ident}: diarization must be off|pyannote|provider')
        count = str(item['num_speakers'])
        if count != 'auto' and (not count.isdigit() or int(count) < 1):
            raise ValueError(f'source {ident}: num-speakers must be auto or positive')
        if count != 'auto' and item['diarization'] == 'off':
            raise ValueError(f'source {ident}: num-speakers requires diarization')
        item['num_speakers'] = count
        if not isinstance(item['multilingual'], bool):
            raise ValueError(f'source {ident}: multilingual must be true or false')
        for key in ['provider', 'lang', 'mode', 'resume', 'timestamps']:
            if not isinstance(item[key], str) or not item[key]:
                raise ValueError(f'source {ident}: {key} must be a nonempty string')
        for key in LISTS:
            if any(not isinstance(value, str) or not value for value in item[key]):
                raise ValueError(f'source {ident}: {key} entries must be nonempty strings')
        item['origins'] = {k: origins[ident].get(k, 'CLI default' if k in shared else 'preset default' if k in defaults else 'application default') for k in item if k != 'id'}
        resolved.append(item)
    if not resolved:
        raise ValueError('at least one --source or preset source is required')
    needs_recording = any('track' in s for s in resolved)
    if needs_recording != bool(recording):
        raise ValueError('final recording is required for track sources' if needs_recording else 'final recording is unused: all sources select files')
    if workflow.get('cleanup') and workflow.get('stop_after_merge'):
        raise ValueError('--cleanup and --stop-after-merge are mutually exclusive')
    start = parse_time(workflow.get('start', '0'))
    end = parse_time(workflow['end']) if 'end' in workflow else None
    if end is not None and end <= start:
        raise ValueError('--end must be greater than --start')
    excerpt = 'start' in workflow or 'end' in workflow
    name = workflow.get('output_name') or (Path(recording).stem if recording else 'session')
    if name in {'', '.', '..'} or Path(name).name != name:
        raise ValueError('--output-name must be a filename component')
    if excerpt and not workflow.get('output_name'):
        end_label = str(round(end * 1000)) if end is not None else 'end'
        name += f'.excerpt-{round(start * 1000)}-{end_label}ms'
    level = 'trace' if workflow.get('trace') else 'debug' if workflow.get('debug') else workflow.get('log_level', 'info')
    if level not in {'quiet', 'error', 'info', 'debug', 'trace'}:
        raise ValueError('invalid log level')
    return {
        'recording': recording, 'sources': resolved,
        'excerpt': excerpt, 'start': start, 'end': end,
        'workdir': str(Path(workflow.get('workdir', f'multitrack-work/{name}')).expanduser().resolve()),
        'outdir': str(Path(workflow.get('outdir', 'output/multitrack')).expanduser().resolve()),
        'output_name': name, 'dry_run': workflow.get('dry_run', False),
        'overwrite': workflow.get('overwrite', False), 'log_level': level,
        'cleanup': not standalone and not workflow.get('stop_after_merge', False) and (workflow.get('cleanup', False) or not configured.get('stop_after_merge', True)),
        'cleanup_lang': workflow.get('cleanup_lang'), 'cleanup_args': cleanup,
    }
