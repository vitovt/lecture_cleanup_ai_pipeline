# Console logging

Workflow commands use root `config.default.yaml` plus `config.yaml`, with CLI
verbosity overriding configuration. Set `--log-level quiet|error|info|debug|trace`,
`--debug`, or `--trace`. Put multitrack logging options before the first source.
Provider tools run directly use their own configuration; workflow wrappers pass
the selected level to provider and cleanup stages.

| Level | Human diagnostics |
| --- | --- |
| quiet | None, including runtime errors; exit codes still report failure |
| error | Errors only |
| info | Major steps, cache reuse, retries/waits, completion paths, warnings and errors |
| debug | INFO plus settings, sizes/counts, timings and runtime stack traces; no full prompts or response bodies |
| trace | DEBUG plus full request settings/prompts and responses; potentially large and sensitive |

Transport chatter and authentication headers are not useful workflow progress.
HTTP SDK debug logs are suppressed; application TRACE logs exclude credentials
and audio bytes. Normal output does not dump raw provider metadata. STT writes
metadata to `--metadata-output` when requested and reports a concise transcript
path; its standalone stdout JSON remains available when that option is absent.

Explicit command results are not progress messages: help, validation output,
preflight JSON, dry-run plans, source inspection, diffs, and conversion output
retain their documented interfaces. Filename helpers must also remain usable
inside command substitutions. Do not filter these as if they were logs.

## What changed

- Local/YouTube, batch and bulk wrappers resolve verbosity before validation and
  pass it through. Older SpeechCore/subtitle wrappers now honor quiet/error for
  their own processing, not just cleanup. Their error messages use stderr.
- Gemini/ElevenLabs wrappers preserve TRACE instead of downgrading it to DEBUG.
  Standalone STT accepts all five levels and `--debug`/`--trace`; retries identify
  the attempt, status and wait. Gemini announces upload; chunk preparation and
  checkpoint checks announce work before it begins.
- Audio extraction reports its start and a concise DEBUG result; full ffmpeg
  progress in the shared provider wrappers is reserved for TRACE.
- Cleanup and summary generation announce configured waits at INFO and request
  duration/result size at DEBUG. Adapter diagnostics use consistent prefixes;
  raw response/error body previews are TRACE-only.
- Multitrack inherits root logging configuration, explains failures at the
  selected level and reports the merged path once. The skip reason remains
  visible when cleanup is disabled.
- Summary regeneration uses the same levels for warnings, errors and write/skip
  progress; inspection/list/diff output remains an explicit command result.

Groq, Pyannote and SpeechCore are independently installed modules. Project
wrappers select their verbosity at the boundary; this change does not rewrite
those modules or change their standalone logging interfaces. SpeechCore accepts
DEBUG/INFO/ERROR: TRACE maps to its DEBUG, while wrapper-level quiet suppresses
all console output. Full SpeechCore payload tracing is not supplied by that CLI. Setup/install
scripts and interactive confirmation prompts are operational output, not
transcription progress logs.

## When adding a log

Use existing Python/shell helpers. Announce potentially slow operations before
starting them. Report results as a duration, count, status or output path; put
content in TRACE only. Explain cache reuse, skipped steps and retry delays.
Avoid repeating a completion path in both the worker and its entrypoint.
