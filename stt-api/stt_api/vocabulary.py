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
    result: list[str] = []
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("```") or value.startswith("~~~"):
            continue
        result.append(value)
    return result


def merge_vocabulary(
    config_terms: Iterable[str],
    config_files: Iterable[str],
    cli_terms: Iterable[str],
    cli_files: Iterable[str],
    *,
    config_base_dir: Path,
    cli_base_dir: Path,
    limit: int,
) -> list[str]:
    candidates = [str(term).strip() for term in config_terms]
    for raw in config_files:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = config_base_dir / path
        candidates.extend(_file_terms(path))
    for raw in cli_files:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = cli_base_dir / path
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


def validate_elevenlabs_keyterms(terms: Iterable[str]) -> None:
    unsupported = set("<>{}[]\\")
    for term in terms:
        if len(term) >= 50:
            raise InputError(
                f"ElevenLabs keyterm must be shorter than 50 characters: {term!r}"
            )
        if len(term.split()) > 5:
            raise InputError(
                f"ElevenLabs keyterm must contain at most 5 words: {term!r}"
            )
        invalid = sorted(set(term) & unsupported)
        if invalid:
            rendered = "".join(invalid)
            raise InputError(
                f"ElevenLabs keyterm contains unsupported character(s) {rendered!r}: {term!r}"
            )
