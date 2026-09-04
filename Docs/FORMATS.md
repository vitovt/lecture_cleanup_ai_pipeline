# Formats and interconnection contracts

## Configuration YAML

`config.default.yaml` contains tracked defaults. Optional `config.yaml` and
`.env` files contain local overrides and secrets. Provider repositories may
have their own configuration and environment files.

## Multitrack session manifest YAML

The source manifest describes simultaneous recordings on one logical timeline.
Relative audio paths are resolved relative to the manifest file.

```yaml
language: uk
provider: groq
tracks:
  - file: ./host.wav

  - file: ./guest.wav
    language: auto
    speaker: SPEAKER_01
    diarization: false
    offset_ms: 250

  - file: ./audience.wav
    diarization: true
    speaker_prefix: AUDIENCE
    offset_ms: 0
```

Defaults and validation:

- `provider` defaults to `groq` and may be overridden per track.
- A track inherits top-level `language`; either level accepts a two-letter code
  or `auto`.
- `offset_ms` defaults to `0`. It is added to every local event timestamp.
- `diarization` defaults to `false`.
- A non-diarized track uses `speaker`, defaulting by manifest order to
  `SPEAKER_00`, `SPEAKER_01`, and so on.
- A diarized track may use `speaker_prefix` but not `speaker`. For example,
  `AUDIENCE` produces `AUDIENCE_00`, `AUDIENCE_01`, and so on.
- A non-diarized track must not use `speaker_prefix`.

The initial implementation supports simultaneous tracks and manual offsets.
Automatic alignment, clock-drift correction, sequential sessions, and audio
leakage deduplication are not part of this format version.

## Resolved manifest YAML

The transcription stage always writes `resolved-manifest.yaml`, including for
`--no-manifest` runs. It expands paths, materializes defaults, records each
track's effective language/provider, and adds `events_file`:

```yaml
tracks:
  - file: /absolute/path/host.wav
    language: uk
    provider: groq
    diarization: false
    offset_ms: 0.0
    speaker: SPEAKER_00
    events_file: /work/tracks/00-host.events.json
```

Edit `offset_ms` in this file and rerun the merge tool to adjust synchronization
without retranscribing audio.

## Transcript event JSON version 1

This is the stable boundary between ASR providers and the merger.

```json
{
  "schema": "lecture-cleanup/transcript-events",
  "version": 1,
  "source_file": "/recordings/host.wav",
  "provider": "groq",
  "requested_language": "auto",
  "detected_language": "uk",
  "duration_seconds": 3600.5,
  "track": {
    "index": 0,
    "offset_ms": 0.0
  },
  "events": [
    {
      "start": 0.08,
      "end": 1.24,
      "speaker": "SPEAKER_00",
      "text": "Секретний телеграм,"
    }
  ]
}
```

Timestamps are seconds on the source track's local timeline. Speaker labels are
session labels after provider labels have been normalized. Event JSON preserves
end timestamps that the custom TXT format does not.

Combined event JSON has the same schema/version and `kind: combined`. Its event
timestamps already include track offsets, and each event includes `track_index`.

## Custom timestamped TXT

This is the preferred input to `lecture_cleanup.sh` because its parser retains
line timestamps and speaker labels:

```text
[00:00:00,080] [SPEAKER_01] Секретний телеграм,
[00:00:01,300] [SPEAKER_01] Привіт!
[00:00:02,160] [AUDIENCE_00] Дякую.
```

The timestamp is the event start in `HH:MM:SS,mmm`. Overlapping speech is
represented by multiple lines whose times overlap in event JSON/SRT.

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

Groq additionally writes its verbose response JSON, formatted TXT, and result
metadata JSON under `provider-artifacts/`. These are diagnostic/provider-owned
formats and are not merger inputs. SpeechCore currently returns downloaded or
API-derived TXT; an eventual SpeechCore multitrack adapter must translate that
result into transcript event JSON version 1.

## Cleaned Markdown and reports

`lecture_cleanup.sh` transforms TXT/SRT into Markdown. Depending on options it
may append or separately write summaries. QC output is CSV with per-chunk source
and cleaned lengths, similarity, and change ratio. These are terminal outputs,
not inputs to the multitrack merger.
