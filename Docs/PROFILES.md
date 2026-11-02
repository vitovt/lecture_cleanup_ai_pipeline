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
