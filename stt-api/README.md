# STT API

`stt-api` is the low-level Speech-to-Text layer used by the Gemini and
ElevenLabs workflow scripts. It owns official provider SDK calls, language
normalization, custom vocabulary/keyterms, long-audio chunking, retries,
checkpoints, and normalized TXT/events/metadata. YouTube download, filenames,
cleanup prompts, Markdown frontmatter, and list processing remain in the
provider-specific top-level scripts.

Provider and mode comparisons, including the Ukrainian/German Gemini baseline
for future ElevenLabs testing, are recorded in [BENCHMARKS.md](BENCHMARKS.md).

## Setup

```bash
./stt-api/setup_venv.sh
```

Then set the transcription keys you use in `stt-api/.env`:

```env
GEMINI_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
```

This is deliberately separate from the root `.env`. The root `GOOGLE_API_KEY`
configures the Gemini text/cleanup adapter; `stt-api/.env` configures audio
transcription providers. Never put keys in `config.yaml`.

`setup_venv.sh` also creates a minimal local `stt-api/config.yaml` when needed.
The full documented defaults are in `config.default.yaml`.

## User workflows

Use one of the full workflow scripts for normal work:

```bash
./auto_process_youtube_via_gemini.sh --lang uk 'https://youtu.be/VIDEO_ID'
./auto_process_youtube_list_via_gemini.sh --lang uk --videos 1-3 'PLAYLIST_URL'
./process_localaudiovideo_via_gemini.sh --lang uk ./lesson.mp4
./process_localaudiovideo_via_gemini_list.sh --lang uk --all

./auto_process_youtube_via_elevenlabs.sh --lang uk --additional-lang de \
  'https://youtu.be/VIDEO_ID'
./auto_process_youtube_list_via_elevenlabs.sh --lang uk --videos 1-3 \
  'PLAYLIST_URL'
./process_localaudiovideo_via_elevenlabs.sh --lang uk ./lesson.mp4
./process_localaudiovideo_via_elevenlabs_list.sh --lang uk --all
```

Equivalent `StartMe.sh` modes are `youtube-gemini`, `youtube-gemini-list`,
`local-gemini`, `local-gemini-list`, `youtube-elevenlabs`,
`youtube-elevenlabs-list`, `local-elevenlabs`, and `local-elevenlabs-list`.
Run any script with `--help` for complete arguments and provider-specific
examples.

## Languages and code-switching

The workflow-level `--lang` option is mandatory. It is the primary language,
the cleanup language, and the output filename suffix. `--additional-lang` can
be repeated for other languages spoken in the recording:

```bash
./auto_process_youtube_via_gemini.sh \
  --lang uk \
  --additional-lang de-DE \
  --additional-lang en-US \
  'https://youtu.be/VIDEO_ID'
```

ElevenLabs workflows also accept `--multilingual` when the additional
languages are unknown:

```bash
./auto_process_youtube_via_elevenlabs.sh \
  --lang uk \
  --multilingual \
  'https://youtu.be/VIDEO_ID'
```

Both primary and additional options accept these shortcuts:

| Shortcut | Normalized workflow code |
|---|---|
| `uk` | `uk-UA` |
| `de` | `de-DE` |
| `en` | `en-US` |
| `ru` | `ru-RU` |

Full BCP-47 codes such as `en-GB` and `ru-RU` are accepted directly. The primary
workflow language must have a two-letter base because the cleanup pipeline uses
ISO-639-1; low-level/additional hints may use any provider-supported BCP-47
code. Additional languages affect recognition only; they do not change
cleanup/output language.

Gemini receives every normalized code as an ordered language hint. ElevenLabs
batch Scribe accepts only one language hint: with only `--lang`, its base ISO
code is sent; when `--multilingual` or one or more `--additional-lang` options
are present, the hint is omitted and Scribe v2 automatically detects any
number of languages. ElevenLabs does not receive the additional codes as an
allowlist. They document expected languages and select the same automatic
mode; use `--multilingual` when those languages are not known in advance.

## Custom vocabulary and keyterms

Gemini workflows accept individual terms and any number of UTF-8 files:

```bash
./process_localaudiovideo_via_gemini.sh \
  --lang uk \
  --additional-lang de \
  --timestamps off \
  --custom-vocabulary 'Sicherheitsgruppe' \
  --custom-vocabulary 'stateful firewall' \
  --custom-vocabulary-file ./aws-terms.txt \
  ./lesson.m4a
```

Vocabulary files contain one term or phrase per line. Empty lines and lines
starting with `#`, `` ``` ``, or `~~~` are ignored. Config, CLI terms, and all
files are merged and case-insensitively deduplicated while preserving first
occurrence order.

Gemini accepts at most 1000 final terms and recommends about 100 or fewer for
best results. Custom vocabulary is incompatible with word timestamps and
speaker diarization. The CLI rejects these combinations before media download,
conversion, or upload; it never silently changes the selected mode.

Smart transcription is likewise incompatible with timestamps and diarization.

ElevenLabs calls vocabulary entries `keyterms`. Pass individual keyterms with
repeatable `--custom-vocabulary` and/or one-entry-per-line files with
repeatable `--custom-vocabulary-file`. The wrapper reads and merges the files,
then sends one keyterms array to ElevenLabs. Keyterms are compatible with word
timestamps, diarization, and `--mode smart` (`no_verbatim=true`):

```bash
./process_localaudiovideo_via_elevenlabs.sh \
  --lang uk \
  --multilingual \
  --diarization provider \
  --custom-vocabulary 'Halbleiter' \
  --custom-vocabulary-file ./physics-de.txt \
  ./lesson.m4a
```

With diarization enabled, timestamped TXT and events JSON use anonymous labels
such as `speaker_0` and `speaker_1`. The labels distinguish voices but do not
identify people by name.

Scribe v2 batch accepts at most 1000 keyterms. Each must be shorter than 50
characters, contain at most 5 words, and cannot contain `<`, `>`, `{`, `}`,
`[`, `]`, or backslash. These constraints are validated before media upload.
Keyterms add a 20% ElevenLabs surcharge; more than 100 keyterms also impose a
20-second minimum billable duration per request.

## Direct low-level use

The low-level CLI is available for diagnostics and integration:

```bash
./stt-api/stt_api.sh validate \
  --provider gemini \
  --language-code uk \
  --language-code de-DE

./stt-api/stt_api.sh transcribe \
  --provider elevenlabs \
  --input-file ./audio.flac \
  --output-dir ./output \
  --language-code uk-UA \
  --language-code de-DE \
  --custom-vocabulary Halbleiter
```

Configuration precedence is `CLI > config.yaml > config.default.yaml`. Process
environment variables override values from `stt-api/.env`.

## Gemini limits handled by this project

- Audio with timestamps or diarization is conservatively split into 25-minute
  chunks (the documented API maximum is 30 minutes).
- Untimed audio is split into 55-minute chunks (documented maximum: 60 minutes).
- Adjacent chunks overlap by five seconds. Timestamped words use ownership
  boundaries; untimed chunks use exact boundary-text deduplication.
- Matching chunks are checkpointed and can be resumed. `--overwrite` or
  `--resume off` bypasses checkpoint reuse.
- Temporary Gemini Files API uploads are deleted after each request attempt.

The current provider behavior and limitations follow Google's
[Gemini audio transcription documentation](https://ai.google.dev/gemini-api/docs/transcribe).

## ElevenLabs limits handled by this project

- The official `elevenlabs` Python SDK is used; version `2.60` or newer is
  required because it fixes repeated multipart fields used by keyterms.
- Standard single-channel uploads support files under 5 GB and up to 10 hours.
  The local conservative split point is 9 hours, so ordinary lectures are sent
  in one request and Scribe can use its own long-audio processing.
- `scribe_v2` returns word timestamps by default and supports up to 32 speakers.
- `--mode smart` maps to `no_verbatim=true`; the default `verbatim` mode keeps
  filler words, false starts, and repetitions for faithful lecture cleanup.
- Matching requests are checkpointed. Provider, model, languages, keyterms,
  timestamps, diarization, mode, and audio bytes are part of the fingerprint.
- With multiple workflow languages, `provider_language_code` is `auto` in
  validation/metadata and Scribe performs automatic multilingual detection.

See the official ElevenLabs
[Speech-to-Text API reference](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
and [Scribe overview](https://elevenlabs.io/docs/overview/capabilities/speech-to-text).

## Multitrack integration

Use `../StartMe.sh multitrack` for explicit sources and TXT merging. Native
speaker detection is selected with `--diarization provider`; the old `on` value
is rejected. `--num-speakers N` passes an expected speaker count to ElevenLabs;
Gemini rejects this unsupported option. Multitrack runs reject native diarization
when the source requires multiple API chunks, since identities cannot be assumed
to remain stable across independent requests. Groq/Pyannote uses its separate
adapter. See `../Docs/MULTITRACK_DESIGN.md` for source overrides and presets.

## Logging

Use `--log-level quiet|error|info|debug|trace`, `--debug`, or `--trace`.
INFO reports audio preparation, checkpoints, requests and retry waits; DEBUG adds
timings/counts and runtime stack traces. Full response payloads are TRACE-only.
With `--metadata-output`, metadata is saved without an extra console JSON dump.
Without it, stdout JSON remains the standalone result. Explicit validation and
preflight output are machine-readable results, independent of diagnostic levels.

## Account allowance checks

Use the main entry point without uploading or transcribing audio:

```bash
../StartMe.sh balance --scope stt --provider elevenlabs
../StartMe.sh balance --scope stt --list
```

The root account service reads this directory's config and `.env`, including
`providers.elevenlabs.api_key_env`. ElevenLabs reports subscription character
allowance and reset time, not a USD or Scribe-specific remaining balance;
`status=partial` makes that distinction explicit. The command needs the main
virtualenv, not the ElevenLabs SDK. See [accounting documentation](../Docs/LLM_ACCOUNTING.md).

### Named model profiles

Save presets in `stt-api/config.yaml` under `profiles`, choose `default_profile`,
and override one invocation with `--profile NAME`. A profile names its provider
and model, plus optional provider settings and a `transcription` mapping.
Explicit CLI options win. `--provider` bypasses the default profile.

From the project entry point, run `./StartMe.sh profiles --scope stt`,
`./StartMe.sh stt-api validate --profile NAME`, or
`./StartMe.sh stt-api transcribe --profile NAME --input-file audio.mp3`.
See [examples and precedence](../Docs/PROFILES.md#stt-profiles).

### OpenRouter

OpenRouter is available through the existing provider-neutral CLI:

```bash
./stt_api.sh validate --provider openrouter
./stt_api.sh transcribe --provider openrouter --input-file lecture.mp3 --output-dir ../input/transcripts
```

Set `OPENROUTER_API_KEY` in this directory's `.env`. For repeated model changes,
use [STT profiles](../Docs/PROFILES.md#openrouter-speech-to-text). The adapter uses
OpenRouter's dedicated transcription endpoint with existing chunking, retries,
checkpoints and TXT/events/raw/metadata outputs. Raw output preserves API usage.
Word timestamps, diarization and keyterms depend on the chosen model; missing
requested timestamps fail explicitly. Generic smart mode and speaker counts
are unavailable. Text generation and STT use their respective `.env` files.


Request accounting is shared with cleanup. API attempts print `STT_USAGE` only
for returned metrics (tokens and reported cost/currency), followed by
`USAGE_TOTAL` for the processing session. Unknown/unsupported fields are omitted;
no token prices are maintained. Retries are separate attempts, while reused
checkpoints do not emit new usage or add charges. Quiet/error logging suppresses
these records. See [accounting contracts](../Docs/LLM_ACCOUNTING.md).
