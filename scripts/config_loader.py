from __future__ import annotations

from pathlib import Path
from copy import deepcopy
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
    llm = result.get("llm", {})
    selected = profile if profile is not None else (
        None if provider_override else llm.get("default_profile")
    )
    if selected is None:
        return result
    profiles = llm.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("llm.profiles must be a mapping")
    if not isinstance(selected, str) or selected not in profiles:
        raise ValueError(f"Unknown LLM profile {selected!r}; available: {', '.join(map(str, profiles)) or 'none'}")
    preset = profiles[selected]
    if not isinstance(preset, dict):
        raise ValueError(f"llm.profiles.{selected} must be a mapping")
    provider = preset.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(f"llm.profiles.{selected}.provider is required")
    provider = provider.strip().lower()
    if provider_override and provider_override.strip().lower() != provider:
        raise ValueError(f"LLM profile {selected!r} uses {provider}, conflicting with --llm-provider {provider_override}")
    if not isinstance(llm.get(provider), dict):
        raise ValueError(f"No LLM configuration for profile provider {provider}")
    llm[provider] = deep_merge(llm[provider], {k: v for k, v in preset.items() if k != "provider"})
    llm["provider"] = provider
    llm["active_profile"] = selected
    return result
