from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


SUMMARY_OUTPUTS = ("append", "separate")
REFERENCE_HEADING_MODES = ("none", "title", "markdown")
REMOVED_SUMMARY_KEYS = (
    "summary_mode",
    "summary_output",
    "summary_heading",
    "long_summary_heading",
    "long_summary_lang",
    "append_summary",
)


@dataclass(frozen=True)
class ShortSummarySettings:
    enabled: bool
    heading: str
    output: str
    file_suffix: str


@dataclass(frozen=True)
class LongSummaryReferenceDisplaySettings:
    label: str
    heading: str
    timestamp: bool
    separator: str


@dataclass(frozen=True)
class LongSummaryReferenceSettings:
    enabled: bool
    display: LongSummaryReferenceDisplaySettings


@dataclass(frozen=True)
class LongSummarySettings:
    enabled: bool
    heading: str
    lang: str
    output: str
    file_suffix: str
    references: LongSummaryReferenceSettings


@dataclass(frozen=True)
class SummarySettings:
    short: ShortSummarySettings
    long: LongSummarySettings

    def enabled_types(self) -> tuple[str, ...]:
        return tuple(
            summary_type
            for summary_type, enabled in (
                ("long", self.long.enabled),
                ("short", self.short.enabled),
            )
            if enabled
        )


def _bool_value(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be true or false")
    return value


def _text_value(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _output_value(value: object, path: str) -> str:
    output = _text_value(value, path).lower()
    if output not in SUMMARY_OUTPUTS:
        raise ValueError(f"{path} must be one of: {', '.join(SUMMARY_OUTPUTS)}")
    return output


def _suffix_value(value: object, path: str) -> str:
    suffix = _text_value(value, path)
    if "/" in suffix or "\\" in suffix or suffix in (".", ".."):
        raise ValueError(f"{path} must be a filename suffix, not a path")
    return suffix


def _display_text_value(
    value: object,
    path: str,
    *,
    strip: bool,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    result = value.strip() if strip else value
    if any(token in result for token in ("\r", "\n", "|", "[", "]")):
        raise ValueError(
            f"{path} must not contain line breaks or wikilink delimiters"
        )
    return result


def resolve_summary_settings(
    cfg: dict,
    lecture_lang: str,
    *,
    cli_short_enabled: Optional[bool] = None,
    cli_long_enabled: Optional[bool] = None,
    cli_short_output: Optional[str] = None,
    cli_long_output: Optional[str] = None,
    cli_short_suffix: Optional[str] = None,
    cli_long_suffix: Optional[str] = None,
    cli_long_lang: Optional[str] = None,
    cli_long_references: Optional[bool] = None,
) -> SummarySettings:
    present_removed = [key for key in REMOVED_SUMMARY_KEYS if key in cfg]
    if present_removed:
        raise ValueError(
            "Removed summary configuration keys: "
            + ", ".join(present_removed)
            + "; migrate them under summary.short and summary.long"
        )

    summary_cfg = cfg.get("summary", {})
    if not isinstance(summary_cfg, dict):
        raise ValueError("summary must be a mapping")
    short_cfg = summary_cfg.get("short", {})
    long_cfg = summary_cfg.get("long", {})
    if not isinstance(short_cfg, dict):
        raise ValueError("summary.short must be a mapping")
    if not isinstance(long_cfg, dict):
        raise ValueError("summary.long must be a mapping")

    short_enabled = _bool_value(
        short_cfg.get("enabled", False), "summary.short.enabled"
    )
    long_enabled = _bool_value(
        long_cfg.get("enabled", False), "summary.long.enabled"
    )
    if cli_short_enabled is not None:
        short_enabled = cli_short_enabled
    if cli_long_enabled is not None:
        long_enabled = cli_long_enabled

    short_output = _output_value(
        cli_short_output or short_cfg.get("output", "append"),
        "summary.short.output",
    )
    long_output = _output_value(
        cli_long_output or long_cfg.get("output", "append"),
        "summary.long.output",
    )
    short_suffix = _suffix_value(
        (
            cli_short_suffix
            if cli_short_suffix is not None
            else short_cfg.get("file_suffix", "-summary")
        ),
        "summary.short.file_suffix",
    )
    long_suffix = _suffix_value(
        (
            cli_long_suffix
            if cli_long_suffix is not None
            else long_cfg.get("file_suffix", "-longsummary")
        ),
        "summary.long.file_suffix",
    )

    configured_long_lang = _text_value(
        long_cfg.get("lang", "default"), "summary.long.lang"
    ).lower()
    requested_long_lang = (cli_long_lang or configured_long_lang).strip().lower()
    long_lang = lecture_lang if requested_long_lang == "default" else requested_long_lang
    if not re.fullmatch(r"[a-z]{2}", long_lang):
        raise ValueError(
            "summary.long.lang must be 'default' or a two-letter ISO-639-1 code"
        )

    references_cfg = long_cfg.get("references", {})
    if not isinstance(references_cfg, dict):
        raise ValueError("summary.long.references must be a mapping")
    display_cfg = references_cfg.get("display", {})
    if not isinstance(display_cfg, dict):
        raise ValueError("summary.long.references.display must be a mapping")

    long_references_enabled = _bool_value(
        references_cfg.get("enabled", False),
        "summary.long.references.enabled",
    )
    if cli_long_references is not None:
        long_references_enabled = cli_long_references

    reference_label = _display_text_value(
        display_cfg.get("label", "🔗 Source"),
        "summary.long.references.display.label",
        strip=True,
    )
    reference_heading = _text_value(
        display_cfg.get("heading", "none"),
        "summary.long.references.display.heading",
    ).lower()
    if reference_heading not in REFERENCE_HEADING_MODES:
        raise ValueError(
            "summary.long.references.display.heading must be one of: "
            + ", ".join(REFERENCE_HEADING_MODES)
        )
    reference_timestamp = _bool_value(
        display_cfg.get("timestamp", True),
        "summary.long.references.display.timestamp",
    )
    reference_separator = _display_text_value(
        display_cfg.get("separator", " · "),
        "summary.long.references.display.separator",
        strip=False,
    )
    if not reference_label and reference_heading == "none":
        raise ValueError(
            "summary.long.references.display must include a label or heading"
        )

    settings = SummarySettings(
        short=ShortSummarySettings(
            enabled=short_enabled,
            heading=_text_value(
                short_cfg.get("heading", "## Summary (не авторський)"),
                "summary.short.heading",
            ),
            output=short_output,
            file_suffix=short_suffix,
        ),
        long=LongSummarySettings(
            enabled=long_enabled,
            heading=_text_value(
                long_cfg.get("heading", "## Long summary (не авторський)"),
                "summary.long.heading",
            ),
            lang=long_lang,
            output=long_output,
            file_suffix=long_suffix,
            references=LongSummaryReferenceSettings(
                enabled=long_references_enabled,
                display=LongSummaryReferenceDisplaySettings(
                    label=reference_label,
                    heading=reference_heading,
                    timestamp=reference_timestamp,
                    separator=reference_separator,
                ),
            ),
        ),
    )
    if (
        settings.short.enabled
        and settings.long.enabled
        and settings.short.output == "separate"
        and settings.long.output == "separate"
        and settings.short.file_suffix == settings.long.file_suffix
    ):
        raise ValueError(
            "summary.short.file_suffix and summary.long.file_suffix must differ "
            "when both summaries use separate output"
        )
    return settings


def validate_summary_reference_dependencies(
    settings: SummarySettings,
    *,
    include_src_block_ids: bool,
    include_txt_block_ids_for_untimed: bool,
) -> None:
    if not settings.long.references.enabled:
        return
    missing = []
    if not include_src_block_ids:
        missing.append("include_src_block_ids=true")
    if not include_txt_block_ids_for_untimed:
        missing.append("include_txt_block_ids_for_untimed=true")
    if missing:
        raise ValueError(
            "summary.long.references.enabled=true requires "
            + " and ".join(missing)
        )
