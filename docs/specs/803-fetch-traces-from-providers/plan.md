# #803: Agent evaluation on production traffic — Implementation Plan

Builds [spec.md](spec.md) in order. Every iteration leaves the branch green: `make lint-check-all`
passes, and so do the tests named in its **Verify** line.

Phase 1 (iterations 1–7) lands first: the example in Phases 2–3 (iterations 8–14) imports `fetch` and
`SpanUsage`, and builds against the local `ak-py` wheel until a release contains them.

## Phase 1: Fetch traces (Agent Kernel core)

### Iteration 1: Neutral model and facade

- **Goal:** `Trace.get().fetch(...)` exists. It raises `NotImplementedError` for every tracer and
  `AKConfigError` when tracing is disabled.
- **Files:** `trace/fetch.py` (new), `trace/base.py`, `trace/trace.py`, `trace/__init__.py`,
  `tests/test_trace_fetch.py` (new).
- **Steps:**
  1. Add `SpanKind`, `TraceQuery`, `SpanUsage`, `FetchedSpan` and `OTelSpanClassifier`, including
     `OTelSpanClassifier.usage` (spec §`trace/fetch.py`).
  2. Add the non-abstract `BaseTrace.fetch` and `Trace.fetch` (spec §`BaseTrace.fetch` and `Trace.fetch`).
  3. Export the four public names from `agentkernel.trace`.
  4. Add `TraceQuery.matches` (spec §`trace/fetch.py`).
  5. Add `TraceFetchContract` in `trace/testing.py`, with the in-memory bring-your-own subclass in
     `tests/test_trace_fetch_contract.py` (spec §`trace/testing.py`).
  6. Write the `TestTraceQuery` (including `matches`), `TestOTelSpanClassifier` (including the `usage`
     cases) and `TestTraceFetch` tests, plus the `oldest_first` test.
- **Verify:** `uv run pytest tests/test_trace_fetch.py tests/test_trace_fetch_contract.py tests/test_trace.py`

### Iteration 2: Langfuse fetcher

- **Goal:** `trace.type: langfuse` fetches observations through the v2 API.
- **Files:** `trace/langfuse/fetch.py` (new), `trace/langfuse/langfuse.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `LangfuseTraceFetcher` (spec §`LangFuse.fetch`), including the `_usage` mapping,
     `expand_metadata`, the `matches` re-check and the repeated-cursor stop.
  2. Add `LangFuse.fetch`, which delegates to it.
  3. Add `LangFuse.flush_on_lambda` and call it from a `finally` in the six runners (spec §Langfuse
     flush on AWS Lambda).
  4. Add `TestLangfuseFetcher`, `TestLangfuseFetchContract` and `TestLangFuseLambdaFlush`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Langfuse tests/test_trace_langfuse_langgraph.py`

### Iteration 3: Logfire fetcher and scrubbing fix

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

### Iteration 4: Traceloop fetcher and extras

- **Goal:** `trace.type: openllmetry` fetches spans over the warehouse REST API, and both extras
  declare `httpx`.
- **Files:** `trace/openllmetry/fetch.py` (new), `trace/openllmetry/openllmetry.py`,
  `ak-py/pyproject.toml`, `ak-py/uv.lock`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Add `TraceloopTraceFetcher` (spec §`OpenLLMetry.fetch`), with the `matches` re-check, the
     `ceil(end)` bound and the repeated-cursor stop.
  2. Add `OpenLLMetry.fetch`.
  3. Add `httpx>=0.27.0` to the `openllmetry` and `logfire` extras, then run `uv lock`.
  4. Add `TestTraceloopFetcher` and `TestTraceloopFetchContract`.
- **Verify:** `uv run pytest tests/test_trace_fetch.py -k Traceloop`

### Iteration 5: CloudWatch fetcher

- **Goal:** `trace.type: cloudwatch` fetches spans from `aws/spans` through CloudWatch Logs Insights.
- **Files:** `trace/cloudwatch/fetch.py` (new), `trace/cloudwatch/cloudwatch.py`, `tests/test_trace_fetch.py`.
- **Steps:**
  1. Lift the region lookup in `CloudWatch._exporter()` (`trace/cloudwatch/cloudwatch.py:137`) into the
     static `CloudWatch.region()`, with no change to the exporter's behaviour or errors.
  2. Add `CloudWatchTraceFetcher` (spec §`CloudWatch.fetch`).
  3. Add `CloudWatch.fetch`.
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
  `test_trace_langfuse_langgraph` and `test_trace_cloudwatch`; `make lint-check-all` before raising the PR.

### Iteration 7: Sync docs and skills

- **User docs:**
  - `docs/docs/advanced/traceability.md`: add a "Fetching Traces Back" section between
    "Viewing Traces in CloudWatch" (`:570`) and "Integrate with Your Own Traceability Platform" (`:576`).
    It covers the filters, `FetchedSpan` and `usage` (totalling it over a trace, which providers report
    cost), Traceloop fetching as best effort, bring-your-own `fetch` tested with `TraceFetchContract`,
    the Langfuse flush on Lambda, credentials per provider (including CloudWatch's IAM read
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
    "read traces back" note with `Trace.get().fetch(...)`, `span.usage`, `LOGFIRE_READ_TOKEN`, and the CloudWatch
    `logs:StartQuery` / `logs:GetQueryResults` / `logs:StopQuery` permissions.
- **No update needed** (verified): `ak-dev-new-framework-integration` only refers to the per-framework
  `BaseTrace` methods (`:384`, `:399`, `:439-440`), which are unchanged. Config docs are unaffected, because there
  are no `AKConfig` changes.
- Confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge.

## Phases 2–3: Evaluate and store (example)

All files are under `examples/aws-serverless/langfuse-trace-evaluation/` unless a path says otherwise.

### Before merge: owner tasks (not code)

- [ ] Create a Langfuse Cloud project for CI; add repository secrets `LANGFUSE_PUBLIC_KEY`,
      `LANGFUSE_SECRET_KEY` and variable `LANGFUSE_BASE_URL`.
- [ ] Extend the weekly CI AWS role (`vars.AWS_ROLE_NAME`, managed outside this repo) with the
      permissions in design.md §Open questions → Phases 2 and 3.
- [ ] Run the Phase 1 live checks against real accounts (iteration 6).

### Iteration 8: Example scaffold and the agent

- **Goal:** the agent deploys on its own, answers, and its traces appear in Langfuse.
- **Files:** `pyproject.toml`, `uv.lock`, `config.yaml`, `test-config.yaml`, `lambda.py`, `build.sh`,
  `deploy/{main.tf,variables.tf,outputs.tf,providers.tf,backend.tf,terraform.tfvars,deploy.sh,Dockerfile.agent}`.
- **Steps:**
  1. `pyproject.toml` with the `agent` and `evaluator` extras and the `dev` group (spec §`pyproject.toml`);
     `uv lock`.
  2. The agent, with `handler = Lambda.handler` (spec §The agent).
  3. `simulate_traffic.py` with `TrafficSimulator.send()` only (spec §`simulate_traffic.py`).
  4. `main.tf` with `module "serverless_agents"` only, plus variables, outputs (`agent_invoke_url`),
     providers and backend (spec §Deployment).
  5. `deploy.sh` building `dist_agent`.
- **Verify:** `cd deploy && ./deploy.sh local`; `uv run python simulate_traffic.py --no-evaluate`; the 5
  traces (root, agents, tool, generations) show in the Langfuse UI within a minute, without waiting for
  another request (the Lambda flush); `terraform destroy`.

### Iteration 9: Phase 2: trace cases and the Opik evaluator

- **Goal:** a trace's spans become a `TraceCase`, and each of the four metrics scores it.
- **Files:** `evaluator/{__init__,case,opik_evaluator}.py`, `tests/test_evaluator.py`.
- **Steps:**
  1. `ToolCall`, `TraceCase`, `TraceEvaluationCase` (spec §`evaluator/case.py`).
  2. `OpikTraceEvaluator` with the metric table, the pass rules and the two-attempt rule (spec
     §`evaluator/opik_evaluator.py`).
  3. The span fixtures, `TestTraceCase` and `TestOpikTraceEvaluator` (spec §Phases 2–3 testing).
- **Verify:** `./build.sh local && uv run pytest tests/ -k "TraceCase or OpikTraceEvaluator"`

### Iteration 10: Phase 3: the DynamoDB store

- **Goal:** results and traces are written idempotently, `TRACE` last, with the size guards.
- **Files:** `evaluator/store.py`, `tests/test_evaluator.py`.
- **Steps:**
  1. `EvaluationStore` (spec §`evaluator/store.py`).
  2. `TestEvaluationStore` on `moto`, with the table schema from spec §Deployment.
- **Verify:** `uv run pytest tests/ -k EvaluationStore`

### Iteration 11: The job and the Lambda entry point

- **Goal:** one `run(event)` fetches, owns, skips, evaluates, stores and moves the watermark.
- **Files:** `evaluator/{job,handler}.py`, `tests/test_evaluator.py`.
- **Steps:**
  1. `EvaluationWindow`, `RunSummary`, `TraceEvaluationJob` (spec §`evaluator/job.py`).
  2. `handler` with the per-sandbox job holder.
  3. `TestTraceEvaluationJob`.
  4. `TrafficSimulator.evaluate()` and `report()`, the CLI, and `TestTrafficSimulator`.
- **Verify:** `uv run pytest -o addopts="" tests/test_evaluator.py`

### Iteration 12: Evaluator infrastructure

- **Goal:** `./deploy.sh local` deploys the agent and the scheduled evaluator together.
- **Files:** `deploy/{main.tf,variables.tf,outputs.tf,providers.tf,deploy.sh,Dockerfile.evaluator}`.
- **Steps:**
  1. `module "evaluator_image"`, `module "evaluator"`, `aws_dynamodb_table.results`, the EventBridge
     rule and target (spec §Deployment).
  2. The new variables and the `evaluator_function_name` / `results_table_name` outputs.
  3. `deploy.sh` also builds `dist_evaluator`.
- **Verify:**
  - `terraform validate`; `./deploy.sh local`.
  - `uv run python simulate_traffic.py`: 5 replies, then a table of 5 traces with their scores; the
    `TRACE` and `EVAL#…` items are in the table.
  - After 30 minutes, the scheduled run's log shows a summary and the `#job` watermark exists.

### Iteration 13: Weekly integration test and CI wiring

- **Goal:** the weekly pipeline deploys, tests and destroys the example.
- **Files:** `lambda_test.py`, `.github/integration-test-config.yaml`,
  `.github/workflows/integration-test-weekly.yaml`.
- **Steps:**
  1. `lambda_test.py`, driving `TrafficSimulator` (spec §Phases 2–3 testing → weekly integration test).
  2. The weekly config entry and the three `TF_VAR_langfuse_*` env entries on Deploy, Test and Destroy
     (spec §Consumer changes).
  3. Needs the owner tasks above (CI Langfuse project, role permissions).
- **Verify:**
  - `python3 .github/scripts/validate_integration_config.py`.
  - Locally: `AK_TEST_ENDPOINT=... uv run pytest lambda_test.py` against iteration 12's deployment.
  - A manual `workflow_dispatch` of Weekly Integration Tests passes the new matrix entry, including
    Destroy.

### Iteration 14: Docs and skills for Phases 2–3

- **Example docs:** `README.md`: architecture (agent → Langfuse → scheduled evaluator → DynamoDB), the
  job flow and its fault handling, the metrics, the table schema and the two indexes, how to swap
  metrics or the store, required variables, deploy and test.
- **User docs:**
  - `docs/docs/examples/overview.md` §AWS Serverless Examples: list the example.
  - `docs/docs/advanced/traceability.md` §Fetching Traces Back: one line linking the example as the
    end-to-end use of `fetch` and `usage`.
- **Skills:**
  - Bundled `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` §Tracing: point the "read traces
    back" note (iteration 7) at the example.
  - Dev skills: none expected; confirm with `ak-dev-sync-skills-from-branch`. Run
    `ak-dev-sync-docs-from-branch` too.

