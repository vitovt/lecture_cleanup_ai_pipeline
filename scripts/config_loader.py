from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


def _read_yaml_dict(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def deep_merge(base: Any, override: Any) -> Any:
    """Merge override onto base.

    - dicts merge recursively
    - lists are replaced whole
    - scalars override
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged: Dict[str, Any] = {}
        for key in base.keys():
            if key in override:
                merged[key] = deep_merge(base[key], override[key])
            else:
                merged[key] = base[key]
        for key in override.keys():
            if key not in base:
                merged[key] = override[key]
        return merged
    return override


def load_default_and_local(
    base_dir: Path,
    default_name: str = "config.default.yaml",
    local_name: str = "config.yaml",
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    default_path = base_dir / default_name
    if not default_path.exists():
        raise FileNotFoundError(f"Missing required config: {default_path}")
    default_cfg = _read_yaml_dict(default_path)

    local_path = base_dir / local_name
    if local_path.exists():
        local_cfg = _read_yaml_dict(local_path)
        has_local = True
    else:
        local_cfg = {}
        has_local = False
    return default_cfg, local_cfg, has_local


def load_effective_config(
    base_dir: Path,
    default_name: str = "config.default.yaml",
    local_name: str = "config.yaml",
) -> Tuple[Dict[str, Any], bool]:
    default_cfg, local_cfg, has_local = load_default_and_local(
        base_dir, default_name=default_name, local_name=local_name
    )
    merged = deep_merge(default_cfg, local_cfg)
    return merged, has_local
