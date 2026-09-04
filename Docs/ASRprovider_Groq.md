# ASR provider: Groq

Groq transcription is implemented in the independent `groq-api/` repository
and invoked through `groq-api/groq_api.sh`. Existing YouTube/local wrappers use
`scripts/groq_shell_common.sh`; multitrack code uses
`multitrack.providers.groq.GroqProvider`.

The provider handles media inspection, upload-limit policies, chunked ASR,
quality retries, optional pyannote diarization, timestamp merging, cost guards,
and artifact output.

```bash
./StartMe.sh groq-api transcribe \
  --input-file ./audio.flac --lang uk --diarization off
```

For multitrack use, `--events-output` writes stable transcript event JSON. Raw
Groq TXT, verbose JSON, and metadata remain under `provider-artifacts/` for
diagnostics, but the merger consumes only normalized event JSON.

See [FORMATS.md](FORMATS.md), [COMPONENT_Diarization.md](COMPONENT_Diarization.md),
and [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md).
