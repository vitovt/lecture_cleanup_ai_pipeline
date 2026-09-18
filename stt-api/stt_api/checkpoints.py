from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def fingerprint(path: Path, settings: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    digest.update(json.dumps(settings, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


class CheckpointStore:
    def __init__(self, directory: Path, enabled: bool) -> None:
        self.directory = directory
        self.enabled = enabled
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)

    def read(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.directory / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def write(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self.directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
