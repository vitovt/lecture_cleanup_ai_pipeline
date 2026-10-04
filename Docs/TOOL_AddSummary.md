# Add or regenerate summaries

`StartMe.sh add-summary` generates short and long summaries from an existing
Markdown file using the same prompts, adapters, retries and reference validation
as `run_pipeline.py`. Run it from any directory; input, `--config`, and external
output paths are relative to the invocation directory.

```bash
./StartMe.sh help add-summary
./StartMe.sh add-summary ./lecture.md --type both --lang uk --dry-run
./StartMe.sh add-summary ./lecture.md --type both --lang uk
```

The direct entry points are `subtitle-utils/add_summary.sh` (uses the project
virtual environment) and `subtitle-utils/add_summary.py` (uses your Python).
The input must be an existing UTF-8 `.md` file. Defaults come from
`config.default.yaml` merged with `config.yaml`; `--config FILE.yaml` replaces
the local override file, while retaining the tracked defaults.

## Common operations

```bash
# Fill missing summaries; existing matches are skipped by default.
./StartMe.sh add-summary ./lecture.md --type both --lang uk

# Add an English long summary alongside a Ukrainian one.
./StartMe.sh add-summary ./lecture.md --type long --lang en

# Deliberately add another summary of the same type and language.
./StartMe.sh add-summary ./lecture.md --type long --lang uk --on-existing add

# Create external files in another directory.
./StartMe.sh add-summary ./lecture.md --type both --lang uk \
  --output separate --outdir "$HOME/Desktop/obsidian/summaries"

# Regenerate a unique matching summary using a different model.
./StartMe.sh add-summary ./lecture.md --type long --lang uk \
  --on-existing replace --model MODEL_NAME

# List identifiers and replace one of several matches.
./StartMe.sh add-summary ./lecture.md --list
./StartMe.sh add-summary ./lecture.md --type long --lang uk \
  --on-existing replace --target SUMMARY_ID

# Replace all selected types, retaining each existing block's language.
# --lang is required here if the configured language is default.
./StartMe.sh add-summary ./lecture.md --type both \
  --on-existing replace --target all
```

`--type short|long|both` overrides configured `enabled` flags. Without it, the
enabled flags determine which types are requested. Tracked defaults disable
both types. `--lang`, `--short-lang`, and `--long-lang` accept two-letter language
codes; the type-specific option wins over `--lang`.

With configured `lang: default`, generation requires an explicit language
option. Neither frontmatter nor the global `language` setting chooses it.
For `--target all` or a specific ID, stored block languages are preserved unless
you explicitly pass a language option. Old blocks without language metadata
use the resolved requested language.

`--output append` updates the source Markdown; `separate` writes external files.
The first external filenames use the configured `file_suffix`, typically
`lecture-summary.md` and `lecture-longsummary.md`. Further languages and
duplicates use names such as `lecture-longsummary.en.md` and
`lecture-longsummary.en.2.md`. Discovery looks only in the source directory and
the selected output directory, using the current suffixes. Files belonging to
another source are not overwritten. External references use relative paths
back to the source.

## Conflicts and identifiers

Matches are determined by type, language and output location. A summary in
another location produces a warning. Old tagged summaries without language
metadata conservatively match any requested language.

| `--on-existing` | Result when a matching summary exists |
| --- | --- |
| `skip` (default) | Keep matches; generate only missing types. If all skip, no LLM call or backup. |
| `error` | Report the conflict before calling the LLM. |
| `replace` | Replace a unique match in place. Multiple matches require `--target ID` or `--target all`. |
| `add` | Append another internal block or create another external file, with a duplicate warning. |

There is no limit on duplicate types or languages. New blocks retain the
existing `LECTURE_CLEANUP_*_SUMMARY_START/END` tags and add a separate JSON
metadata comment with a unique ID, language, source path/hash, prompt hash,
provider, model and creation time. Replacements keep the ID. `--list` shows
stored IDs and synthetic selectors for older blocks without metadata.
Malformed/nested tags and duplicate metadata IDs are errors; the utility does
not guess how to repair them.

## Source filtering and older files

All tagged summaries are excluded from source, regardless of requested type,
language or conflict policy. YAML frontmatter is excluded without changing it.
By default, known diagnostic/edit HTML comments are excluded, including
`filler_removed`, `rephrased`, `unsure`, `unsures`, `STARTING`, `END`, and
provider/model processing metadata. Diagnostic-only fenced blocks are also
excluded; meaningful code and comment examples inside it remain source.
These exclusions do not delete the original comments.

Legacy detection defaults to the configured word `summary`, ignoring case.
At the first matching ATX or Setext heading outside code, the entire tail from
that heading to EOF is excluded. Matching uses literal whole words/phrases.
Inspect this cutoff before processing older files:

```bash
./StartMe.sh add-summary ./old.md --type both --lang uk --dry-run
./StartMe.sh add-summary ./old.md --print-source

# Keep the legacy tail and append new tagged summaries.
./StartMe.sh add-summary ./old.md --type both --lang uk --on-existing add

# Explicitly replace the WHOLE legacy tail, including anything after it.
./StartMe.sh add-summary ./old.md --type both --lang uk --replace-legacy-tail

# Override the heading words for this call.
./StartMe.sh add-summary ./old.md --type both --lang uk \
  --legacy-summary-keyword summary --legacy-summary-keyword підсумок --dry-run
```

An unclassified legacy tail causes internal `skip` to retain the old summaries;
`replace` and `error` require an explicit decision. `--replace-legacy-tail`
requires append output and an actual detected legacy heading. External
generation still works from the source preceding the legacy tail.
`--no-legacy-summary-detection` disables the cutoff; unmarked old summary text
then becomes part of the source. Tagged summaries remain excluded.
`--legacy-case-sensitive` / `--legacy-ignore-case` override case matching.
`--comments service|all|keep` controls HTML comment filtering.

## Long summary references

When long references are enabled, existing source IDs are validated. Missing
heading IDs are handled using `references.missing_ids` or `--missing-ids`:

| Policy | Behavior |
| --- | --- |
| `add` (default) | Use the shared heading renderer to add missing `^src-*` / `^txt-*` IDs, preserving existing IDs and timestamps. |
| `omit` | Warn and generate this long summary without references. |
| `error` | Fail before any LLM call. |

With `add`, IDs are saved to the original source only after **all** requested
generation succeeds. This may change the source even with external output;
the source is backed up by default. Pipeline ID-generation flags do not apply
to this tool. Duplicate source IDs are errors. A source without any recognized
ATX headings needs `omit` or `--no-long-summary-references`. Setext headings
work for legacy detection but are not source reference anchors.

## Preview, backups and failures

| Option | LLM calls | File writes | Output |
| --- | --- | --- | --- |
| `--dry-run` | No | No | Source line ranges, omissions, legacy cutoff, planned actions/IDs/backups, or conflict error. |
| `--print-source` | No | No | Filtered source with any planned IDs; no language selection required. |
| `--list` | No | No | Local internal/external summary inventory; no language selection required. |
| `--diff` | Yes | No | Generated unified diffs, including planned source IDs. |

Backups are enabled by default for every existing file that will change.
They preserve original bytes and permissions, and are saved beside the
original as `{stem}-{datetime}-bak.md`. The timestamp is UTC with microseconds.
`--no-backup` disables them; `--backup-filename` overrides the template.
Templates support `{stem}`, `{name}`, `{datetime}`, cannot contain directories,
must result in `.md`, and cannot overwrite an existing backup.

Generation and validation complete before publishing any file or backup.
Observed file contents are checked again before writing to detect concurrent
edits. Updates use staged files and per-file atomic replacement; a failed
publish attempts rollback, including when backups are disabled. This is not
a filesystem-wide atomic transaction. Any rollback failure reports the
affected paths. A failed write may leave valid backups or newly created
directories.

Warnings/errors carry stable `code=` labels on stderr. Common errors include
`ambiguous_summary`, `unclassified_legacy_summary`, `missing_source_ids`,
`foreign_output`, `backup_exists`, and `file_changed`. Exit codes: `0` success
or intentional skip; `2` input/configuration/conflict error; `1` generation or
write failure. Optional `max_source_chars` checks the filtered source; source
is never silently truncated.

## Configuration precedence

For this utility: CLI → `summary_regeneration.short/long` → `summary.short/long`.
Mappings merge recursively, lists replace, explicit `false` overrides, and
missing/null regeneration values inherit. Other pipeline modes continue using
their existing settings. Use the canonical section name `summary_regeneration`.
For example, a **local** `config.yaml` override can contain:

```yaml
summary_regeneration:
  short:
    enabled: true
    lang: uk
  long:
    enabled: true
    lang: uk
    references:
      enabled: true
  on_existing: skip
  legacy:
    heading_words: [summary, підсумок]
    case_sensitive: false
  references:
    missing_ids: add
  backups:
    enabled: true
    filename: "{stem}-{datetime}-bak.md"
```

The section also supports `llm`, `retry`, `source.comments`,
`external.directory` and `max_source_chars`. The tool-specific `llm`/`retry`
settings recursively override their global equivalents. Per-provider retry
settings remain more specific than global retry settings. CLI
`--llm-provider`, `--model`, `--request-delay`, and `--retry-attempts` take
precedence. All fields are documented beside their defaults in
`config.default.yaml`. `config.yaml.example` is unchanged.
