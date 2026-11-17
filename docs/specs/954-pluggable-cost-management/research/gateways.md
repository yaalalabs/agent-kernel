# LLM gateway survey (LiteLLM Proxy, Agentgateway) and naming prior art

Gathered from vendor docs on 2026-11-16. Version-dependent; items marked *unverified* were not confirmed.

## LiteLLM Proxy

- **Attribution per request** (https://docs.litellm.ai/docs/proxy/customers):
  - end-user, first match wins: `x-litellm-customer-id` header, `x-litellm-end-user-id`, mapped custom header, body `user`, `litellm_metadata.user`, `metadata.user_id`; a JWT field overrides when `end_user_id_jwt_field` is set
  - tags: `metadata.tags` or `x-litellm-tags` header (*header format unverified*)
  - free-form: `metadata.spend_logs_metadata` / `x-litellm-spend-logs-metadata`
  - key / user / team come from the virtual key, not the request
- **Budgets** (https://docs.litellm.ai/docs/proxy/users, /tag_budgets): `max_budget` USD + `budget_duration`; `soft_budget` alert-only.
  - Levels: global, team (+ per-member), internal user, virtual key, customer/end-user, tag, per-model (Enterprise), per agent session.
- **Over-budget responses are inconsistent**: customer 401 `auth_error` "ExceededBudget", tag 422 `budget_exceeded`, per-model 400/429, agent session 429, fail-closed 503. Clients must match the error type, not the status.
- **Read-back** (admin/master key, or a key with `get_spend_routes`): `/spend/logs` (+v2 paged), `/customer/info`, `/user/info`, `/key/info`, `/tag/info`, `/user/daily/activity`, `/global/spend/report` (Enterprise).
- **Cost per call**: `x-litellm-response-cost` response header.
- **Pricing library, no proxy needed**: `litellm.cost_per_token`, `completion_cost`, `model_cost`, `register_model`; data from `model_prices_and_context_window.json` (`LITELLM_LOCAL_MODEL_COST_MAP=True` for the bundled copy). Cache-read/write and reasoning token prices exist in the JSON; `cost_per_token` accepts them as `cache_creation_input_tokens` / `cache_read_input_tokens` and `usage_object`, verified on litellm 1.95.1 (the `uv.lock` pin) on 2026-11-17; it returns a `(prompt, completion)` float pair. litellm is already a dependency (multimodal, thread extras).

## Agentgateway

- Config shapes differ between standalone and Kubernetes and across versions — pin before relying.
- **Metering**: Prometheus `agentgateway_gen_ai_client_token_usage` (labels token type, request/response model); OTel `gen_ai.usage.*`. USD only with a model cost catalog (`agw.ai.usage.cost.*`, CEL `llm.cost`) — *catalog format unverified*.
- **Budgets**: per API key only (`llm.policies.apiKey.keys[].budgets`: `limit.unit USD|Tokens`, `amount`, rolling window, `onBudgetExceeded Block|Audit`), needs SQLite/Postgres. A USD budget silently charges nothing for an unpriced model.
- **Token rate limits**: `localRateLimit` (per instance) or `remoteRateLimit` (Envoy RLS, descriptors from CEL over headers, `jwt.sub`, `apiKey.user`).
- **Refusal**: 429, body `{"error":{"code":"budget_exceeded","type":"rate_limit_error",...}}`.
- **Read-back**: `GET :15000/api/budgets/status?apiKeyName=` per key; **no per-end-user spend API** (Prometheus/logs only). *(Corrected 2026-11-17: there is no HTTP spend API, but per-request usage is stored in its optional request-log DB; see below.)*

## Implications

- Per-user spend read-back is not uniform across gateways → a declared capability, not a guaranteed method.
- A gateway refusal arrives as a framework exception, which adapters flatten into a generic error reply (`user_facing_error_message`) — "refusal is a clear normal reply" does not hold on the gateway path without extra work.
- Gateway is the only seam that stops a run mid-flight; in-process enforcement acts at run boundaries, so a run can overshoot.

## Naming prior art

- **OTel GenAI semconv** (Development status; https://github.com/open-telemetry/semantic-conventions-genai): `gen_ai.usage.input_tokens`, `output_tokens`, `cache_read.input_tokens`, `cache_write.input_tokens`, `reasoning.output_tokens`, `gen_ai.request.model` / `response.model`, `gen_ai.provider.name`. No cost attribute.
- **OpenAI Agents `Usage`**: requests, input/output/total_tokens, cached_tokens, cache_write_tokens, reasoning_tokens, request_usage_entries. No cost/budget; `max_turns` only.
- **Pydantic AI `RunUsage`**: requests, tool_calls, input/output, cache_read/cache_write, reasoning, `cost` (genai-prices). `UsageLimits` includes **`cost_limit`** → `UsageLimitExceeded`: the closest existing framework budget.

## Agentgateway follow-up (2026-11-16)

- https://agentgateway.dev/docs/standalone/latest/llm/cost-controls/budget-limits/: per-key budgets charge the realized cost after the response; the request that crosses the limit completes and the **next** is rejected; counts held in memory, flushed to the DB every 5 s. Per-user limits only via rate-limit token budgets (needs a rate-limit server; tokens, so USD is an estimate).
- Global rate limit descriptors can key on `request.headers["x-user-id"]` (one counter per value, unit `Tokens`): https://agentgateway.dev/docs/kubernetes/latest/documentation/security/rate-limit-global/
- Third party: https://github.com/day0ops/quota-management — per-user USD budgets for agentgateway, user from `x-user-id` header (not official).
- Decision (user): AK sends user, agent and session headers on every LLM call; multi-dimension querying is answered by AK's own store. *(Superseded 2026-11-17: the gateway is now the only usage store.)*

## Survey update (2026-11-17): all three #954 gateways

Collected by a delegated research pass that read the official docs. Each **V** is that pass's report of what the docs said; the URLs were not re-read independently. **V** = seen in official docs or source. **U** = unverified (a search snippet, third-party material, or inference).

### Capability matrix

| Capability | LiteLLM Proxy | Agentgateway (standalone) | Langfuse AI Gateway (beta) |
|---|---|---|---|
| Usage retrieval | `/spend/logs`, `/spend/logs/v2` (paged) **V** | request-log DB only (SQLite/Postgres `request_logs`), read by the UI and `agctl`; no HTTP query API **V** | `GET /api/public/v2/observations` **V** |
| Cost retrieval | per request in spend logs; `x-litellm-response-cost` header **V** | USD from a cost catalog **V**; an unpriced model costs $0 silently **V** | `totalCost` / `costDetails`; Metrics API **V** |
| User aggregation | `/customer/info` spend, `/user/daily/activity`; `/global/spend/report?group_by=customer` is Enterprise **V** | group by `agentgateway.user` (analytics) **V** | v2 metrics filtered by `userId`; grouping is top-N only **V** |
| Agent aggregation | via tags; `/tag/daily/activity` **U** | `standardAttributes.group`, mapped by the operator with CEL **V** | `langfuse-tags` / `langfuse-metadata`, filterable in v2 observations **V** |
| Custom per-request metadata | body `metadata`, `x-litellm-tags`, `x-litellm-spend-logs-metadata` **V** | only operator CEL over request headers or a JWT **V** | `langfuse-*` headers, 8 KiB cap (over the cap, all are ignored) **V** |
| Native budget | key, user, team, customer, global **V** | per API key only (USD or tokens) **V** | none; spend limits are on the roadmap **V** |
| Request-level budget check | pre-request reservation, on by default **V** | charged after the response; the crossing request completes **V** | n/a |
| Streaming usage | `always_include_stream_usage`; cost in the final chunk via `include_cost_in_streaming_usage` **V** | token usage recorded **V**; `include_usage` injection unknown **U** | usage, cache and reasoning tokens recorded **V**; injection unknown **U** |

### LiteLLM Proxy

- End-user resolution order, first match wins:
  1. `x-litellm-customer-id`
  2. `x-litellm-end-user-id`
  3. `user_header_mappings`
  4. body `user`
  5. `litellm_metadata.user`
  6. `metadata.user_id`
  7. `safety_identifier`

  A verified JWT `end_user_id_jwt_field` overrides all of them. **V** (https://docs.litellm.ai/docs/proxy/legacy_end_users)
- `/spend/logs/v2`:
  - `page`, `page_size` (max 1000)
  - filters: `api_key`, `user_id`, `team_id`, `model`, `status_filter`, min/max spend
  - total count capped at 10k
  
  **V**. Whether `user_id` there is the end user (customer) or the internal user: **U**.
- `/spend/logs` (v1) is truncated at 10k rows. **V**
- Non-admin access to `/spend` routes is Enterprise. **V**
- Customer budgets:
  - created with `/customer/new` (`max_budget` or `budget_id`, `budget_duration`)
  - the reset job runs every 10 min by default
  - customer budgets are cached for 60 s
  - no database means no enforcement
  
  **V**. Whether `budget_duration` can be aligned to a calendar month (UTC) rather than rolling from creation: **U**.
- Over budget: a customer gets 401 `auth_error` "ExceededBudget: End User=… over budget"; a key gets `budget_exceeded`; an internal user gets 429; fail-closed returns 503. **V**
- Budget reservation is on by default: the maximum cost is estimated from `max_tokens`, reserved, then replaced by the actual cost. With `disable_budget_reservation`, concurrent requests can overspend. **V**
- Spend writes are batched (`proxy_batch_write_at`; documented default 10 s, possibly 30 s later **U**). With Redis, Redis is the hot counter and the DB reconciles later. **V**
- `max_end_user_budget` as a default for every end user: **U**.

### Agentgateway

- Supported APIs: OpenAI Chat/Responses/Embeddings/Models, Anthropic Messages, Gemini, Realtime and passthrough. Virtual keys are set under `llm.policies.apiKey.keys[]`. **V**
- Attribution:
  - `agentgateway.user` comes from the key owner unless `config.standardAttributes.user`, a gateway-wide CEL expression, overrides it, e.g. `request.headers["x-ak-user-id"]`.
  - `group` and `session` work the same way.
  - The docs warn against trusting client headers for chargeback.
  
  **V** (worked header example: **U**)
- Storage: the optional `config.database.url` (SQLite for one instance, Postgres for several) holds the `request_logs` and `request_log_payloads` tables. Prometheus `agentgateway_gen_ai_client_token_usage`; OTel traces. **V**. Table schema stability across versions: **U**.
- Per-key budgets: rolling windows aligned to the Unix epoch, `Block` or `Audit`; 429 `budget_exceeded` when blocked. **V**

### Langfuse AI Gateway (public beta since 2026-11-04)

- Native formats only, no translation between them: OpenAI base `https://gateway.cloud.langfuse.com/openai/v1`, Anthropic base `.../anthropic/v1`. Hosts per region; self-hostable under MIT. **V** (https://langfuse.com/changelog/2026-11-04-ai-gateway-public-beta)
- Headers:
  - `langfuse-user-id`: honoured **only with service-account keys**; user keys always record the key owner
  - `langfuse-session-id`
  - `langfuse-tags`
  - `langfuse-metadata` (comma-separated `k:v`)
  - `traceparent`
  
  **V** (https://langfuse.com/docs/gateway/features/tracing)
- Retrieval:
  - v2 observations: cursor-paginated, `limit` ≤ 1000, exact filters on `userId`/`sessionId`, JSON filter on tags, metadata and cost
  - v2 metrics: `row_limit` ≤ 1000, grouping top-N only
  - self-hosting needs Langfuse v4+
  
  **V**
- Cost: USD from model definitions unless a cost is ingested; price changes are not applied retroactively. **V**
- No budgets. Recording is best-effort: a returned trace id may have no stored trace. **V**
- Whether a service-account key can be detected through an API: **U**.
- The docs say beta routes and headers may still change. **V**

### Implications for #954

- Only LiteLLM enforces a per-user budget before the request is sent. Agentgateway (per key, charged after the response) and Langfuse (no budgets) need AK's fallback check, which is not strict.
- Agentgateway attribution depends on operator CEL config. AK documents the header names and the expected config.
- Agentgateway has no HTTP read API, so per the 2026-11-17 user decision the adapter reads its request-log DB read-only.

## Survey update 2 (2026-11-17): LiteLLM's two per-user APIs, Agentgateway 1.7, Langfuse self-hosting

Done by a delegated research pass over the official docs and the source repositories. **V** = seen in official docs or in source at the named tag. **U** = unverified.

### LiteLLM

- **Releases.** The latest stable is v1.109.1 (2026-11-12). v1.111 exists only as `v1.111.0-dev.1`…`dev.4`. **V**
- **Customer Management** (documented as v1.111.0 and later):
  - Admin-key endpoints: `/management/v1/customer_organizations`, `/customer_teams` and `/customer_members`, with an idempotent `/upsert` for orgs and members, and default budget templates at `/customer_organizations/{org_id}/default_budgets`.
  - Per-request headers: `x-litellm-customer-org-alias` and `x-litellm-customer-member-id` (optionally `x-litellm-customer-team-id`).
  - `GET .../customer_members/{id}` returns `spend` (current period), `budget_reset_at`, `budget_usage` and `effective_budget`.
  - Daily activity endpoints are per org, team and member; dates are UTC, ranges at most 400 days.
  - Without Enterprise: 5 orgs, 5 teams per org, 5 members per team.

  **V** (https://docs.litellm.ai/docs/proxy/customer_management/api_reference, https://docs.litellm.ai/docs/proxy/customers)
- **Legacy end-user APIs** (open source, all versions):
  - `/customer/{new,update,info,list,delete,block,unblock,daily/activity}`, with `/end_user/*` aliases.
  - A budget is attached by `budget_id`, and `check_end_user_budget` compares `spend` with `max_budget`.

  **V** (source on `main`)
- **`/customer/info` spend** is per period: `reset_budget_job.py` resets end-user spend by the linked budget's (or the default budget's) duration. **V**
- **`/customer/daily/activity`**: admin-only, filters `end_user_ids`, `start_date`, `end_date`, `model`; also present at v1.95.1. **V**
- **`budget_duration` is calendar-aligned** in `duration_parser.py` (at `main` and v1.95.1):
  - `1d`: the next reset time of day
  - `7d` / `1w`: Monday
  - `30d` / `1mo`: the 1st of the month
  - other `Nd`: rolling from today's midnight

  `litellm_settings.timezone` (default UTC) and `budget_reset_time: "HH:MM"` (since v1.95.0). **V** (https://docs.litellm.ai/docs/proxy/budget_reset_and_tz)
- **Default end-user budget**:
  - `litellm_settings.max_end_user_budget_id` (a `/budget/new` row): each end user without a budget gets its own counter against it.
  - `max_end_user_budget` (a float) is declared but not read by the proxy.

  **V** (source). Whether it can be set through an API: **U**.
- **`/spend/logs/v2` filters** include `end_user`, `session_id`, `model`, `request_id`, dates, `page` and `page_size` (≤ 1000). `user_id` is the internal user (`user` column). There is no tag filter. The `end_user` filter is present at v1.95.1. **V**
  - How `session_id` gets populated per request: **U**.
  - Member filtering under Customer Management: **U**.
- **Over budget**:
  - Current releases: 422 by default, configurable via `budget_exceeded_status_code`. `error.type` (or `litellm_error_type` on `/v1/messages`) is `budget_exceeded`, and the message starts with `ExceededBudget:`.
  - v1.95.1 hard-codes 429.

  **V**

### Agentgateway 1.7

- **Release.** v1.7.0 was released 2026-10-27. **V**
- **Database location.** `config.logging.database.url` falls back to `config.database.url`. A `postgres://` URL means Postgres; anything else is SQLite. **V** (source at v1.7.0)
- **Tables.** `request_logs` and `request_log_payloads`. Migrations are tracked in `_agentgateway_request_log_migrations`: Postgres 1–3, SQLite 1–2. **V** (https://github.com/agentgateway/agentgateway/tree/v1.7.0/crates/agentgateway/src/telemetry/log_store)
- **`request_logs` columns**:
  - time and status: `id`, `started_at`, `completed_at`, `duration_ms`, `http_status`, `error`
  - model: `gen_ai_provider_name`, `gen_ai_request_model`, `gen_ai_response_model`
  - tokens: `input_tokens`, `output_tokens`, `total_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `reasoning_tokens`
  - cost: `cost`
  - attribution: `agentgateway_user`, `agentgateway_group`
  - other: `attributes_json`

  **V**
- **Session** is not a column. It is the `agentgateway.session` log field, expected in `attributes_json`. **U**
- **`config.standardAttributes`** takes CEL expressions for `user`, `group` and `session`, e.g. `request.headers["x-user-id"]`. **V**
- **`frontendPolicies.accessLog.database.add`** stores extra CEL fields in `attributes_json`. **V** (docs)

### Langfuse AI Gateway

- **Status.** Public beta since 2026-11-04; "Behavior, routes, and headers can still change." **V**
- **Self-hosting.** Needs Langfuse 4.75.0 or later, with the `langfuse/ai-gateway` image on the same version. Not available with `LANGFUSE_MIGRATION_V4_WRITE_MODE=legacy`. **V** (https://langfuse.com/self-hosting/configuration/ai-gateway)
- **Headers.** The values are capped at 1 KiB each; if the total exceeds 8 KiB, every context header is ignored. `langfuse-metadata` is comma-separated `key:value`. W3C `baggage` is accepted as an alternative. **V** (https://langfuse.com/docs/gateway/features/tracing)
- **Versioning.** There is no API-version header or compatibility matrix. **U**

## Correction (2026-11-17): LiteLLM 1.95.1, read in source (`ak-py/.venv`, the `uv.lock` pin)

Supersedes the **V** marks above where they disagree. These were read in source, not in the docs.

- **`budget_reset_time` does not exist at 1.95.1.** `get_next_standardized_reset_time(duration, current_time, timezone_str)` (`litellm/litellm_core_utils/duration_parser.py:97`) takes no reset time. The timezone comes from `litellm.timezone`, defaulting to UTC (`proxy/common_utils/timezone_utils.py:7-15`).
- **Calendar alignment at 1.95.1**: `1d` aligns to the next midnight, `7d` to Monday and `30d` to the 1st (`duration_parser.py:190-207`); `Nmo` aligns to the 1st (`_handle_month_reset`, `:357`). A `w` unit falls through to "next midnight" (`:143`). So weekly is `7d`, not `1w`.
- **`max_end_user_budget_id` cannot be set through the admin API.** `POST /config/update` (`proxy/proxy_server.py:14376`) stores `litellm_settings` in the DB, but the proxy applies only the keys in `LITELLM_SETTINGS_SAFE_DB_OVERRIDES` (`constants.py:1586-1595`; applied at `proxy_server.py:5669-5674`), and that key is not among them. No admin route returns `litellm_settings` (`/get/config/callbacks`, `:14992`, returns callbacks, alerts and router settings).
- **End-user header**: `x-litellm-customer-id` and `x-litellm-end-user-id` are `STANDARD_CUSTOMER_ID_HEADERS` (`constants.py:1330-1333`), read at `proxy/auth/auth_utils.py:1169`.
- **Budget refusal at 1.95.1**: `BudgetExceededError` (status 429, `exceptions.py:844-856`) becomes `ProxyException(type="budget_exceeded")` (`proxy/auth/auth_exception_handler.py:142-147`). The end-user message starts `ExceededBudget: End User=` (`proxy/auth/auth_checks.py:1121`).
- **`/spend/logs/v2`** has an `end_user` filter, `page_size` and `sort_by` / `sort_order` on one column (`proxy/spend_tracking/spend_management_endpoints.py:1734-1806`). There is no secondary sort key, so rows sharing a `startTime` have no stable order.
- **`/health/readiness`** returns `litellm_version` (`proxy/health_endpoints/_health_endpoints.py:1579`, `:1590`, route at `:1668`).
