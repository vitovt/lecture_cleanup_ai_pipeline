# Formats and interconnection contracts

## Configuration YAML

`config.default.yaml` contains tracked defaults. Optional `config.yaml` and
`.env` files contain local overrides and secrets. Provider repositories may
have their own configuration and environment files.

## Multitrack preset YAML and resolved plan

See [MULTITRACK_DESIGN.md](MULTITRACK_DESIGN.md) for the `defaults` / `sources`
preset contract. Each source has an ID and exactly one of `track` or `file`.
`resolved-plan.yaml` records effective settings and artifact paths for inspection;
it is a diagnostic plan, not a preset. Edit the source preset or use CLI overrides.

Provider JSON is retained for diagnostics. The multitrack interchange and merge
contract is timestamped TXT, shared by all adapters. Internal event objects reuse
existing timestamp sorting; JSON is not required as a merge input.

## Custom timestamped TXT

This is the preferred input to `lecture_cleanup.sh` because its parser retains
line timestamps and speaker labels:

```text
[00:00:00,080] [SPEAKER_01] Секретний телеграм,
[00:00:01,300] [SPEAKER_01] Привіт!
[00:00:02,160] [AUDIENCE_00] Дякую.
```

The timestamp is the event start in `HH:MM:SS,mmm`. Simultaneous speech is represented by separate timestamped lines. TXT records
start times only and cannot represent overlap duration.

## SubRip SRT

Merged SRT retains start/end times and prefixes text with the speaker label:

```srt
1
00:00:00,080 --> 00:00:01,240
SPEAKER_01: Секретний телеграм,
```

The current cleanup pipeline strips SRT timing rows while reading SRT, so use
custom TXT when downstream heading timecodes matter.

## Provider artifacts

Raw responses, metadata, and provider-specific events remain in each source's
`provider/` directory. They are diagnostic formats, not merger inputs. The
provider adapter returns a timestamped TXT path for naming and merging.

## Cleaned Markdown and reports

`lecture_cleanup.sh` transforms TXT/SRT into Markdown. Depending on options it
may append or separately write summaries. QC output is CSV with per-chunk source
and cleaned lengths, similarity, and change ratio. These are terminal outputs,
not inputs to the multitrack merger.
