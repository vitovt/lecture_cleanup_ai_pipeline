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
Input/output/total and optional cached/reasoning tokens come from each response;
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
