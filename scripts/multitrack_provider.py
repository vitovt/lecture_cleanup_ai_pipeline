#!/usr/bin/env python3
"""Provider-environment bridge. JSON on stdin is configuration, never merge input."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stt_args(source: dict) -> list[str]:
    args = ['--provider', source['provider'], '--timestamps', source['timestamps'],
            '--diarization', source['diarization'], '--mode', source['mode'], '--resume', source['resume']]
    languages = ['auto'] if source['multilingual'] else [source['lang'], *source['additional_lang']]
    for lang in languages:
        args += ['--language-code', str(lang)]
    for key, flag in [('model','--model'), ('provider_config','--config'), ('cache_dir','--cache-dir')]:
        if source[key] is not None:
            args += [flag, str(source[key])]
    for key in ['custom_vocabulary', 'custom_vocabulary_file']:
        for value in source[key]:
            args += ['--' + key.replace('_','-'), str(value)]
    if source['num_speakers'] != 'auto':
        args += ['--num-speakers', source['num_speakers']]
    return args


def groq_args(source: dict) -> list[str]:
    args = ['--input-file', source['input'], '--language', source['lang'],
            '--diarization', 'on' if source['diarization'] == 'pyannote' else 'off',
            '--num-speakers', source['num_speakers'], '--resume', source['resume']]
    for key, flag in [('model','--model'), ('provider_config','--config'), ('cache_dir','--cache-dir'),
                      ('prompt','--prompt'), ('temperature','--temperature'), ('max_file_cost_usd','--max-file-cost-usd')]:
        if source[key] is not None:
            args += [flag, str(source[key])]
    for policy in source['oversize_policy']:
        args += ['--oversize-policy', policy]
    return args


def execute(payload: dict) -> dict:
    source, action = payload['source'], payload['action']
    provider = source['provider']
    import logging
    level = source.get('log_level', 'info')
    logging.basicConfig(level={'quiet': 100, 'error': logging.ERROR, 'info': logging.INFO,
                               'debug': logging.DEBUG, 'trace': 5}[level],
                        format='[%(levelname)s] %(message)s', stream=sys.stderr)
    logging.addLevelName(5, 'TRACE')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.debug('Provider bridge: action=%s, provider=%s, source=%s', action, provider, source['id'])
    if provider == 'groq':
        sys.path.insert(0, str(ROOT / 'groq-api'))
        from groq_api import cli
        from groq_api.config import load_config, load_env_file, set_path, get_path
        directory = ROOT / 'groq-api'
        args = cli.build_parser().parse_args(groq_args(source))
        config = load_config(directory, Path(source['provider_config']) if source['provider_config'] else None)
        cli.apply_cli_overrides(config, args)
        # Explicit diarization must never silently lose speaker labels.
        set_path(config, 'diarization.unavailable_policy', 'fail')
        model, language, temperature, speakers = cli.validate_effective_config(config)
        cost = cli.estimate_cost(source['duration'], config, model)
        cli.enforce_file_budget(cost, config)
        if payload.get('credentials'):
            load_env_file(directory / '.env')
            if not os.environ.get(str(get_path(config, 'api.api_key_env', 'GROQ_API_KEY'))):
                raise ValueError('GROQ_API_KEY is not configured')
        if source['diarization'] == 'pyannote' and payload.get('credentials'):
            sys.path.insert(0, str(ROOT / 'pyannote-diarization'))
            from pyannote_diarization.config import load_config as load_pyannote, load_env_file as load_pyannote_env
            pyannote_dir = ROOT / 'pyannote-diarization'
            pyannote_cfg = load_pyannote(pyannote_dir)
            load_pyannote_env(pyannote_dir / '.env')
            token_env = str(pyannote_cfg.get('authentication', {}).get('token_env', 'HF_TOKEN'))
            if not os.environ.get(token_env):
                raise ValueError(f'{token_env} is required for local Pyannote diarization')
        if action == 'plan':
            return {'model': model, 'language': language, 'temperature': temperature,
                    'num_speakers': speakers, 'planned_chunks': 'provider-managed after audio preparation',
                    'diarization': source['diarization'], 'timestamps': True,
                    'oversize_policy': get_path(config, 'upload.oversize_policy'),
                    'estimated_cost_usd': cli.estimate_cost(source['duration'], config, model)}
        # Persist the exact validated configuration to disable fallback in the external runner.
        import yaml
        config_path = Path(payload['output']) / 'effective-provider.yaml'
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
        args.config = str(config_path)
        command = [str(directory / 'groq_api.sh'), 'transcribe', *groq_args(source),
                   '--config', str(config_path), '--output-dir', payload['output'],
                   '--metadata-output', str(Path(payload['output']) / 'metadata.json'), f'--{level}']
        result = subprocess.run(command, stdout=sys.stderr)
        if result.returncode:
            raise ValueError(f'Groq failed with exit code {result.returncode}')
        return json.loads((Path(payload['output']) / 'metadata.json').read_text())
    sys.path.insert(0, str(ROOT / 'stt-api'))
    from stt_api import cli
    cli.configure_logging(level)
    from stt_api.config import load_config, load_env_file
    directory = ROOT / 'stt-api'
    args = cli.build_parser().parse_args(['transcribe', '--input-file', source['input'], *stt_args(source)])
    override = Path(source['provider_config']) if source['provider_config'] else None
    config = load_config(directory, override)
    cli._apply_overrides(config, args)
    settings = cli._effective_settings(config, args, override.parent if override else directory)
    if payload.get('credentials'):
        load_env_file(directory / '.env')
        cli._validate_credentials(config, provider)
    if action == 'plan':
        settings['planned_chunks'] = cli._preflight(
            Path(source['input']), settings, duration_seconds=source['duration'],
        )['planned_chunks']
        return settings
    if settings['diarization'] and cli._preflight(Path(source['input']), settings)['planned_chunks'] != 1:
        raise ValueError('provider diarization requires splitting; stable speaker identities are unsupported')
    args.output_dir = payload['output']
    args.output_basename = 'transcript'
    args.metadata_output = str(Path(payload['output']) / 'metadata.json')
    load_env_file(directory / '.env')
    # Explicit metadata output keeps stdout reserved for the bridge protocol.
    cli.transcribe(config, args, settings)
    return json.loads(Path(args.metadata_output).read_text())


if __name__ == '__main__':
    payload = {}
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(execute(payload), ensure_ascii=False))
    except Exception as exc:
        level = payload.get('source', {}).get('log_level', 'info')
        if level != 'quiet':
            print(f'[ERROR] {exc}', file=sys.stderr)
        if level in {'debug', 'trace'}:
            traceback.print_exc()
        raise SystemExit(2)
