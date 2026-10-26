# #786: Benchmark system for throughput, latency, scaling and cost — Implementation Plan

Ordering only; the *how* is in [`spec.md`](spec.md). The AK change lands first (it is small, testable in CI and
needed by every host). The benchmark project then grows host by host, following the build order in
[`design.md`](design.md#scope-phase-1): local baseline → ECS → scaling on ECS → Lambda → EKS → bare metal → cost.
Each iteration leaves both suites green:

```bash
cd ak-py && uv run pytest && cd .. && make lint-check-all
cd benchmarks && uv run pytest            # from iteration 2 on
```

Iterations 1 and 2 are the "steps 1-3" milestone (timestamps decided, harness + `ws_complete` driver, local
baseline). Iteration 1 is the only one that changes `ak-py` and can ship as its own PR.

## Iteration 1: Pipeline trace logger in AK

- **Goal:** `logging.pipeline_trace.enabled: true` makes every pipeline process write one `AK_TRACE` line per stage;
  off by default; the old stage INFO lines are gone.
- **Files:** new `ak-py/src/agentkernel/core/pipeline_trace.py`; `core/config.py`; `core/logger.py`; the files in
  spec.md § 3; tests listed in spec.md § Testing → AK.
- **Steps:**
  1. `TraceStage`, `PipelineTraceRecord`, `PipelineTraceFormatter`, `PipelineTraceParser`, `PipelineTrace`
     (spec.md § 1).
  2. `_PipelineTraceConfig` + `AKLogger.configure_from_config` call (spec.md § 2).
  3. Convert/add trace points in the shared `pipeline/` files, then ECS, then Lambda (spec.md § 3).
  4. Tests: `test_pipeline_trace.py`, logger/config cases, one stage-sequence case per traced component.
- **Verify:** `uv run pytest tests/test_pipeline_trace.py tests/test_ak_logger.py tests/test_config.py` and the
  per-component files; full suite; `make lint-check-all`.

## Iteration 2: Benchmark skeleton, `ws_complete` driver, local baseline

- **Goal:** `ak-bench run --host local --mode ws_complete` runs burst and steady steps against a locally started app
  and writes `requests.csv`, `windows.csv`, `summary.csv` (no scaling/cost columns) and the per-run latency and
  throughput graphs, with all stage columns filled from the local log file.
- **Files:** `benchmarks/` `pyproject.toml`, `README.md`, `bench.example.yaml`; `app/` (`mock_agent.py`, `auth.py`,
  `agent.py`, local entry point, `config.yaml`); `ak_bench/` `cli.py`, `config.py`, `model.py`, `orchestrator.py`,
  `load/`, `drivers/`, `platforms/base.py`, `platforms/local/`, `scaling/step_end.py` (client condition only),
  `results/`, `plots/per_run.py`, `hosts.py` (`local`); tests.
- **Steps:**
  1. Config, data types and ABCs (spec.md § 5, § 6).
  2. Mock agent and token validator (§ 14, § 8); local app in the single-process `in_memory` topology.
  3. `WsCompleteDriver` (§ 7), confirming the WS frame shapes against the pipeline gateway.
  4. `LoadGenerator`, `BurstLoad`, `SteadyLoad`, `StepRunner`, windows (§ 8).
  5. `LogFileTraceCollector`, `TraceJoiner` (§ 10); CSV writers and per-run plots (§ 15).
  6. `NoopDeployer`, `HostRegistry` with `local`, `BenchCLI` `run` and `plot` (§ 12, § 13).
- **Verify:** `uv run pytest`; `AK_BENCH_LOCAL=1 uv run pytest tests/test_local_smoke.py`; a manual local run of
  steps 1-100 at 0 ms and 500 ms delay with the graphs checked by eye.

## Iteration 3: ECS host (throughput, latency, traces)

- **Goal:** `ak-bench run --host ecs` deploys the app on ECS + SQS, runs the steps, collects traces from CloudWatch
  Logs and queue depth from SQS, and tears down.
- **Files:** `app/deploy/ecs/` (Terraform root, outputs), ECS entry points and Dockerfile; `platforms/aws/`
  `session.py`, `terraform_deployer.py`, `cloudwatch_logs.py`, `cloudwatch_logs_traces.py`; `transports/sqs.py`;
  `hosts.py` (`ecs`, without fetchers yet).
- **Steps:**
  1. `TerraformDeployer` with run tagging, env injection, confirmation prompt, teardown in `finally` (§ 12, § 13).
  2. `CloudWatchLogsQuery` + `CloudWatchLogsTraceCollector` (§ 10).
  3. `SqsTransportCollector`; queue columns in windows; cool-down condition 2 (§ 9).
- **Verify:** unit tests with `Stubber`; one manual ECS run of steps 1-100, checking every ok request has its stage
  columns and the deployment is destroyed afterwards.

## Iteration 4: Scaling collection on ECS

- **Goal:** worker counts per tier and fetcher in `windows.csv`, scaling numbers in `summary.csv`, the full step-end
  rule, and the scaling graphs, on ECS. Optional `scaling` test type if Q2 keeps it.
- **Files:** `platforms/aws/ecs_api_scaling.py`, `ecs_scaling_activities_scaling.py`; `scaling/collector.py`,
  `windows.py`, `derived.py`, `step_end.py` (all three conditions); `load/steps.py` (`ScalingLoad`);
  `plots/per_run.py` scaling graphs; `hosts.py` (`ecs` fetchers).
- **Steps:**
  1. `ScalingCollector` live polling and after-run collection, `collect-scaling` command (§ 9, § 13).
  2. `WindowBuilder`, `ScalingDeriver`, summary columns (§ 9, § 15).
  3. ECS fetchers; ECS deploy defaults with autoscaling on (§ 12).
  4. `ScalingLoad` (only if Q2 keeps the separate test).
- **Verify:** unit tests (`test_step_end.py`, `test_windows.py`, `test_derived.py`); one manual ECS run of steps 1-1000
  showing scale-up and scale-down in the graphs.

## Iteration 5: Lambda host

- **Goal:** the same runs on Lambda + SQS + API Gateway WebSocket.
- **Files:** `app/deploy/lambda/`, Lambda entry points; `platforms/aws/cloudwatch_metric_scaling.py`,
  `lambda_log_streams_scaling.py`; `hosts.py` (`lambda`).
- **Steps:**
  1. Deploy defaults and the batch × delay check (§ 12).
  2. `CloudWatchMetricScalingInfoFetcher` (bound) and `LambdaLogStreamsScalingInfoFetcher` (written, not bound) (§ 9).
  3. Step-end polling of the non-live primary and the missing-datapoint rule; measure the metric delay (Q6).
- **Verify:** unit tests over stubbed `GetMetricData` / Logs Insights results; one manual Lambda run.

## Iteration 6: EKS and bare-metal hosts

- **Goal:** the same runs on K8s + Kafka, on EKS and on the bare-metal cluster.
- **Files:** `app/deploy/k8s/` values; `platforms/k8s/helm_deployer.py`, `api_scaling.py`, `pod_log_traces.py`;
  `transports/kafka.py`; `hosts.py` (`eks`, `baremetal`).
- **Steps:**
  1. `HelmDeployer` with `keda.enabled: true` and the run label (§ 12); decide Q8 first.
  2. `K8sApiScalingInfoFetcher`, pending counts (§ 9).
  3. `PodLogTraceCollector` with live log streaming (§ 10).
  4. `KafkaTransportCollector` (consumer-group lag) (§ 9).
- **Verify:** unit tests with a fake K8s client; a manual run on a local kind cluster first, then EKS and bare metal.

## Iteration 7: Cost

- **Goal:** `cost.csv` with per-step estimates, cost model and billed totals; cost graphs and cross-host comparison
  graphs.
- **Files:** `platforms/aws/*_usage.py`, `price_list.py`, `cost_explorer_billing.py`; `platforms/k8s/node_usage.py`;
  `platforms/baremetal/config_prices.py`; `cost/`; `plots/comparison.py`; `hosts.py` (cost parts on every host).
- **Steps:**
  1. Price sources and `price_table.json` at run start (§ 11).
  2. Usage sources, `usage.json`, `CostEstimator`, `CostModelBuilder` (§ 11).
  3. `CostExplorerBillingReader`, `collect-cost`, `BillComparer`.
  4. Comparison plots across hosts and modes (§ 15).
- **Verify:** `test_cost.py`; stubbed Price List / Cost Explorer parsing tests; `collect-cost` run a day after a
  manual run, checking estimated vs billed side by side.

## Iteration 8: Tests

- New files (spec.md § Testing): AK `test_pipeline_trace.py` plus the per-component tracing cases (iteration 1);
  benchmark `test_step_end.py`, `test_windows.py`, `test_derived.py`, `test_cost.py`, `test_traces.py`,
  `test_config.py`, `test_factories.py`, `test_ws_complete_driver.py`, `test_local_smoke.py` and the stubbed collector
  tests (added in the iterations above). This iteration fills gaps found while running on real hosts.
- Changed patch targets: none. Existing tests only gain cases.
- **Verify:** `cd ak-py && uv run pytest`; `cd benchmarks && uv run pytest`; `make lint-check-all`.

## Iteration 9: Sync docs and skills

- `ak-dev-architecture` (`.agents/skills/ak-dev-architecture/SKILL.md`): add the pipeline trace logger
  (`core/pipeline_trace.py`, logger `ak.pipeline_trace`, `logging.pipeline_trace.enabled`) to the Queue Execution
  Pipeline section, the `AKConfig` key list (`logging`) and the directory tree.
- `ak-dev-testing-conventions`: note the autouse fixture that resets `PipelineTrace`.
- Docs: `docs/docs/core-concepts/configuration.md` (new `logging.pipeline_trace.enabled` field); a short note in the
  deployment docs that request tracing moved from INFO lines to the opt-in trace logger.
- `AGENTS.md` repo map: add `benchmarks/`.
- Bundled user skills (`ak-py/src/agentkernel/skills/`): no change (the trace logger is a debugging/benchmark switch,
  not a scaffolding concern). Confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  flows before merge.

## Iteration 10 (phase 2): Percentiles and SLA check

- **Goal:** `percentiles.csv`, `sla.csv` and a per-host performance report from existing runs.
- **Files:** `ak_bench/sla/`; `BenchCLI` `sla-check`; `sla.example.yaml`.
- **Steps:** `PercentileCalculator`, `SlaConfig`, `SlaChecker`, `PerformanceReport` (spec.md § 16). SLA thresholds and
  AK tuning follow under #468.
- **Verify:** unit tests over a fixture run folder (pass, fail and `no_data` rows).
