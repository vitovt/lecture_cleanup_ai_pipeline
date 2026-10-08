# Multitrack sources: agreed design

This document records the design agreed with the user on 2026-10-09.

## Interface and scope

`StartMe.sh multitrack` delegates to `process_multitrack.sh`. A source has a
stable, unique `id`, an optional display `name`, and exactly one of `track`
(one-based audio stream of the final recording) or `file` (separate recording
containing exactly one audio stream). Stereo channels are not separate streams.
Embedded streams, separate files, and mixtures are supported. Missing names
become `Source_<id>`. Descriptive names are recommended in help and examples.

Before the first `--source ID`, transcription options are shared defaults and
workflow/cleanup options are global. Each `--source` starts a source context;
subsequent transcription options override only that source. Global-only options
are forbidden in source contexts. If any resolved source selects a track, one
recording positional argument is required, last. Otherwise it is forbidden.

```bash
./StartMe.sh multitrack --provider elevenlabs --lang uk --additional-lang de \
  --diarization off \
  --source student --track 2 --name Student_Nazar \
  --source teacher --track 5 --name Teacher_Vitalii recording.mkv

./StartMe.sh multitrack --provider groq --lang uk \
  --source host --file host.wav --name Vitalii \
  --source audience --file audience.wav --name Students \
  --diarization pyannote --num-speakers 3
```

## Presets and precedence

```yaml
defaults:
  provider: elevenlabs
  lang: uk
  additional_lang: [de]
  diarization: off
sources:
  - id: student
    track: 2
    name: Student_Nazar
  - id: teacher
    track: 5
    name: Teacher_Vitalii
```

`--preset FILE` loads YAML. Precedence, highest first: CLI source overrides,
YAML source settings, CLI shared settings, YAML defaults, application defaults.
CLI source IDs already in YAML update those sources; new IDs append sources.
CLI `file` removes inherited `track` and vice versa; both in one declaration
are invalid. Additional-language lists replace inherited lists; an explicit
empty list/CLI clear option removes them. YAML paths are relative to the preset;
CLI paths are relative to the invocation directory. Display names are not IDs.

```bash
./StartMe.sh multitrack --preset webinar.yaml --lang de \
  --source teacher --file better-teacher.wav \
  --source translator --file translator.wav --name Translator recording.mkv
```

## Diarization and provider settings

Modes are `off`, `pyannote` (local engine), and `provider` (native service).
Remove ambiguous public `on` aliases; do not retain obsolete syntax. Unsupported
combinations must fail before extraction/transcription. Groq uses local Pyannote;
ElevenLabs and Gemini have native modes. Providers/settings can vary per source;
shared language and vocabulary settings optimize the common case.

Off: every line uses the exact name. Detected single speaker: exact name too.
Several detected speakers: `<name>_01`, `<name>_02`, etc. Expected speaker counts
are passed only to engines supporting them; unsupported counts are an error.
Actual count mismatch is a visible warning, not a failure. Provider diarization
requiring independent chunk requests must stop in this version because speaker
IDs are not reconciled across chunks. Never silently fall back to another engine.

## Processing boundary and artifacts

Each source is transcribed separately. The interchange and merge format is the
existing `[HH:MM:SS,mmm] [Speaker] text` TXT, not provider JSON. Preserve original
recordings, extracted audio, provider artifacts, source TXT, and merged TXT for
manual inspection. Retain JSON only as provider diagnostics. Reuse the existing
merger's timeline sorting/manual offsets; preserve simultaneous lines and leakage.
No cross-source deduplication, automatic alignment, drift correction, or manual
speaker matching UI in this version. TXT lacks end times; do not invent them.

Integrated cleanup is implemented but `multitrack.stop_after_merge: true` in root
`config.default.yaml` initially stops multitrack workflows after TXT merging.
An explicit CLI override enables cleanup. Single-source workflows retain their
existing cleanup behavior. A standalone transcription/merge utility never invokes
cleanup regardless of configuration. All applicable cleanup options stay global.

## Validation and dry run

Resolve all sources and preflight all providers before work. Check stream counts,
files, options, capabilities, timed output, speaker counts, and planned splitting.
`--dry-run` shows the complete effective plan including defaults, inheritance,
provider settings, sources, output locations, and cleanup behavior; no extraction,
API calls, or output writes. Do not expose credentials in reports.

A shared helper under `subtitle-utils` inspects audio streams. Existing single-file
`process_localaudiovideo_*` scripts reject multiple audio streams and direct users
to multitrack selection. Batch/list wrappers rely on their single-file child;
do not scan a whole batch in advance. Separate `--file` sources use the same check.

## Test recording and authorization

`~/Videos/OBS/2026-10-08_18-01-41-NazarUrok.mkv` has six stereo audio streams,
duration 4415.36 seconds. Select track 2 Student_Nazar and track 5 Teacher_Vitalii;
spoken languages uk/de, uk primary. Earlier user estimate of five tracks was
corrected by ffprobe. Local inspection is authorized. Before real paid/external
transcription, agree with the user on provider and excerpt. Test pure resolution,
preflight errors, naming, TXT merging, offsets, cache invalidation, stream guards,
mock provider integration, and actual local extraction with synthetic audio.

## Implementation organization

Extend the existing multitrack command rather than duplicate workflows. Share
source resolution, media inspection, provider adapters, TXT parsing/merging, and
cleanup dispatch. Reuse provider validation/chunking/checkpoints wherever possible.
Future stt-api providers should use the common adapter contract, declaring their
capabilities in their provider module instead of adding separate merger logic.
