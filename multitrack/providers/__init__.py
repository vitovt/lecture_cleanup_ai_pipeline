from __future__ import annotations

from pathlib import Path

from .base import TranscriptionProvider
from .groq import GroqProvider


def create_provider(
    name: str,
    project_root: Path,
    *,
    config_path: Path | None = None,
    log_level: str = "info",
) -> TranscriptionProvider:
    normalized = name.strip().lower()
    if normalized == "groq":
        return GroqProvider(
            project_root,
            config_path=config_path,
            log_level=log_level,
        )
    raise ValueError(f"unsupported transcription provider: {name}")


__all__ = ["TranscriptionProvider", "create_provider"]
