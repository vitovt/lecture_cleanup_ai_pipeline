# LLM token usage and account balance

DeepSeek reports token usage after each cleanup chunk request and summary request,
plus its account balance before and after the LLM processing session. The same
reporting applies to `StartMe.sh add-summary`. Other cleanup LLM adapters expose
explicit `status=unsupported` stubs. Manual account checks also support STT subscription quotas through the shared
`accounting/` service; automatic STT checks are not enabled.
No accounting files are written, and this feature does not calculate money spent.

Check the effective cleanup provider or select one explicitly:

```bash
./StartMe.sh balance
./StartMe.sh balance --provider deepseek
./StartMe.sh help balance
```

The default command uses the same merged configuration and root `.env` as cleanup,
regardless of the current working directory. It makes no generation request.
The CLI also checks STT accounts through the same entry point:

```bash
./StartMe.sh balance --scope stt                     # stt-api's configured provider
./StartMe.sh balance --scope stt --provider elevenlabs
./StartMe.sh balance --scope stt --provider groq      # explicit unsupported result
./StartMe.sh balance --list                          # capabilities/configuration; no HTTP
./StartMe.sh balance --all                           # all registered accounts in both scopes
./StartMe.sh balance --scope stt --all --format json  # only STT accounts
```

For a single check, omitted `--scope` means `cleanup`. The cleanup default comes
from root `llm.provider`; the STT default comes from `stt-api`'s `provider`.
`--provider` selects a provider within that scope. Invalid provider/scope pairs
are CLI errors. Without `--scope`, `--all` and `--list` cover both scopes.
`--provider` cannot be combined with `--all` or `--list`.

| Scope/provider | Config and credentials | Available checks |
|---|---|---|
| cleanup/deepseek | root config and `.env` | Currency balances |
| cleanup/other | root config and `.env` | Explicit unsupported result |
| stt/elevenlabs | `stt-api/config…` and `stt-api/.env` | Subscription character allowance |
| stt/gemini | `stt-api/config…` and `stt-api/.env` | Unsupported |
| stt/groq | `groq-api/config…` and `groq-api/.env` | Unsupported |
| stt/speechcore | Deprecated integration | Unsupported |

Credential resolution is isolated per account and never modifies `os.environ`.
Exported process variables override the selected `.env`; keys from a different
scope's `.env` are never used as fallback. STT's `providers.<name>.api_key_env`
and Groq's `api.api_key_env` overrides are respected. Scope denotes the source of
credentials, not a distinct billing account. Two configured keys may belong to
the same account; their balances are never summed or automatically deduplicated.
An `accounting.timeout_seconds` setting in the selected config controls account
requests (default 10 seconds, greater than 0 and at most 60). No STT SDK is needed;
`balance.sh` uses the main environment. Checks perform GETs only, never uploads,
generation, transcription, or rate-limit probing.

### ElevenLabs

The adapter reads `ELEVENLABS_API_KEY` from `stt-api/.env` unless `api_key_env`
selects another variable. It calls
[`GET /v1/user/subscription`](https://elevenlabs.io/docs/api-reference/user/subscription/get)
with the `xi-api-key` header. The origin defaults to `https://api.elevenlabs.io`;
`providers.elevenlabs.api_base_url` overrides `ELEVENLABS_API_BASE_URL`, which
otherwise overrides that default. Set an origin without `/v1`.

The endpoint's `character_count` and `character_limit` become a
`subscription_characters` quota with `unit=characters`. Remaining allowance is
`max(limit-used, 0)`; overage is separately `max(used-limit, 0)`. Reset time is the
reported `next_character_count_reset_unix`, converted to UTC, or unknown when
absent. Tier and subscription status are included when reported.

This is account subscription allowance, not a dedicated Scribe quota or a money
balance. The result is `partial` with `reason=monetary_balance_unavailable`;
`balances` remains empty and `available` is unknown. Invoice amounts, overage
costs and allowance extensions are not reinterpreted as available money. No
conversion from characters to USD or remaining audio hours is attempted.

### Output and exit codes

`--format text` (default) emits key=value records. Cleanup retains `LLM_BALANCE`
and its existing currency/amount fields; STT uses `ACCOUNT_BALANCE` followed by
`ACCOUNT_QUOTA` records. New CLI records include scope and UTC check time.
`--list` emits `ACCOUNT_PROVIDER` with configuration state and capabilities.
Its `configured` value means a credential exists, not that it was validated.
Groq's `rate_limits=response_headers` describes the provider's mechanism; this
feature does not collect or cache rate-limit headers.

`--format json` always returns an array, including single checks. Monetary
amounts are decimal strings to preserve precision; counts are integers;
unknown optional values are JSON null, not fabricated zeros. Missing balances
and quotas are empty arrays. List mode returns capability objects instead.

Check statuses: `ok`, `partial`, `unsupported`, `not_configured`, `error`.
Error reasons are stable safe codes, such as `authentication_failed`,
`permission_denied`, `rate_limited`, `connection_failed`, `http_error`,
`invalid_response`, `invalid_configuration`, `component_not_installed`, and
`missing_credentials`.
Bodies, key values and raw exception messages are never printed.

Exit codes: `0` for successful/partial/unsupported results; `1` for errors or a
single requested account missing credentials; `2` for invalid CLI options.
`--all` includes unconfigured entries but does not fail merely because a key is
missing or an optional component is not installed. It continues after provider errors and exits `1` if any actual check
or configuration fails. Unsupported single checks require neither credentials
nor optional SDKs. `--list` makes no HTTP requests and exits `1` on configuration
errors, but not on missing credentials.

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

## Adding an account provider

1. Add a small `accounting/providers/<name>.py` checker accepting
   `AccountSettings` and returning normalized `AccountSnapshot` field overrides.
   It owns only the provider GET and response parsing. Use `AccountError` safe
   reason codes and `accounting.http.get_json` with the configured timeout.
2. Register its scope, provider name, configuration directory/section, key
   variable, capabilities and checker import path in `accounting/registry.py`.
   Reuse the same checker for multiple credential sources when applicable.
3. Add offline response/credential-isolation tests. No CLI provider branch or
   generation/transcription SDK is required.

The shared DeepSeek fetcher is used both by this service and
`DeepSeekAdapter.get_balance()`, preserving existing pipeline before/after
records. The legacy `Balance` and `BalanceSnapshot` imports from
`aiadapters.accounting` remain compatibility exports. Usage-token reporting is
unchanged. Future automatic STT monitoring can call the same account service;
no separate STT balance command is necessary.
