# Model profiles

Profiles are named provider/model presets in local YAML, not aliases for
providers. They work with all cleanup adapters and use the existing recursive
configuration merge. Credentials remain in `.env`.

```yaml
# config.yaml
llm:
  default_profile: quick
  profiles:
    quick:
      provider: groq
      model: openai/gpt-oss-120b
      reasoning_effort: low
    offline:
      provider: dummy
      model: dummy
```

```bash
./StartMe.sh profiles
./StartMe.sh cleanup --input lecture.txt --lang uk           # quick
./StartMe.sh cleanup --input lecture.txt --lang uk --llm-profile offline
./StartMe.sh add-summary notes.md --lang uk --llm-profile quick --dry-run
```

Every workflow that forwards cleanup options also accepts `--llm-profile`.
The same selected model is used for cleanup and its summaries. `add-summary`
accepts the option too. A CLI selection applies only to this invocation; it
never rewrites `config.yaml`.

Precedence: `config.default.yaml` → `config.yaml` → selected profile → explicit
CLI generation options. Each profile must name its `provider`; other keys are
merged over `llm.<provider>`. Nested mappings merge, lists replace, and `null`
can clear an optional value. Profiles do not inherit other profiles.

Set `llm.default_profile: null` to keep the original `llm.provider` behavior.
An explicit `--llm-provider` bypasses the default profile entirely. If both
`--llm-profile` and `--llm-provider` are supplied, their providers must match.
Unknown profiles fail before generation and report available names.

STT and cleanup have separate configuration and profile selections; a cleanup
profile does not change a workflow's transcription provider.

## OpenRouter text generation

Set `OPENROUTER_API_KEY` in the root `.env`, then add local profiles:

```yaml
llm:
  default_profile: router-fast
  profiles:
    router-fast:
      provider: openrouter
      model: google/gemini-2.5-flash
    router-quality:
      provider: openrouter
      model: anthropic/claude-sonnet-4
      reasoning: {effort: high, exclude: true}
      provider_routing:
        order: [Anthropic]
        allow_fallbacks: false
```

```bash
./StartMe.sh cleanup --input lecture.txt --lang uk --llm-profile router-quality
./StartMe.sh youtube-groq --lang uk --llm-profile router-fast 'VIDEO_URL'
```

Here `provider: openrouter` selects the pipeline adapter. `model` is an exact
OpenRouter model ID. `provider_routing` is forwarded as OpenRouter's `provider`
request object; it selects the hosting endpoints *within* OpenRouter. `order`
sets preference; `allow_fallbacks: false` prevents routing to unlisted providers.
Use `only` when restricting the allowed endpoint pool. Availability, supported
parameters and prices depend on the selected model/endpoint. See the official
[routing reference](https://openrouter.ai/docs/guides/routing/provider-selection)
and [model catalogue](https://openrouter.ai/models).

The existing chunking, retries, summaries and `LLM_USAGE` reporting apply.
Input/output/total, optional cached/reasoning tokens and reported USD charges
come from each response;
no separate usage requests or estimated prices are introduced. `balance` lists
OpenRouter as unsupported for account snapshots; this integration adds text
requests and per-request usage only.

## STT profiles

STT follows the same selection rules, using `default_profile` and `profiles` in
`stt-api/config.yaml`. Provider/model/request/chunking settings merge over
`providers.<provider>`. An optional `transcription` mapping merges over the
shared transcription settings, so each model can choose compatible timestamp
or diarization options.

```yaml
# stt-api/config.yaml
# Credentials are loaded from stt-api/.env.
default_profile: scribe-lecture
profiles:
  scribe-lecture:
    provider: elevenlabs
    model: scribe_v2
    transcription:
      diarization: {enabled: true}
  gemini-plain:
    provider: gemini
    model: gemini-3.5-transcribe
    transcription:
      timestamps: {enabled: false}
```

```bash
./StartMe.sh profiles --scope stt
./StartMe.sh stt-api validate --profile gemini-plain
./StartMe.sh stt-api transcribe --input-file audio.mp3 --output-dir input/transcripts
./StartMe.sh stt-api transcribe --profile gemini-plain --input-file audio.mp3 --output-dir input/transcripts
```

`--model`, `--timestamps`, `--diarization` and other explicit STT flags override
the selected profile. `--provider` alone bypasses the default STT profile. STT
presets do not affect existing provider-specific workflow scripts, which select
their provider explicitly; use the provider-neutral `stt-api` entry for profiles.
The resulting TXT can be passed to `StartMe.sh cleanup --llm-profile NAME`.

## OpenRouter speech-to-text

Put `OPENROUTER_API_KEY` in `stt-api/.env`. Add a profile there independently of
cleanup profiles:

```yaml
# stt-api/config.yaml
default_profile: router-whisper
profiles:
  router-whisper:
    provider: openrouter
    model: openai/whisper-large-v3
  router-plain:
    provider: openrouter
    model: openai/whisper-large-v3
    transcription:
      timestamps: {enabled: false}
```

```bash
./StartMe.sh stt-api validate --profile router-whisper
./StartMe.sh stt-api transcribe --profile router-whisper --input-file audio.mp3 --preflight
./StartMe.sh stt-api transcribe --profile router-whisper --input-file audio.mp3 --output-dir input/transcripts
./StartMe.sh cleanup --input input/transcripts/audio.txt --lang uk --llm-profile router-fast
```

This uses the dedicated `/audio/transcriptions` endpoint, not a chat model
prompted to transcribe. Long audio uses the existing splitting, overlap,
checkpoint/resume and timestamp formatter. Model, endpoint and provider options
are included in checkpoint fingerprints. Response `usage` is printed through
shared request accounting; usage and the original payload are preserved in the existing `.raw.json` output; cached results reuse
that original usage, they do not represent another paid request. Metadata
records the selected profile.

Word timestamps request `verbose_json` with word granularity. A model that
returns text without requested timestamps fails explicitly; choose a compatible
model or disable timestamps. Diarization and keyterms are forwarded when
requested, but support varies by model. `smart` and `--num-speakers` are not
supported for this adapter. A single language is sent as an ISO language hint;
multiple languages leave detection to the model.

`providers.openrouter.provider_options` maps to the STT endpoint's native
`provider` object (data policy and provider-specific passthrough). Its schema is
different from text `provider_routing`; Chat Completions routing fields should
not be assumed to work here. Consult the official
[transcription endpoint reference](https://openrouter.ai/docs/api/api-reference/stt/create-transcription).

The default 900-second chunks and 25 MiB audio cap are conservative client
settings, not an assertion of universal provider limits. Adjust
`chunking.max_seconds` and `request.max_audio_bytes` in a profile for the chosen
model. Files over the configured byte cap fail locally before upload. No new
SDK dependencies or automatic account-balance requests are added.
