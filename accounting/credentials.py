"""Resolve each account independently without changing process environment."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from scripts.config_loader import load_effective_config
from accounting.http import AccountError, check_timeout


def read_environment(path):
    values = {}
    if path.is_file():
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key.strip()] = value
    # Match STT's documented precedence: exported values override this file.
    return {**values, **os.environ}


def section(config, path):
    result = config
    for key in path.split('.') if path else ():
        result = result.get(key, {})
        if not isinstance(result, dict):
            raise AccountError('invalid_configuration')
    return result


@dataclass(frozen=True)
class AccountSettings:
    api_key: str = field(repr=False)
    api_base_url: str
    timeout: float


def resolve_settings(root, spec):
    directory = Path(root) / spec.directory
    if spec.directory != '.' and not (directory / 'config.default.yaml').is_file():
        raise AccountError('component_not_installed')
    cfg, _ = load_effective_config(directory)
    options = section(cfg, spec.config_section)
    env = read_environment(directory / '.env')
    key_name = options.get(spec.key_env_option, spec.key_env)
    if not isinstance(key_name, str) or not key_name:
        raise AccountError('invalid_configuration')
    key = env.get(key_name, '').strip()
    if not key:
        raise AccountError('missing_credentials')
    env_url_name = f'{spec.provider.upper()}_API_BASE_URL'
    url = options.get('api_base_url') or env.get(env_url_name) or spec.default_api_base_url
    if not isinstance(url, str):
        raise AccountError('invalid_configuration')
    url = url.strip().rstrip('/')
    # Dedicated account timeout; transcription/generation timeouts can be minutes.
    timeout = check_timeout(section(cfg, 'accounting').get('timeout_seconds', 10))
    return AccountSettings(key, url, timeout)
