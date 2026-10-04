"""Configuration used only when adding summaries to existing Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from string import Formatter

from scripts.config_loader import deep_merge
from scripts.summary_settings import resolve_summary_settings


def specified(value):
    """A null override means inherit; false and other explicit values survive."""
    if isinstance(value, dict):
        return {key: specified(child) for key, child in value.items() if child is not None}
    return value


def boolean(value, name):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def choice(value, options, name):
    if value not in options:
        raise ValueError(f"{name} must be one of: {', '.join(options)}")
    return value


def mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


@dataclass(frozen=True)
class RegenerationPolicy:
    on_existing: str
    legacy_enabled: bool
    legacy_words: tuple[str, ...]
    legacy_case_sensitive: bool
    comments: str
    missing_ids: str
    backups: bool
    backup_filename: str
    directory: str | None
    max_source_chars: int | None


def regeneration_config(cfg: dict, args) -> tuple[dict, RegenerationPolicy]:
    tool = specified(mapping(cfg.get("summary_regeneration", {}), "summary_regeneration"))
    unknown = set(tool) - {
        "short", "long", "llm", "retry", "on_existing", "legacy", "source",
        "references", "backups", "external", "max_source_chars",
    }
    if unknown:
        raise ValueError(f"Unknown summary_regeneration settings: {', '.join(sorted(unknown))}")
    effective = deep_merge(cfg, {
        "summary": {
            kind: mapping(tool.get(kind, {}), f"summary_regeneration.{kind}")
            for kind in ("short", "long")
        },
        "llm": mapping(tool.get("llm", {}), "summary_regeneration.llm"),
        "retry": mapping(tool.get("retry", {}), "summary_regeneration.retry"),
    })
    legacy = mapping(tool.get("legacy", {}), "summary_regeneration.legacy")
    source = mapping(tool.get("source", {}), "summary_regeneration.source")
    references = mapping(tool.get("references", {}), "summary_regeneration.references")
    backups = mapping(tool.get("backups", {}), "summary_regeneration.backups")
    external = mapping(tool.get("external", {}), "summary_regeneration.external")
    words = args.legacy_summary_keyword
    if words is None:
        words = legacy.get("heading_words", [])
    if not isinstance(words, list) or any(not isinstance(word, str) or not word.strip() for word in words):
        raise ValueError("summary_regeneration.legacy.heading_words must be a list of non-empty strings")
    pattern = args.backup_filename or backups.get("filename", "{stem}-{datetime}-bak.md")
    if not isinstance(pattern, str) or not pattern or "/" in pattern or "\\" in pattern:
        raise ValueError("summary_regeneration.backups.filename must be a filename template without directories")
    for _, field, format_spec, conversion in Formatter().parse(pattern):
        if field is not None and (field not in {"stem", "name", "datetime"} or format_spec or conversion):
            raise ValueError("Backup filename supports only {stem}, {name}, and {datetime}")
    directory = args.outdir if args.outdir is not None else external.get("directory")
    if directory is not None and (not isinstance(directory, str) or not directory.strip()):
        raise ValueError("summary_regeneration.external.directory must be null or a non-empty path")
    maximum = tool.get("max_source_chars")
    if maximum is not None and (type(maximum) is not int or maximum <= 0):
        raise ValueError("summary_regeneration.max_source_chars must be null or a positive integer")
    return effective, RegenerationPolicy(
        on_existing=choice(args.on_existing or tool.get("on_existing", "skip"),
                           ("skip", "replace", "add", "error"), "on_existing"),
        legacy_enabled=boolean(args.legacy_detection if args.legacy_detection is not None else legacy.get("enabled", True), "legacy.enabled"),
        legacy_words=tuple(word.strip() for word in words),
        legacy_case_sensitive=boolean(args.legacy_case_sensitive if args.legacy_case_sensitive is not None else legacy.get("case_sensitive", False), "legacy.case_sensitive"),
        comments=choice(args.comments or source.get("comments", "service"), ("service", "all", "keep"), "source.comments"),
        missing_ids=choice(args.missing_ids or references.get("missing_ids", "add"), ("error", "omit", "add"), "references.missing_ids"),
        backups=boolean(args.backup if args.backup is not None else backups.get("enabled", True), "backups.enabled"),
        backup_filename=pattern, directory=directory, max_source_chars=maximum,
    )


def requested_settings(cfg, args, *, inspection=False):
    summary = mapping(cfg.get("summary", {}), "summary")
    overrides = {}
    for kind in ("short", "long"):
        options = dict(mapping(summary.get(kind, {}), f"summary.{kind}"))
        if args.type:
            options["enabled"] = args.type in (kind, "both")
        language = getattr(args, f"{kind}_lang") or args.lang
        if language:
            options["lang"] = language.lower()
        configured_language = options.get("lang", "default")
        is_default = isinstance(configured_language, str) and configured_language.strip().lower() == "default"
        if not inspection and options.get("enabled", False) and is_default:
            raise ValueError(f"{kind} summary language is default; pass an explicit --lang (frontmatter is not used)")
        if args.output:
            options["output"] = args.output
        overrides[kind] = options
    if args.references is not None:
        overrides["long"]["references"] = deep_merge(
            overrides["long"].get("references", {}), {"enabled": args.references},
        )
    result = resolve_summary_settings(deep_merge(cfg, {"summary": overrides}), args.lang or "zz")
    for kind in result.enabled_types():
        heading = getattr(result, kind).heading
        if any(token in heading for token in ("\n", "\r", "LECTURE_CLEANUP_")):
            raise ValueError(f"{kind} summary heading must fit on one line without reserved document markers")
    if not inspection and not result.enabled_types():
        raise ValueError("No summary types are enabled; configure enabled or pass --type short|long|both")
    return result
