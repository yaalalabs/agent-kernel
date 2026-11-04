# Fetching Traces Back from the Providers' Clouds

**Requirement (changed 2026-10-08):** traces stay in the tracing provider's cloud (Langfuse / Logfire /
Traceloop / AWS CloudWatch) as normal. AK must be able to **fetch them back** for evaluation, filtered by e.g. **time
interval** or **only tool calls**.

**How this was researched:** official docs + API references (web), and the installed SDKs in
`ak-py/.venv` (langfuse 4.15.1, logfire 4.41.0, traceloop-sdk 0.62.3), with file/line evidence.
**No live calls were made** (no API keys here), so everything is from docs + SDK source.

> AWS CloudWatch tracing landed on `develop` later (#794); its read API is surveyed in §6, after the
> original three providers.
>
> §4 below sketches a separate `TraceSource` interface. The adopted design puts `fetch()` on `BaseTrace`
> instead; see [../design.md](../design.md).

---

## TL;DR

**All three providers can return traces with time-window and tool-call filtering, but in different ways and with different limits.**

| | **Langfuse** | **Logfire** | **Traceloop** |
|---|---|---|---|
| Read API | REST `GET /api/public/v2/observations` | SQL Query API `POST /v2/query` | REST `GET /v2/warehouse/spans` |
| Python client in installed SDK | ✅ `langfuse.api.observations.get_many(...)` | ✅ `LogfireQueryClient.query_json_rows(...)` (+ async, Arrow, CSV, DB-API) | ❌ none; call REST yourself |
| Auth | public + secret key (same as sending) | separate **read token** | same API key as sending (Bearer) |
| Time window | ✅ `from_start_time` / `to_start_time` | ✅ `min_timestamp` / `max_timestamp` (+ SQL) | ✅ `from_timestamp_sec` / `to_timestamp_sec` |
| Only tool calls | ✅ `type="TOOL"` | ✅ SQL `WHERE attributes->>'gen_ai.operation.name'='execute_tool' OR span_name='Function: {name}'` | ⚠️ likely: filter `traceloop.span.kind = tool` (not tested) |
| Other filters | name, session_id, user_id, trace_id, environment, level, version, tags, metadata, input/output text search (JSON `filter`) | **anything**: full SQL over all columns + attributes JSON | workflow, span_name, any attribute (`filters` JSON: equals/contains/in/exists…) |
| Whole trace | ✅ `get_many(trace_id=...)`, rebuild from parent ids | ✅ `WHERE trace_id IN (...)` | ⚠️ only via **undocumented** endpoint (`/v2/projects/default/traces/{id}/spans`) |
| Pagination | cursor, ≤1000/page | ❌ none: **max 10,000 rows/query**; split time windows | cursor (`next_cursor`) |
| Data format | ❌ **Langfuse's own model** (observations), not raw OTel | ✅ **close to raw OTel** (ids, timestamps, attributes JSON) | ✅ **close to raw OTel** (`span_attributes`, `resource_attributes`) |
| Readable after | ~15–30 s | ~5 min | not documented |
| How far back (cloud plans) | Hobby 30 d · Core 90 d · Pro 3 y | Personal/Team 30 d · Growth 90 d · Ent. custom | ⚠️ **Free 24 h** · Enterprise custom |
| Rate limits | per org: Hobby 30/min · Core 100/min · Pro 1000/min; 5 MB per response | plan-based concurrency + daily budget (numbers not published); 429 + Retry-After | not documented |
| Read cost | not billed (inferred; billing is on ingestion) | not billed (inferred) | not stated |
| Bulk export | scheduled S3/GCS/Azure export (Parquet/JSONL…), **Pro+Teams add-on / Enterprise / self-host only**; UI CSV/JSON on all plans | no dedicated feature; use Query API → Arrow/Parquet | none |
| Biggest risk | **v1 read endpoints removed from Cloud on 16 Nov 2026**; must use v2 | 10k-row cap, no pagination | 24 h free retention, no SDK client, ServiceNow acquisition (Mar 2026) |

**Verdict:**
- **Langfuse: best fit.** Real SDK method, direct `type="TOOL"` filter, cursor pagination. Downside:
  the data comes back in Langfuse's model, so it needs its own normaliser.
- **Logfire: most flexible.** SQL can filter on anything, and the data is close to raw OTel. Downsides:
  the row cap and the 5-minute delay.
- **Traceloop: works on paper, weakest in practice.** REST only, the tool filter is untested, the
  whole-trace endpoint is undocumented, and the free plan keeps data for only 24 hours.

---

## 1. Langfuse

**Read path:** `langfuse.api.observations.get_many(...)` → `GET /api/public/v2/observations`
(SDK `langfuse/api/observations/client.py:28`). Async: `langfuse.async_api.observations.get_many`.

- **Filters (direct parameters):** `from_start_time` (inclusive), `to_start_time` (exclusive), `type`
  (GENERATION, SPAN, EVENT, AGENT, **TOOL**, CHAIN, RETRIEVER, EVALUATOR, EMBEDDING, GUARDRAIL), `name`,
  `user_id`, `session_id`, `trace_id`, `level`, `parent_observation_id`, `is_root_observation`,
  `environment`, `version`.
- **Generic `filter`:** a JSON array of `{type, column, operator, value, key?}`. **It overrides the
  direct parameters**, so put the time window in it too. Columns include tags/traceTags, metadata
  (with `key`), input/output (`matches` = text search), latency, tokens, cost, model, promptName….
- **Pagination:** cursor; `limit` default 50, max 1000; loop until `resp.meta.cursor` is None. Sorted
  newest first.
- **Field selection:** `fields=` groups. `core` is always returned (id, traceId, startTime, endTime,
  parentObservationId, type); the default adds `basic`; optional groups are `time`, `io`, `metadata`,
  `model`, `usage`, `prompt`, `metrics`, `trace_context`. Metadata values are cut at 200 chars unless
  listed in `expand_metadata`.
- **Format:** flat `ObservationV2` rows in Langfuse's own model. Rebuild the tree via
  `parent_observation_id`. Trace-level input/output is not on v2 rows.
- **How our OTel spans map to Langfuse types** (Langfuse server `ObservationTypeMapper.ts`, in priority
  order): `langfuse.observation.type` → `openinference.span.kind` (TOOL→TOOL, LLM→GENERATION,
  AGENT→AGENT…) → `gen_ai.operation.name` (execute_tool→TOOL, invoke_agent→AGENT) → `gen_ai.tool.name` →
  model attr → GENERATION, else SPAN. **So tool calls from all our captured runners should map to
  TOOL.** Unmapped attributes end up under `metadata.attributes.<otel key>`; the raw spans are not
  returned as-is.
- **⚠️ Deprecation:** `api.trace.get/list`, `api.sessions.*`, `api.legacy.observations_v1.*` will be
  **removed from Langfuse Cloud on 16 Nov 2026** (per the SDK). Langfuse's built-in
  `langfuse.run_batched_evaluation(...)` still calls these deprecated endpoints
  (`batch_evaluation.py:1173-1189`), so **don't build on it**; use v2 `observations.get_many`.
- **Limits:** rate limit per org: Hobby 30/min, Core 100/min, Pro 1000/min (deprecated endpoints are
  lower). 5 MB per response, so lower `limit` when fetching `io`. Readable ~15–30 s after ingestion
  (retry on `NotFoundError`). If AK ever uses a custom `span_exporter`, it must send the header
  `x-langfuse-ingestion-version: 4`, or data can be delayed up to 15 min on v2 endpoints.
- **Bulk:** UI export CSV/JSON (all plans). Scheduled blob export to S3/GCS/Azure
  (Parquet/CSV/JSON/JSONL, every 20 min to weekly, with backfill) on **Pro + Teams add-on, Enterprise,
  self-hosted**.
- **Self-hosted:** no rate limits; retention as configured; v2 endpoints need self-hosted Langfuse v4.

```python
import datetime as dt
from langfuse import get_client

langfuse = get_client()
end = dt.datetime.now(dt.timezone.utc); start = end - dt.timedelta(hours=24)
tool_calls, cursor = [], None
while True:
    resp = langfuse.api.observations.get_many(
        type="TOOL", from_start_time=start, to_start_time=end,
        fields="core,basic,time,io,metadata,metrics", limit=200, cursor=cursor,
    )
    tool_calls.extend(resp.data)
    cursor = resp.meta.cursor
    if not cursor:
        break
```

Sources: [API limits](https://langfuse.com/faq/all/api-limits) · [pricing](https://langfuse.com/pricing) ·
[OTel integration](https://langfuse.com/integrations/native/opentelemetry) ·
[UI export](https://langfuse.com/docs/api-and-data-platform/features/export-from-ui) ·
[blob export](https://langfuse.com/docs/api-and-data-platform/features/export-to-blob-storage)

---

## 2. Logfire

**Read path:** SQL **Query API**, `POST https://logfire-{us|eu}.pydantic.dev/v2/query`, with a
project-scoped **read token** (create it in the UI or with `logfire read-tokens --project org/proj create`).
The region is taken from the token prefix.

- **SDK** (`logfire.query_client`, verified in 4.41.0): `LogfireQueryClient(read_token, ...)` /
  `AsyncLogfireQueryClient`. `logfire.experimental.query_client` still exists as a backwards-compatible
  path (the code lives there in 4.41.0 and `logfire.query_client` re-exports it).
  - `query_json_rows(sql, min_timestamp, max_timestamp, limit, *, timezone, environment)` → `{columns, rows}`
  - `query_arrow(...)` → `pyarrow.Table`; `query_csv(...)` → str; `query_json` (deprecated)
  - `logfire.db_api.connect(...)`: PEP 249, works with pandas `read_sql`
- **Filtering:** full SQL (DataFusion) over the **`records`** table. Columns: `trace_id`, `span_id`,
  `parent_span_id`, `span_name` (template, e.g. `'Function: {name}'`), `message` (filled in),
  `start_timestamp`, `end_timestamp`, `duration`, `attributes` (JSON), `tags`, `level`, `kind`,
  `is_exception`, `exception_*`, `otel_status_*`, `otel_events`, `otel_scope_name`,
  `otel_resource_attributes`, `service_name`, `deployment_environment`, `created_at`. JSON access:
  `attributes->>'gen_ai.operation.name'`.
- **`min_timestamp` is required in practice** (omitting it is deprecated). Time filters apply to
  `start_timestamp`.
- **Limits:**
  - **max 10,000 rows per query (default 100), no pagination.** If you get exactly `limit` rows, data is
    missing; split the time window, or use a `created_at` cursor.
  - Rate limits: plan-based concurrency + daily budget (numbers not published); 429 + Retry-After.
  - **Readable ~5 min after storage.** SDK client timeout defaults to 30 s.
  - Retention: Personal/Team 30 d, Growth 90 d, Enterprise custom.
- **Format:** close to raw OTel. ids, timestamps, attributes (JSON object; a JSON *string* in
  Arrow/CSV), events, resource attrs, plus Logfire's own `logfire.*` keys.
- **Data loss to know about:** **scrubbing happens client-side before export** (that's why AK's
  `session_id` attribute arrives as `"[Scrubbed due to 'session']"`; see [span-formats.md](span-formats.md) §5); scrubbed values are gone for good. Ingestion
  truncates span name/message to 512 bytes and huge records (>10 MB). Records timestamped more than 24 h
  in the past are dropped.
- **Bulk:** no dedicated export feature; use the Query API (Arrow → Parquet). There's also a hosted
  MCP server for ad-hoc querying.

```python
from datetime import datetime, timedelta, timezone
from logfire.query_client import LogfireQueryClient

SQL = """
SELECT trace_id, span_id, parent_span_id, span_name, start_timestamp, end_timestamp, attributes
FROM records
WHERE kind = 'span'
  AND (attributes->>'gen_ai.operation.name' = 'execute_tool'   -- Pydantic AI
       OR span_name = 'Function: {name}')                      -- OpenAI Agents SDK
ORDER BY start_timestamp
"""
end = datetime.now(timezone.utc) - timedelta(minutes=5); start = end - timedelta(hours=6)
with LogfireQueryClient(read_token=READ_TOKEN) as client:
    res = client.query_json_rows(sql=SQL, min_timestamp=start, max_timestamp=end, limit=10_000)
    if len(res["rows"]) == 10_000:
        raise RuntimeError("hit row cap; split the time window")
```

Sources: [Query API](https://pydantic.dev/docs/logfire/manage/query-api/) ·
[SQL reference](https://pydantic.dev/docs/logfire/reference/sql/) ·
[query limits](https://pydantic.dev/docs/logfire/reference/query-limits/) ·
[ingest limits](https://pydantic.dev/docs/logfire/reference/limits/) ·
[MCP server](https://pydantic.dev/docs/logfire/guides/mcp-server) · [pricing](https://pydantic.dev/pricing)

---

## 3. Traceloop

**Read path:** REST **`GET https://api.traceloop.com/v2/warehouse/spans`** (documented),
`Authorization: Bearer <API key>`. **The installed SDK has no read method** (`Client` only has
user_feedback, datasets, experiment, associations).

- **Filters:** `from_timestamp_sec` (required), `to_timestamp_sec`, `workflow`, `span_name`; unknown
  query params act as exact attribute matches; `filters` = URL-encoded JSON
  `[{id, operator, value}]` (equals, not_equals, gt/gte/lt/lte, contains, starts_with, in, not_in,
  exists, not_exists).
- **Sorting:** `sort_by` (timestamp, duration_ms, span_name, trace_id, total_tokens…), `sort_order`.
- **Pagination:** `limit` + `next_cursor` → `cursor`; `total_results` returned. Max `limit` not documented.
- **Format:** close to raw OTel: `trace_id`, `span_id`, `parent_span_id`, `span_name`, `span_kind`,
  `span_attributes`, `resource_attributes`, timestamp/duration (ms), status, plus extracted
  prompts/completions/input/output.
- **⚠️ Unverified:** whether `traceloop.span.kind`, `gen_ai.*` and
  `traceloop.association.properties.session_id` work as filter ids exactly as written. Traceloop's own
  MCP server maps `gen_ai.*` → `llm.*` when filtering, which hints that the backend may rename fields.
- **Whole trace by ID:** only via **undocumented** endpoints used by Traceloop's official MCP server
  ([traceloop/opentelemetry-mcp-server](https://github.com/traceloop/opentelemetry-mcp-server)):
  `GET /v2/projects/default/traces/{trace_id}/spans`, `POST /v2/projects/default/spans`. These could
  change without notice.
- **Limits:** **retention 24 h on Free**, custom on Enterprise. 50K spans/month free. Rate limits and
  read cost not documented.
- **Other:** self-host "hybrid" mode (your own ClickHouse) and full on-prem are Enterprise only.
  `POST /v2/metrics` returns evaluator/monitor metrics, not spans.
- **⚠️ Vendor risk:** **ServiceNow acquired Traceloop in March 2026**, to fold into its AI Control
  Tower. The API and docs are still live, but the standalone roadmap is unknown.

```python
import json, os, httpx

def fetch_tool_spans(start_s: int, end_s: int):
    params = {"from_timestamp_sec": start_s, "to_timestamp_sec": end_s, "limit": 500,
              "filters": json.dumps([{"id": "traceloop.span.kind", "operator": "equals", "value": "tool"}])}
    headers = {"Authorization": f"Bearer {os.environ['TRACELOOP_API_KEY']}"}
    with httpx.Client(base_url="https://api.traceloop.com", headers=headers, timeout=60) as c:
        while True:
            body = c.get("/v2/warehouse/spans", params=params).raise_for_status().json()["spans"]
            yield from body["data"]
            if not body.get("next_cursor"):
                break
            params["cursor"] = body["next_cursor"]
```

Sources: [API intro](https://www.traceloop.com/docs/api-reference/introduction) ·
[Get Spans](https://www.traceloop.com/docs/api-reference/warehouse/get_spans) ·
[pricing](https://www.traceloop.com/pricing) ·
[hybrid self-host](https://www.traceloop.com/docs/self-host/hybrid-deployment) ·
[acquisition (Calcalist)](https://www.calcalistech.com/ctechnews/article/sjghwiqf11e)

---

## 4. What this means for AK's design

```
                     ┌──────────────────────────────────────────────┐
  AK eval run  ────▶ │ TraceSource interface                        │
  (time window,      │   fetch(window, filter: kind=tool/llm/agent, │
   kind filter,      │         session_id, name, ...) -> spans      │
   session…)         └───────┬──────────────┬──────────────┬────────┘
                             ▼              ▼              ▼
                     LangfuseSource   LogfireSource   TraceloopSource
                     (SDK v2 obs.)    (SQL query)     (REST warehouse)
                             │              │              │
                             ▼              ▼              ▼
                   Langfuse model     ~raw OTel        ~raw OTel
                             └──────────────┼──────────────┘
                                            ▼
                         Normaliser → AK Trace model → evaluators
```

- **One `TraceSource` interface, one implementation per provider.** It translates AK's generic filter
  (time window, span kind, session id, name) into each provider's query language:
  - Langfuse: params / JSON `filter`
  - Logfire: SQL
  - Traceloop: `filters` JSON
- **The normaliser input changes per provider:**
  - Langfuse returns **its own observation model**, which needs a Langfuse-specific mapper. Its type
    mapping (TOOL/GENERATION/AGENT) already normalises a lot, though.
  - Logfire and Traceloop return **near-raw OTel**, so the per-span convention mappers from
    [span-formats.md](span-formats.md) still apply.
- **The "tool calls only" filter differs per provider:**
  - Langfuse: `type="TOOL"`
  - Logfire: `gen_ai.operation.name='execute_tool'` **or** `span_name='Function: {name}'` (it depends
    on the framework instrumentation)
  - Traceloop: `traceloop.span.kind=tool`
  - AK should hide this behind one `kind=tool` option.
- **Handle each provider's limits:**
  - Langfuse: rate-limit backoff, smaller pages when fetching io
  - Logfire: split windows to stay under 10k rows, 5-min delay
  - Traceloop: 24 h retention on free, so fetch at least daily or warn the user
- **Credentials:** Logfire needs a separate **read token** (new config). Langfuse and Traceloop reuse
  the existing keys.
- **Fetch spans, then whole traces:** to evaluate a tool call in context, first fetch the matching
  spans, then fetch their full traces by trace_id. That's easy on Langfuse and Logfire, and only
  undocumented on Traceloop.

## 5. Still to verify (needs real accounts/keys)
- [ ] Langfuse: `type="TOOL"` actually returns our OpenInference/gen_ai tool spans; the exact JSON
      `filter` shape for `stringOptions` "any of".
- [ ] Logfire: real attribute JSON round-trip (nested JSON queryable with `->>`); actual rate-limit numbers.
- [ ] Traceloop: which filter ids work (`traceloop.span.kind` vs `llm.*` renaming); max `limit`; rate
      limits; whether the undocumented whole-trace endpoint is usable with a normal API key.
- [ ] Reads are free on all three (inferred from pricing pages; not stated anywhere).

---

## 6. AWS CloudWatch (added after #794)

**Sources:** AWS docs (Transaction Search, the span log group, `StartQuery` API reference, CloudWatch Logs
quotas), the installed botocore 1.43.86 service model, and the AK tracer in `trace/cloudwatch/`. **No live
calls were made.**

- **Where spans live.** With Transaction Search enabled, "spans sent to X-Ray are ingested in a log group
  called `aws/spans`", "stored in the semantic convention format with W3C trace IDs". The AK tracer exports
  to the X-Ray OTLP endpoint, and its docs make Transaction Search a prerequisite
  (`docs/docs/advanced/traceability.md` §AWS Prerequisites). So `aws/spans` holds every AK span.
  - Spans exported to a collector or the CloudWatch agent land there only if those forward to X-Ray.
  - `PutLogEvents` cannot write to `aws/spans`, and its data cannot be transformed.
- **Read API.** CloudWatch Logs Insights over `aws/spans`: `StartQuery`, then poll `GetQueryResults`.
  The X-Ray trace APIs (`GetTraceSummaries`, `BatchGetTraces`) cover only the indexed trace summaries
  (1% by default), so they are not used.
- **Record shape** (from the awslabs `agentcore-investigation` skill's queries, not an AWS schema page; ⚠️
  verify live): OTel JSON with `traceId`, `spanId`, `parentSpanId`, `name`, `kind`, `startTimeUnixNano`,
  `endTimeUnixNano`, `status.code`, `attributes.*` (e.g. `attributes.session.id`,
  `attributes.gen_ai.operation.name`), `resource.attributes.*`, `scope.name`. Logs Insights flattens JSON,
  so filters use dotted paths such as `attributes.session.id = "..."`.
- **Session id.** The AK tracer stamps `session.id` on the run span and on every span started during the
  run (`trace/cloudwatch/cloudwatch.py:35-44`, `:93`), so a direct filter selects a whole session.
- **Limits** (`StartQuery` reference and quotas page):
  - Time range in epoch **seconds**, both ends inclusive.
  - `limit` up to 100,000, but one `GetQueryResults` call returns at most 10,000 rows; more need
    `nextToken`. AK pages by time with 10,000-row queries instead, because the `cloudwatch` extra allows
    botocore versions that may predate `nextToken`.
  - Queries time out after 60 minutes; up to 100 concurrent queries; `StartQuery` and `GetQueryResults` are
    throttled at 10 TPS per account and region.
- **Credentials.** The standard AWS chain. Reading needs `logs:StartQuery`, `logs:GetQueryResults` (and
  `logs:StopQuery` to cancel); the send-side `AWSXrayWriteOnlyAccess` does not grant them.
- **Cost.** Logs Insights bills by data scanned, so wide windows over busy accounts cost money.
- **Readable after.** Not documented by AWS. A third-party guide says spans can take up to 10 minutes to
  appear after Transaction Search is first enabled.
- **Retention.** Not documented for `aws/spans`; CloudWatch log groups keep data indefinitely unless a
  retention policy is set.

**Still to verify (live):**
- [ ] The `@message` JSON shape above, and whether `attributes` is stored flat or nested.
- [ ] What `@timestamp` is for a span (start or end). The fetcher pads the query range 15 minutes past
      `end` and applies the window to `startTimeUnixNano` locally, so either works.
- [ ] `attributes.openinference.span.kind = "TOOL"` filters match (dotted attribute keys inside the JSON).
- [ ] The delay before a span is queryable.

