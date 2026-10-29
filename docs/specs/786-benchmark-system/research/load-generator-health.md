# Research: Recording the Load Generator's Own Health (Review Issue 7)

Background research for review issue 7. **Decided 2026-10-26: not tracked.** The benchmark
records nothing about the client's own health. Kept for reference only; nothing here is a requirement. Researched 2026-10-26; sources linked inline.
"[local]" means measured on a dev box (Linux, Python 3.12, psutil 5.9.8), not taken from docs.

## The problem

- The load generator is one Python asyncio process. If it can't keep up (CPU, busy event loop), it sends late and
  stamps responses late. AK then looks slower than it is, and nothing in the results shows why.
- A busy event loop hurts both ends: sends go out after their scheduled time, and a response that has arrived is only
  stamped "received" when the loop gets to it. Artillery's old FAQ describes the same effect for Node: "latency
  reports will be skewed … by event loop lag"
  ([archived FAQ](https://web.archive.org/web/2021/https://artillery.io/docs/faq/)).

## What other load tools do

| Tool | What it watches | What it does with it |
|------|-----------------|----------------------|
| Locust | Own process CPU (`psutil` `Process.cpu_percent()`, every 10 s) and memory | Logs a warning once above 90 %; not written to its CSVs ([runners.py](https://github.com/locustio/locust/blob/master/locust/runners.py), [docs](https://docs.locust.io/en/stable/increase-performance.html)) |
| k6 | `dropped_iterations`: sends it couldn't start on time in open-load mode | Counts them as a metric; late sends are dropped, not sent late ([metrics](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/), [dropped iterations](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/)). Sizing guide: keep ≥ 20 % CPU idle, memory < 90 % ([large tests](https://grafana.com/docs/k6/latest/testing-guides/running-large-tests/)) |
| Gatling Enterprise | Per-generator CPU, memory, TCP open/connect counts and times, TLS handshake times | Exported as time-series metrics; optional stop criterion on mean CPU ([OTel](https://docs.gatling.io/integrations/observability-tools/otel/)) |
| wrk2 | Intended send time vs. actual send time | Measures latency from the *intended* time; keeps the uncorrected one too (`--u_latency`) ([wrk2](https://github.com/giltene/wrk2)) |
| Artillery (v1) | Own CPU | Printed a warning above 80 %; no longer in the current code ([archived FAQ](https://web.archive.org/web/2021/https://artillery.io/docs/faq/)) |
| Tsung | CPU, load average, free memory per host | Written as stats every 10 s ([reports](http://tsung.erlang-projects.org/user_manual/reports.html)) |

Takeaways:

- Everyone samples their **own process CPU** every 1–10 s. Warning lines sit at 80–90 %. We record the number and
  draw it; we don't warn (record-and-report rule).
- The open-load shortfall (k6's dropped iterations, wrk2's intended vs. actual) is the most direct signal. We already
  store **scheduled send time** and **sent time** per request, so we get it without extra measuring.
- Latency from the scheduled time (wrk2's "corrected" view) and from the sent time can both be worked out from the
  per-request CSV after the run. No correction at recording time.

## Measuring event-loop lag

- **Method (used by aiodebug, loopmon, Node's `monitorEventLoopDelay`):** a small task on the loop sleeps a fixed
  interval and records how much later than asked it woke up: `lag = loop.time() - t0 - interval`
  ([aiodebug](https://gitlab.com/quantlane/libs/aiodebug), [loopmon](https://github.com/isac322/loopmon),
  [Node perf_hooks](https://nodejs.org/api/perf_hooks.html)).
- **Interval:** Node 10 ms, loopmon 100 ms, aiodebug 250 ms. A 1 s probe would miss most stalls shorter than the
  window, so probe every **10 ms** and write **max / avg / sample count** per 1 s window.
- **Floor:** on Linux the epoll timeout is rounded up to whole ms (CPython `Lib/selectors.py`). [local] An idle loop
  shows about 0.3–0.5 ms lag. Record the raw value; don't subtract a baseline.
- **Cost:** one timer and one wake-up per probe; negligible at 100 Hz.
- The probe **must run on the loop**, because the loop is what it measures.
- asyncio debug mode (`PYTHONASYNCIODEBUG=1`, logs callbacks slower than 100 ms) is a diagnostic, not a metric; don't
  use it in benchmark runs ([asyncio-dev](https://docs.python.org/3/library/asyncio-dev.html)).
- Use: per window, `loop_lag_max` is an upper bound on how late any receive stamp in that window could be.

## Process and host metrics

- **psutil** ([docs](https://psutil.readthedocs.io/)):
  - `Process.cpu_percent()`: 100 = one full core. A Python process can't use much more than one core (GIL), so this
    is the number that saturates. System-wide CPU on an 8-vCPU box would only show about 12.5 % at that point.
  - The first call returns a meaningless 0.0; call once at start and discard it.
  - `memory_info().rss`, `num_fds()`, `num_ctx_switches()` (involuntary = pre-empted), `num_threads()`.
  - `net_io_counters()`: host/NIC counters (bytes, drops), not per process; take the difference per window.
  - `oneshot()` reads several values cheaply. [local] A full sample took about 0.35 ms, so 1 Hz costs < 0.1 % of a
    core.
  - Don't call `net_connections()` every second ([local] about 24 ms, and it grows with the connection count).
- **In a container** (ECS, Fargate, K8s): psutil shows the host's CPUs, not the container's limit. Read cgroup v2
  `/sys/fs/cgroup/cpu.stat`: `nr_throttled` and `throttled_usec` show directly when the generator was CPU-starved
  ([cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html),
  [CFS bandwidth](https://docs.kernel.org/scheduler/sched-bwc.html)).
- **TCP retransmits:** `RetransSegs` in `/proc/net/snmp`, host-wide; take the difference per window ([local] about
  0.04 ms to read).
- **GC pauses:** `gc.callbacks` gets "start" / "stop" calls; sum the pause time per window
  ([gc](https://docs.python.org/3/library/gc.html)). Cheap.
- **Sample from a separate thread.** If the sampler ran on the event loop, a stalled loop would also delay the sample
  and stretch its window. A daemon thread waking on fixed 1 s deadlines keeps the windows right. It still needs the GIL
  (switch interval 5 ms, can be longer), so record its own wake-up delay too
  ([sys.getswitchinterval](https://docs.python.org/3/library/sys.html)).

## Timestamps and clocks

- `time.monotonic()` / `monotonic_ns()` never goes backwards; `time.time()` can jump if the clock is set
  ([time](https://docs.python.org/3/library/time.html)). Since Python 3.13, `perf_counter()` uses the same clock as
  `monotonic()`.
- Take every in-process time (scheduled, sent, received, lag) with `time.monotonic_ns()`.
- To join with AK's log timestamps, convert to wall-clock time with an anchor pair taken at run start
  (`wall = anchor_wall + (mono - anchor_mono)`). Re-take the pair every window and record the difference, so a clock
  step or slew is visible without the benchmark acting on it.
- CloudWatch log timestamps are milliseconds since the epoch, and Logs Insights `@timestamp` is the event time, not
  the ingestion time ([InputLogEvent](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_InputLogEvent.html),
  [discoverable fields](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_AnalyzeLogData-discoverable-fields.html)),
  so the client↔AK join is at ms resolution at best.
- **Clock sync on EC2:** Amazon Time Sync Service at `169.254.169.123`, used by default on Amazon Linux 2023. AWS's
  `chronyc tracking` example shows µs-level offsets ([EC2 NTP](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-ec2-ntp.html)).
  Saving `chronyc tracking` (system time offset, root dispersion) at run start and end records how good the sync was.
  No documented accuracy figure was found for Lambda / Fargate clocks (not verified).

## How far one process goes, and when to use more

- **Single-connection ceiling** ([websocket-benchmark](https://github.com/tarasko/websocket-benchmark), loopback echo,
  one connection, round trips/s): `websockets` 17.1 about 23k (asyncio) / 25k (uvloop) at 256 B; about 16k over TLS.
  aiohttp is faster (about 36k / 41k). No published figure was found for thousands of concurrent connections in one
  process (not verified). Our load (1000 clients at a few requests/s each) is far below these numbers, but the
  measurements above are what show whether it holds.
- **uvloop:** "2-4x faster" on raw echo ([uvloop](https://github.com/MagicStack/uvloop)), but only about 5–15 % in the
  WebSocket benchmark, since frame parsing in Python dominates.
- **Memory:** `websockets` uses about 64 KiB per connection by default, 14 KiB without compression
  ([memory](https://websockets.readthedocs.io/en/stable/topics/memory.html)); about 64 MB for 1000 clients.
- **When to scale out:** Locust recommends one process per CPU core
  ([distributed](https://docs.locust.io/en/stable/running-distributed.html)). The data above (process CPU near 100 %,
  loop lag growing with load) is what shows it's needed.
- **Merging results from several processes or machines:** Locust workers send stats to a master every 3 s; k6 splits
  the load into execution segments and each instance has to be aggregated
  ([k6 distributed](https://grafana.com/docs/k6/latest/testing-guides/running-distributed-tests/)). For us: each
  worker writes its own per-request rows with a `worker_id`. Throughput and latency are rebuilt from the raw rows
  (never averages of averages). Health rows stay per worker; CPU and lag are never summed.

## OS and machine limits

- **Open files:** each socket is a file descriptor. Many distros default the soft `ulimit -n` to 1024; a process can
  raise its soft limit up to the hard limit ([resource](https://docs.python.org/3/library/resource.html)).
- **Ephemeral ports:** default range 32768–60999, about 28k ports
  ([ip-sysctl](https://docs.kernel.org/networking/ip-sysctl.html)), so about 28k connections per source IP to one
  destination IP and port ([Cloudflare](https://blog.cloudflare.com/how-to-stop-running-out-of-ephemeral-ports-and-start-to-love-long-lived-connections/)).
  Not an issue at 1000 clients.
- **EC2 network:** instances of 4xlarge and smaller have "up to" bandwidth and burst on credits, typically for 5 to
  60 minutes, then drop to baseline (e.g. c5.large: 0.75 Gbps baseline vs. "up to 10")
  ([EC2 bandwidth](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html)). A long
  steady step on a small instance can hit that drop partway through.
- **ENA counters:** `ethtool -S` shows `bw_in/out_allowance_exceeded`, `pps_allowance_exceeded`,
  `conntrack_allowance_exceeded` ([ENA monitoring](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/monitoring-network-performance-ena.html)).
  A snapshot at run start and end is enough.
- **Burstable (T) instances:** in standard mode, once CPU credits run out the instance drops to its baseline (e.g.
  t3.large: 30 % per vCPU) ([burstable credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)).
  This silently caps the generator's CPU mid-run.
- **Same region / AZ as the target:** general practice so the client→front-door network time is small and steady. No
  explicit AWS load-testing guidance found (not verified).
- **AWS's own solution:** [Distributed Load Testing on AWS](https://docs.aws.amazon.com/solutions/latest/distributed-load-testing-on-aws/solution-overview.html)
  runs JMeter / k6 / Locust on ECS Fargate across regions. Its per-task limits weren't found (not verified).

## Recommended design (record and report only)

### Per-request CSV: additions

- `worker_id`: which generator process sent it (needed once there's more than one).
- `send_delay` = sent − scheduled send time.
- `latency_from_scheduled` = complete − scheduled send time, next to the existing `latency` (from sent).
- Raw times stay as they are (scheduled, sent, first chunk, complete), taken with `monotonic_ns` and written as epoch
  time through the anchor.

### Per-time-window CSV: new `gen_` columns

| Group | Columns | Source |
|-------|---------|--------|
| Sending | `gen_sends_due`, `gen_send_backlog` (due but not yet sent at window end), `gen_send_delay_max` / `_avg`, `gen_in_flight` | worked out from the per-request rows when the CSV is written |
| Event loop | `gen_loop_lag_max` / `_avg` / `_samples`, `gen_loop_tasks` | 10 ms probe on the loop |
| Process | `gen_proc_cpu_pct` (100 = one core), `gen_proc_rss_mb`, `gen_proc_fds`, `gen_proc_ctx_invol` | psutil, sampler thread |
| GC | `gen_gc_pause_ms`, `gen_gc_count` | `gc.callbacks` |
| Host | `gen_host_cpu_pct`, `gen_host_cpu_pct_max_core`, `gen_host_mem_pct`, `gen_net_bytes_sent` / `_recv`, `gen_net_drops`, `gen_tcp_retrans` | psutil, `/proc/net/snmp` |
| Container (empty outside one) | `gen_cgroup_throttled_count`, `gen_cgroup_throttled_ms` | cgroup `cpu.stat` |
| Clock | `gen_wall_minus_mono` | anchor pair |
| Sampler | `gen_sampler_wake_delay` | sampler thread |

WebSocket connection counts for the window are covered by issue 8 (later work).

### Run metadata: once per run

- Instance type, region and AZ, vCPUs and usable CPUs (CPU affinity, cgroup quota), `ulimit -n`, ephemeral port
  range.
- Python, `websockets` and uvloop versions.
- `chronyc tracking` at start and end; `ethtool -S` allowance counters at start and end (EC2 only).

### Graph

- Load generator panels on each step's `03-timeline.png`: `gen_proc_cpu_pct`, `gen_loop_lag_max` and `gen_send_delay_max`
  on the same time axis as Tx/Rx and latency. No limit lines.

### Left out of phase 1

- asyncio debug mode / slow-callback logging, per-socket `ss` / `net_connections`, kernel receive timestamps,
  coordinated-omission correction at recording time (the raw columns already allow it later).
