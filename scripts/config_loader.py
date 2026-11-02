from __future__ import annotations

from pathlib import Path
import sys
from copy import deepcopy
from typing import Any, Dict, Tuple

import yaml

# Also support utilities that import this module via the scripts directory.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from provider_profiles import deep_merge, resolve_provider_profile


def _read_yaml_dict(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


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
    *,
    llm_profile: str | None = None,
    provider_override: str | None = None,
) -> Tuple[Dict[str, Any], bool]:
    default_cfg, local_cfg, has_local = load_default_and_local(
        base_dir, default_name=default_name, local_name=local_name
    )
    merged = deep_merge(default_cfg, local_cfg)
    return resolve_llm_profile(merged, llm_profile, provider_override), has_local


def resolve_llm_profile(cfg: Dict[str, Any], profile: str | None = None,
                        provider_override: str | None = None) -> Dict[str, Any]:
    """Apply one flat provider preset after file merging, before CLI overrides.

    An explicit provider bypasses the default profile. An explicit profile and
    a conflicting provider are rejected rather than silently changing models.
    Never modify the input mapping or persist a selection to disk.
    """
    result = deepcopy(cfg)
    if "llm" in result:
        result["llm"] = resolve_provider_profile(result["llm"], profile, provider_override)
    elif "providers" in result:
        result = resolve_provider_profile(result, profile, provider_override,
            providers_key="providers", label="STT", provider_flag="--provider")
    return result
