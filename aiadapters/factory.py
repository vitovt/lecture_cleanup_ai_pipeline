from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from .base import LLMAdapter, LLMAuthError


def _load_env_file_generic(project_root: Path) -> bool:
    """Load key=value pairs from .env into os.environ.

    - Supports optional 'export ' prefix per line.
    - Silent on errors; returns True if at least one key=value pair was loaded.
    """
    env_path = project_root / ".env"
    if not env_path.exists():
        return False
    loaded_any = False
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].lstrip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v:
                    os.environ[k] = v
                    loaded_any = True
    except Exception:
        # silent; fall back to existing environment
        return loaded_any
    return loaded_any


def _effective_provider_and_config(cfg: Dict, provider_override: Optional[str]) -> Tuple[str, Dict]:
    """Resolve provider name and its config from the global config dict.

    Supports both new structure:
      llm:
        provider: openai|gemini|...
        openai: { model, temperature, top_p }
        gemini: { model, temperature, top_p }

    and legacy top-level keys: model, temperature, top_p.
    """
    llm_section = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}
    provider = (provider_override or llm_section.get("provider") or "openai").strip().lower()
    provider_cfg = {}
    if isinstance(llm_section.get(provider), dict):
        provider_cfg = dict(llm_section.get(provider) or {})
    # Backward-compat fallbacks
    provider_cfg.setdefault("model", cfg.get("model"))
    provider_cfg.setdefault("temperature", cfg.get("temperature"))
    provider_cfg.setdefault("top_p", cfg.get("top_p"))
    return provider, provider_cfg


def create_llm_adapter(cfg: Dict, *, provider_override: Optional[str], project_root: Path) -> LLMAdapter:
    """Factory returning a configured LLMAdapter based on config and CLI override.

    - Loads .env into process environment (non-destructive for existing vars).
    - Instantiates the appropriate adapter and validates its environment.
    """
    # Make .env variables available
    _load_env_file_generic(project_root)

    provider, p_cfg = _effective_provider_and_config(cfg, provider_override)
    model = p_cfg.get("model")
    temperature = p_cfg.get("temperature")
    top_p = p_cfg.get("top_p")

    if provider == "openai":
        from .openai_adapter import OpenAIAdapter
        adapter: LLMAdapter = OpenAIAdapter(model=model, temperature=temperature, top_p=top_p)
    elif provider == "gemini":
        from .gemini_adapter import GeminiAdapter
        adapter = GeminiAdapter(model=model, temperature=temperature, top_p=top_p)
    elif provider == "dummy":
        from .dummy_adapter import DummyAdapter
        adapter = DummyAdapter(model=model, temperature=temperature, top_p=top_p)
    else:
        raise ValueError(f"Unknown LLM provider '{provider}'. Implement an adapter and register it in the factory.")

    # Environment validation (e.g., check required API keys)
    try:
        adapter.validate_environment()
    except LLMAuthError:
        # Surface clearer hint for commonly-used keys
        if provider == "openai":
            raise
        if provider == "gemini":
            raise
        raise
    return adapter


