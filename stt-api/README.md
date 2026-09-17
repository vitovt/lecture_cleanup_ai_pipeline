# STT API

`stt-api` is the low-level Speech-to-Text layer used by the Gemini workflow
scripts. It owns provider SDK calls, language normalization, custom vocabulary,
long-audio chunking, retries, checkpoints, and normalized TXT/events/metadata.
YouTube download, filenames, cleanup prompts, Markdown frontmatter, and list
processing remain in the four top-level Gemini scripts.

Gemini is currently implemented. The provider-neutral layout is intended to
support ElevenLabs later without changing the existing workflow entrypoints.

## Setup

```bash
./stt-api/setup_venv.sh
```

Then set the transcription key in `stt-api/.env`:

```env
GEMINI_API_KEY=your_key
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
```

Equivalent `StartMe.sh` modes are `youtube-gemini`, `youtube-gemini-list`,
`local-gemini`, and `local-gemini-list`. Run any script with `--help` for its
complete mandatory/optional arguments and provider-specific examples.

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

Both primary and additional options accept these shortcuts:

| Shortcut | BCP-47 sent to Gemini |
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

## Custom vocabulary

Pass individual terms and/or any number of UTF-8 files:

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
starting with `#` are ignored. Config, CLI terms, and all files are merged and
case-insensitively deduplicated while preserving first occurrence order.

Gemini accepts at most 1000 final terms and recommends about 100 or fewer for
best results. Custom vocabulary is incompatible with word timestamps and
speaker diarization. The CLI rejects these combinations before media download,
conversion, or upload; it never silently changes the selected mode.

Smart transcription is likewise incompatible with timestamps and diarization.

## Direct low-level use

The low-level CLI is available for diagnostics and integration:

```bash
./stt-api/stt_api.sh validate \
  --provider gemini \
  --language-code uk \
  --language-code de-DE

./stt-api/stt_api.sh transcribe \
  --provider gemini \
  --input-file ./audio.flac \
  --output-dir ./output \
  --language-code uk-UA \
  --language-code de-DE
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
