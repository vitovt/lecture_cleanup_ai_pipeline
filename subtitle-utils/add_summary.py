#!/usr/bin/env python3
"""Generate additional summaries from an existing Markdown source."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.config_loader import load_effective_config
from scripts.logging_helper import set_log_level
from scripts.summary_document import SummaryError, prepare_source, read_markdown
from scripts.summary_regeneration import (
    digest, external_inventory, generate_actions, plan_actions,
    prepare_references, print_diffs, render_updates, report_source, warning,
)
from scripts.summary_regeneration_config import regeneration_config, requested_settings
from scripts.summary_storage import backup_paths, publish, snapshot


def parser():
    result = argparse.ArgumentParser(
        description="Add or regenerate short/long summaries of a Markdown source.",
        epilog=(
            "Defaults: config.default.yaml + config.yaml; summary_regeneration "
            "overrides summary only for this tool. append updates FILE.md; "
            "separate writes beside it or under --outdir. Existing summaries "
            "are skipped by default. --dry-run, --print-source, and --list "
            "never call an LLM or write files. --diff calls the LLM but does "
            "not write files. A default summary language requires --lang; "
            "frontmatter is never used to choose the language."
        ),
    )
    result.add_argument("filename", type=Path, metavar="FILE.md")
    result.add_argument("--type", choices=("short", "long", "both"), help="override which summary types are enabled")
    result.add_argument("--lang", help="explicit summary language for both selected types (ISO-639-1)")
    result.add_argument("--short-lang", help="override short summary language")
    result.add_argument("--long-lang", help="override long summary language")
    result.add_argument("--output", choices=("append", "separate"), help="override the output mode for both types")
    result.add_argument("--outdir", help="external summary directory; relative to your working directory")
    result.add_argument("--on-existing", choices=("skip", "replace", "add", "error"), help="retain, replace, duplicate, or reject existing summaries")
    result.add_argument("--target", metavar="ID|all", help="replacement selector from --list; all preserves each existing language")
    result.add_argument("--replace-legacy-tail", action="store_true", help="replace the entire unmarked tail from the first matching legacy heading")
    detection = result.add_mutually_exclusive_group()
    detection.add_argument("--legacy-summary-detection", dest="legacy_detection", action="store_true", help="stop source at a matching unmarked heading")
    detection.add_argument("--no-legacy-summary-detection", dest="legacy_detection", action="store_false", help="disable legacy heading cutoff")
    result.add_argument("--legacy-summary-keyword", action="append", help="replace configured heading words; repeat to supply several words")
    sensitivity = result.add_mutually_exclusive_group()
    sensitivity.add_argument("--legacy-case-sensitive", dest="legacy_case_sensitive", action="store_true")
    sensitivity.add_argument("--legacy-ignore-case", dest="legacy_case_sensitive", action="store_false")
    result.add_argument("--comments", choices=("service", "all", "keep"), help="HTML comment filtering for source only")
    result.add_argument("--missing-ids", choices=("error", "omit", "add"), help="handle missing source IDs when long references are enabled; add modifies source after successful generation")
    references = result.add_mutually_exclusive_group()
    references.add_argument("--long-summary-references", dest="references", action="store_true")
    references.add_argument("--no-long-summary-references", dest="references", action="store_false")
    backups = result.add_mutually_exclusive_group()
    backups.add_argument("--backup", dest="backup", action="store_true", help="back up every existing file that will be changed")
    backups.add_argument("--no-backup", dest="backup", action="store_false")
    result.add_argument("--backup-filename", help="backup template using {stem}, {name}, {datetime}")
    inspection = result.add_mutually_exclusive_group()
    inspection.add_argument("--dry-run", action="store_true", help="report source ranges, exclusions, conflicts, writes and backups without LLM calls")
    inspection.add_argument("--print-source", action="store_true", help="print filtered source, including planned IDs, without LLM calls")
    inspection.add_argument("--list", action="store_true", help="list local internal/external summary IDs without generation")
    inspection.add_argument("--diff", action="store_true", help="generate summaries and print diffs without writing or backing up files")
    result.add_argument("--config", type=Path, help="use this local YAML override instead of the project's config.yaml")
    result.add_argument("--llm-provider", help="override LLM provider")
    result.add_argument("--model", help="override the selected provider's model")
    result.add_argument("--request-delay", type=float, help="delay before each LLM request in seconds")
    result.add_argument("--retry-attempts", type=int, help="total attempts per request, including validation failures")
    result.add_argument("--debug", action="store_true")
    result.add_argument("--trace", action="store_true", help="log full prompts and responses")
    result.set_defaults(legacy_detection=None, legacy_case_sensitive=None, references=None, backup=None)
    return result


def run(args):
    if args.config is not None and not args.config.is_file():
        raise SummaryError("invalid_config", f"Config file does not exist: {args.config}")
    cfg, _ = load_effective_config(PROJECT_ROOT, local_name=str(args.config.resolve()) if args.config else "config.yaml")
    cfg, policy = regeneration_config(cfg, args)
    set_log_level("trace" if args.trace else "debug" if args.debug else cfg.get("logging", {}).get("level", "info"))
    path = args.filename.expanduser().resolve()
    original = read_markdown(path)
    document = prepare_source(path, original, policy)
    try:
        settings = requested_settings(cfg, args, inspection=args.list or args.print_source)
        directory = Path(os.path.expandvars(policy.directory)).expanduser().resolve() if policy.directory is not None else path.parent
        external, texts = external_inventory(path, settings, directory)
        all_blocks = document.blocks + external
        ids = [block.metadata["id"] for block in all_blocks if "id" in block.metadata]
        if len(ids) != len(set(ids)):
            raise SummaryError("duplicate_summary_id", "Summary metadata IDs are duplicated across associated files")
        if args.list:
            for block in all_blocks:
                print(f"SUMMARY id={block.identifier!r} type={block.kind} lang={block.language or 'unknown'} file={str(block.path)!r} lines={block.start + 1}-{block.end}")
            if document.legacy_start is not None:
                print(f"SUMMARY id=legacy-tail type=unknown lang=unknown file={str(path)!r} line={document.legacy_start + 1}")
            return 0
        if args.print_source:
            # Source inspection is independent of output conflicts and language.
            from scripts.summary_regeneration import Action
            pretend = [Action(kind, getattr(settings, kind).lang, path, "append") for kind in settings.enabled_types()]
            document, _, _ = prepare_references(document, settings, policy, pretend)
            sys.stdout.write(document.source)
            return 0
        actions = plan_actions(document, settings, policy, args, directory, all_blocks)
        active = [action for action in actions if action.operation != "skip"]
        if active and not document.source.strip().lstrip("\ufeff"):
            raise SummaryError("empty_source", "No source remains after excluding summaries, metadata and comments")
        document, settings, ids_added = prepare_references(document, settings, policy, actions)
        if active and policy.max_source_chars is not None and len(document.source) > policy.max_source_chars:
            raise SummaryError("source_too_large", f"Source has {len(document.source)} characters, limit is {policy.max_source_chars}; source is never truncated")
        originals = {path: original.encode("utf-8")}
        affected = {action.path for action in active}
        if ids_added:
            affected.add(path)
        for output in affected:
            if output != path:
                # Guard the exact content used by the planner/renderer. A file
                # created or edited since inventory must not become our baseline.
                originals[output] = texts[output].encode("utf-8") if output in texts else None
                if snapshot(output) != originals[output]:
                    raise SummaryError("file_changed", f"File changed after inventory: {output}")
        backups = backup_paths(affected, policy)
    except (ValueError, OSError):
        if args.dry_run:
            report_source(document)
        raise
    if args.dry_run:
        report_source(document)
        if ids_added:
            print(f"SOURCE_EDIT action=add_ids count={ids_added} file={str(path)!r}")
        for action in actions:
            print(f"PLAN type={action.kind} lang={action.language} action={action.operation} file={str(action.path)!r}" + (f" target={action.target.identifier!r}" if action.target else ""))
        for output, backup in backups.items():
            print(f"BACKUP source={str(output)!r} file={str(backup)!r}")
        print("DRY_RUN llm_requests=0 writes=0")
        return 0
    if not active:
        print("SUMMARY status=skipped llm_requests=0 writes=0")
        return 0
    for block in all_blocks:
        if block.metadata.get("source_hash") and block.metadata["source_hash"] != digest(document.source):
            warning("stale_summary", f"Summary {block.identifier} was generated from different source text")
    generate_actions(actions, document, settings, cfg, args)
    updates = render_updates(actions, document, texts, args)
    if ids_added and path not in updates:
        updates[path] = document.original
    if args.diff:
        print_diffs(updates, originals)
    else:
        publish(updates, originals, backups)
        for output in sorted(updates):
            print(f"WRITE file={str(output)!r}")
        for backup in backups.values():
            print(f"BACKUP file={str(backup)!r}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arguments = parser()
    if not argv:
        arguments.print_help()
        return 0
    args = arguments.parse_args(argv)
    try:
        return run(args)
    except SummaryError as exc:
        print(f"ERROR code={exc.code} {exc}", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError) as exc:
        print(f"ERROR code=invalid_configuration {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR code=generation_or_write_failed {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
