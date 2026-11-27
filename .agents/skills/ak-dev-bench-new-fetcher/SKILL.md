---
name: ak-dev-bench-new-fetcher
description: >
  Step-by-step guide for adding a new fetcher to the ak-bench benchmark harness (benchmarks/ak_bench/fetchers/):
  a new way to read worker counts, CPU / memory, queue depth, TRACE lines or cost from a platform (AWS, GCP, Azure,
  Kubernetes, a broker). Use this skill when a host needs data the existing fetchers don't read, e.g. a Cloud Run
  scaling fetcher, a Pub/Sub transport collector or a Kubernetes replica fetcher. Covers picking the family,
  writing fetch() only, timestamps and tiers, thread safety, naming, config, binding it to a host's lists, and
  cloud-free tests.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Fetcher to ak-bench

A fetcher reads one kind of data from one platform source and returns its family's result type. Everything else
(storing, the cool-down check, CSV columns, graphs, when it runs) is already written. Read
`ak-dev-bench-architecture` first if you haven't.

Before writing a new class, check whether an existing **generic** fetcher covers it with new constructor
parameters (the design's `CloudWatchMetricScalingInfoFetcher(namespace, metric, dimension)` serves any CloudWatch
metric). A new parameterisation is a host-file line, not a new file.

## Step 0: Research the source (before any code)

Follow the workflow in `ak-dev-bench-architecture` (baseline, research rules, recording, when to ask). For a
fetcher, find out and compare, from the platform's official docs:

- **Every way the platform exposes this data**: control-plane API (describe / list calls), metrics service, logs
  (platform logs, structured performance events), events or activity history, an agent or sidecar, the billing
  export. List them all before choosing.
- **What each gives**, mapped to what the #786 design measures for this family: desired vs running counts, exact
  worker start / stop times (and extras such as image pull time), autoscaler decision times, per-worker vs per-tier
  values, CPU and memory as a % or absolute, which stats (max, avg, per worker), queue waiting vs in-flight.
  Prefer the source that gives the design's columns most exactly; a second source is worth binding when it adds
  something the first can't (e.g. ECS: live counts from the API plus exact decision times from scaling activities).
- **Time behaviour**: resolution (1 s, 60 s, ...), publish delay (how long until a period is complete), history and
  retention (can it be read after the step, or only live?), whether idle periods are missing or zero, whether
  values are approximate (SQS counts are).
  This decides the list (`during_step` vs `after_step`), `settle_window_s`, and the late-data clipping.
- **Limits and cost**: rate limits / quotas per call, page size and max ids per call, cost per call or per query
  (Logs Insights bills per GB scanned, metrics APIs per metric), so a 5 s poll over a long run stays affordable and
  under the quota.
- **Setup and permissions**: what must be enabled on the deployment (Container Insights, Lambda Insights layer,
  a metrics agent, log format) and the exact IAM / RBAC permissions the harness's caller needs. These go into the
  host's deployment folder and the README prerequisites.
- **Accuracy caveats** a reader of the graphs needs (sampling, aggregation, clock source); record them in the #786
  notes, never as checks in code.

Record the comparison, the choice and the rejected options with source links in
`docs/specs/786-benchmark-system/research/`, and the delays to measure on the first runs in the #786 design.

## Step 1: Pick the family

| The source gives | Subclass | `fetch()` returns |
|---|---|---|
| Worker counts (desired / running) and worker start / stop times | `ScalingInfoFetcher` (`fetchers/core/scaling.py`) | `ScalingInfo` |
| CPU / memory per worker or per tier | `ResourceUsageFetcher` (`fetchers/core/resources.py`) | `ResourceUsage` |
| AK `TRACE` lines (request-path stage timestamps) | `TraceCollector` (`fetchers/core/trace.py`) | `TraceInfo` |
| Pipeline queue depth | `TransportCollector` (`fetchers/core/transport.py`) | `QueueInfo` |
| Billed or estimated cost | `CostFetcher` (`fetchers/core/cost.py`) | `CostInfo` |

If the data fits none of them, stop: a new family changes `fetchers/core/`, `results/` and the #786 design. Raise
it as a design change, not a fetcher.

## Step 2: Put the file in the right folder

`benchmarks/ak_bench/fetchers/<platform>/<family>/<source>.py`

- `<platform>` is the system the code **calls**, not where AK runs: SQS is `aws/transport/sqs.py`; a Kubernetes
  replica fetcher is `kubernetes/scaling/deployment_replicas.py` and serves EKS, GKE and AKS; a Kafka lag reader is
  `kafka/transport/...`.
- `<family>` is named like the `fetchers/core/` file: `scaling`, `resources`, `trace`, `transport`, `cost`.
- The file name names the source (`ecs_api.py`, `cloudwatch_metric.py`), no `_scaling` suffix. The class name is full:
  `<Source><Family base>` (e.g. `EcsApiScalingInfoFetcher`, `SqsTransportCollector`, `CostExplorerCostFetcher`).
- Create a folder (with an empty `__init__.py`) only when you add its first file. Helpers shared by several fetchers
  of one platform (SDK session, a log-query helper) go in `<platform>/common/`, not in `core/`.

## Step 3: Write the class

```python
from datetime import datetime, timedelta

from ak_bench.fetchers.core.scaling import CountSample, ScalingInfo, ScalingInfoFetcher
from ak_bench.hosts.host import Deployment, RunInfo


class AcaReplicasScalingInfoFetcher(ScalingInfoFetcher):
    """Running replica count of each Container App, from the Azure Monitor `Replicas` metric."""

    name = "azure.aca_replicas"                 # registry name: CSV columns and the fetchers.<name> config key
    count_types = frozenset({"running"})        # what samples it gives; must include "running" for cooldown_checks

    def __init__(self, client, period_s: int = 60, **kwargs):
        super().__init__(**kwargs)              # poll_interval_s, settle_window_s: set by the host, not here
        self._client = client
        self._period_s = period_s

    def fetch(self, run: RunInfo, deployment: Deployment, start: datetime, end: datetime) -> ScalingInfo:
        info = ScalingInfo()
        for tier, res in deployment.resources.items():   # same calls for every tier; tag each row with the tier
            for ts, value in self._read(res["app"], start, end):
                info.samples.append(CountSample(ts + timedelta(seconds=self._period_s), tier, "running", int(value)))
        return info
```

Contract (`fetchers/core/info_fetcher.py`):

- **Write `fetch()` only.** It reads and returns; it never writes files. `store()`, `is_settled()`, `has_value()` and
  `fetch_and_store()` come from the family base. Returning another type is refused with `FetcherTypeError`.
- **`name`** is required and must be unique across the host: rows are keyed by it, so two fetchers with one name
  overwrite each other. `StageFetchers.validate` refuses a missing name but does not yet check duplicates; check
  them yourself. Convention: `<platform>.<source>`, plus a suffix for a parameterised generic one
  (`aws.cloudwatch_metric.ConcurrentExecutions`). Set it as a class attribute, or in `__init__` when it depends on the
  parameters.
- **Window:** `fetch()` gets `(start, end)` from the list it is in (see the architecture skill). Read exactly that
  window when the source has history. A source with only a current value (SQS depth, a describe call) returns one
  sample at `end` and belongs in `during_step`.
- **Timestamps:** timezone-aware UTC `datetime`. A value the source gives per period (a metric datapoint, a
  `bin()` row) gets `ts` = the **end** of the period, because it is only known once the period is over.
- **Late data:** a source that publishes with a delay must not report a recent period as 0. Clip the read to
  `now - <delay>` (a constructor parameter with a measured default) so a missing recent period is left out, not zero;
  a missing older period may be a real 0 if the source sends nothing when idle. When the clipped window is empty
  (the cool-down reads only the last `cooldown_lookback_s`), move `start` back so the latest known period is still
  returned; otherwise the check never gets a value.
- **One sample per period, zeros included** for a fetcher that isn't polled (`after_step` etc.). In
  `per-time-window.csv` a non-polled series carries each value forward only for its smallest gap between samples
  (`WindowGrid.fill`), and a series of one sample fills only its own window. Leaving idle periods out makes gaps
  show as empty cells. A polled (`during_step`) series carries for its poll interval instead.
- **Outside the steps the deployment can be empty.** `finish` after a failed `deploy.sh` passes
  `Deployment("", {}, {}, {}, {})`. A fetcher meant for `after_all_steps` / `after_teardown` (cost) should work from
  `run.deployment_id` alone, and every fetcher must cope with empty `resources` / `queues` / `logs` (return an empty
  result). See the
  `CloudWatchMetricScalingInfoFetcher` sketch in `docs/specs/786-benchmark-system/design.md`.
- **Tiers:** loop over `deployment.resources` (scaling, resources), `deployment.queues` (transport) or
  `deployment.logs` (trace / log-based). Read the ids from there, never build names from tier names. If you need a
  new id, it is a new key in the host's `deployment.json` (see `ak-dev-bench-new-host`).
- **Stateless and thread-safe.** The same object can be in several lists and in several hosts, and `fetch()` can run
  in two threads at once (a `during_step` poll and the cool-down check). No per-call state on `self`; share only
  thread-safe clients (boto3 clients are, boto3 `Session` objects are not).
- **No cloud call at construction.** Host bundles are built at import time of `hosts/<platform>.py`, which every
  command and test imports (CI has no credentials and no region). Constructing a fetcher must work offline. Note that
  `boto3.Session().client("ecs")` already fails without a region (`NoRegionError`), so the #786 sketches that create
  the client in `__init__` won't import in CI as written: create clients on first use (thread-safely, e.g. a
  lock-guarded cache in `<platform>/common/`) or pass the region in explicitly.
- **Errors:** let them raise. `FetcherInvoker` logs the failure to the run log and the run carries on with empty
  columns. Don't catch-and-return-empty: that hides a broken fetcher as "no data". Do handle pagination and API
  limits (e.g. `describe_tasks` takes 100 ARNs) inside `fetch()`.
- **Record and report only:** no thresholds, warnings about values, or retries that change the run.

Family-specific fields:

- `ScalingInfoFetcher`: `count_types` lists the `count_type`s it emits (`"running"`, `"desired"`). For
  `cooldown_checks` it must return a `running` sample for **every** tier on every read: `is_settled()` compares each
  tier's latest `running` with its starting value, so a tier missing from a read means "not settled". Declared types lay
  out empty columns when nothing was stored. `WorkerSpan(tier, worker, started, stopped | None, extra)`: spans are
  merged by worker id (latest wins), so a `during_step` fetcher may return every worker it sees each poll.
- `ResourceUsageFetcher`: `metrics = frozenset({(metric, stat), ...})`, e.g. `("cpu_pct", "max")`. `stat` is
  `value` (one value per worker → p0..p100 columns), or `min` / `avg` / `max` (one column). Another stat is
  averaged; give `results/csv/resource_columns.py` a rule for it if that's wrong. `worker=None` for tier-level values.
- `TraceCollector`: parse lines with AK's `TraceLine.parse(line)` (`agentkernel.core`; `None` for a non-trace line),
  never your own regex; return
  `{request_id: {TraceStage: ts}}`. One collector per log backend, not per host.
- `TransportCollector`: `QueueDepth(ts, queue, waiting, in_flight)`, `queue` = the `deployment.queues` key
  (`input` / `output`). Approximate broker counts need a `settle_window_s` in the host (SQS uses 60).
- `CostFetcher`: `CostItem(period_start, period_end, service, usd, metric)`. Filter by the tag
  `ak-bench-run-id = run.deployment_id`, which the deployment folder puts on every resource it creates.

## Step 4: Dependencies and config

- A new SDK goes into `benchmarks/pyproject.toml` `dependencies` with a bounded range, then `uv lock`. Don't add a
  dependency for a few lines of HTTP.
- No new `ak-bench.yaml` keys for a fetcher. Its poll interval comes from `fetchers.<name>.poll_interval_s` (else
  `fetchers.default`) automatically; other constructor parameters are set in the host file. Don't pass
  `poll_interval_s` in the host unless you mean to pin it: a constructor value wins and `ak-bench.yaml` can no longer
  change it. If a value really must be
  configurable per run, raise it as a design change.

## Step 5: Bind it to a host

Add the object to one or more of the host's `StageFetchers` lists in `hosts/<platform>.py` (see
`ak-dev-bench-new-host`). Place it where its data exists:

- current-value-only source → `during_step` (and `cooldown_checks` if it can say "settled");
- history with ingestion delay (logs, metrics) → `after_step`;
- cost / billing → `after_teardown` (billed, a day later) or `after_all_steps`;
- scaling or transport fetcher that should end the cool-down → `cooldown_checks` (scaling needs `"running"`).

Results need no change: columns and graphs are laid out from the host's lists by family.

## Step 6: Tests (cloud-free)

Put tests in `benchmarks/tests/fetchers/<platform>/<family>/test_<platform>_<family>_<source>.py`. The file name
must be unique across `tests/` (the test folders have no `__init__.py`; `aws/scaling/` and `aws/resources/` both have
a `cloudwatch_metric.py`).

- Stub the SDK, never call it: `botocore.stub.Stubber` for boto3, or a fake client passed to the constructor. A
  recorded API response can live under `tests/fixtures/`.
- Cover: the request built from `deployment` (ids per tier, the window), the mapping to the result type (tier tags,
  period-end timestamps, late-data clipping, a missing period), pagination, and `fetch_and_store()` writing the
  family CSV into `tmp_path`.
- For a fetcher meant for `cooldown_checks`, add an `is_settled()` case through the family base with your result.
- Validation: a host with the fetcher passes `StageFetchers.validate()` (no `HostRefused`).
- Run `cd benchmarks && uv run pytest -q` and ruff.

## Step 7: Docs

- Add the fetcher to the host's row in the #786 Hosts table (`docs/specs/786-benchmark-system/design.md`) and, if
  you researched the source (delays, resolution, quotas), to its `research/` notes, verified against the official
  docs.
- If the fetcher needs a new id in `deployment.json`, document it in `benchmarks/app/deploy/README.md`.

## Checklist

- [ ] Right family; file at `fetchers/<called platform>/<family>/<source>.py`
- [ ] Only `fetch()` written; returns the family type; `name` set and unique; `count_types` / `metrics` declared
- [ ] Loops over the deployment's tiers / queues / logs; timestamps UTC, period values at period end; late data clipped
- [ ] Stateless, thread-safe, no cloud call in `__init__`; errors raise
- [ ] Bound in the host's lists where its data exists
- [ ] Cloud-free tests pass; ruff clean; #786 design updated
