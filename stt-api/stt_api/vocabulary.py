from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .errors import InputError


def _file_terms(path: Path) -> list[str]:
    if not path.is_file():
        raise InputError(f"custom vocabulary file not found: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InputError(f"custom vocabulary file is not UTF-8: {path}") from exc
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def merge_vocabulary(
    config_terms: Iterable[str],
    config_files: Iterable[str],
    cli_terms: Iterable[str],
    cli_files: Iterable[str],
    *,
    base_dir: Path,
    limit: int,
) -> list[str]:
    candidates = [str(term).strip() for term in config_terms]
    for raw in [*config_files, *cli_files]:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        candidates.extend(_file_terms(path))
    candidates.extend(str(term).strip() for term in cli_terms)

    result: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        if not term or term.startswith("#"):
            continue
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            result.append(term)
    if len(result) > limit:
        raise InputError(
            f"merged custom vocabulary has {len(result)} entries; provider limit is {limit}"
        )
    return result
