from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping: {path}")
    return data


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        result = dict(base)
        for key, value in override.items():
            result[key] = deep_merge(result[key], value) if key in result else value
        return result
    return override


def load_config(project_dir: Path, override: Path | None = None) -> dict[str, Any]:
    default_path = project_dir / "config.default.yaml"
    if not default_path.is_file():
        raise ConfigError(f"missing default config: {default_path}")
    result = read_yaml(default_path)
    local_path = override or project_dir / "config.yaml"
    if local_path.is_file():
        result = deep_merge(result, read_yaml(local_path))
    elif override is not None:
        raise ConfigError(f"config override not found: {local_path}")
    return result


def get_path(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set_path(config: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    current = config
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE file without overriding process environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
