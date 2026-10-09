# ASR provider: Groq

Groq transcription is implemented in the independent `groq-api/` repository
and invoked through `groq-api/groq_api.sh`. Existing YouTube/local wrappers use
`scripts/groq_shell_common.sh`; multitrack code uses
the provider-environment bridge in `scripts/multitrack_provider.py`.

The provider handles media inspection, upload-limit policies, chunked ASR,
quality retries, optional pyannote diarization, timestamp merging, cost guards,
and artifact output.

```bash
./StartMe.sh groq-api transcribe \
  --input-file ./audio.flac --lang uk --diarization off
```

## Resume and checkpoints

Groq workflows resume automatically. After pyannote finishes, its speaker
timeline is saved; after each Groq audio part finishes, its accepted response
and quality report are saved. If a later part or cleanup stage fails, repeat the
same command. Matching stages are reported as `reusing ... checkpoint` and are
not recomputed or uploaded again.

By default, checkpoints are stored in `.groq-cache` below the transcript output
directory (`--srtoutdir` in the high-level wrappers). They are keyed by audio
content and relevant effective settings. Changed audio, language, model,
speaker count, prompt, temperature, or quality settings therefore do not reuse
an incompatible result. Corrupt and obsolete checkpoint formats are ignored.

```bash
./StartMe.sh youtube-groq "VIDEO_URL" --lang en --resume on
./StartMe.sh youtube-groq "VIDEO_URL" --lang en --cache-dir /data/asr-cache
./StartMe.sh youtube-groq "VIDEO_URL" --lang en --resume off
```

`--resume on` is the default. `--overwrite` implies `--resume off` because it
requests a clean reprocessing run. Checkpointing is not retroactive: work
completed by a version installed before checkpoint support cannot be recovered
from its console log or temporary files.

Groq HTTP 429 rate limits are transient and honor the provider retry delay. If
an optional quality retry fails after an earlier candidate completed, the
provider keeps the best completed candidate. A failure of the first request for
an audio part still stops the run, leaving earlier stage checkpoints available.

For multitrack use, `--events-output` writes stable transcript event JSON. Raw
Groq TXT, verbose JSON, and metadata remain under `provider-artifacts/` for
diagnostics, but the merger consumes only normalized event JSON.

See [FORMATS.md](FORMATS.md), [COMPONENT_Diarization.md](COMPONENT_Diarization.md),
and [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md).
