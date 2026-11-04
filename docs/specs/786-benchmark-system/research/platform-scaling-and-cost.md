# Research: Measuring Scaling and Cost

How the [Scaling](../design.md) and [Cost](../design.md) requirements are measured. Both follow the
"record and report only" principle: the runner records timestamps, counts and dollars, and the graphs show them. The
derived numbers below (scale-up time, scale-down time) are fixed calculations over the recorded data, not
pass/fail checks.

## Pluggable per-platform collectors

Every cloud has its own APIs for worker counts and cost (ECS `DescribeServices` vs. GCP Cloud Monitoring /
Azure Monitor; AWS Cost Explorer vs. GCP BigQuery billing export vs. Azure Cost Management). GCP and Azure
are coming later, so the platform-specific parts are kept behind interfaces and everything else is shared:

```
Host (registered by name, e.g. "ecs", "lambda", later "cloud_run", "aca")
├── Deployer            deploy() -> Deployment(endpoint(url, auth), resources: {tier: resource id},
│                                  queues: {"input": ids, "output": ids}, logs: {component: log source})
│                       teardown()
│                       deployed_settings() -> dict  (autoscaling settings + worker size, saved in run metadata)
├── ScalingInfoFetchers one or more per host; each reads worker counts one way (see Scaling info fetchers below)
├── ResourceUsageFetchers one or more per host; each reads worker CPU / memory one way (see resource-usage.md)
├── TraceCollector      fetch(run, deployment, start, end) -> TraceInfo  (stage timestamps per request, from the AK trace logs)
├── BillingReader       billed(run) -> [CostItem(component, usd)] | None   (one per cloud; later step; None if no bill)
└── TransportCollector  fetch(run, deployment, start, end) -> QueueInfo  (queue depth: waiting, in flight, per queue;
                        picked by transport: sqs, later pubsub, servicebus)
```

- **One base class for everything read from the platform during a step:** `ScalingInfoFetcher`,
  `ResourceUsageFetcher`, `TraceCollector` and `TransportCollector` all extend the generic `InfoFetcher[T]`, so they
  have the same methods and parameters:
  - constructor parameters `live_track: bool = False` and `poll_interval_s`;
  - `fetch(run, deployment, start, end) -> T`: the only method a platform subclass writes;
  - `store(result: T, step)`: written once in each of the four family bases, since each stores a different type;
  - `fetch_and_store(...)`: written once in `InfoFetcher`; calls `fetch()`, then `store()`.
  - Each family base fixes `T`: `ScalingInfo`, `ResourceUsage`, `TraceInfo`, `QueueInfo` (dataclasses). A type
    checker flags a subclass whose `fetch()` returns another type, and `fetch_and_store` raises a clear error if it
    does at runtime.
  - So the step runner calls all of them the same way (see
    [Scaling info fetchers](#scaling-info-fetchers-pluggable)). The billing reader and the Deployer don't extend it: they
    run once per run or after the run, not inside a step.
- **Shared, platform-independent code:** run orchestration, the step runner (live tracking, cool-down check, after-step fetch) and timestamps,
  turning scaling
  source output into per-window worker counts, all derived numbers (scale-up/down times),
  CSV writing and graphs. It only sees the common return types above.
- **Per-platform code:** only the API calls that fill those types. A field with no source on a platform (e.g. `desired`
  on Lambda) is returned as empty and the column stays blank.
- **Reuse within a platform family:** e.g. the AWS billing reader, the CloudWatch Logs trace collector and the SQS
  transport collector are shared by Lambda and ECS.
- **Adding GCP or Azure** = implement these for the new host and register it. No changes to the harness, CSVs
  or plots.
- Worker counts come only from the platform side (APIs, metrics, logs). Nothing in AK or the benchmark pre-hook
  reports a worker id.

File and class layout for these interfaces: to be specified in the implementation spec (written after this design is
approved).

## Scaling

### Terminology

- **Horizontal scaling:** changing the **number** of workers (tasks, Lambda execution environments). Each
  worker stays the same size. The usual names are **scale out** (add workers) and **scale in** (remove workers).
- **Vertical scaling:** changing the **size** of each worker (more or less CPU/memory per task, a bigger Lambda
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
- **Lambda:** concurrency falls as soon as invocations stop; the SQS pollers scale back down on their
  own.

### Load-step tests: scaling per step

The [load steps](../design.md) of both test types (burst and steady traffic) also record scaling, over each
step's [timeline](../design.md): before → load → cool-down → wait + fetch. The
data covers the first three parts; the fourth waits for log ingestion (default 1 min) and then fetches the step's data
with history. Live tracking runs from the start of "before" to the end of the cool-down.

- The derived numbers below are computed per step, with `t_load_up` = first send of the step and `t_load_down` = end
  of the load part (steady traffic: the configured time is up; burst: the last response arrived or timed out).
- **When the cool-down ends:** the step runner checks three things on every poll during the cool-down, and the step ends when
  all three hold in the same poll. They're checked in this order (decided 2026-11-03, PR #877 review), and a later check only runs once the earlier ones hold:
  1. **All requests settled (client):** every request sent in the step has a response or has timed out. This alone
     covers requests that completed normally.
  2. **Pipeline empty (TransportCollector):** both queues hold nothing, counting messages still being processed.
     The queue ids come from `deployment.queues` (`{"input": ids, "output": ids}`, filled by the deployer).
     This covers requests the client gave up on (timed out) that are still inside AK, so they don't finish during
     the next step.
     - SQS: `ApproximateNumberOfMessages` (waiting) **and** `ApproximateNumberOfMessagesNotVisible` (received by a
       worker, not yet deleted) are 0, on the input and output queues, **in every poll of the last 60 s** (decided
       2026-11-03, PR #877 review). Both counts are approximate (SQS has no exact count) and AWS says they may not be
       consistent until at least 1 minute after producers stop sending, so one poll reading 0 isn't enough: a message
       still being worked on (e.g. a timed-out request in a step that never scaled) can read 0 once. The rule assumes
       a message still waiting or being worked on reads non-zero in at least one poll within 60 s, so 60 s of zeros is
       taken as empty. It's not a hard guarantee, since both counts are approximate.
  3. **Workers back (primary fetcher):** the running count of every tier is back at its count at the end of the
     "before" part.
  - A condition with no source on a host counts as met.
  - **A read that fails or returns no value** (API error, missing permission, no datapoint) counts as **not met** for
    that poll and writes a run-log entry; the next poll checks again. If it never succeeds, the maximum cool-down
    ends the step. On SQS, such a poll breaks the 60 s run of zeros, so the 60 s start again. (Decided 2026-11-04, PR
    #893 review: before, a failed read could be mistaken for "no source" and end the step too early.)
  - Why all three: in a steady-traffic step that didn't scale, condition 3 is already true when the load stops, and
    the input queue is empty as soon as the last requests are picked up, while those requests are still being
    processed. Checking only 3 (or 3 + waiting messages) would end the step too early and mix its last responses into
    the next step.
  - The check calls the primary fetcher's plain `fetch()` (reads, stores nothing), whether it's live-tracked or not.
  - ECS: the primary fetcher (`aws.ecs_api`) reads the current state, so the end is seen within one poll.
  - Lambda: the primary fetcher (`aws.cloudwatch_metric.ConcurrentExecutions`) isn't live-tracked, but the check
    still calls its `fetch()` for the latest minutes, accepting the CloudWatch delay. Lambda sends no datapoint in a
    minute with no invocations (verified, see [Open points](#open-points)), so the fetcher reads a minute with no
    datapoint as 0 once it's older than its `metric_delay_s` constructor parameter (decided 2026-11-04, PR #893
    review; default set from the first Lambda runs). Newer minutes without a datapoint aren't returned yet (their data
    may still be on its way). A read of the latest minutes looks back far enough to get the latest known minute, so
    the step end is seen about `metric_delay_s` after the workers really scaled in, and the harness needs no
    Lambda-specific window; if the fetcher returns no value at all, that poll counts as not met. The parameter belongs
    to this AWS fetcher only, not to `ak-bench.yaml`. Lambda sends metric data to
    CloudWatch in 1-minute intervals. The recorded counts still come from its `fetch_and_store()` after the
    cool-down, which has the complete data. If the delay turns out too long,
    a person can bind `aws.lambda_log_streams` to the host in `hosts.py` instead (a manual choice, not automatic).
- **Maximum cool-down time:** configurable, **default 45 min**, counted from `t_load_down`. If it's reached, the step
  ends, records `cooldown_max_reached = true`, "scale-down done" stays empty and `workers_after_down` shows where it
  stopped. Why 45 min:
  - It's a safety net for a step that never gets back to the starting count, so it's set from the slowest host.
  - ECS is the slowest: target tracking starts scaling in only after 15 one-minute datapoints below target (~15 min),
    then waits `scale_in_cooldown` (our Terraform default 120 s) between scale-in activities, and target tracking
    removes capacity more conservatively than it adds it. So a normal ECS scale-in is expected to take ~15–25 min.
  - Lambda (concurrency drops when invocations stop) is expected to finish well within it.
  - 45 min leaves room for an ECS scale-in that takes several activities, without cutting it off and losing the
    scale-down result. Waiting too long only costs time; ending too early loses data.
  - Can be set per host (e.g. lower for Lambda) once real scale-in times are known.
- The steps are run one after another (steady N, then burst N, then the next N; the next starts only after the
  previous step's wait + fetch), so each step starts from the minimum workers.

### What to record (per time window, e.g. 1 s or 5 s)

Added to the per-time-window CSV, next to Tx/Rx/errors:

- **Desired workers:** what the autoscaler asked for.
- **Running workers:** what the platform says is running. On serverless hosts this is the number of instances that
  were handling work in the window (that's what their metrics and logs count).
- **Queue depth:** input and output queue backlog, each queue in its own column (SQS
  `ApproximateNumberOfMessages` waiting and `ApproximateNumberOfMessagesNotVisible` in flight).
- **Latency percentiles** (p0 / p25 / p50 / p75 / p99 / p100) of requests completed in that window.

Worker counts are recorded **per tier** and **per scaling info fetcher** (below). Which tiers scale depends on the host
(checked against our Terraform):

- **ECS:** only the agent runner autoscales (target tracking on `BacklogPerTask`). The REST/IO service runs a fixed
  `desired_count` (default 1) with no autoscaling, so its count is recorded but stays flat.
- **Lambda:** every function scales on its own: request handler, agent runner, response handler (and the WebSocket
  connection handler). Each is recorded as its own tier.

### Scaling info fetchers (pluggable)

Every host has more than one way to read its worker counts (a management API, a monitoring metric, the logs), with
different resolution and delay. Each way is a separate plugin, a **scaling info fetcher**: a subclass of one abstract
class, `ScalingInfoFetcher`, so a new way can be added for any host without touching the harness.

- **One fetcher = one way to read worker counts on one platform**, with a registry name (e.g. `aws.ecs_api`,
  `aws.cloudwatch_metric.ConcurrentExecutions`). A host lists one or more fetchers in `hosts.py`, and every bound fetcher runs. A
  fetcher can be written without being bound (e.g. `aws.lambda_log_streams`): it exists as a class but no step run
  uses it. There's no config switch for fetchers.
- **Same methods and parameters for every fetcher:**
  - `fetch(run, deployment, start, end) -> ScalingInfo`: the only method a subclass writes. It reads and stores
    nothing.
  - `store(...)`: written once in `ScalingInfoFetcher`; adds the result to the step's CSV files.
  - **No duplicate rows** (decided 2026-11-03, PR #877 review): before writing a row, `store()` checks whether a row
    with the same timestamp and key is already stored (resource usage: `ts, tier, worker, metric, stat, fetcher`;
    worker counts: `ts, tier, count type, fetcher`; spans: `tier, worker, fetcher`). If so, the new row replaces it
    instead of being added again. So re-running `collect-scaling` / `collect-resources` adds no duplicates, and late
    data (e.g. a Logs Insights window that got more events) updates that window's value.
  - `fetch_and_store(...)`: written once in `InfoFetcher`, the base class of every fetcher (see
    [Pluggable per-platform collectors](#pluggable-per-platform-collectors)); calls `fetch()`, then `store()`.
  - Constructor parameters: `live_track: bool = False`, and `poll_interval_s` (how often a live-tracked fetcher is
    polled; default from `ak-bench.yaml`, settable per fetcher, since sources differ: e.g. the ECS API has request
    rate limits).
- **`live_track` only sorts the fetchers into two groups.** The runner reads it before each step; nothing inside a
  fetcher depends on it. Data is available at different times, but the calls are the same:
  - **`live_track = True`:** management APIs (ECS, Azure Container Apps) only show the current state, so a
    background task calls `fetch_and_store` every `poll_interval_s` with (last poll, now), from the start of the
    step's "before" part until the cool-down ends. Each poll covers only the new time, so nothing is stored twice.
  - **`live_track = False`:** monitoring metrics and logs keep history but arrive late, so `fetch_and_store` is
    called once per step with (step start, step end), after the cool-down and a configured wait for log ingestion
    (default 1 min). It can be re-run later with `collect-scaling --run-id …`, which refills the CSVs (no duplicates, see `store()` above) and re-plots.
  - **The host bundle always sets `live_track`** for each of its fetchers: a source with no history must be `True`.
    The `False` default is never relied on.
- **Not split by serverless / containerized:** the harness never checks what kind of host it is. A host is only ever
  one kind, the line between them is blurry (Fargate, Cloud Run, Azure Container Apps), and the fetching code depends
  on where the data comes from, not on the deployment type.
- **Common return type (`ScalingInfo`):** every fetcher returns the same data, so the shared code never knows where it
  came from:
  - **Count samples:** `(ts, tier, count type, value)`, count type = desired / running.
  - **Worker spans** (optional, from fetchers that see individual workers): `(tier, worker, started, stopped)`, plus
    extra fields where useful (e.g. ECS `pullStartedAt`). The shared code turns spans into a
    running count at any window size, so these give exact times, not just poll-interval resolution.
- **Which resources to watch:** a fetcher gets the per-tier resource ids from the deployer's `Deployment.resources`
  (ECS cluster and service names, Lambda function names, ...), so it needs no extra config.
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
- **Primary fetcher:** the first fetcher in the host's list in `hosts.py`. The end-of-step check uses it. The
  summary CSV records which fetcher each number came from.
- **Reuse across platforms:** generic fetchers take constructor parameters instead of being rewritten, e.g. one cloud
  metric fetcher per monitoring backend (CloudWatch, Cloud Monitoring, Azure Monitor) given the metric name, and one
  "distinct instance ids in the logs" fetcher per log backend given the id field. The log-based ones share the log
  fetching code with the TraceCollector for the same backend.
- **A count with no fetcher** on a platform (e.g. `desired` on Lambda) stays empty.

Class sketch and a worked example: to be specified in the implementation spec (written after this design is approved).

Fetchers per host (✓ = available now, later = when the platform is added), primary first:

| Host | Fetcher | `live_track` | Gives | Resolution |
|------|---------|--------|-------|------------|
| ECS ✓ | `aws.ecs_api`: `DescribeServices` (`desiredCount`, `runningCount`) + `DescribeTasks` (task `createdAt` / `pullStartedAt` / `startedAt` / `stoppedAt`) | yes | desired, running, spans | poll interval; spans exact |
| ECS ✓ | `aws.ecs_scaling_activities`: Application Auto Scaling `DescribeScalingActivities` (`StartTime`, "Setting desired count to N") | no | desired | exact |
| Lambda ✓ | `aws.cloudwatch_metric.ConcurrentExecutions`: CloudWatch `AWS/Lambda` metric per function (`FunctionName` dimension), `Maximum` statistic | no | running | 1 min |
| Lambda (written, not bound to the host) | `aws.lambda_log_streams`: one span per log stream (= per execution environment), from its first to its last `REPORT` line | no | running, spans | exact to about one invocation |
| Azure Container Apps (later) | `azure.aca_replicas_api`: List Replicas (`createdTime`, `runningState`) | yes | running, spans | poll interval |
| Azure Container Apps (later) | `azure.monitor_metric.Replicas` (split by revision only) | no | running | 1 min |
| Cloud Run (later) | `gcp.logging_instance_ids`: distinct `labels.instanceId` in Cloud Logging | no | running | any window size |
| Cloud Run (later) | `gcp.monitoring_metric.instance_count` (state active / idle) | no | running | not verified |
| Azure Functions Flex (later) | `azure.app_insights_instances`: `dcount(cloud_RoleInstance)` per window | no | running | any window size |
| Azure Functions Flex (later) | `azure.monitor_metric`: instance count (emitted every 30 s) | no | running | 30 s |

- Only ECS exposes a **desired** count. Lambda, Cloud Run and Azure Functions have none, and Azure Container Apps
  doesn't expose one.
- **Lambda: only `aws.cloudwatch_metric.ConcurrentExecutions` is bound to the host.** `aws.lambda_log_streams` is
  written too but not bound; see [Lambda: `ConcurrentExecutions` bound, log streams written but not bound](#lambda-concurrentexecutions-bound-log-streams-written-but-not-bound) below.
  - `ConcurrentExecutions` is "the number of active concurrent invocations at a given point in time". Lambda emits it
    for all functions, versions and aliases (no reserved concurrency needed), at 1-minute granularity, and AWS says to
    read it with the `Maximum` statistic.
  - One `GetMetricData` call per step (after the cool-down and wait, over (step start, step end)), one query per
    function (tier), period 60 s; plus the end-of-step check's plain `fetch()` calls during the cool-down.
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
  visible in `DescribeTasks` for at least 1 hour after they stop. Live tracking through every step catches all of them.
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

The times above and the worker counts below are computed per tier and per scaling info fetcher. On Lambda
(`aws.cloudwatch_metric.ConcurrentExecutions`) the `workers_*` counts are concurrent invocations, not execution
environments.

Worker counts (from → to), recorded per tier, count type (desired / running) and fetcher, next to the times:

| Number                 | Scale up                                                  | Scale down                                           |
|------------------------|-----------------------------------------------------------|------------------------------------------------------|
| **From**               | `workers_before_up`: count at `t_load_up` (end of baseline) | `workers_before_down`: count at `t_load_down`        |
| **To**                 | `workers_peak`: highest count in the step                 | `workers_after_down`: count at the end of the cool-down      |
| **Change**             | `peak − before_up` workers added                          | `before_down − after_down` workers removed           |
| **Rate**               | workers added ÷ (scale-up done − `t_load_up`), as workers/min | workers removed ÷ (scale-down done − `t_load_down`), as workers/min |

- So each scaling result reads like "ECS runner: 2 → 18 tasks in 7.5 min (first new task at 4 min, ~2.1 tasks/min);
  18 → 2 in 21 min (~0.8 tasks/min)".
- **The rate is an average from the load change to the end of the scaling** (decided 2026-11-03, PR #877 review):
  scale up from `t_load_up` (the step's first send) to scale-up done, scale down from `t_load_down` (end of the load)
  to scale-down done. It is **not** the 1 s / 5 s time windows of the per-time-window CSV.
  - It includes the time before the platform reacts; that part is also recorded on its own (decision delay, first
    new worker).
  - It can't divide by 0: scaling always finishes after the load change. (Measuring from the first new worker could:
    on Lambda both times can fall in the same minute.)
  - Example above: 16 tasks added, scale-up done 7.5 min after the first send, so 16 ÷ 7.5 min ≈ 2.1 tasks/min.
  - A step that didn't scale has no scale-up / scale-down done time, so its rate stays empty.
- **A time read from a 1-minute value counts at the end of that minute** (Lambda's `ConcurrentExecutions`):
  CloudWatch labels each value with the start of its minute, but the count could have been reached at any moment in
  that minute. So "10:01 → 61 workers" means "61 reached by 10:02:00". This applies to every time read from such a
  value (first new worker, scale-up done, scale-down start / done). Otherwise scale-up could look finished at the same
  moment as the first send. ECS counts come from live polls with exact times and need no such rule.
  - Platforms don't add workers evenly. They add them in steps, e.g. ECS goes 2 → 8 at minute 4, waits out the
    scale-out cooldown, then goes 8 → 18. The rate smooths these steps into one number, which hides the shape.
  - The step pattern itself is seen in the worker-count graph, not in this number. What sets the steps:
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
    and `batch_size × maximum agent delay` has to stay under it: 10 × the default 5 s maximum delay is 50 s. So the
    benchmark deployer sets the agent runner timeout to **60 s** (decided 2026-11-04, PR #893 review). The input queue
    visibility timeout stays at AK's default 60 s: Lambda rejects a function timeout above it, and AK's Terraform checks
    visibility ≥ timeout (`ak-aws/serverless/state.tf`). AWS recommends a visibility timeout of at least 6× the
    function timeout; that isn't applied. Batch size, timeout and the minimum and maximum agent delay are saved in the
    run metadata.
  - So the number of concurrent executions is much lower than the number of requests: each
    environment handles a batch of messages, then the next batch. Example: 1000 requests at once, 2 s each, batch
    size 10, default mode: 5 invocations at first, +300 per minute (~5 per second), so all 100 batches are picked up
    after ~20 s by ~100 environments, and the last ones finish ~20 s later. That's a `ConcurrentExecutions` peak of
    roughly 100, not 1000 (rough estimate, not measured).

All autoscaling settings for the run (returned by the Deployer's `deployed_settings()`) are saved in the run metadata so the times can be explained later: min/max,
target, cooldowns, Lambda ESM mode / max concurrency, and the worker size (task vCPU/memory, Lambda memory).

### Graphs

- Worker count over time (desired / running, one line per scaling info fetcher) with the start and end of the step's
  load marked.
- Latency percentiles per window and queue depth over time on the same time axis.
- Tx/Rx over time across the whole step.

## Cost

What a run **actually cost**, read from the cloud's bill, for the whole run.

### How the cost code is split

- **Billing reader:** one per cloud (AWS: Cost Explorer). Returns `None` where a platform has no bill, and the
  cost columns stay blank.
- **Shared code:** writes the cost CSV and draws the cost graph. It never calls a cloud API.
- Adding a cloud = its billing reader.

### Billed cost of each run

**Tag everything.** Every resource the runner deploys gets a `ak-bench-run-id` tag (Terraform `default_tags`).
The billed cost is AWS Cost Explorer `GetCostAndUsage` filtered by the run tag, grouped by service.

- **One tag value per host × execution mode** (decided 2026-11-04, PR #893 review): `<run-id>-<host>-<mode>`, e.g.
  `<run-id>-lambda-async`. Each host × mode has its own deployment, so its `cost.csv` holds only that deployment's
  bill, never another host's or mode's.

- **Metric: `UnblendedCost`** (decided 2026-11-02): the usage at the rate AWS charged, **without discounts and
  credits** (Cost Explorer shows those as their own line items; the after-discount view is `NetUnblendedCost`, not
  used). The metric name is recorded with the run's billed cost.
- **AWS's own billing rules are already in it** (e.g. Fargate's per-second billing with a 1-minute minimum, SQS
  billing per API request including empty receives), so the benchmark doesn't model them.
- **The whole run only, never per step.** The tag is set once, at deploy time, and one deployment serves every step of
  both test types (1 → 10 → 100 → 1000), so every charge of that host × mode carries the same tag value and Cost
  Explorer can't tell the steps apart. Its time grain (daily, or hourly) can't separate them either: steps are
  minutes long and run back to back. The total covers set-up, every step, the waits after the steps and the time until tear-down.
- The tag must be activated as a cost allocation tag (management account). Tagged costs show from activation on; the
  management account can **backfill** up to 12 months (one backfill request per 24 h). Costs only appear for periods
  when the tag was actually on the resource.
- Cost Explorer refreshes at least once every 24 h (some data can arrive later), so this is a **separate, later step**
  (`collect-cost --run-id …`) that fills in the cost CSV after the run. It fits the existing "re-plot from existing
  CSVs" option. Each Cost Explorer API request costs $0.01.
- **Daily granularity** (decided 2026-10-29): every host × mode of every run has its own tag value, so its billed cost
  is the sum of the daily rows for that value over the days the run covered (two days if it crosses midnight).
  Hourly isn't used.
- Shared or long-lived resources (e.g. a NAT gateway) can be tagged, but if they're shared across runs or used by
  other things, their cost must be listed as a fixed allocation instead.
- **Output:** `cost.csv` per host × mode: the billed cost per service and in total, the metric name and the dates
  covered.
- With the mock agent, the cost covers **AK infrastructure only**; LLM token costs are excluded.

### Graphs

- Billed cost per run, by service (drawn by `collect-cost`, once the bill is available).

## Open points

- Load-step tests, Lambda end detection: **verified 2026-11-04 (PR #893 review), `ConcurrentExecutions` has no
  datapoint in a minute with no invocations**, never a 0. AWS's docs don't say this for `ConcurrentExecutions`; it was
  checked on the deployed `aws-serverless/openai` example's agent runner (us-east-2): over 15 days of 1-minute data
  (`Maximum`, 60 s), there were 29 datapoints, all in minutes that also had `Invocations`, and no 0 values. So a
  missing minute is read as 0, but only for minutes older than the fetcher's `metric_delay_s` (decided 2026-11-04,
  see [Load-step tests](#load-step-tests-scaling-per-step)). The delay's default is still to be measured on the first
  Lambda runs.
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
- Whether the 1-min default wait before the after-cool-down fetch (`live_track = False` fetchers) is enough for each
  log backend (log ingestion delay differs per backend). Checked on the first runs.

## Sources (checked 2026-10-20; GCP / Azure scaling fetchers checked 2026-10-22; Lambda metrics checked 2026-10-23)

- Horizontal vs. vertical scaling terms: https://wa.aws.amazon.com/wellarchitected/2020-07-02T19-33-23/wat.concept.horizontal-scaling.en.html
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
- Cost Explorer pricing: https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/
- Cost Explorer `UnblendedCost` vs `NetUnblendedCost` (discounts as separate line items; net = after discounts), checked 2026-11-02: https://docs.aws.amazon.com/cost-management/latest/userguide/ce-advanced.html, https://docs.aws.amazon.com/cost-management/latest/userguide/ce-exploring-data.html
- SQS `GetQueueAttributes` (`ApproximateNumberOfMessages`, `ApproximateNumberOfMessagesNotVisible` = in flight, consistent only ≥ 1 min after producers stop): https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_GetQueueAttributes.html
- Fargate pricing: https://aws.amazon.com/fargate/pricing/
