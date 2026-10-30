# Research: Measuring Scaling and Cost

How the [Scaling](../design.md) and [Cost](../design.md) requirements are measured. Both follow the
"record and report only" principle: the runner records timestamps, counts and dollars, and the graphs show them. The
derived numbers below (scale-up time, cost per 1M messages) are fixed calculations over the recorded data, not
pass/fail checks.

## Pluggable per-platform collectors

Every cloud has its own APIs for worker counts and cost (ECS `DescribeServices` vs. the K8s API vs. GCP Cloud
Monitoring / Azure Monitor; AWS Cost Explorer vs. GCP BigQuery billing export vs. Azure Cost Management). GCP and Azure
are coming later, so the platform-specific parts are kept behind interfaces and everything else is shared:

```
Host (registered by name, e.g. "ecs", "lambda", "eks", "baremetal", later "cloud_run", "aca")
├── Deployer            deploy() -> Deployment(endpoint(url, auth), resources: {tier: resource id}), teardown()
│                       deployed_settings() -> dict  (autoscaling settings + worker size, saved in run metadata)
├── ScalingInfoFetchers one or more per host; each reads worker counts one way (see Scaling info fetchers below)
├── ResourceUsageFetchers one or more per host; each reads worker CPU / memory one way (see resource-usage.md)
├── TraceCollector      stage_timestamps(run) -> {request_id: {stage: ts}}  (from the AK trace logs)
├── UsageSources        one or more per host, one per billed thing (Fargate, Lambda, SQS, API Gateway, K8s nodes, ...)
│                       usage(run, deployment, start, end) -> [UsageItem(component, unit, qty, start, end)]
├── BillingReader       billed(run) -> [CostItem(component, usd)] | None   (one per cloud; later step; None if no bill)
├── PriceSource         prices(region) -> PriceTable   (one per cloud; fetched per run, see Cost → Prices)
└── TransportCollector  poll() -> {queue: QueueDepth(waiting, in_flight)}   (picked by transport: sqs, kafka, later pubsub, servicebus)
```

- **Shared, platform-independent code:** scaling-test orchestration, the poll loop and timestamps, turning scaling
  source output into per-window worker counts, all derived numbers (scale-up/down times, idle cost, cost per 1M messages = usage × price table),
  CSV writing and graphs. It only sees the common return types above.
- **Per-platform code:** only the API calls that fill those types. A field with no source on a platform (e.g. `desired`
  on Lambda, `billed` on bare metal) is returned as empty and the column stays blank.
- **Reuse within a platform family:** e.g. one K8s scaling info fetcher serves EKS, bare metal and later GKE/AKS (they
  differ only in their cost parts); the AWS billing reader and price source are shared by Lambda, ECS and EKS, and
  each host picks the usage sources for the things it's billed for.
- **Adding GCP or Azure** = implement these for the new host and register it. No changes to the harness, CSVs
  or plots.
- Worker counts come only from the platform side (APIs, metrics, logs). Nothing in AK or the benchmark pre-hook
  reports a worker id.

File and class layout for these interfaces: to be specified in `spec.md`.

## Scaling

### Terminology

- **Horizontal scaling:** changing the **number** of workers (tasks, pods, Lambda execution environments). Each
  worker stays the same size. The usual names are **scale out** (add workers) and **scale in** (remove workers).
- **Vertical scaling:** changing the **size** of each worker (more or less CPU/memory per task or pod, a bigger Lambda
  memory setting). The number of workers stays the same. This is usually called **scale up / scale down**.
- **The benchmark tracks horizontal scaling only.** Worker size is a fixed deployment setting for each run, and it's
  saved in the run metadata next to the autoscaling settings.
- **Naming in these docs:** "scale up" / "scale down" (scale-up time, scale-down time, etc.) mean **adding / removing
  workers**, i.e. horizontal scale out / scale in. They don't mean vertical scaling.

### Scale-down delay per platform

There's no separate scaling test. Scaling is measured inside every load step, over its
[timeline](#load-step-tests-scaling-per-step): the load starts (scale up), the load stops (scale down). A step's
cool-down has to outlast the platform's scale-down delay, otherwise scale-down never completes inside the step. What
sets that delay:

- **ECS:** target tracking only scales down after **15 consecutive one-minute datapoints** below target (so ~15 min after
  the load drops), then each scale-down step is followed by `scale_in_cooldown` (`scaling_config`; our Terraform default is 120 s, the
  Application Auto Scaling default for ECS is 300 s).
- **EKS / bare metal:** our chart uses `keda.minReplicaCount: 1`, so scaling from N back to 1 is done by the **HPA**
  that KEDA creates, not by KEDA. The HPA's scale-down stabilization window is 300 s by default (configurable through
  the ScaledObject's `horizontalPodAutoscalerConfig.behavior`). KEDA's `cooldownPeriod` only applies when scaling to 0,
  so it doesn't matter here.
- **Lambda:** concurrency falls as soon as invocations stop; the SQS pollers scale back down to the minimum (5) on their
  own.

### Load-step tests: scaling per step

The [load steps](../design.md) of both test types (burst and steady traffic) also record scaling, over each
step's [timeline](../design.md): before → load → cool-down.

- The derived numbers below are computed per step, with `t_load_up` = first send of the step and `t_load_down` = end
  of the load part (steady traffic: the configured time is up; burst: the last response arrived or timed out).
- **When the cool-down ends:** the shared poll loop checks three things during the cool-down, and the step ends when
  all three hold in the same poll:
  1. **All requests settled (client):** every request sent in the step has a response or has timed out. This alone
     covers requests that completed normally.
  2. **Pipeline empty (TransportCollector):** both queues hold nothing, counting messages still being processed.
     This covers requests the client gave up on (timed out) that are still inside AK, so they don't finish during
     the next step.
     - SQS: `ApproximateNumberOfMessages` (waiting) **and** `ApproximateNumberOfMessagesNotVisible` (received by a
       worker, not yet deleted) are 0, on the input and output queues. AWS says these counts may not be consistent
       until at least 1 minute after producers stop sending, so only polls taken ≥ 1 min after the step's last send
       count.
     - Kafka: consumer-group lag is 0 on the input and output topics. AK commits offsets only after processing a
       message (`ak-py/src/agentkernel/pipeline/transport/kafka.py`), so a message being processed still counts as
       lag.
  3. **Workers back (primary fetcher):** the running count of every tier is back at its count at the end of the
     "before" part.
  - A condition with no source on a host counts as met, e.g. the local `in_memory` host has no fetchers and no
    TransportCollector, so only condition 1 applies there.
  - Why all three: in a steady-traffic step that didn't scale, condition 3 is already true when the load stops, and
    the input queue is empty as soon as the last requests are picked up, while those requests are still being
    processed. Checking only 3 (or 3 + waiting messages) would end the step too early and mix its last responses into
    the next step.
  - ECS and K8s: the primary fetchers (`aws.ecs_api`, `k8s.api`) are live, so the end is seen within one poll.
  - Lambda: the primary fetcher (`aws.cloudwatch_metric.ConcurrentExecutions`) is also **polled during the run**
    for this, accepting the CloudWatch delay. Lambda sends metric data to CloudWatch in 1-minute intervals. The
    recorded counts still come from the after-run call, which has the complete data. If the delay turns out too long,
    the host can be switched to `aws.lambda_log_streams` by config (a manual choice, not automatic).
- **Maximum cool-down time:** configurable, **default 45 min**, counted from `t_load_down`. If it's reached, the step
  ends, records `cooldown_max_reached = true`, "scale-down done" stays empty and `workers_after_down` shows where it
  stopped. Why 45 min:
  - It's a safety net for a step that never gets back to the starting count, so it's set from the slowest host.
  - ECS is the slowest: target tracking starts scaling in only after 15 one-minute datapoints below target (~15 min),
    then waits `scale_in_cooldown` (our Terraform default 120 s) between scale-in activities, and target tracking
    removes capacity more conservatively than it adds it. So a normal ECS scale-in is expected to take ~15–25 min.
  - K8s (HPA, 5 min default stabilization window) and Lambda (concurrency drops when invocations stop) are expected
    to finish well within it.
  - 45 min leaves room for an ECS scale-in that takes several activities, without cutting it off and losing the
    scale-down result. Waiting too long only costs time; ending too early loses data.
  - Can be set per host (e.g. lower for K8s / Lambda) once real scale-in times are known.
- The steps are run one after another, so each step starts from the minimum workers.

### What to record (per time window, e.g. 1 s or 5 s)

Added to the per-time-window CSV, next to Tx/Rx/errors:

- **Desired workers:** what the autoscaler asked for.
- **Running workers:** what the platform says is running. On serverless hosts this is the number of instances that
  were handling work in the window (that's what their metrics and logs count).
- **Pending workers** (K8s only): pods created but not scheduled, e.g. when bare-metal nodes are full.
- **Queue depth:** input and output queue backlog, each queue in its own column (SQS
  `ApproximateNumberOfMessagesVisible`, Kafka consumer-group lag).
- **Latency percentiles** (p0 / p25 / p50 / p75 / p100) of requests completed in that window.

Worker counts are recorded **per tier** and **per scaling info fetcher** (below). Which tiers scale depends on the host
(checked against our Terraform):

- **ECS:** only the agent runner autoscales (target tracking on `BacklogPerTask`). The REST/IO service runs a fixed
  `desired_count` (default 1) with no autoscaling, so its count is recorded but stays flat.
- **Lambda:** every function scales on its own: request handler, agent runner, response handler (and the WebSocket
  connection handler). Each is recorded as its own tier.
- **Local (`in_memory`):** one process, nothing scales. There are no fetchers and no scaling is recorded locally.

### Scaling info fetchers (pluggable)

Every host has more than one way to read its worker counts (a management API, a monitoring metric, the logs), with
different resolution and delay. Each way is a separate plugin, a **scaling info fetcher**: a subclass of one abstract
class, `ScalingInfoFetcher`, so a new way can be added for any host without touching the harness.

- **One fetcher = one way to read worker counts on one platform**, with a registry name (e.g. `aws.ecs_api`,
  `aws.cloudwatch_metric.ConcurrentExecutions`). A host lists one or more fetchers; the benchmark config can turn fetchers on or off per
  run.
- **One method for all fetchers:** `fetch(run, deployment, start, end) -> ScalingInfo`, plus a `live` flag that says
  when the harness calls it. Data is only available at different times, but the call is the same:
  - **`live = True`:** management APIs (ECS, K8s, Azure Container Apps) only show the current state, so the shared poll
    loop calls `fetch` every few seconds during the run with (last poll, now).
  - **`live = False`:** monitoring metrics and logs keep history but arrive late, so `fetch` is called once after the
    run with (run start, run end). This runs automatically at the end of the run after a configured wait, and can be
    re-run later with `collect-scaling --run-id …`, which refills the CSVs and re-plots.
- **Not split by serverless / containerized:** the harness never checks what kind of host it is. A host is only ever
  one kind, the line between them is blurry (Fargate, Cloud Run, Azure Container Apps), and the fetching code depends
  on where the data comes from, not on the deployment type.
- **Common return type (`ScalingInfo`):** every fetcher returns the same data, so the shared code never knows where it
  came from:
  - **Count samples:** `(ts, tier, count type, value)`, count type = desired / running / pending.
  - **Worker spans** (optional, from fetchers that see individual workers): `(tier, worker, started, stopped)`, plus
    extra fields where useful (e.g. ECS `pullStartedAt` for the cost estimate). The shared code turns spans into a
    running count at any window size, so these give exact times, not just poll-interval resolution.
- **Which resources to watch:** a fetcher gets the per-tier resource ids from the deployer's `Deployment.resources`
  (ECS cluster and service names, K8s Deployment names, Lambda function names, ...), so it needs no extra config.
- **One `fetch()` covers every tier:** the fetcher loops over `Deployment.resources` and runs the same code for each
  tier, tagging each count with its tier name. No per-tier code.
  - ECS: one `aws.ecs_api` call reads the agent runner service and the IO service.
  - Lambda: one `aws.cloudwatch_metric.ConcurrentExecutions` call reads every function (request handler, agent
    runner, response handler, WebSocket connection handler).
  - Adding or removing a tier is a change to the deployer's `resources` only. Fetchers, CSV columns, the end-of-step
    check and the graphs pick it up as is.
  - Turning on autoscaling for a tier that's already listed (e.g. the ECS IO service, which our Terraform doesn't
    autoscale today) needs no benchmark change: its line just stops being flat.
- **All fetchers are recorded side by side:** the per-time-window CSV has one column per tier × count type × fetcher
  (e.g. `runner.running.aws.ecs_api`), and the derived numbers below are computed for every fetcher. Fetchers can
  disagree (different resolution and lag); that's shown, not reconciled.
- **Candidates for now:** where a host lists two fetchers below, both are kept as candidates while the design is
  discussed. Each host will be finalized to one fetcher; until then both are recorded side by side.
- **Primary fetcher:** the first fetcher in the host's list. The end-of-step check uses it. The benchmark
  config can change the order. The summary CSV records which fetcher each number came from.
- **Reuse across platforms:** generic fetchers take constructor parameters instead of being rewritten, e.g. one cloud
  metric fetcher per monitoring backend (CloudWatch, Cloud Monitoring, Azure Monitor) given the metric name, and one
  "distinct instance ids in the logs" fetcher per log backend given the id field. The log-based ones share the log
  fetching code with the TraceCollector for the same backend. One K8s fetcher serves EKS, bare metal, GKE and AKS.
- **A count with no fetcher** on a platform (e.g. `desired` on Lambda) stays empty.

Class sketch and a worked example: to be specified in `spec.md`.

Fetchers per host (✓ = available now, later = when the platform is added), primary first:

| Host | Fetcher | `live` | Gives | Resolution |
|------|---------|--------|-------|------------|
| ECS ✓ | `aws.ecs_api`: `DescribeServices` (`desiredCount`, `runningCount`) + `DescribeTasks` (task `createdAt` / `pullStartedAt` / `startedAt` / `stoppedAt`) | yes | desired, running, spans | poll interval; spans exact |
| ECS ✓ | `aws.ecs_scaling_activities`: Application Auto Scaling `DescribeScalingActivities` (`StartTime`, "Setting desired count to N") | no | desired | exact |
| EKS / bare metal ✓, GKE / AKS later | `k8s.api`: Deployment `spec.replicas` (set by KEDA/HPA), `readyReplicas`, pod start/stop times, `Pending` pods | yes | desired, running, pending, spans | poll interval; spans exact |
| Lambda ✓ | `aws.cloudwatch_metric.ConcurrentExecutions`: CloudWatch `AWS/Lambda` metric per function (`FunctionName` dimension), `Maximum` statistic | no | running | 1 min |
| Lambda (written, not bound to the host) | `aws.lambda_log_streams`: one span per log stream (= per execution environment), from its first to its last `REPORT` line | no | running, spans | exact to about one invocation |
| Azure Container Apps (later) | `azure.aca_replicas_api`: List Replicas (`createdTime`, `runningState`) | yes | running, spans | poll interval |
| Azure Container Apps (later) | `azure.monitor_metric.Replicas` (split by revision only) | no | running | 1 min |
| Cloud Run (later) | `gcp.logging_instance_ids`: distinct `labels.instanceId` in Cloud Logging | no | running | any window size |
| Cloud Run (later) | `gcp.monitoring_metric.instance_count` (state active / idle) | no | running | not verified |
| Azure Functions Flex (later) | `azure.app_insights_instances`: `dcount(cloud_RoleInstance)` per window | no | running | any window size |
| Azure Functions Flex (later) | `azure.monitor_metric`: instance count (emitted every 30 s) | no | running | 30 s |

- Only ECS and K8s expose a **desired** count. Lambda, Cloud Run and Azure Functions have none, and Azure Container
  Apps runs KEDA internally without exposing it.
- **Lambda: only `aws.cloudwatch_metric.ConcurrentExecutions` is bound to the host.** `aws.lambda_log_streams` is
  written too but not bound; see [Lambda: `ConcurrentExecutions` bound, log streams written but not bound](#lambda-concurrentexecutions-bound-log-streams-written-but-not-bound) below.
  - `ConcurrentExecutions` is "the number of active concurrent invocations at a given point in time". Lambda emits it
    for all functions, versions and aliases (no reserved concurrency needed), at 1-minute granularity, and AWS says to
    read it with the `Maximum` statistic.
  - One `GetMetricData` call per run, one query per function (tier), period 60 s.
  - It gives `running` only: no `desired` and no worker spans. So the Lambda scaling times (first new worker,
    scale-up done, scale-down start/done) have 1-minute resolution.
  - Lambda doesn't report when an environment is shut down; the metric counts invocations in progress. "Scale-down
    done" on Lambda means "concurrent invocations are back to the baseline level".
- `aws.lambda_log_streams` runs one Logs Insights query per function: `stats min(@timestamp), max(@timestamp) by
  @logStream` over the `REPORT` lines. That's one row per execution environment, so the count is exact (no
  `count_distinct`, which is approximate for high counts) and stays far below the 10,000-rows-per-page limit.
  - A `REPORT` line is written when an invocation ends, so a span starts up to one invocation (agent delay + cold
    start) late.
  - Lambda doesn't report when an environment is shut down, so a span ends at the environment's last invocation.
    With this fetcher, "scale-down done" means "the extra environments stopped getting invocations".
- `aws.ecs_api` keeps every task it has seen across polls (merged by task ARN), because stopped tasks only stay
  visible in `DescribeTasks` for at least 1 hour after they stop. Polling during the run catches all of them.
- `aws.ecs_scaling_activities` gives the exact time of each autoscaler decision (activity history is kept 6 weeks), so
  the decision delay isn't limited by the poll interval. The new desired count is parsed from the activity's
  description text; if a description can't be parsed, only the `aws.ecs_api` desired count is used.
- **ECS scale-down:** target tracking only starts scaling in ~15 min after the load drops, then waits
  `scale_in_cooldown` (120 s in our Terraform) between steps. `aws.ecs_api` doesn't wait for or detect this; it keeps
  polling through the whole cool-down (see [Scale-down delay](#scale-down-delay-per-platform)), and the shared code
  reads "scale-down start" and "scale-down done" from the recorded counts afterwards. If the cool-down hits its maximum,
  "scale-down done" stays empty and `workers_after_down` shows where it stopped.

#### Lambda: `ConcurrentExecutions` bound, log streams written but not bound

- **Both fetchers are written.** Only `aws.cloudwatch_metric.ConcurrentExecutions` is bound to the Lambda host (it's
  the only entry in its fetcher list in `hosts.py`). `aws.lambda_log_streams` is implemented, but not listed in any
  host.
- **Try the metric first.** Why:
  - It's AWS's own concurrency number, the same one the Lambda console graphs and the concurrency quota is checked
    against.
  - Simplest to run: one `GetMetricData` call, no Logs Insights queries (billed per GB scanned), no dependence on log
    lines.
  - Reuses the generic `CloudWatchMetricScalingInfoFetcher`.
- **Switching is manual.** If the first Lambda runs show the metric's known limits get in the way, a person binds
  `aws.lambda_log_streams` to the Lambda host in `hosts.py` by hand. There's no automatic fallback and no config
  switch; the harness never picks a fetcher on its own. The limits to look for:
  - 1-minute resolution is too coarse to read the Lambda scale-up/down times.
  - It reads low because it counts invocations in progress, not environments that are alive (e.g. with a short agent
    delay).
- If both end up bound, they're recorded side by side like any other pair of fetchers.

| | `aws.cloudwatch_metric.ConcurrentExecutions` | `aws.lambda_log_streams` |
|---|---|---|
| What it counts | Invocations running at the same moment | Execution environments (workers) |
| Resolution | 1 min | Exact to about one invocation |
| Per-worker start/stop | No | Yes (spans) |
| Exact time of each scale-up/down step | No: one aggregated value per minute, and Lambda publishes no scaling events to get the times from | Yes (from the spans) |
| With a short agent delay (e.g. 0 ms) | Reads low: environments sit idle between short invocations | Still counts every environment |
| Cost / effort | One `GetMetricData` call, simplest | One Logs Insights query per function (billed per GB scanned) |
| Depends on | The per-function metric (emitted for all functions) | `REPORT` lines in CloudWatch Logs |

- ECS tasks also get one log stream each (`awslogs` driver: `<awslogs-stream-prefix>/<container name>/<task id>`; our
  Terraform uses prefix `ecs`). A log-based ECS fetcher is possible but not needed: `aws.ecs_api` already gives each
  task's exact created / started / stopped times, including the image pull before the task writes any log.

### Derived numbers (written to the summary CSV)

Scale up, measured from `t_load_up` (the step's first send):

- **Decision delay:** `t_load_up` → first increase in desired workers (empty where no source gives `desired`).
- **First new worker:** `t_load_up` → first increase in running workers (or the first span started after
  `t_load_up`, for sources with spans).
- **Scale-up done:** `t_load_up` → running worker count reaches its peak in the step.
- **Backlog drained:** `t_load_up` → queue depth back to the baseline level.

Scale down, measured from `t_load_down` (the end of the step's load part):

- **Scale-down start:** `t_load_down` → first decrease in desired/running workers.
- **Scale-down done:** `t_load_down` → running workers back to the baseline count.

The times above and the worker counts below are computed per tier and per scaling info fetcher.

Worker counts (from → to), recorded per tier, count type (desired / running) and fetcher, next to the times:

| Number                 | Scale up                                                  | Scale down                                           |
|------------------------|-----------------------------------------------------------|------------------------------------------------------|
| **From**               | `workers_before_up`: count at `t_load_up` (end of baseline) | `workers_before_down`: count at `t_load_down`        |
| **To**                 | `workers_peak`: highest count in the step                 | `workers_after_down`: count at the end of the cool-down      |
| **Change**             | `peak − before_up` workers added                          | `before_down − after_down` workers removed           |
| **Rate**               | workers added ÷ (scale-up done − first new worker), as workers/min | workers removed ÷ (scale-down done − scale-down start), as workers/min |

- So each scaling result reads like "ECS runner: 2 → 18 tasks in 7.5 min (first new task at 4 min, ~4.6 tasks/min);
  18 → 2 in 21 min".
- **The rate is an average over the scaling window.**
  - The "scaling window" is the time span while workers are being added (first new worker → scale-up done), or removed
    (scale-down start → scale-down done). It is **not** the 1 s / 5 s time windows of the per-time-window CSV.
  - Example above: 16 tasks added between minute 4 and minute 7.5, so 16 ÷ 3.5 min ≈ 4.6 tasks/min.
  - Platforms don't add workers evenly. They add them in steps, e.g. ECS goes 2 → 8 at minute 4, waits out the
    scale-out cooldown, then goes 8 → 18. The rate smooths these steps into one number, which hides the shape.
  - The step pattern itself is seen in the worker-count graph, not in this number. What sets the steps:
    - K8s HPA: re-evaluates every 15 s and by default adds at most 4 pods or 100% of current replicas (whichever is
      more) per 15 s.
    - ECS target tracking: each scaling activity adds capacity in proportion to how far the metric is above target, then
      waits for the scale-out cooldown (300 s Application Auto Scaling default for ECS; our Terraform sets 30 s) before
      adding more, unless a larger scale-out is
      triggered.
    - Lambda: see the Lambda note under [Platform notes](#platform-notes-that-will-show-up-in-the-numbers).
- A count that has no source on a platform stays empty (e.g. `desired` on Lambda, see
  [Scaling info fetchers](#scaling-info-fetchers-pluggable)).
- `workers_after_down` can be above the baseline count if scale-down didn't finish inside the cool-down; then
  "scale-down done" is empty and the "to" count shows where it stopped.

### Platform notes that will show up in the numbers

- **ECS:** the `BacklogPerTask` custom metric is published by a Lambda on `rate(1 minute)`, and target tracking
  scales out after **3 consecutive one-minute datapoints** above target. So the decision delay is at least ~3 min,
  plus Fargate task start (image pull + container start). AWS measured ~6 min on average to trigger scale-out with
  60 s metrics. The 20 s high-resolution metrics AWS launched in June 2026 (~86 s to trigger) only cover the built-in
  CPU/memory metrics, not custom metrics like ours.
- **EKS / bare metal:** scaling from 1 to N is driven by the HPA, which re-reads the metric every **15 s** (default
  sync period). KEDA's `pollingInterval` (30 s) only matters when scaling up from 0. By default the HPA adds at most
  **4 pods or 100% of current replicas (whichever is more) per 15 s**, so a big load increase is followed in steps. Pod start adds
  image pull and startup. On bare metal there's no node autoscaler, so scaling stops when the nodes are full (pods go
  `Pending`; record the pending count too). Max replicas are capped by the input topic's Kafka partitions (KEDA's
  Kafka scaler won't go past the partition count unless `allowIdleConsumers: true`).
- **Lambda:** no explicit workers. With the SQS event source mapping in default mode, Lambda starts with 5 concurrent
  invokes and adds up to **300 per minute**, up to **1,250** per mapping (and within the account concurrency quota,
  1,000 by default). An optional *provisioned mode* (min/max event pollers) scales faster. Scale-down is effectively
  immediate. The worker count is read from the `ConcurrentExecutions` metric
  (`aws.cloudwatch_metric.ConcurrentExecutions`). Each execution environment also writes to its own CloudWatch log
  stream (`YYYY/MM/DD/[version]<env GUID>`), so counting distinct log streams per window gives the environment count
  (`aws.lambda_log_streams`, written but not bound to the host).
  - **How AK uses it (checked in the code):** the agent runner's SQS event source mapping has `batch_size = 10` and
    AK's `SQSConsumer` handles the records of a batch **one after another**, so one invocation with 10 messages and a
    2 s agent delay runs ~20 s. The agent runner timeout is 45 s by default (`ak-aws/serverless/variables.tf`, `agent_runner`),
    so `batch_size × agent delay` has to stay under it (a 5 s delay with batch size 10 hits the timeout). Batch size, timeout and agent delay are saved in the
    run metadata.
  - So the number of concurrent executions is much lower than the number of requests: each
    environment handles a batch of messages, then the next batch. Example: 1000 requests at once, 2 s each, batch
    size 10, default mode: 5 invocations at first, +300 per minute (~5 per second), so all 100 batches are picked up
    after ~20 s by ~100 environments, and the last ones finish ~20 s later. That's a `ConcurrentExecutions` peak of
    roughly 100, not 1000 (rough estimate, not measured).

All autoscaling settings for the run (returned by the Deployer's `deployed_settings()`) are saved in the run metadata so the times can be explained later: min/max,
target, cooldowns, HPA `behavior`, KEDA polling interval, Kafka partitions, Lambda ESM mode / max concurrency, and
the worker size (task vCPU/memory, pod resource requests/limits, Lambda memory).

### Graphs

- Worker count over time (desired / running, one line per scaling info fetcher) with the start and end of the step's
  load marked.
- Avg latency and queue depth over time on the same time axis.
- Tx/Rx over time across the whole step.

## Cost

Two separate things: what a run **actually cost** (test costs), and an **estimate** of what running AK costs per
target (cost models).

### Two cost numbers per run: billed and estimated

| | Billed | Estimated |
|---|---|---|
| Source | the cloud's bill (AWS Cost Explorer, filtered by the run tag) | usage × price table, computed by the benchmark |
| Accuracy | exact: what is paid, incl. discounts, free tier, Savings Plans | close: list prices |
| Available | ~1 day after the run (`collect-cost` step) | at the end of the run |
| Split by time | whole run only (daily, or hourly if enabled) | any window: per step, per step part |
| Bare metal | none (no bill) | yes ($/node-hour) |
| What-if ("cost of 1M messages?") | no | yes: the cost model is built from it |

- **Per-step costs, cost per 1M requests and the cost model come from the estimate.** The billed number is the real
  cost of the whole run and checks the estimate.
- Both are recorded and graphed side by side (estimated vs. billed per run). A large gap means the estimate is
  missing a usage source (e.g. NAT gateway, data transfer, CloudWatch Logs). Adding that source and recomputing old
  runs works, because usage is stored separately from prices.

### How the cost code is split

Same pattern as the scaling info fetchers: the cloud-specific code only **fetches numbers**, all the maths is shared.

- **Usage sources:** one small class per billed thing (Fargate tasks, Lambda, SQS, API Gateway WebSocket, ALB, K8s
  nodes, ...), not one class per cloud, so no class fills up with `if lambda / if ecs` branches. Each host lists the
  ones it's billed for (e.g. ECS = Fargate + SQS + ALB, Lambda = Lambda + SQS + API Gateway). Each returns quantities
  with a time range (`usage(run, deployment, start, end)`), so the shared code can cut them per step. Most read data
  the run already has (e.g. the ECS task spans from `aws.ecs_api`).
- **Billing reader:** one per cloud (AWS: Cost Explorer). Returns `None` where there's no bill.
- **Price source:** one per cloud, see [Prices](#prices-fetched-per-run-saved-with-the-results).
- **Shared code:** usage × prices per component, per-step costs, cost per 1M successful requests, idle cost,
  estimated vs. billed, CSVs and graphs. It never calls a cloud API.
- Adding a cloud = its usage sources + billing reader + price source. Adding a billed service on an existing cloud =
  one usage source. A provider changing **how** it bills something only changes that one usage source.

### 1. Test costs (actual cost of each run)

**Tag everything.** Every resource the runner deploys gets a `ak-bench-run-id` tag (Terraform `default_tags`, Helm
labels). Then two numbers are recorded:

- **Billed cost (authoritative, delayed):** AWS Cost Explorer `GetCostAndUsage` filtered by the run tag, grouped by
  service. Caveats:
  - The tag must be activated as a cost allocation tag (management account). Tagged costs show from activation on;
    the management account can **backfill** up to 12 months (one backfill request per 24 h). Costs only appear for
    periods when the tag was actually on the resource.
  - Cost Explorer refreshes at least once every 24 h (some data can arrive later), so this is a **separate, later
    step** (`collect-cost --run-id …`) that fills in the cost CSV after the run. It fits the existing "re-plot from
    existing CSVs" option. Each Cost Explorer API request costs $0.01.
  - Daily granularity is enough for a run's total, since every run has its own tag: only that run's resources
    carry its tag value, so the run's billed cost is the sum of the daily rows for that value over the days the run
    covered (two days if it crosses midnight). Not using hourly (decided 2026-10-29). Hourly granularity (opt-in, about
    $0.01 per 1,000 usage records per month) only helps if we want the cost per step of a run, and hourly data is kept
    for **14 days** only, so `collect-cost` must run within that window.
  - Shared or long-lived resources (EKS control plane, NAT gateway, a long-lived MSK cluster) can be tagged, but if
    they're shared across runs or used by other things, their cost must be listed as a fixed allocation instead. The
    automatic `aws:eks:cluster-name` tag doesn't cover the EKS control plane fee.
- **Usage-based estimate (immediate):** computed at the end of the run from the usage the runner already sees, times
  a price table. Usage is recorded with timestamps, so the same estimate is also split **per step** (first send → end
  of cool-down), which gives the [per-step costs](../design.md). Cost Explorer can't split a run this finely
  (daily, or hourly if enabled), so per-step costs always come from the estimate; the billed total checks the
  estimate for the whole run.
  - ECS/Fargate: task-seconds × (vCPU, GB). Fargate bills per second with a 1-minute minimum, from the **start of
    the image pull** until the task stops, so use the task's `pullStartedAt` → `stoppedAt` (the `aws.ecs_api`
    scaling info fetcher already records them in its worker spans), not `startedAt`.
  - Lambda: GB-seconds from the `REPORT` log lines (`Billed Duration` × `Memory Size`), plus request count.
  - SQS: SQS bills per **API request**, not per message: a batch of up to 10 messages is one request per 64 KB of
    payload, and empty receives are billed too. CloudWatch's `NumberOfMessagesSent/Received/Deleted` count messages,
    so they overcount when batching is used. Count requests from AK's own send/receive/delete calls (or divide by
    the batch sizes used), plus `NumberOfEmptyReceives`.
  - API Gateway WebSocket: messages (metered in 32 KB blocks; ping/pong not billed) + connection minutes.
  - Session store (Redis/DynamoDB), ALB, NAT: hours/units used.
  - EKS: node-hours + control plane hours. For pod-level cost, AWS **split cost allocation data for EKS** (in the
    Cost and Usage Report) or OpenCost/Kubecost if installed.
  - **Bare metal:** there's no bill, so cost is always this estimate: node-hours × a configured $/node-hour (hardware
    amortisation + power/hosting), supplied in the benchmark config.

Recording both lets the estimate be checked against the bill, which is also how the cost model gets validated.

### 2. Cost models (estimated cost per target)

Split every target's cost into a **fixed (idle)** part and a **variable (per-message)** part:

```
monthly_cost(N messages) = idle_cost_per_month + N × cost_per_message
```

- **Idle cost:** what the deployment costs with zero traffic: min replicas × hours, always-on infra (ALB, NAT, Redis,
  MSK brokers, EKS control plane, Kafka nodes). Measured by leaving the deployment idle for a fixed window (e.g. 1 h)
  and pricing the usage, or computed directly from the min-capacity settings. Lambda + SQS will be near zero apart from
  the session store; ECS/EKS pay for min replicas.
- **Cost per message (→ cost per 1M messages):** derived from the benchmark's own measurements, not guessed:
  - Per-request services (SQS, API Gateway, DynamoDB, Lambda invocations): count of billed operations per message,
    from the run's usage ÷ messages handled (e.g. SQS: send + receive + delete on both queues, divided by batching).
  - Compute: for containers, worker-seconds per message at the measured saturation throughput (from the throughput
    tests: messages/s per worker). For Lambda, GB-seconds per message.

**Inputs and outputs:**

- A **price table** per run (region + date it was fetched), saved with the run's results. See
  [Prices](#prices-fetched-per-run-saved-with-the-results).
- Cost CSV columns (per host × mode): `idle_cost_per_hour`, `cost_per_1m_messages`, broken down by component, plus
  `test_cost_estimated`, `test_cost_billed` (filled later), and the price-table version.

**Caveats to state with the numbers:**

- With the mock agent, the model covers **AK infrastructure only**; LLM token costs are excluded.
- The mock agent's delay is a cost driver for Lambda and containers (they're billed while waiting), so cost per message
  is reported for the agent delay used, and the model takes agent duration as a parameter.

### Graphs

- Test cost per run: estimated vs. billed.

### Prices: fetched per run, saved with the results

Nobody edits prices by hand when a provider changes them.

- **Fetched at the start of each run** by the cloud's price source, from the provider's public price API (list
  prices):
  - AWS: Price List Query API, `GetProducts` (on-demand terms, `pricePerUnit`).
  - GCP (later): Cloud Billing Pricing API (public SKUs and prices; needs an API key, no IAM permissions).
  - Azure (later): Retail Prices API, `https://prices.azure.com/api/retail/prices` (no authentication).
- **Saved with the run** (`results/<run-id>/<platform>/<host>/<mode>/price_table.json`, with fetch date and region; layout in [design.md](../design.md)). Old runs keep the
  prices they ran with, and any run can be re-priced later with newer prices from its stored usage.
- **Config file only for what has no API:** the bare-metal $/node-hour, and optional overrides (e.g. a negotiated
  discount). An override is recorded in the saved price table.
- The billed cost doesn't use the price table; it already has the real prices.

## Open points

- Load-step tests, Lambda end detection, not verified: whether `ConcurrentExecutions` has **no datapoint** (rather
  than 0) in a minute with no invocations. AWS says Lambda sends metrics when a function finishes processing an
  event, which suggests idle minutes are missing. If so, a missing datapoint has to be read as 0, but only for minutes
  old enough that their data would have arrived (a configurable metric delay; value to be measured on the first
  Lambda runs).
- The $/node-hour figure for the bare-metal cluster.
- Not verified: whether the fixed 3 / 15 datapoint rule still applies to custom metrics (like `BacklogPerTask`) after
  AWS's June 2026 faster-scaling launch. AWS only describes the change for the built-in CPU/memory metrics. Check the
  CloudWatch alarms that the ECS policy creates once deployed.
- Not verified: the sampling interval of Cloud Run's `container/instance_count` metric (the Cloud Functions
  `instance_count` metric is sampled every 60 s). Check when Cloud Run is added.
- Not verified: whether the "Setting desired count to N" wording of ECS scaling activity descriptions is stable enough
  to parse.
- Not verified: the exact API name of the Azure Functions Flex instance count metric (the docs show both
  "Automatic Scaling Instance Count" and `InstanceCount`). Check with `az monitor metrics list-definitions`.
- Which one fetcher to keep for ECS: `aws.ecs_api` alone, or with `aws.ecs_scaling_activities`.
- Whether Lambda stays on `ConcurrentExecutions` or switches to `aws.lambda_log_streams`: decided after the first
  Lambda runs (see [Lambda: `ConcurrentExecutions` bound, log streams written but not bound](#lambda-concurrentexecutions-bound-log-streams-written-but-not-bound)).
- How long the after-run scaling step (`live = False` fetchers) waits before querying metrics and logs (log ingestion delay differs per backend).

## Sources (checked 2026-10-20; GCP / Azure scaling fetchers checked 2026-10-22; Lambda metrics checked 2026-10-23)

- Horizontal vs. vertical scaling terms: https://wa.aws.amazon.com/wellarchitected/2020-07-02T19-33-23/wat.concept.horizontal-scaling.en.html
- KEDA ScaledObject spec (`pollingInterval`, `cooldownPeriod`): https://keda.sh/docs/2.18/reference/scaledobject-spec/
- KEDA Kafka scaler (`allowIdleConsumers`): https://keda.sh/docs/2.17/scalers/apache-kafka
- Kubernetes HPA (sync period, default `behavior`): https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- Application Auto Scaling target tracking (cooldown defaults; scale-in more conservative than scale-out): https://docs.aws.amazon.com/autoscaling/application/userguide/target-tracking-scaling-policy-overview.html
- Lambda sends metric data to CloudWatch in 1-minute intervals, when a function finishes processing an event: https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics.html
- Target tracking 3 / 15 datapoints and the June 2026 faster scaling: https://github.com/aws/containers-roadmap/issues/2113
- ECS high-resolution metrics: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/target-tracking-faster-auto-scaling.html
- Lambda SQS scaling: https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html
- Lambda concurrency metrics (1-minute granularity, "active concurrent invocations", emitted for all functions, versions and aliases, view with MAX): https://docs.aws.amazon.com/lambda/latest/dg/monitoring-concurrency.html
- Lambda metric types (`ConcurrentExecutions` per function, `Max` statistic): https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html
- Lambda log streams: https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs-view.md
- ECS `awslogs` stream name format: https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_LogConfiguration.html
- ECS stopped tasks visible ≥ 1 hour: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/stopped-task-errors.html
- Application Auto Scaling scaling activities (6 weeks): https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-scaling-activities.html
- Logs Insights discovered fields for Lambda (`@logStream`, `@duration`, `@type`): https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_AnalyzeLogData-discoverable-fields.html
- Logs Insights `count_distinct` is approximate: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax-Stats.html
- Logs Insights result paging (10,000 per page): https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html
- Cloud Run logging (`labels.instanceId`): https://docs.cloud.google.com/run/docs/logging
- Cloud Run monitoring (instance count metric): https://docs.cloud.google.com/run/docs/monitoring
- Cloud Functions `instance_count` sampling: https://docs.cloud.google.com/monitoring/api/metrics_gcp_c
- Azure Container Apps List Replicas API: https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps-revision-replicas?view=rest-resource-manager-containerapps-2026-01-01
- Azure Container Apps metrics (`Replicas`, PT1M): https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-app-containerapps-metrics
- Azure Functions monitoring reference (instance count metric, 30 s): https://learn.microsoft.com/en-us/azure/azure-functions/monitor-functions-reference
- Azure Functions telemetry (`cloud_RoleInstance` queries): https://learn.microsoft.com/en-us/azure/azure-functions/analyze-telemetry-data
- Cost allocation tag backfill: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-allocation-backfill.html
- Cost Explorer hourly granularity: https://docs.aws.eu/cost-management/latest/userguide/ce-hourly-granularity.html
- Cost Explorer pricing: https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/
- SQS pricing: https://aws.amazon.com/sqs/pricing/
- AWS Price List Query API (`GetProducts`, on-demand `pricePerUnit`): https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list-query-api.html, https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html
- GCP Cloud Billing Pricing API (public prices, API key): https://docs.cloud.google.com/billing/docs/how-to/get-pricing-information-api
- Azure Retail Prices API (unauthenticated): https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
- SQS `GetQueueAttributes` (`ApproximateNumberOfMessages`, `ApproximateNumberOfMessagesNotVisible` = in flight, consistent only ≥ 1 min after producers stop): https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_GetQueueAttributes.html
- Fargate pricing: https://aws.amazon.com/fargate/pricing/
- API Gateway pricing: https://aws.amazon.com/api-gateway/pricing/
- EKS split cost allocation data: https://docs.aws.amazon.com/cur/latest/userguide/split-cost-allocation-data.md
- EKS cost awareness (control plane tagging): https://docs.aws.amazon.com/eks/latest/best-practices/cost-opt-awareness.html
