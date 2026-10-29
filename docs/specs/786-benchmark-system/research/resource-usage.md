# Research: Measuring Worker CPU and Memory Usage

How the [Resource usage](../design.md) requirement is measured: CPU and memory used
by the workers of each tier, read from the platform the same way worker counts are read by the
[scaling info fetchers](platform-scaling-and-cost.md#scaling-info-fetchers-pluggable).

Status (2026-10-29): **agreed:** the fetchers each host binds (Lambda Insights included, on by default),
p0 / p25 / p50 / p75 / p100 per window and per step (min / avg / max for the ECS service metrics, changed from
min / avg / max everywhere on 2026-10-29), and separate graphs. Still open: see [Open points](#open-points).

## Design: resource usage fetchers (pluggable)

Same pattern as the scaling info fetchers: one abstract class, one subclass per **way of reading** CPU / memory on one
platform, a `live` flag for when it's called, and a host lists one or more of them.

- **Why a separate interface, not part of `ScalingInfoFetcher`:**
  - The sources are different (ECS `DescribeServices` gives counts but no usage; Container Insights gives usage but
    needs to be switched on), and so are their delays.
  - Scaling must keep working on a host where no usage source is set up. A host with no resource fetcher just has
    empty columns.
  - Shared code is reused below the interface instead: the CloudWatch metrics and Logs Insights helpers are used by
    both kinds of fetcher.
- **Name:** `ResourceUsageFetcher`, returning `ResourceUsage`. Not "usage source": that name is taken by the cost
  [usage sources](platform-scaling-and-cost.md#how-the-cost-code-is-split) (billed quantities).

```python
@dataclass
class ResourceSample:
    """One reading: the value of one metric, for one worker (or a whole tier), at one moment."""

    ts: datetime            # when the reading was taken
    tier: str               # which tier it's for: a key of Deployment.resources, e.g. "runner", "io"
    worker: str | None      # which worker: task id, pod name, Lambda log stream; None = one value for the whole tier
    metric: str             # what was read: "cpu_pct" / "mem_pct" / "mem_mb" / "cpu_time_ms"
    stat: str               # "value" = a raw reading; "min" / "avg" / "max" = the source already aggregated it
    value: float            # the number


@dataclass
class ResourceUsage:
    """Everything one fetch() call returns: all the readings, for every tier, worker, metric and time in [start, end]."""

    samples: list[ResourceSample] = field(default_factory=list)


class ResourceUsageFetcher(ABC):
    """One way of reading worker CPU / memory from one platform."""

    name: str    # registry name, e.g. "aws.ecs_service_metrics"; used in the CSV column names
    live: bool   # True: called every few seconds during the run. False: called once after the run.

    @abstractmethod
    def fetch(self, run: Run, deployment: Deployment, start: datetime, end: datetime) -> ResourceUsage: ...
```

- **`ResourceSample` = one reading.** Each row says "at time `ts`, worker `worker` of tier `tier` had `metric` =
  `value`". `stat` says whether that number is a raw reading (`value`) or something the source already worked out
  across several readings (`min` / `avg` / `max`).
- **`ResourceUsage` = one `fetch()` call's result.** Just the list of `ResourceSample`s. It's a class rather than a
  bare list so per-fetch details (e.g. "Container Insights was off") can be added later without changing `fetch()`'s
  signature, the same as `ScalingInfo` for the scaling fetchers.
- **Example:** one `aws.ecs_container_insights` fetch over a step with two runner tasks returns a `ResourceUsage`
  holding, among others:

  | `ts` | `tier` | `worker` | `metric` | `stat` | `value` |
  |------|--------|----------|----------|--------|---------|
  | 10:04:00 | runner | task-1a2b | cpu_pct | value | 37.5 |
  | 10:04:00 | runner | task-1a2b | mem_mb | value | 412 |
  | 10:04:00 | runner | task-9f8e | cpu_pct | value | 52.0 |
  | 10:05:00 | runner | task-1a2b | cpu_pct | value | 41.0 |

  The `aws.ecs_service_metrics` fetch for the same minute gives whole-tier values instead, since AWS doesn't give
  per-task numbers there:

  | `ts` | `tier` | `worker` | `metric` | `stat` | `value` |
  |------|--------|----------|----------|--------|---------|
  | 10:04:00 | runner | `None` | cpu_pct | min | 37.5 |
  | 10:04:00 | runner | `None` | cpu_pct | avg | 44.8 |
  | 10:04:00 | runner | `None` | cpu_pct | max | 52.0 |

- **Fetchers only return readings.** The shared resource collector turns them into the per-window percentile
  columns, the summary columns and the long-form `resource-usage.csv` (which is these rows plus a `fetcher` column).
- **How many samples:** one per worker per time window per metric (and per stat). Not one per worker in total, and
  not one per request.
  - ECS Container Insights: one event per task per minute → one sample per task per minute per metric. 7 tasks over
    a 30-minute step ≈ 210 per metric.
  - The ECS service metric: one sample per tier per minute per stat (`worker = None`).
  - Lambda (both fetchers): the source has one event per **invocation**, `worker` = the log stream (execution
    environment) it ran in. A burst step of 100 gives about 100 request-handler invocations (up to 100 environments
    if they run at the same time), but fewer agent-runner invocations: the SQS event source mapping hands up to
    `batch_size` (our Terraform default 10) messages to one invocation, so 100 messages can be as few as 10
    invocations, and an environment that finishes picks up the next batch.
  - **Lambda is reduced in the query, not fetched raw:** a steady step of 1000 clients can mean hundreds of thousands
    of invocations, above what one Logs Insights query returns (default 10,000 rows, at most 100,000 with `limit`
    since May 2026). So the query groups by log stream and time window
    (`stats max(used_memory_max), avg(...), max(...) by @logStream, bin(<window>)`), giving one sample per
    environment per window per stat (`stat` = `max` / `avg`). 100 environments over a 10-minute load at 10 s windows
    ≈ 6,000 rows per metric. If a step still goes over the limit, the fetcher splits the time range.
- **One `fetch()` covers every tier:** it loops over `Deployment.resources`, exactly like the scaling fetchers. Adding
  a tier needs no change here.
- **Per worker where the source has it, per tier where it doesn't.** `worker = None` marks a whole-tier value (e.g.
  the ECS service average).
- **Units:** CPU as a % of what one worker has (task vCPU, pod request/limit, Lambda share), memory in MiB and as a %
  of the worker's memory, so hosts with different worker sizes read the same way. The worker size is already in the
  run metadata.
- **Called by the same collector loop** as the scaling fetchers (`live` ones polled during the run, the others after
  it, re-runnable with a `collect-resources --run-id …` step like `collect-scaling`).
- **A fetcher that fails** (no permission, Container Insights off) records empty columns and a run-log entry; the run
  carries on. Same rule as the scaling fetchers.

## ECS (Fargate)

Three places have ECS CPU / memory. Bound: the first two.

### 1. `aws.ecs_service_metrics`: free service metrics (per tier)

- `AWS/ECS` namespace, `CPUUtilization` and `MemoryUtilization`, dimensions `ClusterName` + `ServiceName`. Fargate
  services get them automatically, free, sent in **1-minute periods**, kept 2 weeks.
- **Per service only, not per task.** So one value per tier per minute.
- **What the statistics mean** (checked): ECS samples every 20 s; each 1-minute datapoint is built from those 3
  samples.
  - `Average`: total used by all tasks ÷ (task size × number of tasks), i.e. the average task.
  - `Minimum` / `Maximum`: the task with the lowest / highest usage ("the smallest and largest of the 20 second
    metrics").
  - So it already gives a per-tier min / avg / max across tasks, once a minute, and only those: per-task values
    aren't in this source, so percentiles can't be worked out from it. This fetcher's columns stay min / avg / max;
    the percentiles come from Container Insights. A spike shorter than the 20 s samples
    isn't seen.
- Read with `GetMetricData` after the run, stats `Average`, `Minimum`, `Maximum`.
- With CPU set at task level (ours), CPU % doesn't go above 100.
- Optional 20-second resolution (`resolutionSeconds = 20` on the service's monitoring configuration) exists; not set
  in our Terraform and not proposed.
- `live = False`. Implemented as a generic `CloudWatchMetricResourceFetcher` (namespace, metric names, dimensions as
  constructor parameters), so GCP / Azure monitoring-metric fetchers follow the same shape later.

### 2. `aws.ecs_container_insights`: per-task usage (Container Insights)

- With Container Insights on, ECS writes **performance log events** to
  `/aws/ecs/containerinsights/<cluster>/performance`. Events with `Type = "Task"` carry `TaskId`, `CpuUtilized`,
  `CpuReserved`, `MemoryUtilized`, `MemoryReserved` (MiB) and a `Timestamp`; `Type = "Container"` events add
  `ContainerName`.
- **Per task**, so `worker` = task id, which joins with the `aws.ecs_api` worker spans.
  `cpu_pct = CpuUtilized / CpuReserved × 100`, `mem_pct = MemoryUtilized / MemoryReserved × 100`.
- Read with one Logs Insights query per run (shared `cloudwatch_logs.py` helper), e.g.
  `filter Type = "Task" | fields Timestamp, TaskId, CpuUtilized, CpuReserved, MemoryUtilized, MemoryReserved`.
- **Our Terraform already turns it on:** the `terraform-aws-modules/ecs` module (6.10.0) defaults `cluster_setting`
  to `containerInsights = enabled`, and `ak-aws/containerized/rest_service.tf` doesn't override it.
- **Enhanced observability** (`containerInsights = enhanced`) also publishes per-task metrics with a `TaskId`
  dimension (`TaskCpuUtilization`, `TaskMemoryUtilization`, and `ContainerCpuUtilization` / `ContainerMemoryUtilization`
  per container). Only needed if the log events turn out not to cover Fargate tasks. Costs more than standard.
- `live = False` (log ingestion delay).
- **Fargate:** AWS's reference shows only an EC2 example. A Fargate `Type = "Task"` event with
  `"LaunchType": "FARGATE"` and the same CPU / memory fields is shown by an AWS developer advocate's write-up from
  2022, before enhanced observability existed, so standard Container Insights covers Fargate tasks. Community queries
  pick them out by the `FargateTelemetry-…` log stream. Checked against those examples, not an AWS reference page.
- **Interval:** one event per task (and per container) **every minute**.
- `CpuUtilized` / `CpuReserved` are in CPU units (1024 = 1 vCPU), `MemoryUtilized` / `MemoryReserved` in MiB.

### 3. Task metadata endpoint `/task/stats` (not proposed for now)

- Inside every Fargate task (platform 1.4.0+), `${ECS_CONTAINER_METADATA_URI_V4}/task/stats` returns Docker stats
  (CPU and memory) for all containers of the task. Finest resolution (any interval).
- **Only reachable from inside the task**, so it needs code in the task: AK sampling it and logging the values, or a
  sidecar container. That's a change to AK or the task definition, so not proposed unless the 1-minute data from 1
  and 2 is too coarse.

## Lambda

The standard `AWS/Lambda` metrics have no CPU or memory metric. Two sources:

### 1. `aws.lambda_report_memory`: `REPORT` lines (memory only, free)

- Every invocation ends with a `REPORT` line: `Duration`, `Billed Duration`, `Memory Size`, **`Max Memory Used`**.
- Read with Logs Insights (`filter @type = "REPORT" | stats max(@maxMemoryUsed) by @logStream, bin(<window>)`), the
  same helper and the same lines as the Lambda cost usage source (`lambda_usage.py`). `worker` = log stream (one per
  execution environment, as in `aws.lambda_log_streams`).
- Free, nothing to switch on.
- **No CPU.**
- Caveat: "when invocations share an execution environment, Lambda reports the maximum memory used across all
  invocations", so it's a high-water mark per environment, not the memory of that invocation.
- `live = False`.

### 2. `aws.lambda_insights`: Lambda Insights extension (CPU and memory)

- Lambda Insights is a CloudWatch extension added to the function as a **layer**. It writes **one performance log
  event per invocation** (embedded metric format, log group `/aws/lambda-insights`) and per-function metrics in the
  `LambdaInsights` namespace.
- AWS's documented fields: `cpu_total_time` (ms, = `cpu_user_time` + `cpu_system_time`), `memory_utilization`
  (%), `used_memory_max` (MB), `total_memory` (MB), `init_duration`, `threads_max`, plus network, `/tmp`, file
  descriptors and agent stats.
  - AWS's two tables disagree on `memory_utilization`: the metrics table says the **maximum**, the log-entry table the
    **average**, as a % of the memory. Record it as given; don't rely on which one it is.
- **Fields not in AWS's list:** a third-party example event (2023) also has `function_name`, `request_id`,
  `trace_id`, `duration`, `billed_duration`, `cold_start`, `timeout` and `shutdown_reason`. AWS's docs don't list
  them, so the fetcher must cope if one is missing:
  - CPU %, per environment per window: `sum(cpu_total_time) / sum(duration) × 100` (CPU time as a share of the
    time spent in invocations), worked out in the query. If `duration` is missing, record only `cpu_time_ms`
    (`sum(cpu_total_time)` per window).
  - `worker` = the event's log stream, if it's one per execution environment (as in the function's own log group).
    If it isn't, group by `function_name` and record a per-tier value (`worker = None`) instead.
  - Check both on the first Lambda run.
- **Setup:**
  - Zip functions (our default, `package_type = "LocalZip"`): add the Lambda Insights layer ARN (per region and
    architecture). Our Terraform has a `layers` variable on all four functions (request handler, agent runner,
    response handler, WebSocket connection handler) and the authorizer, so no Terraform change.
  - Container-image functions (our Terraform also allows `ecr_image_uri`): layers don't apply; the extension is
    installed in the Dockerfile instead. Benchmark runs use zip packages, so not needed now.
  - **IAM: nothing to add.** AWS's policy for it, `CloudWatchLambdaInsightsExecutionRolePolicy`, allows
    `logs:CreateLogGroup` and `logs:CreateLogStream` / `logs:PutLogEvents` on `/aws/lambda-insights`. All our
    function roles already attach `AWSLambdaBasicExecutionRole`, which allows the same three actions on every
    resource (`"*"`).
- **Cost and side effect:** billed for its logs (~1 KB per invocation) and metrics, and the extension's run time is
  billed in 1 ms increments. It runs inside the measured functions, so it adds a little to their duration (and to the
  latency being measured). To be recorded in the run metadata whether it was on.
- Only on Amazon Linux 2 / 2023 runtimes.
- `live = False`.

Bound: both. `aws.lambda_report_memory` always (free). `aws.lambda_insights` is **on by default**; a per-run config
value switches it off (e.g. to check how much latency the extension adds). The deployer adds the layer when it's on (no
IAM change, see above); the run metadata records whether it was.

## Kubernetes (EKS, bare metal) and local

Less researched; to check before building.

- **`k8s.metrics_api`** (live): the `metrics.k8s.io` API (`PodMetrics`, from metrics-server) gives each container's
  CPU (cores) and memory (bytes). `worker` = pod name. metrics-server must be installed in the cluster. It gives raw
  usage; % is worked out against the pod's requests/limits (as `kubectl top` / the HPA do).
  - **Resolution:** the metrics-server binary defaults to 60 s, but its official install manifest and Helm chart set
    `--metric-resolution=15s`. 15 s is also the finest the kubelet gives. An install with other args may differ, so
    the run metadata records the cluster's value.
  - metrics-server says it's "meant only for autoscaling purposes" and not "an accurate source of resource usage
    metrics". A Prometheus / cAdvisor fetcher can be added later if
    it isn't good enough.
- **`local.process`** (live): reads the AK process(es) of the local baseline directly with `psutil`
  (`cpu_percent`, `memory_info().rss`), one tier per process. If local AK runs in Docker, `docker stats` instead.

## What's recorded

- **Per-time-window CSV:** per tier × metric × stat × fetcher, e.g. `runner.cpu_pct.avg.aws.ecs_service_metrics`,
  `runner.mem_mb.p50.aws.ecs_container_insights`. Per-worker sources are reduced to p0 / p25 / p50 / p75 / p100
  across the tier's workers in each window. The ECS service metrics keep the min / avg / max AWS gives.
- **Per-step `resource-usage.csv` (new):** the raw per-worker samples in long form
  (`ts, tier, worker, metric, value, fetcher`), since one column per worker doesn't fit the per-time-window file.
- **Summary CSV (per test type, one row per step):** p0 / p25 / p50 / p75 / p100 of CPU % and memory per tier over
  the step's whole time period (before → load → cool-down), one set per fetcher, e.g.
  `runner.cpu_pct.p100.aws.ecs_container_insights`.
  - Worked out from all the raw samples in the step (every worker, every sample time): p0 = the lowest single
    sample, p100 = the highest.
  - ECS service metrics: min / avg / max (the lowest `Minimum`, the average of the `Average` datapoints, the highest
    `Maximum`).
  - Step N is N requests (burst) or N clients (steady traffic), so this row shows how usage changes with load.
- **Graphs:** separate graphs, not panels in `03-timeline.png`:
  - `graphs/03-resource-usage-per-step.png` (comparing the steps): CPU % and memory against the load step,
    p0 / p25 / p50 / p75 / p100, one row of panels per tier.
  - `step-<N>/graphs/05-resource-usage.png` (one step): CPU % and memory over the step's timeline, p0 / p25 / p50 /
    p75 / p100 across the tier's workers per time window, one row of panels per tier. Same time axis and before /
    load / cool-down shading as `03-timeline.png`.
  - Which fetcher a graph draws: for each metric, the first fetcher in the host's list that gives it (the per-worker
    one first: Container Insights before the ECS service metric, Lambda Insights before `REPORT` memory). The graph
    names it. The other fetchers stay in the CSVs.
  - Lambda: a time window with no invocations has no sample, so the line has a gap there (not drawn as 0).
- **Run metadata:** which resource fetchers ran, and whether Container Insights (standard / enhanced) and Lambda
  Insights were on, and the K8s metrics-server resolution.

## Open points

- Lambda Insights fields that aren't in AWS's docs (`duration`, `function_name`) and whether its log stream is one
  per environment: check on the first Lambda run; the fallbacks are described above.
- Fargate `Type = "Task"` events: confirmed only by non-AWS examples; check on the first ECS run.

## Sources (checked 2026-10-26, rechecked 2026-10-27)

- ECS free CloudWatch metrics (1-minute periods, Fargate automatic, per-task needs Container Insights): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-metrics.html
- ECS service metric statistics (Average / Minimum / Maximum use cases): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service_utilization-metrics-explanation.html
- ECS service utilization (formula, 20 s samples, Minimum / Maximum = lowest / highest task, 20 s resolution option): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service_utilization.html
- Container Insights ECS metrics (`CpuUtilized`, `MemoryUtilized` in MiB): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-ECS.html
- Container Insights enhanced observability (`TaskId` dimension, `TaskCpuUtilization`, `TaskMemoryUtilization`): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-enhanced-observability-metrics-ECS.html
- Container Insights ECS performance log events (log group, `Type = "Task"` fields): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-reference-performance-logs-ECS.html
- Fargate task metadata endpoint v4 (`/task/stats`, Docker stats, inside the task only): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4-fargate.html
- Lambda `REPORT` line (`Max Memory Used`, shared-environment caveat): https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html
- Lambda Insights (extension layer, one performance event per invocation, pricing): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Lambda-Insights.html
- Lambda Insights metrics (`cpu_total_time`, `memory_utilization`, `used_memory_max`): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Lambda-Insights-metrics-lambda-functions.html
- Lambda Insights log-only fields (`cpu_user_time`, `threads_max`, `memory_utilization` as average): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Lambda-Insights-metrics-lambda-functions.html
- Lambda Insights log group and per-invocation event example with `request_id` / `duration` (third party, 2023): https://docs.aws.amazon.com/lambda/latest/dg/monitoring-insights.html, https://dev.classmethod.jp/articles/lambda-insights-structure-usage/
- `CloudWatchLambdaInsightsExecutionRolePolicy`: https://docs.aws.amazon.com/aws-managed-policy/latest/reference/CloudWatchLambdaInsightsExecutionRolePolicy.html
- `AWSLambdaBasicExecutionRole`: https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSLambdaBasicExecutionRole.html
- Lambda Insights on container images (Dockerfile, not a layer): https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Lambda-Insights-Getting-Started-docker.html
- Fargate `Type = "Task"` event with `LaunchType: FARGATE`, one per minute (AWS developer advocate's blog, 2022): https://nathanpeck.com/diving-into-amazon-ecs-task-history-with-container-insights/
- Fargate per-task Container Insights queries (community): https://dev.classmethod.jp/articles/record-fargate-per-task-cpu-and-memory-usage-in-cloudwatch-metrics/
- Logs Insights result limit (100,000 with `limit` and paging, from May 2026; default 10,000): https://aws.amazon.com/de/about-aws/whats-new/2026/05/cloudwatch-logs-query-results/, https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax-Limit.html
- metrics-server (autoscaling only, 15 s): https://github.com/kubernetes-sigs/metrics-server/blob/master/README.md
- metrics-server defaults (binary 60 s; manifest / Helm chart `--metric-resolution=15s`): https://github.com/kubernetes-sigs/metrics-server/blob/master/cmd/metrics-server/app/options/options.go, https://github.com/kubernetes-sigs/metrics-server/blob/master/charts/metrics-server/values.yaml
