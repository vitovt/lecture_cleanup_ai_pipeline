# Multitrack stage 1: completion and validation

**Status: feature-complete, 2026-10-09.** The agreed first implementation stage
is closed. The next activity is user testing on real recordings and fixes based
on that feedback, not additional feature development. This status does not claim
that every provider/audio scenario has been validated in production.

Start with [MULTITRACK_QUICKSTART.md](MULTITRACK_QUICKSTART.md). The agreed scope is
recorded in [MULTITRACK_DESIGN.md](MULTITRACK_DESIGN.md).

## Completed scope

- `StartMe.sh multitrack` and the dedicated shell workflow.
- Stable source IDs selecting embedded tracks, separate single-stream files, or
  both; descriptive names and `Source_<ID>` fallback labels.
- Strict global/source CLI scopes; YAML defaults and per-source overrides;
  adding sources and replacing track selections with files or vice versa.
- Independent Groq, ElevenLabs, and Gemini transcription with per-source settings
  and explicit compatibility checks. Future services need an stt-api adapter.
- Explicit diarization modes, supported expected-speaker counts, and rejection of
  native diarization requiring independent provider chunks.
- Shared media-stream inspection used by local workflows and separate-file sources.
- Timestamped TXT naming, chronological merging, manual offsets, and retained
  audio/provider/source artifacts. No provider JSON merge contract.
- Read-only dry run; start/end excerpts with original timestamp restoration and
  excerpt-based provider preflight; completed-source reuse and provider checkpoints.
- Standalone transcription/merge and TXT-only merge tools; optional integrated
  cleanup. Cleanup remains disabled by default for multitrack workflows.

Implementation commits: `ac0354b` (source workflow), `9b1cc09` (chunk-boundary fix),
and `8246521` (excerpts). The design was recorded in `13b7871`.

## Verified behavior

The latest implementation validation passed **209 project tests and 28 stt-api
tests**. This includes synthetic audio extraction, scopes/overrides, timestamp
ordering, offsets, speaker naming, cache invalidation, stream guards, provider
argument handling, and mocked cleanup dispatch. These are recorded results from
the implementation stage, not a claim that the suite was rerun for this
documentation-only closeout.

Two real ElevenLabs Scribe v2 runs processed 00:10–01:10 from the OBS lesson
`2026-10-08_18-01-41-NazarUrok.mkv`, selecting tracks 2 and 5:

| Run | Behavior verified | Accuracy review |
| --- | --- | --- |
| Fixed labels on both sources | Two independent 60-second requests, 15 merged lines, correct names, preserved source lines and original timestamps | User approved the first transcript |
| Student native diarization; teacher detection off | Native excerpt selection, one-speaker fallback to the exact name, mixed modes, 15 merged lines, original timestamps | Structural checks passed; no separate user accuracy approval recorded |

An identical rerun of the second command succeeded with cached source transcripts
inside the network-restricted sandbox, without transcription/HTTP requests.
Original audio, the first approved transcript, and both runs' artifacts were kept.
The second ASR response differed slightly in the opening teacher greeting; the
first transcript was not replaced.

Local run records (ignored artifacts, not files shipped by Git):

- `multitrack-work/nazar-elevenlabs-0010-0110/TEST_NOTES.md`
- `multitrack-work/nazar-excerpt-mixed-diarization/TEST_NOTES.md`

Four failure cases in the pre-existing, untracked
`tests/test_youtube_subtitles.py` were reproduced against the original code.
They are unrelated to multitrack and were not modified. The passing project
count above excludes that untracked test file.

## Implementation limits

| Transcription provider | Accepted diarization | Expected count |
| --- | --- | --- |
| Groq | `off`, local `pyannote` | Supported by Pyannote |
| ElevenLabs | `off`, native `provider` | Supported with native diarization |
| Gemini | `off`, native `provider` | Explicit counts are rejected |

Native speaker identities are not reconciled across independent requests.
A native-diarization source requiring splitting is rejected; a short enough
excerpt may be processed instead. There is no silent fallback to another engine.
A single detected speaker uses the exact source name; several use `_01`, `_02`,
etc. A count mismatch is a warning, not an exact-count guarantee.

Timed output is required. Groq supports one language hint and a prompt, not
additional-language lists or native vocabulary options. Gemini's current client
rejects custom vocabulary and smart mode when combined with the timestamps
required for merging. Other provider limits remain enforced by their clients.

There is no automatic alignment, clock-drift correction, cross-source speaker
matching, or microphone-leakage deduplication. Simultaneous/duplicate speech is
preserved. TXT stores start times only, not utterance end times. A separate-file
source must contain exactly one audio stream; channel splitting is not provided.

The old manifest CLI and ambiguous public `--diarization on` alias were removed.
The independently installed Groq repository still has its own internal CLI;
project wrappers translate `pyannote` at that boundary. Use the documented
project-level commands for the new terminology.

## Validation still pending

These are real-data acceptance checks, not missing first-stage features:

- Full-length recordings, long silence, and synchronization across the recording.
- Genuine multiple-speaker separation within one source.
- Live Groq/Pyannote and Gemini runs, and sessions using different providers.
- Real mixed embedded/separate-file sessions and manually corrected offsets.
- Interruption during a live provider request and recovery of partial work.
- Real multitrack cleanup quality: preservation of speaker turns and short replies.

The user will test real files this week or process them together with the
assistant. Feedback should include a reproducible command and short interval;
see the quick start's reporting notes.

## Deferred beyond this stage

Automatic synchronization, drift correction, leakage deduplication, and manual
or automatic speaker identity matching across provider chunks remain future
work. No implementation of these is required to close stage 1. Prioritize them
only if real-data use demonstrates a need.
