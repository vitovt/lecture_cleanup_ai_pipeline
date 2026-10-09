"""Preflight, extract, transcribe independently, merge TXT, optionally clean."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from multitrack.sources import ROOT
from scripts.artifact_paths import require_available, write_record, configured_cache
from multitrack.excerpts import source_window
from multitrack.merging import read_timestamped_txt, name_source_events, merge_txt_files
from multitrack.formats import write_custom_txt

sys.path.insert(0, str(ROOT / 'subtitle-utils'))
from audio_streams import inspect_audio, require_single_audio


def _log(plan: dict, message: str, *, debug: bool = False) -> None:
    level = plan.get('log_level', 'info')
    if level in {'quiet', 'error'} or (debug and level not in {'debug', 'trace'}):
        return
    print(f"[{'DEBUG' if debug else 'INFO'}] {message}", file=sys.stderr, flush=True)


def provider_call(source: dict, action: str, *, credentials: bool = False, output: Path | None = None) -> dict:
    directory = ROOT / ('groq-api' if source['provider'] == 'groq' else 'stt-api')
    python = directory / '.venv/bin/python'
    if not python.is_file():
        raise ValueError(f'{directory.name}: virtualenv missing; run its setup_venv.sh')
    result = subprocess.run([str(python), str(ROOT / 'scripts/multitrack_provider.py')],
        input=json.dumps({'source': source, 'action': action, 'credentials': credentials,
                          'output': str(output) if output else None}),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE if action == 'plan' else None, text=True)
    if result.returncode:
        raise ValueError(f"source {source['id']}: {(result.stderr or 'provider process failed').strip()}")
    if action != 'plan' and result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    return json.loads(result.stdout)


def preflight(plan: dict) -> dict:
    require_available(Path(plan['outdir']) / (plan['output_name'] + '.md'), plan['overwrite'])
    for binary in ['ffprobe', 'ffmpeg']:
        if not shutil.which(binary):
            raise ValueError(f'{binary} is required')
    # Parse cleanup arguments before any paid work, using the cleanup parser itself.
    from scripts.run_pipeline import build_parser
    parser = build_parser()
    try:
        parser.parse_args(['--input', 'planned.txt', '--lang', plan['cleanup_lang'] or 'uk', *plan['cleanup_args']])
    except SystemExit as exc:
        raise ValueError('invalid cleanup arguments') from exc
    for index, token in enumerate(plan['cleanup_args']):
        if token in {'--context-file', '--glossary'}:
            if not Path(plan['cleanup_args'][index + 1]).expanduser().is_file():
                raise ValueError(f'{token}: referenced file does not exist')
    recording = inspect_audio(Path(plan['recording'])) if plan['recording'] else None
    labels = set()
    session_ends = []
    for source in plan['sources']:
        ident = source['id']
        if source['name'] in labels:
            raise ValueError(f'duplicate source display name: {source["name"]}')
        labels.add(source['name'])
        if 'track' in source:
            assert recording is not None
            if source['track'] > len(recording['streams']):
                raise ValueError(f"source {ident}: requested track {source['track']}; recording contains {len(recording['streams'])}")
            info = recording
            stream = info['streams'][source['track']-1]
            source['input'] = plan['recording']
        else:
            source['input'] = source['file']
            info = require_single_audio(Path(source['file']))
            stream = info['streams'][0]
        source['log_level'] = plan['log_level']
        source['original_duration'] = info['duration']
        source['stream_index'] = stream['index']
        source['stream_start'] = float(stream.get('start_time', 0) or 0)
        stream_delay = 0.0
        if 'track' in source:
            origin = min(float(s.get('start_time', 0) or 0) for s in info['streams'])
            stream_delay = source['stream_start'] - origin
        timeline_offset_ms = source['offset_ms'] + stream_delay * 1000
        available = info['duration'] - stream_delay
        session_ends.append(available + timeline_offset_ms / 1000)
        if plan['excerpt']:
            try:
                source.update(source_window(available, timeline_offset_ms, plan['start'], plan['end']))
            except ValueError as exc:
                raise ValueError(f'source {ident}: {exc}') from exc
        else:
            source.update(extract_start=0.0, duration=available, merge_offset_ms=timeline_offset_ms)
        source['extract_seek'] = stream_delay + source['extract_start']
        if source['timestamps'] != 'on':
            raise ValueError(f'source {ident}: TXT merging requires timestamps on')
        provider = source['provider']
        if provider == 'groq':
            if source['diarization'] == 'provider':
                raise ValueError(f'source {ident}: Groq has no native diarization; select pyannote')
            if source['additional_lang'] or source['multilingual'] or source['custom_vocabulary'] or source['custom_vocabulary_file'] or source['mode'] != 'verbatim':
                raise ValueError(f'source {ident}: Groq does not support additional-lang, multilingual, custom-vocabulary, or smart mode; use --lang auto / --prompt, or another provider')
        else:
            if source['diarization'] == 'pyannote':
                raise ValueError(f'source {ident}: this adapter supports pyannote with Groq only; select provider or off')
            if any(source[k] is not None for k in ['prompt', 'temperature', 'max_file_cost_usd']) or source['oversize_policy']:
                raise ValueError(f'source {ident}: Groq-only options supplied to {provider}')
        if source['diarization'] == 'pyannote':
            for relative in ['pyannote-diarization/pyannote_diarization.sh', 'pyannote-diarization/.venv/bin/python']:
                if not (ROOT / relative).is_file():
                    raise ValueError(f'local diarization dependency missing: {relative}')
        custom_cache = source['cache_dir'] or configured_cache(provider, source['provider_config'])
        source['custom_cache_dir'] = bool(custom_cache)
        source['cache_dir'] = custom_cache or str(Path(plan['workdir']) / 'cache' / ident)
        source['provider_settings'] = provider_call(source, 'plan', credentials=not plan['dry_run'])
        if source['diarization'] == 'provider' and source['provider_settings']['planned_chunks'] != 1:
            raise ValueError(f'source {ident}: provider diarization requires {source["provider_settings"]["planned_chunks"]} requests; stable speaker identities across chunks are unsupported')
        source['audio_output'] = str(Path(plan['workdir']) / 'media' / ident / 'audio.flac')
        source['txt_output'] = str(Path(plan['workdir']) / 'transcripts' / ident / 'source.txt')
    if plan['end'] is not None and plan['end'] > max(session_ends) + 0.001:
        raise ValueError('--end exceeds the available session duration')
    plan['merged_txt'] = str(Path(plan['transcript_dir']) / (plan['output_name'] + '.txt'))
    originals = {Path(source['input']).resolve() for source in plan['sources']}
    outputs = [Path(plan['merged_txt'])]
    for source in plan['sources']:
        outputs.extend([Path(source['audio_output']), Path(source['txt_output'])])
    if originals & {path.resolve() for path in outputs}:
        raise ValueError('artifact paths must not overwrite original source recordings; choose another --workdir')
    if plan['cleanup']:
        languages = {str(s['lang']).split('-')[0] for s in plan['sources']}
        language = plan['cleanup_lang'] or (next(iter(languages)) if len(languages) == 1 else None)
        import re
        if not language or not re.fullmatch('[a-z]{2}', language):
            raise ValueError('cleanup requires --cleanup-lang CODE when source languages differ or use auto')
        plan['cleanup_lang'] = language
    return plan


def _fingerprint(source: dict) -> str:
    # Hash bytes, not only filenames or timestamps: replacing a recording invalidates reuse.
    digest = hashlib.sha256()
    with Path(source['input']).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    keys = {k:v for k,v in source.items() if k not in {'origins', 'audio_output', 'txt_output'}}
    provider_dir = ROOT / ('groq-api' if source['provider'] == 'groq' else 'stt-api')
    configs = [provider_dir / 'config.default.yaml', Path(source['provider_config']) if source['provider_config'] else provider_dir / 'config.yaml']
    if source['diarization'] == 'pyannote':
        configs.extend([ROOT / 'pyannote-diarization/config.default.yaml', ROOT / 'pyannote-diarization/config.yaml'])
    for path in configs:
        if path.is_file():
            digest.update(path.read_bytes())
    digest.update(json.dumps(keys, sort_keys=True).encode())
    return digest.hexdigest()


def run(plan: dict) -> Path:
    workdir = Path(plan['workdir'])
    require_available(Path(plan['outdir']) / (plan['output_name'] + '.md'), plan['overwrite'])
    write_record(workdir, inputs=[s['input'] for s in plan['sources']], custom_workdir=plan.get('custom_workdir', False),
                 outputs={'markdown': {'path': str(Path(plan['outdir']) / (plan['output_name'] + '.md')), 'protected': True, 'overridden': plan['custom_outdir']},
                          'transcript': {'path': plan['merged_txt'], 'protected': True, 'overridden': plan['custom_transcript_dir']},
                          'source_caches': [{'path': s['cache_dir'], 'protected': s['custom_cache_dir'], 'overridden': s['custom_cache_dir']} for s in plan['sources']]})
    (workdir / 'resolved-plan.yaml').write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False))
    inputs = []
    speaker_owners = {}
    for source in plan['sources']:
        _log(plan, f"Source {source['id']}: {source['provider']} / {source['diarization']}")
        destination = Path(source['txt_output']).parent
        destination.mkdir(parents=True, exist_ok=True)
        _log(plan, f"Source {source['id']}: hashing input and checking completed-source cache")
        started = time.monotonic()
        signature = _fingerprint(source)
        _log(plan, f"Input fingerprint ready in {time.monotonic() - started:.2f}s; input={source['input']}", debug=True)
        stamp = destination / 'completed.json'
        txt = Path(source['txt_output'])
        cached = False
        if not plan['overwrite'] and stamp.is_file() and txt.is_file():
            try:
                cached = json.loads(stamp.read_text()).get('fingerprint') == signature
                if cached:
                    read_timestamped_txt(txt)
            except (ValueError, OSError):
                cached = False
        _log(plan, f"Source {source['id']}: cache {'hit; reusing source TXT' if cached else 'miss or bypassed; processing audio'}")
        if not cached:
            audio = Path(source['audio_output'])
            audio.parent.mkdir(parents=True, exist_ok=True)
            temporary = audio.with_name('audio.part.flac')
            command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                       '-ss', str(source['extract_seek']), '-i', source['input'],
                       '-t', str(source['duration']), '-map', f"0:{source['stream_index']}",
                       '-vn', '-c:a', 'flac', str(temporary)]
            _log(plan, f"Source {source['id']}: extracting {source['duration']:.3f}s of audio")
            _log(plan, f"Extraction: stream={source['stream_index']}, seek={source['extract_seek']:.3f}s, output={audio}", debug=True)
            started = time.monotonic()
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f'extraction failed: {result.stderr.strip()}')
            temporary.replace(audio)
            _log(plan, f"Extraction complete in {time.monotonic() - started:.2f}s; {audio.stat().st_size} bytes", debug=True)
            provider_dir = workdir / 'provider' / source['id']
            provider_dir.mkdir(parents=True, exist_ok=True)
            effective = {**source, 'input': str(audio)}
            if plan['overwrite']:
                effective['resume'] = 'off'
            _log(plan, f"Source {source['id']}: starting {source['provider']} provider preparation")
            started = time.monotonic()
            metadata = provider_call(effective, 'transcribe', credentials=True, output=provider_dir)
            _log(plan, f"Provider completed in {time.monotonic() - started:.2f}s; transcript={metadata['transcript_file']}", debug=True)
            raw_txt = Path(metadata['transcript_file'])
            events = name_source_events(read_timestamped_txt(raw_txt), source['name'], source['diarization'], source['num_speakers'])
            write_custom_txt(txt, events)
            stamp.write_text(json.dumps({'fingerprint': signature}))
        for label in {e.speaker for e in read_timestamped_txt(txt)}:
            if label in speaker_owners and speaker_owners[label] != source['id']:
                raise ValueError(f'speaker label collision: {label}; choose distinct source names')
            speaker_owners[label] = source['id']
        inputs.append((txt, source['merge_offset_ms']))
    output = Path(plan['merged_txt'])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.part.txt')
    _log(plan, f"Merging {len(inputs)} source transcripts by timestamp")
    merge_txt_files(inputs, temporary)
    temporary.replace(output)
    _log(plan, f"Merged transcript: {output}")
    if plan['cleanup']:
        _log(plan, 'Starting lecture cleanup')
        speaker_context = workdir / 'speaker-context.md'
        speaker_context.write_text(
            'Preserve every speaker label and speaker change in this conversation. '
            'Do not combine speech belonging to different speakers or rename speakers. '
            'Preserve chronological order, including short interruptions.\n', encoding='utf-8')
        command = [str(ROOT / 'lecture_cleanup.sh'), '--input', str(output), '--lang', plan['cleanup_lang'],
                   '--outdir', plan['outdir'], '--log-level', plan['log_level'],
                   '--context-file', str(speaker_context), *plan['cleanup_args']]
        if plan['overwrite']:
            command.append('--overwrite')
        subprocess.run(command, check=True)
    else:
        _log(plan, f"Stopping after merge: {plan.get('stop_reason') or 'cleanup disabled'}. Source artifacts retained.")
    return output
