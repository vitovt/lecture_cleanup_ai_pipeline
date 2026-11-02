# Request usage, costs and account balances

All cleanup adapters and the STT component use the shared `accounting.usage`
normalizer, formatter and accumulator. Available metrics are printed after API
requests as `LLM_USAGE` or `STT_USAGE`. Only valid returned values are shown:
unsupported or missing fields are omitted, and a request without statistics
produces no usage line. Reported zero tokens or zero cost remain visible.

The shared parser supports Chat Completions, Responses, Gemini metadata and
compatible envelopes, both dictionaries and SDK objects. New integrations pass
responses to this mechanism instead of adding provider-specific console output.
OpenRouter declares USD as its cost currency; other APIs must report a currency
or declare one in their integration before monetary fields are shown.

`cost` is the charge reported by the API, handled as `Decimal`, with a
`currency` field. Raw HTTP JSON preserves monetary decimal digits. No prices are
hardcoded, no token-to-price estimates are made, and no management key or extra
API request is needed. Tokens and money are independent: either can be shown
without the other. Cache and reasoning breakdowns are subsets of input/output
and are never added to total tokens again. Upstream/BYOK cost estimates are not
substituted for the charge reported to this account.

`USAGE_TOTAL` summarizes the processing session by scope/provider/model. A
combined row (`scope=all`) is emitted when several groups contributed. Different
currencies are never added together: a multi-currency total has separate money
rows. Missing responses still count as attempts, so a known subtotal is marked
`partial=true`, with `<metric>_requests` showing how many attempts supplied that
metric. No metrics means no total row. Retries and rejected summary responses
are counted separately; reused STT checkpoints add no new requests or costs.
Totals are finalized on normal completion or exceptions. Quiet/error logging
suppresses accounting output. No separate persistent accounting database is
created; STT's existing raw diagnostics still preserve original response usage.

Account checks remain separate. DeepSeek reports account balance before/after
LLM sessions; unsupported automatic balance reporting is silent. The explicit
`balance` CLI still reports capability/error statuses, including STT subscription
allowances, without generation or transcription. A balance change may include
other jobs and is not used to estimate the cost of this job.

### OpenAI per-request tokens

The existing OpenAI adapter reads `usage` from each Responses API response and
emits `LLM_USAGE` through the existing cleanup/summary reporting path. It uses
the same `OPENAI_API_KEY` as generation. There are no additional API calls,
Admin keys, account queries, prices, or currency estimates.

- `input_tokens`, `output_tokens`, `total_tokens`: provider-reported core counts.
- `cache_hit_tokens`: `usage.input_tokens_details.cached_tokens`, when reported.
- `cache_miss_tokens`: input tokens minus cached input tokens, when known.
- `reasoning_tokens`: `usage.output_tokens_details.reasoning_tokens`, when reported.

Cached tokens are included in input tokens, and reasoning tokens are included in
output tokens; neither is added to the total again. Missing or invalid optional
details are omitted; missing or inconsistent core counts are not displayed.
Successful zero counts remain zero. Every new attempt
clears the previous response's counters, including direct adapter calls.
See the official [Responses API usage schema](https://developers.openai.com/api/reference/resources/responses/methods/retrieve).

For example, a chunk can emit:

```text
LLM_USAGE provider=openai model=your-model stage=cleanup label=chunk%201%2F2 status=ok outcome=ok part=1 parts=2 attempt=1 attempts=2 summary=none input_tokens=100 output_tokens=30 total_tokens=130 cache_hit_tokens=40 cache_miss_tokens=60 reasoning_tokens=20
```

`balance --provider openai` remains `unsupported`: per-request token usage is
reported during processing, not retrieved from the account balance command.

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

- `LLM_USAGE`: `stage=cleanup|summary`; `STT_USAGE`: `stage=transcription`.
  Context identifies chunk/part and attempt numbers when available. A combined
  summary uses `summary=both`.
- `status=ok` means at least one valid metric is present. Missing/unsupported
  metrics are omitted, including money for APIs without reported charges.
  There are no automatic `unknown` or `unsupported` usage placeholders.
- `outcome=ok|error` describes the generation call, before downstream output
  validation. A rejected summary response still consumed tokens and has its own
  usage record. Retried requests produce additional records, not replacements.
- `input_tokens` includes cache hits and misses. `reasoning_tokens` is a subset
  of `output_tokens`; do not add either breakdown to `total_tokens` again.
- Both summaries normally share one API request (`summary=both`); its usage is
  reported once, since separate per-summary counts are unavailable.
- `LLM_BALANCE`: `phase=before|after|check`, `status=ok|error`; explicit account
  queries may also return `unsupported`.
  Successful queries emit one record per currency with exact decimal amounts
  (`total`, `granted`, `topped_up`) and `available=true|false`. Failed queries
  emit a `reason` code and omit amounts. Monitoring failures do not stop cleanup;
  the final balance is attempted even if processing raises an error or is
  interrupted normally. Forced process termination cannot guarantee final output.

Filtering examples (assuming normal console output was saved to `run.log`):

```bash
# Balance records (manual checks also report unsupported providers).
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

LLM integrations call the base `_record_response(response)` hook after each
reply. It sets `last_usage: TokenUsage` and preserves statistics for multiple
transport replies within one generation attempt. There is no usage capability
flag or per-model pricing registry. STT integrations call
`request_with_usage(call, scope=..., provider=..., model=..., emit=...)` inside
their existing retry loop. The same shared reporter handles output and totals;
cache hits bypass the transport and therefore bypass accounting. Balance
extensions still use `supports_balance` and `get_balance()` independently.

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
`aiadapters.accounting` remain compatibility exports alongside `TokenUsage`.
Request accounting uses the common implementation described above. Future
automatic STT monitoring can call the same account service;
no separate STT balance command is necessary.

OpenRouter Chat Completions also emits `LLM_USAGE` from the response `usage`
object: `prompt_tokens`, `completion_tokens`, `total_tokens`, and optional cached
and reasoning details. Reasoning is included in output tokens and cache hits in
input tokens. Missing or malformed statistics are omitted. No extra usage
requests are made. See [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting).


Example request and session total (illustrative amounts):

```text
LLM_USAGE scope=cleanup provider=openrouter model=vendor%2Fmodel stage=cleanup status=ok outcome=ok input_tokens=100 output_tokens=30 total_tokens=130 cost=0.0042 currency=USD
USAGE_TOTAL scope=cleanup provider=openrouter model=vendor%2Fmodel requests=2 input_tokens=200 output_tokens=60 total_tokens=260 cost=0.0084 currency=USD
```

STT OpenRouter uses the same monetary and token reporting through the dedicated
transcription response's `usage` object. Its raw/checkpoint JSON retains cost
as a decimal string. See [OpenRouter transcription usage](https://openrouter.ai/docs/api/api-reference/stt/create-transcription).
Gemini metadata is normalized using the documented input, candidate, thinking,
and tool-use counts; see [Gemini usage metadata](https://ai.google.dev/api/generate-content).

## Whole-workflow totals

Processing modes launched through `StartMe.sh` own one temporary usage journal
for the command and its child processes. STT, cleanup, summaries, batch items
and multitrack workers that emit shared usage events contribute to the same
final `USAGE_TOTAL` records. Nested sessions do not print duplicate totals.
Components without request statistics contribute no invented metrics.

The journal contains only provider/model/scope identifiers, returned numerical
metrics and output visibility. It contains no prompts, transcripts or API keys,
is created with private permissions, and is removed when the command exits.
The child command's arguments, working directory, streams and exit status are
preserved. Direct standalone LLM/STT processing still reports its own session
total without a workflow journal. Standalone STT keeps JSON on stdout and
accounting on stderr. Quiet/error modes suppress the totals as well as request
records. SIGKILL or a machine crash cannot guarantee final reporting or cleanup.
