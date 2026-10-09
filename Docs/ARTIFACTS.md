# Output destinations and working artifacts

All root workflows, including `StartMe.sh cleanup`, direct `lecture_cleanup.sh`,
YouTube/local-media wrappers, and multitrack, use these shared destinations:

```bash
# In the project's .env (examples):
CLEANUP_MDOUTDIR="$HOME/Desktop/obsidian"
TRANSCRIPT_OUTDIR="$HOME/Desktop/transcripts"
```

Markdown goes directly into `CLEANUP_MDOUTDIR`; final TXT/SRT goes directly into
`TRANSCRIPT_OUTDIR`. Without overrides the defaults are project `output/` and
`input/transcripts/`. `--outdir` and `--srtoutdir` override the respective setting
on workflows which produce those outputs. Direct cleanup reads an existing
transcript and does not copy it. Independent low-level tools (stt-api, Groq,
subtitle download/conversion utilities) retain their own explicit output options.

Relative `.env` paths are relative to the **project**, while relative CLI paths
are relative to the **directory where you run the command**. For example, with
the project at `/projects/lectures` and the shell in `/tmp/review`:

- `.env`: `CLEANUP_MDOUTDIR="notes"` means `/projects/lectures/notes`.
- CLI: `--outdir notes` means `/tmp/review/notes`.
- `$HOME` and `~` expand to your home directory.

The old `AUTOYOUTUBE_*OUTDIR`, `AUTOLOCAL_*OUTDIR`, and provider-specific output
variables no longer control destinations. Replace Markdown variables with
`CLEANUP_MDOUTDIR` and transcript variables with `TRANSCRIPT_OUTDIR`.

## Names and existing files

Media workflows use the sanitized input basename (YouTube uses its resolved
video title/ID), without adding a provider or language suffix. Direct cleanup
uses the supplied transcript's stem. Multitrack also accepts `--output-name`;
excerpts add their bounds to the default name.

If that Markdown already exists, processing fails before transcription/LLM work.
Choose `--overwrite` explicitly to replace it. This applies even to a multitrack
run that would stop after merging. A final TXT/SRT may be republished during
resume; provider-specific originals remain in the working directory. Different
inputs with the same basename intentionally encounter the same Markdown guard.
A concurrent run is not a supported way to process the same destination.

## Directory layout

```text
input/
  transcripts/                   final TXT/SRT, protected from automatic cleaning
  _work/
    <name>-<identity hash>/
      run.json                   ownership, inputs, destinations and categories
      media/                     downloaded/extracted audio or video
      transcripts/               source TXT and multitrack completion records
      provider/                  original provider TXT/JSON, metadata and diagnostics
      cache/                     resumable provider checkpoints
      resolved-plan.yaml         multitrack's effective settings
output/                          final Markdown, protected from automatic cleaning
```

Working identities distinguish inputs and workflows without changing final
filenames. Multitrack source categories contain a directory for each source ID.
Original input media is referenced, never moved or deleted by a workflow.
An explicit `--workdir` replaces the working location for multitrack.

Deleting `media/` alone leaves completed multitrack source TXT reusable when
inputs/settings still match. Deleting `cache/` discards provider checkpoints;
deleting `transcripts/` discards outer multitrack completion records. Retain
`provider/` when you need to inspect original responses or recover transcripts.
Do not delete an active job's files.

## Contract for a future cleaner

No automatic cleaner is implemented here. A future cleaner must require a
recognized `run.json` with `automatic_cleaning_allowed: true`, limit itself to
its named categories beneath the project's real `input/_work/`, and refuse
symlink escapes. It must not follow input/output references as deletion targets.
All final outputs are protected. Explicit working/output/transcript/cache
locations are protected even when they happen to lie under `input/_work/`.
Check protected destinations across **all** run records before deleting a parent
category; an override may be nested inside another job. Unregistered paths and
unknown files outside categories are not automatically eligible for deletion.

## Existing data and CSV

The 2026-10-09 migration moves generated workflow directories into this layout.
Older single-source collections are retained in `legacy-<workflow>-<hash>` jobs;
historical filenames are kept, including language suffixes. Top-level TXT/SRT
copies are published under `input/transcripts/`, and old workflow Markdown is
flattened into `output/`. Collisions receive `.migrated-N` names; no file is
silently discarded. Migration never follows external destination settings.
The local inventory is `input/_work/migration-2026-10-09.json`.

Provider responses/checkpoints remain available, but historical cache settings
or paths may prevent automatic reuse. Review archived transcripts before
requesting paid reprocessing. Operational multitrack metadata is updated to the
new paths; archived logs and test notes remain historical records.

QC CSV is disabled in `config.default.yaml`. Existing `config.yaml` overrides
still apply. To opt in use `--qc-report outdir` or `default_outdir`; to disable an
existing local override use `--qc-report off` or `qc_report_mode: "off"`.
The CSV calculation has not changed and is not a transcription-quality score.
