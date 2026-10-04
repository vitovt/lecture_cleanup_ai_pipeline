"""Plan and apply summary updates to an existing Markdown document."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import sys
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from aiadapters.factory import create_llm_adapter
from scripts.heading_references import HeadingReferenceOptions, render_heading_references
from scripts.source_timecode_core import HEADING_RE, protected_line_mask, strip_trailing_block_ids
from scripts.summary_document import SummaryBlock, SummaryError, inventory, prepare_source, read_markdown
from scripts.summary_generation import _load_summary_prompt, _summary_block, generate_summaries, generation_options
from scripts.summary_references import SummaryReferenceError, collect_source_blocks


def warning(code, message):
    print(f"WARNING code={code} {message}", file=sys.stderr)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Action:
    kind: str
    language: str
    path: Path
    operation: str
    target: SummaryBlock | None = None
    body: str = ""


def external_inventory(source_path, settings, directory):
    """Discover associated files locally; never search an entire vault/disk."""
    blocks = []
    texts = {}
    for folder in dict.fromkeys((source_path.parent, directory)):
        if not folder.exists():
            continue
        if not folder.is_dir():
            raise SummaryError("invalid_output", f"Output directory is not a directory: {folder}")
        for path in sorted(folder.iterdir()):
            if path == source_path or path.suffix.lower() != ".md":
                continue
            expected_kind = None
            for kind in ("short", "long"):
                base = source_path.stem + getattr(settings, kind).file_suffix
                if re.fullmatch(re.escape(base) + r"(?:\.[a-z]{2})?(?:\.\d+)?\.md", path.name):
                    expected_kind = kind
                    break
            if expected_kind is None:
                continue
            text = read_markdown(path)
            found = inventory(path, text)
            if not found:
                # An occupied unmarked filename is not assumed to be ours.
                continue
            if any(block.metadata.get("source") not in (None, str(source_path)) for block in found):
                continue
            if any(block.kind != expected_kind for block in found):
                raise SummaryError("foreign_output", f"Unexpected summary type in {path}")
            blocks.extend(found)
            texts[path] = text
    return blocks, texts


def plan_actions(document, settings, policy, args, directory, all_blocks):
    actions = []
    occupied = {block.path for block in all_blocks}
    reserved = {document.path}
    if args.target and policy.on_existing != "replace":
        raise SummaryError("invalid_target", "--target requires --on-existing replace")
    if args.replace_legacy_tail:
        if document.legacy_start is None:
            raise SummaryError("legacy_tail_not_found", "No legacy summary heading found; inspect --dry-run")
        if args.target:
            raise SummaryError("invalid_target", "--target cannot be combined with --replace-legacy-tail")
        if any(getattr(settings, kind).output != "append" for kind in settings.enabled_types()):
            raise SummaryError("invalid_output", "--replace-legacy-tail requires append output for all selected types")
    target_found = False
    for kind in settings.enabled_types():
        config = getattr(settings, kind)
        internal = config.output == "append"
        candidates = [block for block in all_blocks if block.kind == kind and (
            block.path == document.path if internal else block.path != document.path and block.path.parent == directory
        )]
        matching = [block for block in candidates if block.language in (None, config.lang)]
        if args.target:
            matching = [block for block in candidates if args.target == "all" or block.identifier == args.target]
            target_found |= bool(matching)
        if any(block.language is None for block in matching):
            warning("unknown_existing_language", f"{kind}: existing summary language is not recorded")
        if any(block.kind == kind and block not in candidates for block in all_blocks):
            warning("summary_elsewhere", f"{kind}: summary exists in a different output location")
        if args.replace_legacy_tail:
            actions.append(Action(kind, config.lang, document.path, "replace_legacy_tail"))
            continue
        legacy_conflict = internal and document.legacy_start is not None and not matching and not args.target
        if legacy_conflict and policy.on_existing in ("replace", "error"):
            raise SummaryError("unclassified_legacy_summary", "Use --replace-legacy-tail to replace the unmarked tail, or --on-existing add to keep it")
        if matching or legacy_conflict:
            if policy.on_existing == "error":
                raise SummaryError("summary_exists", f"{kind}/{config.lang} already exists; choose skip, replace, or add")
            if policy.on_existing == "skip":
                path = document.path if internal else matching[0].path
                actions.append(Action(kind, config.lang, path, "skip"))
                warning("summary_skipped", f"{kind}/{config.lang}: existing summary retained")
                continue
            if policy.on_existing == "replace":
                if len(matching) > 1 and args.target != "all":
                    raise SummaryError("ambiguous_summary", f"Multiple {kind} summaries; choose --target ID or --target all")
                for block in matching:
                    language = block.language if args.target and not (args.lang or getattr(args, f"{kind}_lang")) else config.lang
                    actions.append(Action(kind, language or config.lang, block.path, "replace", block))
                continue
            warning("duplicate_summary", f"Adding another {kind}/{config.lang} summary as explicitly requested")
        if args.target:
            continue
        if internal:
            path = document.path
            operation = "append"
        else:
            stem = document.path.stem + config.file_suffix
            path = directory / f"{stem}.md"
            if path.exists() or path in reserved:
                if path.exists() and path not in occupied and policy.on_existing != "add":
                    raise SummaryError("foreign_output", f"Unassociated output file exists: {path}; choose another directory or --on-existing add")
                path = directory / f"{stem}.{config.lang}.md"
            if path.exists() or path in reserved:
                if policy.on_existing != "add":
                    raise SummaryError("output_collision", f"Output filename is occupied: {path}")
                number = 2
                while path.exists() or path in reserved:
                    path = directory / f"{stem}.{config.lang}.{number}.md"
                    number += 1
            reserved.add(path)
            operation = "create"
        actions.append(Action(kind, config.lang, path, operation))
    if args.target and not target_found:
        raise SummaryError("target_not_found", f"No selected summary matches target {args.target!r}")
    return actions


def prepare_references(document, settings, policy, actions):
    original = document.original
    active = [action for action in actions if action.operation != "skip"]
    if not settings.long.references.enabled or not any(action.kind == "long" for action in active):
        return document, settings, 0
    try:
        source_blocks = collect_source_blocks(document.source)
    except SummaryReferenceError as exc:
        raise SummaryError("invalid_source_ids", str(exc)) from exc
    lines = document.source.splitlines(keepends=True)
    protected = protected_line_mask(lines, protect_summaries=False)
    missing = 0
    for index, line in enumerate(lines):
        heading = HEADING_RE.match(line)
        if heading and not protected[index] and not strip_trailing_block_ids(heading.group("body"))[1]:
            missing += 1
    if not missing and source_blocks:
        return document, settings, 0
    if not missing and not source_blocks:
        if policy.missing_ids != "omit":
            raise SummaryError("missing_source_ids", "Source has no identifiable headings; add headings or disable references")
    if policy.missing_ids == "error":
        raise SummaryError("missing_source_ids", f"{missing} source heading(s) have no IDs; choose --missing-ids add or omit")
    if policy.missing_ids == "omit":
        warning("references_omitted", f"{missing} heading(s) lack IDs; generating long summary without references")
        settings = replace(settings, long=replace(settings.long, references=replace(settings.long.references, enabled=False)))
        return document, settings, 0
    rendered = render_heading_references(document.source, HeadingReferenceOptions(
        include_src=True, include_txt_for_untimed=True, only_add_ids=True,
    )).markdown
    new_lines = rendered.splitlines(keepends=True)
    if len(new_lines) != len(lines):
        raise SummaryError("invalid_source_edit", "ID renderer unexpectedly changed the source line count")
    original_lines = original.splitlines(keepends=True)
    changed = 0
    for index, (before, after) in enumerate(zip(lines, new_lines)):
        if before == after:
            continue
        heading = HEADING_RE.match(after)
        _, identifiers = strip_trailing_block_ids(heading.group("body"))
        original_index = document.line_map[index]
        line = original_lines[original_index]
        body = line.rstrip("\r\n")
        original_lines[original_index] = body + " " + identifiers[-1].raw + line[len(body):]
        changed += 1
    updated = prepare_source(document.path, "".join(original_lines), policy)
    collect_source_blocks(updated.source)
    return updated, settings, changed


def report_source(document):
    ranges = []
    for index in document.line_map:
        if ranges and ranges[-1][1] == index:
            ranges[-1] = (ranges[-1][0], index + 1)
        else:
            ranges.append((index, index + 1))
    spans = ",".join(f"{start + 1}-{end}" for start, end in ranges) or "none"
    print(f"SOURCE lines={spans} chars={len(document.source)} comments_removed={document.comments_removed}")
    grouped = {}
    for start, end, reason in document.omitted:
        grouped.setdefault(reason, []).append(f"{start + 1}-{end}")
    for reason, omitted_ranges in grouped.items():
        shown = ",".join(omitted_ranges[:6])
        if len(omitted_ranges) > 6:
            shown += ",…"
        print(f"OMIT reason={reason!r} lines={shown} count={len(omitted_ranges)}")
    if document.legacy_start is not None:
        title = document.original.splitlines()[document.legacy_start].strip()
        print(f"LEGACY heading={title!r} line={document.legacy_start + 1}")


def generate_actions(actions, document, settings, cfg, args):
    options = generation_options(
        cfg, provider_override=args.llm_provider, model_override=args.model,
        request_delay_override=args.request_delay, retry_attempts_override=args.retry_attempts,
    )
    provider, model = options["provider"], options["model"]
    cfg = {**cfg, "llm": {**cfg["llm"], provider: {**cfg["llm"][provider], "model": model}}}
    adapter = create_llm_adapter(cfg, provider_override=provider, project_root=Path(__file__).resolve().parents[1])
    pending = [action for action in actions if action.operation != "skip"]
    while pending:
        group = [pending.pop(0)]
        partner = next((action for action in pending if action.kind != group[0].kind), None)
        if partner is not None:
            pending.remove(partner)
            group.append(partner)
        enabled = {action.kind: action for action in group}
        requested = replace(
            settings,
            short=replace(settings.short, enabled="short" in enabled, lang=enabled["short"].language if "short" in enabled else settings.short.lang),
            long=replace(settings.long, enabled="long" in enabled, lang=enabled["long"].language if "long" in enabled else settings.long.lang),
        )
        long = enabled.get("long")
        note = "SOURCE" if long and long.path != document.path else ""
        target = os.path.relpath(document.path, long.path.parent).replace(os.sep, "/") if note else None
        summaries = generate_summaries(
            adapter, model, document.source, requested,
            temperature=options["temperature"], top_p=options["top_p"],
            attempts=options["attempts"], pause_seconds=options["pause_seconds"],
            request_delay=options["request_delay"], source_note=note, reference_target=target,
            debug=args.debug, trace=args.trace,
        )
        for action in group:
            prompt = _load_summary_prompt(action.kind, action.language, note + "#" if action.kind == "long" and settings.long.references.enabled else None)
            metadata = {
                "version": 1, "id": action.target.metadata.get("id") if action.target else None,
                "lang": action.language, "source": str(document.path),
                "source_hash": digest(document.source), "prompt_hash": digest("\n".join(prompt)),
                "provider": provider, "model": model,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            metadata["id"] = metadata["id"] or uuid.uuid4().hex
            action.body = _summary_block(action.kind, summaries[action.kind], getattr(settings, action.kind).heading, metadata=metadata)


def render_updates(actions, document, texts, args):
    updates = {}
    paths = {action.path for action in actions if action.operation != "skip"}
    for path in paths:
        original = document.original if path == document.path else texts.get(path, "")
        lines = original.splitlines(keepends=True)
        newline = "\r\n" if "\r\n" in original else "\n"
        chosen = [action for action in actions if action.path == path and action.operation != "skip"]
        # Descending line order preserves the offsets of every other block.
        for action in sorted((action for action in chosen if action.target), key=lambda action: action.target.start, reverse=True):
            block = action.body.replace("\n", newline) + newline
            lines[action.target.start:action.target.end] = [block]
        if args.replace_legacy_tail and path == document.path:
            lines = original.splitlines(keepends=True)[:document.legacy_start]
        result = "".join(lines)
        additions = [action.body.replace("\n", newline) for action in chosen if action.target is None]
        if additions:
            separator = "" if not result else (newline if result.endswith(newline) else newline * 2)
            result += separator + (newline * 2).join(additions) + newline
        updates[path] = result
    return updates


def print_diffs(updates, originals):
    for path in sorted(updates):
        before = originals[path].decode("utf-8") if originals[path] is not None else ""
        print("".join(difflib.unified_diff(
            before.splitlines(keepends=True), updates[path].splitlines(keepends=True),
            fromfile=str(path), tofile=str(path) + ".generated", n=3,
        )), end="")
