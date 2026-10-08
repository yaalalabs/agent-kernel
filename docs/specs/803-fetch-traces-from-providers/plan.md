# #803: Fetch traces back from the tracing providers' clouds — Implementation Plan

Builds [spec.md](spec.md) in order. Every iteration leaves the branch green: `make lint-check-all`
passes, and so does the trace test set from spec.md §Testing.

## Iteration 1: Neutral model and facade

- **Goal:** `Trace.get().fetch(...)` exists. It raises `NotImplementedError` for every tracer and
  `AKConfigError` when tracing is disabled.
- **Files:** `trace/fetch.py` (new), `trace/base.py`, `trace/trace.py`, `trace/__init__.py`,
  `tests/test_trace_fetch.py` (new).
- **Steps:**
  1. Add `SpanKind`, `TraceQuery`, `FetchedSpan` and `OTelSpanClassifier` (spec §`trace/fetch.py`).
  2. Add the non-abstract `BaseTrace.fetch` and `Trace.fetch` (spec §`BaseTrace.fetch` and `Trace.fetch`).
  3. Export the three public names from `agentkernel.trace`.
  4. Write the `TestTraceQuery`, `TestOTelSpanClassifier` and `TestTraceFetch` tests, plus the
     `oldest_first` test.
- **Verify:** `uv run pytest tests/test_trace_fetch.py tests/test_trace.py`

## Iteration 2: Langfuse fetcher

- **Goal:** `trace.type: langfuse` fetches observations through the v2 API.
- **Files:** `trace/langfuse/fetch.py` (new), `trace/langfuse/langfuse.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `LangfuseTraceFetcher` (spec §`LangFuse.fetch`).
  2. Add `LangFuse.fetch`, which delegates to it.
  3. Add `TestLangfuseFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Langfuse tests/test_trace_langfuse_langgraph.py`

## Iteration 3: Logfire fetcher and scrubbing fix

- **Goal:** `trace.type: logfire` fetches spans over SQL with `LOGFIRE_READ_TOKEN`, and new runs export
  an unscrubbed `session_id`.
- **Files:** `trace/logfire/fetch.py` (new), `trace/logfire/logfire.py`, `tests/test_trace_fetch.py`,
  `tests/test_trace_logfire.py`.
- **Steps:**
  1. Add `LogfireTraceFetcher` (spec §`Logfire.fetch`).
  2. Add `Logfire.fetch`.
  3. Add the `ScrubbingOptions` callback to `init()` (spec §Scrubbing fix).
  4. Add `ScrubbingOptions` to the `fake_logfire` fixture, plus the scrubbing test.
  5. Add `TestLogfireFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Logfire tests/test_trace_logfire.py`

## Iteration 4: Traceloop fetcher and extras

- **Goal:** `trace.type: openllmetry` fetches spans over the warehouse REST API, and both extras
  declare `httpx`.
- **Files:** `trace/openllmetry/fetch.py` (new), `trace/openllmetry/openllmetry.py`,
  `ak-py/pyproject.toml`, `ak-py/uv.lock`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `TraceloopTraceFetcher` (spec §`OpenLLMetry.fetch`).
  2. Add `OpenLLMetry.fetch`.
  3. Add `httpx>=0.27.0` to the `openllmetry` and `logfire` extras, then run `uv lock`.
  4. Add `TestTraceloopFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Traceloop`

## Iteration 5: CloudWatch fetcher

- **Goal:** `trace.type: cloudwatch` fetches spans from `aws/spans` through CloudWatch Logs Insights.
- **Files:** `trace/cloudwatch/fetch.py` (new), `trace/cloudwatch/cloudwatch.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Lift the region lookup in `CloudWatch._exporter()` (`trace/cloudwatch/cloudwatch.py:137`) into the
     static `CloudWatch.region()`, with no change to the exporter's behaviour or errors.
  2. Add `CloudWatchTraceFetcher` (spec §`CloudWatch.fetch`).
  3. Add `CloudWatch.fetch`.
  4. Add `TestCloudWatchFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k CloudWatch tests/test_trace_cloudwatch.py`

## Iteration 6: Tests and live verification

- **Goal:** the whole trace suite passes, and the provider assumptions are confirmed against real
  accounts.
- **Steps:**
  1. Run the full trace suite and lint (spec §Testing → Run).
  2. Run the manual live checks in spec §Testing against free-tier Langfuse, Logfire and Traceloop
     projects, and an AWS account with Transaction Search enabled. Record the results in
     `research/provider-read-apis.md` §5 and §6.
  3. Fix any filter ids or field names the live checks contradict. Any change to the result contract
     goes back to design.md.
- **Verify:**
  - `cd ak-py && uv run pytest tests/test_trace_fetch.py tests/test_trace_logfire.py tests/test_trace.py tests/test_trace_langfuse_langgraph.py tests/test_trace_cloudwatch.py`
  - `make lint-check-all`

## Iteration 7: Sync docs and skills

- **User docs:**
  - `docs/docs/advanced/traceability.md`: add a "Fetching Traces Back" section between
    "Viewing Traces in CloudWatch" (`:570`) and "Integrate with Your Own Traceability Platform" (`:576`).
    It covers the filters, `FetchedSpan`, credentials per provider (including CloudWatch's IAM read
    permissions), provider limits, and bring-your-own `fetch`.
- **Dev skills:**
  - `.agents/skills/ak-dev-new-tracing-provider/SKILL.md`:
    - §Architecture Overview (`:18`): mention the optional `fetch`.
    - New step after §5 (`:174`): implement `trace/<provider>/fetch.py` (rules 1–5 of spec §Rules).
    - §Checklist (`:299`): add a fetcher item.
  - `.agents/skills/ak-dev-architecture/SKILL.md`, directory tree (`:1053-1059`): add `fetch.py`, and
    note the per-provider `fetch.py` on the four adapters.
- **Bundled skill:**
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`, §Tracing (`:172-271`): add a short
    "read traces back" note with `Trace.get().fetch(...)`, `LOGFIRE_READ_TOKEN`, and the CloudWatch
    `logs:StartQuery` / `logs:GetQueryResults` / `logs:StopQuery` permissions.
- **No update needed** (verified): `ak-dev-new-framework-integration` only refers to the per-framework
  `BaseTrace` methods (`:384`, `:399`, `:439-440`), which are unchanged. Config docs are unaffected, because there
  are no `AKConfig` changes.
- Confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.
