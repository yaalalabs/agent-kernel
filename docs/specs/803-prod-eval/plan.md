# #803: Agent evaluation on production traffic — Implementation Plan

Builds [spec.md](spec.md) in order. Every iteration leaves the branch green: `make lint-check-all`
passes, and so do the tests named in its **Verify** line.

Phase 1 (iterations 1–7) lands first: the example in Phases 2–3 (iterations 8–14) imports `fetch_spans` /
`fetch_traces` and `SpanUsage`, and builds against the local `ak-py` wheel until a release contains them.

## Phase 1: Fetch spans (Agent Kernel core)

### Iteration 1: Neutral model and facade

- **Goal:** `Trace.get().fetch_spans(...)` exists. It raises `NotImplementedError` for every tracer and
  `AKConfigError` when tracing is disabled.
- **Files:** `trace/fetch.py` (new), `trace/base.py`, `trace/trace.py`, `trace/__init__.py`,
  `tests/test_trace_fetch.py` (new).
- **Steps:**
  1. Add `SpanKind`, `TraceQuery`, `SpanUsage`, `FetchedSpan` and `OTelSpanClassifier`, including
     `OTelSpanClassifier.usage` (spec §`trace/fetch.py`).
  2. Add the `TraceFetcher` base: the pinned window, the merge, `_fetch_by_cursor` and `_fetch_by_time_window`
     (spec §`trace/fetch.py`).
  3. Add the non-abstract `BaseTrace.fetch_spans` and `Trace.fetch_spans` (spec §`BaseTrace.fetch_spans` and `Trace.fetch_spans`).
  4. Export the five public names (`TraceQuery`, `FetchedSpan`, `SpanUsage`, `SpanKind`,
     `OTelSpanClassifier`) from `agentkernel.trace`. `TraceFetcher` stays internal.
  5. Add `TraceQuery.matches` (spec §`trace/fetch.py`).
  6. Add `TraceFetchContract` in `trace/testing.py`, with the in-memory bring-your-own subclass in
     `tests/test_trace_fetch_contract.py` (spec §`trace/testing.py`).
  7. Write the `TestTraceQuery` (including `matches`), `TestOTelSpanClassifier` (including the `usage`
     cases), `TestTraceFetch` and `TestTraceFetcher` tests, plus the `oldest_first` test.
- **Verify:** `uv run pytest tests/test_trace_fetch.py tests/test_trace_fetch_contract.py tests/test_trace.py`

### Iteration 2: Langfuse fetcher

- **Goal:** `trace.type: langfuse` fetches observations through the v2 API.
- **Files:** `trace/langfuse/fetch.py` (new), `trace/langfuse/langfuse.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `LangfuseTraceFetcher(TraceFetcher)` (spec §`LangFuse.fetch_spans`), including the `_usage` mapping,
     `expand_metadata` and one `_fetch_by_cursor` per request-matrix cell.
  2. Add `LangFuse.fetch_spans`, which delegates to it.
  3. Add `LangFuse.flush_on_lambda` and call it from a `finally` in the six runners (spec §Langfuse
     flush on AWS Lambda).
  4. Add `TestLangfuseFetcher`, `TestLangfuseFetchContract`, and `TestRunnersFlush` (parametrized over all six
     runners) plus `TestFlushOnLambda` in `tests/test_trace_langfuse_flush.py`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Langfuse tests/test_trace_langfuse_langgraph.py tests/test_trace_langfuse_flush.py`

### Iteration 3: Logfire fetcher and scrubbing fix

- **Goal:** `trace.type: logfire` fetches spans over SQL with `LOGFIRE_READ_TOKEN`, and new runs export
  an unscrubbed `session_id`.
- **Files:** `trace/logfire/fetch.py` (new), `trace/logfire/logfire.py`, `tests/test_trace_fetch.py`,
  `tests/test_trace_logfire.py`.
- **Steps:**
  1. Add `LogfireTraceFetcher(TraceFetcher)` (spec §`Logfire.fetch_spans`), paging through `_fetch_by_time_window`.
  2. Add `Logfire.fetch_spans`, which resolves `LOGFIRE_READ_TOKEN` through `SecretManager`.
  3. Add the `ScrubbingOptions` callback to `init()` (spec §Scrubbing fix).
  4. Add `ScrubbingOptions` to the `fake_logfire` fixture, plus the scrubbing test.
  5. Add `TestLogfireFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Logfire tests/test_trace_logfire.py`

### Iteration 4: Traceloop fetcher and extras

- **Goal:** `trace.type: openllmetry` fetches spans over the warehouse REST API, and both extras
  declare `httpx`.
- **Files:** `trace/openllmetry/fetch.py` (new), `trace/openllmetry/openllmetry.py`,
  `ak-py/pyproject.toml`, `ak-py/uv.lock`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `TraceloopTraceFetcher(TraceFetcher)` (spec §`OpenLLMetry.fetch_spans`), with the `ceil(end)` bound,
     one `_fetch_by_cursor`, and no server-side kind filter.
  2. Add `OpenLLMetry.fetch_spans`, which resolves `TRACELOOP_API_KEY` through `SecretManager`.
  3. Add `httpx>=0.27.0` to the `openllmetry` and `logfire` extras, then run `uv lock`.
  4. Add `TestTraceloopFetcher` (including the `traceloop.span.kind`-only tool span) and
     `TestTraceloopFetchContract`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Traceloop`

### Iteration 5: CloudWatch fetcher

- **Goal:** `trace.type: cloudwatch` fetches spans from `aws/spans` through CloudWatch Logs Insights.
- **Files:** `trace/cloudwatch/fetch.py` (new), `trace/cloudwatch/cloudwatch.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Lift the region lookup in `CloudWatch._exporter()` (`trace/cloudwatch/cloudwatch.py:146`) into the
     static `CloudWatch.region(botocore_session)`, with no change to the exporter's behaviour or errors.
  2. Add `CloudWatchTraceFetcher(TraceFetcher)` (spec §`CloudWatch.fetch_spans`), paging through
     `_fetch_by_time_window`.
  3. Add `CloudWatch.fetch_spans`.
  4. Add `TestCloudWatchFetcher`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k CloudWatch tests/test_trace_cloudwatch.py`

### Iteration 6: Tests and live verification

- **Goal:** the whole trace suite passes, and the provider assumptions are confirmed against real
  accounts.
- **Steps:**
  1. Run the full trace suite and lint (spec §Phase 1 testing → Run).
  2. Run the manual live checks in spec §Phase 1 testing against free-tier Langfuse, Logfire and Traceloop
     projects, and an AWS account with Transaction Search enabled. Record the results in
     `research/provider-read-apis.md` §5 and §6.
  3. Fix any filter ids or field names the live checks contradict. Any change to the result contract
     goes back to design.md.
- **Verify:** each file on its own, `cd ak-py && uv run pytest -o addopts="" tests/<file>.py`, for
  `test_trace_fetch`, `test_trace_fetch_contract`, `test_trace_logfire`, `test_trace`,
  `test_trace_langfuse_langgraph`, `test_trace_langfuse_flush` and `test_trace_cloudwatch`; `make lint-check-all` before raising the PR.

### Iteration 7: Sync docs and skills

- **User docs:**
  - `docs/docs/advanced/traceability.md`: add a "Fetching Spans Back" section between
    "Viewing Traces in CloudWatch" (`:570`) and "Integrate with Your Own Traceability Platform" (`:576`).
    It covers the filters, `FetchedSpan` and `usage` (totalling it over a trace, which providers report
    cost), Traceloop fetching as best effort, session ids reaching every provider unscrubbed (keep personal data
    out of them), bring-your-own `fetch_spans` tested with `TraceFetchContract`,
    credentials per provider (including CloudWatch's IAM read permissions, and the two keys AK resolves
    through `SecretManager`), and provider limits.
  - `docs/docs/advanced/traceability.md`, Langfuse section: a "Running on AWS Lambda" note, worded like
    the CloudWatch one (`:566`). The Langfuse runners now flush after every `run()` on Lambda; streamed
    runs don't. This is a send-side change, so it doesn't go in "Fetching Spans Back".
  - `docs/src/pages/features.tsx`, Observability card highlights (`:903-910`): add "Fetch spans back
    for evaluation".
  - `docs/docs/intro.md`, What's New tip (`:10`): one entry for fetching spans back, linking
    "Fetching Spans Back".
- **Dev skills:**
  - `.agents/skills/ak-dev-new-tracing-provider/SKILL.md`:
    - §Architecture Overview (`:18`): mention the optional `fetch_spans`.
    - New step after §5 (`:174`): implement `trace/<provider>/fetch.py` on `TraceFetcher` (rules 1–7 of
      spec §Rules).
    - §Checklist (`:299`): add a fetcher item.
  - `.agents/skills/ak-dev-architecture/SKILL.md`, directory tree (`:1053-1059`): add `fetch.py`, and
    note the per-provider `fetch.py` on the four adapters.
- **Bundled skill:**
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`, §Tracing (`:172-271`): add a short
    "fetch spans back" note with `Trace.get().fetch_spans(...)`, `span.usage`, `LOGFIRE_READ_TOKEN`, and the CloudWatch
    `logs:StartQuery` / `logs:GetQueryResults` / `logs:StopQuery` permissions.
- **No update needed** (verified): `ak-dev-new-framework-integration` only refers to the per-framework
  `BaseTrace` methods (`:384`, `:399`, `:439-440`), which are unchanged. Config docs are unaffected, because there
  are no `AKConfig` changes.
- Confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.

## Phases 2–3: Evaluate and store (example)

All files are under `examples/aws-serverless/openai-langfuse-trace-evaluation/` unless a path says otherwise.
The example runs in queue mode (`queue_mode = true`, `execution_mode = "rest_sync"`) with three Lambdas:
`lambda_request_handler.py` (ingress plus `/eval`, `/check` and the internal `/grade`), `lambda_agent_runner.py`
(the agent) and `lambda_response_handler.py`. It has no unit-test suite; `lambda_test.py` is its only test.

### Before merge: owner tasks (not code)

- [ ] Create a Langfuse Cloud project for CI; add repository secrets `LANGFUSE_PUBLIC_KEY`,
      `LANGFUSE_SECRET_KEY` and variable `LANGFUSE_BASE_URL`.
- [ ] Run the Phase 1 live checks against real accounts (iteration 6).

### Iteration 8: Example scaffold, the agent and the traffic

- **Goal:** the agent deploys on its own, answers, and its traces appear in Langfuse.
- **Files:** `pyproject.toml`, `uv.lock`, `config.yaml`, `lambda_request_handler.py`, `lambda_agent_runner.py`,
  `lambda_response_handler.py`, `simulate_traffic.py`, `build.sh`,
  `deploy/{main.tf,variables.tf,outputs.tf,providers.tf,terraform.tfvars,deploy.sh,Dockerfile.request_handler,Dockerfile.agent_runner}`.
- **Steps:**
  1. `pyproject.toml` with the runtime dependencies and the `dev` group (spec §`pyproject.toml`); `uv lock`.
  2. `lambda_agent_runner.py` with the triage and support agents and the `get_order_status` tool;
     `lambda_request_handler.py` with `handler = Lambda.handler`; `lambda_response_handler.py` with
     `ResponseHandler.handle` (spec §The agent and the wiring).
  3. `TrafficSimulator` and its CLI (spec §`simulate_traffic.py`).
  4. `main.tf` with `module "serverless_agents"` (no `gateway_endpoints` yet), plus variables, outputs
     (`agent_invoke_url`), providers and backend (spec §Deployment).
  5. `deploy.sh` building `dist_request_handler`, `dist_agent_runner` and `dist_response_handler`.
- **Verify:** `cd deploy && ./deploy.sh local`; `uv run python simulate_traffic.py`; the 3 traces (root,
  agents, tool, generations) show in the Langfuse UI under the printed session id within a minute, without
  waiting for another request (the Lambda flush); `terraform destroy`.

### Iteration 9: Phase 2: trace cases and the Opik evaluator

- **Goal:** a trace's spans become a `TraceCase`, and each of the four metrics scores it.
- **Files:** `evaluator/{__init__,case,opik_evaluator}.py`, `ak-py/src/agentkernel/test/__init__.py`.
- **Steps:**
  1. `ToolCall`, `TraceCase`, `TraceEvaluationCase` (spec §`evaluator/case.py`).
  2. `OpikTraceEvaluator` with the metric table, the pass rules and the two-attempt rule (spec
     §`evaluator/opik_evaluator.py`).
  3. Export `AKEvaluator`, `AKEvaluationCase`, `AKEvaluationResult`, `AKEvaluationError`, `AKMetricNotSupported`
     and `AKMissingInput` from `agentkernel.test`, so the example imports them from the public package.
- **Verify:** `./build.sh local`; the evaluator is exercised end to end in iteration 12.

### Iteration 10: Phase 3: the DynamoDB store

- **Goal:** each found trace has one row with its `progress`; a graded trace's row gets a column per
  metric in one atomic write, within the whole-item size budget; a session's rows can be counted by
  `progress`.
- **Files:** `evaluator/store.py`.
- **Steps:**
  1. `Progress`, `TraceProgress`, `SessionProgress` and `EvaluationStore`, including `read_progress`,
     `write_progress`, `save_results`, `mark_failed` and `count_session_progress` (spec §`evaluator/store.py`).
- **Verify:** exercised end to end in iteration 12.

### Iteration 11: The evaluation run and the API

- **Goal:** `/eval` sets every found trace's `progress` and starts grading the ready ones asynchronously,
  `grade` judges them, and `/check` counts the session's traces by `progress`.
- **Files:** `evaluator/{job,api}.py`, `lambda_request_handler.py`.
- **Steps:**
  1. `PrepareSummary`, `GradeSummary` and `TraceEvaluationJob` with `prepare_traces` and `grade_traces`
     (`FETCH_WINDOW`, `SETTLE_TIME`, `GRADING_LEASE`) (spec §`evaluator/job.py`).
  2. `EvaluationAPI` with `from_env`, `start_evaluation`, `check_progress` and `grade_traces` (spec §`evaluator/api.py`).
  3. `lambda_request_handler.py`: register `/eval` (POST), `/check` (GET) and the internal `/grade` (POST) with
     `Lambda.register`; keep `handler = Lambda.handler` (spec §The agent and the wiring).
- **Verify:** exercised end to end in iteration 12.

### Iteration 12: Evaluation infrastructure

- **Goal:** `./deploy.sh local` deploys the agent with `/eval` and `/check`, the results table and the
  Lambda's DynamoDB permissions.
- **Files:** `deploy/{main.tf,outputs.tf,deploy.sh}`.
- **Steps:**
  1. `gateway_endpoints`, the request handler's `timeout`, `memory_size` and evaluation environment
     variables on `module "serverless_agents"` (spec §Deployment).
  2. `aws_dynamodb_table.results` (with the `INCLUDE`-projected `session_id-index`),
     `aws_iam_role_policy.evaluation`, `aws_lambda_function_event_invoke_config.grading`
     (`maximum_retry_attempts = 0`) and the `results_table_name` output.
  3. `deploy.sh` also copies `evaluator/` into the request handler package (`dist_request_handler`).
- **Verify:**
  - `terraform validate`; `./deploy.sh local`.
  - `uv run python simulate_traffic.py`, wait 2.5 minutes (the job's settle time), then
    `curl -X POST .../eval` with the printed session id → `202` with `grading: 3`; poll
    `curl ".../check?session_id=...&expected=3"` until `complete` is `true`; the table holds 3 `graded`
    rows with their metric columns.
  - `/check` for an unknown session id → every count `0`, `complete` false.

### Iteration 13: Weekly integration test and CI wiring

- **Goal:** the weekly pipeline deploys, tests and destroys the example.
- **Files:** `lambda_test.py`, `.github/integration-test-config.yaml`,
  `.github/workflows/integration-test-weekly.yaml`.
- **Steps:**
  1. `lambda_test.py` with the `EvaluationClient` helper and `test_every_request_is_graded`, including the
     grading rounds (spec §Phases 2–3 testing → weekly integration test).
  2. The weekly config entry and the three `TF_VAR_langfuse_*` env entries on Deploy, Test and Destroy
     (spec §Consumer changes).
  3. Needs the owner task above (CI Langfuse project and secrets).
- **Verify:**
  - `python3 .github/scripts/validate_integration_config.py`.
  - Locally: `AK_TEST_ENDPOINT=... uv run pytest lambda_test.py` against iteration 12's deployment.
  - A manual `workflow_dispatch` of Weekly Integration Tests passes the new matrix entry, including
    Destroy.

### Iteration 14: Docs and skills for Phases 2–3

- **Example docs:** `README.md`: architecture (agent → Langfuse → `/eval` → DynamoDB → `/check`), the
  evaluation run and its fault handling, the metrics, the table schema, how to swap metrics or the store,
  required variables, deploy, `simulate_traffic.py` plus the `curl` calls to `/eval` and `/check`, and test.
- **User docs:**
  - `docs/docs/examples/overview.md` §AWS Serverless Examples: list the example.
  - `docs/docs/advanced/traceability.md` §Fetching Spans Back: one line linking the example as the
    end-to-end use of `fetch_traces` and `usage`.
  - `docs/src/pages/features.tsx`: no change. The "Pluggable Evaluators" card (`:1494`) covers the test
    framework's built-in evaluators; the example only subclasses `AKEvaluator`, and the Observability
    card (iteration 7) already covers fetching.
- **Skills:**
  - Bundled `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` §Tracing: point the "read traces
    back" note (iteration 7) at the example.
  - Dev skills: none expected; confirm with `ak-dev-sync-skills-from-branch`. Run
    `ak-dev-sync-docs-from-branch` too.

## Follow-up: whole traces and span status

Done after iterations 1–14, to take trace assembly out of the example. The rule behind it: AK maps each
provider's fields onto neutral ones but doesn't patch over a provider's own mistakes, and user code trusts what
the fetcher returns. Branch `feature/803-prod-eval-implementation` is unpublished, so renames are free.

### Iteration 15: `fetch_spans`, `fetch_traces` and `FetchedSpan.status` (library)

- **Goal:** `Trace.get().fetch_traces(...)` returns `FetchedTrace`s, and every `FetchedSpan` has a `status`.
- **Files:** `trace/fetch.py`, `trace/trace.py`, `trace/base.py`, `trace/testing.py`, `trace/__init__.py`,
  `trace/{langfuse,logfire,openllmetry,cloudwatch}/fetch.py` and their tracer classes,
  `tests/test_trace_fetch.py`, `tests/test_trace_fetch_contract.py`, `tests/test_trace_logfire.py`.
- **Steps:**
  1. Rename `Trace.fetch`, `BaseTrace.fetch` and `TraceFetcher.fetch` to `fetch_spans` (spec §`BaseTrace.fetch_spans`
     and `Trace.fetch_spans`).
  2. Add `FetchedTrace` and `Trace.fetch_traces`, built once on `fetch_spans` (spec §`FetchedTrace`).
  3. Add `SpanStatus` and `FetchedSpan.status`, mapped per fetcher (spec §`SpanStatus`).
  4. Export `FetchedTrace` and `SpanStatus`; add the `fetch_traces` case to `TraceFetchContract`.
  5. Tests: `SpanStatus.of`, `FetchedTrace` grouping, root / no root / two roots, usage sum, ordering,
     `fetch_traces` filter rejection, and a status test per fetcher.
- **Verify:** `uv run pytest tests/test_trace_fetch.py tests/test_trace_fetch_contract.py tests/test_trace_logfire.py tests/test_trace.py`

### Iteration 16: Example cleanup

- **Goal:** the example builds its `TraceCase` from a `FetchedTrace` and holds no trace-assembly code.
- **Files:** `evaluator/{case,job}.py` and `README.md` of `openai-langfuse-trace-evaluation`.
- **Steps:**
  1. `case.py`: remove `_span_kind`, `_sum_usage`, `spans_missing_parent` and the root finding; add
     `TraceCase.from_trace`; a tool call is failed when `status == ERROR`. Keep the provider-specific name and
     result readers.
  2. `job.py`: call `fetch_traces(last=FETCH_WINDOW, ...)` by `session_id` in `prepare_traces` and by `trace_ids`
     in `grade_traces`; skip `root is None` and count it in `PrepareSummary.no_root`; remove `FETCH_LIMIT` and its check. Keep `SETTLE_TIME`, the progress states and the "not found"
     handling in `/grade`.
  3. Update the README ("The evaluation run", the "public AK API" line).
- **Verify:** `./build.sh local`; `AK_TEST_ENDPOINT=... uv run pytest lambda_test.py` against a deployment.

### Iteration 17: Docs and skills

- `docs/docs/advanced/traceability.md` §Fetching Spans Back: the rename, `fetch_traces` and `FetchedTrace`,
  `status`, the Traceloop root note and partial traces at window edges. `docs/docs/intro.md` and
  `docs/docs/examples/overview.md`: the renamed call. `docs/docs/deployment/aws-serverless.md`: list the
  example. `docs/src/pages/index.tsx` and `docs/src/components/FeatureExplorer/data.tsx`: the span-fetch
  highlight and tag. `docs/docs/core-concepts/configuration.md` and `docs/docs/testing/cli-testing.md`: import
  `AKEvaluator` from `agentkernel.test`.
- Dev skills: `ak-dev-new-tracing-provider`, `ak-dev-architecture`, `ak-dev-testing-conventions`.
- Bundled skills: `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` and its `evals/evals.json`;
  `ak-test/SKILL.md` (the `agentkernel.test` import).
- **Open:** one live run of the Langfuse example to confirm tool spans come back as `TOOL`; the Logfire
  `otel_status_code` column and Traceloop's status field name are unverified against live accounts.
