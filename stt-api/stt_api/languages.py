from __future__ import annotations

import re

from .errors import InputError


ALIASES = {
    "uk": "uk-UA",
    "uk-ua": "uk-UA",
    "de": "de-DE",
    "de-de": "de-DE",
    "en": "en-US",
    "en-us": "en-US",
    "en-gb": "en-GB",
    "ru": "ru-RU",
    "ru-ru": "ru-RU",
}
BCP47_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4}){0,2}$")


def normalize_language(value: str, *, allow_auto: bool = False) -> str:
    raw = value.strip()
    if allow_auto and raw.lower() == "auto":
        return "auto"
    if not raw:
        raise InputError("language code cannot be empty")
    alias = ALIASES.get(raw.lower())
    if alias:
        return alias
    if not BCP47_RE.fullmatch(raw):
        raise InputError(
            f"invalid language code '{value}'; use a supported BCP-47 code "
            "such as uk-UA or a shortcut: uk, de, en, ru"
        )
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.upper() if len(part) == 2 else part.title())
    return "-".join(normalized)


def normalize_languages(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = normalize_language(value, allow_auto=True)
        if normalized == "auto":
            if len(values) != 1:
                raise InputError("'auto' cannot be combined with explicit language codes")
            return []
        if normalized not in result:
            result.append(normalized)
    return result
