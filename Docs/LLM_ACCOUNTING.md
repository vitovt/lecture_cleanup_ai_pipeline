# LLM token usage and account balance

DeepSeek reports token usage after each cleanup chunk request and summary request,
plus its account balance before and after the LLM processing session. The same
reporting applies to `StartMe.sh add-summary`. Other cleanup LLM adapters expose
explicit `status=unsupported` stubs. Audio transcription providers are not included.
No accounting files are written, and this feature does not calculate money spent.

Check the effective cleanup provider or select one explicitly:

```bash
./StartMe.sh balance
./StartMe.sh balance --provider deepseek
./StartMe.sh help balance
```

The command uses the same merged configuration and root `.env` as cleanup,
regardless of the current working directory. It makes no generation request.
Exit codes: `0` for a successful query or an unsupported provider, `1` for a
configuration/authentication/network/response failure, `2` for invalid CLI options.
Unsupported providers require no credentials or optional SDKs for this command.

Accounting records contain whitespace-separated `key=value` fields. Pipeline
records have the usual `[INFO]` prefix and follow the selected log level;
`balance` prints records directly without a logging prefix. Event names and keys
are stable; consumers should select fields by name rather than position. Values
containing whitespace or reserved characters use UTF-8 URL percent encoding
(for example, `label=chunk%201%2F3%20%28attempt%201%2F2%29`).

```text
LLM_USAGE provider=deepseek model=deepseek-v4-pro stage=cleanup label=chunk%201%2F3%20%28attempt%201%2F2%29 status=ok outcome=ok part=1 parts=3 attempt=1 attempts=2 summary=none input_tokens=100 output_tokens=30 total_tokens=130 cache_hit_tokens=40 cache_miss_tokens=60 reasoning_tokens=20
LLM_BALANCE provider=deepseek phase=check status=ok currency=USD total=8.123456 granted=0.000000 topped_up=8.123456 available=true
```

- `LLM_USAGE`: `stage=cleanup|summary`; cleanup identifies `part` and `parts`,
  summary identifies `summary=short|long|both`, and both identify `attempt` and
  `attempts`. Non-applicable context fields are `none`.
- `status=ok` means the API returned valid core token counts; `unknown` means
  usage was missing, invalid, or unavailable after a failed request;
  `unsupported` means the adapter has not implemented accounting yet. Unknown
  counts are the literal `unknown`, never zero. Optional breakdowns may be
  `unknown` even when the core counts are valid.
- `outcome=ok|error` describes the generation call, before downstream output
  validation. A rejected summary response still consumed tokens and has its own
  usage record. Retried requests produce additional records, not replacements.
- `input_tokens` includes cache hits and misses. `reasoning_tokens` is a subset
  of `output_tokens`; do not add either breakdown to `total_tokens` again.
- Both summaries normally share one API request (`summary=both`); its usage is
  reported once, since separate per-summary counts are unavailable.
- `LLM_BALANCE`: `phase=before|after|check`, `status=ok|error|unsupported`.
  Successful queries emit one record per currency with exact decimal amounts
  (`total`, `granted`, `topped_up`) and `available=true|false`. Failed queries
  emit a `reason` code and omit amounts. Monitoring failures do not stop cleanup;
  the final balance is attempted even if processing raises an error or is
  interrupted normally. Forced process termination cannot guarantee final output.

Filtering examples (assuming normal console output was saved to `run.log`):

```bash
# Only balance records, including failures and unsupported providers.
grep -E '(^| )LLM_BALANCE ' run.log

# One total-token value per cleanup attempt with valid usage.
awk '/LLM_USAGE / && /stage=cleanup / && /status=ok / {
  for (i=1; i<=NF; i++) if ($i ~ /^total_tokens=/) {
    split($i, field, "="); print field[2]
  }
}' run.log

# Summary records, including combined summaries and retries.
grep -E '(^| )LLM_USAGE .*stage=summary ' run.log

# Get the queried USD balance as a decimal value.
./StartMe.sh balance --provider deepseek | awk '/status=ok / && /currency=USD / {
  for (i=1; i<=NF; i++) if ($i ~ /^total=/) {
    split($i, field, "="); print field[2]
  }
}'
```

Balances belong to the account, not to one process: concurrent jobs and top-ups
affect them. Missing usage after a timeout can also mean a billed request was not
counted locally. Token sums are therefore only complete when every request has
valid usage. Balances in different currencies must be kept separate.

Adapter extension points are `supports_usage`, `_record_response()` and
`last_usage: TokenUsage`, plus `supports_balance` and
`get_balance() -> BalanceSnapshot`. Defaults in `LLMAdapter` are unsupported.
