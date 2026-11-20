# Agentgateway 1.7.x: where session and request id land in the request log

**Status:** verified on a real run, 2026-11-17. **Takeaway:** the session is `attributes_json."agentgateway.session"`,
a request id added through `frontendPolicies.accessLog.database.add` is `attributes_json."<key>"`. Neither is a column.

## Setup

- Image `ghcr.io/agentgateway/agentgateway:v1.7.0` (the only non-prerelease 1.7 tag on GHCR on that date), run with
  `--network host`, logging to SQLite.
- Upstream: a Python stdlib mock of OpenAI `/v1/chat/completions` returning `usage` (12 prompt, 3 completion tokens).
- Config:

```yaml
config:
  logging:
    database:
      url: /data/agw.db
  standardAttributes:
    user: request.headers["x-ak-user-id"]
    group: request.headers["x-ak-agent-id"]
    session: request.headers["x-ak-session-id"]
frontendPolicies:
  accessLog:
    database:
      add:
        ak.request_id: request.headers["x-ak-request-id"]
llm:
  port: 4000
  models:
  - name: gpt-4o-mini
    provider: openAI
    params:
      baseUrl: http://127.0.0.1:8081
      apiKey: {file: /cfg/key}
```

- Request: `POST /v1/chat/completions` with `x-ak-user-id: oidc|https%3A%2F%2Fissuer.example|user-123`,
  `x-ak-agent-id: support-agent`, `x-ak-session-id: sess-42`, `x-ak-request-id: req-abc`.

## Observed

`_agentgateway_request_log_migrations` (SQLite): versions `1` (create request log schema) and `2` (add request log
analytics columns). Postgres was not run; the v1.7.0 source tree ships Postgres migrations 1–3
(`crates/agentgateway/src/telemetry/log_store/postgres_migrations/`).

`request_logs` row (columns):

```json
{
 "id": "01a1e880-2fa0-702f-b52c-d31dada8393f",
 "started_at": "2026-11-17T07:54:37.326796+00:00",
 "completed_at": "2026-11-17T07:54:37.343697+00:00",
 "http_status": 200,
 "gen_ai_provider_name": "openai",
 "gen_ai_request_model": "gpt-4o-mini",
 "gen_ai_response_model": "gpt-4o-mini",
 "input_tokens": 12,
 "output_tokens": 3,
 "total_tokens": 15,
 "cost": 3.6e-06,
 "agentgateway_user": "oidc|https%3A%2F%2Fissuer.example|user-123",
 "agentgateway_group": "support-agent",
 "cache_read_input_tokens": null
}
```

`attributes_json` (relevant keys):

```json
{
 "agentgateway.user": "oidc|https%3A%2F%2Fissuer.example|user-123",
 "agentgateway.group": "support-agent",
 "agentgateway.session": "sess-42",
 "ak.request_id": "req-abc",
 "gen_ai.usage.input_tokens": 12,
 "gen_ai.usage.output_tokens": 3,
 "agw.ai.usage.cost.total": 3.6e-06
}
```

A second request with only `x-ak-user-id: u2`: `agentgateway_group` is `NULL`, and `agentgateway.session`,
`ak.request_id` and `agentgateway.group` are **absent** from `attributes_json` (not empty strings).

## Conclusions for design.md

- Session: `json_extract(attributes_json, '$."agentgateway.session"')`. The key name is hard-coded in
  `crates/agentgateway/src/config.rs:696` (`standard_attributes`).
- Request id: `json_extract(attributes_json, '$."ak.request_id"')`, present only with the documented
  `accessLog.database.add` entry.
- The percent-encoded user id round-trips unchanged through the header and the column.
- Missing attribution is an absent key or `NULL` column, read as `None`.
- Not checked here: the $0 price for an uncatalogued model (the mock used a catalogued model, priced 3.6e-06), and
  Postgres.
